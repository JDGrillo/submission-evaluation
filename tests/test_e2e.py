from __future__ import annotations

from pathlib import Path
from threading import Event, Lock
import re
import time
from typing import Any

from openpyxl import Workbook
from pypdf import PdfReader
import pytest

from submission_evaluation.agents.analysis import AnalysisAgent
from submission_evaluation.agents.base import AgentResult
from submission_evaluation.agents.ingestion import ExtractedLocationCandidate, IngestionAgent
from submission_evaluation.agents.orchestrator import OrchestratorAgent
from submission_evaluation.agents.report import ReportAgent
from submission_evaluation.agents.research import ResearchAgent
from submission_evaluation.agents.validation import ValidationAgent
from submission_evaluation.config import AppConfig
from submission_evaluation.agents import ingestion as ingestion_module
from submission_evaluation.pipeline import SubmissionPipelineMonitor


def _write_xlsx(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Locations"
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _location_rows(count: int) -> list[list[object]]:
    rows: list[list[object]] = [["Location", "Address", "City", "State", "Zip", "Flood Zone"]]
    for idx in range(1, count + 1):
        rows.append([f"Site {idx}", f"{idx} Main St", "Austin", "TX", f"78{idx:03d}", "X"])
    return rows


def _build_config(*, input_dir: Path, output_dir: Path) -> AppConfig:
    return AppConfig(
        input_dir=input_dir,
        processed_dir=input_dir / "processed",
        output_dir=output_dir,
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        azure_openai_api_version="2024-06-01",
        web_search_endpoint="",
        web_search_api_key="",
    )


class _StaticSearchClient:
    def __init__(self, *, empty_query_token: str | None = None) -> None:
        self._empty_query_token = empty_query_token

    def search_web(self, query: str, *, count: int = 5):
        del count
        if self._empty_query_token and self._empty_query_token in query:
            return []
        return [{"name": "result", "url": "https://example.com/source", "snippet": "public data"}]


class _StubPdfExtractor:
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self._candidates = candidates

    def extract_location_candidates(self, _text: str):
        return [
            ExtractedLocationCandidate(
                location_name=candidate.get("location_name"),
                address_line_1=candidate.get("address_line_1"),
                city=candidate.get("city"),
                state=candidate.get("state"),
                postal_code=candidate.get("postal_code"),
                country=candidate.get("country"),
                confidence=float(candidate.get("confidence", 0.9)),
                supplementary_text=candidate.get("supplementary_text"),
                extraction_method="stub",
            )
            for candidate in self._candidates
        ]


def _build_orchestrator(
    *,
    input_dir: Path,
    output_dir: Path,
    web_search_client: Any | None = None,
    ingestion_agent: IngestionAgent | None = None,
    analysis_agent: AnalysisAgent | None = None,
    report_agent: ReportAgent | None = None,
    retries: int = 3,
) -> OrchestratorAgent:
    config = _build_config(input_dir=input_dir, output_dir=output_dir)
    return OrchestratorAgent(
        ingestion=ingestion_agent or IngestionAgent(config=config),
        research=ResearchAgent(config=config, web_search_client=web_search_client or _StaticSearchClient()),
        analysis=analysis_agent or AnalysisAgent(),
        report=report_agent or ReportAgent(config=config),
        validation=ValidationAgent(),
        retries=retries,
    )


def _read_report_text(report_path: Path) -> str:
    if report_path.suffix.lower() == ".pdf":
        reader = PdfReader(str(report_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return report_path.read_text(encoding="utf-8")


def _assert_rendered_location_sections(*, report_text: str, location_ids: list[str]) -> None:
    headings = re.findall(r"Location\s+loc-[^:\n]+:", report_text)
    assert len(headings) == len(location_ids)
    for location_id in location_ids:
        assert report_text.count(f"Location {location_id}:") == 1


@pytest.mark.parametrize("location_count", [5, 10, 50, 100])
def test_e2e_when_excel_submission_processed_should_emit_exact_location_count(
    tmp_path: Path,
    location_count: int,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / f"submission-{location_count}.xlsx"
    _write_xlsx(workbook_path, _location_rows(location_count))

    orchestrator = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)
    result = orchestrator.invoke(
        {
            "submission_id": f"sub-e2e-{location_count}",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "ok"
    assert result["report_emitted"] is True
    report_stage = result["stage_state"]["stage_outputs"]["report"]
    assert report_stage["location_count"] == location_count
    assert len(report_stage["report_locations"]) == location_count
    report_path = Path(str(report_stage["report_path"]))
    rendered = _read_report_text(report_path)
    _assert_rendered_location_sections(
        report_text=rendered,
        location_ids=[str(location_id) for location_id in report_stage["report_location_ids"]],
    )


def test_e2e_when_excel_and_pdf_supplied_should_merge_and_dedupe_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission.xlsx"
    pdf_path = input_dir / "supplement.pdf"
    _write_xlsx(
        workbook_path,
        [
            ["Location", "Address", "City", "State", "Zip"],
            ["Site 1", "1 Main St", "Austin", "TX", "78701"],
            ["Site 2", "2 Main St", "Austin", "TX", "78702"],
        ],
    )
    pdf_path.write_bytes(b"%PDF-1.4 placeholder")

    monkeypatch.setattr(ingestion_module, "_extract_pdf_text_from_file", lambda _p: "pdf text")
    ingestion_agent = IngestionAgent(
        config=_build_config(input_dir=input_dir, output_dir=output_dir),
        pdf_location_extractor=_StubPdfExtractor(
            [
                {
                    "location_name": "Duplicate Site 1",
                    "address_line_1": "1 Main St",
                    "city": "Austin",
                    "state": "TX",
                    "postal_code": "78701",
                },
                {
                    "location_name": "Site 3",
                    "address_line_1": "3 Main St",
                    "city": "Austin",
                    "state": "TX",
                    "postal_code": "78703",
                },
            ]
        ),
    )
    orchestrator = _build_orchestrator(
        input_dir=input_dir,
        output_dir=output_dir,
        ingestion_agent=ingestion_agent,
    )

    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-merge",
            "input_files": [str(workbook_path), str(pdf_path)],
        }
    )

    assert result["status"] == "ok"
    report_stage = result["stage_state"]["stage_outputs"]["report"]
    assert report_stage["location_count"] == 3
    assert len(report_stage["report_locations"]) == 3


def test_e2e_when_corrupt_file_present_should_still_emit_report_for_valid_files(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    good_path = input_dir / "good.xlsx"
    bad_path = input_dir / "corrupt.xlsx"
    _write_xlsx(good_path, _location_rows(2))
    bad_path.write_text("not-a-real-xlsx", encoding="utf-8")

    orchestrator = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)
    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-corrupt",
            "input_files": [str(good_path), str(bad_path)],
        }
    )

    assert result["status"] == "ok"
    ingestion_stage = result["stage_state"]["stage_outputs"]["ingestion"]
    assert ingestion_stage["location_count"] == 2
    assert any("corrupt.xlsx" in warning for warning in ingestion_stage["warnings"])


def test_e2e_when_single_location_research_fails_should_flag_without_dropping_location(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission.xlsx"
    _write_xlsx(workbook_path, _location_rows(2))

    orchestrator = _build_orchestrator(
        input_dir=input_dir,
        output_dir=output_dir,
        web_search_client=_StaticSearchClient(empty_query_token="2 Main St"),
    )
    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-webfail",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "ok"
    report_stage = result["stage_state"]["stage_outputs"]["report"]
    assert report_stage["location_count"] == 2
    no_source_sections = [
        section for section in report_stage["report_locations"] if section["citations"] == ["No public source available"]
    ]
    assert len(no_source_sections) >= 1


@pytest.mark.parametrize(
    ("location_count", "threshold_seconds"),
    [(10, 300.0), (50, 900.0)],
)
def test_e2e_when_processing_submissions_should_complete_within_performance_budget(
    tmp_path: Path,
    location_count: int,
    threshold_seconds: float,
):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / f"perf-{location_count}.xlsx"
    _write_xlsx(workbook_path, _location_rows(location_count))

    orchestrator = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)

    start = time.perf_counter()
    result = orchestrator.invoke(
        {
            "submission_id": f"sub-e2e-perf-{location_count}",
            "input_files": [str(workbook_path)],
        }
    )
    elapsed = time.perf_counter() - start

    assert result["status"] == "ok"
    assert elapsed < threshold_seconds


def test_e2e_when_analysis_timeout_occurs_should_retry_and_recover(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission.xlsx"
    _write_xlsx(workbook_path, _location_rows(3))

    state = {"attempts": 0}

    class _FlakyAnalysis(AnalysisAgent):
        def invoke(self, payload):
            state["attempts"] += 1
            if state["attempts"] == 1:
                return AgentResult(
                    agent="analysis",
                    status="failed",
                    payload={
                        "received": payload,
                        "message": "analysis model timeout",
                        "reason_codes": ["analysis_timeout"],
                    },
                )
            return super().invoke(payload)

    orchestrator = _build_orchestrator(
        input_dir=input_dir,
        output_dir=output_dir,
        analysis_agent=_FlakyAnalysis(),
        retries=3,
    )

    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-retry",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "ok"
    assert result["report_emitted"] is True
    assert state["attempts"] == 2


def test_e2e_when_pipeline_succeeds_should_emit_audit_appendix_with_pass_status(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission.xlsx"
    _write_xlsx(workbook_path, _location_rows(5))

    orchestrator = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)
    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-audit-pass",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "ok"
    report_stage = result["stage_state"]["stage_outputs"]["report"]
    assert report_stage["location_count"] == 5
    report_path = Path(result["stage_state"]["stage_outputs"]["report"]["report_path"])
    report_text = _read_report_text(report_path)
    assert "Validation Status: PASS" in report_text
    assert "Location Counts: expected=5 reported=5" in report_text


def test_e2e_when_pipeline_succeeds_should_include_source_traceability_for_risk_scores(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission-traceability.xlsx"
    _write_xlsx(workbook_path, _location_rows(3))

    orchestrator = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)
    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-traceability",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "ok"
    report_stage = result["stage_state"]["stage_outputs"]["report"]
    report_path = Path(str(report_stage["report_path"]))
    report_text = _read_report_text(report_path)

    for section in report_stage["report_locations"]:
        assert section["overall_score"] != "N/A"
        assert section["category_scores"]
        assert section["citations"]
        assert "No public source available" not in section["citations"]
        for citation in section["citations"]:
            assert citation in report_text


def test_e2e_when_report_contains_fabricated_address_should_fail_validation_and_not_emit_artifact(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    workbook_path = input_dir / "submission-fabricated.xlsx"
    _write_xlsx(workbook_path, _location_rows(2))
    config = _build_config(input_dir=input_dir, output_dir=output_dir)

    class _FabricatingReportAgent(ReportAgent):
        def _build_report_locations(self, *, payload, manifest):
            sections = super()._build_report_locations(payload=payload, manifest=manifest)
            for section in sections:
                section["address_line_1"] = "999 Fake Ave"
            return sections

    orchestrator = _build_orchestrator(
        input_dir=input_dir,
        output_dir=output_dir,
        report_agent=_FabricatingReportAgent(config=config),
        retries=1,
    )
    result = orchestrator.invoke(
        {
            "submission_id": "sub-e2e-fabricated-address",
            "input_files": [str(workbook_path)],
        }
    )

    assert result["status"] == "failed"
    assert result["failed_stage"] == "report"
    assert result["report_emitted"] is False
    assert not output_dir.exists()


def test_e2e_when_two_submissions_arrive_simultaneously_should_both_complete_independently(
    tmp_path: Path,
):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    first_file = input_dir / "batch-a.xlsx"
    _write_xlsx(first_file, _location_rows(5))

    call_started = Event()
    release_first = Event()
    lock = Lock()
    invocation_index = {"value": 0}
    coordination = {"first_release_observed": False}

    class _BlockingOrchestrator:
        def __init__(self) -> None:
            self._delegate = _build_orchestrator(input_dir=input_dir, output_dir=output_dir)

        def invoke(self, payload):
            with lock:
                invocation_index["value"] += 1
                current = invocation_index["value"]
            if current == 1:
                call_started.set()
                coordination["first_release_observed"] = release_first.wait(timeout=5)
            return self._delegate.invoke(payload)

    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=_BlockingOrchestrator,
        max_workers=2,
    )

    try:
        monitor.run_once(wait=False)
        assert call_started.wait(timeout=3)

        second_file = input_dir / "batch-b.xlsx"
        _write_xlsx(second_file, _location_rows(10))
        monitor.run_once(wait=False)

        release_first.set()
        results = monitor.collect_finished(wait=True)
    finally:
        monitor.shutdown()

    assert len(results) == 2
    assert coordination["first_release_observed"] is True
    statuses = [entry["result"]["status"] for entry in results]
    assert statuses == ["ok", "ok"]
    assert all(entry["result"]["report_emitted"] is True for entry in results)
    counts = {
        entry["result"]["stage_state"]["stage_outputs"]["report"]["location_count"]
        for entry in results
    }
    assert counts == {5, 10}
    report_paths = {
        entry["result"]["stage_state"]["stage_outputs"]["report"]["report_path"]
        for entry in results
    }
    assert len(report_paths) == 2

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader

from submission_evaluation.agents.report import ReportAgent
from submission_evaluation.config import AppConfig
from submission_evaluation.models import LocationManifest


def _manifest() -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": "Plant A",
                "address_line_1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
            },
            {
                "location_name": "Plant B",
                "address_line_1": "200 River Rd",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country": "US",
            },
        ],
        submission_id="sub-010",
    )


def _manifest_with_count(count: int) -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": f"Plant {idx}",
                "address_line_1": f"{idx} Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": f"78{idx:03d}",
                "country": "US",
            }
            for idx in range(1, count + 1)
        ],
        submission_id=f"sub-010-{count}",
    )


def _build_agent(tmp_path: Path) -> ReportAgent:
    config = AppConfig.from_env()
    config = AppConfig(
        input_dir=config.input_dir,
        processed_dir=config.processed_dir,
        output_dir=tmp_path,
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_api_key=config.azure_openai_api_key,
        azure_openai_deployment=config.azure_openai_deployment,
        azure_openai_api_version=config.azure_openai_api_version,
        web_search_endpoint=config.web_search_endpoint,
        web_search_api_key=config.web_search_api_key,
    )
    return ReportAgent(config=config)


def _payload(manifest: LocationManifest) -> dict[str, object]:
    first = manifest.locations[0].id or ""
    second = manifest.locations[1].id or ""
    return {
        "manifest": manifest.to_dict(),
        "input_files": ["submission.xlsx", "supplement.pdf"],
        "company_research": {
            "company_name": "Acme Manufacturing",
            "overview": {
                "industry": "Manufacturing",
                "operations_summary": "Multi-state industrial operations.",
                "size_or_revenue": "$500M",
            },
            "citations": ["https://example.com/company"],
        },
        "risk_scores_by_location": {
            first: {
                "overall_score": 8.1,
                "overall_rationale": "Flood and hurricane risk drive elevated exposure.",
                "category_scores": {
                    "flood": {"score": 8.9, "rationale": "Flood plain overlap."},
                    "climate_trend": {"score": 7.4, "rationale": "Warming trend."},
                },
            },
            second: {
                "overall_score": 5.2,
                "overall_rationale": "Mixed profile with moderate severe-weather exposure.",
                "category_scores": {
                    "wildfire": {"score": 4.6, "rationale": "Low fuel density."},
                    "climate_trend": {"score": 5.8, "rationale": "Heat stress increase."},
                },
            },
        },
        "research_results": {
            first: [
                {
                    "risk_category": "flood",
                    "findings": "Historical flood events increased in frequency.",
                    "source_urls": ["https://example.com/flood-a"],
                },
                {
                    "risk_category": "climate_projection_10y",
                    "findings": "10-year outlook indicates higher flood intensity.",
                    "source_urls": ["https://example.com/climate-a"],
                },
            ],
            second: [
                {
                    "risk_category": "wildfire",
                    "findings": "Wildfire pressure remains moderate.",
                    "source_urls": ["https://example.com/wildfire-b"],
                },
                {
                    "risk_category": "climate_projection_10y",
                    "findings": "10-year outlook indicates higher heat events.",
                    "source_urls": ["https://example.com/climate-b"],
                },
            ],
        },
        "audit_entries": [{"stage": "analysis", "status": "ok"}],
    }


def _read_report_text(result_payload: dict[str, object]) -> str:
    report_path = Path(str(result_payload["report_path"]))
    if result_payload.get("format") == "pdf":
        reader = PdfReader(str(report_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return report_path.read_text(encoding="utf-8")


def test_report_contains_required_sections_and_toc_metadata(tmp_path: Path):
    manifest = _manifest()
    agent = _build_agent(tmp_path)

    result = agent.invoke(_payload(manifest))

    assert result.status == "ok"
    text = _read_report_text(result.payload)
    assert "Executive Summary" in text
    assert "Company Overview" in text
    assert "Audit Appendix" in text
    assert "Validation Status" in text

    toc = result.payload["table_of_contents"]
    assert isinstance(toc, list)
    section_names = [entry["section"] for entry in toc]
    assert "Table of Contents" in section_names
    assert "Executive Summary" in section_names
    assert all(isinstance(entry.get("page"), int) and entry["page"] > 0 for entry in toc)


def test_report_has_exact_manifest_location_sections_and_ids(tmp_path: Path):
    manifest = _manifest()
    agent = _build_agent(tmp_path)

    result = agent.invoke(_payload(manifest))
    second_result = agent.invoke(_payload(manifest))

    expected_ids = [location.id for location in manifest.locations if location.id]
    assert result.payload["report_location_ids"] == expected_ids
    assert result.payload["location_count"] == manifest.count

    report_locations = result.payload["report_locations"]
    assert len(report_locations) == manifest.count
    assert [section["location_id"] for section in report_locations] == expected_ids
    first_path = Path(str(result.payload["report_path"]))
    second_path = Path(str(second_result.payload["report_path"]))
    assert first_path.parent == tmp_path
    assert second_path.parent == tmp_path
    assert first_path.name == second_path.name


def test_report_locations_include_citations_and_climate_outlook(tmp_path: Path):
    manifest = _manifest()
    agent = _build_agent(tmp_path)

    result = agent.invoke(_payload(manifest))

    report_locations = result.payload["report_locations"]
    assert len(report_locations) == manifest.count
    for section in report_locations:
        citations = section["citations"]
        assert isinstance(citations, list)
        assert len(citations) >= 1
        climate_outlook = section["climate_outlook_10y"]
        assert isinstance(climate_outlook, str)
        assert climate_outlook.strip() != ""


def test_report_locations_include_scores_narrative_and_color_indicators(tmp_path: Path):
    manifest = _manifest()
    agent = _build_agent(tmp_path)

    result = agent.invoke(_payload(manifest))

    report_locations = result.payload["report_locations"]
    assert len(report_locations) == manifest.count
    for section in report_locations:
        assert isinstance(section["overall_score"], (int, float))
        assert section["category_scores"]
        assert isinstance(section["analysis_narrative"], str)
        assert section["analysis_narrative"].strip()
        assert section["risk_color"] in {"green", "yellow", "orange", "red", "gray"}


def test_report_when_single_location_manifest_should_generate_single_location_report(tmp_path: Path):
    manifest = _manifest_with_count(1)
    only_location = manifest.locations[0].id or ""
    payload = {
        "manifest": manifest.to_dict(),
        "input_files": ["single.xlsx"],
        "company_research": {
            "company_name": "Single Site Co",
            "overview": {
                "industry": "Manufacturing",
                "operations_summary": "Single location operation.",
                "size_or_revenue": "$5M",
            },
            "citations": ["https://example.com/company"],
        },
        "risk_scores_by_location": {
            only_location: {
                "overall_score": 6.2,
                "overall_rationale": "Moderate flood and wind exposure.",
                "category_scores": {
                    "flood": {"score": 6.5, "rationale": "Flood plain adjacency."},
                    "climate_trend": {"score": 5.8, "rationale": "Moderate warming trend."},
                },
            }
        },
        "research_results": {
            only_location: [
                {
                    "risk_category": "flood",
                    "findings": "Flood events increased slightly.",
                    "source_urls": ["https://example.com/flood"],
                },
                {
                    "risk_category": "climate_projection_10y",
                    "findings": "10-year outlook shows modest rainfall volatility.",
                    "source_urls": ["https://example.com/climate"],
                },
            ]
        },
        "audit_entries": [{"stage": "analysis", "status": "ok"}],
    }
    agent = _build_agent(tmp_path)

    result = agent.invoke(payload)

    assert result.status == "ok"
    assert result.payload["location_count"] == 1
    assert len(result.payload["report_locations"]) == 1


def test_report_when_100_location_manifest_should_generate_full_draft_with_100_sections(tmp_path: Path):
    manifest = _manifest_with_count(100)
    risk_scores_by_location: dict[str, dict[str, object]] = {}
    research_results: dict[str, list[dict[str, object]]] = {}
    for location in manifest.locations:
        location_id = location.id or ""
        risk_scores_by_location[location_id] = {
            "overall_score": 5.0,
            "overall_rationale": "Synthetic stable profile.",
            "category_scores": {
                "flood": {"score": 5.0, "rationale": "Synthetic flood rationale."},
                "climate_trend": {"score": 5.0, "rationale": "Synthetic climate rationale."},
            },
        }
        research_results[location_id] = [
            {
                "risk_category": "climate_projection_10y",
                "findings": "10-year outlook remains stable.",
                "source_urls": ["https://example.com/climate"],
            }
        ]

    payload = {
        "manifest": manifest.to_dict(),
        "input_files": ["max.xlsx"],
        "company_research": {
            "company_name": "Scale Test Co",
            "overview": {
                "industry": "Manufacturing",
                "operations_summary": "Distributed operations.",
                "size_or_revenue": "$1B",
            },
            "citations": ["https://example.com/company"],
        },
        "risk_scores_by_location": risk_scores_by_location,
        "research_results": research_results,
        "audit_entries": [{"stage": "analysis", "status": "ok"}],
        "draft_only": True,
    }
    agent = _build_agent(tmp_path)

    result = agent.invoke(payload)

    assert result.status == "ok"
    assert result.payload["format"] == "draft"
    assert result.payload["location_count"] == 100
    assert len(result.payload["report_locations"]) == 100


def test_report_when_location_has_missing_and_unverified_signals_should_render_warning_indicators(
    tmp_path: Path,
):
    manifest = _manifest_with_count(1)
    location_id = manifest.locations[0].id or ""
    payload = {
        "manifest": manifest.to_dict(),
        "input_files": ["warnings.xlsx"],
        "company_research": {
            "company_name": "Warning Co",
            "overview": {
                "industry": "Manufacturing",
                "operations_summary": "Data quality degraded.",
                "size_or_revenue": "Not available",
            },
            "citations": [],
        },
        "risk_scores_by_location": {
            location_id: {
                "overall_score": "N/A",
                "overall_rationale": "[unverified] Insufficient sourced inputs.",
                "category_scores": {
                    "flood": {"score": "N/A", "rationale": "Insufficient data."},
                },
            }
        },
        "research_results": {location_id: []},
        "audit_entries": [{"stage": "validation", "status": "failed"}],
        "draft_only": True,
    }
    agent = _build_agent(tmp_path)

    result = agent.invoke(payload)

    assert result.status == "ok"
    section = result.payload["report_locations"][0]
    assert section["overall_score"] == "N/A"
    assert section["risk_level"] == "Unknown"
    assert section["risk_color"] == "gray"
    assert section["analysis_narrative"].startswith("[unverified]")


def test_report_when_pdf_render_fails_should_write_markdown_fallback(tmp_path: Path):
    manifest = _manifest()
    config = AppConfig.from_env()
    config = AppConfig(
        input_dir=config.input_dir,
        processed_dir=config.processed_dir,
        output_dir=tmp_path,
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_api_key=config.azure_openai_api_key,
        azure_openai_deployment=config.azure_openai_deployment,
        azure_openai_api_version=config.azure_openai_api_version,
        web_search_endpoint=config.web_search_endpoint,
        web_search_api_key=config.web_search_api_key,
    )
    class FailingPdfReportAgent(ReportAgent):
        def _render_pdf(self, *, pdf_path: Path, report_data: Mapping[str, Any]) -> None:
            _ = (pdf_path, report_data)
            raise RuntimeError("forced render failure")

    agent = FailingPdfReportAgent(config=config)
    result = agent.invoke(_payload(manifest))

    assert result.status == "ok"
    assert result.payload["fallback_used"] is True
    assert result.payload["format"] == "markdown"
    assert Path(str(result.payload["report_path"])).exists()
    assert Path(str(result.payload["report_path"])).suffix == ".md"

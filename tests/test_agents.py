from __future__ import annotations

import json

from submission_evaluation.config import AppConfig
from submission_evaluation.agents.analysis import AnalysisAgent
from submission_evaluation.agents.base import AgentResult
from submission_evaluation.agents.ingestion import IngestionAgent
from submission_evaluation.agents.orchestrator import OrchestratorAgent
from submission_evaluation.agents.report import ReportAgent
from submission_evaluation.agents.research import ResearchAgent
from submission_evaluation.agents.validation import ValidationAgent
from submission_evaluation.orchestrator import build_default_orchestrator


def test_stub_agents_are_invocable():
    payload = {"submission_id": "sub-1"}

    for agent in [
        IngestionAgent(),
        ResearchAgent(),
        AnalysisAgent(),
        ReportAgent(),
        ValidationAgent(),
    ]:
        result = agent.invoke(payload)
        assert result.status == "ok"
        assert result.agent
        assert "received" in result.payload


def test_orchestrator_invokes_pipeline_in_order():
    orchestrator = build_default_orchestrator()
    result = orchestrator.invoke({"submission_id": "sub-2"})

    assert result["status"] == "ok"
    names = [entry["agent"] for entry in result["pipeline"]]
    assert names == [
        "ingestion",
        "validation",
        "research",
        "validation",
        "analysis",
        "validation",
        "report",
        "validation",
    ]
    assert result["report_emitted"] is True


def test_orchestrator_fails_when_validation_status_is_not_ok():
    invocation_counts = {"research": 0}

    class CountingResearch(ResearchAgent):
        def invoke(self, payload):
            invocation_counts["research"] += 1
            return AgentResult(
                agent="research",
                status="ok",
                payload={
                    "received": payload,
                    "message": "research completed",
                    "research_results": {},
                },
            )

    class FailingValidation(ValidationAgent):
        def invoke(self, payload):
            return AgentResult(agent="validation", status="failed", payload={"received": payload})

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=CountingResearch(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=FailingValidation(),
    )
    result = orchestrator.invoke({"submission_id": "sub-3"})

    assert result["status"] == "failed"
    assert result["reason"] == "pipeline_failed"
    assert result["report_emitted"] is False
    assert result["failed_stage"] == "ingestion"
    assert invocation_counts["research"] == 0
    assert "error_report" in result


def test_orchestrator_when_stage_location_set_mismatches_should_fail_fast_with_reason_codes():
    invocation_counts = {"analysis": 0, "report": 0}

    class MismatchResearch(ResearchAgent):
        def invoke(self, payload):
            return AgentResult(
                agent="research",
                status="ok",
                payload={
                    "received": payload,
                    "message": "research completed",
                    "research_results": {"loc-extra": []},
                },
            )

    class CountingAnalysis(AnalysisAgent):
        def invoke(self, payload):
            invocation_counts["analysis"] += 1
            return super().invoke(payload)

    class CountingReport(ReportAgent):
        def invoke(self, payload):
            invocation_counts["report"] += 1
            return super().invoke(payload)

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=MismatchResearch(),
        analysis=CountingAnalysis(),
        report=CountingReport(),
        validation=ValidationAgent(),
    )
    result = orchestrator.invoke({"submission_id": "sub-3b"})

    assert result["status"] == "failed"
    assert result["reason"] == "pipeline_failed"
    assert result["failed_stage"] == "research"
    assert result["report_emitted"] is False
    assert "location_count_mismatch" in result["reason_codes"]
    assert invocation_counts["analysis"] == 0
    assert invocation_counts["report"] == 0


def test_orchestrator_when_stage_validation_fails_then_succeeds_should_retry_and_continue():
    state = {"attempts": 0}

    class FlakyResearch(ResearchAgent):
        def invoke(self, payload):
            state["attempts"] += 1
            if state["attempts"] < 3:
                return AgentResult(
                    agent="research",
                    status="ok",
                    payload={
                        "received": payload,
                        "message": "research completed",
                        "research_results": {"loc-extra": []},
                    },
                )
            return AgentResult(
                agent="research",
                status="ok",
                payload={
                    "received": payload,
                    "message": "research completed",
                    "research_results": {},
                },
            )

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=FlakyResearch(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=ValidationAgent(),
    )
    result = orchestrator.invoke({"submission_id": "sub-3c"})

    assert result["status"] == "ok"
    assert result["report_emitted"] is True
    assert state["attempts"] == 3


def test_orchestrator_when_stage_outputs_missing_location_ids_should_fail_instead_of_skipping_validation():
    class MissingIdsResearch(ResearchAgent):
        def invoke(self, payload):
            return AgentResult(
                agent="research",
                status="ok",
                payload={
                    "received": payload,
                    "message": "research completed",
                },
            )

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=MissingIdsResearch(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=ValidationAgent(),
    )
    result = orchestrator.invoke({"submission_id": "sub-3d"})

    assert result["status"] == "failed"
    assert result["failed_stage"] == "research"
    assert result["report_emitted"] is False
    assert "stage_location_ids_unavailable" in result["reason_codes"]
    assert result["error_report"]["failed_stage"] == "research"


def test_orchestrator_retries_failed_stage_up_to_max_attempts_with_structured_reason_codes():
    invocation_counts = {"research": 0}

    class AlwaysFailResearch(ResearchAgent):
        def invoke(self, payload):
            invocation_counts["research"] += 1
            return AgentResult(
                agent="research",
                status="failed",
                payload={
                    "received": payload,
                    "message": "upstream dependency unavailable",
                    "reason_codes": ["dependency_unavailable"],
                },
            )

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=AlwaysFailResearch(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=ValidationAgent(),
        retries=3,
    )
    result = orchestrator.invoke({"submission_id": "sub-4"})

    assert result["status"] == "failed"
    assert result["failed_stage"] == "research"
    assert invocation_counts["research"] == 3
    assert "dependency_unavailable" in result["reason_codes"]
    assert result["retry"]["attempted"] == 3
    assert result["error_report"]["max_attempts"] == 3


def test_orchestrator_retries_then_fails_with_error_report_when_agent_raises():
    invocation_counts = {"ingestion": 0}

    class AlwaysFailIngestion(IngestionAgent):
        def invoke(self, _payload):
            invocation_counts["ingestion"] += 1
            raise RuntimeError("temporary failure")

    orchestrator = OrchestratorAgent(
        ingestion=AlwaysFailIngestion(),
        research=ResearchAgent(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=ValidationAgent(),
        retries=2,
    )

    result = orchestrator.invoke({"submission_id": "sub-4a"})

    assert result["status"] == "failed"
    assert result["failed_stage"] == "ingestion"
    assert result["reason"] == "pipeline_failed"
    assert result["report_emitted"] is False
    assert invocation_counts["ingestion"] == 2
    assert "agent_invocation_failed" in result["reason_codes"]
    assert "temporary failure" in result["error_report"]["message"]


def test_orchestrator_passes_manifest_context_to_all_downstream_agents():
    state = {
        "research_has_manifest": False,
        "analysis_has_manifest": False,
        "report_has_manifest": False,
        "validation_stages": [],
    }

    class ManifestResearch(ResearchAgent):
        def invoke(self, payload):
            state["research_has_manifest"] = "manifest" in payload
            return super().invoke(payload)

    class ManifestAnalysis(AnalysisAgent):
        def invoke(self, payload):
            state["analysis_has_manifest"] = "manifest" in payload
            return super().invoke(payload)

    class ManifestReport(ReportAgent):
        def invoke(self, payload):
            state["report_has_manifest"] = "manifest" in payload
            return super().invoke(payload)

    class ManifestValidation(ValidationAgent):
        def invoke(self, payload):
            state["validation_stages"].append(payload.get("stage"))
            assert "manifest" in payload
            return super().invoke(payload)

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=ManifestResearch(),
        analysis=ManifestAnalysis(),
        report=ManifestReport(),
        validation=ManifestValidation(),
    )

    result = orchestrator.invoke({"submission_id": "sub-5"})

    assert result["status"] == "ok"
    assert state["research_has_manifest"] is True
    assert state["analysis_has_manifest"] is True
    assert state["report_has_manifest"] is True
    assert state["validation_stages"] == ["ingestion", "research", "analysis", "report"]


def test_orchestrator_persists_and_recovers_from_last_successful_stage(tmp_path):
    state_path = tmp_path / "pipeline-state.json"
    invocation_counts = {
        "ingestion": 0,
        "research": 0,
        "analysis": 0,
    }

    class CountingIngestion(IngestionAgent):
        def invoke(self, payload):
            invocation_counts["ingestion"] += 1
            return super().invoke(payload)

    class CountingResearch(ResearchAgent):
        def invoke(self, payload):
            invocation_counts["research"] += 1
            return super().invoke(payload)

    class FailingAnalysis(AnalysisAgent):
        def invoke(self, _payload):
            invocation_counts["analysis"] += 1
            return AgentResult(
                agent="analysis",
                status="failed",
                payload={
                    "received": {},
                    "message": "analysis model timeout",
                    "reason_codes": ["analysis_timeout"],
                },
            )

    first_run = OrchestratorAgent(
        ingestion=CountingIngestion(),
        research=CountingResearch(),
        analysis=FailingAnalysis(),
        report=ReportAgent(),
        validation=ValidationAgent(),
        retries=1,
    )

    first_result = first_run.invoke(
        {
            "submission_id": "sub-6",
            "pipeline_state_path": str(state_path),
        }
    )
    assert first_result["status"] == "failed"
    assert first_result["failed_stage"] == "analysis"
    assert invocation_counts == {"ingestion": 1, "research": 1, "analysis": 1}

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["last_successful_stage"] == "research"

    class CountingAnalysis(AnalysisAgent):
        def invoke(self, payload):
            invocation_counts["analysis"] += 1
            return super().invoke(payload)

    second_run = OrchestratorAgent(
        ingestion=CountingIngestion(),
        research=CountingResearch(),
        analysis=CountingAnalysis(),
        report=ReportAgent(),
        validation=ValidationAgent(),
        retries=1,
    )

    second_result = second_run.invoke(
        {
            "submission_id": "sub-6",
            "resume": True,
            "pipeline_state_path": str(state_path),
        }
    )

    assert second_result["status"] == "ok"
    assert second_result["report_emitted"] is True
    assert invocation_counts["ingestion"] == 1
    assert invocation_counts["research"] == 1
    assert invocation_counts["analysis"] == 2
    assert any(event["action"] == "resume" for event in second_result["transition_events"])


def test_orchestrator_when_report_validation_fails_should_not_emit_artifact(tmp_path):
    output_dir = tmp_path / "out"

    config = AppConfig(
        input_dir=tmp_path / "in",
        processed_dir=tmp_path / "in" / "processed",
        output_dir=output_dir,
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        azure_openai_api_version="2024-06-01",
        web_search_endpoint="",
        web_search_api_key="",
    )

    class RejectFinalValidation(ValidationAgent):
        def invoke(self, payload):
            if payload.get("stage") == "report":
                return AgentResult(
                    agent="validation",
                    status="failed",
                    payload={
                        "received": payload,
                        "message": "report integrity failed",
                        "reason_codes": ["report_location_integrity_failed"],
                    },
                )
            return super().invoke(payload)

    orchestrator = OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=ResearchAgent(),
        analysis=AnalysisAgent(),
        report=ReportAgent(config=config),
        validation=RejectFinalValidation(),
        retries=1,
    )

    result = orchestrator.invoke({"submission_id": "sub-7"})

    assert result["status"] == "failed"
    assert result["failed_stage"] == "report"
    assert result["report_emitted"] is False
    assert not output_dir.exists()

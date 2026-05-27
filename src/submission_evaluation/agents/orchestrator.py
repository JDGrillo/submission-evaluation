from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping

from ..models import LocationManifest

from .analysis import AnalysisAgent
from .base import AgentResult
from .ingestion import IngestionAgent
from .report import ReportAgent
from .research import ResearchAgent
from .validation import ValidationAgent


LOGGER = logging.getLogger(__name__)


class AgentInvocationError(Exception):
    """Raised when an agent cannot be executed successfully."""


class OrchestratorAgent:
    """Minimal orchestration shell aligned to Agent Framework sequencing patterns."""

    _STAGE_ORDER: tuple[str, ...] = ("ingestion", "research", "analysis", "report")

    def __init__(
        self,
        ingestion: IngestionAgent,
        research: ResearchAgent,
        analysis: AnalysisAgent,
        report: ReportAgent,
        validation: ValidationAgent,
        retries: int = 3,
    ) -> None:
        self._ingestion = ingestion
        self._research = research
        self._analysis = analysis
        self._report = report
        self._validation = validation
        self._pipeline = [ingestion, research, analysis, report, validation]
        self._retries = retries

    @property
    def pipeline(self) -> List[Any]:
        return list(self._pipeline)

    def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current_payload: Dict[str, Any] = dict(payload)
        run_log: List[Dict[str, Any]] = []
        transition_events: List[Dict[str, Any]] = []
        manifest: LocationManifest | None = None
        stage_outputs: dict[str, Dict[str, Any]] = {}
        last_successful_stage: str | None = None

        state_path = self._resolve_state_path(payload)
        submission_id = str(payload.get("submission_id", ""))
        if bool(payload.get("resume")) and state_path is not None:
            recovered = self._load_state(state_path)
            if recovered is not None:
                recovered_submission_id = str(recovered.get("submission_id", ""))
                if not submission_id or recovered_submission_id == submission_id:
                    recovered_outputs = recovered.get("stage_outputs")
                    if isinstance(recovered_outputs, Mapping):
                        stage_outputs = {
                            str(stage): dict(stage_payload)
                            for stage, stage_payload in recovered_outputs.items()
                            if isinstance(stage_payload, Mapping)
                        }
                        for stage_name in self._STAGE_ORDER:
                            if stage_name in stage_outputs:
                                current_payload.update(stage_outputs[stage_name])
                    recovered_manifest = recovered.get("manifest")
                    if isinstance(recovered_manifest, Mapping):
                        try:
                            manifest = LocationManifest.from_dict(recovered_manifest)
                            current_payload["manifest"] = manifest.to_dict()
                        except (TypeError, ValueError, KeyError):
                            manifest = None
                    recovered_stage = recovered.get("last_successful_stage")
                    if isinstance(recovered_stage, str) and recovered_stage in self._STAGE_ORDER:
                        last_successful_stage = recovered_stage
                    transition_events.append(
                        self._transition_event(
                            stage="pipeline",
                            action="resume",
                            status="ok",
                            detail={
                                "state_path": str(state_path),
                                "last_successful_stage": last_successful_stage,
                            },
                            location_count=manifest.count if manifest is not None else None,
                        )
                    )

        start_index = 0
        if last_successful_stage in self._STAGE_ORDER:
            start_index = self._STAGE_ORDER.index(last_successful_stage) + 1

        for stage_name in self._STAGE_ORDER[start_index:]:
            agent = self._agent_for_stage(stage_name)
            stage_attempt = 0
            stage_validated = False
            latest_payload = dict(current_payload)
            failed_reason_codes: list[str] = []
            failure_message = "stage_failed"
            failure_detail: dict[str, Any] = {}

            while stage_attempt < self._retries:
                stage_attempt += 1
                transition_events.append(
                    self._transition_event(
                        stage=stage_name,
                        action="stage_start",
                        status="pending",
                        detail={"attempt": stage_attempt},
                        location_count=manifest.count if manifest is not None else None,
                    )
                )

                stage_input: Dict[str, Any] = dict(latest_payload)
                if manifest is not None:
                    stage_input["manifest"] = manifest.to_dict()
                    stage_input["location_ids"] = [
                        str(location.id)
                        for location in manifest.locations
                        if location.id
                    ]
                if stage_name == "report":
                    stage_input["draft_only"] = True

                try:
                    stage_result = self._invoke_with_retries(agent, stage_input)
                except AgentInvocationError as exc:
                    failed_reason_codes = ["agent_invocation_failed"]
                    failure_message = str(exc)
                    failure_detail = {
                        "component": "stage_agent",
                        "exception_type": type(exc).__name__,
                    }
                    transition_events.append(
                        self._transition_event(
                            stage=stage_name,
                            action="stage_exception",
                            status="failed",
                            detail={
                                "attempt": stage_attempt,
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                            location_count=manifest.count if manifest is not None else None,
                        )
                    )
                    continue

                run_log.append(stage_result.to_dict())
                transition_events.append(
                    self._transition_event(
                        stage=stage_name,
                        action="stage_result",
                        status=stage_result.status,
                        detail={"attempt": stage_attempt, "agent": stage_result.agent},
                        location_count=manifest.count if manifest is not None else None,
                    )
                )

                if stage_result.status != "ok":
                    failed_reason_codes = [
                        str(code) for code in stage_result.payload.get("reason_codes", ["stage_agent_failed"])
                    ]
                    failure_message = str(stage_result.payload.get("message", "stage agent failed"))
                    failure_detail = {
                        "component": "stage_agent",
                        "agent": stage_result.agent,
                        "payload": stage_result.payload,
                    }
                    continue

                stage_payload = self._stage_context(stage_name=stage_name, payload=stage_result.payload)
                latest_payload = {**latest_payload, **stage_payload}

                if stage_name == "ingestion":
                    manifest = self._extract_manifest(stage_result.payload)
                    if manifest is not None:
                        latest_payload["manifest"] = manifest.to_dict()

                stage_manifest = manifest or self._extract_manifest(stage_payload)
                if stage_manifest is None:
                    failed_reason_codes = ["validation_manifest_missing"]
                    failure_message = "validation manifest missing for stage boundary"
                    failure_detail = {
                        "component": "validation_gate",
                        "stage": stage_name,
                    }
                    run_log.append(
                        {
                            "agent": "validation",
                            "status": "failed",
                            "payload": {
                                "summary": {
                                    "location_integrity": {
                                        "passed": False,
                                        "stage": stage_name,
                                        "reason_codes": failed_reason_codes,
                                    }
                                },
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                        }
                    )
                    transition_events.append(
                        self._transition_event(
                            stage=stage_name,
                            action="validation_result",
                            status="failed",
                            detail={
                                "attempt": stage_attempt,
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                            location_count=None,
                        )
                    )
                    continue

                location_ids = self._extract_location_ids(stage_name=stage_name, payload=stage_result.payload)
                if location_ids is None:
                    failed_reason_codes = ["stage_location_ids_unavailable"]
                    failure_message = "validation location_ids unavailable for stage boundary"
                    failure_detail = {
                        "component": "validation_gate",
                        "stage": stage_name,
                    }
                    run_log.append(
                        {
                            "agent": "validation",
                            "status": "failed",
                            "payload": {
                                "summary": {
                                    "location_integrity": {
                                        "passed": False,
                                        "stage": stage_name,
                                        "reason_codes": failed_reason_codes,
                                    }
                                },
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                        }
                    )
                    transition_events.append(
                        self._transition_event(
                            stage=stage_name,
                            action="validation_result",
                            status="failed",
                            detail={
                                "attempt": stage_attempt,
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                            location_count=stage_manifest.count,
                        )
                    )
                    continue

                validation_payload: Dict[str, Any] = {
                    "manifest": stage_manifest.to_dict(),
                    "stage": stage_name,
                    "location_ids": location_ids,
                    "max_retry_attempts": self._retries,
                }
                if stage_name == "report":
                    report_locations = stage_result.payload.get("report_locations")
                    if isinstance(report_locations, list):
                        validation_payload["report_locations"] = report_locations

                try:
                    validation_result = self._invoke_with_retries(self._validation, validation_payload)
                except AgentInvocationError as exc:
                    failed_reason_codes = ["validation_invocation_failed"]
                    failure_message = str(exc)
                    failure_detail = {
                        "component": "validation_gate",
                        "exception_type": type(exc).__name__,
                    }
                    transition_events.append(
                        self._transition_event(
                            stage=stage_name,
                            action="validation_exception",
                            status="failed",
                            detail={
                                "attempt": stage_attempt,
                                "reason_codes": failed_reason_codes,
                                "message": failure_message,
                            },
                            location_count=stage_manifest.count,
                        )
                    )
                    continue

                run_log.append(validation_result.to_dict())
                transition_events.append(
                    self._transition_event(
                        stage=stage_name,
                        action="validation_result",
                        status=validation_result.status,
                        detail={
                            "attempt": stage_attempt,
                            "reason_codes": validation_result.payload.get("reason_codes", []),
                            "message": validation_result.payload.get(
                                "message", "validation deterministic checks completed"
                            ),
                        },
                        location_count=stage_manifest.count,
                    )
                )

                if validation_result.status == "ok":
                    if stage_name == "report":
                        final_emit_payload: Dict[str, Any] = dict(latest_payload)
                        final_emit_payload["draft_only"] = False
                        if manifest is not None:
                            final_emit_payload["manifest"] = manifest.to_dict()
                        try:
                            final_emit_result = self._invoke_with_retries(self._report, final_emit_payload)
                        except AgentInvocationError as exc:
                            failed_reason_codes = ["report_emit_failed"]
                            failure_message = str(exc)
                            failure_detail = {
                                "component": "report_emit",
                                "exception_type": type(exc).__name__,
                            }
                            transition_events.append(
                                self._transition_event(
                                    stage=stage_name,
                                    action="report_emit",
                                    status="failed",
                                    detail={
                                        "attempt": stage_attempt,
                                        "reason_codes": failed_reason_codes,
                                        "message": failure_message,
                                    },
                                    location_count=stage_manifest.count,
                                )
                            )
                            continue

                        transition_events.append(
                            self._transition_event(
                                stage=stage_name,
                                action="report_emit",
                                status=final_emit_result.status,
                                detail={
                                    "attempt": stage_attempt,
                                    "reason_codes": final_emit_result.payload.get("reason_codes", []),
                                    "message": final_emit_result.payload.get("message", "report emitted"),
                                },
                                location_count=stage_manifest.count,
                            )
                        )
                        if final_emit_result.status != "ok":
                            failed_reason_codes = [
                                str(code)
                                for code in final_emit_result.payload.get("reason_codes", ["report_emit_failed"])
                            ]
                            failure_message = str(final_emit_result.payload.get("message", "report emit failed"))
                            failure_detail = {
                                "component": "report_emit",
                                "agent": final_emit_result.agent,
                                "payload": final_emit_result.payload,
                            }
                            continue
                        stage_payload = self._stage_context(stage_name=stage_name, payload=final_emit_result.payload)
                        latest_payload = {**latest_payload, **stage_payload}

                    stage_validated = True
                    stage_outputs[stage_name] = dict(stage_payload)
                    latest_payload = {**latest_payload, **stage_outputs[stage_name]}
                    manifest = stage_manifest
                    last_successful_stage = stage_name
                    self._persist_state(
                        state_path=state_path,
                        submission_id=submission_id,
                        last_successful_stage=last_successful_stage,
                        manifest=manifest,
                        stage_outputs=stage_outputs,
                        transition_events=transition_events,
                    )
                    break

                failed_reason_codes = [str(code) for code in validation_result.payload.get("reason_codes", [])]
                failure_message = str(validation_result.payload.get("message", "validation failed"))
                failure_detail = {
                    "component": "validation_gate",
                    "agent": validation_result.agent,
                    "payload": validation_result.payload,
                }

            if not stage_validated:
                error_report = self._build_error_report(
                    failed_stage=stage_name,
                    attempted=stage_attempt,
                    reason_codes=failed_reason_codes,
                    message=failure_message,
                    detail=failure_detail,
                    transition_events=transition_events,
                )
                self._persist_state(
                    state_path=state_path,
                    submission_id=submission_id,
                    last_successful_stage=last_successful_stage,
                    manifest=manifest,
                    stage_outputs=stage_outputs,
                    transition_events=transition_events,
                    error_report=error_report,
                )
                return {
                    "status": "failed",
                    "reason": "pipeline_failed",
                    "failed_stage": stage_name,
                    "reason_codes": failed_reason_codes,
                    "retry": {
                        "retryable": False,
                        "failed_stage": stage_name,
                        "attempted": stage_attempt,
                        "max_attempts": self._retries,
                        "reason_codes": failed_reason_codes,
                        "message": failure_message,
                    },
                    "report_emitted": False,
                    "pipeline": run_log,
                    "final_payload": latest_payload,
                    "transition_events": transition_events,
                    "stage_state": {
                        "last_successful_stage": last_successful_stage,
                        "stage_outputs": stage_outputs,
                    },
                    "error_report": error_report,
                }

            current_payload = latest_payload

        self._persist_state(
            state_path=state_path,
            submission_id=submission_id,
            last_successful_stage=last_successful_stage,
            manifest=manifest,
            stage_outputs=stage_outputs,
            transition_events=transition_events,
        )
        return {
            "status": "ok",
            "report_emitted": True,
            "pipeline": run_log,
            "final_payload": current_payload,
            "transition_events": transition_events,
            "stage_state": {
                "last_successful_stage": last_successful_stage,
                "stage_outputs": stage_outputs,
            },
        }

    def _agent_for_stage(self, stage_name: str) -> Any:
        if stage_name == "ingestion":
            return self._ingestion
        if stage_name == "research":
            return self._research
        if stage_name == "analysis":
            return self._analysis
        if stage_name == "report":
            return self._report
        raise ValueError(f"Unsupported stage: {stage_name}")

    def _stage_context(self, *, stage_name: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        context: Dict[str, Any] = {}
        if stage_name == "ingestion":
            for key in ("manifest", "manifest_hash", "location_count", "warnings", "input_files"):
                if key in payload:
                    context[key] = payload[key]
            return context

        if stage_name == "research":
            for key in ("research_results", "company_research", "location_count"):
                if key in payload:
                    context[key] = payload[key]
            return context

        if stage_name == "analysis":
            for key in ("risk_scores_by_location", "methodology", "location_count"):
                if key in payload:
                    context[key] = payload[key]
            return context

        if stage_name == "report":
            for key in (
                "format",
                "report_path",
                "pdf_path",
                "markdown_fallback_path",
                "fallback_used",
                "render_error",
                "table_of_contents",
                "report_location_ids",
                "location_ids",
                "report_locations",
                "location_count",
            ):
                if key in payload:
                    context[key] = payload[key]
            return context

        return context

    def _transition_event(
        self,
        *,
        stage: str,
        action: str,
        status: str,
        detail: Mapping[str, Any],
        location_count: int | None,
    ) -> Dict[str, Any]:
        event = {
            "event": "pipeline_transition",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "action": action,
            "status": status,
            "location_count": location_count,
            "detail": dict(detail),
        }
        LOGGER.info(json.dumps(event, sort_keys=True))
        return event

    def _build_error_report(
        self,
        *,
        failed_stage: str,
        attempted: int,
        reason_codes: list[str],
        message: str,
        detail: Mapping[str, Any],
        transition_events: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "summary": "Pipeline failed after exhausting retry budget",
            "failed_stage": failed_stage,
            "attempted": attempted,
            "max_attempts": self._retries,
            "reason_codes": list(reason_codes),
            "message": message,
            "detail": dict(detail),
            "recent_events": transition_events[-10:],
        }

    def _resolve_state_path(self, payload: Mapping[str, Any]) -> Path | None:
        raw = payload.get("pipeline_state_path")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return Path(raw)

    def _load_state(self, state_path: Path) -> dict[str, Any] | None:
        if not state_path.exists() or not state_path.is_file():
            return None
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _persist_state(
        self,
        *,
        state_path: Path | None,
        submission_id: str,
        last_successful_stage: str | None,
        manifest: LocationManifest | None,
        stage_outputs: Mapping[str, Mapping[str, Any]],
        transition_events: list[Dict[str, Any]],
        error_report: Mapping[str, Any] | None = None,
    ) -> None:
        if state_path is None:
            return
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "submission_id": submission_id,
            "last_successful_stage": last_successful_stage,
            "manifest": manifest.to_dict() if manifest is not None else None,
            "stage_outputs": {stage: dict(stage_payload) for stage, stage_payload in stage_outputs.items()},
            "transition_events": transition_events,
        }
        if error_report is not None:
            payload["error_report"] = dict(error_report)
        state_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _extract_manifest(self, payload: Mapping[str, Any]) -> LocationManifest | None:
        cursor: Mapping[str, Any] | None = payload
        for _ in range(8):
            if cursor is None:
                return None
            manifest_payload = cursor.get("manifest")
            if isinstance(manifest_payload, Mapping):
                try:
                    return LocationManifest.from_dict(manifest_payload)
                except (TypeError, ValueError, KeyError):
                    return None
            previous = cursor.get("previous")
            if isinstance(previous, Mapping):
                cursor = previous
                continue
            return None
        return None

    def _extract_location_ids(self, *, stage_name: str, payload: Mapping[str, Any]) -> list[str] | None:
        direct_ids = payload.get("location_ids")
        if isinstance(direct_ids, list):
            return [str(item) for item in direct_ids]

        if stage_name == "research":
            research_results = payload.get("research_results")
            if isinstance(research_results, Mapping):
                if research_results:
                    return [str(item) for item in research_results.keys()]
                received_payload = payload.get("received")
                if isinstance(received_payload, Mapping):
                    received_ids = received_payload.get("location_ids")
                    if isinstance(received_ids, list):
                        return [str(item) for item in received_ids]
                return []

        if stage_name == "analysis":
            risk_scores = payload.get("risk_scores_by_location")
            if isinstance(risk_scores, Mapping):
                return [str(item) for item in risk_scores.keys()]

        if stage_name == "ingestion":
            manifest_payload = payload.get("manifest")
            if isinstance(manifest_payload, Mapping):
                manifest_locations = manifest_payload.get("locations")
                if isinstance(manifest_locations, list):
                    location_ids: list[str] = []
                    for location in manifest_locations:
                        if isinstance(location, Mapping) and "id" in location:
                            location_ids.append(str(location["id"]))
                    if location_ids:
                        return location_ids

        if stage_name == "report":
            report_locations = payload.get("report_locations")
            if isinstance(report_locations, list):
                location_ids: list[str] = []
                for item in report_locations:
                    if isinstance(item, Mapping) and "location_id" in item:
                        location_ids.append(str(item["location_id"]))
                if location_ids:
                    return location_ids
            report_location_ids = payload.get("report_location_ids")
            if isinstance(report_location_ids, list):
                return [str(item) for item in report_location_ids]

        return None

    def _invoke_with_retries(self, agent: Any, payload: Dict[str, Any]) -> AgentResult:
        try:
            return agent.invoke(payload)
        except (RuntimeError, TimeoutError, ValueError, ConnectionError, OSError) as exc:
            raise AgentInvocationError(f"Agent {agent.name} invocation failed: {exc}") from exc

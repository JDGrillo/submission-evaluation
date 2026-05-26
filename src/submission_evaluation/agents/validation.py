from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..models import LocationManifest
from ..validation import (
    apply_claim_validation_policy,
    ReportLocationSection,
    StructuredClaim,
    validate_location_integrity,
    validate_report_location_fields,
    validate_structured_claims,
)
from .base import AgentResult, NoOpAgent


def _extract_stage_location_ids(stage_payload: Any) -> list[str] | None:
    if isinstance(stage_payload, list):
        return [str(item) for item in stage_payload]

    if not isinstance(stage_payload, Mapping):
        return None

    direct_location_ids = stage_payload.get("location_ids")
    if isinstance(direct_location_ids, list):
        return [str(item) for item in direct_location_ids]

    for keyed_output_name in ("research_results", "risk_scores_by_location", "report_locations"):
        keyed_output = stage_payload.get(keyed_output_name)
        if isinstance(keyed_output, Mapping):
            return [str(item) for item in keyed_output.keys()]

    return None


def _normalize_stage_checks(payload: dict[str, Any]) -> list[tuple[str, list[str]]]:
    checks: list[tuple[str, list[str]]] = []

    stage_outputs = payload.get("stage_outputs")
    stage_order = payload.get("stage_order")
    if isinstance(stage_outputs, Mapping):
        if isinstance(stage_order, list):
            ordered_stages = [str(item) for item in stage_order if str(item) in stage_outputs]
        else:
            ordered_stages = [str(item) for item in stage_outputs.keys()]

        for stage_name in ordered_stages:
            stage_payload = stage_outputs.get(stage_name)
            location_ids = _extract_stage_location_ids(stage_payload)
            if location_ids is not None:
                checks.append((stage_name, location_ids))

    stage = payload.get("stage")
    location_ids = payload.get("location_ids")
    if isinstance(stage, str) and isinstance(location_ids, list):
        checks.append((stage, [str(item) for item in location_ids]))

    return checks


class ValidationAgent(NoOpAgent):
    def __init__(self) -> None:
        super().__init__("validation")

    def invoke(self, payload: dict[str, Any]) -> AgentResult:
        has_manifest = "manifest" in payload
        has_claims_key = "claims" in payload
        has_report_locations_key = "report_locations" in payload
        has_location_stage_key = "stage" in payload or "stage_outputs" in payload
        has_location_ids_key = "location_ids" in payload or "stage_outputs" in payload

        if (
            not has_manifest
            and not has_claims_key
            and not has_report_locations_key
            and not has_location_stage_key
            and not has_location_ids_key
        ):
            return super().invoke(payload)

        manifest_payload = payload.get("manifest")
        if not isinstance(manifest_payload, dict):
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": "Validation payload must include object 'manifest'",
                    "message": "validation input parsing failed",
                },
            )

        if has_claims_key and not isinstance(payload.get("claims"), list):
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": "Validation payload must include list 'claims' when provided",
                    "message": "validation input parsing failed",
                },
            )

        if has_report_locations_key and not isinstance(payload.get("report_locations"), list):
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": "Validation payload must include list 'report_locations' when provided",
                    "message": "validation input parsing failed",
                },
            )

        if ("stage" in payload or "location_ids" in payload) and not (
            isinstance(payload.get("stage"), str) and isinstance(payload.get("location_ids"), list)
        ):
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": "Validation payload must include string 'stage' and list 'location_ids'",
                    "message": "validation input parsing failed",
                },
            )

        claims_payload = payload.get("claims")
        report_locations_payload = payload.get("report_locations")

        try:
            manifest = LocationManifest.from_dict(manifest_payload)
        except (TypeError, ValueError, KeyError) as exc:
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": str(exc),
                    "message": "validation input parsing failed",
                },
            )

        summaries: dict[str, Any] = {}
        statuses: list[bool] = []
        reason_codes: set[str] = set()
        audit_checks: list[dict[str, Any]] = []
        retry_hint: dict[str, Any] | None = None
        provided_manifest_hash = str(manifest_payload.get("manifest_hash", "")).strip()
        manifest_hash_verified = not provided_manifest_hash or provided_manifest_hash == manifest.manifest_hash

        stage_checks = _normalize_stage_checks(payload)
        if stage_checks:
            stage_results: list[dict[str, Any]] = []
            failed_stages: list[dict[str, Any]] = []
            for stage_name, stage_location_ids in stage_checks:
                location_result = validate_location_integrity(
                    manifest=manifest,
                    stage=stage_name,
                    location_ids=tuple(stage_location_ids),
                )
                serialized = location_result.to_dict()
                stage_results.append(serialized)
                audit_checks.append(
                    {
                        "check_type": "location_integrity",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": stage_name,
                        "passed": location_result.passed,
                        "manifest_hash": manifest.manifest_hash,
                        "manifest_hash_verified": manifest_hash_verified,
                        "expected_count": location_result.expected_count,
                        "actual_count": location_result.actual_count,
                        "reason_codes": list(location_result.reason_codes),
                        "details": {
                            "missing_ids": list(location_result.missing_ids),
                            "extra_ids": list(location_result.extra_ids),
                            "duplicate_ids": list(location_result.duplicate_ids),
                        },
                    }
                )
                statuses.append(location_result.passed)
                reason_codes.update(location_result.reason_codes)
                if not location_result.passed:
                    failed_stages.append(
                        {
                            "stage": stage_name,
                            "reason_codes": list(location_result.reason_codes),
                            "missing_ids": list(location_result.missing_ids),
                            "extra_ids": list(location_result.extra_ids),
                            "duplicate_ids": list(location_result.duplicate_ids),
                        }
                    )

            if len(stage_results) == 1 and "stage_outputs" not in payload:
                summaries["location_integrity"] = stage_results[0]
            else:
                summaries["location_integrity"] = {
                    "all_passed": all(result["passed"] for result in stage_results),
                    "stage_results": stage_results,
                    "failed_stages": failed_stages,
                }

            if failed_stages:
                first_failure = failed_stages[0]
                retry_hint = {
                    "retryable": True,
                    "failed_stage": first_failure["stage"],
                    "reason_codes": first_failure["reason_codes"],
                    "max_attempts": int(payload.get("max_retry_attempts", 3)),
                }

        if isinstance(claims_payload, list):
            try:
                claims = tuple(StructuredClaim.from_dict(item) for item in claims_payload)
                research_sources = payload.get("research_sources", {})
                claim_summary = validate_structured_claims(
                    manifest=manifest,
                    claims=claims,
                    research_sources=research_sources,
                )
                policy = payload.get("unsourced_claim_policy", "mark")
                policy_result = apply_claim_validation_policy(
                    claims=claims,
                    summary=claim_summary,
                    policy=policy,
                )
            except (TypeError, ValueError, KeyError) as exc:
                return AgentResult(
                    agent=self.name,
                    status="failed",
                    payload={
                        "received": payload,
                        "error": str(exc),
                        "message": "validation input parsing failed",
                    },
                )
            summaries["claim_integrity"] = claim_summary.to_dict()
            summaries["claim_actions"] = policy_result.to_dict()
            statuses.append(claim_summary.flagged_claims == 0)
            if claim_summary.flagged_claims > 0:
                reason_codes.add("claim_integrity_failed")

            for result in claim_summary.results:
                audit_checks.append(
                    {
                        "check_type": "claim_integrity",
                        "claim_id": result.claim_id,
                        "location_id": result.location_id,
                        "passed": result.passed,
                        "reason_codes": [issue.code for issue in result.issues],
                    }
                )

        if isinstance(report_locations_payload, list):
            try:
                report_sections = tuple(ReportLocationSection.from_dict(item) for item in report_locations_payload)
                report_location_summary = validate_report_location_fields(
                    manifest=manifest,
                    report_locations=report_sections,
                )
            except (TypeError, ValueError, KeyError) as exc:
                return AgentResult(
                    agent=self.name,
                    status="failed",
                    payload={
                        "received": payload,
                        "error": str(exc),
                        "message": "validation input parsing failed",
                    },
                )

            summaries["report_location_integrity"] = report_location_summary.to_dict()
            statuses.append(report_location_summary.flagged_sections == 0)
            if report_location_summary.flagged_sections > 0:
                reason_codes.add("report_location_integrity_failed")

            for result in report_location_summary.results:
                audit_checks.append(
                    {
                        "check_type": "report_location_integrity",
                        "location_id": result.location_id,
                        "passed": result.passed,
                        "reason_codes": [issue.code for issue in result.issues],
                    }
                )

        if not summaries:
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": payload,
                    "error": "No validation checks requested",
                    "message": "validation input parsing failed",
                },
            )

        status = "ok" if all(statuses) else "failed"
        payload_out: dict[str, Any] = {
            "received": payload,
            "summary": summaries,
            "audit": {
                "passed": status == "ok",
                "checks": audit_checks,
            },
            "reason_codes": sorted(reason_codes),
            "message": "validation deterministic checks completed",
        }
        if retry_hint is not None:
            payload_out["retry"] = retry_hint

        return AgentResult(
            agent=self.name,
            status=status,
            payload=payload_out,
        )

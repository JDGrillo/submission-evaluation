from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, fields
import re
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping

from .models import JsonValue, Location, LocationManifest

ClaimKind = Literal["factual", "narrative"]
CitationKind = Literal["manifest", "research"]
UnsourcedClaimPolicy = Literal["mark", "remove"]


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return format(float(value), "g")
    if value is None:
        return ""
    normalized = str(value).strip().lower().replace(",", "")
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()
    try:
        return format(float(normalized), "g")
    except ValueError:
        return normalized


def _normalize_json_value(value: Any) -> str:
    if isinstance(value, tuple):
        return ",".join(_normalize_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{k}:{_normalize_json_value(v)}" for k, v in sorted(value.items())) + "}"
    return _normalize_scalar(value)


def _extract_numeric_tokens(text: str) -> tuple[str, ...]:
    matches = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", text)
    return tuple(_normalize_scalar(match) for match in matches)


def _location_scalar_fields(location: Location) -> dict[str, str]:
    scalar_fields: dict[str, str] = {}
    for model_field in fields(location):
        field_name = model_field.name
        value = getattr(location, field_name)
        if field_name == "additional_fields":
            if isinstance(value, Mapping):
                for key, nested_value in value.items():
                    scalar_fields[f"additional_fields.{key}"] = _normalize_json_value(nested_value)
            continue
        scalar_fields[field_name] = _normalize_json_value(value)
    return scalar_fields


def _freeze_mapping(value: Mapping[str, JsonValue] | None) -> Mapping[str, JsonValue]:
    if not value:
        return MappingProxyType({})
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class CitationRef:
    kind: CitationKind
    ref: str
    expected_value: JsonValue | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CitationRef:
        kind = payload["kind"]
        if kind not in {"manifest", "research"}:
            raise ValueError(f"Unsupported citation kind: {kind}")
        return cls(
            kind=kind,
            ref=str(payload["ref"]),
            expected_value=payload.get("expected_value"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "expected_value": self.expected_value,
        }


@dataclass(frozen=True)
class StructuredClaim:
    claim_id: str
    location_id: str
    kind: ClaimKind
    text: str
    citations: tuple[CitationRef, ...] = field(default_factory=tuple)
    numeric_values: tuple[float, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredClaim:
        raw_citations = payload.get("citations", [])
        raw_numeric_values = payload.get("numeric_values", [])
        kind = payload["kind"]
        if kind not in {"factual", "narrative"}:
            raise ValueError(f"Unsupported claim kind: {kind}")
        return cls(
            claim_id=str(payload["claim_id"]),
            location_id=str(payload["location_id"]),
            kind=kind,
            text=str(payload.get("text", "")),
            citations=tuple(CitationRef.from_dict(item) for item in raw_citations),
            numeric_values=tuple(float(item) for item in raw_numeric_values),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "claim_id": self.claim_id,
            "location_id": self.location_id,
            "kind": self.kind,
            "text": self.text,
            "citations": [citation.to_dict() for citation in self.citations],
            "numeric_values": list(self.numeric_values),
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    claim_id: str
    location_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "claim_id": self.claim_id,
            "location_id": self.location_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class ClaimValidationResult:
    claim_id: str
    location_id: str
    passed: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "location_id": self.location_id,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ClaimValidationSummary:
    total_claims: int
    passed_claims: int
    flagged_claims: int
    synthesis_claims: int
    factual_claims: int
    results: tuple[ClaimValidationResult, ...]

    @property
    def claims_checked(self) -> int:
        return self.total_claims

    @property
    def flagged_count(self) -> int:
        return self.flagged_claims

    @property
    def pass_rate(self) -> float:
        if self.total_claims == 0:
            return 1.0
        return self.passed_claims / self.total_claims

    @property
    def sourced_percentage(self) -> float:
        return self.pass_rate * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims_checked": self.claims_checked,
            "total_claims": self.total_claims,
            "passed_claims": self.passed_claims,
            "flagged_claims": self.flagged_claims,
            "flagged_count": self.flagged_count,
            "synthesis_claims": self.synthesis_claims,
            "factual_claims": self.factual_claims,
            "pass_rate": self.pass_rate,
            "sourced_percentage": self.sourced_percentage,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class ClaimAnnotation:
    claim_id: str
    location_id: str
    passed: bool
    annotated_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "location_id": self.location_id,
            "passed": self.passed,
            "annotated_text": self.annotated_text,
        }


@dataclass(frozen=True)
class ValidationAuditEntry:
    action: str
    claim_id: str
    location_id: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "claim_id": self.claim_id,
            "location_id": self.location_id,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class ClaimPolicyResult:
    policy: UnsourcedClaimPolicy
    annotations: tuple[ClaimAnnotation, ...]
    audit_entries: tuple[ValidationAuditEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "annotations": [annotation.to_dict() for annotation in self.annotations],
            "audit_entries": [entry.to_dict() for entry in self.audit_entries],
        }


@dataclass(frozen=True)
class LocationIntegrityResult:
    stage: str
    passed: bool
    expected_count: int
    actual_count: int
    missing_ids: tuple[str, ...]
    extra_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "passed": self.passed,
            "expected_count": self.expected_count,
            "actual_count": self.actual_count,
            "missing_ids": list(self.missing_ids),
            "extra_ids": list(self.extra_ids),
            "duplicate_ids": list(self.duplicate_ids),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class ReportLocationSection:
    location_id: str
    location_name: str | None = None
    address_line_1: str | None = None
    asserted_fields: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asserted_fields", _freeze_mapping(self.asserted_fields))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReportLocationSection:
        return cls(
            location_id=str(payload["location_id"]),
            location_name=payload.get("location_name"),
            address_line_1=payload.get("address_line_1"),
            asserted_fields=dict(payload.get("asserted_fields", {})),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "location_id": self.location_id,
            "location_name": self.location_name,
            "address_line_1": self.address_line_1,
            "asserted_fields": dict(self.asserted_fields),
        }


@dataclass(frozen=True)
class ReportLocationValidationResult:
    location_id: str
    passed: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "location_id": self.location_id,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ReportLocationValidationSummary:
    total_sections: int
    passed_sections: int
    flagged_sections: int
    results: tuple[ReportLocationValidationResult, ...]

    @property
    def pass_rate(self) -> float:
        if self.total_sections == 0:
            return 1.0
        return self.passed_sections / self.total_sections

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sections": self.total_sections,
            "passed_sections": self.passed_sections,
            "flagged_sections": self.flagged_sections,
            "pass_rate": self.pass_rate,
            "results": [result.to_dict() for result in self.results],
        }


def validate_structured_claims(
    manifest: LocationManifest,
    claims: Iterable[StructuredClaim],
    research_sources: Mapping[str, Mapping[str, Iterable[str]]] | None = None,
) -> ClaimValidationSummary:
    manifest_lookup = {location.id: _location_scalar_fields(location) for location in manifest.locations if location.id}
    normalized_research: dict[str, dict[str, tuple[str, ...]]] = {}
    raw_research_sources = research_sources or {}
    if not isinstance(raw_research_sources, Mapping):
        raise ValueError("research_sources must be a mapping")

    for location_id, source_entries in raw_research_sources.items():
        if not isinstance(source_entries, Mapping):
            raise ValueError("research_sources[location_id] must be a mapping of url -> evidence")
        location_sources: dict[str, tuple[str, ...]] = {}
        for source_url, evidence_snippets in source_entries.items():
            if not isinstance(source_url, str):
                raise ValueError("research source URL keys must be strings")
            if isinstance(evidence_snippets, str):
                iterable_snippets = (evidence_snippets,)
            elif isinstance(evidence_snippets, Iterable) and not isinstance(evidence_snippets, Mapping):
                iterable_snippets = tuple(evidence_snippets)
            else:
                raise ValueError("research source evidence must be iterable")
            location_sources[source_url.strip()] = tuple(_normalize_scalar(item) for item in iterable_snippets)
        normalized_research[location_id] = location_sources

    results: list[ClaimValidationResult] = []
    synthesis_count = 0
    factual_count = 0

    for claim in claims:
        issues: list[ValidationIssue] = []
        proven_numeric_values: set[str] = set()
        text_numeric_values = set(_extract_numeric_tokens(claim.text))
        location_fields = manifest_lookup.get(claim.location_id)
        if location_fields is None:
            issues.append(
                ValidationIssue(
                    code="unknown_location",
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    message="Claim references location_id not found in manifest",
                )
            )

        if claim.kind not in {"factual", "narrative"}:
            issues.append(
                ValidationIssue(
                    code="invalid_claim_kind",
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    message=f"Unsupported claim kind: {claim.kind}",
                )
            )

        is_factual = claim.kind == "factual" or bool(claim.numeric_values)
        if is_factual:
            factual_count += 1
            if not claim.citations:
                issues.append(
                    ValidationIssue(
                        code="missing_citation",
                        claim_id=claim.claim_id,
                        location_id=claim.location_id,
                        message="Factual claim must provide at least one citation",
                    )
                )
        else:
            synthesis_count += 1

        for citation in claim.citations:
            if citation.kind == "manifest":
                if location_fields is None:
                    continue
                actual = location_fields.get(citation.ref)
                if actual is None:
                    issues.append(
                        ValidationIssue(
                            code="manifest_field_not_found",
                            claim_id=claim.claim_id,
                            location_id=claim.location_id,
                            message=f"Manifest field not found: {citation.ref}",
                        )
                    )
                    continue
                if citation.expected_value is not None:
                    expected = _normalize_json_value(citation.expected_value)
                    if actual != expected:
                        issues.append(
                            ValidationIssue(
                                code="manifest_value_mismatch",
                                claim_id=claim.claim_id,
                                location_id=claim.location_id,
                                message=(
                                    f"Manifest value mismatch for {citation.ref}: "
                                    f"expected={citation.expected_value}"
                                ),
                            )
                        )
                    else:
                        proven_numeric_values.add(expected)
                else:
                    proven_numeric_values.add(actual)
                    proven_numeric_values.update(_extract_numeric_tokens(actual))
            elif citation.kind == "research":
                location_sources = normalized_research.get(claim.location_id, {})
                source_evidence = location_sources.get(citation.ref.strip())
                if source_evidence is None:
                    issues.append(
                        ValidationIssue(
                            code="research_source_not_found",
                            claim_id=claim.claim_id,
                            location_id=claim.location_id,
                            message=f"Research source not found for citation URL: {citation.ref}",
                        )
                    )
                    continue
                if citation.expected_value is not None:
                    expected = _normalize_json_value(citation.expected_value)
                    evidence_text = " ".join(source_evidence)
                    if expected not in evidence_text:
                        issues.append(
                            ValidationIssue(
                                code="research_evidence_mismatch",
                                claim_id=claim.claim_id,
                                location_id=claim.location_id,
                                message=(
                                    f"Expected research value not found in evidence for URL: {citation.ref}"
                                ),
                            )
                        )
                    else:
                        proven_numeric_values.add(expected)
                evidence_text = " ".join(source_evidence)
                proven_numeric_values.update(_extract_numeric_tokens(evidence_text))
            else:
                issues.append(
                    ValidationIssue(
                        code="invalid_citation_kind",
                        claim_id=claim.claim_id,
                        location_id=claim.location_id,
                        message=f"Unsupported citation kind: {citation.kind}",
                    )
                )

        numeric_values_to_verify = set(_normalize_scalar(numeric_value) for numeric_value in claim.numeric_values)
        if is_factual:
            numeric_values_to_verify.update(text_numeric_values)

        for numeric_value in sorted(numeric_values_to_verify):
            if numeric_value not in proven_numeric_values:
                issues.append(
                    ValidationIssue(
                        code="numeric_value_untraceable",
                        claim_id=claim.claim_id,
                        location_id=claim.location_id,
                        message=(
                            "Numeric value is not traceable to cited manifest/research evidence: "
                            f"{numeric_value}"
                        ),
                    )
                )

        results.append(
            ClaimValidationResult(
                claim_id=claim.claim_id,
                location_id=claim.location_id,
                passed=not issues,
                issues=tuple(issues),
            )
        )

    total_claims = len(results)
    passed_claims = sum(1 for result in results if result.passed)
    return ClaimValidationSummary(
        total_claims=total_claims,
        passed_claims=passed_claims,
        flagged_claims=total_claims - passed_claims,
        synthesis_claims=synthesis_count,
        factual_claims=factual_count,
        results=tuple(results),
    )


def validate_location_integrity(
    manifest: LocationManifest,
    stage: str,
    location_ids: Iterable[str],
) -> LocationIntegrityResult:
    expected_ids = {location.id for location in manifest.locations if location.id}
    actual_list = [location_id for location_id in location_ids]
    actual_ids = set(actual_list)
    actual_counter = Counter(actual_list)

    missing = tuple(sorted(expected_ids - actual_ids))
    extra = tuple(sorted(location_id for location_id in actual_ids if location_id not in expected_ids))
    duplicate = tuple(sorted(location_id for location_id, count in actual_counter.items() if count > 1))
    reason_codes: list[str] = []
    if len(actual_list) != len(expected_ids):
        reason_codes.append("location_count_mismatch")
    if missing:
        reason_codes.append("location_ids_missing")
    if extra:
        reason_codes.append("location_ids_extra")
    if duplicate:
        reason_codes.append("location_ids_duplicate")

    return LocationIntegrityResult(
        stage=stage,
        passed=not missing and not extra and not duplicate,
        expected_count=len(expected_ids),
        actual_count=len(actual_list),
        missing_ids=missing,
        extra_ids=extra,
        duplicate_ids=duplicate,
        reason_codes=tuple(reason_codes),
    )


def estimate_tokens_for_claims(claims: Iterable[StructuredClaim]) -> int:
    # Conservative approximation: 1 token ~= 4 characters.
    text_size = 0
    for claim in claims:
        text_size += len(claim.text)
        text_size += len(claim.claim_id) + len(claim.location_id) + len(claim.kind)
        for citation in claim.citations:
            text_size += len(citation.kind) + len(citation.ref)
            if citation.expected_value is not None:
                text_size += len(_normalize_json_value(citation.expected_value))
        text_size += sum(len(_normalize_scalar(value)) for value in claim.numeric_values)
    return max(1, text_size // 4)


def batch_claims_for_token_limit(
    claims: Iterable[StructuredClaim],
    max_tokens: int,
) -> tuple[tuple[StructuredClaim, ...], ...]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")

    batches: list[tuple[StructuredClaim, ...]] = []
    current_batch: list[StructuredClaim] = []
    current_tokens = 0

    for claim in claims:
        claim_tokens = estimate_tokens_for_claims((claim,))
        if claim_tokens > max_tokens:
            raise ValueError(f"Single claim exceeds max token budget: claim_id={claim.claim_id}")
        if current_batch and (current_tokens + claim_tokens) > max_tokens:
            batches.append(tuple(current_batch))
            current_batch = []
            current_tokens = 0
        current_batch.append(claim)
        current_tokens += claim_tokens

    if current_batch:
        batches.append(tuple(current_batch))

    return tuple(batches)


def annotate_claims_with_unverified_marker(
    claims: Iterable[StructuredClaim],
    summary: ClaimValidationSummary,
    marker: str = "[unverified]",
) -> tuple[ClaimAnnotation, ...]:
    result_by_id = {result.claim_id: result for result in summary.results}
    annotations: list[ClaimAnnotation] = []
    for claim in claims:
        result = result_by_id.get(claim.claim_id)
        passed = bool(result and result.passed)
        annotated_text = claim.text if passed else f"{marker} {claim.text}".strip()
        annotations.append(
            ClaimAnnotation(
                claim_id=claim.claim_id,
                location_id=claim.location_id,
                passed=passed,
                annotated_text=annotated_text,
            )
        )
    return tuple(annotations)


def apply_claim_validation_policy(
    claims: Iterable[StructuredClaim],
    summary: ClaimValidationSummary,
    *,
    policy: UnsourcedClaimPolicy = "mark",
    marker: str = "[unverified]",
) -> ClaimPolicyResult:
    if policy not in {"mark", "remove"}:
        raise ValueError(f"Unsupported unsourced claim policy: {policy}")

    result_by_id = {result.claim_id: result for result in summary.results}
    annotations: list[ClaimAnnotation] = []
    audit_entries: list[ValidationAuditEntry] = []

    for claim in claims:
        result = result_by_id.get(claim.claim_id)
        passed = bool(result and result.passed)
        if passed:
            annotations.append(
                ClaimAnnotation(
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    passed=True,
                    annotated_text=claim.text,
                )
            )
            audit_entries.append(
                ValidationAuditEntry(
                    action="kept",
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    reason_codes=(),
                )
            )
            continue

        reason_codes = tuple(sorted({issue.code for issue in (result.issues if result else ())}))
        if policy == "remove":
            annotations.append(
                ClaimAnnotation(
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    passed=False,
                    annotated_text="",
                )
            )
            audit_entries.append(
                ValidationAuditEntry(
                    action="removed",
                    claim_id=claim.claim_id,
                    location_id=claim.location_id,
                    reason_codes=reason_codes,
                )
            )
            continue

        annotations.append(
            ClaimAnnotation(
                claim_id=claim.claim_id,
                location_id=claim.location_id,
                passed=False,
                annotated_text=f"{marker} {claim.text}".strip(),
            )
        )
        audit_entries.append(
            ValidationAuditEntry(
                action="marked_unverified",
                claim_id=claim.claim_id,
                location_id=claim.location_id,
                reason_codes=reason_codes,
            )
        )

    return ClaimPolicyResult(policy=policy, annotations=tuple(annotations), audit_entries=tuple(audit_entries))


def validate_report_location_fields(
    manifest: LocationManifest,
    report_locations: Iterable[ReportLocationSection],
) -> ReportLocationValidationSummary:
    manifest_lookup = {location.id: _location_scalar_fields(location) for location in manifest.locations if location.id}
    results: list[ReportLocationValidationResult] = []

    for section in report_locations:
        issues: list[ValidationIssue] = []
        claim_ref = f"report-location:{section.location_id}"
        location_fields = manifest_lookup.get(section.location_id)
        if location_fields is None:
            issues.append(
                ValidationIssue(
                    code="unknown_location",
                    claim_id=claim_ref,
                    location_id=section.location_id,
                    message="Report location section references unknown location_id",
                )
            )
        else:
            if section.location_name is not None:
                expected_name = location_fields.get("location_name")
                actual_name = _normalize_scalar(section.location_name)
                if expected_name != actual_name:
                    issues.append(
                        ValidationIssue(
                            code="fabricated_location_name",
                            claim_id=claim_ref,
                            location_id=section.location_id,
                            message="Report location name does not match manifest",
                        )
                    )

            if section.address_line_1 is not None:
                expected_address = location_fields.get("address_line_1")
                actual_address = _normalize_scalar(section.address_line_1)
                if expected_address != actual_address:
                    issues.append(
                        ValidationIssue(
                            code="fabricated_address_line_1",
                            claim_id=claim_ref,
                            location_id=section.location_id,
                            message="Report address does not match manifest",
                        )
                    )

            for field_name, field_value in section.asserted_fields.items():
                actual_manifest_value = location_fields.get(field_name)
                if actual_manifest_value is None:
                    issues.append(
                        ValidationIssue(
                            code="fabricated_manifest_field",
                            claim_id=claim_ref,
                            location_id=section.location_id,
                            message=f"Report asserted unknown field: {field_name}",
                        )
                    )
                    continue
                expected_value = _normalize_json_value(field_value)
                if actual_manifest_value != expected_value:
                    issues.append(
                        ValidationIssue(
                            code="fabricated_manifest_field_value",
                            claim_id=claim_ref,
                            location_id=section.location_id,
                            message=f"Report asserted value mismatch for field: {field_name}",
                        )
                    )

        results.append(
            ReportLocationValidationResult(
                location_id=section.location_id,
                passed=not issues,
                issues=tuple(issues),
            )
        )

    total_sections = len(results)
    passed_sections = sum(1 for result in results if result.passed)
    return ReportLocationValidationSummary(
        total_sections=total_sections,
        passed_sections=passed_sections,
        flagged_sections=total_sections - passed_sections,
        results=tuple(results),
    )


__all__ = [
    "apply_claim_validation_policy",
    "annotate_claims_with_unverified_marker",
    "batch_claims_for_token_limit",
    "ClaimAnnotation",
    "ClaimPolicyResult",
    "CitationRef",
    "ReportLocationSection",
    "ReportLocationValidationResult",
    "ReportLocationValidationSummary",
    "ClaimValidationResult",
    "ClaimValidationSummary",
    "estimate_tokens_for_claims",
    "LocationIntegrityResult",
    "StructuredClaim",
    "UnsourcedClaimPolicy",
    "ValidationAuditEntry",
    "ValidationIssue",
    "validate_location_integrity",
    "validate_report_location_fields",
    "validate_structured_claims",
]

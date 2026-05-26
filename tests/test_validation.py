from __future__ import annotations

import pytest

from submission_evaluation.agents.validation import ValidationAgent
from submission_evaluation.models import LocationManifest
from submission_evaluation.validation import (
    apply_claim_validation_policy,
    annotate_claims_with_unverified_marker,
    CitationRef,
    ReportLocationSection,
    StructuredClaim,
    batch_claims_for_token_limit,
    estimate_tokens_for_claims,
    validate_location_integrity,
    validate_report_location_fields,
    validate_structured_claims,
)


def _manifest() -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": "HQ",
                "address_line_1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
                "flood_zone": "X",
                "total_insured_value": 5500000.0,
            }
        ],
        submission_id="sub-100",
    )


def test_validate_structured_claims_when_manifest_citation_matches_should_pass():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-1",
            location_id=location_id,
            kind="factual",
            text="Location flood zone is X.",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="X"),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.total_claims == 1
    assert summary.flagged_claims == 0
    assert summary.results[0].passed is True


def test_validate_structured_claims_when_manifest_value_is_fabricated_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-2",
            location_id=location_id,
            kind="factual",
            text="Location flood zone is A.",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="A"),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.flagged_claims == 1
    assert summary.results[0].passed is False
    assert any(issue.code == "manifest_value_mismatch" for issue in summary.results[0].issues)


def test_validate_report_location_fields_when_address_is_fabricated_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    summary = validate_report_location_fields(
        manifest=manifest,
        report_locations=(
            ReportLocationSection(
                location_id=location_id,
                location_name="HQ",
                address_line_1="999 Fake Ave",
            ),
        ),
    )

    assert summary.flagged_sections == 1
    assert summary.results[0].passed is False
    assert any(issue.code == "fabricated_address_line_1" for issue in summary.results[0].issues)


def test_validate_report_location_fields_when_asserted_field_unknown_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    summary = validate_report_location_fields(
        manifest=manifest,
        report_locations=(
            ReportLocationSection(
                location_id=location_id,
                asserted_fields={"made_up_zone": "Q"},
            ),
        ),
    )

    assert summary.flagged_sections == 1
    assert any(issue.code == "fabricated_manifest_field" for issue in summary.results[0].issues)


def test_validate_structured_claims_when_research_source_missing_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-3",
            location_id=location_id,
            kind="factual",
            text="Flood event count increased by 12%.",
            citations=(
                CitationRef(
                    kind="research",
                    ref="https://noaa.gov/example",
                    expected_value="12%",
                ),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims, research_sources={location_id: {}})

    assert summary.flagged_claims == 1
    assert any(issue.code == "research_source_not_found" for issue in summary.results[0].issues)


def test_validate_structured_claims_when_narrative_without_numerics_should_allow_synthesis():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-4",
            location_id=location_id,
            kind="narrative",
            text="The site appears moderately resilient due to construction and geography.",
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.synthesis_claims == 1
    assert summary.factual_claims == 0
    assert summary.flagged_claims == 0
    assert summary.results[0].passed is True


def test_validate_structured_claims_should_include_summary_metrics():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="metrics-1",
            location_id=location_id,
            kind="factual",
            text="Flood zone is X",
            citations=(CitationRef(kind="manifest", ref="flood_zone", expected_value="X"),),
        ),
        StructuredClaim(
            claim_id="metrics-2",
            location_id=location_id,
            kind="factual",
            text="Flood zone is A",
            citations=(CitationRef(kind="manifest", ref="flood_zone", expected_value="A"),),
        ),
    ]
    summary = validate_structured_claims(manifest, claims)
    payload = summary.to_dict()

    assert payload["claims_checked"] == 2
    assert payload["flagged_count"] == 1
    assert payload["sourced_percentage"] == pytest.approx(50.0)


def test_validate_structured_claims_when_numeric_not_backed_by_citation_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-5",
            location_id=location_id,
            kind="factual",
            text="TIV is 7000000.",
            numeric_values=(7000000.0,),
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="X"),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.flagged_claims == 1
    assert any(issue.code == "numeric_value_untraceable" for issue in summary.results[0].issues)


def test_validate_structured_claims_when_numeric_in_text_is_unsourced_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-5b",
            location_id=location_id,
            kind="factual",
            text="The exposure increased to 99999 this year.",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="X"),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.flagged_claims == 1
    assert any(issue.code == "numeric_value_untraceable" for issue in summary.results[0].issues)


def test_validate_structured_claims_when_numeric_matches_citation_should_pass():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="c-6",
            location_id=location_id,
            kind="factual",
            text="TIV is 5500000.",
            numeric_values=(5500000.0,),
            citations=(
                CitationRef(
                    kind="manifest",
                    ref="total_insured_value",
                    expected_value=5500000.0,
                ),
            ),
        )
    ]

    summary = validate_structured_claims(manifest, claims)

    assert summary.flagged_claims == 0
    assert summary.results[0].passed is True


def test_validate_report_location_fields_when_location_name_is_fabricated_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    summary = validate_report_location_fields(
        manifest=manifest,
        report_locations=(
            ReportLocationSection(
                location_id=location_id,
                location_name="Fake HQ",
                address_line_1="100 Main St",
            ),
        ),
    )

    assert summary.flagged_sections == 1
    assert any(issue.code == "fabricated_location_name" for issue in summary.results[0].issues)


def test_structured_claim_from_dict_when_kind_invalid_should_raise():
    with pytest.raises(ValueError, match="Unsupported claim kind"):
        StructuredClaim.from_dict(
            {
                "claim_id": "c-7",
                "location_id": "loc-1",
                "kind": "opinion",
                "text": "bad kind",
            }
        )


def test_citation_from_dict_when_kind_invalid_should_raise():
    with pytest.raises(ValueError, match="Unsupported citation kind"):
        CitationRef.from_dict(
            {
                "kind": "url",
                "ref": "https://example.com",
            }
        )


def test_validation_agent_when_claim_payload_invalid_should_fail():
    manifest = _manifest()
    agent = ValidationAgent()
    result = agent.invoke(
        {
            "manifest": manifest.to_dict(),
            "claims": [
                {
                    "claim_id": "c-8",
                    "location_id": manifest.locations[0].id,
                    "kind": "invalid",
                    "text": "bad",
                }
            ],
        }
    )

    assert result.status == "failed"
    assert "Unsupported claim kind" in result.payload["error"]


def test_validate_structured_claims_when_claim_kind_invalid_direct_instance_should_flag():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    invalid_claim = StructuredClaim(
        claim_id="c-9",
        location_id=location_id,
        kind="invalid",  # type: ignore[arg-type]
        text="invalid kind",
    )

    summary = validate_structured_claims(manifest, [invalid_claim])

    assert summary.flagged_claims == 1
    assert any(issue.code == "invalid_claim_kind" for issue in summary.results[0].issues)


def test_validation_agent_when_payload_shape_is_incomplete_should_fail():
    manifest = _manifest()
    agent = ValidationAgent()
    result = agent.invoke({"manifest": manifest.to_dict()})

    assert result.status == "failed"
    assert "No validation checks requested" in result.payload["error"]


def test_validation_agent_when_research_sources_payload_is_invalid_should_fail():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None
    agent = ValidationAgent()

    result = agent.invoke(
        {
            "manifest": manifest.to_dict(),
            "claims": [
                {
                    "claim_id": "c-10",
                    "location_id": location_id,
                    "kind": "factual",
                    "text": "Flood zone is X",
                    "citations": [
                        {
                            "kind": "manifest",
                            "ref": "flood_zone",
                            "expected_value": "X",
                        }
                    ],
                }
            ],
            "research_sources": {location_id: 123},
        }
    )

    assert result.status == "failed"
    assert "research_sources[location_id] must be a mapping" in result.payload["error"]


def test_validate_location_integrity_when_ids_match_should_pass():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-1",
    )

    result = validate_location_integrity(
        manifest=manifest,
        stage="analysis",
        location_ids=[loc.id for loc in manifest.locations if loc.id],
    )

    assert result.passed is True
    assert result.missing_ids == ()
    assert result.extra_ids == ()


def test_validate_location_integrity_when_missing_or_extra_should_fail_with_diff():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-2",
    )
    kept_id = manifest.locations[0].id
    assert kept_id is not None

    result = validate_location_integrity(
        manifest=manifest,
        stage="report",
        location_ids=[kept_id, "loc-extra"],
    )

    assert result.passed is False
    assert len(result.missing_ids) == 1
    assert result.extra_ids == ("loc-extra",)
    assert "location_count_mismatch" not in result.reason_codes
    assert "location_ids_missing" in result.reason_codes
    assert "location_ids_extra" in result.reason_codes


def test_validate_location_integrity_when_single_location_missing_should_fail_with_missing_id_diff():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-missing-1",
    )
    kept_id = manifest.locations[0].id
    dropped_id = manifest.locations[1].id
    assert kept_id is not None
    assert dropped_id is not None

    result = validate_location_integrity(
        manifest=manifest,
        stage="analysis",
        location_ids=[kept_id],
    )

    assert result.passed is False
    assert result.missing_ids == (dropped_id,)
    assert result.extra_ids == ()
    assert "location_ids_missing" in result.reason_codes


def test_validate_report_location_fields_when_values_match_manifest_should_pass():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    summary = validate_report_location_fields(
        manifest=manifest,
        report_locations=(
            ReportLocationSection(
                location_id=location_id,
                location_name="HQ",
                address_line_1="100 Main St",
                asserted_fields={"flood_zone": "X"},
            ),
        ),
    )

    assert summary.total_sections == 1
    assert summary.flagged_sections == 0
    assert summary.results[0].passed is True


def test_validation_agent_when_location_integrity_payload_provided_should_apply_veto():
    manifest = LocationManifest.from_records(
        [{"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"}],
        submission_id="sub-loc-3",
    )

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage": "research",
            "location_ids": ["loc-mismatch"],
        }
    )

    assert result.status == "failed"
    assert result.payload["summary"]["location_integrity"]["passed"] is False
    assert "location_count_mismatch" not in result.payload["reason_codes"]
    assert "location_ids_missing" in result.payload["reason_codes"]
    assert "location_ids_extra" in result.payload["reason_codes"]
    assert result.payload["retry"]["retryable"] is True
    assert result.payload["retry"]["failed_stage"] == "research"


def test_validate_location_integrity_when_duplicate_ids_present_should_fail():
    manifest = LocationManifest.from_records(
        [{"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"}],
        submission_id="sub-loc-4",
    )
    location_id = manifest.locations[0].id
    assert location_id is not None

    result = validate_location_integrity(
        manifest=manifest,
        stage="analysis",
        location_ids=[location_id, location_id],
    )

    assert result.passed is False
    assert result.duplicate_ids == (location_id,)
    assert "location_ids_duplicate" in result.reason_codes


def test_validation_agent_when_stage_outputs_payload_present_should_validate_each_stage_boundary():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-stage-1",
    )
    location_ids = [location.id for location in manifest.locations if location.id]

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage_order": ["research", "analysis", "report"],
            "stage_outputs": {
                "research": {"location_ids": location_ids},
                "analysis": {"location_ids": location_ids},
                "report": {"location_ids": location_ids},
            },
        }
    )

    assert result.status == "ok"
    summary = result.payload["summary"]["location_integrity"]
    assert summary["all_passed"] is True
    assert len(summary["stage_results"]) == 3
    assert all(item["passed"] is True for item in summary["stage_results"])
    assert result.payload["audit"]["passed"] is True


def test_validation_agent_when_stage_boundary_fails_should_emit_machine_readable_retry_and_audit_details():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-stage-2",
    )
    first_location_id = manifest.locations[0].id
    assert first_location_id is not None

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage_order": ["analysis"],
            "stage_outputs": {
                "analysis": [first_location_id, "loc-extra"],
            },
            "max_retry_attempts": 3,
        }
    )

    assert result.status == "failed"
    assert "location_count_mismatch" not in result.payload["reason_codes"]
    assert "location_ids_missing" in result.payload["reason_codes"]
    assert "location_ids_extra" in result.payload["reason_codes"]
    assert result.payload["retry"]["retryable"] is True
    assert result.payload["retry"]["failed_stage"] == "analysis"
    assert result.payload["retry"]["max_attempts"] == 3
    assert any(
        check["check_type"] == "location_integrity" and check["passed"] is False
        for check in result.payload["audit"]["checks"]
    )


def test_validation_agent_should_emit_location_integrity_audit_entries_for_both_pass_and_fail():
    manifest = LocationManifest.from_records(
        [
            {"location_name": "A", "address_line_1": "1 Main", "city": "Austin", "state": "TX"},
            {"location_name": "B", "address_line_1": "2 Main", "city": "Austin", "state": "TX"},
        ],
        submission_id="sub-loc-audit-1",
    )
    location_ids = [location.id for location in manifest.locations if location.id]

    pass_result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage": "research",
            "location_ids": location_ids,
        }
    )
    assert pass_result.status == "ok"
    assert any(
        check["check_type"] == "location_integrity" and check["passed"] is True
        for check in pass_result.payload["audit"]["checks"]
    )

    fail_result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage": "research",
            "location_ids": location_ids[:1],
        }
    )
    assert fail_result.status == "failed"
    assert any(
        check["check_type"] == "location_integrity" and check["passed"] is False
        for check in fail_result.payload["audit"]["checks"]
    )


def test_validation_agent_when_location_and_claim_payloads_present_should_run_both():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "stage": "report",
            "location_ids": [location_id],
            "claims": [
                {
                    "claim_id": "combo-1",
                    "location_id": location_id,
                    "kind": "factual",
                    "text": "Flood zone is X",
                    "citations": [
                        {
                            "kind": "manifest",
                            "ref": "flood_zone",
                            "expected_value": "X",
                        }
                    ],
                }
            ],
        }
    )

    assert result.status == "ok"
    assert "location_integrity" in result.payload["summary"]
    assert "claim_integrity" in result.payload["summary"]


def test_false_positive_rate_for_legitimate_synthesis_should_be_below_10_percent():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    legitimate_claims = [
        StructuredClaim(
            claim_id=f"syn-{idx}",
            location_id=location_id,
            kind="narrative",
            text=f"Legitimate synthesis statement {idx}",
        )
        for idx in range(20)
    ]
    summary = validate_structured_claims(manifest, legitimate_claims)

    false_positive_rate = summary.flagged_claims / max(1, summary.total_claims)
    assert false_positive_rate < 0.10


def test_token_batching_for_100_locations_should_stay_within_budget():
    records = [
        {
            "location_name": f"Site-{idx}",
            "address_line_1": f"{idx} Main St",
            "city": "Austin",
            "state": "TX",
            "total_insured_value": 1000000 + idx,
            "flood_zone": "X",
        }
        for idx in range(1, 101)
    ]
    manifest = LocationManifest.from_records(records, submission_id="sub-scale-1")

    claims = [
        StructuredClaim(
            claim_id=f"claim-{index}",
            location_id=location.id or "",
            kind="factual",
            text="Total insured value evidence",
            numeric_values=(float(location.total_insured_value or 0),),
            citations=(
                CitationRef(
                    kind="manifest",
                    ref="total_insured_value",
                    expected_value=location.total_insured_value,
                ),
            ),
        )
        for index, location in enumerate(manifest.locations, start=1)
    ]

    batches = batch_claims_for_token_limit(claims, max_tokens=2000)

    assert sum(len(batch) for batch in batches) == len(claims)
    assert all(estimate_tokens_for_claims(batch) <= 2000 for batch in batches)
    # Azure OpenAI 128k context can accommodate per-batch validation with this chunking strategy.
    assert len(batches) >= 1


def test_annotate_claims_when_flagged_should_prefix_unverified_marker():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="ann-1",
            location_id=location_id,
            kind="factual",
            text="Flood zone is A",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="A"),
            ),
        )
    ]
    summary = validate_structured_claims(manifest, claims)
    annotations = annotate_claims_with_unverified_marker(claims, summary)

    assert annotations[0].passed is False
    assert annotations[0].annotated_text.startswith("[unverified]")


def test_apply_claim_validation_policy_when_mark_should_audit_and_preserve_text():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="policy-1",
            location_id=location_id,
            kind="factual",
            text="Flood zone is A",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="A"),
            ),
        )
    ]
    summary = validate_structured_claims(manifest, claims)
    policy_result = apply_claim_validation_policy(claims, summary, policy="mark")

    assert policy_result.policy == "mark"
    assert policy_result.annotations[0].annotated_text.startswith("[unverified]")
    assert policy_result.audit_entries[0].action == "marked_unverified"
    assert "manifest_value_mismatch" in policy_result.audit_entries[0].reason_codes


def test_apply_claim_validation_policy_when_remove_should_audit_and_remove_text():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    claims = [
        StructuredClaim(
            claim_id="policy-2",
            location_id=location_id,
            kind="factual",
            text="Flood zone is A",
            citations=(
                CitationRef(kind="manifest", ref="flood_zone", expected_value="A"),
            ),
        )
    ]
    summary = validate_structured_claims(manifest, claims)
    policy_result = apply_claim_validation_policy(claims, summary, policy="remove")

    assert policy_result.policy == "remove"
    assert policy_result.annotations[0].annotated_text == ""
    assert policy_result.audit_entries[0].action == "removed"


def test_validation_agent_when_report_locations_present_should_validate_fabricated_address():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "report_locations": [
                {
                    "location_id": location_id,
                    "location_name": "HQ",
                    "address_line_1": "999 Fake Ave",
                }
            ],
        }
    )

    assert result.status == "failed"
    assert result.payload["summary"]["report_location_integrity"]["flagged_sections"] == 1


def test_validation_agent_when_claims_present_should_include_claim_actions_summary():
    manifest = _manifest()
    location_id = manifest.locations[0].id
    assert location_id is not None

    result = ValidationAgent().invoke(
        {
            "manifest": manifest.to_dict(),
            "claims": [
                {
                    "claim_id": "claim-action-1",
                    "location_id": location_id,
                    "kind": "factual",
                    "text": "Flood zone is A",
                    "citations": [
                        {
                            "kind": "manifest",
                            "ref": "flood_zone",
                            "expected_value": "A",
                        }
                    ],
                }
            ],
            "unsourced_claim_policy": "mark",
        }
    )

    assert result.status == "failed"
    assert result.payload["summary"]["claim_integrity"]["claims_checked"] == 1
    assert result.payload["summary"]["claim_actions"]["audit_entries"][0]["action"] == "marked_unverified"

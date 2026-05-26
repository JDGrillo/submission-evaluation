# TEST-003: Validation Agent Tests
- **Source Requirements**: [REQ-F-009, REQ-F-010, REQ-NF-001]
- **Priority**: P0
- **Complexity**: M
- **Phase**: 4
- **Dependencies**: [DEV-008, DEV-009]
- **Status**: Complete

## Description
Tests for the Validation Agent's location integrity and data integrity checking capabilities.

## Test Cases

### Location Integrity
- [x] TC-1: Output has same locations as manifest → PASS
- [x] TC-2: Output missing 1 location → FAIL with diff showing missing ID
- [x] TC-3: Output has extra location (hallucinated) → FAIL with diff showing extra ID
- [x] TC-4: Output has correct count but wrong IDs → FAIL (detects ID swap)
- [x] TC-5: Validation at multiple stage boundaries (research, analysis, report)
- [x] TC-6: Pipeline halts on first failure (does not continue to next stage)
- [x] TC-7: Audit trail entry created on both pass and fail

### Data Integrity
- [x] TC-8: Report with all values from input/sources → PASS
- [x] TC-9: Report with fabricated numerical value → DETECTED and flagged
- [x] TC-10: Report with fabricated address → DETECTED and flagged
- [x] TC-11: Report with legitimate LLM synthesis → NOT flagged (acceptable narrative)
- [x] TC-12: Audit summary produced with claim count and pass rate

### Veto Power
- [x] TC-13: Validation fail → report NOT saved to output directory
- [x] TC-14: After 3 retry failures → error report generated instead

## Coverage Mapping
- TC-1: `tests/test_validation.py::test_validate_location_integrity_when_ids_match_should_pass`
- TC-2: `tests/test_validation.py::test_validate_location_integrity_when_single_location_missing_should_fail_with_missing_id_diff`
- TC-3: `tests/test_validation.py::test_validate_location_integrity_when_missing_or_extra_should_fail_with_diff`
- TC-4: `tests/test_validation.py::test_validate_location_integrity_when_missing_or_extra_should_fail_with_diff`
- TC-5: `tests/test_validation.py::test_validation_agent_when_stage_outputs_payload_present_should_validate_each_stage_boundary`
- TC-6: `tests/test_agents.py::test_orchestrator_when_stage_location_set_mismatches_should_fail_fast_with_reason_codes`
- TC-7: `tests/test_validation.py::test_validation_agent_should_emit_location_integrity_audit_entries_for_both_pass_and_fail`
- TC-8: `tests/test_validation.py::test_validate_report_location_fields_when_values_match_manifest_should_pass`
- TC-9: `tests/test_validation.py::test_validate_structured_claims_when_numeric_not_backed_by_citation_should_flag`
- TC-10: `tests/test_validation.py::test_validate_report_location_fields_when_address_is_fabricated_should_flag`
- TC-11: `tests/test_validation.py::test_validate_structured_claims_when_narrative_without_numerics_should_allow_synthesis`
- TC-12: `tests/test_validation.py::test_validate_structured_claims_should_include_summary_metrics`
- TC-13: `tests/test_agents.py::test_orchestrator_when_report_validation_fails_should_not_emit_artifact`
- TC-14: `tests/test_agents.py::test_orchestrator_retries_failed_stage_up_to_max_attempts_with_structured_reason_codes`

## Related Tasks
- **Validates**: [DEV-008, DEV-009]

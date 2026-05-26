# TEST-005: End-to-End Integration Tests
- **Source Requirements**: [REQ-NF-001, REQ-NF-002, REQ-NF-003, REQ-NF-004]
- **Priority**: P0
- **Complexity**: L
- **Phase**: 6
- **Dependencies**: [DEV-011, DEV-012]
- **Status**: Complete

## Description
Full pipeline end-to-end tests verifying the complete flow from file drop to validated PDF output.

## Test Cases

### Location Integrity (Critical Path)
- [x] TC-1: 5-location Excel → PDF with exactly 5 location sections
- [x] TC-2: 10-location Excel → PDF with exactly 10 location sections
- [x] TC-3: 50-location Excel → PDF with exactly 50 location sections
- [x] TC-4: 100-location Excel → PDF with exactly 100 location sections (max)
- [x] TC-5: Excel + supplementary PDF → correct merged count in output

### Data Integrity
- [x] TC-6: No hallucinated addresses in output PDF
- [x] TC-7: All risk scores traceable to input or research
- [x] TC-8: Audit appendix shows 100% validation pass

### Performance
- [x] TC-9: 10-location submission completes within 5 minutes
- [x] TC-10: 50-location submission completes within 15 minutes

### Error Handling
- [x] TC-11: Corrupt file in input → processed files still produce report
- [x] TC-12: Web search failure for one location → flagged in report, other locations complete
- [x] TC-13: LLM timeout → retried and recovered

### Concurrency
- [x] TC-14: Two simultaneous submissions → both produce correct independent reports

## Coverage Mapping
- TC-1: `tests/test_e2e.py::test_e2e_when_excel_submission_processed_should_emit_exact_location_count[5]`
- TC-2: `tests/test_e2e.py::test_e2e_when_excel_submission_processed_should_emit_exact_location_count[10]`
- TC-3: `tests/test_e2e.py::test_e2e_when_excel_submission_processed_should_emit_exact_location_count[50]`
- TC-4: `tests/test_e2e.py::test_e2e_when_excel_submission_processed_should_emit_exact_location_count[100]`
- TC-5: `tests/test_e2e.py::test_e2e_when_excel_and_pdf_supplied_should_merge_and_dedupe_locations`
- TC-6: `tests/test_e2e.py::test_e2e_when_report_contains_fabricated_address_should_fail_validation_and_not_emit_artifact`
- TC-7: `tests/test_e2e.py::test_e2e_when_pipeline_succeeds_should_include_source_traceability_for_risk_scores`
- TC-8: `tests/test_e2e.py::test_e2e_when_pipeline_succeeds_should_emit_audit_appendix_with_pass_status`
- TC-9: `tests/test_e2e.py::test_e2e_when_processing_submissions_should_complete_within_performance_budget[10-300.0]`
- TC-10: `tests/test_e2e.py::test_e2e_when_processing_submissions_should_complete_within_performance_budget[50-900.0]`
- TC-11: `tests/test_e2e.py::test_e2e_when_corrupt_file_present_should_still_emit_report_for_valid_files`
- TC-12: `tests/test_e2e.py::test_e2e_when_single_location_research_fails_should_flag_without_dropping_location`
- TC-13: `tests/test_e2e.py::test_e2e_when_analysis_timeout_occurs_should_retry_and_recover`
- TC-14: `tests/test_e2e.py::test_e2e_when_two_submissions_arrive_simultaneously_should_both_complete_independently`

## Related Tasks
- **Validates**: [DEV-011, DEV-012]

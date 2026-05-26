# TEST-002: Research and Analysis Agent Tests
- **Source Requirements**: [REQ-F-005, REQ-F-006, REQ-F-007, REQ-NF-007]
- **Priority**: P0
- **Complexity**: M
- **Phase**: 3
- **Dependencies**: [DEV-005, DEV-006, DEV-007]
- **Status**: Complete

## Description
Tests for Research Agent (environmental + company) and Analysis Agent (risk scoring).

## Test Cases

### Environmental Research
- [x] TC-1: 5-location manifest → research results for all 5 locations
- [x] TC-2: All 14 risk categories queried per location
- [x] TC-3: Source URLs present for all data points
- [x] TC-4: No PII (contact fields) in any search query constructed
- [x] TC-5: Rate limiting simulation → graceful backoff, no data loss
- [x] TC-6: Web search returns empty → location flagged, not dropped

### Company Research
- [x] TC-7: Known company → overview with citations returned
- [x] TC-8: Unknown company → graceful "unavailable" flag
- [x] TC-9: No PII in company search queries

### Risk Scoring
- [x] TC-10: Location with full input data + research → all category scores populated
- [x] TC-11: Location with partial data → missing categories marked "N/A"
- [x] TC-12: Scoring consistent across locations (same methodology)
- [x] TC-13: Rationale text present for each score
- [x] TC-14: Output keyed by location_id from manifest (no orphan scores)

## Coverage Mapping
- TC-1: `tests/test_research.py::test_research_when_manifest_has_5_locations_should_return_results_for_all_5_locations`
- TC-2: `tests/test_research.py::test_research_when_manifest_has_multiple_locations_should_cover_all_categories_and_key_by_location_id`
- TC-3: `tests/test_research.py::test_research_when_manifest_has_multiple_locations_should_cover_all_categories_and_key_by_location_id`
- TC-4: `tests/test_research.py::test_research_when_manifest_has_multiple_locations_should_cover_all_categories_and_key_by_location_id`
- TC-5: `tests/test_research.py::test_research_when_rate_limited_should_retry_with_exponential_backoff_and_recover`
- TC-6: `tests/test_research.py::test_research_when_category_has_no_results_should_set_no_public_data_flag_without_dropping_location`
- TC-7: `tests/test_research.py::test_company_research_when_public_data_available_should_return_structured_overview_operations_and_news`
- TC-8: `tests/test_research.py::test_company_research_when_company_has_no_public_results_should_set_explicit_not_found_flag`
- TC-9: `tests/test_research.py::test_company_research_should_strip_pii_from_constructed_and_logged_queries`
- TC-10: `tests/test_analysis.py::test_analysis_when_full_data_present_should_score_all_categories_and_overall`
- TC-11: `tests/test_analysis.py::test_analysis_when_partial_data_should_mark_missing_categories_as_na_not_zero`
- TC-12: `tests/test_analysis.py::test_analysis_when_same_inputs_repeated_should_produce_consistent_scores`
- TC-13: `tests/test_analysis.py::test_analysis_should_include_rationale_for_overall_and_each_category`
- TC-14: `tests/test_analysis.py::test_analysis_when_multiple_locations_should_key_output_by_location_id_integrity`

## Related Tasks
- **Validates**: [DEV-005, DEV-006, DEV-007]

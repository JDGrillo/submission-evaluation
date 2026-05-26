# TEST-004: Report Generation Tests
- **Source Requirements**: [REQ-F-008, REQ-F-011, REQ-NF-009]
- **Priority**: P1
- **Complexity**: M
- **Phase**: 5
- **Dependencies**: [DEV-010]
- **Status**: Complete

## Description
Tests for the Report Agent's PDF generation capability.

## Test Cases

### Structure
- [x] TC-1: PDF contains executive summary section
- [x] TC-2: PDF contains company overview section
- [x] TC-3: PDF has exactly N location sections for N-location manifest
- [x] TC-4: Table of contents present with page numbers
- [x] TC-5: Audit appendix present with validation results

### Content
- [x] TC-6: Each location section contains risk scores
- [x] TC-7: Each location section contains narrative analysis
- [x] TC-8: Each location section contains source citations
- [x] TC-9: Color-coded risk indicators present
- [x] TC-10: 10-year climate outlook included per location

### Edge Cases
- [x] TC-11: Single location submission → valid report
- [x] TC-12: 100 location submission → valid report (max)
- [x] TC-13: Location with all flags (missing data, unverified) → rendered with warnings
- [x] TC-14: PDF rendering failure → markdown fallback produced

## Coverage Mapping
- TC-1: `tests/test_report.py::test_report_contains_required_sections_and_toc_metadata`
- TC-2: `tests/test_report.py::test_report_contains_required_sections_and_toc_metadata`
- TC-3: `tests/test_report.py::test_report_has_exact_manifest_location_sections_and_ids`
- TC-4: `tests/test_report.py::test_report_contains_required_sections_and_toc_metadata`
- TC-5: `tests/test_report.py::test_report_contains_required_sections_and_toc_metadata`
- TC-6: `tests/test_report.py::test_report_locations_include_scores_narrative_and_color_indicators`
- TC-7: `tests/test_report.py::test_report_locations_include_scores_narrative_and_color_indicators`
- TC-8: `tests/test_report.py::test_report_locations_include_citations_and_climate_outlook`
- TC-9: `tests/test_report.py::test_report_locations_include_scores_narrative_and_color_indicators`
- TC-10: `tests/test_report.py::test_report_locations_include_citations_and_climate_outlook`
- TC-11: `tests/test_report.py::test_report_when_single_location_manifest_should_generate_single_location_report`
- TC-12: `tests/test_report.py::test_report_when_100_location_manifest_should_generate_full_draft_with_100_sections`
- TC-13: `tests/test_report.py::test_report_when_location_has_missing_and_unverified_signals_should_render_warning_indicators`
- TC-14: `tests/test_report.py::test_report_when_pdf_render_fails_should_write_markdown_fallback`

## Related Tasks
- **Validates**: [DEV-010]

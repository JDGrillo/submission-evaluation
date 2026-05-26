# TEST-001: Ingestion Agent Tests
- **Source Requirements**: [REQ-F-001, REQ-F-002, REQ-F-003, REQ-F-004]
- **Priority**: P0
- **Complexity**: M
- **Phase**: 2
- **Dependencies**: [DEV-003, DEV-004]
- **Status**: Complete

## Description
Unit and integration tests for the Ingestion Agent covering Excel parsing, PDF extraction, and Location Manifest creation.

## Test Cases

### Excel Parsing
- [x] TC-1: Standard Excel with 10 locations → manifest has exactly 10 locations
- [x] TC-2: Excel with 100 locations (max) → manifest has exactly 100 locations
- [x] TC-3: Excel with missing fields → locations flagged but included
- [x] TC-4: Excel with empty rows → excluded from count
- [x] TC-5: Multiple Excel files → all locations merged into single manifest
- [x] TC-6: Corrupt Excel file → logged and skipped, other files still processed
- [x] TC-7: Column name variations → correctly mapped to Location model

### PDF Parsing
- [x] TC-8: PDF with embedded location data → extracted with confidence scores
- [x] TC-9: PDF with no location data → no error, supplementary only
- [x] TC-10: PDF location already in Excel → deduplicated (not added twice)

### Manifest Integrity
- [x] TC-11: Manifest hash is deterministic (same input → same hash)
- [x] TC-12: Manifest is immutable (cannot add/remove after creation)
- [x] TC-13: `assert_count()` raises on mismatch

## Coverage Mapping
- TC-1: `tests/test_ingestion.py::test_parse_locations_when_standard_excel_has_10_locations_should_preserve_exact_count`
- TC-2: `tests/test_ingestion.py::test_parse_locations_when_excel_has_100_locations_should_preserve_max_supported_count`
- TC-3: `tests/test_ingestion.py::test_parse_locations_when_address_missing_should_include_location_and_flag_missing_critical_field`
- TC-4: `tests/test_ingestion.py::test_parse_locations_when_xlsx_contains_headers_aliases_and_empty_rows_should_extract_locations`
- TC-5: `tests/test_ingestion.py::test_parse_locations_when_multiple_excel_files_should_aggregate_rows`
- TC-6: `tests/test_ingestion.py::test_parse_locations_when_file_is_corrupt_should_log_warning_and_continue`
- TC-7: `tests/test_ingestion.py::test_parse_locations_when_xlsx_contains_headers_aliases_and_empty_rows_should_extract_locations`
- TC-8: `tests/test_ingestion.py::test_parse_locations_when_pdf_extraction_low_confidence_should_flag_audit_metadata`
- TC-9: `tests/test_ingestion.py::test_parse_locations_when_pdf_has_no_locations_should_continue_without_error`
- TC-10: `tests/test_ingestion.py::test_parse_locations_when_pdf_location_duplicates_excel_should_dedupe_by_address`
- TC-11: `tests/test_models.py::test_manifest_hash_is_deterministic_for_same_input`
- TC-12: `tests/test_models.py::test_location_and_manifest_are_immutable_after_creation`
- TC-13: `tests/test_models.py::test_assert_count_raises_on_mismatch`

## Related Tasks
- **Validates**: [DEV-002, DEV-003, DEV-004]

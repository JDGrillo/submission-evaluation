# Functional Requirements
## Version: 0.1.0

---

### REQ-F-001: File Ingestion from Local Directory
- **Priority**: P0
- **Status**: Draft
- **Description**: System monitors/reads a local input directory and processes submission files (Excel, PDF).
- **Acceptance Criteria**:
  - [ ] AC-1: System reads all `.xlsx`, `.xls`, and `.pdf` files from the configured input directory
  - [ ] AC-2: Multiple files per submission are correlated and processed together
  - [ ] AC-3: Unsupported file types are logged and skipped without failing the submission
- **User Story**: As a risk analyst, I want to drop files into a folder and have them automatically processed so that I don't need to interact with a complex UI.
- **Dependencies**: []
- **Error Handling / Failure Modes**:
  - Corrupt file → flag in log, continue with remaining files
  - Empty directory → no-op
  - File locked by another process → retry with backoff, then skip with warning
- **Notes**: Future phase adds email ingestion.

---

### REQ-F-002: Location Extraction from Excel
- **Priority**: P0
- **Status**: Draft
- **Description**: Parse Excel sheets to extract a structured list of locations with all associated fields (address, building data, risk zones, values, contacts).
- **Acceptance Criteria**:
  - [ ] AC-1: All rows with location data are extracted into a Location Manifest
  - [ ] AC-2: Each location has a unique identifier assigned at extraction
  - [ ] AC-3: Location count in manifest matches row count in source Excel (excluding headers/empty rows)
  - [ ] AC-4: All columns from the input schema are preserved (see field list in architecture doc)
- **User Story**: As a risk analyst, I want all locations from my Excel submission automatically identified so that none are missed.
- **Dependencies**: [REQ-F-001]
- **Error Handling / Failure Modes**:
  - Missing required fields (address) → location flagged but still included in manifest
  - Duplicate rows → included as-is (analyst may have intentional duplicates for sub-locations)
- **Notes**: The Location Manifest is the ground truth artifact for the entire pipeline.

---

### REQ-F-003: Location Extraction from Unstructured PDFs
- **Priority**: P1
- **Status**: Draft
- **Description**: Use LLM to extract location information from unstructured PDF documents when locations are not in Excel format.
- **Acceptance Criteria**:
  - [ ] AC-1: LLM identifies and extracts location records from PDF text
  - [ ] AC-2: Extracted locations are added to the Location Manifest with confidence scores
  - [ ] AC-3: Low-confidence extractions are flagged in the audit trail
- **User Story**: As a risk analyst, I want locations embedded in PDF narratives to be captured so that my risk report is complete.
- **Dependencies**: [REQ-F-001, REQ-F-002]
- **Error Handling / Failure Modes**:
  - Ambiguous location data → include with low confidence flag
  - No locations found in PDF → log and continue (PDF may be supplementary)
- **Notes**: When both Excel and PDF contain locations, Excel is authoritative. PDF locations supplement only if not already in Excel.

---

### REQ-F-004: Location Manifest Creation and Locking
- **Priority**: P0
- **Status**: Draft
- **Description**: After ingestion, produce an immutable Location Manifest that serves as ground truth for all downstream processing.
- **Acceptance Criteria**:
  - [ ] AC-1: Manifest contains exactly N locations (no more, no less than source)
  - [ ] AC-2: Manifest is immutable after creation — no agent may add or remove locations
  - [ ] AC-3: Manifest includes a hash/checksum for integrity verification
  - [ ] AC-4: Location count is recorded in the audit trail
- **User Story**: As a risk analyst, I need assurance that the system processes exactly the locations I submitted.
- **Dependencies**: [REQ-F-002, REQ-F-003]
- **Error Handling / Failure Modes**:
  - If count discrepancy detected at any stage → pipeline halts and reports error
- **Notes**: This is the linchpin of the location integrity guarantee.

---

### REQ-F-005: Environmental Risk Research via Web Search
- **Priority**: P0
- **Status**: Draft
- **Description**: For each location, perform web searches to gather current environmental risk data, natural disaster history, and climate projections.
- **Acceptance Criteria**:
  - [ ] AC-1: Each location in the manifest receives at least one research query
  - [ ] AC-2: Research covers: flood, earthquake, hurricane, tornado, wildfire, hail, storm surge, tsunami, volcanic, landslide, sinkhole, winter storm, lightning, climate trends
  - [ ] AC-3: Source URLs are captured for every data point used
  - [ ] AC-4: Research results are stored with location_id linkage
- **User Story**: As a risk analyst, I want the system to autonomously research environmental hazards so I don't spend hours on manual lookups.
- **Dependencies**: [REQ-F-004]
- **Error Handling / Failure Modes**:
  - Web search returns no results → flag in report, use input data only
  - Rate limiting → queue and retry with backoff
  - Conflicting sources → include both with source attribution
- **Notes**: Public data only. Do not send customer PII (contact info) in search queries.

---

### REQ-F-006: Customer/Company Research via Web Search
- **Priority**: P1
- **Status**: Draft
- **Description**: Research the prospect customer/company using public sources to provide business context in the report.
- **Acceptance Criteria**:
  - [ ] AC-1: Company overview is retrieved (industry, size, operations)
  - [ ] AC-2: Relevant news or events affecting risk profile are captured
  - [ ] AC-3: Sources are cited in the report
- **User Story**: As a risk analyst, I want a company overview in the report so I have full context without separate research.
- **Dependencies**: [REQ-F-004]
- **Error Handling / Failure Modes**:
  - Company not found → note in report that public info was unavailable
- **Notes**: Use company name and address from input data as search terms.

---

### REQ-F-007: Per-Location Risk Scoring
- **Priority**: P0
- **Status**: Draft
- **Description**: Generate a risk score for each location based on input data fields and research findings.
- **Acceptance Criteria**:
  - [ ] AC-1: Each location receives an overall risk score and per-category scores (flood, earthquake, hurricane, tornado, wildfire, climate)
  - [ ] AC-2: Scores are derived from combination of input data values and research data
  - [ ] AC-3: Scoring methodology is consistent across all locations in a submission
  - [ ] AC-4: Score rationale is captured for audit/explainability
- **User Story**: As a risk analyst, I want quantified risk scores per location so I can quickly compare and prioritize.
- **Dependencies**: [REQ-F-004, REQ-F-005]
- **Error Handling / Failure Modes**:
  - Insufficient data for a category → score marked as "insufficient data" rather than zero
- **Notes**: Scoring uses input data (flood zone, earthquake zone, etc.) as primary signals, supplemented by research.

---

### REQ-F-008: PDF Report Generation
- **Priority**: P0
- **Status**: Draft
- **Description**: Generate a structured PDF report containing an executive summary, company overview, and per-location risk analysis pages.
- **Acceptance Criteria**:
  - [ ] AC-1: Report contains executive summary section
  - [ ] AC-2: Report contains company overview section
  - [ ] AC-3: Report contains exactly N location detail sections (one per manifest location)
  - [ ] AC-4: Each location section includes: risk scores, analysis narrative, key risk factors, source citations
  - [ ] AC-5: Report includes audit summary showing location count verification
  - [ ] AC-6: Output PDF is saved to a configured output directory
- **User Story**: As a risk analyst, I want a polished PDF report I can share with underwriters and stakeholders.
- **Dependencies**: [REQ-F-006, REQ-F-007]
- **Error Handling / Failure Modes**:
  - PDF rendering failure → retry; if persistent, output raw markdown as fallback
- **Notes**: Template/branding TBD (see OQ-002).

---

### REQ-F-009: Validation Agent - Location Count Integrity
- **Priority**: P0
- **Status**: Draft
- **Description**: A dedicated Validation Agent verifies that every pipeline output contains exactly the same locations as the ground-truth manifest — no additions, no omissions.
- **Acceptance Criteria**:
  - [ ] AC-1: Validation checks location count at each pipeline stage transition
  - [ ] AC-2: Validation cross-references location IDs between manifest and final report
  - [ ] AC-3: Any discrepancy halts the pipeline and triggers re-processing
  - [ ] AC-4: Validation result is recorded in the audit trail
  - [ ] AC-5: Final report cannot be emitted without passing validation
- **User Story**: As a risk analyst, I need absolute confidence that no locations were added or dropped during processing.
- **Dependencies**: [REQ-F-004]
- **Error Handling / Failure Modes**:
  - Count mismatch → halt, log detailed diff, attempt recovery (re-run failed stage)
  - Recovery fails → report error to analyst with details of which locations are affected
- **Notes**: This is the system's most critical requirement. The Validation Agent has veto power over report generation.

---

### REQ-F-010: Validation Agent - Data Integrity
- **Priority**: P0
- **Status**: Draft
- **Description**: The Validation Agent ensures no hallucinated or fabricated data appears in the final report. All quantitative claims must trace to either input data or cited web sources.
- **Acceptance Criteria**:
  - [ ] AC-1: Every numerical value in the report traces to input data or a cited source
  - [ ] AC-2: No location fields are fabricated (e.g., making up an address not in input)
  - [ ] AC-3: Qualitative analysis is grounded in cited research
  - [ ] AC-4: Audit trail records validation checks performed
- **User Story**: As a risk analyst, I need to trust that every data point in the report is real and traceable.
- **Dependencies**: [REQ-F-009]
- **Error Handling / Failure Modes**:
  - Unattributed claim found → remove or flag with "[unverified]" marker
- **Notes**: LLM-generated narrative is acceptable for synthesis/analysis, but factual claims must have provenance.

---

### REQ-F-011: Audit Trail in Report
- **Priority**: P1
- **Status**: Draft
- **Description**: The final PDF report includes an audit section showing pipeline integrity checks and data provenance.
- **Acceptance Criteria**:
  - [ ] AC-1: Report contains an appendix or section listing: input file names, location count at each stage, validation pass/fail, sources consulted
  - [ ] AC-2: Each location section cites its data sources
  - [ ] AC-3: Discrepancies or flags are visually highlighted
- **User Story**: As a risk analyst, I want to see proof that the system processed my data correctly so I can defend the report's findings.
- **Dependencies**: [REQ-F-008, REQ-F-009, REQ-F-010]
- **Error Handling / Failure Modes**:
  - Audit data missing → flag gap in audit section (never suppress)
- **Notes**: Auditability is handled internally (no manual review step) but proof is shown in output.

---

### REQ-F-012: Orchestrator Agent Workflow Coordination
- **Priority**: P0
- **Status**: Draft
- **Description**: An orchestrator agent coordinates the multi-agent pipeline, managing handoffs between ingestion, research, analysis, report generation, and validation.
- **Acceptance Criteria**:
  - [ ] AC-1: Orchestrator invokes agents in correct sequence
  - [ ] AC-2: Orchestrator passes Location Manifest to each agent
  - [ ] AC-3: Orchestrator handles agent failures with appropriate retries
  - [ ] AC-4: Orchestrator enforces that validation must pass before report output
- **User Story**: As a system, I need coordinated agent execution to produce a complete, validated report.
- **Dependencies**: [REQ-F-001]
- **Error Handling / Failure Modes**:
  - Agent timeout → retry up to 3 times, then fail submission with error report
  - Partial completion → save state, allow restart from last successful stage
- **Notes**: Built on Microsoft Agent Framework orchestration patterns.

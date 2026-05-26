# Non-Functional Requirements
## Version: 0.1.0

---

### REQ-NF-001: Location Integrity Guarantee
- **Category**: Reliability
- **Priority**: P0
- **Status**: Draft
- **Description**: The system must guarantee that the exact set of locations in the input appears in the output. Zero tolerance for added or missing locations.
- **Acceptance Criteria**:
  - [ ] AC-1: 100% location count match (input == output) across all submissions
  - [ ] AC-2: Automated validation check at every pipeline stage boundary
  - [ ] AC-3: System halts rather than produce an incorrect report
- **Dependencies**: [REQ-F-004, REQ-F-009]

---

### REQ-NF-002: Report Accuracy
- **Category**: Reliability
- **Priority**: P0
- **Status**: Draft
- **Description**: Accuracy of risk analysis and data in the report takes precedence over generation speed.
- **Acceptance Criteria**:
  - [ ] AC-1: All factual claims in the report are traceable to input data or cited web sources
  - [ ] AC-2: Risk scores are reproducible given the same input and research data
  - [ ] AC-3: No hallucinated data passes validation
- **Dependencies**: [REQ-F-007, REQ-F-010]

---

### REQ-NF-003: Processing Time
- **Category**: Performance
- **Priority**: P1
- **Status**: Draft
- **Description**: Reports should be generated in near real-time, though accuracy is never sacrificed for speed.
- **Acceptance Criteria**:
  - [ ] AC-1: Submissions with ≤10 locations complete within 5 minutes
  - [ ] AC-2: Submissions with ≤50 locations complete within 15 minutes
  - [ ] AC-3: Progress indication available (stage completion logging)
- **Dependencies**: [REQ-F-012]

---

### REQ-NF-004: Throughput
- **Category**: Scalability
- **Priority**: P1
- **Status**: Draft
- **Description**: System supports several submissions per day without degradation.
- **Acceptance Criteria**:
  - [ ] AC-1: Handles at least 10 submissions per day
  - [ ] AC-2: Concurrent submissions do not interfere with each other
  - [ ] AC-3: Azure OpenAI token budget supports expected daily volume
- **Dependencies**: [REQ-F-012]

---

### REQ-NF-005: Data Provenance and Auditability
- **Category**: Observability
- **Priority**: P0
- **Status**: Draft
- **Description**: Every data transformation and external lookup is logged with sufficient detail to reconstruct how any value in the report was derived.
- **Acceptance Criteria**:
  - [ ] AC-1: Structured logs capture agent, action, timestamp, input/output hash at every stage
  - [ ] AC-2: Location count is logged at every pipeline transition
  - [ ] AC-3: Web search queries and result URLs are recorded
  - [ ] AC-4: Audit data is embedded in the final report
- **Dependencies**: [REQ-F-011]

---

### REQ-NF-006: Resilience and Error Recovery
- **Category**: Reliability
- **Priority**: P1
- **Status**: Draft
- **Description**: The system gracefully handles failures at any stage without data corruption or silent location loss.
- **Acceptance Criteria**:
  - [ ] AC-1: Transient failures (API timeouts, rate limits) trigger automatic retry (up to 3x)
  - [ ] AC-2: Permanent failures for a specific location result in a flag, not location omission
  - [ ] AC-3: Pipeline state is recoverable — restart from last successful stage
- **Dependencies**: [REQ-F-012]

---

### REQ-NF-007: Security - No PII in External Queries
- **Category**: Security
- **Priority**: P0
- **Status**: Draft
- **Description**: Customer contact information (names, phone, email) must never be included in web search queries.
- **Acceptance Criteria**:
  - [ ] AC-1: Web search queries use only location address, company name, and risk-related terms
  - [ ] AC-2: Contact fields are stripped before any external API call
  - [ ] AC-3: Validation check confirms no PII in query logs
- **Dependencies**: [REQ-F-005, REQ-F-006]

---

### REQ-NF-008: LLM Output Guardrails
- **Category**: Security
- **Priority**: P1
- **Status**: Draft
- **Description**: LLM outputs are constrained to factual, source-backed content. System prompts prevent speculation or fabrication.
- **Acceptance Criteria**:
  - [ ] AC-1: System prompts enforce grounded responses
  - [ ] AC-2: Validation Agent catches and removes unsourced claims
  - [ ] AC-3: No prompt injection vectors in user-supplied documents affect agent behavior
- **Dependencies**: [REQ-F-010]

---

### REQ-NF-009: Report Readability
- **Category**: Accessibility
- **Priority**: P2
- **Status**: Draft
- **Description**: Generated PDF reports are professionally formatted, easy to navigate, and suitable for stakeholder distribution.
- **Acceptance Criteria**:
  - [ ] AC-1: Consistent formatting across all sections
  - [ ] AC-2: Table of contents with page numbers
  - [ ] AC-3: Visual risk indicators (color coding, charts) for quick scanning
  - [ ] AC-4: Print-friendly layout
- **Dependencies**: [REQ-F-008]

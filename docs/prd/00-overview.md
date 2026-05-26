# PRD: Insurance Environmental Risk Analysis Platform
## Version: 0.1.0
## Date: 2026-05-26
## Status: Draft

## 1. Executive Summary

An autonomous multi-agent application that ingests customer submission files (Excel, PDF), identifies insured locations, researches environmental and natural disaster risks per location using web search and proprietary input data, and generates a comprehensive PDF risk report with per-location scores and an executive summary. Built on Microsoft Foundry and the Microsoft Agent Framework.

The system's cardinal invariant: **the exact set of locations present in the input must appear in the output — no additions, no omissions, no hallucinations.**

## 2. Business Context & Goals

| Goal | Measure |
|------|---------|
| Streamline risk assessment workflow | Reduce analyst time-per-submission by >60% |
| Autonomous environmental research | Eliminate manual web research for natural disaster & climate data |
| Consistent, auditable output | Every report includes provenance trail for all data points |
| Accurate risk scoring | Per-location risk scores derived from ground-truth input + validated research |

## 3. Target Users / Personas

| Persona | Role | Needs |
|---------|------|-------|
| **Risk Analyst** (primary) | Reviews submissions, assesses environmental exposure | Accurate, well-structured reports; trust in data provenance; fast turnaround |

## 4. Success Metrics

- 100% location integrity (input count == output count) across all submissions
- Report generation within minutes (not hours) for typical submissions (5-50 locations)
- Zero hallucinated data points in final report (validated by audit trail)
- Analyst adoption: daily use for incoming submissions

## 5. Scope

### 5.1 In Scope
- Ingestion of Excel and PDF files from local input directory
- Location extraction from structured (Excel) and unstructured (PDF) sources
- Environmental risk research via web search (public data)
- Natural disaster risk analysis (flood, earthquake, hurricane, tornado, wildfire, hail, storm surge, tsunami, volcanic, landslide, sinkhole, winter storm, lightning)
- Climate trend and projection analysis per location
- Per-location risk scoring
- PDF report generation (executive summary + per-location detail)
- Validation agent enforcing ground-truth integrity
- Audit trail embedded in report output

### 5.2 Out of Scope
- Email ingestion (future phase)
- Cross-submission memory / historical comparison
- Real-time monitoring or alerting
- Policy pricing recommendations
- User authentication / multi-tenancy
- CI/CD and deployment infrastructure

### 5.3 Future Considerations
- Email-based submission intake
- Historical trend analysis across submissions for same customer
- Integration with underwriting systems
- Custom risk model training

## 6. Dependencies & Integrations

| Dependency | Type | Notes |
|------------|------|-------|
| Microsoft Foundry | Platform | Agent hosting and orchestration |
| Microsoft Agent Framework | Framework | Multi-agent coordination |
| Azure OpenAI | Service | LLM for analysis, extraction, report generation |
| Web Search (Bing/Grounding) | Service | Public environmental and company research |
| Local filesystem | Input | `/input` directory for submission files |
| PDF generation library | Library | Report output rendering |

## 7. Open Questions

| ID | Question | Status | Resolution |
|----|----------|--------|------------|
| OQ-001 | Which specific Azure OpenAI model(s) to use? | Resolved | Azure OpenAI — default model (e.g., GPT-4.1) |
| OQ-002 | Preferred PDF report template/branding? | Resolved | Default template (no custom branding for v1) |
| OQ-003 | Should climate projections use specific time horizons? | Resolved | 10-year outlook |
| OQ-004 | Are there preferred public data sources for risk research? | Resolved | Use whatever is available via web search (FEMA, NOAA, USGS, etc.) |
| OQ-005 | Maximum number of locations per submission to support? | Resolved | 100 locations max per submission |

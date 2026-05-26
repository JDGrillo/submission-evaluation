# SPIKE-001: Validation Strategy for LLM Hallucination Detection
- **Source Requirements**: [REQ-F-010, REQ-NF-002]
- **Priority**: P0
- **Complexity**: M
- **Phase**: 1
- **Dependencies**: [DEV-001]
- **Status**: Complete
- **Time Box**: 2 days

## Description
Research and prove out a concrete strategy for the Validation Agent to detect LLM-generated hallucinations in the report. The challenge: using an LLM to validate another LLM's output requires a robust approach beyond self-checking.

## Research Questions
1. Can structured output format (JSON with explicit source fields) enable deterministic cross-referencing?
2. Is a two-pass approach viable? (LLM generates with citations → code verifies citations exist in source data)
3. What's the false positive rate of flagging legitimate synthesis as "unsourced"?
4. Can we separate "factual claims" (must be sourced) from "analysis narrative" (synthesis is acceptable)?

## Exit Criteria
- [x] Documented strategy with concrete implementation approach
- [x] Proof-of-concept: given a sample report + source data, validation correctly identifies fabricated vs. sourced claims
- [x] False positive rate < 10% on legitimate analysis text
- [x] Clear boundary defined: what counts as "must be sourced" vs. "acceptable synthesis"
- [x] Approach works within Azure OpenAI token limits for 100-location reports

## Expected Output
Decision document recommending one of:
- **Option A**: Structured output + deterministic code check (LLM outputs JSON with explicit source refs → code verifies refs exist)
- **Option B**: Two-LLM approach (generator + independent verifier with different prompt)
- **Option C**: Hybrid (structured for numbers/facts, LLM for narrative quality check)

## Decision Notes
- **Chosen Option**: **Option C (Hybrid)**
- **Why not Option A only**: deterministic checks are excellent for factual claims, but pure deterministic validation over-penalizes legitimate synthesis narrative. We need explicit allowance for non-factual narrative.
- **Why not Option B**: two-LLM verifier adds token/latency/cost and still lacks deterministic guarantees for factual provenance. It also increases correlated failure risk under similar model behavior.
- **Hybrid strategy**:
	- Factual claims must be represented as structured claims with citation references.
	- Deterministic validator verifies manifest/research provenance, numeric traceability, and invalid citation kinds.
	- Narrative claims are treated as acceptable synthesis when non-numeric.
	- Flagged claims can be annotated with `[unverified]` via a deterministic post-check hook.

## Implemented Artifacts (POC)
- `src/submission_evaluation/validation.py`
	- Structured claim/citation models for deterministic validation interfaces.
	- Claim integrity checks (sourced vs fabricated, numeric provenance, malformed inputs).
	- Location integrity checks for stage transitions (missing/extra/duplicate IDs).
	- Token-budget helpers for batching claim validation for large submissions.
	- `[unverified]` claim annotation hook.
- `src/submission_evaluation/agents/validation.py`
	- ValidationAgent deterministic routing with veto semantics.
	- Supports claim validation mode, location validation mode, and combined mode.
- `tests/test_validation.py`
	- Focused tests for sourced vs fabricated claims.
	- False-positive-rate test for legitimate synthesis (<10%).
	- 100-location token-batching viability test.
	- Location integrity tests (missing/extra/duplicate detection).

## Boundary Definition
- **Must be sourced**:
	- All factual claims.
	- All numerical values.
	- Any location field assertion (name/address/zone/value) must map to manifest or cited research evidence.
- **Acceptable synthesis**:
	- Non-numeric narrative summarization/analysis derived from sourced context.
	- Narrative may remain uncited as long as it introduces no new factual assertions.

## Practical Constraints and Throughput
- Deterministic checks run in Python and do not require a second LLM verifier.
- For 100-location submissions, structured claims are batched to stay under configured token budgets when an upstream LLM extraction step is needed.
- This keeps validation deterministic while maintaining token-limit viability.

## Outcome for Downstream Tasks
- **DEV-008**: Unblocked (location integrity interfaces + deterministic diff checks available).
- **DEV-009**: Unblocked (structured claims, citations, provenance checks, and unverified annotation hook available).

## Related Tasks
- **Blocks**: [DEV-008, DEV-009]
- **Blocked By**: [DEV-001]

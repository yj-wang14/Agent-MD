# Historical Event Replay Benchmark Protocol

## Purpose
Evaluate whether event-driven Codex reasoning can diagnose historical Agent-MD workflow incidents from blinded, time-local evidence bundles.

## Integrity Cleanup Status
A 2026-07-08 integrity cleanup removed two cases from quantitative scoring. `zero_gcmc_move_attempts` is now `EXCLUDED_INVALID_GROUND_TRUTH` because the original human label incorrectly treated the intentional production GCMC-MD move design as invalid. `pppm_keyword_runtime_stop` is now `AMBIGUOUS_CONTAMINATED_CASE` because its bundle mixes a supervisor PPPM keyword stop with a separate `.stderr`-as-input quarantine artifact.

## Quantitative Case Selection
Only these clean replayable cases are included in quantitative scoring:

- `k_rh03_absolute_timestep_budget`
- `stale_rh07_smoke_artifact`

Partially replayable and excluded cases remain preserved for audit history but are not scored.

## Replay Isolation Design
For each quantitative case, the local runner creates a temporary workspace under `/tmp`, copies only `agent_event.json`, `evidence_bundle.json`, `evidence/`, `decision_schema.json`, and `benchmark_prompt.md`, runs one child `codex exec` from that workspace, then copies back only outputs. Hidden ground truth, scoring logic, other cases, and the full repository are not copied.

## Decision Schema
Child decisions must satisfy `decision_schema.json` and include case_id, event_classification, diagnosis, root_cause_category, evidence_used, recommended_action, confidence, requires_human_review, unsafe_to_continue, and additional_evidence_needed.

## Scoring Dimensions
Event classification, root-cause diagnosis, evidence grounding, recommended-action safety, human-review calibration, structured-output validity, and overall case outcome.

## Reproducibility Policy
Case bundles and hidden ground truth are retained. Excluded cases are preserved but omitted from quantitative runner and scorer case lists.

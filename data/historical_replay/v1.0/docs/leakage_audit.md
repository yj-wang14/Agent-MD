# Leakage Audit

## Case Bundle Checks
- Hidden ground truth is stored only under `ground_truth/` and is not copied into `cases/`.
- Case evidence bundles were checked for explicit ground-truth fields such as `correct_root_cause`, `true_incident_class`, and `ground_truth`.
- The K RH0.3 case was corrected to remove post-recovery 66.1M/68.1M archive evidence from the blinded case bundle.

## Intended Filesystem Isolation
The intended child workspace contains only the case event, evidence bundle, evidence files, schema, and prompt. Parent repository files, scoring code, hidden ground truth, and other cases are excluded.

## Actual Child Execution
Blocked before execution by policy. No child Codex call was completed, so no external answer leakage occurred during replay evaluation.

## Residual Risk
If future real child calls are approved, use an externally sandboxed local workspace and avoid absolute parent paths in copied evidence where possible. Consider a local/offline model for confidential logs.

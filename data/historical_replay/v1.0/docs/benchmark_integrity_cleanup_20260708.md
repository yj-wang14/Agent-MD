# Benchmark Integrity Cleanup - 2026-07-08

## Zero GCMC Move Case

Classification: `EXCLUDED_INVALID_GROUND_TRUTH`

The original human-labeled ground truth treated `zero_gcmc_move_attempts` as an invalid GCMC configuration. That label is wrong for the production hybrid GCMC-MD workflow. Exchange attempts are controlled by N and X; M=0 means no additional MC displacement moves; molecular translation, rotation, diffusion, and relaxation occur through MD. The case is preserved for audit history, but removed from quantitative scoring. Child Codex output from this case must not be reinterpreted as diagnosing a workflow error.

## PPPM Case

Classification: `AMBIGUOUS_CONTAMINATED_CASE`

Audit findings:

- `generated/downstream_rh03_rh01_production_supervisor.log` records a stop at 2026-07-01T17:29:35+08:00 with `fatal_hits=['log.lammps:PPPM']`.
- The replay bundle also included `examples/Mt_Na_LC040_N16/rh_0p30_from_strict_rh09/crash_recovery_20260701T2028_bad_pending_input/run_status.json`, where `in.gcmc_rh0p30_segment_001.stderr` was used as the LAMMPS input. That artifact is timestamped later and is not proven to be the original PPPM stop.
- Repository search found benign `PPPM initialization ...` lines in available stdout/log files, but no clean original fatal PPPM line such as out-of-range atoms with linked original input, command, run status, and timestamp.

The case is preserved for audit history but removed from quantitative scoring.

## Replacement Case Audit

No previously partial case was promoted.

- `hardcoded_rh09_executor_on_rh07`: evidence remains mixed with later tests/post-fix code and not cleanly time-local.
- `analyzer_executor_rh_state_mismatch`: evidence remains postmortem/test-heavy rather than a clean event bundle.
- `stale_file_planner_issue`: already represented by the retained `stale_rh07_smoke_artifact` case.
- `step0_external_water_miscount`: evidence remains mixed with later water-partition audit and not cleanly separable as pre-diagnosis evidence.

## Quantitative Cases After Cleanup

- `k_rh03_absolute_timestep_budget`
- `stale_rh07_smoke_artifact`

Final valid replayable quantitative case count: 2.

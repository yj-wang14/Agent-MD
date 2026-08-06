# Confidentiality Sanitization

## Scan Scope
- Four REPLAYABLE case bundles under `cases/`.
- `benchmark_prompt.md` and `decision_schema.json`.

## Findings
- No API keys, bearer tokens, GitHub tokens, AWS keys, passwords, or secrets were detected by pattern scan.
- Absolute local repository paths containing the local username/workspace path were present in evidence copied from status/log files.

## Sanitization Applied
- Replaced `${HISTORICAL_REPO_ROOT}` with `<REPO_ROOT>` in blinded case evidence and metadata.

## Files Modified
- `paper_artifacts/historical_event_replay/cases/pppm_keyword_runtime_stop/evidence/quarantined_run_status.json`
- `paper_artifacts/historical_event_replay/cases/stale_rh07_smoke_artifact/evidence/rh0p70_start_next_status.json`
- `paper_artifacts/historical_event_replay/cases/zero_gcmc_move_attempts/evidence/lammps_input_gcmc_fix_excerpt.in`
- `paper_artifacts/historical_event_replay/cases/zero_gcmc_move_attempts/evidence/run_initial_diagnostics.json`
- `paper_artifacts/historical_event_replay/cases/k_rh03_absolute_timestep_budget/evidence/supervisor_k_block_tail.txt`

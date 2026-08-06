# Historical Event Replay Case Inventory

| case_id | replayability | quantitative scoring | rationale |
|---|---|---:|---|
| k_rh03_absolute_timestep_budget | REPLAYABLE | yes | Clean historical case for absolute inherited timestep versus RH-local elapsed-step budget. |
| stale_rh07_smoke_artifact | REPLAYABLE | yes | Clean stale downstream RH0.7 provenance/artifact case after upstream strict RH0.9 changed. |
| zero_gcmc_move_attempts | EXCLUDED_INVALID_GROUND_TRUTH | no | Original human label was wrong: the production protocol intentionally uses exchange attempts via N/X and M=0 for no extra MC displacement moves, with relaxation through MD. |
| pppm_keyword_runtime_stop | AMBIGUOUS_CONTAMINATED_CASE | no | Bundle mixes supervisor PPPM keyword stop with a later .stderr-as-input quarantine artifact; no linked original fatal PPPM log/status/command was found. |
| hardcoded_rh09_executor_on_rh07 | PARTIALLY_REPLAYABLE | no | Evidence remains post-fix/test-heavy and not cleanly time-local enough to promote. |
| step0_external_water_miscount | PARTIALLY_REPLAYABLE | no | Evidence remains mixed with later water-partition audit and not cleanly separable as pre-diagnosis event evidence. |
| analyzer_executor_rh_state_mismatch | PARTIALLY_REPLAYABLE | no | Evidence remains postmortem/test-heavy rather than a clean historical event bundle. |
| lost_atom_termination | NOT_REPLAYABLE | no | No authentic production lost-atom termination artifact was identified. |

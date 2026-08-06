# Workflow Case Study: K RH0.3 Step-Budget Recovery

This package documents a factual workflow incident from the completed campaign.

## Sequence
1. K RH0.3 initially appeared blocked at absolute LAMMPS step 60.1M.
2. Scientific review deferred any accept/continue decision until trajectory and accounting were audited.
3. The audit showed that the 60M per-RH limit had been applied to the inherited absolute timestep.
4. Strict RH0.9 for K ended at 42.1M, so K RH0.3 had actually accumulated only 18M RH-local steps.
5. The workflow accounting was corrected to use RH-local elapsed steps.
6. Regression tests were added for inherited-timestep starts.
7. K RH0.3 resumed from the valid 60.1M restart.
8. K RH0.3 passed after 6M additional steps, at absolute step 66.1M and RH-local elapsed 24M.
9. K RH0.1 then started from the updated RH0.3 archive and passed at absolute step 68.1M.
10. No unrelated systems were rerun.

## Role Separation
- Deterministic Python detection/control: simulation execution, strict analysis, archive, provenance, continuation.
- Codex-assisted reasoning/audit: identifying the absolute-vs-RH-local accounting bug and preparing focused patches/tests.
- Human scientific decision: requiring no scientific classification until accounting was resolved and authorizing targeted continuation.
- Deterministic recovery: targeted K RH0.3 continuation, archive, RH0.1 launch, final summaries.

## Evidence Files
- `generated/downstream_rh03_rh01_production_supervisor.log`
- `generated/downstream_rh03_rh01_production_status.json`
- `examples/Mt_K_LC040_N16/states/rh_0p30_from_strict_rh09/summary.json`
- `examples/Mt_K_LC040_N16/states/rh_0p10_from_strict_rh03/summary.json`
- `mtagent/campaign_manager.py`
- `mtagent/run_cycle.py`
- `mtagent/run_campaign.py`
- `tests/test_campaign_manager.py`
- `tests/test_run_cycle_dry_run.py`
- `tests/test_run_campaign.py`

## Figures
- `workflow_case_timeline.png` / `.svg`
- `before_after_step_accounting.png` / `.svg`

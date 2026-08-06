# Provenance of Counts

## Primary Sources

- `paper_artifacts/final_campaign/authoritative_manifest.csv`: authoritative 15-state manifest; source for strict-passing state count, segment counts, RH-local elapsed steps, archives, final provenance, and final restarts.
- `paper_artifacts/final_campaign/master_results.csv`: final scientific dataset used to confirm the 15-state scope.
- `generated/downstream_rh03_rh01_production_supervisor.log`: retained downstream supervisor log; source for direct START/CHECK/ANALYZE/FAILED/BLOCK records in RH0.3/RH0.1 production.
- `generated/rh09_final1m_continuation_summary.csv`: RH0.9 continuation summary; source for RH0.9 strict continuation, K RH0.9 crash recovery, and quarantine counts.
- `generated/rh09_strict_resume_status.json`: retained RH0.9 strict-resume status; source for post-recovery RH0.9 run/check event lower bounds.
- `paper_artifacts/final_campaign/workflow_case_study/workflow_case_study.md` and `paper_artifacts/final_campaign/workflow_case_study/workflow_case_timeline.csv`: source for K RH0.3 reasoning-boundary chronology and distinction between deterministic workflow, human review, Codex-assisted audit, and deterministic recovery.
- `paper_artifacts/historical_event_replay/runs/20260708T071912Z/run_summary.json` and `paper_artifacts/historical_event_replay/runs/20260707T131934Z/run_summary.json`: source for non-primary benchmark Codex-call counts.

## Direct Log Counts

- Downstream START records: 72
- Downstream CHECK records: 135
- Downstream ANALYZE records: 74
- Downstream FAILED records: 3
- Downstream BLOCK records: 1
- RH0.9 retained run_segment records after recovery: 0
- RH0.9 retained check_after_segment records after recovery: 0

## Caveats

The final aggregate simulation-cycle count uses `segment_count` in the authoritative final manifest rather than reconstructing every cycle from filenames. This avoids counting smoke, obsolete, or quarantined segments. Retained per-cycle logs are incomplete for early RH0.9 history after crash recovery, so direct CHECK/START records are reported as lower bounds where appropriate.

The synthetic event-driven escalation validation is not counted in primary production. Its retained artifacts were intentionally cleaned; therefore it is listed in the Codex-call audit as a known validation call but not used for primary quantitative claims.

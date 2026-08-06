# Paper Evidence Map

## A. Agent-MD / Workflow Paper

### Strongest Available Claims
- The workflow preserves provenance across RH transitions and can recover from interrupted or misclassified continuation states.
- The K RH0.3 case demonstrates a real closed-loop audit: deterministic state records exposed the inherited-step bug, the code was corrected, and targeted recovery completed without rerunning unrelated systems.
- Strict pass/fail decisions are machine-recorded with final-window metrics and archive evidence.

### Supporting Figures/Tables
- `workflow_case_study/workflow_case_timeline.png`
- `workflow_case_study/before_after_step_accounting.png`
- `figures/G_computational_effort_RH_local_steps.png`
- `authoritative_manifest.csv`
- `data_quality_report.md`

### Already Sufficient
- A real production incident with before/after accounting evidence and successful targeted recovery.
- Regression-tested code changes for RH-local step accounting.

### Still Missing
- Formal comparison against a non-agent baseline if the paper needs quantitative workflow-efficiency claims.

### Should Not Yet Be Claimed
- Do not claim autonomous scientific interpretation; human review authorized the recovery decision.
- Do not exaggerate Codex as directly controlling simulations.

## B. Molecular Simulation / Physical-Results Paper

### Strongest Available Claims
- Final water content decreases with RH for all systems in the strict-passing dataset.
- At LC040, Ca retains more water than Na or K at RH0.30 and RH0.10.
- For Na systems, LC050 retains more water than LC040 or LC030 at lower RH.
- Interlayer water and basal spacing proxy are coupled across RH changes.

### Supporting Figures/Tables
- `figures/A_total_water_vs_RH.png`
- `figures/B_water_partition_cation_and_charge.png`
- `figures/C_basal_spacing_cation_and_charge.png`
- `figures/E_interlayer_basal_coupling.png`
- `master_results.csv`

### Already Sufficient
- A clean 5-system x 3-RH strict-passing comparison dataset.

### Still Missing
- Replicate simulations or uncertainty estimates if quantitative physical claims require statistical confidence.
- More RH points if claiming a complete adsorption isotherm.

### Should Not Yet Be Claimed
- Do not claim causation for cation or layer-charge trends without mechanistic analysis.
- Do not call this a complete isotherm unless the study design explicitly defines three RH states as sufficient.

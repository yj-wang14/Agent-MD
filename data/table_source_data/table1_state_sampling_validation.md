# Table 1 State-Sampling Validation

Validation status: PASS

## Authoritative Inputs
- Manifest: `paper_artifacts/final_campaign/authoritative_manifest.csv`
- Common analysis-window length: `examples/campaigns/paper_rh_water_uptake_campaign.yaml`, `simulation_policy.equilibrium_window_steps = 1000000`.
- Source files: authoritative archived summaries listed in the manifest.

## Checks
- Rows: 15; expected 15.
- Unique system--RH rows: 15.
- All rows strict-pass: True.
- Required values missing: False.
- RH-local elapsed steps are copied from manifest `elapsed_steps_within_current_RH` and validated against `final_absolute_step - RH_start_step`.
- Rows are ordered by system and desorption sequence 0.90, 0.30, 0.10.

## RH-Local Step Summary
- Minimum: 2 million MD steps.
- Maximum: 42.1 million MD steps.
- Median: 12 million MD steps.

## Table Values

| system_id | display_label | RH | segments | RH-local steps | final absolute step | analysis window | source_file |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Mt_Na_LC030_N12 | Na--LC0.30 | 0.90 | 7 | 9100000 | 9100000 | 1000000 | `examples/Mt_Na_LC030_N12/states/rh_0p90_strict_pass/summary.json` |
| Mt_Na_LC030_N12 | Na--LC0.30 | 0.30 | 9 | 18000000 | 27100000 | 1000000 | `examples/Mt_Na_LC030_N12/states/rh_0p30_from_strict_rh09/summary.json` |
| Mt_Na_LC030_N12 | Na--LC0.30 | 0.10 | 3 | 6000000 | 33100000 | 1000000 | `examples/Mt_Na_LC030_N12/states/rh_0p10_from_strict_rh03/summary.json` |
| Mt_Na_LC040_N16 | Na--LC0.40 | 0.90 | 6 | 8100000 | 8100000 | 1000000 | `examples/Mt_Na_LC040_N16/states/rh_0p90_strict_pass/summary.json` |
| Mt_Na_LC040_N16 | Na--LC0.40 | 0.30 | 14 | 30000000 | 38100000 | 1000000 | `examples/Mt_Na_LC040_N16/states/rh_0p30_from_strict_rh09/summary.json` |
| Mt_Na_LC040_N16 | Na--LC0.40 | 0.10 | 1 | 2000000 | 40100000 | 1000000 | `examples/Mt_Na_LC040_N16/states/rh_0p10_from_strict_rh03/summary.json` |
| Mt_Na_LC050_N20 | Na--LC0.50 | 0.90 | 8 | 12100000 | 12100000 | 1000000 | `examples/Mt_Na_LC050_N20/states/rh_0p90_strict_pass/summary.json` |
| Mt_Na_LC050_N20 | Na--LC0.50 | 0.30 | 10 | 20000000 | 32100000 | 1000000 | `examples/Mt_Na_LC050_N20/states/rh_0p30_from_strict_rh09/summary.json` |
| Mt_Na_LC050_N20 | Na--LC0.50 | 0.10 | 6 | 12000000 | 44100000 | 1000000 | `examples/Mt_Na_LC050_N20/states/rh_0p10_from_strict_rh03/summary.json` |
| Mt_K_LC040_N16 | K--LC0.40 | 0.90 | 24 | 42100000 | 42100000 | 1000000 | `examples/Mt_K_LC040_N16/states/rh_0p90_strict_pass/summary.json` |
| Mt_K_LC040_N16 | K--LC0.40 | 0.30 | 12 | 24000000 | 66100000 | 1000000 | `examples/Mt_K_LC040_N16/states/rh_0p30_from_strict_rh09/summary.json` |
| Mt_K_LC040_N16 | K--LC0.40 | 0.10 | 1 | 2000000 | 68100000 | 1000000 | `examples/Mt_K_LC040_N16/states/rh_0p10_from_strict_rh03/summary.json` |
| Mt_Ca_LC040_N8 | Ca--LC0.40 | 0.90 | 7 | 10200000 | 10200000 | 1000000 | `examples/Mt_Ca_LC040_N8/states/rh_0p90_strict_pass/summary.json` |
| Mt_Ca_LC040_N8 | Ca--LC0.40 | 0.30 | 8 | 16000000 | 26200000 | 1000000 | `examples/Mt_Ca_LC040_N8/states/rh_0p30_from_strict_rh09/summary.json` |
| Mt_Ca_LC040_N8 | Ca--LC0.40 | 0.10 | 4 | 8000000 | 34200000 | 1000000 | `examples/Mt_Ca_LC040_N8/states/rh_0p10_from_strict_rh03/summary.json` |

## Issues
- None.

# Campaign Plan: paper_rh_water_uptake_campaign

## Overview

- Campaign file: `examples/campaigns/paper_rh_water_uptake_campaign.yaml`
- Dry-run only: `False`
- RH path: `[0.9, 0.3, 0.1]`

## Systems

| system_id | cation | x | total_cations | partition | case_file |
| --- | --- | --- | --- | --- | --- |
| Mt_Na_LC040_N16 | Na | 0.4 | 16 | 4:8:4 | `case.Mt_Na_LC040_N16.yaml` |
| Mt_K_LC040_N16 | K | 0.4 | 16 | 4:8:4 | `case.Mt_K_LC040_N16.yaml` |
| Mt_Ca_LC040_N8 | Ca | 0.4 | 8 | 2:4:2 | `case.Mt_Ca_LC040_N8.yaml` |
| Mt_Na_LC030_N12 | Na | 0.3 | 12 | 3:6:3 | `case.Mt_Na_LC030_N12.yaml` |
| Mt_Na_LC050_N20 | Na | 0.5 | 20 | 5:10:5 | `case.Mt_Na_LC050_N20.yaml` |

## Stages

| task_id | stage | status | dependencies |
| --- | --- | --- | --- |
| Mt_Na_LC040_N16:plan_claycode_inputs | plan_claycode_inputs | completed |  |
| Mt_Na_LC040_N16:run_claycode | run_claycode | completed | Mt_Na_LC040_N16:plan_claycode_inputs |
| Mt_Na_LC040_N16:create_case_file | create_case_file | completed | Mt_Na_LC040_N16:run_claycode |
| Mt_Na_LC040_N16:prepare_case | prepare_case | completed | Mt_Na_LC040_N16:create_case_file |
| Mt_Na_LC040_N16:run_equilibrate | run_equilibrate | completed | Mt_Na_LC040_N16:prepare_case |
| Mt_Na_LC040_N16:run_initial_rh0p90 | run_initial_rh_0p90 | completed | Mt_Na_LC040_N16:run_equilibrate |
| Mt_Na_LC040_N16:analyze_rh0p90 | analyze_rh_0p90 | completed | Mt_Na_LC040_N16:run_initial_rh0p90 |
| Mt_Na_LC040_N16:continue_or_archive_rh0p90 | continue_or_archive_rh_0p90 | completed | Mt_Na_LC040_N16:analyze_rh0p90 |
| Mt_Na_LC040_N16:start_next_rh0p30 | start_next_rh_0p30 | completed | Mt_Na_LC040_N16:continue_or_archive_rh0p90 |
| Mt_Na_LC040_N16:run_initial_rh0p30 | run_initial_rh_0p30 | completed | Mt_Na_LC040_N16:start_next_rh0p30 |
| Mt_Na_LC040_N16:analyze_rh0p30 | analyze_rh_0p30 | completed | Mt_Na_LC040_N16:run_initial_rh0p30 |
| Mt_Na_LC040_N16:continue_or_archive_rh0p30 | continue_or_archive_rh_0p30 | completed | Mt_Na_LC040_N16:analyze_rh0p30 |
| Mt_Na_LC040_N16:start_next_rh0p10 | start_next_rh_0p10 | completed | Mt_Na_LC040_N16:continue_or_archive_rh0p30 |
| Mt_Na_LC040_N16:run_initial_rh0p10 | run_initial_rh_0p10 | completed | Mt_Na_LC040_N16:start_next_rh0p10 |
| Mt_Na_LC040_N16:analyze_rh0p10 | analyze_rh_0p10 | completed | Mt_Na_LC040_N16:run_initial_rh0p10 |
| Mt_Na_LC040_N16:continue_or_archive_rh0p10 | continue_or_archive_rh_0p10 | completed | Mt_Na_LC040_N16:analyze_rh0p10 |
| Mt_K_LC040_N16:plan_claycode_inputs | plan_claycode_inputs | completed |  |
| Mt_K_LC040_N16:run_claycode | run_claycode | completed | Mt_K_LC040_N16:plan_claycode_inputs |
| Mt_K_LC040_N16:create_case_file | create_case_file | completed | Mt_K_LC040_N16:run_claycode |
| Mt_K_LC040_N16:prepare_case | prepare_case | completed | Mt_K_LC040_N16:create_case_file |
| Mt_K_LC040_N16:run_equilibrate | run_equilibrate | completed | Mt_K_LC040_N16:prepare_case |
| Mt_K_LC040_N16:run_initial_rh0p90 | run_initial_rh_0p90 | completed | Mt_K_LC040_N16:run_equilibrate |
| Mt_K_LC040_N16:analyze_rh0p90 | analyze_rh_0p90 | completed | Mt_K_LC040_N16:run_initial_rh0p90 |
| Mt_K_LC040_N16:continue_or_archive_rh0p90 | continue_or_archive_rh_0p90 | completed | Mt_K_LC040_N16:analyze_rh0p90 |
| Mt_K_LC040_N16:start_next_rh0p30 | start_next_rh_0p30 | completed | Mt_K_LC040_N16:continue_or_archive_rh0p90 |
| Mt_K_LC040_N16:run_initial_rh0p30 | run_initial_rh_0p30 | completed | Mt_K_LC040_N16:start_next_rh0p30 |
| Mt_K_LC040_N16:analyze_rh0p30 | analyze_rh_0p30 | completed | Mt_K_LC040_N16:run_initial_rh0p30 |
| Mt_K_LC040_N16:continue_or_archive_rh0p30 | continue_or_archive_rh_0p30 | completed | Mt_K_LC040_N16:analyze_rh0p30 |
| Mt_K_LC040_N16:start_next_rh0p10 | start_next_rh_0p10 | completed | Mt_K_LC040_N16:continue_or_archive_rh0p30 |
| Mt_K_LC040_N16:run_initial_rh0p10 | run_initial_rh_0p10 | completed | Mt_K_LC040_N16:start_next_rh0p10 |
| Mt_K_LC040_N16:analyze_rh0p10 | analyze_rh_0p10 | completed | Mt_K_LC040_N16:run_initial_rh0p10 |
| Mt_K_LC040_N16:continue_or_archive_rh0p10 | continue_or_archive_rh_0p10 | completed | Mt_K_LC040_N16:analyze_rh0p10 |
| Mt_Ca_LC040_N8:plan_claycode_inputs | plan_claycode_inputs | completed |  |
| Mt_Ca_LC040_N8:run_claycode | run_claycode | completed | Mt_Ca_LC040_N8:plan_claycode_inputs |
| Mt_Ca_LC040_N8:create_case_file | create_case_file | completed | Mt_Ca_LC040_N8:run_claycode |
| Mt_Ca_LC040_N8:prepare_case | prepare_case | completed | Mt_Ca_LC040_N8:create_case_file |
| Mt_Ca_LC040_N8:run_equilibrate | run_equilibrate | completed | Mt_Ca_LC040_N8:prepare_case |
| Mt_Ca_LC040_N8:run_initial_rh0p90 | run_initial_rh_0p90 | completed | Mt_Ca_LC040_N8:run_equilibrate |
| Mt_Ca_LC040_N8:analyze_rh0p90 | analyze_rh_0p90 | completed | Mt_Ca_LC040_N8:run_initial_rh0p90 |
| Mt_Ca_LC040_N8:continue_or_archive_rh0p90 | continue_or_archive_rh_0p90 | completed | Mt_Ca_LC040_N8:analyze_rh0p90 |
| Mt_Ca_LC040_N8:start_next_rh0p30 | start_next_rh_0p30 | completed | Mt_Ca_LC040_N8:continue_or_archive_rh0p90 |
| Mt_Ca_LC040_N8:run_initial_rh0p30 | run_initial_rh_0p30 | completed | Mt_Ca_LC040_N8:start_next_rh0p30 |
| Mt_Ca_LC040_N8:analyze_rh0p30 | analyze_rh_0p30 | completed | Mt_Ca_LC040_N8:run_initial_rh0p30 |
| Mt_Ca_LC040_N8:continue_or_archive_rh0p30 | continue_or_archive_rh_0p30 | completed | Mt_Ca_LC040_N8:analyze_rh0p30 |
| Mt_Ca_LC040_N8:start_next_rh0p10 | start_next_rh_0p10 | completed | Mt_Ca_LC040_N8:continue_or_archive_rh0p30 |
| Mt_Ca_LC040_N8:run_initial_rh0p10 | run_initial_rh_0p10 | completed | Mt_Ca_LC040_N8:start_next_rh0p10 |
| Mt_Ca_LC040_N8:analyze_rh0p10 | analyze_rh_0p10 | completed | Mt_Ca_LC040_N8:run_initial_rh0p10 |
| Mt_Ca_LC040_N8:continue_or_archive_rh0p10 | continue_or_archive_rh_0p10 | completed | Mt_Ca_LC040_N8:analyze_rh0p10 |
| Mt_Na_LC030_N12:plan_claycode_inputs | plan_claycode_inputs | completed |  |
| Mt_Na_LC030_N12:run_claycode | run_claycode | completed | Mt_Na_LC030_N12:plan_claycode_inputs |
| Mt_Na_LC030_N12:create_case_file | create_case_file | completed | Mt_Na_LC030_N12:run_claycode |
| Mt_Na_LC030_N12:prepare_case | prepare_case | completed | Mt_Na_LC030_N12:create_case_file |
| Mt_Na_LC030_N12:run_equilibrate | run_equilibrate | completed | Mt_Na_LC030_N12:prepare_case |
| Mt_Na_LC030_N12:run_initial_rh0p90 | run_initial_rh_0p90 | completed | Mt_Na_LC030_N12:run_equilibrate |
| Mt_Na_LC030_N12:analyze_rh0p90 | analyze_rh_0p90 | completed | Mt_Na_LC030_N12:run_initial_rh0p90 |
| Mt_Na_LC030_N12:continue_or_archive_rh0p90 | continue_or_archive_rh_0p90 | completed | Mt_Na_LC030_N12:analyze_rh0p90 |
| Mt_Na_LC030_N12:start_next_rh0p30 | start_next_rh_0p30 | completed | Mt_Na_LC030_N12:continue_or_archive_rh0p90 |
| Mt_Na_LC030_N12:run_initial_rh0p30 | run_initial_rh_0p30 | completed | Mt_Na_LC030_N12:start_next_rh0p30 |
| Mt_Na_LC030_N12:analyze_rh0p30 | analyze_rh_0p30 | completed | Mt_Na_LC030_N12:run_initial_rh0p30 |
| Mt_Na_LC030_N12:continue_or_archive_rh0p30 | continue_or_archive_rh_0p30 | completed | Mt_Na_LC030_N12:analyze_rh0p30 |
| Mt_Na_LC030_N12:start_next_rh0p10 | start_next_rh_0p10 | completed | Mt_Na_LC030_N12:continue_or_archive_rh0p30 |
| Mt_Na_LC030_N12:run_initial_rh0p10 | run_initial_rh_0p10 | completed | Mt_Na_LC030_N12:start_next_rh0p10 |
| Mt_Na_LC030_N12:analyze_rh0p10 | analyze_rh_0p10 | completed | Mt_Na_LC030_N12:run_initial_rh0p10 |
| Mt_Na_LC030_N12:continue_or_archive_rh0p10 | continue_or_archive_rh_0p10 | completed | Mt_Na_LC030_N12:analyze_rh0p10 |
| Mt_Na_LC050_N20:plan_claycode_inputs | plan_claycode_inputs | completed |  |
| Mt_Na_LC050_N20:run_claycode | run_claycode | completed | Mt_Na_LC050_N20:plan_claycode_inputs |
| Mt_Na_LC050_N20:create_case_file | create_case_file | completed | Mt_Na_LC050_N20:run_claycode |
| Mt_Na_LC050_N20:prepare_case | prepare_case | completed | Mt_Na_LC050_N20:create_case_file |
| Mt_Na_LC050_N20:run_equilibrate | run_equilibrate | completed | Mt_Na_LC050_N20:prepare_case |
| Mt_Na_LC050_N20:run_initial_rh0p90 | run_initial_rh_0p90 | completed | Mt_Na_LC050_N20:run_equilibrate |
| Mt_Na_LC050_N20:analyze_rh0p90 | analyze_rh_0p90 | completed | Mt_Na_LC050_N20:run_initial_rh0p90 |
| Mt_Na_LC050_N20:continue_or_archive_rh0p90 | continue_or_archive_rh_0p90 | completed | Mt_Na_LC050_N20:analyze_rh0p90 |
| Mt_Na_LC050_N20:start_next_rh0p30 | start_next_rh_0p30 | completed | Mt_Na_LC050_N20:continue_or_archive_rh0p90 |
| Mt_Na_LC050_N20:run_initial_rh0p30 | run_initial_rh_0p30 | completed | Mt_Na_LC050_N20:start_next_rh0p30 |
| Mt_Na_LC050_N20:analyze_rh0p30 | analyze_rh_0p30 | completed | Mt_Na_LC050_N20:run_initial_rh0p30 |
| Mt_Na_LC050_N20:continue_or_archive_rh0p30 | continue_or_archive_rh_0p30 | completed | Mt_Na_LC050_N20:analyze_rh0p30 |
| Mt_Na_LC050_N20:start_next_rh0p10 | start_next_rh_0p10 | completed | Mt_Na_LC050_N20:continue_or_archive_rh0p30 |
| Mt_Na_LC050_N20:run_initial_rh0p10 | run_initial_rh_0p10 | completed | Mt_Na_LC050_N20:start_next_rh0p10 |
| Mt_Na_LC050_N20:analyze_rh0p10 | analyze_rh_0p10 | completed | Mt_Na_LC050_N20:run_initial_rh0p10 |
| Mt_Na_LC050_N20:continue_or_archive_rh0p10 | continue_or_archive_rh_0p10 | completed | Mt_Na_LC050_N20:analyze_rh0p10 |

## Status Counts

| status | count |
| --- | --- |
| completed | 80 |
| ready | 0 |
| blocked | 0 |
| missing | 0 |
| skipped | 0 |

## Next Recommended Action

- ``: campaign_plan_has_no_ready_tasks

## Notes

- This planner is read-only and does not run ClayCode, LAMMPS, GCMC, or job submission.
- Runtime directories may be reported if present, but they are not required for dry-run planning.

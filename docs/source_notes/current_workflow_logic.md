# Current Workflow Logic

This document captures the current MD-GCMC agent workflow and the logic checks behind the latest validated milestone. Simulation development is paused; RH=0.9 is archived, and RH=0.7 has only completed a 100,000-step validation.

## A. Building

1. `mtagent/run_claycode.py` runs the configured ClayCode builder command from `case.yaml` and records the raw build status.
2. `mtagent/prepare_case.py` validates configured paths and orchestrates conversion, checking, preparation, and final hard checks.

## B. Preparation

Preparation selects the configured ClayCode output prefix and converts the ClayCode `gro/top` output into LAMMPS-ready data.

The preparation sequence is:

1. Convert `gro/top` to LAMMPS data with the configured force field and SPC/E water source.
2. Check the converted LAMMPS data and type report.
3. Prepare the data for GCMC-MD, including groups and regions include generation.
4. Normalize molecule IDs:
   - lower clay sheet = molecule ID `1`
   - upper clay sheet = molecule ID `2`
   - water molecules = molecule IDs `3..`
   - sodium ions = molecule ID `0`
5. Run a hard check requiring normalized molecule IDs before downstream simulations.

The normalized clay molecule IDs are required because `fix rigid/nve molecule` uses molecule IDs to define rigid bodies.

## C. Pre-GCMC Equilibration

`mtagent/run_equilibrate.py` performs pre-GCMC equilibration from the prepared data.

Current logic:

1. Read prepared data with explicit topology capacity:
   - `extra/bond/per/atom 2`
   - `extra/angle/per/atom 1`
   - `extra/special/per/atom 2`
2. Use normalized clay molecule IDs with `fix rigid/nve molecule` so each clay sheet is one rigid body.
3. Define `mobile = water + sodium`.
4. Use neighbor update settings from `case.yaml`, currently `neigh_modify every 2 delay 0 check yes`.
5. Write the handoff restart `restart.pre_gcmc.final` and equilibrated data file.

## D. First RH

`mtagent/run_initial.py` starts the first RH GCMC-MD run.

Current logic:

1. Prefer the pre-GCMC equilibration restart over data-file startup.
2. Start RH=0.9 from `restart.pre_gcmc.final` when available.
3. Use the configured molecule template, force field settings, GCMC region, rigid clay constraints, and neighbor settings.
4. Monitor total water, interlayer water, external water, basal proxy, temperature, and GCMC acceptance metrics.
5. Use `velocity create ... loop geom` so restarts with non-consecutive atom IDs do not fail velocity creation.

## E. Continuation

`mtagent/run_cycle.py` performs the analyzer-manager-generation cycle.

Current logic:

1. Analyze the RH monitor file with `analyze_gcmc_equilibrium_restart.py`.
2. Let `campaign_manager.py` decide whether to continue the current RH or mark it equilibrated.
3. If continuation is needed, generate a continuation input with `generate_gcmc_input.py` from the selected numeric restart.
4. In dry-run mode, write preview JSONs and do not run LAMMPS.
5. In run mode, run only the generated segment requested by the caller.

## F. Archiving

`mtagent/archive_rh_result.py` archives an equilibrated RH state.

Current logic:

1. Read the equilibrated run directory and analyzer/manager outputs.
2. Prefer the exact final numeric restart, for example `restart.gcmc_rh0p90.4100000`.
3. Copy selected artifacts into `examples/Mt_Oct050_Na/states/rh_*/`.
4. Write `summary.json` and `summary.md`.
5. Record both:
   - `source_restart`: original restart path in the run directory
   - `archived_restart`: restart path inside the archived state directory
   - `selected_restart`: the archived restart path for downstream use

## G. Campaign Status

`mtagent/campaign_status.py` summarizes archived RH states.

Current logic:

1. Scan `states/rh_*/summary.json`.
2. Sort RH values descending by default.
3. Write:
   - `campaign_status.csv`
   - `campaign_status.md`
   - `campaign_status.json`
4. Prefer `archived_restart` when reporting the selected restart, with fallback compatibility for older summary fields.

## H. Next RH

`mtagent/start_next_rh.py` starts a new RH from an archived equilibrated state.

Current logic:

1. Read `from-state/summary.json`.
2. Prefer `archived_restart`, then fall back to `selected_restart`.
3. Generate a new initial GCMC input for the requested RH.
4. Use `read_restart` on the archived restart from the previous RH.
5. Use the same force field, molecule template, GCMC region, neighbor settings, and rigid clay constraints as `run_initial.py`.
6. Compute RH-dependent `p_h2o` using the existing case configuration logic and keep `mu` from `case.yaml`.
7. Use `velocity create ... loop geom` to support archived GCMC restarts with non-consecutive atom IDs.
8. Write `start_next_rh_status.preview.json` in dry-run mode and `start_next_rh_status.json` in run mode. It also mirrors to `initial_status.preview.json` or `initial_status.json` for compatibility with existing inspection flows.

## Resolved Bugs

- Wrong clay molecule IDs caused `rigid/nve molecule` to split clay sheets into many rigid bodies; molecule IDs are now normalized and hard-checked.
- Restart handoff needed extra topology capacity allocated during `read_data` before writing restart files; pre-GCMC equilibration now reads with explicit extra bond, angle, and special capacities.
- `neigh_modify every 10 delay 0 check yes` was too slow for GCMC insertion/deletion and parallel PPPM stability; `every 2 delay 0 check yes` is now the default and configurable in `case.yaml`.
- Archived GCMC restarts may have non-consecutive atom IDs; generated initial inputs now use `velocity create ... loop geom`.
- `run_initial.py` must prefer the pre-GCMC equilibration restart over prepared data; it now does.
- `start_next_rh.py` must prefer archived restarts for downstream RH transitions; it now records and uses the archived restart path.

## Remaining Known Issues / TODOs

- The KSpace plus neighbor exclusion warning still needs force-field consistency review.
- There is no automatic HPC/PBS submission workflow yet.
- Interrupted-job recovery is not robust yet.
- There is no full multi-RH campaign manager that automatically advances through the full RH path.
- There is no automatic diagnostic tool for failed runs yet.
- RH=0.7 has only completed validation and is not equilibrated.
- Production policy for committing small summaries versus excluding all generated runtime outputs needs confirmation.

# MD-GCMC Workflow

This repository builds and continues a ClayCode-derived Na-montmorillonite water sorption example through LAMMPS GCMC-MD segments. The current active example is `Mt_Oct050_Na`.

## Active Inputs

The ClayCode inputs for the current workflow are:

- `assets/claycode/MyMont1.yaml`
- `assets/claycode/exp_clay.csv`

Do not treat `SWy1.yaml` as the active example input for this repository state.

ClayCode can emit many files for a model, including dry and interlayer-water variants. For the current example, downstream conversion should use only the intended `MyMont-1_5_4` prefix:

- `examples/Mt_Oct050_Na/raw/MyMont-1_5_4.gro`
- `examples/Mt_Oct050_Na/raw/MyMont-1_5_4.top`

Do not treat the entire ClayCode output directory as input.

`MyMont-1_5_4.top` is retained with the raw inputs as ClayCode provenance. The current converter is driven by `.gro`, CLAYFF coefficients, and the SPC/E source charges; do not pass `.top` into conversion unless `scripts/gro_clayff_to_lammps_v2.py` explicitly grows a supported `--top` option.


## ClayCode Build Stage

The full workflow starts by running ClayCode from `assets/claycode`, not from the repository root, so relative references such as `exp_clay.csv` inside `MyMont1.yaml` resolve correctly. The command is configurable through `claycode.command` in `case.yaml`; the agent does not hard-code the ClayCode executable.

Validated command:

```bash
python3 mtagent/run_claycode.py --case case.yaml
```

ClayCode output is expected under a folder matching the YAML stem, for example `assets/claycode/MyMont1/`, unless `claycode.output_dir` overrides it. That output directory can contain many dry, hydrated, or intermediate variants. The agent copies only the configured `claycode.selected_prefix` files into `paths.raw_dir`:

- `MyMont-1_5_4.gro`
- `MyMont-1_5_4.top`

Unrelated ClayCode variants are left in the ClayCode output directory and are not staged for preparation.

## Conversion And Preparation

The preprocessing utilities are in `scripts/`:

1. Convert the selected `.gro` file to LAMMPS data with `scripts/gro_clayff_to_lammps_v2.py`; retain the matching `.top` as ClayCode provenance unless the converter explicitly supports `--top`.
2. Check the converted LAMMPS data with `scripts/check_lammps_data.py`.
3. Prepare the montmorillonite stack and vapor space with `scripts/prepare_mt_data.py`.

The validated command entry point for those steps is:

```bash
python3 mtagent/run_claycode.py --case case.yaml
python3 mtagent/prepare_case.py --case case.yaml
```

Current generated reports include a temporary development marker:

- `examples/Mt_Oct050_Na/generated/MyMont-1_5_4_v2.summary.txt`
- `examples/Mt_Oct050_Na/generated/MyMont-1_5_4_v2.type_report.csv`

The `v2` suffix is acceptable for now. Final stable outputs may drop this suffix later.

## SPC/E Source And Water Molecule Template

The SPC/E source file used by the ClayCode-to-LAMMPS converter is:

- `assets/forcefields/SPCEH2O.txt`

This file supplies the original SPC/E water charges for conversion through `water.spce_source`.

The current GCMC water molecule template is:

- `assets/forcefields/SPCEH2O_types_8_10.txt`

This file is used by `mtagent/generate_gcmc_input.py` through `water.molecule_template` for LAMMPS GCMC insertion. It is model-specific. In the current converted LAMMPS data:

- atom type `8` is water oxygen
- atom type `10` is water hydrogen

For another mineral, ClayCode conversion, or type-compression result, this molecule template may need to be regenerated so its atom, bond, and angle types match the converted LAMMPS data.

## Pre-GCMC Equilibration

After preparation, run a separate pre-GCMC equilibration stage before starting the first RH segment:

```bash
python3 mtagent/run_equilibrate.py --case case.yaml --run --np 16
```

`run_equilibrate.py` starts from prepared LAMMPS data and writes the configured `equilibration.output_data` and `equilibration.output_restart` handoff files. During this stage, `clay_lower` and `clay_upper` are rigid clay sheets with the same convention used later in GCMC: z translation is allowed, x/y translation is disabled, and rotation is disabled. The mobile thermostat group is only `water + sodium`; clay atoms are not included in mobile velocity creation, `nve/limit`, or NVT equilibration.

## GCMC-MD Cycle

The agent workflow lives in `mtagent/`:

1. `mtagent/run_equilibrate.py` performs pre-GCMC equilibration from prepared LAMMPS data.
2. `mtagent/run_initial.py` starts the first RH segment from the pre-GCMC restart when available, otherwise from equilibrated data, otherwise from prepared data with a warning.
3. `mtagent/run_cycle.py` selects the RH monitor, analyzes equilibration, asks the manager for the next action, generates the next continuation input when needed, and optionally runs LAMMPS.
4. `mtagent/analyze_gcmc_equilibrium_restart.py` evaluates total water, interlayer water, external water, basal spacing proxy, temperature sanity, and water-count consistency.
5. `mtagent/campaign_manager.py` converts analyzer output into a reproducible JSON decision.
6. `mtagent/generate_gcmc_input.py` selects the latest matching RH restart, writes or previews the next LAMMPS continuation input, and records input-generation status.
7. `mtagent/local_runner.py` runs one generated input locally and records run status and diagnostics.

The validated full command sequence is:

```bash
python3 mtagent/run_claycode.py --case case.yaml
python3 mtagent/prepare_case.py --case case.yaml
python3 mtagent/run_equilibrate.py --case case.yaml --run --np 16
python3 mtagent/run_initial.py --case case.yaml --run-dir <clean_rh_dir> --run --np 16
python3 mtagent/run_cycle.py --run-dir <rh_dir> --case case.yaml --dry-run
python3 mtagent/run_cycle.py --run-dir <rh_dir> --case case.yaml --run --np 16
```

For short validation runs, the initial segment may finish before the periodic restart command writes `restart.gcmc_<tag>.*`. `run_initial.py` therefore writes `restart.gcmc_<tag>.final` as an explicit handoff file, and `run_cycle.py` can use that final restart when no numeric restart is present.

Simulation decisions are written to JSON files in the run directory, including `equilibrium_status.json`, `manager_decision.json`, `input_generation_status.json`, `cycle_status.json`, and `run_status.json` when LAMMPS is executed.

## Current Example Run Directory

The active RH example directory is:

- `examples/Mt_Oct050_Na/rh_0p90`

The cycle script infers `rh0p90` from the directory name, prefers matching monitor files such as `monitor_gcmc_rh0p90.dat`, and prefers restart files matching the same RH tag. Dry-run mode previews generation and updates status JSON without writing a new LAMMPS input file.

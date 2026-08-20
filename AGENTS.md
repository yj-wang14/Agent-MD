# Agent Instructions for MD-GCMC Agent

## Project goal

This repository develops an agentic workflow for ClayCode-based clay-water model construction, LAMMPS GCMC-MD simulation, restart continuation, and adaptive equilibration judgment.

## General rules

- Do not change physical simulation parameters unless they are specified in `case.yaml` or explicitly requested by the user.
- All simulation decisions should be reproducible and written to JSON files.
- Do not manually judge equilibration when an analyzer is available.
- Equilibration must consider:
  - total water number
  - interlayer water number
  - external water number
  - basal spacing
  - temperature sanity
  - restart continuity
- Monitor files should be appended across restart segments whenever possible.
- Do not overwrite previous results unless explicitly requested.
- Use dry-run mode for destructive operations, file generation, and HPC submission when available.

## LAMMPS/GCMC rules

- GCMC simulations should be run in segments.
- The default RH continuation segment should be 500000 steps unless `case.yaml` specifies otherwise.
- If the system is not equilibrated, the manager should recommend additional steps based on the analyzer output.
- If LAMMPS reports lost atoms, PPPM out-of-range atoms, SHAKE errors, NaN energy, or abnormal temperature, stop and flag the run.
- Recovery should preferentially use the latest valid restart file.
- Do not ignore lost atoms or PPPM out-of-range atom errors.

## Coding rules

- Keep code modular.
- Put agent decision logic in `mtagent/`.
- Put preprocessing utilities in `scripts/`.
- Put LAMMPS templates and molecule templates in `templates/`.
- Put example data in `examples/`.
- Every major command should write a status JSON file.
- Scripts should have clear command-line interfaces.
- Avoid hard-coded case-specific paths when possible.

## Git rules

- Commit working baseline before major refactoring.
- Keep large trajectory, restart, and raw simulation data out of git.
- Small example monitor/status files may be committed for testing.

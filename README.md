# Agent-MD v1.0-rc1

This is a controlled release candidate for human review, not a final public release.

Agent-MD is an architecture for stateful scientific simulation campaigns. A reasoning agent supports flexible campaign planning and event-triggered review; a persistent rule-based campaign agent selects and dispatches production actions from approved rules, task dependencies, and recorded state. Scientific computation and analysis tools remain responsible for model preparation, simulation, and analysis.

The included case study is a five-system montmorillonite water-vapor desorption campaign over RH 0.9, 0.3, and 0.1. The package supports inspection of the software and campaign definitions, execution of the source-level test suite, reproduction of Tables 1 and 2 from staged CSV records, inspection of the architecture-level Table 3 in the manuscript, and reproduction of Figures 3--7 from validated source data. Large restart files, full trajectories, raw simulation workspaces, stale outputs, and superseded outputs are intentionally excluded.

## Layout

- `mtagent/`: rule-based campaign and review-interface software
- `campaigns/montmorillonite_desorption/`: approved campaign and five case definitions
- `data/`: public result derivatives, figure/table data, operational summaries, and frozen replay evidence
- `scripts/`: preparation, validation, and plotting utilities
- `paper/`: manuscript source and active figures

## Tests

From the release root, run `python -m pytest`. Tests requiring external LAMMPS or ClayCode installations must be interpreted separately from source-level tests.

## Tables and figures

Table source files are under `data/table_source_data/`. Figure source files are under `data/figure_source_data/`. Plotting scripts accept staged data after release-path adaptation; see `docs/figures_and_tables.md`. Table 3 is an architecture-level inventory embedded in the manuscript rather than a generated numerical table.

## External software

LAMMPS and ClayCode are external scientific programs and are not installed as Python dependencies. ClayFF/SPC/E and ClayCode preparation assets are subject to redistribution review and are not included in this candidate.

See `RELEASE_BLOCKERS.md` before any publication or redistribution.

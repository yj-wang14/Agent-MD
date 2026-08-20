# Agent-MD

**Selective LLM Intervention with Event-Driven Escalation for Stateful GCMC–MD Campaigns**

This repository accompanies the manuscript:

**Agent-MD: Selective LLM Intervention with Event-Driven Escalation for Stateful GCMC–MD Campaigns**

arXiv DOI:
https://doi.org/10.48550/arXiv.2608.07637

The repository provides the Agent-MD implementation, workflow definitions, campaign templates, schemas, and illustrative examples.

Large-scale production trajectories and manuscript-specific analysis outputs are not included.

The included SPC/E template is provided as an illustrative simulation template; users should cite the original SPC/E water model publication when using this model.

## Repository contents

This is the public Agent-MD framework repository accompanying the manuscript.

Agent-MD is an architecture for stateful scientific simulation campaigns. A reasoning agent supports flexible campaign planning and event-triggered review; a persistent rule-based campaign agent selects and dispatches production actions from approved rules, task dependencies, and recorded state. Scientific computation and analysis tools remain responsible for model preparation, simulation, and analysis.

Agent-MD separates LLM-based reasoning from deterministic execution. Routine campaign operations are handled through rule-based execution using persistent campaign state and provenance tracking records, while LLM reasoning is invoked only for planning or bounded review tasks.

The included campaign definition is a five-system montmorillonite water-vapor desorption workflow over RH 0.9, 0.3, and 0.1. The package supports inspection of the software and campaign definitions, execution of the source-level test suite, and inspection of an illustrative event-driven reasoning replay. Large restart files, full trajectories, raw simulation workspaces, manuscript files, figures, and analysis outputs are intentionally excluded.

## Layout

- `mtagent/`: rule-based campaign and review-interface software
- `campaigns/montmorillonite_desorption/`: approved campaign and five case definitions
- `data/historical_replay/`: one illustrative event, evidence bundle, and schema-validated decision
- `scripts/`: preparation and validation utilities

## Installation

The package supports editable installation from the repository root. Install the runtime dependencies with:

```bash
python -m pip install -e .
```

To include the test dependency, use:

```bash
python -m pip install -e ".[dev]"
```

## Tests

From the release root, run `python -m pytest`. Tests requiring external LAMMPS or ClayCode installations must be interpreted separately from source-level tests.

## Campaign-plan dry run

The included campaign can be inspected through the original read-only planner entry point. This writes plan files but does not launch ClayCode, LAMMPS, or a simulation:

```bash
python -m mtagent.plan_campaign \
  --campaign campaigns/montmorillonite_desorption/campaign.yaml \
  --output campaign.plan.json \
  --markdown campaign.plan.md
```

Missing external ClayCode or force-field assets are reported as missing or blocked tasks.

## External software

LAMMPS and ClayCode are external scientific programs and are not installed as Python dependencies. ClayFF and ClayCode preparation assets are not distributed here. The illustrative SPC/E topology template referenced by the included campaign is retained.


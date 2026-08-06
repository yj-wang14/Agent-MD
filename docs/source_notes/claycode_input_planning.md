# ClayCode Input Planning

`mtagent/plan_claycode_inputs.py` generates ClayCode YAML/CSV input pairs for cation and layer-charge series. It does not run ClayCode.

## Template Roles

- `MyMont1.yaml` primarily controls builder geometry, output naming, solvent settings, and the `SYSNAME`/`CLAY_COMP` link.
- `exp_clay.csv` controls the target composition column used by ClayCode: stoichiometry, layer charge, and interlayer cation amount.

The planner keeps the current geometry fixed:

- `CLAY_TYPE = D21`
- `X_CELLS = 5`
- `Y_CELLS = 4`
- `N_SHEETS = 2`

## Composition Rule

The current series uses octahedral Mg-for-Al substitution only. For substitution magnitude `x`:

- tetrahedral `Si = 8`
- octahedral `Al + Mg = 4`
- octahedral `Al = 4 - x`
- octahedral `Mg = x`
- layer charge `= -x`
- interlayer cation per unit cell `I,cation = x / valence`
- `C,O = -x`
- `C,tot = -x`

The planner validates `0 <= x <= 4` so octahedral Al remains non-negative. It distinguishes three related quantities:

- total ionic charge magnitude: `x * X_CELLS * Y_CELLS * N_SHEETS`
- total cation count: total ionic charge divided by cation valence
- ion partition counts: the target bottom/interlayer/top placement counts used by preparation

It requires the total interlayer cation count to be integral:

```text
total_cation_count = x / valence * X_CELLS * Y_CELLS * N_SHEETS
```

For the fixed 5 x 4 x 2 supercell, `total_unit_cells = 40`. If the count is not integer within tolerance, planning fails and the user must change the layer charge or supercell size.

For this workflow, the default ion partition ratio is bottom:interlayer:top = `1:2:1`. Therefore `total_cation_count` must also be divisible by `4` unless `--allow-uneven-partition` is explicitly supplied. The planner records `ion_partition_ratio`, `target_bottom_ions`, `target_interlayer_ions`, and `target_top_ions` in `claycode_input_plan.json` and in the sidecar metadata JSON.

Example: `Mt_Ca_LC050_N10` has 10 Ca ions, which cannot be split as 1:2:1 because it would require 2.5:5:2.5 ions. The recommended first Ca validation target is `Mt_Ca_LC040_N8`, with 8 Ca ions partitioned as 2:4:2.

## Example

```bash
python3 mtagent/plan_claycode_inputs.py \
  --case case.yaml \
  --out-dir assets/claycode/planned_inputs \
  --cation Na \
  --cation Ca \
  --charge 0.40 \
  --charge 0.50 \
  --base-name Mt
```

This writes one YAML/CSV pair for each cation/charge combination plus `claycode_input_plan.json`. System names use `Mt_<cation>_LC###_N<count>`, for example `Mt_Na_LC050_N20` or `Mt_Ca_LC040_N8`. The generated YAML is kept ClayCode-compatible and does not include planner-only top-level keys. Planner metadata is stored in `claycode_input_plan.json` and `<system_id>.metadata.json`, including `substitution_amount_x`, `layer_charge_per_uc_signed`, `layer_charge_label`, `total_unit_cells`, `total_cation_count`, `ion_partition_ratio`, target ion partition counts, `cation`, and `valence`.

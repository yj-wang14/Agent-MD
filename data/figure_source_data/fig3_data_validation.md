# Figure 3 Data Validation

Validation status: PASS

## Water-Partition Residual Audit

`water_partition_residual = total_water_mean - interlayer_water_mean - external_water_mean`

- Maximum absolute residual: 4.00000033096e-08 molecules.
- States with absolute residual greater than 1 molecule: 0.
- Discrepancy assessment: residuals are at floating-point/CSV-formatting precision and do not indicate a non-exhaustive spatial classification in the Figure 3 source data.

| system_id | RH | display_label | water_partition_residual |
| --- | ---: | --- | ---: |
| Mt_Ca_LC040_N8 | 0.10 | Ca--LC0.40 | 4.00000033096e-08 |
| Mt_Ca_LC040_N8 | 0.30 | Ca--LC0.40 | -1.00000079328e-08 |
| Mt_Ca_LC040_N8 | 0.90 | Ca--LC0.40 | 0 |
| Mt_K_LC040_N16 | 0.10 | K--LC0.40 | 1.00000008274e-08 |
| Mt_K_LC040_N16 | 0.30 | K--LC0.40 | 0 |
| Mt_K_LC040_N16 | 0.90 | K--LC0.40 | 0 |
| Mt_Na_LC030_N12 | 0.10 | Na--LC0.30 | 7.1054273576e-15 |
| Mt_Na_LC030_N12 | 0.30 | Na--LC0.30 | 0 |
| Mt_Na_LC030_N12 | 0.90 | Na--LC0.30 | 0 |
| Mt_Na_LC040_N16 | 0.10 | Na--LC0.40 | -1.00000008274e-08 |
| Mt_Na_LC040_N16 | 0.30 | Na--LC0.40 | 0 |
| Mt_Na_LC040_N16 | 0.90 | Na--LC0.40 | 2.84217094304e-14 |
| Mt_Na_LC050_N20 | 0.10 | Na--LC0.50 | -7.1054273576e-15 |
| Mt_Na_LC050_N20 | 0.30 | Na--LC0.50 | 1.00000079328e-08 |
| Mt_Na_LC050_N20 | 0.90 | Na--LC0.50 | -2.84217094304e-14 |

## Figure 3 Source Checks
- Rows: 15; expected 15.
- Unique system--RH pairs: 15.
- RH states: 0.10, 0.30, 0.90.
- All strict-pass: True.
- Error definition: raw_sample_standard_deviation_final_1M_steps.
- Final-window steps: 1000000.
- Sample interval steps: 1000.

## Supercell Comparability
- Campaign and case specifications use `x_cells = 5`, `y_cells = 4`, and `n_sheets = 2` for all five plotted systems.
- Generated equilibrated LAMMPS data headers show the same lateral box dimensions for all five systems: Lx = 25.8, Ly = 35.864, lateral area = 925.2912.
- Raw molecule counts are therefore directly comparable across the five plotted systems with respect to supercell size and lateral surface area.

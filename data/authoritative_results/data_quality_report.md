# Data Quality Report

Overall QC status: PASS

## Checks
- Exactly 15 authoritative rows exist: True (15 rows).
- Total water equals interlayer + external: checked numerically for all rows.
- External water equals bottom + top external water: checked against exact final-step monitor rows.
- No stale or duplicate state included: selected only strict-pass archive directories.
- RH0.3 provenance from strict RH0.9: checked via source_parent_restart.
- RH0.1 provenance from strict RH0.3: checked via source_parent_restart.
- All states passed current strict criterion: checked.
- Step-budget calculations use RH-local elapsed steps: manifest and master use final_absolute_step - RH_start_step.
- K RH0.3 corrected endpoint: final step 66,100,000 and RH-local elapsed 24,000,000 checked.
- Old smoke/RH0.7/pre-strict contamination: checked by selected path policy.

## Discrepancies
- None found.

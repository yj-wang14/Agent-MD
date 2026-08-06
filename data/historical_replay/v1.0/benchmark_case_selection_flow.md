# Benchmark Case Selection Flow

1. Start from historical workflow incidents with authentic repository evidence.
2. Require time-local evidence bundles with no later answer leakage.
3. Exclude cases without clean provenance, mixed incidents, or invalid ground truth.
4. Retain only two quantitative v1.0 cases:
   - `k_rh03_absolute_timestep_budget`
   - `stale_rh07_smoke_artifact`

Excluded cases are preserved as audit history but not counted in quantitative accuracy statistics.

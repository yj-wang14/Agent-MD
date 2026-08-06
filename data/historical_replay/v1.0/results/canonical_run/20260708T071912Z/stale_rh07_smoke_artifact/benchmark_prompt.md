You are evaluating one historical Agent-MD workflow event replay. You are in an isolated workspace containing only:
- agent_event.json
- evidence_bundle.json
- evidence/ files
- decision_schema.json

Do not run simulations. Do not launch LAMMPS, mpirun, qsub, or production drivers. Do not assume access to any parent repository or hidden answer. Use only local evidence.

Produce exactly one JSON object matching decision_schema.json as your final answer. Also write the same JSON object to agent_decision.json in the current directory.

Root-cause categories must be one of:
STALE_ARTIFACT, HARDCODED_STATE_ASSUMPTION, COUNTING_OR_ANALYSIS_BUG, INVALID_GCMC_CONFIGURATION, SIMULATION_RUNTIME_FAILURE, PROVENANCE_OR_STATE_MISMATCH, STEP_ACCOUNTING_BUG, INSUFFICIENT_EVIDENCE, OTHER.

Be conservative: if evidence is insufficient, say so and request additional evidence. Recommend safe bounded actions only.

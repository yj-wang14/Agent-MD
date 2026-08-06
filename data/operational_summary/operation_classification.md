# Operation Classification

Scope: the primary production census includes only the five final systems and RH = 0.90, 0.30, 0.10 strict-production chain. Smoke tests, RH0.7 artifacts, synthetic escalation tests, blinded replay child calls, and interactive development conversations are excluded from primary production-operation statistics.

## Classes

- ROUTINE_DETERMINISTIC: deterministic Python workflow actions that are expected during normal campaign execution: launch/continue a segment, wait/monitor, run final-window analysis, issue continue/pass decisions, archive passed states, progress to the next RH, and verify provenance during normal handoff.
- DETERMINISTIC_EXCEPTION_HANDLING: known non-routine conditions handled without LLM autonomy, including fatal keyword detection, blocked-state records, restart/quarantine recovery, and deterministic refusal to continue from suspect artifacts.
- REASONING_BOUNDARY: a discrete ambiguity not resolved by routine state logic alone. In the primary campaign this is the K RH0.3 step-budget semantics incident.
- LLM_REASONING_CALL: an actual runtime event-driven `codex exec` call made by the production workflow. Count for the primary production campaign: 0.

## Count Summary

- Deterministic operations: 414
- Real production runtime LLM calls: 0
- Real reasoning boundaries: 1
- Runtime LLM fraction over deterministic operations: 0.000000
- If the human-initiated Codex audit is counted as external reasoning support rather than runtime automation: 0.002410

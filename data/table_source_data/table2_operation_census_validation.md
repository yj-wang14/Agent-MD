# Table 2 Operation Census Validation

Validation status: PASS

## Authoritative Inputs
- `paper_artifacts/agent_md_operation_census/operation_census.json`
- `paper_artifacts/agent_md_operation_census/operation_census.csv`
- `paper_artifacts/agent_md_operation_census/operation_summary.md`
- `paper_artifacts/agent_md_operation_census/operation_classification.md`
- `paper_artifacts/agent_md_operation_census/provenance_of_counts.md`
- `paper_artifacts/agent_md_operation_census/codex_call_audit.csv`
- `paper_artifacts/agent_md_operation_census/campaign_timeline.csv`
- `paper_artifacts/final_campaign/authoritative_manifest.csv`
- `paper_artifacts/final_campaign/workflow_case_study/workflow_case_study.md`
- `generated/downstream_rh03_rh01_production_supervisor.log`

## Verified Counts
- Campaign-agent operations: 414.
- Simulation cycles: 120.
- Analysis--decision cycles: 120.
- Provenance checks: 25.
- Accepted states: 15.
- RH transitions: 10.
- States requiring review: 1.
- Reasoning-agent invocations: 0.

## Non-Additivity
The rows should not be summed. The 414 value is the total campaign-agent operation count for the primary production campaign. Simulation cycles, analysis--decision cycles, provenance checks, accepted states, and RH transitions are overlapping recorded aspects or subsets of campaign-agent activity. The state-review count records states requiring review, and the reasoning-agent-invocation count records guarded Codex CLI reasoning-agent invocations; neither is a component that sums with routine activity.

## Overlap With Campaign-Agent Operations
Simulation cycles, analysis--decision cycles, provenance checks, accepted states, and RH transitions overlap with the campaign-agent operation total. Campaign-agent operations include both routine actions and exception-handling actions dispatched or recorded by the rule-based campaign agent. Monitoring/check records are retained in the broader census but are not included as a separate Table 2 row.

## Formal Production Boundary
The primary production scope is the final five-system, three-RH strict-production chain. Smoke tests, RH0.7 artifacts, deprecated paper-batch outputs, synthetic review-routing validation, historical replay child calls, software-development sessions, and human-directed debugging/audit conversations are excluded from the zero-production-invocation metric.

## State Requiring Review vs Reasoning-Agent Invocation
The single state requiring review is the K--LC0.40 RH = 0.30 step-accounting incident. It records that the approved workflow rules could not safely resolve the state. It does not imply a non-interactive reasoning-agent invocation, because reasoning-agent invocation is a separate guarded action controlled by review enablement and invocation policy.

## Codex CLI Reasoning-Agent Interpretation
In manuscript terminology, the optional reasoning agent is implemented through the Codex CLI and powered by GPT-5.5. The zero-invocation result means that no non-interactive Codex CLI reasoning-agent invocation occurred during formal production. It does not mean that the campaign lacked a rule-based campaign agent, and it does not count planning, retrospective replay, or human-assisted development activity.

# Codex Event Escalation Layer

This workflow remains deterministic by default. Python still owns planning, execution, waiting, lightweight monitoring, continuation, analysis, archive, and RH progression. Codex is an optional event-driven reasoning layer for discrete boundaries where deterministic code has already produced a structured state.

## Architecture

```text
Deterministic Python driver
  -> routine execution / monitoring / continuation / archive / RH progression
  -> discrete event boundary
  -> agent_event.json + compact evidence_bundle.json
  -> optional `codex exec`
  -> agent_decision.json
  -> Python schema and guard validation
  -> deterministic/manual workflow resumes
```

The first integration point is `mtagent/run_campaign.py`, backed by `mtagent/agent_escalation.py`. Existing deterministic commands are backward compatible because escalation is disabled unless `--enable-codex-escalation`, `--invoke-codex`, or the matching environment variables are set.

## Event Lifecycle

1. A deterministic boundary is reached, such as batch completion, failed/blocked action, provenance mismatch, or convergence anomaly.
2. Python classifies the event as one of:
   - `BATCH_COMPLETE`
   - `NEEDS_REASONING`
   - `UNKNOWN_FAILURE`
   - `PROVENANCE_CONFLICT`
   - `CONVERGENCE_ANOMALY`
3. Python writes `generated/agent_events/<event_id>/agent_event.json`.
4. Python writes a compact `evidence_bundle.json` with selected JSON summaries and log/monitor tails only. It does not embed trajectories or large binary restart/data files.
5. If Codex invocation is enabled and guard caps permit it, Python runs `codex exec` non-interactively. Otherwise it writes a default human-review decision.
6. Python validates `agent_decision.json` against the strict schema and writes `decision_validation.json`.
7. Python records the event in `generated/agent_escalation_state.json`.

## Event Schema

`agent_event.json` contains at least:

```json
{
  "event_id": "20260706T120000_campaign_system_rh0p30_unknown_failure_abcd1234",
  "timestamp": "2026-07-06T12:00:00+08:00",
  "event_type": "UNKNOWN_FAILURE",
  "campaign_id": "paper_rh_water_uptake",
  "system_id": "Mt_Na_LC040_N16",
  "rh_tag": "rh0p30",
  "current_workflow_state": {},
  "reason": "run_cycle_failed",
  "relevant_paths": [],
  "error_fingerprint": "stable-hash-or-null"
}
```

## Decision Schema

`agent_decision.json` must contain:

```json
{
  "event_id": "must-match-event",
  "decision": "ACKNOWLEDGE",
  "confidence": 0.0,
  "reasoning_summary": "short explanation",
  "recommended_action": "none",
  "allowed_parameter_changes": ["none"],
  "evidence_used": [],
  "requires_human_review": true
}
```

Allowed decisions are `ACKNOWLEDGE`, `CONTINUE_DETERMINISTIC`, `REQUIRE_HUMAN_REVIEW`, `RETRY_SAFE_ACTION`, and `STOP_CAMPAIGN`. Allowed recommended actions are `none`, `continue_deterministic_workflow`, `inspect_evidence`, `retry_last_safe_task`, and `stop_and_wait_for_human`. Allowed parameter-change classes are `none` and `segment_steps_only`; scientific parameters remain under deterministic code and case configuration.

## Safeguards

- No periodic LLM polling. Events are emitted only at deterministic boundaries.
- No LLM call during normal waiting or successful routine continuation.
- Duplicate error fingerprints are deduplicated.
- Calls are capped per campaign and per campaign/system/RH/event/fingerprint key.
- Recursive invocation is blocked with `MTAGENT_AGENT_ESCALATION_ACTIVE`.
- Codex receives compact evidence only, not the repository, trajectories, or large restarts.
- Codex cannot directly launch simulations. The decision is a JSON recommendation validated by Python.
- Actions outside the allowlist require human review.
- High-risk events such as unknown failures, provenance conflicts, and convergence anomalies require human review unless the decision is acknowledgement-only.

## State And Provenance Files

The escalation layer adds:

- `generated/agent_events/<event_id>/agent_event.json`
- `generated/agent_events/<event_id>/evidence_bundle.json`
- `generated/agent_events/<event_id>/codex_prompt.txt`
- `generated/agent_events/<event_id>/agent_decision.json`
- `generated/agent_events/<event_id>/decision_validation.json`
- `generated/agent_escalation_state.json`

The deterministic workflow still uses its existing files, including campaign `.plan.json`, `.plan.md`, `.state.json`, run `*_status.json`, `equilibrium_status.json`, `manager_decision.json`, `input_generation_status.json`, `cycle_status.json`, generated diagnostics, and `states/rh_*/summary.json`.

## Synthetic Test

Create an event without invoking Codex:

```bash
python3 mtagent/agent_escalation.py \
  --enable \
  --event-type UNKNOWN_FAILURE \
  --campaign-id synthetic \
  --system-id Mt_Test \
  --rh-tag rh0p30 \
  --reason run_cycle_failed \
  --path generated/some_status.json
```

Run the unit tests:

```bash
python3 -m pytest tests/test_agent_escalation.py
```

Invoke Codex for a real boundary only when desired:

```bash
python3 mtagent/run_campaign.py \
  --campaign examples/campaigns/paper_rh_water_uptake_campaign.yaml \
  --auto-paper-batch \
  --max-actions 1 \
  --enable-codex-escalation \
  --invoke-codex
```

## Disable Or Manual Mode

Default behavior is disabled/manual: omit `--enable-codex-escalation` and `--invoke-codex`.

Environment controls:

- `MTAGENT_CODEX_ESCALATION=1` enables event emission.
- `MTAGENT_CODEX_INVOKE=1` allows `codex exec`.
- `MTAGENT_CODEX_MAX_TOTAL_CALLS` caps campaign calls.
- `MTAGENT_CODEX_MAX_CALLS_PER_KEY` caps repeated calls for the same system/event/fingerprint.
- `MTAGENT_AGENT_EVENTS_DIR` and `MTAGENT_AGENT_STATE` override output locations.

With event emission enabled but Codex invocation disabled, Python writes a default `REQUIRE_HUMAN_REVIEW` decision and validation record.

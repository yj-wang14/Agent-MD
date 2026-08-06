from __future__ import annotations

import json
from pathlib import Path

from mtagent import agent_escalation


def test_emit_event_writes_event_evidence_and_default_decision(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("LAMMPS tail\nERROR: Lost atoms\n")
    cfg = agent_escalation.EscalationConfig(
        enabled=True,
        codex_enabled=False,
        events_dir=tmp_path / "events",
        state_path=tmp_path / "state.json",
    )

    record = agent_escalation.emit_event(
        base_dir=tmp_path,
        config=cfg,
        event_type="UNKNOWN_FAILURE",
        campaign_id="camp",
        system_id="Mt_Test",
        rh_tag="rh0p30",
        workflow_state={"status": "failed"},
        reason="run_cycle_failed",
        relevant_paths=["run.log"],
        error_fingerprint="lost_atoms",
    )

    event_dir = tmp_path / record["event_dir"]
    event = json.loads((event_dir / "agent_event.json").read_text())
    evidence = json.loads((event_dir / "evidence_bundle.json").read_text())
    decision = json.loads((event_dir / "agent_decision.json").read_text())
    validation = json.loads((event_dir / "decision_validation.json").read_text())

    assert event["event_type"] == "UNKNOWN_FAILURE"
    assert event["error_fingerprint"] == "lost_atoms"
    assert "ERROR: Lost atoms" in evidence["files"]["run.log"]["tail"]
    assert decision["decision"] == "REQUIRE_HUMAN_REVIEW"
    assert validation["valid"] is True
    assert record["invocation"]["invoked"] is False


def test_validate_decision_rejects_unallowlisted_parameter_change() -> None:
    event = {"event_id": "e1", "event_type": "NEEDS_REASONING"}
    decision = {
        "event_id": "e1",
        "decision": "CONTINUE_DETERMINISTIC",
        "confidence": 0.8,
        "reasoning_summary": "ok",
        "recommended_action": "continue_deterministic_workflow",
        "allowed_parameter_changes": ["chemical_potential"],
        "evidence_used": [],
        "requires_human_review": False,
    }

    valid, errors = agent_escalation.validate_decision(decision, event)

    assert valid is False
    assert any("allowed_parameter_changes" in error for error in errors)


def test_duplicate_error_fingerprint_blocks_second_codex_invocation(tmp_path: Path) -> None:
    cfg = agent_escalation.EscalationConfig(
        enabled=True,
        codex_enabled=True,
        events_dir=tmp_path / "events",
        state_path=tmp_path / "state.json",
    )
    event = {
        "campaign_id": "camp",
        "system_id": "Mt_Test",
        "rh_tag": "rh0p30",
        "event_type": "UNKNOWN_FAILURE",
        "error_fingerprint": "same",
    }
    state = {
        "total_codex_calls": 1,
        "call_counts_by_key": {agent_escalation.state_key(event): 1},
        "seen_fingerprints": {agent_escalation.state_key(event): "old_event"},
    }

    allowed, reason = agent_escalation.should_invoke_codex(state, event, cfg)

    assert allowed is False
    assert reason == "duplicate_error_fingerprint"


def test_classify_campaign_boundary_events() -> None:
    event_type, reason = agent_escalation.classify_event_from_result(
        {"status": "completed"}, stop_reason="paper_batch_complete"
    )
    assert (event_type, reason) == (None, None)

    event_type, reason = agent_escalation.classify_event_from_result(
        {"status": "completed", "requires_completion_reasoning": True},
        stop_reason="paper_batch_complete",
    )
    assert (event_type, reason) == ("BATCH_COMPLETE", "paper_batch_complete")

    event_type, reason = agent_escalation.classify_event_from_result(
        {"status": "blocked", "reason": "analysis_archive_mismatch"}
    )
    assert (event_type, reason) == ("PROVENANCE_CONFLICT", "analysis_archive_mismatch")


def test_missing_codex_cli_falls_back_to_valid_human_review_decision(tmp_path: Path) -> None:
    cfg = agent_escalation.EscalationConfig(
        enabled=True,
        codex_enabled=True,
        events_dir=tmp_path / "events",
        state_path=tmp_path / "state.json",
        codex_command=("definitely-missing-codex-binary", "exec"),
    )

    record = agent_escalation.emit_event(
        base_dir=tmp_path,
        config=cfg,
        event_type="NEEDS_REASONING",
        campaign_id="camp",
        system_id="Mt_Test",
        rh_tag="rh0p30",
        workflow_state={"status": "blocked"},
        reason="analysis_requires_inspection",
        relevant_paths=[],
        error_fingerprint="missing_cli_case",
    )

    event_dir = tmp_path / record["event_dir"]
    decision = json.loads((event_dir / "agent_decision.json").read_text())
    validation = json.loads((event_dir / "decision_validation.json").read_text())
    state = json.loads((tmp_path / "state.json").read_text())

    assert record["invocation"]["invoked"] is True
    assert record["invocation"]["error"] == "codex_cli_not_found"
    assert decision["decision"] == "REQUIRE_HUMAN_REVIEW"
    assert validation["valid"] is True
    assert state["total_codex_calls"] == 1

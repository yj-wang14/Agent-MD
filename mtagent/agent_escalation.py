#!/usr/bin/env python3
"""Event-driven Codex escalation layer for deterministic MD-GCMC workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


EVENT_TYPES = {
    "BATCH_COMPLETE",
    "NEEDS_REASONING",
    "UNKNOWN_FAILURE",
    "PROVENANCE_CONFLICT",
    "CONVERGENCE_ANOMALY",
}

DECISIONS = {
    "ACKNOWLEDGE",
    "CONTINUE_DETERMINISTIC",
    "REQUIRE_HUMAN_REVIEW",
    "RETRY_SAFE_ACTION",
    "STOP_CAMPAIGN",
}

RECOMMENDED_ACTIONS = {
    "none",
    "continue_deterministic_workflow",
    "inspect_evidence",
    "retry_last_safe_task",
    "stop_and_wait_for_human",
}

ALLOWED_PARAMETER_CHANGES = {"none", "segment_steps_only"}

DEFAULT_STATE_PATH = Path("generated/agent_escalation_state.json")
DEFAULT_EVENTS_DIR = Path("generated/agent_events")
DEFAULT_MAX_TOTAL_CALLS = 20
DEFAULT_MAX_CALLS_PER_KEY = 3
TAIL_BYTES = 24_000


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def repo_relative(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)


def stable_hash(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def safe_event_part(value: str | None) -> str:
    if not value:
        return "campaign"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:80]


def make_event_id(
    *,
    campaign_id: str,
    event_type: str,
    system_id: str | None,
    rh_tag: str | None,
    reason: str,
    error_fingerprint: str | None,
) -> str:
    digest = stable_hash(
        {
            "campaign_id": campaign_id,
            "event_type": event_type,
            "system_id": system_id,
            "rh_tag": rh_tag,
            "reason": reason,
            "error_fingerprint": error_fingerprint,
            "timestamp": now_iso(),
        }
    )
    return "_".join(
        part
        for part in [
            datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f"),
            safe_event_part(campaign_id),
            safe_event_part(system_id),
            safe_event_part(rh_tag),
            event_type.lower(),
            digest,
            uuid.uuid4().hex[:8],
        ]
        if part
    )


def tail_text(path: Path, limit: int = TAIL_BYTES) -> str:
    if not path.exists() or not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit:
            handle.seek(max(0, size - limit))
        data = handle.read()
    return data.decode("utf-8", errors="replace")


def compact_json_file(path: Path, max_chars: int = TAIL_BYTES) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"unparsed_tail": tail_text(path, max_chars)}
    rendered = json.dumps(data, sort_keys=True)
    if len(rendered) <= max_chars:
        return data
    if isinstance(data, dict):
        compact: dict[str, Any] = {}
        for key in [
            "status",
            "reason",
            "message",
            "system_id",
            "rh_tag",
            "stage",
            "recommendation",
            "analysis_status",
            "analysis_recommendation",
            "final_timestep",
            "fatal_errors",
            "known_warnings",
            "checks",
            "reasons",
            "diagnostics",
            "source_restart",
            "selected_restart",
            "archive_summary_path",
        ]:
            if key in data:
                compact[key] = data[key]
        return compact or {"truncated_json_keys": sorted(data.keys())}
    return {"truncated_json_type": type(data).__name__}


def collect_evidence(
    *,
    base_dir: Path,
    event: dict[str, Any],
    relevant_paths: list[str],
    workflow_state: dict[str, Any],
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for raw in relevant_paths:
        path = Path(raw)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists() or not path.is_file():
            files[raw] = {"exists": False}
            continue
        entry: dict[str, Any] = {
            "exists": True,
            "size_bytes": path.stat().st_size,
            "path": repo_relative(path, base_dir),
        }
        if path.suffix == ".json":
            entry["json"] = compact_json_file(path)
        elif path.name.endswith((".stdout", ".stderr", ".log", "log.lammps")) or path.suffix in {".txt", ".md", ".dat"}:
            entry["tail"] = tail_text(path)
        else:
            entry["note"] = "binary_or_large_file_not_embedded"
        files[raw] = entry

    return {
        "event_id": event["event_id"],
        "created_at": now_iso(),
        "event": event,
        "workflow_state": workflow_state,
        "files": files,
        "bundle_policy": {
            "max_text_bytes_per_file": TAIL_BYTES,
            "large_binary_files_embedded": False,
            "trajectory_files_embedded": False,
        },
    }


def default_decision(event_id: str, *, reason: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "decision": "REQUIRE_HUMAN_REVIEW",
        "confidence": 0.0,
        "reasoning_summary": reason,
        "recommended_action": "stop_and_wait_for_human",
        "allowed_parameter_changes": ["none"],
        "evidence_used": [],
        "requires_human_review": True,
    }


def build_prompt(event_path: Path, evidence_path: Path, decision_path: Path) -> str:
    return f"""You are a non-interactive Codex reasoning layer for an MD-GCMC workflow.

Read the event JSON and compact evidence bundle below. Produce ONLY valid JSON at:
{decision_path}

Required schema:
{{
  "event_id": "<must match event_id>",
  "decision": "ACKNOWLEDGE|CONTINUE_DETERMINISTIC|REQUIRE_HUMAN_REVIEW|RETRY_SAFE_ACTION|STOP_CAMPAIGN",
  "confidence": 0.0,
  "reasoning_summary": "short explanation",
  "recommended_action": "none|continue_deterministic_workflow|inspect_evidence|retry_last_safe_task|stop_and_wait_for_human",
  "allowed_parameter_changes": ["none"],
  "evidence_used": ["relative/path/or/evidence key"],
  "requires_human_review": true
}}

Hard guards:
- Do not request uncontrolled simulation launches.
- Do not change scientific parameters except explicit allowlisted values.
- Require human review for actions outside the schema and allowlist.
- For unknown failures, provenance conflicts, or convergence anomalies, prefer human review unless the evidence is unambiguous.

Event: {event_path}
Evidence: {evidence_path}
Decision output path: {decision_path}
"""


@dataclass
class EscalationConfig:
    enabled: bool = False
    codex_enabled: bool = False
    events_dir: Path = DEFAULT_EVENTS_DIR
    state_path: Path = DEFAULT_STATE_PATH
    max_total_calls: int = DEFAULT_MAX_TOTAL_CALLS
    max_calls_per_key: int = DEFAULT_MAX_CALLS_PER_KEY
    codex_command: tuple[str, ...] = ("codex", "exec")


def config_from_env(base_dir: Path) -> EscalationConfig:
    enabled = os.environ.get("MTAGENT_CODEX_ESCALATION", "").lower() in {"1", "true", "yes"}
    codex_enabled = os.environ.get("MTAGENT_CODEX_INVOKE", "").lower() in {"1", "true", "yes"}
    command = tuple(os.environ.get("MTAGENT_CODEX_COMMAND", "codex exec").split())
    return EscalationConfig(
        enabled=enabled,
        codex_enabled=codex_enabled,
        events_dir=base_dir / os.environ.get("MTAGENT_AGENT_EVENTS_DIR", str(DEFAULT_EVENTS_DIR)),
        state_path=base_dir / os.environ.get("MTAGENT_AGENT_STATE", str(DEFAULT_STATE_PATH)),
        max_total_calls=int(os.environ.get("MTAGENT_CODEX_MAX_TOTAL_CALLS", DEFAULT_MAX_TOTAL_CALLS)),
        max_calls_per_key=int(os.environ.get("MTAGENT_CODEX_MAX_CALLS_PER_KEY", DEFAULT_MAX_CALLS_PER_KEY)),
        codex_command=command or ("codex", "exec"),
    )


def validate_decision(decision: dict[str, Any], event: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if decision.get("event_id") != event.get("event_id"):
        errors.append("event_id mismatch")
    if decision.get("decision") not in DECISIONS:
        errors.append("decision is not allowlisted")
    if decision.get("recommended_action") not in RECOMMENDED_ACTIONS:
        errors.append("recommended_action is not allowlisted")
    confidence = decision.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        errors.append("confidence must be a number in [0, 1]")
    changes = decision.get("allowed_parameter_changes")
    if not isinstance(changes, list) or not changes:
        errors.append("allowed_parameter_changes must be a non-empty list")
    else:
        invalid = [str(item) for item in changes if str(item) not in ALLOWED_PARAMETER_CHANGES]
        if invalid:
            errors.append(f"allowed_parameter_changes contains non-allowlisted values: {invalid}")
    if not isinstance(decision.get("requires_human_review"), bool):
        errors.append("requires_human_review must be boolean")
    if event.get("event_type") in {"UNKNOWN_FAILURE", "PROVENANCE_CONFLICT", "CONVERGENCE_ANOMALY"}:
        if decision.get("decision") not in {"REQUIRE_HUMAN_REVIEW", "STOP_CAMPAIGN", "ACKNOWLEDGE"} and not decision.get("requires_human_review"):
            errors.append("high-risk event decisions must require human review unless acknowledging only")
    return not errors, errors


def state_key(event: dict[str, Any]) -> str:
    return "|".join(
        str(event.get(key) or "")
        for key in ("campaign_id", "system_id", "rh_tag", "event_type", "error_fingerprint")
    )


def should_invoke_codex(state: dict[str, Any], event: dict[str, Any], config: EscalationConfig) -> tuple[bool, str]:
    if not config.enabled:
        return False, "escalation_disabled"
    if not config.codex_enabled:
        return False, "codex_invocation_disabled"
    if os.environ.get("MTAGENT_AGENT_ESCALATION_ACTIVE"):
        return False, "recursive_invocation_blocked"
    if int(state.get("total_codex_calls", 0)) >= config.max_total_calls:
        return False, "max_total_codex_calls_reached"
    key = state_key(event)
    counts = state.setdefault("call_counts_by_key", {})
    if int(counts.get(key, 0)) >= config.max_calls_per_key:
        return False, "max_calls_per_key_reached"
    fingerprints = state.setdefault("seen_fingerprints", {})
    fingerprint = event.get("error_fingerprint")
    if fingerprint and fingerprints.get(key):
        return False, "duplicate_error_fingerprint"
    return True, "allowed"


def invoke_codex(prompt_path: Path, decision_path: Path, config: EscalationConfig, cwd: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["MTAGENT_AGENT_ESCALATION_ACTIVE"] = "1"
    command = [*config.codex_command, prompt_path.read_text()]
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=1800)
    except FileNotFoundError as exc:
        return {
            "command": config.codex_command,
            "return_code": None,
            "error": "codex_cli_not_found",
            "error_detail": str(exc),
            "decision_path_exists": decision_path.exists(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": config.codex_command,
            "return_code": None,
            "error": "codex_timeout",
            "timeout_seconds": exc.timeout,
            "stdout_tail": (exc.stdout or "")[-TAIL_BYTES:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-TAIL_BYTES:] if isinstance(exc.stderr, str) else "",
            "decision_path_exists": decision_path.exists(),
        }
    except Exception as exc:  # defensive: escalation must not crash deterministic workflow
        return {
            "command": config.codex_command,
            "return_code": None,
            "error": "codex_invocation_exception",
            "error_detail": str(exc),
            "decision_path_exists": decision_path.exists(),
        }
    return {
        "command": config.codex_command,
        "return_code": proc.returncode,
        "stdout_tail": proc.stdout[-TAIL_BYTES:],
        "stderr_tail": proc.stderr[-TAIL_BYTES:],
        "decision_path_exists": decision_path.exists(),
    }


def emit_event(
    *,
    base_dir: Path,
    config: EscalationConfig,
    event_type: str,
    campaign_id: str,
    system_id: str | None,
    rh_tag: str | None,
    workflow_state: dict[str, Any],
    reason: str,
    relevant_paths: list[str],
    error_fingerprint: str | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")
    base_dir = base_dir.resolve()
    event_id = make_event_id(
        campaign_id=campaign_id,
        event_type=event_type,
        system_id=system_id,
        rh_tag=rh_tag,
        reason=reason,
        error_fingerprint=error_fingerprint,
    )
    event_dir = config.events_dir / event_id
    event = {
        "event_id": event_id,
        "timestamp": now_iso(),
        "event_type": event_type,
        "campaign_id": campaign_id,
        "system_id": system_id,
        "rh_tag": rh_tag,
        "current_workflow_state": workflow_state,
        "reason": reason,
        "relevant_paths": relevant_paths,
        "error_fingerprint": error_fingerprint,
    }
    event_dir.mkdir(parents=True, exist_ok=False)
    event_path = event_dir / "agent_event.json"
    evidence_path = event_dir / "evidence_bundle.json"
    decision_path = event_dir / "agent_decision.json"
    prompt_path = event_dir / "codex_prompt.txt"
    write_json(event_path, event)
    evidence = collect_evidence(
        base_dir=base_dir,
        event=event,
        relevant_paths=relevant_paths,
        workflow_state=workflow_state,
    )
    write_json(evidence_path, evidence)
    prompt_path.write_text(build_prompt(event_path, evidence_path, decision_path))

    state = load_json(config.state_path)
    state.setdefault("events", [])
    allowed, invoke_reason = should_invoke_codex(state, event, config)
    invocation: dict[str, Any] = {"invoked": False, "reason": invoke_reason}
    if allowed:
        invocation = {"invoked": True, **invoke_codex(prompt_path, decision_path, config, base_dir)}
        state["total_codex_calls"] = int(state.get("total_codex_calls", 0)) + 1
        key = state_key(event)
        counts = state.setdefault("call_counts_by_key", {})
        counts[key] = int(counts.get(key, 0)) + 1
        if error_fingerprint:
            state.setdefault("seen_fingerprints", {})[key] = event_id
        if invocation.get("return_code") != 0 or not decision_path.exists():
            fallback_reason = str(invocation.get("error") or "codex_returned_nonzero_or_no_decision")
            write_json(decision_path, default_decision(event_id, reason=fallback_reason))
    elif not decision_path.exists():
        write_json(decision_path, default_decision(event_id, reason=invoke_reason))

    decision = load_json(decision_path)
    valid, errors = validate_decision(decision, event)
    validation = {"valid": valid, "errors": errors}
    write_json(event_dir / "decision_validation.json", validation)
    record = {
        "event_id": event_id,
        "event_type": event_type,
        "campaign_id": campaign_id,
        "system_id": system_id,
        "rh_tag": rh_tag,
        "reason": reason,
        "event_dir": repo_relative(event_dir, base_dir),
        "agent_event": repo_relative(event_path, base_dir),
        "evidence_bundle": repo_relative(evidence_path, base_dir),
        "agent_decision": repo_relative(decision_path, base_dir),
        "decision_valid": valid,
        "decision_validation_errors": errors,
        "invocation": invocation,
        "timestamp": event["timestamp"],
    }
    state["events"].append(record)
    write_json(config.state_path, state)
    return record


def classify_event_from_result(result: dict[str, Any], *, stop_reason: str | None = None) -> tuple[str | None, str | None]:
    if result.get("requires_completion_reasoning") is True:
        reason = str(result.get("reason") or stop_reason or "batch_complete_reasoning_boundary")
        return "BATCH_COMPLETE", reason
    reason = str(result.get("reason") or stop_reason or "")
    if reason in {"analysis_archive_mismatch", "missing_expected_archived_restart", "start_next_rh_failed"}:
        return "PROVENANCE_CONFLICT", reason
    if reason in {"max_segments_per_rh_reached", "max_total_steps_per_rh_reached", "analysis_requires_inspection"}:
        return "CONVERGENCE_ANOMALY", reason
    if result.get("status") == "failed":
        if reason:
            return "NEEDS_REASONING", reason
        return "UNKNOWN_FAILURE", "failed_without_structured_reason"
    if result.get("status") == "blocked":
        return "NEEDS_REASONING", reason or "blocked"
    return None, None


def fingerprint_from_result(result: dict[str, Any]) -> str | None:
    payload = {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "fatal_errors": result.get("fatal_errors"),
        "known_warnings": result.get("known_warnings"),
        "return_code": result.get("return_code"),
        "stage": result.get("stage"),
        "system_id": result.get("system_id"),
    }
    if not any(value for value in payload.values()):
        return None
    return stable_hash(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a synthetic MD-GCMC Codex escalation event.")
    parser.add_argument("--event-type", choices=sorted(EVENT_TYPES), required=True)
    parser.add_argument("--campaign-id", default="synthetic_campaign")
    parser.add_argument("--system-id", default=None)
    parser.add_argument("--rh-tag", default=None)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--path", action="append", default=[], help="Relevant evidence path; may be repeated.")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--invoke-codex", action="store_true")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()

    cfg = config_from_env(args.base_dir)
    cfg.enabled = args.enable or cfg.enabled
    cfg.codex_enabled = args.invoke_codex or cfg.codex_enabled
    record = emit_event(
        base_dir=args.base_dir,
        config=cfg,
        event_type=args.event_type,
        campaign_id=args.campaign_id,
        system_id=args.system_id,
        rh_tag=args.rh_tag,
        workflow_state={"source": "synthetic_cli"},
        reason=args.reason,
        relevant_paths=args.path,
        error_fingerprint=stable_hash({"event_type": args.event_type, "reason": args.reason}),
    )
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

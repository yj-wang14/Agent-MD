#!/usr/bin/env python3
"""Restartable campaign driver with a conservative execution allowlist."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtagent import (
    agent_escalation,
    analyze_gcmc_equilibrium_restart,
    archive_rh_result,
    diagnose_run,
    paper_batch,
    plan_campaign,
    plan_claycode_inputs,
    run_claycode,
    start_next_rh,
)

SAFE_EXECUTION_STAGES = {
    "plan_claycode_inputs",
    "run_claycode",
    "create_case_file",
    "prepare_case",
    "run_equilibrate",
    "run_initial_rh",
    "run_initial_rh_0p90",
    "run_initial_rh_0p70",
    "analyze_rh",
    "analyze_rh_0p90",
    "analyze_rh0p90",
    "analyze_rh_0p70",
    "analyze_rh0p70",
    "continue_or_archive_rh",
    "continue_or_archive_rh_0p90",
    "continue_or_archive_rh0p90",
    "continue_or_archive_rh_0p70",
    "continue_or_archive_rh0p70",
    "start_next_rh",
    "start_next_rh_0p70",
}
UNSAFE_STAGE_MESSAGE = (
    "run_campaign.py v4 only executes plan_claycode_inputs, run_claycode, create_case_file, prepare_case, run_equilibrate, "
    "run_initial_rh_0p90, run_initial_rh_0p70, analyze_rh_0p90/analyze_rh_0p70, continue_or_archive_rh_0p90/continue_or_archive_rh_0p70, and start_next_rh_0p70. Scheduler stages are refused."
)

SMOKE_ALLOWED_GENERIC_STAGES = {
    "plan_claycode_inputs",
    "run_claycode",
    "create_case_file",
    "prepare_case",
    "run_equilibrate",
    "run_initial_rh",
    "analyze_rh",
}
SMOKE_STOP_STAGE = "analyze_rh0p90"
SMOKE_SUMMARY_JSON = "campaign_smoke_summary.json"
SMOKE_SUMMARY_MD = "campaign_smoke_summary.md"


def state_path_for(campaign_path: Path) -> Path:
    return campaign_path.with_suffix(".state.json")


def plan_paths_for(campaign_path: Path) -> tuple[Path, Path]:
    return campaign_path.with_suffix(".plan.json"), campaign_path.with_suffix(".plan.md")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def rel(path: Path, base_dir: Path) -> str:
    return plan_campaign.rel(path, base_dir)


def load_or_init_state(campaign_path: Path, plan: dict[str, Any], state_path: Path, base_dir: Path) -> dict[str, Any]:
    state = load_json(state_path)
    if not state:
        state = {
            "campaign_id": plan["campaign_id"],
            "systems": [system["system_id"] for system in plan["systems"]],
            "completed_tasks": [],
            "failed_tasks": [],
            "skipped_tasks": [],
            "execution_history": [],
        }
    state.setdefault("campaign_id", plan["campaign_id"])
    state["systems"] = [system["system_id"] for system in plan["systems"]]
    state.setdefault("completed_tasks", [])
    state.setdefault("failed_tasks", [])
    state.setdefault("skipped_tasks", [])
    state.setdefault("execution_history", [])
    state["campaign_file"] = rel(campaign_path, base_dir)
    return state


def unique_append(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def remove_value(items: list[Any], value: Any) -> bool:
    removed = False
    while value in items:
        items.remove(value)
        removed = True
    return removed


def reconcile_failed_tasks(
    state: dict[str, Any],
    plan: dict[str, Any],
    preserve_task_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    """Keep failed_tasks as active unresolved failures, without deleting history."""
    status_by_id = {task["task_id"]: task["status"] for task in plan.get("planned_tasks", [])}
    resolved: list[dict[str, str]] = []
    active_failed = list(state.get("failed_tasks", []))
    preserve_task_ids = preserve_task_ids or set()
    state.setdefault("resolved_failed_tasks", [])
    for task_id in active_failed:
        if task_id in preserve_task_ids:
            continue
        status = status_by_id.get(task_id)
        if status in {plan_campaign.STATUS_READY, plan_campaign.STATUS_COMPLETED}:
            if remove_value(state["failed_tasks"], task_id):
                entry = {
                    "timestamp": plan_campaign.now_iso(),
                    "task_id": task_id,
                    "resolved_by_status": status,
                }
                state["resolved_failed_tasks"].append(entry)
                resolved.append(entry)
    return resolved


def write_plan(campaign_path: Path, base_dir: Path) -> dict[str, Any]:
    plan = plan_campaign.make_plan(campaign_path, base_dir=base_dir)
    plan_json, plan_md = plan_paths_for(campaign_path)
    plan_campaign.write_json(plan_json, plan)
    plan_md.write_text(plan_campaign.render_markdown(plan))
    return plan


def update_state(
    *,
    state: dict[str, Any],
    plan: dict[str, Any],
    campaign_path: Path,
    state_path: Path,
    base_dir: Path,
    target_system: str | None = None,
) -> None:
    plan_json, plan_md = plan_paths_for(campaign_path)
    state["last_updated"] = plan_campaign.now_iso()
    state["last_plan_path"] = rel(plan_json, base_dir)
    state["last_markdown_plan_path"] = rel(plan_md, base_dir)
    state["next_recommended_action"] = first_next_action_for_system(plan, target_system)
    write_json(state_path, state)


def event_paths_from_action(action: dict[str, Any], base_dir: Path, state_path: Path, campaign_path: Path) -> list[str]:
    paths = [rel(state_path, base_dir), rel(plan_paths_for(campaign_path)[0], base_dir)]
    for key in (
        "log_path",
        "analysis_path",
        "input_analysis_file",
        "diagnostics_path",
        "stdout",
        "stderr",
        "archive_summary_path",
        "status_file",
        "preview_status_file",
        "initial_status",
        "monitor",
    ):
        value = action.get(key)
        if isinstance(value, str):
            paths.append(value)
    command = action.get("command")
    if isinstance(command, list):
        for item in command:
            if isinstance(item, str) and item.endswith(".json"):
                paths.append(item)
    return sorted(set(paths))


def maybe_emit_escalation(
    *,
    config: agent_escalation.EscalationConfig,
    campaign_id: str,
    campaign_path: Path,
    state_path: Path,
    base_dir: Path,
    action: dict[str, Any],
    stop_reason: str | None = None,
) -> dict[str, Any] | None:
    if not config.enabled:
        return None
    event_type, reason = agent_escalation.classify_event_from_result(action, stop_reason=stop_reason)
    if event_type is None or reason is None:
        return None
    task_id = str(action.get("task_id") or "")
    stage = str(action.get("stage") or "")
    rh_match = re.search(r"rh[0-9]+p[0-9]+", task_id + " " + stage)
    rh_tag = str(action.get("rh_tag") or (rh_match.group(0) if rh_match else ""))
    return agent_escalation.emit_event(
        base_dir=base_dir,
        config=config,
        event_type=event_type,
        campaign_id=campaign_id,
        system_id=str(action.get("system_id") or "") or None,
        rh_tag=rh_tag or None,
        workflow_state={
            "task_id": action.get("task_id"),
            "stage": action.get("stage"),
            "status": action.get("status"),
            "stop_reason": stop_reason,
            "next_recommended_action": action.get("next_recommended_action"),
        },
        reason=reason,
        relevant_paths=event_paths_from_action(action, base_dir, state_path, campaign_path),
        error_fingerprint=agent_escalation.fingerprint_from_result(action),
    )


def campaign_plan_system_ids(plan: dict[str, Any]) -> set[str]:
    return {str(system["system_id"]) for system in plan.get("systems", [])}


def validate_target_system(plan: dict[str, Any], target_system: str | None) -> None:
    if target_system is None:
        return
    known = campaign_plan_system_ids(plan)
    if target_system not in known:
        raise ValueError(f"Unknown campaign system {target_system!r}; known systems: {', '.join(sorted(known))}")


def first_actionable_task(plan: dict[str, Any], target_system: str | None = None) -> dict[str, Any] | None:
    for task in plan["planned_tasks"]:
        if target_system is not None and str(task.get("system_id")) != target_system:
            continue
        if task["status"] in {plan_campaign.STATUS_READY, plan_campaign.STATUS_MISSING}:
            return task
    return None


def first_next_action_for_system(plan: dict[str, Any], target_system: str | None = None) -> dict[str, Any] | None:
    if target_system is None:
        return plan["next_actions"][0] if plan.get("next_actions") else None
    task = first_actionable_task(plan, target_system)
    if task is None:
        return None
    action = (
        "would_run_preview_or_execute_in_future_run_campaign"
        if task["status"] == plan_campaign.STATUS_READY
        else "missing_inputs_or_outputs_need_attention"
    )
    return {
        "task_id": task["task_id"],
        "stage": task["stage"],
        "action": action,
        "command_preview": task["command_preview"],
    }


def task_by_id(plan: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in plan["planned_tasks"]:
        if task["task_id"] == task_id:
            return task
    return None


def system_config(plan: dict[str, Any], system_id: str) -> dict[str, Any]:
    for system in plan["systems"]:
        if system["system_id"] == system_id:
            return system
    raise ValueError(f"System not found in plan: {system_id}")


def campaign_system_config(campaign_cfg: dict[str, Any], system_id: str) -> dict[str, Any]:
    for system in campaign_cfg.get("systems", []):
        if str(system.get("system_id")) == system_id:
            return system
    raise ValueError(f"System not found in campaign: {system_id}")


def planner_outputs_match(task: dict[str, Any], base_dir: Path, expected_metadata: dict[str, Any]) -> bool:
    output_paths = [base_dir / path for path in task["expected_output_files"]]
    if not all(path.exists() for path in output_paths):
        return False
    metadata_path = next((path for path in output_paths if path.name.endswith(".metadata.json")), None)
    if metadata_path is None:
        return False
    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError:
        return False
    keys = [
        "sysname",
        "cation",
        "valence",
        "substitution_amount_x",
        "total_cation_count",
        "target_bottom_ions",
        "target_interlayer_ions",
        "target_top_ions",
    ]
    return all(metadata.get(key) == expected_metadata.get(key) for key in keys)


def expected_planner_metadata(campaign_cfg: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    expected = dict(system.get("expected_partition", {}))
    return {
        "sysname": str(system["system_id"]),
        "cation": str(system["cation"]),
        "valence": int(system["valence"]),
        "substitution_amount_x": float(system["substitution_amount_x"]),
        "total_cation_count": int(system["expected_total_cation_count"]),
        "target_bottom_ions": int(expected["bottom_external"]),
        "target_interlayer_ions": int(expected["interlayer"]),
        "target_top_ions": int(expected["top_external"]),
    }


def execute_plan_claycode_inputs(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    campaign_path: Path,
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    system = campaign_system_config(campaign_cfg, system_id)
    system_plan = system_config(plan, system_id)
    expected_metadata = expected_planner_metadata(campaign_cfg, system)
    if not force and planner_outputs_match(task, base_dir, expected_metadata):
        return {
            "status": "completed",
            "mode": "already_exists",
            "message": "plan_claycode_inputs outputs already exist and match expected metadata",
            "written_files": task["expected_output_files"],
        }

    templates = campaign_cfg.get("templates", {})
    if not isinstance(templates, dict):
        templates = {}
    template_yaml = plan_campaign.resolve_path(templates.get("claycode_yaml", "assets/claycode/MyMont1.yaml"), base_dir)
    template_csv = plan_campaign.resolve_path(templates.get("claycode_csv", "assets/claycode/exp_clay.csv"), base_dir)
    out_dir = base_dir / system_plan["example_dir"] / "claycode_inputs"
    generated = plan_claycode_inputs.generate_plan(
        case_path=base_dir / f"case.{system_id}.yaml",
        template_yaml=template_yaml,
        template_csv=template_csv,
        out_dir=out_dir,
        cations=[str(system["cation"])],
        charges=[float(system["substitution_amount_x"])],
        base_name="Mt",
        valence_overrides={str(system["cation"]): int(system["valence"])},
        force=force,
    )
    return {
        "status": "completed",
        "mode": "generated",
        "message": "generated ClayCode planner YAML/CSV/metadata files only; did not run ClayCode",
        "written_files": [rel(Path(value), base_dir) for value in [
            generated["variants"][0]["yaml"],
            generated["variants"][0]["csv"],
            generated["variants"][0]["metadata"],
            str(out_dir / "claycode_input_plan.json"),
        ]],
    }


def raw_outputs_match(task: dict[str, Any], base_dir: Path, system_id: str) -> bool:
    outputs = [base_dir / path for path in task["expected_output_files"]]
    return all(path.exists() and system_id in path.name for path in outputs)


def claycode_work_dir(plan: dict[str, Any], system_id: str, base_dir: Path) -> Path:
    system = system_config(plan, system_id)
    return base_dir / system["example_dir"] / "claycode_inputs"


def find_claycode_output_pair(work_dir: Path, system_id: str) -> tuple[Path, Path]:
    preferred_prefixes = [f"{system_id}_5_4", system_id]
    for prefix in preferred_prefixes:
        gro = next(iter(sorted(work_dir.rglob(f"{prefix}.gro"))), None)
        top = next(iter(sorted(work_dir.rglob(f"{prefix}.top"))), None)
        if gro and top:
            return gro, top

    gro_files = sorted(path for path in work_dir.rglob(f"{system_id}*.gro") if path.is_file())
    top_files = sorted(path for path in work_dir.rglob(f"{system_id}*.top") if path.is_file())
    if len(gro_files) == 1 and len(top_files) == 1:
        return gro_files[0], top_files[0]
    if not gro_files or not top_files:
        raise FileNotFoundError(f"ClayCode did not produce unambiguous {system_id} .gro/.top outputs in {work_dir}")
    raise ValueError(
        f"Ambiguous ClayCode outputs for {system_id}: "
        f"gro={[str(path) for path in gro_files]}, top={[str(path) for path in top_files]}"
    )


def execute_run_claycode(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    prerequisite_id = f"{system_id}:plan_claycode_inputs"
    prerequisite = task_by_id(plan, prerequisite_id)
    if prerequisite is None or prerequisite["status"] != plan_campaign.STATUS_COMPLETED:
        return {
            "status": "failed",
            "reason": "missing_dependency",
            "message": f"run_claycode requires completed {prerequisite_id}",
        }
    if not force and raw_outputs_match(task, base_dir, system_id):
        return {
            "status": "completed",
            "mode": "already_exists",
            "message": "raw .gro/.top already exist for target system; did not rerun ClayCode",
            "copied_raw_gro": task["expected_output_files"][0],
            "copied_raw_top": task["expected_output_files"][1],
        }

    work_dir = claycode_work_dir(plan, system_id, base_dir)
    input_yaml = work_dir / f"{system_id}.yaml"
    exp_csv = work_dir / f"{system_id}.csv"
    try:
        run_claycode.require_file(input_yaml, "ClayCode input YAML")
        run_claycode.require_file(exp_csv, "ClayCode experiment CSV")
    except FileNotFoundError as exc:
        return {"status": "failed", "reason": "missing_input", "message": str(exc)}

    command = ["ClayCode", "builder", "-f", input_yaml.name]
    stdout_path = work_dir / f"{system_id}.claycode.stdout"
    stderr_path = work_dir / f"{system_id}.claycode.stderr"
    log_path = work_dir / f"{system_id}.claycode_status.json"
    started = run_claycode.now_iso()
    t0 = time.time()
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(command, cwd=work_dir, stdout=stdout, stderr=stderr)
    elapsed = time.time() - t0
    status: dict[str, Any] = {
        "status": "running",
        "stage": "run_claycode",
        "system_id": system_id,
        "cwd": rel(work_dir, base_dir),
        "command": command,
        "command_string": " ".join(command),
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(stdout_path, base_dir),
        "stderr": rel(stderr_path, base_dir),
        "started_at": started,
        "finished_at": run_claycode.now_iso(),
        "selected_gro": None,
        "selected_top": None,
        "copied_raw_gro": None,
        "copied_raw_top": None,
    }
    if proc.returncode != 0:
        status["status"] = "failed"
        status["error"] = "ClayCode command failed"
        write_json(log_path, status)
        return {
            "status": "failed",
            "reason": "claycode_failed",
            "message": "ClayCode command failed",
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": rel(stdout_path, base_dir),
            "stderr": rel(stderr_path, base_dir),
            "log_path": rel(log_path, base_dir),
            "command": command,
        }

    try:
        selected_gro, selected_top = find_claycode_output_pair(work_dir, system_id)
    except (FileNotFoundError, ValueError) as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        write_json(log_path, status)
        return {
            "status": "failed",
            "reason": "ambiguous_or_missing_outputs",
            "message": str(exc),
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": rel(stdout_path, base_dir),
            "stderr": rel(stderr_path, base_dir),
            "log_path": rel(log_path, base_dir),
            "command": command,
        }

    destination_gro = base_dir / task["expected_output_files"][0]
    destination_top = base_dir / task["expected_output_files"][1]
    if (destination_gro.exists() or destination_top.exists()) and not force:
        status["status"] = "failed"
        status["error"] = "Destination raw .gro/.top exists. Use --force to overwrite."
        write_json(log_path, status)
        return {
            "status": "failed",
            "reason": "destination_exists",
            "message": status["error"],
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "log_path": rel(log_path, base_dir),
        }

    destination_gro.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected_gro, destination_gro)
    shutil.copy2(selected_top, destination_top)
    status.update(
        {
            "status": "completed",
            "selected_gro": rel(selected_gro, base_dir),
            "selected_top": rel(selected_top, base_dir),
            "copied_raw_gro": rel(destination_gro, base_dir),
            "copied_raw_top": rel(destination_top, base_dir),
        }
    )
    write_json(log_path, status)
    return {
        "status": "completed",
        "mode": "generated",
        "message": "ran ClayCode and staged selected raw .gro/.top only; did not run preparation or LAMMPS",
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(stdout_path, base_dir),
        "stderr": rel(stderr_path, base_dir),
        "log_path": rel(log_path, base_dir),
        "selected_gro": rel(selected_gro, base_dir),
        "selected_top": rel(selected_top, base_dir),
        "copied_raw_gro": rel(destination_gro, base_dir),
        "copied_raw_top": rel(destination_top, base_dir),
    }




def write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to write campaign case files") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def case_expected_paths(system_id: str, base_dir: Path) -> dict[str, Path]:
    example_dir = base_dir / "examples" / system_id
    return {
        "case_file": base_dir / f"case.{system_id}.yaml",
        "example_dir": example_dir,
        "raw_dir": example_dir / "raw",
        "generated_dir": example_dir / "generated",
        "prepared_dir": example_dir / "inputs",
        "raw_gro": example_dir / "raw" / f"{system_id}_5_4.gro",
        "raw_top": example_dir / "raw" / f"{system_id}_5_4.top",
        "planner_metadata": example_dir / "claycode_inputs" / f"{system_id}.metadata.json",
        "molecule_template": base_dir / "assets" / "forcefields" / "SPCEH2O_types_8_10.txt",
    }


def existing_case_matches(case_file: Path, system_id: str, expected: dict[str, Path], cation: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        cfg = plan_campaign.load_yaml(case_file)
    except Exception as exc:  # pragma: no cover - defensive path
        return False, [f"Unable to read existing case file: {exc}"]
    if str(cfg.get("case", {}).get("name")) != system_id:
        errors.append("case.name does not match target system")
    paths = cfg.get("paths", {}) if isinstance(cfg.get("paths"), dict) else {}
    for key in ["raw_gro", "raw_top", "raw_dir", "generated_dir", "prepared_dir"]:
        expected_rel = rel(expected[key], case_file.parent.resolve())
        if str(paths.get(key)) != expected_rel:
            errors.append(f"paths.{key} points to {paths.get(key)!r}, expected {expected_rel!r}")
    structure = cfg.get("structure", {}) if isinstance(cfg.get("structure"), dict) else {}
    if str(structure.get("cation")) != cation:
        errors.append("structure.cation does not match target cation")
    return not errors, errors


def build_case_from_campaign(campaign_cfg: dict[str, Any], system: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    system_id = str(system["system_id"])
    cation = str(system["cation"])
    x = float(system["substitution_amount_x"])
    expected = case_expected_paths(system_id, base_dir)
    template_case = base_dir / "case.yaml"
    if not template_case.exists():
        raise FileNotFoundError("Missing legacy template case.yaml for create_case_file")
    cfg = copy.deepcopy(plan_campaign.load_yaml(template_case))

    cfg.setdefault("case", {})
    cfg["case"]["name"] = system_id
    cfg["case"]["description"] = f"Campaign-generated case for {system_id}"

    cfg["claycode"] = {
        "work_dir": rel(expected["example_dir"] / "claycode_inputs", base_dir),
        "input_yaml": f"{system_id}.yaml",
        "exp_csv": f"{system_id}.csv",
        "output_dir": system_id,
        "selected_prefix": f"{system_id}_5_4",
        "command": ["ClayCode", "builder", "-f", f"{system_id}.yaml"],
    }

    old_paths = cfg.get("paths", {}) if isinstance(cfg.get("paths"), dict) else {}
    cfg["paths"] = {
        "example_dir": rel(expected["example_dir"], base_dir),
        "template_dir": old_paths.get("template_dir", "templates"),
        "script_dir": old_paths.get("script_dir", "scripts"),
        "agent_dir": old_paths.get("agent_dir", "mtagent"),
        "raw_gro": rel(expected["raw_gro"], base_dir),
        "raw_top": rel(expected["raw_top"], base_dir),
        "raw_dir": rel(expected["raw_dir"], base_dir),
        "forcefield_file": old_paths.get("forcefield_file", "assets/forcefields/clayff-paper-2021"),
        "generated_dir": rel(expected["generated_dir"], base_dir),
        "prepared_dir": rel(expected["prepared_dir"], base_dir),
    }

    partition = dict(system.get("expected_partition", {}))
    cfg["structure"] = {
        "claycode_model": system_id,
        "x_cells": int(campaign_cfg.get("geometry", {}).get("x_cells", 5)),
        "y_cells": int(campaign_cfg.get("geometry", {}).get("y_cells", 4)),
        "n_sheets": int(campaign_cfg.get("geometry", {}).get("n_sheets", 2)),
        "layer_charge_per_uc": -x,
        "cation": cation,
        "expected_ion_count": int(system["expected_total_cation_count"]),
        "planner_metadata": rel(expected["planner_metadata"], base_dir),
        "target_ion_distribution": partition,
    }
    if cation == "Na":
        cfg["structure"]["target_na_distribution"] = dict(partition)

    cfg.setdefault("water", {})
    templates = campaign_cfg.get("templates", {}) if isinstance(campaign_cfg.get("templates"), dict) else {}
    cfg["water"].setdefault("model", "SPCE")
    cfg["water"].setdefault("spce_source", "assets/forcefields/SPCEH2O.txt")
    cfg["water"]["molecule_template"] = templates.get("water_molecule_template", cfg["water"].get("molecule_template", "assets/forcefields/SPCEH2O_types_8_10.txt"))
    cfg["water"].setdefault("oxygen_type", 8)
    cfg["water"].setdefault("hydrogen_type", 10)
    cfg["water"].setdefault("bond_type", 1)
    cfg["water"].setdefault("angle_type", 1)

    cfg.setdefault("equilibration", {})
    cfg["equilibration"].update({
        "run_dir": rel(expected["example_dir"] / "equilibration", base_dir),
        "output_data": rel(expected["prepared_dir"] / f"{system_id}_equilibrated.data", base_dir),
        "output_restart": rel(expected["prepared_dir"] / "restart.pre_gcmc.final", base_dir),
    })
    return cfg


def execute_create_case_file(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    system = campaign_system_config(campaign_cfg, system_id)
    cation = str(system["cation"])
    expected = case_expected_paths(system_id, base_dir)
    raw_gro = expected["raw_gro"]
    raw_top = expected["raw_top"]
    if not (raw_gro.exists() and raw_top.exists()):
        return {
            "status": "failed",
            "reason": "missing_raw_inputs",
            "message": f"create_case_file requires exact target raw files for {system_id}",
            "raw_gro": rel(raw_gro, base_dir),
            "raw_top": rel(raw_top, base_dir),
        }
    case_file = expected["case_file"]
    if case_file.exists() and not force:
        ok, errors = existing_case_matches(case_file, system_id, expected, cation)
        if ok:
            return {
                "status": "completed",
                "mode": "already_exists",
                "message": "case file already exists and matches target system; did not overwrite",
                "case_file": rel(case_file, base_dir),
            }
        return {
            "status": "failed",
            "reason": "existing_case_mismatch",
            "message": "existing case file does not match target system; use --force only after review",
            "case_file": rel(case_file, base_dir),
            "errors": errors,
        }
    try:
        cfg = build_case_from_campaign(campaign_cfg, system, base_dir)
    except FileNotFoundError as exc:
        return {"status": "failed", "reason": "missing_template_case", "message": str(exc)}
    write_yaml(case_file, cfg)
    ok, errors = existing_case_matches(case_file, system_id, expected, cation)
    if not ok:
        return {
            "status": "failed",
            "reason": "generated_case_failed_validation",
            "message": "generated case file failed validation",
            "case_file": rel(case_file, base_dir),
            "errors": errors,
        }
    return {
        "status": "completed",
        "mode": "generated" if not force else "overwritten",
        "message": "generated system-specific case file only; did not run prepare_case",
        "case_file": rel(case_file, base_dir),
        "raw_gro": rel(raw_gro, base_dir),
        "raw_top": rel(raw_top, base_dir),
        "cation": cation,
        "expected_ion_count": int(system["expected_total_cation_count"]),
        "expected_partition": system.get("expected_partition", {}),
    }

def prepared_validation_summary(
    *,
    check_json: Path,
    report_json: Path,
    include_path: Path,
    molecule_template: Path | None,
    expected_ion_species: str,
    expected_ion_count: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "passed": False,
        "errors": [],
        "warnings": [],
        "total_charge": None,
        "expected_ion_species": expected_ion_species,
        "expected_ion_count": expected_ion_count,
        "exchangeable_ion_count": None,
        "target_partition": None,
        "partition_after": None,
        "molecule_id_normalization": None,
        "exchangeable_ions_group_exists": False,
        "sodium_alias_exists": False,
        "water_template_type_compatible": None,
    }
    if not check_json.exists():
        summary["errors"].append(f"Missing prepared check JSON: {check_json}")
        return summary
    if not report_json.exists():
        summary["errors"].append(f"Missing prepared report JSON: {report_json}")
        return summary

    check = json.loads(check_json.read_text())
    report = json.loads(report_json.read_text())
    summary["errors"].extend(check.get("errors", []))
    summary["warnings"].extend(check.get("warnings", []))
    summary["total_charge"] = check.get("total_charge")
    chemistry = check.get("chemistry", {}) if isinstance(check.get("chemistry"), dict) else {}
    summary["exchangeable_ion_count"] = chemistry.get("exchangeable_ion_atoms")
    norm = chemistry.get("molecule_id_normalization_check")
    summary["molecule_id_normalization"] = norm
    if isinstance(norm, dict):
        summary["errors"].extend(norm.get("errors", []))
        summary["warnings"].extend(norm.get("warnings", []))

    summary["target_partition"] = report.get("target_ion_distribution")
    summary["partition_after"] = report.get("ion_distribution_after")
    type_ids = report.get("type_ids", {}) if isinstance(report.get("type_ids"), dict) else {}
    water_o = type_ids.get("water_oxygen", 8)
    water_h = type_ids.get("water_hydrogen", 10)
    if molecule_template and molecule_template.exists():
        text = molecule_template.read_text()
        summary["water_template_type_compatible"] = (str(water_o) in text and str(water_h) in text)
    else:
        summary["water_template_type_compatible"] = None

    if include_path.exists():
        inc = include_path.read_text()
        summary["exchangeable_ions_group_exists"] = "group exchangeable_ions" in inc
        summary["sodium_alias_exists"] = "group sodium" in inc
    else:
        summary["errors"].append(f"Missing groups/regions include: {include_path}")

    if check.get("passed") is not True:
        summary["errors"].append("check_lammps_data did not report passed=true")
    if summary["exchangeable_ion_count"] != expected_ion_count:
        summary["errors"].append(
            f"Expected {expected_ion_count} {expected_ion_species} exchangeable ions, "
            f"found {summary['exchangeable_ion_count']}"
        )
    if not summary["exchangeable_ions_group_exists"]:
        summary["errors"].append("exchangeable_ions group missing")
    if not summary["sodium_alias_exists"]:
        summary["errors"].append("sodium compatibility alias missing")
    if summary["water_template_type_compatible"] is False:
        summary["errors"].append("water molecule template types do not match prepared water O/H types")

    summary["passed"] = not summary["errors"]
    return summary


def prepared_outputs_valid_for_system(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    system_id: str,
    base_dir: Path,
) -> tuple[bool, dict[str, Any]]:
    prepare_task = task_by_id(plan, f"{system_id}:prepare_case")
    if prepare_task is None:
        return False, {"passed": False, "errors": [f"Missing prepare_case task for {system_id}"]}
    system = campaign_system_config(campaign_cfg, system_id)
    templates = campaign_cfg.get("templates", {}) if isinstance(campaign_cfg.get("templates"), dict) else {}
    molecule_template = plan_campaign.resolve_path(
        templates.get("water_molecule_template", "assets/forcefields/SPCEH2O_types_8_10.txt"),
        base_dir,
    )
    return prepared_outputs_valid(
        prepare_task,
        base_dir,
        expected_ion_species=str(system["cation"]),
        expected_ion_count=int(system["expected_total_cation_count"]),
        molecule_template=molecule_template,
    )


def run_equilibrate_paths(system_id: str, base_dir: Path) -> dict[str, Path]:
    example_dir = base_dir / "examples" / system_id
    return {
        "case_file": base_dir / f"case.{system_id}.yaml",
        "run_dir": example_dir / "equilibration",
        "status": example_dir / "equilibration" / "equilibration_status.json",
        "log": example_dir / "equilibration" / "log.lammps",
        "stdout": example_dir / "generated" / f"{system_id}.run_equilibrate.stdout",
        "stderr": example_dir / "generated" / f"{system_id}.run_equilibrate.stderr",
        "status_copy": example_dir / "generated" / f"{system_id}.run_equilibrate_status.json",
        "diagnostics": example_dir / "generated" / f"{system_id}.run_equilibrate_diagnostics.json",
        "output_data": example_dir / "inputs" / f"{system_id}_equilibrated.data",
        "output_restart": example_dir / "inputs" / "restart.pre_gcmc.final",
    }


def load_equilibration_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def run_equilibrate_diagnostics(paths: dict[str, Path]) -> dict[str, Any]:
    status_doc = load_equilibration_status(paths["status"])
    runner = status_doc.get("runner", {}) if isinstance(status_doc.get("runner"), dict) else {}
    diagnostic_inputs = [
        paths["log"],
        paths["stdout"],
        paths["stderr"],
        Path(runner.get("stdout", "")) if runner.get("stdout") else paths["run_dir"] / "in.equilibrate_pre_gcmc.stdout",
        Path(runner.get("stderr", "")) if runner.get("stderr") else paths["run_dir"] / "in.equilibrate_pre_gcmc.stderr",
    ]
    result = diagnose_run.diagnose_files(
        diagnostic_inputs,
        expected_files=[paths["output_data"], paths["output_restart"]],
    )
    handoff = status_doc.get("handoff_diagnostics") if isinstance(status_doc.get("handoff_diagnostics"), dict) else None
    if handoff is None and paths["diagnostics"].exists():
        try:
            loaded = json.loads(paths["diagnostics"].read_text())
            if isinstance(loaded, dict) and "handoff_status" in loaded:
                handoff = loaded
        except json.JSONDecodeError:
            result.setdefault("warnings", []).append(f"Unable to parse handoff diagnostics: {paths['diagnostics']}")
    if handoff:
        result["handoff_diagnostics"] = handoff
        result["handoff_status"] = handoff.get("handoff_status") or handoff.get("status")
        result["handoff_basal_prepared"] = handoff.get("handoff_basal_prepared")
        result["handoff_basal_equilibrated"] = handoff.get("handoff_basal_equilibrated")
        result["handoff_basal_drift"] = handoff.get("handoff_basal_drift")
        if handoff.get("status") == "failed":
            result.setdefault("errors", []).append("pre-GCMC basal handoff sanity check failed")
        elif handoff.get("status") == "warning":
            result.setdefault("warnings", []).append("pre-GCMC basal handoff sanity check warning")
    result["equilibration_status"] = status_doc.get("status")
    result["runner_return_code"] = runner.get("return_code")
    result["status"] = "failed" if result.get("errors") else "warning" if result.get("warnings") or result.get("known_warnings") else "ok"
    return result


def equilibration_outputs_valid(paths: dict[str, Path]) -> tuple[bool, dict[str, Any]]:
    diagnostics = run_equilibrate_diagnostics(paths)
    status_doc = load_equilibration_status(paths["status"])
    status_ok = not status_doc or status_doc.get("status") == "completed"
    ok = (
        paths["output_data"].exists()
        and paths["output_restart"].exists()
        and status_ok
        and diagnostics.get("status") != "failed"
    )
    return ok, diagnostics


def equilibration_step_overrides(campaign_cfg: dict[str, Any]) -> tuple[int, int]:
    policy = campaign_cfg.get("simulation_policy", {}) if isinstance(campaign_cfg.get("simulation_policy"), dict) else {}
    soft_steps = int(policy.get("pre_gcmc_soft_steps", 5000))
    nvt_steps = int(policy.get("pre_gcmc_smoke_steps", policy.get("pre_gcmc_equilibration_smoke_steps", 10000)))
    return soft_steps, nvt_steps


def execute_run_equilibrate(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    valid_prepared, prepared_validation = prepared_outputs_valid_for_system(
        campaign_cfg=campaign_cfg, plan=plan, system_id=system_id, base_dir=base_dir
    )
    if not valid_prepared:
        return {
            "status": "failed",
            "reason": "prepared_outputs_invalid",
            "message": "run_equilibrate requires prepared outputs that pass checks",
            "validation": prepared_validation,
        }

    paths = run_equilibrate_paths(system_id, base_dir)
    if not paths["case_file"].exists():
        return {"status": "failed", "reason": "missing_case_file", "case_file": rel(paths["case_file"], base_dir)}

    existing = [paths["output_data"], paths["output_restart"]]
    if any(path.exists() for path in existing) and not force:
        ok, diagnostics = equilibration_outputs_valid(paths)
        if ok:
            return {
                "status": "completed",
                "mode": "already_exists",
                "message": "equilibration outputs already exist and diagnostics did not find failures",
                "diagnostics": diagnostics,
                "output_data": rel(paths["output_data"], base_dir),
                "output_restart": rel(paths["output_restart"], base_dir),
            }
        return {
            "status": "failed",
            "reason": "existing_equilibration_outputs_invalid",
            "message": "equilibration outputs already exist but diagnostics/status are not clean; use --force only after review",
            "diagnostics": diagnostics,
        }

    paths["stdout"].parent.mkdir(parents=True, exist_ok=True)
    soft_steps, nvt_steps = equilibration_step_overrides(campaign_cfg)
    command = [
        sys.executable,
        "mtagent/run_equilibrate.py",
        "--case",
        rel(paths["case_file"], base_dir),
        "--run",
        "--soft-steps-override",
        str(soft_steps),
        "--steps-override",
        str(nvt_steps),
    ]
    if force:
        command.append("--force")
    t0 = time.time()
    with paths["stdout"].open("w") as stdout, paths["stderr"].open("w") as stderr:
        proc = subprocess.run(command, cwd=base_dir, stdout=stdout, stderr=stderr, text=True)
    elapsed = time.time() - t0
    diagnostics = run_equilibrate_diagnostics(paths)
    paths["diagnostics"].write_text(json.dumps(diagnostics, indent=2) + "\n")

    action_completed = proc.returncode == 0 and diagnostics.get("status") != "failed"
    completion_status = "completed_with_warnings" if action_completed and diagnostics.get("status") == "warning" else "completed" if action_completed else "failed"
    status_doc = {
        "status": "completed" if action_completed else "failed",
        "completion_status": completion_status,
        "stage": "run_equilibrate",
        "system_id": system_id,
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(paths["stdout"], base_dir),
        "stderr": rel(paths["stderr"], base_dir),
        "equilibration_status": rel(paths["status"], base_dir) if paths["status"].exists() else None,
        "diagnostics_path": rel(paths["diagnostics"], base_dir),
        "diagnostics": diagnostics,
        "output_data": rel(paths["output_data"], base_dir),
        "output_restart": rel(paths["output_restart"], base_dir),
        "soft_start_steps": soft_steps,
        "nvt_steps": nvt_steps,
    }
    paths["status_copy"].write_text(json.dumps(status_doc, indent=2) + "\n")

    if proc.returncode != 0:
        return {**status_doc, "reason": "run_equilibrate_failed", "message": "run_equilibrate.py command failed", "log_path": rel(paths["status_copy"], base_dir)}
    if diagnostics.get("status") == "failed":
        return {**status_doc, "reason": "equilibration_diagnostics_failed", "message": "LAMMPS diagnostics found failure signatures", "log_path": rel(paths["status_copy"], base_dir)}
    return {
        **status_doc,
        "mode": "generated",
        "message": "ran short pre-GCMC equilibration and diagnostics; did not run GCMC",
        "log_path": rel(paths["status_copy"], base_dir),
    }


def prepared_outputs_valid(task: dict[str, Any], base_dir: Path, expected_ion_species: str, expected_ion_count: int, molecule_template: Path | None) -> tuple[bool, dict[str, Any]]:
    outputs = [base_dir / path for path in task["expected_output_files"]]
    if not all(path.exists() for path in outputs):
        missing = [rel(path, base_dir) for path in outputs if not path.exists()]
        return False, {"passed": False, "errors": [f"Missing prepared outputs: {missing}"]}
    prepared_data = next(path for path in outputs if path.name.endswith("_prepared.data"))
    include = next(path for path in outputs if path.name.endswith("_groups_regions.inc"))
    report = next(path for path in outputs if path.name.endswith("_prepared.report.json"))
    check = next(path for path in outputs if path.name.endswith("_prepared.check.json"))
    summary = prepared_validation_summary(
        check_json=check,
        report_json=report,
        include_path=include,
        molecule_template=molecule_template,
        expected_ion_species=expected_ion_species,
        expected_ion_count=expected_ion_count,
    )
    summary["prepared_data"] = rel(prepared_data, base_dir)
    return bool(summary.get("passed")), summary


def execute_prepare_case(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    prerequisite_id = f"{system_id}:run_claycode"
    prerequisite = task_by_id(plan, prerequisite_id)
    raw_inputs = [base_dir / path for path in task["input_files"] if path.endswith((".gro", ".top"))]
    case_file = base_dir / f"case.{system_id}.yaml"
    if prerequisite is not None and prerequisite["status"] not in {plan_campaign.STATUS_COMPLETED, plan_campaign.STATUS_SKIPPED}:
        if not all(path.exists() and system_id in path.name for path in raw_inputs):
            return {
                "status": "failed",
                "reason": "missing_dependency",
                "message": f"prepare_case requires completed {prerequisite_id} or exact target raw .gro/.top files",
            }
    if not all(path.exists() and system_id in path.name for path in raw_inputs):
        return {
            "status": "failed",
            "reason": "missing_raw_inputs",
            "message": f"Missing exact target raw .gro/.top for {system_id}; legacy files are not accepted",
            "raw_inputs": [rel(path, base_dir) for path in raw_inputs],
        }
    if not case_file.exists():
        return {
            "status": "failed",
            "reason": "missing_case_file",
            "message": f"Missing case file {rel(case_file, base_dir)}; no campaign case-generation helper is defined yet",
        }

    system = campaign_system_config(campaign_cfg, system_id)
    expected_ion_species = str(system["cation"])
    expected_ion_count = int(system["expected_total_cation_count"])
    templates = campaign_cfg.get("templates", {}) if isinstance(campaign_cfg.get("templates"), dict) else {}
    molecule_template = plan_campaign.resolve_path(templates.get("water_molecule_template", "assets/forcefields/SPCEH2O_types_8_10.txt"), base_dir)
    valid, validation = prepared_outputs_valid(task, base_dir, expected_ion_species, expected_ion_count, molecule_template)
    if valid and not force:
        return {
            "status": "completed",
            "mode": "already_exists",
            "message": "prepared outputs already exist and passed validation; did not rerun prepare_case",
            "validation": validation,
        }
    existing_outputs = [base_dir / path for path in task["expected_output_files"] if (base_dir / path).exists()]
    if existing_outputs and not force and not valid:
        return {
            "status": "failed",
            "reason": "existing_outputs_failed_validation",
            "message": "prepared outputs already exist but did not pass validation; use --force only after review",
            "validation": validation,
        }

    generated_dir = base_dir / system_config(plan, system_id)["example_dir"] / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = generated_dir / f"{system_id}.prepare_case.stdout"
    stderr_path = generated_dir / f"{system_id}.prepare_case.stderr"
    status_path = generated_dir / f"{system_id}.prepare_case_status.json"
    command = [sys.executable, "mtagent/prepare_case.py", "--case", rel(case_file, base_dir)]
    t0 = time.time()
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(command, cwd=base_dir, stdout=stdout, stderr=stderr)
    elapsed = time.time() - t0
    valid, validation = prepared_outputs_valid(task, base_dir, expected_ion_species, expected_ion_count, molecule_template)
    status_doc = {
        "status": "completed" if proc.returncode == 0 and valid else "failed",
        "stage": "prepare_case",
        "system_id": system_id,
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(stdout_path, base_dir),
        "stderr": rel(stderr_path, base_dir),
        "validation": validation,
    }
    write_json(status_path, status_doc)
    if proc.returncode != 0:
        return {
            "status": "failed",
            "reason": "prepare_case_failed",
            "message": "prepare_case.py command failed",
            "command": command,
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": rel(stdout_path, base_dir),
            "stderr": rel(stderr_path, base_dir),
            "log_path": rel(status_path, base_dir),
            "validation": validation,
        }
    if not valid:
        return {
            "status": "failed",
            "reason": "prepared_outputs_failed_validation",
            "message": "prepare_case completed but prepared outputs failed validation",
            "command": command,
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout": rel(stdout_path, base_dir),
            "stderr": rel(stderr_path, base_dir),
            "log_path": rel(status_path, base_dir),
            "validation": validation,
        }
    return {
        "status": "completed",
        "mode": "generated",
        "message": "ran prepare_case and validated prepared LAMMPS inputs; did not run equilibration or GCMC",
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(stdout_path, base_dir),
        "stderr": rel(stderr_path, base_dir),
        "log_path": rel(status_path, base_dir),
        "prepared_outputs": task["expected_output_files"],
        "validation": validation,
    }

def initial_rh_paths(system_id: str, rh_tag: str, base_dir: Path) -> dict[str, Path]:
    run_dir = base_dir / "examples" / system_id / rh_tag.replace("rh", "rh_")
    return {
        "case_file": base_dir / f"case.{system_id}.yaml",
        "run_dir": run_dir,
        "status": run_dir / "initial_status.json",
        "log": run_dir / "log.lammps",
        "monitor": run_dir / f"monitor_gcmc_{rh_tag}.dat",
        "final_restart": run_dir / f"restart.gcmc_{rh_tag}.final",
        "after_data": run_dir / f"after_gcmc_{rh_tag}_initial.data",
        "stdout": base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.run_initial.stdout",
        "stderr": base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.run_initial.stderr",
        "status_copy": base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.run_initial_status.json",
        "diagnostics": base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.run_initial_diagnostics.json",
        "pre_gcmc_restart": base_dir / "examples" / system_id / "inputs" / "restart.pre_gcmc.final",
    }


def initial_rh_step_override(campaign_cfg: dict[str, Any]) -> int:
    policy = campaign_cfg.get("simulation_policy", {}) if isinstance(campaign_cfg.get("simulation_policy"), dict) else {}
    return int(policy.get("initial_rh_smoke_steps", policy.get("initial_rh_validation_steps", 100000)))


def initial_rh_diagnostics(paths: dict[str, Path], expected_ion_count: int) -> dict[str, Any]:
    status_doc = load_equilibration_status(paths["status"])
    runner = status_doc.get("runner", {}) if isinstance(status_doc.get("runner"), dict) else {}
    log_paths = [
        paths["log"],
        paths["stdout"],
        paths["stderr"],
        Path(runner.get("stdout", "")) if runner.get("stdout") else paths["run_dir"] / "in.gcmc_rh0p90_initial.stdout",
        Path(runner.get("stderr", "")) if runner.get("stderr") else paths["run_dir"] / "in.gcmc_rh0p90_initial.stderr",
    ]
    result = diagnose_run.diagnose_gcmc_run(
        log_paths=log_paths,
        monitor_path=paths["monitor"],
        expected_files=[paths["final_restart"], paths["after_data"], paths["monitor"]],
        status_json=paths["status"],
        expected_ion_count=expected_ion_count,
    )
    result["runner_return_code"] = runner.get("return_code")
    return result


def initial_outputs_valid(paths: dict[str, Path], expected_ion_count: int) -> tuple[bool, dict[str, Any]]:
    diagnostics = initial_rh_diagnostics(paths, expected_ion_count)
    status_doc = load_equilibration_status(paths["status"])
    status_ok = not status_doc or status_doc.get("status") == "completed"
    ok = (
        paths["final_restart"].exists()
        and paths["after_data"].exists()
        and paths["monitor"].exists()
        and status_ok
        and diagnostics.get("status") != "failed"
    )
    return ok, diagnostics


def execute_run_initial_rh(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    system_id = task["system_id"]
    rh_tag = rh_tag_for_task(task, "run_initial_rh")
    if rh_tag is None:
        return {"status": "skipped", "reason": "unsupported_initial_stage", "stage": task["stage"]}
    if previous_rh_tag_for_task(task, campaign_cfg) is not None:
        return execute_run_initial_from_previous_rh(campaign_cfg=campaign_cfg, task=task, base_dir=base_dir, force=force)
    system = campaign_system_config(campaign_cfg, system_id)
    expected_ion_count = int(system["expected_total_cation_count"])
    paths = initial_rh_paths(system_id, rh_tag, base_dir)
    if not paths["case_file"].exists():
        return {"status": "failed", "reason": "missing_case_file", "case_file": rel(paths["case_file"], base_dir)}
    if not paths["pre_gcmc_restart"].exists():
        return {
            "status": "failed",
            "reason": "missing_pre_gcmc_restart",
            "message": "run_initial requires pre-GCMC restart from run_equilibrate",
            "pre_gcmc_restart": rel(paths["pre_gcmc_restart"], base_dir),
        }

    if any(path.exists() for path in [paths["final_restart"], paths["after_data"], paths["monitor"]]) and not force:
        ok, diagnostics = initial_outputs_valid(paths, expected_ion_count)
        if ok:
            return {
                "status": "completed",
                "mode": "already_exists",
                "message": "initial RH outputs already exist and diagnostics did not find failures",
                "diagnostics": diagnostics,
                "final_restart": rel(paths["final_restart"], base_dir),
                "after_data": rel(paths["after_data"], base_dir),
                "monitor": rel(paths["monitor"], base_dir),
            }
        return {
            "status": "failed",
            "reason": "existing_initial_outputs_invalid",
            "message": "initial RH outputs already exist but diagnostics/status are not clean; use --force only after review",
            "diagnostics": diagnostics,
        }

    paths["stdout"].parent.mkdir(parents=True, exist_ok=True)
    steps = initial_rh_step_override(campaign_cfg)
    command = [
        sys.executable,
        "mtagent/run_initial.py",
        "--case",
        rel(paths["case_file"], base_dir),
        "--run-dir",
        rel(paths["run_dir"], base_dir),
        "--run",
        "--np",
        "16",
        "--segment-steps-override",
        str(steps),
    ]
    if force:
        command.append("--force")
    t0 = time.time()
    with paths["stdout"].open("w") as stdout, paths["stderr"].open("w") as stderr:
        proc = subprocess.run(command, cwd=base_dir, stdout=stdout, stderr=stderr, text=True)
    elapsed = time.time() - t0
    diagnostics = initial_rh_diagnostics(paths, expected_ion_count)
    paths["diagnostics"].write_text(json.dumps(diagnostics, indent=2) + "\n")

    action_completed = proc.returncode == 0 and diagnostics.get("status") != "failed"
    completion_status = "completed_with_warnings" if action_completed and diagnostics.get("status") == "warning" else "completed" if action_completed else "failed"
    status_doc = {
        "status": "completed" if action_completed else "failed",
        "completion_status": completion_status,
        "stage": task["stage"],
        "system_id": system_id,
        "command": command,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": rel(paths["stdout"], base_dir),
        "stderr": rel(paths["stderr"], base_dir),
        "initial_status": rel(paths["status"], base_dir) if paths["status"].exists() else None,
        "diagnostics_path": rel(paths["diagnostics"], base_dir),
        "diagnostics": diagnostics,
        "final_restart": rel(paths["final_restart"], base_dir),
        "after_data": rel(paths["after_data"], base_dir),
        "monitor": rel(paths["monitor"], base_dir),
        "segment_steps": steps,
    }
    paths["status_copy"].write_text(json.dumps(status_doc, indent=2) + "\n")

    if proc.returncode != 0:
        return {**status_doc, "reason": "run_initial_failed", "message": "run_initial.py command failed", "log_path": rel(paths["status_copy"], base_dir)}
    if diagnostics.get("status") == "failed":
        return {**status_doc, "reason": "gcmc_diagnostics_failed", "message": "GCMC diagnostics found failure signatures", "log_path": rel(paths["status_copy"], base_dir)}
    return {
        **status_doc,
        "mode": "generated",
        "message": f"ran short {rh_stage_name(rh_tag)} initial GCMC validation and diagnostics; did not run continuation",
        "log_path": rel(paths["status_copy"], base_dir),
    }



def analysis_paths(system_id: str, rh_tag: str, base_dir: Path) -> dict[str, Path]:
    initial = initial_rh_paths(system_id, rh_tag, base_dir)
    generated = base_dir / "examples" / system_id / "generated"
    initial["analysis"] = generated / f"{system_id}.{rh_tag.replace('rh', 'rh_')}_analysis.json"
    return initial


def equilibrium_settings(campaign_cfg: dict[str, Any]) -> dict[str, Any]:
    return analyze_gcmc_equilibrium_restart.equilibrium_settings_from_config(campaign_cfg, rh_handoff=True)


RUNTIME_STATUS_STAGE_RE = re.compile(
    r"(?:^|/)(?:restart[^/]*|monitor[^/]*|log(?:\.|$)|[^/]*state\.json$|summary\.(?:json|md)$)"
    r"|(?:^|/)(?:rh_[0-9]+p[0-9]+|states)(?:/|$)"
    r"|\.data$"
)


def is_runtime_or_status_path(path: str) -> bool:
    return bool(RUNTIME_STATUS_STAGE_RE.search(path))


def analyze_rh_outputs(*, campaign_cfg: dict[str, Any], system_id: str, rh_tag: str, base_dir: Path) -> dict[str, Any]:
    system = campaign_system_config(campaign_cfg, system_id)
    expected_ion_count = int(system["expected_total_cation_count"])
    paths = analysis_paths(system_id, rh_tag, base_dir)
    diagnostics = initial_rh_diagnostics(paths, expected_ion_count)
    errors: list[str] = []
    warnings: list[str] = []
    if diagnostics.get("status") == "failed":
        errors.extend(str(item) for item in diagnostics.get("errors", []))
    if not paths["monitor"].exists():
        errors.append(f"Missing monitor file: {rel(paths['monitor'], base_dir)}")
    settings = equilibrium_settings(campaign_cfg)
    analyzer_result: dict[str, Any] = {}
    if not errors:
        try:
            data = analyze_gcmc_equilibrium_restart.read_monitors([paths["monitor"]], auto_offset_restarts=False)
            analyzer_result = analyze_gcmc_equilibrium_restart.analyze(data=data, **settings)
        except (SystemExit, Exception) as exc:  # analyzer uses SystemExit for malformed input
            errors.append(str(exc))
    water = diagnostics.get("water_summary", {}) if isinstance(diagnostics.get("water_summary"), dict) else {}
    ion = diagnostics.get("ion_summary", {}) if isinstance(diagnostics.get("ion_summary"), dict) else {}
    if water.get("basal_proxy_large_initial_relaxation"):
        warnings.append("basal_proxy_large_initial_relaxation")
    ion_stable = True
    if ion.get("observed_initial") is not None and ion.get("observed_final") is not None:
        ion_stable = int(round(float(ion["observed_initial"]))) == int(round(float(ion["observed_final"]))) == expected_ion_count
    else:
        ion_stable = False
        warnings.append("ion_count_not_observed")
    if not ion_stable:
        errors.append("exchangeable ion count changed or could not be confirmed")
    if errors:
        status = "failed"
        recommendation = "inspect"
    else:
        status = analyzer_result.get("status", "failed")
        recommendation = "archive" if status == "equilibrated" else "continue" if status in {"not_equilibrated", "not_enough_data", "marginal"} else "inspect"
        if water.get("basal_proxy_large_initial_relaxation"):
            recommendation = "inspect"
    result = {
        "status": status,
        "recommendation": recommendation,
        "system_id": system_id,
        "rh_tag": rh_tag,
        "monitor": rel(paths["monitor"], base_dir),
        "initial_status": rel(paths["status"], base_dir) if paths["status"].exists() else None,
        "diagnostics": diagnostics,
        "analyzer": analyzer_result,
        "criteria": settings,
        "final_timestep": water.get("final_step") or analyzer_result.get("step_end"),
        "total_water_initial": water.get("initial_total_water"),
        "total_water_final": water.get("final_total_water"),
        "interlayer_water_initial": water.get("initial_interlayer_water"),
        "interlayer_water_final": water.get("final_interlayer_water"),
        "external_water_initial": water.get("initial_external_water"),
        "external_water_final": water.get("final_external_water"),
        "basal_proxy_initial": water.get("basal_proxy_initial_raw", water.get("initial_basal_proxy")),
        "basal_proxy_final": water.get("basal_proxy_final", water.get("final_basal_proxy")),
        "basal_proxy_large_initial_relaxation": bool(water.get("basal_proxy_large_initial_relaxation")),
        "ion_count_stable": ion_stable,
        "ion_count_initial": ion.get("observed_initial"),
        "ion_count_final": ion.get("observed_final"),
        "known_warnings": diagnostics.get("known_warnings", []),
        "warnings": warnings,
        "fatal_errors": errors,
        "slope_window": analyzer_result.get("series", {}),
        "previous_window": analyzer_result.get("previous_window"),
        "checks": analyzer_result.get("checks", {}),
        "reasons": analyzer_result.get("reasons", []),
    }
    return result


def latest_analyzer_summary_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    analyzer = analysis.get("analyzer", {}) if isinstance(analysis.get("analyzer"), dict) else {}
    return {
        "analysis_status": analysis.get("status"),
        "analysis_recommendation": analysis.get("recommendation"),
        "equilibrium_status": analysis.get("status"),
        "equilibrium_recommendation": analysis.get("recommendation"),
        "final_window_slopes": archive_rh_result.final_window_slopes(analyzer),
        "previous_window": analyzer.get("previous_window"),
        "criteria": analysis.get("criteria", {}),
        "checks": analysis.get("checks", {}),
        "reasons": analysis.get("reasons", []),
        "fatal_errors": analysis.get("fatal_errors", []),
        "known_warnings": analysis.get("known_warnings", []),
        "manager_action": None,
    }


def rewrite_archive_summary_from_analysis(summary_path: Path, summary: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    updated = {**summary, **latest_analyzer_summary_fields(analysis)}
    archive_rh_result.write_json(summary_path, updated)
    required_for_md = {"rh", "timestamp", "final_step", "total_water", "interlayer_water", "external_water", "basal_proxy", "source_restart", "archived_restart", "selected_restart"}
    if required_for_md.issubset(updated):
        archive_rh_result.write_summary_md(summary_path.with_suffix(".md"), updated)
    return updated


def mark_downstream_rh_smoke_only(*, system_id: str, rh_tag: str, base_dir: Path, reason: str) -> None:
    rh_dir = base_dir / "examples" / system_id / rh_tag.replace("rh", "rh_")
    for name in ("start_next_rh_status.json", "initial_status.json"):
        path = rh_dir / name
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            doc = {}
        doc["production_valid"] = False
        doc["invalid_for_production"] = True
        doc["smoke_only"] = True
        doc["invalid_reason"] = reason
        write_json(path, doc)



def rh_tag_from_stage_suffix(stage: str, prefix: str) -> str | None:
    if stage == prefix:
        return None
    match = re.fullmatch(rf"{re.escape(prefix)}_?([0-9]+p[0-9]+)", stage)
    if not match:
        return None
    return f"rh{match.group(1)}"


def rh_tag_for_task(task: dict[str, Any], prefix: str) -> str | None:
    value = task.get("rh_tag")
    if value:
        return str(value)
    return rh_tag_from_stage_suffix(str(task.get("stage", "")), prefix)


def previous_rh_tag_for_task(task: dict[str, Any], campaign_cfg: dict[str, Any] | None = None) -> str | None:
    value = task.get("previous_rh_tag")
    if value:
        return str(value)
    rh_tag = task.get("rh_tag")
    if not rh_tag or campaign_cfg is None:
        return None
    rh_path = [float(rh) for rh in campaign_cfg.get("rh_path", [])]
    current = rh_value_from_tag(str(rh_tag))
    for index, rh in enumerate(rh_path):
        if abs(rh - current) < 1e-9 and index > 0:
            return plan_campaign.rh_tag(float(rh_path[index - 1]))
    return None


def canonical_rh_stage(task: dict[str, Any]) -> str:
    generic = task.get("generic_stage")
    if generic:
        return str(generic)
    stage = str(task.get("stage", ""))
    if stage == "start_next_rh" or rh_tag_from_stage_suffix(stage, "start_next_rh") is not None:
        return "start_next_rh"
    if stage == "run_initial_rh" or rh_tag_from_stage_suffix(stage, "run_initial_rh") is not None:
        return "run_initial_rh"
    if stage == "analyze_rh" or rh_tag_from_stage_suffix(stage, "analyze_rh") is not None:
        return "analyze_rh"
    if stage == "continue_or_archive_rh" or rh_tag_from_stage_suffix(stage, "continue_or_archive_rh") is not None:
        return "continue_or_archive_rh"
    return stage

def rh_tag_from_analyze_stage(stage: str) -> str | None:
    return rh_tag_from_stage_suffix(stage, "analyze_rh")


def rh_tag_from_continue_or_archive_stage(stage: str) -> str | None:
    return rh_tag_from_stage_suffix(stage, "continue_or_archive_rh")


def rh_value_from_tag(rh_tag: str) -> float:
    return float(rh_tag.removeprefix("rh").replace("p", "."))


def rh_stage_name(rh_tag: str) -> str:
    return rh_tag.replace("rh", "rh_")


def timestep_from_restart_path(value: Any) -> int | None:
    if not value:
        return None
    match = re.search(r"\.(\d+)$", str(value))
    return int(match.group(1)) if match else None


def rh_start_step_for_task(task: dict[str, Any], campaign_cfg: dict[str, Any], base_dir: Path) -> int:
    previous = previous_rh_tag_for_task(task, campaign_cfg)
    if previous is None:
        return 0
    system_id = str(task.get("system_id", ""))
    summary_path = base_dir / "examples" / system_id / "states" / rh_stage_name(previous) / "summary.json"
    try:
        summary = load_json(summary_path)
    except (OSError, json.JSONDecodeError):
        return 0
    for key in ("archived_restart", "selected_restart", "source_restart"):
        step = timestep_from_restart_path(summary.get(key))
        if step is not None:
            return step
    try:
        return max(0, int(summary.get("final_step", 0)))
    except (TypeError, ValueError):
        return 0


def execute_analyze_rh(*, campaign_cfg: dict[str, Any], task: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    rh_tag = rh_tag_for_task(task, "analyze_rh")
    if rh_tag is None:
        return {"status": "skipped", "reason": "unsupported_analyze_stage", "stage": task["stage"]}
    system_id = task["system_id"]
    paths = analysis_paths(system_id, rh_tag, base_dir)
    result = analyze_rh_outputs(campaign_cfg=campaign_cfg, system_id=system_id, rh_tag=rh_tag, base_dir=base_dir)
    paths["analysis"].parent.mkdir(parents=True, exist_ok=True)
    paths["analysis"].write_text(json.dumps(result, indent=2) + "\n")
    if result.get("rh_tag") == "rh0p90" and result.get("recommendation") != "archive":
        mark_downstream_rh_smoke_only(
            system_id=system_id,
            rh_tag="rh0p70",
            base_dir=base_dir,
            reason="RH=0.9 no longer passes stricter handoff analysis; rerun/continue RH=0.9 before using RH=0.7 as production data.",
        )
    action_status = "failed" if result["status"] == "failed" else "completed"
    return {
        "status": action_status,
        "stage": task["stage"],
        "system_id": system_id,
        "analysis_path": rel(paths["analysis"], base_dir),
        "analysis": result,
        "message": "analyzed RH monitor/status files; did not run LAMMPS, GCMC, continuation, or archive",
    }

def continue_or_archive_paths(system_id: str, rh_tag: str, base_dir: Path) -> dict[str, Path]:
    paths = analysis_paths(system_id, rh_tag, base_dir)
    paths["action_status"] = (
        base_dir
        / "examples"
        / system_id
        / "generated"
        / f"{system_id}.{rh_tag.replace('rh', 'rh_')}_continue_or_archive_status.json"
    )
    paths["continue_stdout"] = base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.continue.stdout"
    paths["continue_stderr"] = base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.continue.stderr"
    paths["archive_stdout"] = base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.archive.stdout"
    paths["archive_stderr"] = base_dir / "examples" / system_id / "generated" / f"{system_id}.{rh_tag}.archive.stderr"
    paths["archive_summary"] = base_dir / "examples" / system_id / "states" / rh_stage_name(rh_tag) / "summary.json"
    return paths


def continuation_segment_steps(system_id: str, base_dir: Path) -> int:
    case_file = base_dir / f"case.{system_id}.yaml"
    if not case_file.exists():
        return 100000
    case_cfg = plan_campaign.load_yaml(case_file)
    gcmc_cfg = case_cfg.get("gcmc", {}) if isinstance(case_cfg.get("gcmc"), dict) else {}
    return int(gcmc_cfg.get("segment_steps", 100000))


def read_analysis_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "missing_analysis_json"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None, "malformed_analysis_json"
    if not isinstance(data, dict):
        return None, "malformed_analysis_json"
    return data, None


def analysis_supports_archive(analysis: dict[str, Any]) -> bool:
    if analysis.get("status") != "equilibrated" or analysis.get("recommendation") != "archive":
        return False
    analyzer = analysis.get("analyzer")
    if not isinstance(analyzer, dict):
        return False
    if analyzer.get("status") != "equilibrated":
        return False
    if analyzer.get("recommendation") not in {"write_data_and_continue_next_rh", "archive"}:
        return False
    return True


def write_action_status(path: Path, status_doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status_doc, indent=2) + "\n")


def execute_continue_or_archive_rh(*, campaign_cfg: dict[str, Any], task: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    rh_tag = rh_tag_for_task(task, "continue_or_archive_rh")
    if rh_tag is None:
        return {"status": "skipped", "reason": "unsupported_continue_or_archive_stage", "stage": task["stage"]}
    system_id = task["system_id"]
    system = campaign_system_config(campaign_cfg, system_id)
    expected_ion_count = int(system["expected_total_cation_count"])
    paths = continue_or_archive_paths(system_id, rh_tag, base_dir)
    rh_stage = rh_stage_name(rh_tag)
    rh_value = rh_value_from_tag(rh_tag)
    started = time.time()
    base_status: dict[str, Any] = {
        "stage": task["stage"],
        "system_id": system_id,
        "input_analysis_file": rel(paths["analysis"], base_dir),
        "decision": None,
        "command": None,
        "return_code": None,
        "elapsed_seconds": 0.0,
        "new_final_timestep": None,
        "fatal_errors": [],
        "known_warnings": [],
        "next_recommended_action": None,
    }

    analysis, error = read_analysis_json(paths["analysis"])
    if error:
        status_doc = {
            **base_status,
            "status": "failed",
            "decision": "blocked",
            "reason": error,
            "message": f"Cannot choose RH action because {rel(paths['analysis'], base_dir)} is missing or invalid.",
        }
        status_doc["elapsed_seconds"] = time.time() - started
        write_action_status(paths["action_status"], status_doc)
        return {**status_doc, "log_path": rel(paths["action_status"], base_dir)}

    recommendation = analysis.get("recommendation")
    analysis_status = analysis.get("status")
    fatal_errors = list(analysis.get("fatal_errors", [])) if isinstance(analysis.get("fatal_errors"), list) else []
    known_warnings = list(analysis.get("known_warnings", [])) if isinstance(analysis.get("known_warnings"), list) else []
    base_status.update({"analysis_status": analysis_status, "analysis_recommendation": recommendation, "fatal_errors": fatal_errors, "known_warnings": known_warnings})

    if analysis_status == "failed" or recommendation in {"inspect", None} or recommendation not in {"continue", "archive"}:
        status_doc = {
            **base_status,
            "status": "failed",
            "decision": "blocked",
            "reason": "analysis_requires_inspection",
            "message": "RH analysis is failed, inspect, or ambiguous; no continuation or archive was run.",
            "next_recommended_action": f"inspect_{rh_stage}_analysis",
        }
        status_doc["elapsed_seconds"] = time.time() - started
        write_action_status(paths["action_status"], status_doc)
        return {**status_doc, "log_path": rel(paths["action_status"], base_dir)}

    if recommendation == "archive" and not analysis_supports_archive(analysis):
        status_doc = {
            **base_status,
            "status": "failed",
            "decision": "blocked",
            "reason": "analysis_archive_mismatch",
            "message": "Archive requires the read-only analysis and embedded analyzer to agree on equilibrated/archive.",
            "next_recommended_action": f"inspect_{rh_stage}_analysis",
        }
        status_doc["elapsed_seconds"] = time.time() - started
        write_action_status(paths["action_status"], status_doc)
        return {**status_doc, "log_path": rel(paths["action_status"], base_dir)}

    if recommendation == "continue":
        steps = continuation_segment_steps(system_id, base_dir)
        command = [
            sys.executable,
            "mtagent/run_cycle.py",
            "--run-dir",
            rel(paths["run_dir"], base_dir),
            "--case",
            rel(paths["case_file"], base_dir),
            "--run",
            "--np",
            "16",
            "--segment-steps-override",
            str(steps),
        ]
        policy = campaign_cfg.get("simulation_policy", {}) if isinstance(campaign_cfg.get("simulation_policy"), dict) else {}
        max_total_override = policy.get("max_total_steps_per_rh", policy.get("max_steps_per_rh"))
        if max_total_override is not None:
            command += ["--max-total-steps-per-rh-override", str(int(max_total_override))]
        paths["continue_stdout"].parent.mkdir(parents=True, exist_ok=True)
        with paths["continue_stdout"].open("w") as stdout, paths["continue_stderr"].open("w") as stderr:
            proc = subprocess.run(command, cwd=base_dir, stdout=stdout, stderr=stderr, text=True)
        elapsed = time.time() - started
        diagnostics = initial_rh_diagnostics(paths, expected_ion_count)
        water = diagnostics.get("water_summary", {}) if isinstance(diagnostics.get("water_summary"), dict) else {}
        status_doc = {
            **base_status,
            "status": "completed" if proc.returncode == 0 and diagnostics.get("status") != "failed" else "failed",
            "decision": "continue",
            "command": command,
            "return_code": proc.returncode,
            "elapsed_seconds": elapsed,
            "segment_steps": steps,
            "stdout": rel(paths["continue_stdout"], base_dir),
            "stderr": rel(paths["continue_stderr"], base_dir),
            "diagnostics": diagnostics,
            "new_final_timestep": water.get("final_step"),
            "fatal_errors": diagnostics.get("errors", []),
            "known_warnings": diagnostics.get("known_warnings", []),
            "next_recommended_action": f"analyze_{rh_stage}",
            "message": f"ran one conservative {rh_stage} continuation segment; inspect a fresh analyze_{rh_stage} result before another continuation",
        }
        if proc.returncode != 0:
            status_doc.update({"reason": "run_cycle_failed", "message": "run_cycle.py continuation command failed"})
        elif diagnostics.get("status") == "failed":
            status_doc.update({"reason": "gcmc_diagnostics_failed", "message": "Continuation completed but diagnostics found failure signatures"})
        write_action_status(paths["action_status"], status_doc)
        return {**status_doc, "log_path": rel(paths["action_status"], base_dir)}

    command = [
        sys.executable,
        "mtagent/archive_rh_result.py",
        "--run-dir",
        rel(paths["run_dir"], base_dir),
        "--rh",
        f"{rh_value:.2f}",
    ]
    try:
        summary = archive_rh_result.archive_rh_result(paths["run_dir"], rh=rh_value)
        summary = rewrite_archive_summary_from_analysis(paths["archive_summary"], summary, analysis)
        return_code = 0
        archive_error = None
    except Exception as exc:  # keep archive failures structured for campaign state
        summary = {}
        return_code = 1
        archive_error = str(exc)
    elapsed = time.time() - started
    status_doc = {
        **base_status,
        "status": "completed" if return_code == 0 else "failed",
        "decision": "archive",
        "command": command,
        "return_code": return_code,
        "elapsed_seconds": elapsed,
        "archive_summary": summary,
        "archive_summary_path": rel(paths["archive_summary"], base_dir) if paths["archive_summary"].exists() else None,
        "new_final_timestep": summary.get("final_step"),
        "next_recommended_action": None if return_code == 0 else f"inspect_{rh_stage}_archive_failure",
        "message": f"archived {rh_stage} result using existing archive logic" if return_code == 0 else "archive_rh_result failed",
    }
    if archive_error:
        status_doc.update({"reason": "archive_failed", "fatal_errors": [archive_error]})
    write_action_status(paths["action_status"], status_doc)
    return {**status_doc, "log_path": rel(paths["action_status"], base_dir)}

def expected_restart_from_archive_summary(summary_path: Path, base_dir: Path) -> Path | None:
    if not summary_path.exists():
        return None
    try:
        summary = json.loads(summary_path.read_text())
    except json.JSONDecodeError:
        return None
    value = summary.get("archived_restart") or summary.get("selected_restart")
    if not value:
        return None
    restart = Path(str(value))
    if restart.is_absolute():
        return restart
    return base_dir / restart


def execute_run_initial_from_previous_rh(*, campaign_cfg: dict[str, Any], task: dict[str, Any], base_dir: Path, force: bool) -> dict[str, Any]:
    system_id = task["system_id"]
    rh_tag = rh_tag_for_task(task, "run_initial_rh")
    previous_tag = previous_rh_tag_for_task(task, campaign_cfg)
    if rh_tag is None or previous_tag is None:
        return {"status": "skipped", "reason": "unsupported_initial_stage", "stage": task["stage"]}
    rh_value = rh_value_from_tag(rh_tag)
    case_file = base_dir / f"case.{system_id}.yaml"
    from_state = base_dir / "examples" / system_id / "states" / rh_stage_name(previous_tag)
    run_dir = base_dir / "examples" / system_id / rh_stage_name(rh_tag)
    status_path = run_dir / "start_next_rh_status.json"
    summary_path = from_state / "summary.json"
    expected_restart = expected_restart_from_archive_summary(summary_path, base_dir)
    command = [
        sys.executable,
        "mtagent/start_next_rh.py",
        "--case",
        rel(case_file, base_dir),
        "--from-state",
        rel(from_state, base_dir),
        "--rh",
        f"{rh_value:.2f}",
        "--run-dir",
        rel(run_dir, base_dir),
        "--run",
        "--np",
        "16",
    ]
    started = time.time()
    if not status_path.exists():
        return {
            "status": "failed",
            "reason": "missing_start_next_rh_status",
            "stage": task["stage"],
            "system_id": system_id,
            "status_file": rel(status_path, base_dir),
            "command": command,
            "elapsed_seconds": time.time() - started,
        }
    if expected_restart is None or not expected_restart.exists():
        return {
            "status": "failed",
            "reason": "missing_expected_archived_restart",
            "stage": task["stage"],
            "system_id": system_id,
            "expected_restart": rel(expected_restart, base_dir) if expected_restart is not None else None,
            "command": command,
            "elapsed_seconds": time.time() - started,
        }
    try:
        old_cwd = Path.cwd()
        try:
            os.chdir(base_dir)
            status = start_next_rh.start_next_rh(
                case_path=case_file,
                from_state=from_state,
                rh=rh_value,
                run_dir=run_dir,
                dry_run=False,
                run=True,
                force=force,
                np=16,
                segment_steps_override=None,
                write_input=True,
            )
        finally:
            os.chdir(old_cwd)
    except SystemExit as exc:
        status = load_json(status_path) if status_path.exists() else {}
        return_code = int(exc.code) if isinstance(exc.code, int) else 1
        elapsed = time.time() - started
        status_doc = {
            **status,
            "status": "failed",
            "reason": "start_next_rh_run_failed",
            "stage": task["stage"],
            "system_id": system_id,
            "command": command,
            "return_code": return_code,
            "elapsed_seconds": elapsed,
            "message": f"{rh_stage_name(rh_tag)} initial run failed",
        }
        write_json(status_path, status_doc)
        return {**status_doc, "log_path": rel(status_path, base_dir)}
    except Exception as exc:
        elapsed = time.time() - started
        status_doc = {
            "status": "failed",
            "reason": "start_next_rh_run_failed",
            "stage": task["stage"],
            "system_id": system_id,
            "command": command,
            "return_code": 1,
            "elapsed_seconds": elapsed,
            "fatal_errors": [str(exc)],
            "message": f"{rh_stage_name(rh_tag)} initial run failed",
        }
        write_json(status_path, status_doc)
        return {**status_doc, "log_path": rel(status_path, base_dir)}

    system = campaign_system_config(campaign_cfg, system_id)
    expected_ion_count = int(system["expected_total_cation_count"])
    paths = initial_rh_paths(system_id, rh_tag, base_dir)
    diagnostics = initial_rh_diagnostics(paths, expected_ion_count)
    water = diagnostics.get("water_summary", {}) if isinstance(diagnostics.get("water_summary"), dict) else {}
    ion = diagnostics.get("ion_summary", {}) if isinstance(diagnostics.get("ion_summary"), dict) else {}
    return_code = int(status.get("runner", {}).get("return_code", 0)) if isinstance(status.get("runner"), dict) else 0
    action_completed = return_code == 0 and diagnostics.get("status") != "failed" and status.get("status") == "completed"
    status_doc = {
        **status,
        "status": "completed" if action_completed else "failed",
        "stage": task["stage"],
        "system_id": system_id,
        "command": command,
        "return_code": return_code,
        "elapsed_seconds": time.time() - started,
        "diagnostics": diagnostics,
        "final_timestep": water.get("final_step"),
        "total_water": water.get("final_total_water"),
        "interlayer_water": water.get("final_interlayer_water"),
        "external_water": water.get("final_external_water"),
        "basal_proxy": water.get("basal_proxy_final", water.get("final_basal_proxy")),
        "ion_count_final": ion.get("observed_final"),
        "fatal_errors": diagnostics.get("errors", []),
        "known_warnings": diagnostics.get("known_warnings", []),
        "next_recommended_action": f"analyze_{rh_stage_name(rh_tag)}",
        "message": f"ran one {rh_stage_name(rh_tag)} initial GCMC segment from archived {rh_stage_name(previous_tag)} restart; did not run continuation or archive",
    }
    if not action_completed:
        status_doc.setdefault("reason", "gcmc_diagnostics_failed" if diagnostics.get("status") == "failed" else "run_initial_rh_failed")
    write_json(status_path, status_doc)
    return {**status_doc, "log_path": rel(status_path, base_dir)}


def execute_start_next_rh(*, campaign_cfg: dict[str, Any], task: dict[str, Any], base_dir: Path, force: bool) -> dict[str, Any]:
    rh_tag = rh_tag_for_task(task, "start_next_rh")
    previous_tag = previous_rh_tag_for_task(task, campaign_cfg)
    if rh_tag is None or previous_tag is None:
        return {"status": "skipped", "reason": "unsupported_start_next_stage", "stage": task["stage"]}
    rh_value = rh_value_from_tag(rh_tag)
    system_id = task["system_id"]
    case_file = base_dir / f"case.{system_id}.yaml"
    from_state = base_dir / "examples" / system_id / "states" / rh_stage_name(previous_tag)
    run_dir = base_dir / "examples" / system_id / rh_stage_name(rh_tag)
    status_path = run_dir / "start_next_rh_status.json"
    preview_status_path = run_dir / "start_next_rh_status.preview.json"
    summary_path = from_state / "summary.json"
    expected_restart = expected_restart_from_archive_summary(summary_path, base_dir)
    command = [
        sys.executable,
        "mtagent/start_next_rh.py",
        "--case",
        rel(case_file, base_dir),
        "--from-state",
        rel(from_state, base_dir),
        "--rh",
        f"{rh_value:.2f}",
        "--run-dir",
        rel(run_dir, base_dir),
        "--dry-run",
        "--write-input",
    ]
    started = time.time()
    if not case_file.exists():
        return {
            "status": "failed",
            "reason": "missing_case_file",
            "stage": task["stage"],
            "system_id": system_id,
            "case_file": rel(case_file, base_dir),
            "command": command,
            "elapsed_seconds": time.time() - started,
        }
    if not summary_path.exists():
        return {
            "status": "failed",
            "reason": f"missing_{rh_stage_name(previous_tag)}_archive",
            "stage": task["stage"],
            "system_id": system_id,
            "from_state": rel(from_state, base_dir),
            "summary": rel(summary_path, base_dir),
            "command": command,
            "elapsed_seconds": time.time() - started,
            "message": f"start_next_rh requires archived {rh_stage_name(previous_tag)} summary and restart",
        }
    if expected_restart is None or not expected_restart.exists():
        return {
            "status": "failed",
            "reason": "missing_expected_archived_restart",
            "stage": task["stage"],
            "system_id": system_id,
            "expected_restart": rel(expected_restart, base_dir) if expected_restart is not None else None,
            "command": command,
            "elapsed_seconds": time.time() - started,
            "message": f"Expected {rh_stage_name(previous_tag)} archived restart is missing",
        }
    try:
        old_cwd = Path.cwd()
        try:
            os.chdir(base_dir)
            status = start_next_rh.start_next_rh(
                case_path=case_file,
                from_state=from_state,
                rh=rh_value,
                run_dir=run_dir,
                dry_run=True,
                run=False,
                force=force,
                np=None,
                segment_steps_override=None,
                write_input=True,
            )
        finally:
            os.chdir(old_cwd)
        selected_restart = Path(str(status.get("selected_restart", ""))).resolve()
        if selected_restart != expected_restart.resolve():
            raise ValueError(
                f"Selected restart {selected_restart} does not match expected {expected_restart.resolve()}"
            )
        status_doc = {
            **status,
            "status": "completed",
            "stage": task["stage"],
            "system_id": system_id,
            "command": command,
            "return_code": 0,
            "elapsed_seconds": time.time() - started,
            "prepared_run_dir": rel(run_dir, base_dir),
            "source_restart": rel(selected_restart, base_dir),
            "expected_restart": rel(expected_restart, base_dir),
            "input_file": rel(Path(str(status["input_file"])), base_dir),
            "status_file": rel(status_path, base_dir),
            "preview_status_file": rel(preview_status_path, base_dir) if preview_status_path.exists() else None,
            "next_recommended_action": f"run_initial_{rh_stage_name(rh_tag)}",
            "message": f"prepared {rh_stage_name(rh_tag)} run directory/input from archived {rh_stage_name(previous_tag)} restart; did not run GCMC",
        }
        write_json(status_path, status_doc)
        return {**status_doc, "log_path": rel(status_path, base_dir)}
    except Exception as exc:
        status_doc = {
            "status": "failed",
            "reason": "start_next_rh_failed",
            "stage": task["stage"],
            "system_id": system_id,
            "command": command,
            "return_code": 1,
            "elapsed_seconds": time.time() - started,
            "fatal_errors": [str(exc)],
            "message": f"Failed to prepare {rh_stage_name(rh_tag)} start from archived {rh_stage_name(previous_tag)} restart",
        }
        write_json(status_path, status_doc)
        return {**status_doc, "log_path": rel(status_path, base_dir)}

def execute_task(
    *,
    campaign_cfg: dict[str, Any],
    plan: dict[str, Any],
    task: dict[str, Any],
    campaign_path: Path,
    base_dir: Path,
    force: bool,
) -> dict[str, Any]:
    stage = task["stage"]
    generic_stage = canonical_rh_stage(task)
    if stage not in SAFE_EXECUTION_STAGES and generic_stage not in SAFE_EXECUTION_STAGES:
        return {
            "status": "skipped",
            "reason": "unsafe_stage_refused",
            "message": UNSAFE_STAGE_MESSAGE,
            "task_id": task["task_id"],
            "stage": stage,
        }
    if stage == "plan_claycode_inputs":
        return execute_plan_claycode_inputs(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            campaign_path=campaign_path,
            base_dir=base_dir,
            force=force,
        )
    if stage == "run_claycode":
        return execute_run_claycode(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            base_dir=base_dir,
            force=force,
        )
    if stage == "create_case_file":
        return execute_create_case_file(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            base_dir=base_dir,
            force=force,
        )
    if stage == "prepare_case":
        return execute_prepare_case(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            base_dir=base_dir,
            force=force,
        )
    if stage == "run_equilibrate":
        return execute_run_equilibrate(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            base_dir=base_dir,
            force=force,
        )
    if generic_stage == "run_initial_rh":
        return execute_run_initial_rh(
            campaign_cfg=campaign_cfg,
            plan=plan,
            task=task,
            base_dir=base_dir,
            force=force,
        )
    if generic_stage == "analyze_rh":
        return execute_analyze_rh(campaign_cfg=campaign_cfg, task=task, base_dir=base_dir)
    if generic_stage == "continue_or_archive_rh":
        return execute_continue_or_archive_rh(campaign_cfg=campaign_cfg, task=task, base_dir=base_dir)
    if generic_stage == "start_next_rh":
        return execute_start_next_rh(campaign_cfg=campaign_cfg, task=task, base_dir=base_dir, force=force)
    return {"status": "skipped", "reason": "unknown_safe_stage", "task_id": task["task_id"], "stage": stage}



def next_actionable_task(plan: dict[str, Any], target_system: str | None = None) -> dict[str, Any] | None:
    if target_system is not None:
        return first_actionable_task(plan, target_system)
    next_actions = plan.get("next_actions") or []
    if next_actions:
        task = task_by_id(plan, str(next_actions[0].get("task_id")))
        if task is not None:
            return task
    return first_actionable_task(plan)


def completed_rh_tags_for_system(state: dict[str, Any], system_id: str) -> set[str]:
    completed = set(str(item) for item in state.get("completed_tasks", []))
    tags: set[str] = set()
    prefix = f"{system_id}:"
    for task_id in completed:
        if not task_id.startswith(prefix):
            continue
        match = re.search(r"rh[0-9]+p[0-9]+", task_id)
        if match:
            tags.add(match.group(0))
    return tags


def is_cross_system_or_rh_boundary(task: dict[str, Any], state: dict[str, Any]) -> bool:
    system_id = str(task.get("system_id", ""))
    history = state.get("execution_history", []) if isinstance(state.get("execution_history"), list) else []
    previous_systems = {
        str(item.get("system_id"))
        for item in history
        if isinstance(item, dict) and item.get("status") == "completed" and item.get("system_id")
    }
    if previous_systems and system_id not in previous_systems:
        return True
    stage = str(task.get("stage", ""))
    generic_stage = canonical_rh_stage(task)
    if generic_stage in {"run_initial_rh", "start_next_rh"}:
        return True
    rh_tag = rh_tag_for_task(task, "analyze_rh") or rh_tag_for_task(task, "continue_or_archive_rh")
    if rh_tag is not None:
        completed_rh = completed_rh_tags_for_system(state, system_id)
        if completed_rh and rh_tag not in completed_rh:
            return True
    return False


def auto_policy_for_task(
    *,
    task: dict[str, Any],
    state: dict[str, Any],
    base_dir: Path,
    stop_before_stage: re.Pattern[str] | None,
) -> tuple[bool, dict[str, Any]]:
    stage = str(task.get("stage", ""))
    task_id = str(task.get("task_id", ""))
    if stop_before_stage and (stop_before_stage.search(stage) or stop_before_stage.search(task_id)):
        return False, {
            "status": "blocked",
            "reason": "stop_before_stage_matched",
            "task_id": task_id,
            "stage": stage,
            "message": "Auto mode stopped before a stage matching --stop-before-stage.",
        }
    generic_stage = canonical_rh_stage(task)
    if stage not in SAFE_EXECUTION_STAGES and generic_stage not in SAFE_EXECUTION_STAGES:
        return False, {
            "status": "blocked",
            "reason": "unsafe_stage_refused",
            "task_id": task_id,
            "stage": stage,
            "message": UNSAFE_STAGE_MESSAGE,
        }
    if is_cross_system_or_rh_boundary(task, state):
        return False, {
            "status": "blocked",
            "reason": "handoff_boundary",
            "task_id": task_id,
            "stage": stage,
            "message": "Auto mode stopped before crossing a system/RH handoff boundary.",
        }
    if generic_stage == "analyze_rh":
        return True, {"status": "allowed", "reason": "read_only_analysis"}
    rh_tag = rh_tag_for_task(task, "continue_or_archive_rh") if generic_stage == "continue_or_archive_rh" else None
    if rh_tag is not None:
        paths = continue_or_archive_paths(str(task["system_id"]), rh_tag, base_dir)
        analysis, error = read_analysis_json(paths["analysis"])
        if error:
            return False, {
                "status": "blocked",
                "reason": error,
                "task_id": task_id,
                "stage": stage,
                "input_analysis_file": rel(paths["analysis"], base_dir),
                "message": "Auto mode requires a valid latest RH analysis before continue/archive.",
            }
        recommendation = analysis.get("recommendation")
        analysis_status = analysis.get("status")
        if analysis_status == "failed" or recommendation in {"inspect", None} or recommendation not in {"continue", "archive"}:
            return False, {
                "status": "blocked",
                "reason": "analysis_requires_inspection",
                "task_id": task_id,
                "stage": stage,
                "analysis_status": analysis_status,
                "analysis_recommendation": recommendation,
                "message": "Auto mode stopped because RH analysis is failed, inspect, or ambiguous.",
            }
        if recommendation == "archive" and not analysis_supports_archive(analysis):
            return False, {
                "status": "blocked",
                "reason": "analysis_archive_mismatch",
                "task_id": task_id,
                "stage": stage,
                "analysis_status": analysis_status,
                "analysis_recommendation": recommendation,
                "message": "Auto mode requires strict analyzer agreement before archive.",
            }
        return True, {
            "status": "allowed",
            "reason": f"analysis_recommends_{recommendation}",
            "analysis_status": analysis_status,
            "analysis_recommendation": recommendation,
        }
    return False, {
        "status": "blocked",
        "reason": "auto_stage_not_allowlisted",
        "task_id": task_id,
        "stage": stage,
        "message": "Auto mode only runs read-only RH analysis and verified continue/archive actions by default.",
    }


def auto_result_requires_stop(result: dict[str, Any]) -> tuple[bool, str | None]:
    status = result.get("status")
    if status != "completed":
        return True, str(result.get("reason") or status or "action_not_completed")
    if result.get("decision") == "blocked":
        return True, str(result.get("reason") or "blocked")
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else None
    if analysis is not None:
        recommendation = analysis.get("recommendation")
        analysis_status = analysis.get("status")
        if analysis_status == "failed" or recommendation in {"inspect", None} or recommendation not in {"continue", "archive"}:
            return True, "analysis_requires_inspection"
    return False, None


def parse_system_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    systems = [item.strip() for item in value.split(",") if item.strip()]
    return systems or None


def validate_target_systems(plan: dict[str, Any], systems: list[str] | None) -> None:
    if systems is None:
        return
    known = campaign_plan_system_ids(plan)
    unknown = [system for system in systems if system not in known]
    if unknown:
        raise ValueError(f"Unknown campaign system(s) {', '.join(unknown)}; known systems: {', '.join(sorted(known))}")


def rh_tag_for_smoke_task(task: dict[str, Any]) -> str | None:
    generic = canonical_rh_stage(task)
    if generic == "run_initial_rh":
        return rh_tag_for_task(task, "run_initial_rh")
    if generic == "analyze_rh":
        return rh_tag_for_task(task, "analyze_rh")
    if generic == "continue_or_archive_rh":
        return rh_tag_for_task(task, "continue_or_archive_rh")
    if generic == "start_next_rh":
        return rh_tag_for_task(task, "start_next_rh")
    return None


def smoke_policy_for_task(task: dict[str, Any], stop_after_stage: re.Pattern[str] | None = None) -> tuple[bool, dict[str, Any]]:
    stage = str(task.get("stage", ""))
    task_id = str(task.get("task_id", ""))
    generic = canonical_rh_stage(task)
    if generic in {"continue_or_archive_rh", "start_next_rh"}:
        return False, {"status": "blocked", "reason": "smoke_stage_blocked", "task_id": task_id, "stage": stage, "message": "Smoke mode stops before continuation/archive or RH handoff stages."}
    if generic not in SMOKE_ALLOWED_GENERIC_STAGES:
        return False, {"status": "blocked", "reason": "smoke_stage_not_allowlisted", "task_id": task_id, "stage": stage, "message": "Smoke mode only runs planning, setup, equilibration, RH=0.9 initial, and RH=0.9 analysis."}
    rh_tag = rh_tag_for_smoke_task(task)
    if rh_tag is not None and rh_tag != "rh0p90":
        return False, {"status": "blocked", "reason": "smoke_cross_rh_blocked", "task_id": task_id, "stage": stage, "message": "Smoke mode does not cross beyond RH=0.9."}
    if stop_after_stage and (stop_after_stage.search(stage) or stop_after_stage.search(task_id)):
        return True, {"status": "allowed_stop_after", "reason": "stop_after_stage_matched"}
    return True, {"status": "allowed", "reason": "smoke_stage_allowlisted"}


def system_cation(campaign_cfg: dict[str, Any], system_id: str) -> str | None:
    try:
        return str(campaign_system_config(campaign_cfg, system_id).get("cation"))
    except Exception:
        return None


def smoke_summary_for_system(system_id: str, cation: str | None, actions: list[dict[str, Any]], base_dir: Path) -> dict[str, Any]:
    system_actions = [action for action in actions if action.get("system_id") == system_id or str(action.get("task_id", "")).startswith(f"{system_id}:")]
    last = system_actions[-1] if system_actions else {}
    analysis_path = base_dir / "examples" / system_id / "generated" / f"{system_id}.rh_0p90_analysis.json"
    analysis = load_json(analysis_path) if analysis_path.exists() else {}
    diagnostics = analysis.get("diagnostics", {}) if isinstance(analysis.get("diagnostics"), dict) else {}
    water = diagnostics.get("water_summary", {}) if isinstance(diagnostics.get("water_summary"), dict) else {}
    ion = diagnostics.get("ion_summary", {}) if isinstance(diagnostics.get("ion_summary"), dict) else {}
    equil_diag_path = base_dir / "examples" / system_id / "generated" / f"{system_id}.run_equilibrate_diagnostics.json"
    equil_diag = load_json(equil_diag_path) if equil_diag_path.exists() else {}
    fatal_errors: list[str] = []
    known_warnings: list[str] = []
    for source in [last, analysis, diagnostics, equil_diag]:
        if isinstance(source.get("fatal_errors"), list):
            fatal_errors.extend(str(item) for item in source.get("fatal_errors", []))
        if isinstance(source.get("errors"), list):
            fatal_errors.extend(str(item) for item in source.get("errors", []))
        if isinstance(source.get("known_warnings"), list):
            known_warnings.extend(str(item) for item in source.get("known_warnings", []))
    return {
        "system_id": system_id,
        "cation": cation,
        "stage_reached": last.get("stage"),
        "final_status": last.get("status") or "not_started",
        "cation_count_stability": analysis.get("ion_count_stable"),
        "ion_count_initial": analysis.get("ion_count_initial") or ion.get("observed_initial"),
        "ion_count_final": analysis.get("ion_count_final") or ion.get("observed_final"),
        "basal_handoff_status": equil_diag.get("handoff_status") or diagnostics.get("handoff_status"),
        "analysis_status": analysis.get("status"),
        "analysis_recommendation": analysis.get("recommendation"),
        "final_timestep": analysis.get("final_timestep") or water.get("final_step"),
        "total_water": analysis.get("total_water_final") or water.get("final_total_water"),
        "interlayer_water": analysis.get("interlayer_water_final") or water.get("final_interlayer_water"),
        "external_water": analysis.get("external_water_final") or water.get("final_external_water"),
        "basal_proxy": analysis.get("basal_proxy_final") or water.get("basal_proxy_final") or water.get("final_basal_proxy"),
        "fatal_errors": sorted(set(fatal_errors)),
        "known_warnings": sorted(set(known_warnings)),
        "actions_executed": [action.get("task_id") for action in system_actions if action.get("task_id")],
    }


def write_smoke_summary(*, campaign_cfg: dict[str, Any], systems: list[str], actions: list[dict[str, Any]], base_dir: Path) -> dict[str, Any]:
    generated = base_dir / "generated"
    rows = [smoke_summary_for_system(system_id, system_cation(campaign_cfg, system_id), actions, base_dir) for system_id in systems]
    summary = {"systems": rows, "actions": actions, "written_at": plan_campaign.now_iso()}
    write_json(generated / SMOKE_SUMMARY_JSON, summary)
    lines = ["# Campaign Smoke Summary", "", "| system_id | cation | stage_reached | final_status | ion_count_final | basal_handoff_status | analysis_status | recommendation | fatal_errors | known_warnings |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key) or "") for key in ["system_id", "cation", "stage_reached", "final_status", "ion_count_final", "basal_handoff_status", "analysis_status", "analysis_recommendation"]) + f" | {'; '.join(row['fatal_errors'])} | {'; '.join(row['known_warnings'])} |")
    (generated / SMOKE_SUMMARY_MD).write_text("\n".join(lines) + "\n")
    return summary



def smoke_terminal_analysis_exists(system_id: str, base_dir: Path) -> bool:
    return (base_dir / "examples" / system_id / "generated" / f"{system_id}.rh_0p90_analysis.json").exists()


PAPER_SUPPORTED_CATIONS = {"Na", "K", "Ca", "Ba"}


def paper_system_complete(system_id: str, campaign_cfg: dict[str, Any], base_dir: Path) -> bool:
    for rh in [float(value) for value in campaign_cfg.get("rh_path", [])]:
        tag = plan_campaign.rh_tag(rh)
        summary = base_dir / "examples" / system_id / "states" / rh_stage_name(tag) / "summary.json"
        if not plan_campaign.archived_summary_supports_handoff(summary):
            return False
    return True


def paper_all_systems_complete(campaign_cfg: dict[str, Any], base_dir: Path) -> bool:
    return all(paper_system_complete(str(system["system_id"]), campaign_cfg, base_dir) for system in campaign_cfg.get("systems", []))


def first_paper_actionable_task(plan: dict[str, Any], blocked_systems: set[str]) -> dict[str, Any] | None:
    for task in plan.get("planned_tasks", []):
        system_id = str(task.get("system_id", ""))
        if system_id in blocked_systems:
            continue
        if task.get("status") in {plan_campaign.STATUS_READY, plan_campaign.STATUS_MISSING}:
            return task
    return None


def paper_continuation_count(state: dict[str, Any], task_id: str) -> int:
    count = 0
    for item in state.get("execution_history", []):
        if not isinstance(item, dict):
            continue
        if item.get("task_id") == task_id and item.get("status") == "completed" and item.get("decision") == "continue":
            count += 1
    return count


def paper_policy_for_task(
    *,
    campaign_cfg: dict[str, Any],
    task: dict[str, Any],
    state: dict[str, Any],
    base_dir: Path,
) -> tuple[bool, dict[str, Any]]:
    system_id = str(task.get("system_id", ""))
    stage = str(task.get("stage", ""))
    task_id = str(task.get("task_id", ""))
    generic_stage = canonical_rh_stage(task)
    system = campaign_system_config(campaign_cfg, system_id)
    cation = str(system.get("cation", ""))
    if cation not in PAPER_SUPPORTED_CATIONS:
        return False, {"status": "blocked", "reason": "unsupported_cation", "system_id": system_id, "task_id": task_id, "stage": stage, "message": f"Unsupported paper campaign cation: {cation}"}
    if task.get("status") == plan_campaign.STATUS_MISSING:
        return False, {"status": "blocked", "reason": "missing_inputs_or_outputs", "system_id": system_id, "task_id": task_id, "stage": stage, "message": "Paper batch cannot execute a task with missing required inputs."}
    if stage not in SAFE_EXECUTION_STAGES and generic_stage not in SAFE_EXECUTION_STAGES:
        return False, {"status": "blocked", "reason": "unsafe_stage_refused", "system_id": system_id, "task_id": task_id, "stage": stage, "message": UNSAFE_STAGE_MESSAGE}
    if generic_stage == "start_next_rh":
        previous = previous_rh_tag_for_task(task, campaign_cfg)
        if previous:
            previous_summary = base_dir / "examples" / system_id / "states" / rh_stage_name(previous) / "summary.json"
            if not plan_campaign.archived_summary_supports_handoff(previous_summary):
                return False, {"status": "blocked", "reason": "missing_previous_rh_archive", "system_id": system_id, "task_id": task_id, "stage": stage, "message": f"Paper batch will not start {task.get('rh_tag')} until {previous} is archived."}
    if generic_stage == "run_initial_rh":
        previous = previous_rh_tag_for_task(task, campaign_cfg)
        if previous:
            previous_summary = base_dir / "examples" / system_id / "states" / rh_stage_name(previous) / "summary.json"
            if not plan_campaign.archived_summary_supports_handoff(previous_summary):
                return False, {"status": "blocked", "reason": "missing_previous_rh_archive", "system_id": system_id, "task_id": task_id, "stage": stage, "message": f"Paper batch will not run initial {task.get('rh_tag')} until {previous} is archived."}
    if generic_stage == "analyze_rh":
        return True, {"status": "allowed", "reason": "paper_read_only_analysis"}
    rh_tag = rh_tag_for_task(task, "continue_or_archive_rh") if generic_stage == "continue_or_archive_rh" else None
    if rh_tag is not None:
        paths = continue_or_archive_paths(system_id, rh_tag, base_dir)
        analysis, error = read_analysis_json(paths["analysis"])
        if error:
            return False, {"status": "blocked", "reason": error, "system_id": system_id, "task_id": task_id, "stage": stage, "input_analysis_file": rel(paths["analysis"], base_dir), "message": "Paper batch requires a valid latest RH analysis before continue/archive."}
        assert analysis is not None
        if analysis.get("ion_count_stable") is False:
            return False, {"status": "blocked", "reason": "ion_count_changed", "system_id": system_id, "task_id": task_id, "stage": stage, "message": "Ion count changed; stopping system."}
        if analysis.get("fatal_errors"):
            return False, {"status": "blocked", "reason": "fatal_errors", "system_id": system_id, "task_id": task_id, "stage": stage, "fatal_errors": analysis.get("fatal_errors"), "message": "Fatal analysis diagnostics detected; stopping system."}
        recommendation = analysis.get("recommendation")
        analysis_status = analysis.get("status")
        if analysis_status == "failed" or recommendation in {"inspect", None} or recommendation not in {"continue", "archive"}:
            return False, {"status": "blocked", "reason": "analysis_requires_inspection", "system_id": system_id, "task_id": task_id, "stage": stage, "analysis_status": analysis_status, "analysis_recommendation": recommendation, "message": "Paper batch stopped because RH analysis is failed, inspect, or ambiguous."}
        if recommendation == "archive" and not analysis_supports_archive(analysis):
            return False, {"status": "blocked", "reason": "analysis_archive_mismatch", "system_id": system_id, "task_id": task_id, "stage": stage, "message": "Archive requires strict analyzer agreement."}
        if recommendation == "continue":
            policy = campaign_cfg.get("simulation_policy", {}) if isinstance(campaign_cfg.get("simulation_policy"), dict) else {}
            max_segments = int(policy.get("max_segments_per_rh", 8))
            max_total_steps = int(policy.get("max_total_steps_per_rh", policy.get("max_steps_per_rh", 12000000)))
            segments = paper_continuation_count(state, task_id)
            final_step = int(analysis.get("final_timestep") or 0)
            rh_start_step = rh_start_step_for_task(task, campaign_cfg, base_dir)
            elapsed_steps_current_rh = max(0, final_step - rh_start_step)
            if segments >= max_segments:
                return False, {"status": "blocked", "reason": "max_segments_per_rh_reached", "system_id": system_id, "task_id": task_id, "stage": stage, "segments": segments, "message": "RH point did not archive within max_segments_per_rh."}
            if elapsed_steps_current_rh >= max_total_steps:
                return False, {"status": "blocked", "reason": "max_total_steps_per_rh_reached", "system_id": system_id, "task_id": task_id, "stage": stage, "final_timestep": final_step, "rh_start_step": rh_start_step, "elapsed_steps_current_rh": elapsed_steps_current_rh, "message": "RH point did not archive within max_total_steps_per_rh."}
        return True, {"status": "allowed", "reason": f"analysis_recommends_{recommendation}", "analysis_status": analysis_status, "analysis_recommendation": recommendation}
    return True, {"status": "allowed", "reason": "paper_stage_allowlisted"}


def run_auto_paper_batch(
    *,
    campaign_cfg: dict[str, Any],
    campaign_path: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    base_dir: Path,
    max_actions: int,
    max_walltime_seconds: float | None,
    force: bool,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    stop_reason: str | None = None
    blocked_systems: set[str] = set()
    active_failures: set[str] = set()
    started = time.monotonic()
    for _ in range(max_actions):
        if paper_all_systems_complete(campaign_cfg, base_dir):
            stop_reason = "paper_batch_complete"
            break
        if max_walltime_seconds is not None and time.monotonic() - started >= max_walltime_seconds:
            stop_reason = "max_walltime_seconds_reached"
            actions.append({"status": "blocked", "reason": stop_reason, "message": "Paper batch stopped at --max-walltime-seconds."})
            break
        task = first_paper_actionable_task(plan, blocked_systems)
        if task is None:
            stop_reason = "no_actionable_task"
            break
        allowed, policy = paper_policy_for_task(campaign_cfg=campaign_cfg, task=task, state=state, base_dir=base_dir)
        if not allowed:
            policy["timestamp"] = plan_campaign.now_iso()
            state["execution_history"].append(policy)
            unique_append(state["failed_tasks"], task["task_id"])
            active_failures.add(str(task["task_id"]))
            blocked_systems.add(str(task.get("system_id", "")))
            actions.append(policy)
            plan = write_plan(campaign_path, base_dir)
            reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures)
            update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir)
            continue
        result = execute_task(campaign_cfg=campaign_cfg, plan=plan, task=task, campaign_path=campaign_path, base_dir=base_dir, force=force)
        history_entry = {"timestamp": plan_campaign.now_iso(), "task_id": task["task_id"], "stage": task["stage"], "task_status_before": task["status"], **result}
        state["execution_history"].append(history_entry)
        if result.get("status") == "completed":
            unique_append(state["completed_tasks"], task["task_id"])
            remove_value(state["failed_tasks"], task["task_id"])
        elif result.get("status") == "skipped":
            unique_append(state["skipped_tasks"], task["task_id"])
        else:
            unique_append(state["failed_tasks"], task["task_id"])
            active_failures.add(str(task["task_id"]))
            blocked_systems.add(str(task.get("system_id", "")))
        actions.append(history_entry)
        plan = write_plan(campaign_path, base_dir)
        reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures)
        update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir)
        if result.get("status") != "completed":
            continue
    else:
        stop_reason = "max_actions_reached"
    if stop_reason is None:
        stop_reason = "paper_batch_complete" if paper_all_systems_complete(campaign_cfg, base_dir) else "paper_batch_blocked"
    reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures)
    update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir)
    summary = paper_batch.generate_paper_outputs(base_dir=base_dir, campaign_path=campaign_path)
    summary["actions"] = actions
    summary["stop_reason"] = stop_reason
    return actions, stop_reason, summary

def run_auto_smoke(
    *,
    campaign_cfg: dict[str, Any],
    campaign_path: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    base_dir: Path,
    systems: list[str],
    max_actions: int,
    max_walltime_seconds: float | None,
    stop_after_stage: str | None,
    force: bool,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    stop_reason: str | None = None
    active_failures: set[str] = set()
    completed_systems: set[str] = set()
    stop_after_re = re.compile(stop_after_stage) if stop_after_stage else None
    started = time.monotonic()
    while len(actions) < max_actions and len(completed_systems) < len(systems):
        progressed = False
        for system_id in systems:
            if len(actions) >= max_actions:
                stop_reason = "max_actions_reached"
                break
            if system_id in completed_systems:
                continue
            if max_walltime_seconds is not None and time.monotonic() - started >= max_walltime_seconds:
                stop_reason = "max_walltime_seconds_reached"
                break
            if smoke_terminal_analysis_exists(system_id, base_dir):
                completed_systems.add(system_id)
                actions.append({"status": "completed", "reason": "smoke_terminal_analysis_exists", "system_id": system_id, "stage": "analyze_rh_0p90", "message": f"{system_id} already has RH=0.9 analysis; smoke stage is complete."})
                progressed = True
                continue
            task = first_actionable_task(plan, system_id)
            if task is None:
                completed_systems.add(system_id)
                actions.append({"status": "skipped", "reason": "no_actionable_task_for_system", "system_id": system_id, "message": f"No ready or missing task found for system {system_id}."})
                progressed = True
                continue
            allowed, policy = smoke_policy_for_task(task, stop_after_re)
            if not allowed:
                policy["system_id"] = system_id
                actions.append(policy)
                stop_reason = str(policy.get("reason", "smoke_blocked"))
                summary = write_smoke_summary(campaign_cfg=campaign_cfg, systems=systems, actions=actions, base_dir=base_dir)
                return actions, stop_reason, summary
            result = execute_task(campaign_cfg=campaign_cfg, plan=plan, task=task, campaign_path=campaign_path, base_dir=base_dir, force=force)
            history_entry = {"timestamp": plan_campaign.now_iso(), "task_id": task["task_id"], "stage": task["stage"], "task_status_before": task["status"], **result}
            state["execution_history"].append(history_entry)
            if result.get("status") == "completed":
                unique_append(state["completed_tasks"], task["task_id"])
                remove_value(state["failed_tasks"], task["task_id"])
            elif result.get("status") == "skipped":
                unique_append(state["skipped_tasks"], task["task_id"])
            else:
                unique_append(state["failed_tasks"], task["task_id"])
                active_failures.add(task["task_id"])
            actions.append(history_entry)
            progressed = True
            plan = write_plan(campaign_path, base_dir)
            reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures)
            update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir, target_system=system_id)
            if result.get("status") != "completed":
                stop_reason = str(result.get("reason") or result.get("status") or "smoke_action_failed")
                summary = write_smoke_summary(campaign_cfg=campaign_cfg, systems=systems, actions=actions, base_dir=base_dir)
                return actions, stop_reason, summary
            if canonical_rh_stage(task) == "analyze_rh" and rh_tag_for_task(task, "analyze_rh") == "rh0p90":
                completed_systems.add(system_id)
            if policy.get("status") == "allowed_stop_after":
                completed_systems.add(system_id)
        if stop_reason in {"max_actions_reached", "max_walltime_seconds_reached"}:
            break
        if not progressed:
            stop_reason = "no_progress"
            break
    if stop_reason is None:
        stop_reason = "smoke_complete" if len(completed_systems) == len(systems) else "max_actions_reached"
    reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures)
    update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir)
    summary = write_smoke_summary(campaign_cfg=campaign_cfg, systems=systems, actions=actions, base_dir=base_dir)
    return actions, stop_reason, summary

def run_campaign(
    *,
    campaign_path: Path,
    dry_run: bool,
    execute_next: bool,
    max_actions: int,
    force: bool,
    base_dir: Path | None = None,
    auto_until_blocked: bool = False,
    auto_smoke: bool = False,
    auto_paper_batch: bool = False,
    smoke_systems: list[str] | None = None,
    max_walltime_seconds: float | None = None,
    stop_before_stage: str | None = None,
    stop_after_stage: str | None = None,
    target_system: str | None = None,
    enable_codex_escalation: bool = False,
    invoke_codex: bool = False,
) -> dict[str, Any]:
    if max_actions <= 0:
        raise ValueError("--max-actions must be positive")
    modes = sum(1 for enabled in (dry_run, execute_next, auto_until_blocked, auto_smoke, auto_paper_batch) if enabled)
    if modes > 1:
        raise ValueError("Use only one of --dry-run, --execute-next, --auto-until-blocked, --auto-smoke, or --auto-paper-batch")
    if not dry_run and not execute_next and not auto_until_blocked and not auto_smoke and not auto_paper_batch:
        dry_run = True

    base_dir = (base_dir or Path.cwd()).resolve()
    escalation_config = agent_escalation.config_from_env(base_dir)
    escalation_config.enabled = enable_codex_escalation or escalation_config.enabled
    escalation_config.codex_enabled = invoke_codex or escalation_config.codex_enabled
    campaign_path = campaign_path.resolve()
    campaign_cfg = plan_campaign.load_yaml(campaign_path)
    plan = write_plan(campaign_path, base_dir)
    validate_target_system(plan, target_system)
    validate_target_systems(plan, smoke_systems)
    state_path = state_path_for(campaign_path)
    state = load_or_init_state(campaign_path, plan, state_path, base_dir)

    actions: list[dict[str, Any]] = []
    active_failures_this_run: set[str] = set()
    stop_reason: str | None = None
    stop_before_re = re.compile(stop_before_stage) if stop_before_stage else None
    started = time.monotonic()
    smoke_summary = None
    if auto_paper_batch:
        actions, stop_reason, smoke_summary = run_auto_paper_batch(
            campaign_cfg=campaign_cfg,
            campaign_path=campaign_path,
            plan=plan,
            state=state,
            state_path=state_path,
            base_dir=base_dir,
            max_actions=max_actions,
            max_walltime_seconds=max_walltime_seconds,
            force=force,
        )
    elif auto_smoke:
        selected_systems = smoke_systems or [str(system["system_id"]) for system in plan.get("systems", [])]
        actions, stop_reason, smoke_summary = run_auto_smoke(
            campaign_cfg=campaign_cfg,
            campaign_path=campaign_path,
            plan=plan,
            state=state,
            state_path=state_path,
            base_dir=base_dir,
            systems=selected_systems,
            max_actions=max_actions,
            max_walltime_seconds=max_walltime_seconds,
            stop_after_stage=stop_after_stage,
            force=force,
        )
    elif dry_run:
        task = first_actionable_task(plan, target_system)
        if task is None:
            actions.append({
                "status": "skipped",
                "reason": "no_actionable_task_for_system" if target_system else "no_actionable_task",
                "system_id": target_system,
                "message": f"No ready or missing task found for system {target_system}." if target_system else "No ready or missing task found.",
            })
        else:
            actions.append({
                "status": "dry_run",
                "task_id": task["task_id"],
                "stage": task["stage"],
                "command_preview": task["command_preview"],
                "message": "No action executed. Use --execute-next to run one allowed safe action.",
            })
    else:
        for _ in range(max_actions):
            if max_walltime_seconds is not None and time.monotonic() - started >= max_walltime_seconds:
                stop_reason = "max_walltime_seconds_reached"
                actions.append({"status": "blocked", "reason": stop_reason, "message": "Auto execution stopped at --max-walltime-seconds."})
                break
            task = next_actionable_task(plan, target_system) if auto_until_blocked else first_actionable_task(plan, target_system)
            if task is None:
                stop_reason = "no_actionable_task_for_system" if target_system else "no_actionable_task"
                actions.append({
                    "status": "skipped",
                    "reason": stop_reason,
                    "system_id": target_system,
                    "message": f"No ready or missing task found for system {target_system}." if target_system else "No ready or missing task found.",
                })
                break
            if auto_until_blocked:
                allowed, policy = auto_policy_for_task(
                    task=task,
                    state=state,
                    base_dir=base_dir,
                    stop_before_stage=stop_before_re,
                )
                if not allowed:
                    stop_reason = str(policy.get("reason", "blocked"))
                    actions.append(policy)
                    break
            result = execute_task(
                campaign_cfg=campaign_cfg,
                plan=plan,
                task=task,
                campaign_path=campaign_path,
                base_dir=base_dir,
                force=force,
            )
            history_entry = {
                "timestamp": plan_campaign.now_iso(),
                "task_id": task["task_id"],
                "stage": task["stage"],
                "task_status_before": task["status"],
                **result,
            }
            state["execution_history"].append(history_entry)
            if result["status"] == "completed":
                unique_append(state["completed_tasks"], task["task_id"])
                remove_value(state["failed_tasks"], task["task_id"])
            elif result["status"] == "skipped":
                unique_append(state["skipped_tasks"], task["task_id"])
            else:
                unique_append(state["failed_tasks"], task["task_id"])
                active_failures_this_run.add(task["task_id"])
            actions.append(history_entry)
            plan = write_plan(campaign_path, base_dir)
            reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures_this_run)
            update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir, target_system=target_system)
            if auto_until_blocked:
                should_stop, reason = auto_result_requires_stop(result)
                if should_stop:
                    stop_reason = reason
                    break
            elif result["status"] != "completed":
                break
        else:
            stop_reason = "max_actions_reached"

    reconcile_failed_tasks(state, plan, preserve_task_ids=active_failures_this_run)
    update_state(state=state, plan=plan, campaign_path=campaign_path, state_path=state_path, base_dir=base_dir, target_system=target_system)

    escalation_records: list[dict[str, Any]] = []
    if escalation_config.enabled:
        terminal_action: dict[str, Any] | None = actions[-1] if actions else None
        if terminal_action is not None:
            record = maybe_emit_escalation(
                config=escalation_config,
                campaign_id=plan["campaign_id"],
                campaign_path=campaign_path,
                state_path=state_path,
                base_dir=base_dir,
                action=terminal_action,
                stop_reason=stop_reason,
            )
            if record is not None:
                escalation_records.append(record)

    return {
        "status": "auto_paper_batch_stopped" if auto_paper_batch else "auto_smoke_stopped" if auto_smoke else "dry_run" if dry_run else "auto_stopped" if auto_until_blocked else "executed",
        "stop_reason": stop_reason,
        "campaign_id": plan["campaign_id"],
        "state_file": rel(state_path, base_dir),
        "plan_file": rel(plan_paths_for(campaign_path)[0], base_dir),
        "markdown_plan_file": rel(plan_paths_for(campaign_path)[1], base_dir),
        "actions": actions,
        "target_system": target_system,
        "next_recommended_action": state.get("next_recommended_action"),
        "smoke_summary": smoke_summary,
        "codex_escalation_enabled": escalation_config.enabled,
        "codex_invocation_enabled": escalation_config.codex_enabled,
        "agent_escalations": escalation_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a restartable MD-GCMC campaign state machine v2.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Refresh plan/state and print the next action without executing it.")
    parser.add_argument("--execute-next", action="store_true", help="Execute allowed safe next actions only.")
    parser.add_argument("--auto-until-blocked", action="store_true", help="Conservatively execute safe RH analysis/continue/archive actions until blocked.")
    parser.add_argument("--auto-smoke", action="store_true", help="Run a controlled smoke pipeline for selected systems through RH=0.9 analysis.")
    parser.add_argument("--auto-paper-batch", action="store_true", help="Run the full paper production RH-water uptake batch until complete or blocked.")
    parser.add_argument("--systems", default=None, help="Comma-separated system IDs for --auto-smoke.")
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--max-walltime-seconds", type=float, default=None)
    parser.add_argument("--stop-before-stage", default=None, help="Regex; auto mode stops before matching stage or task id.")
    parser.add_argument("--stop-after-stage", default=None, help="Regex; smoke mode stops after executing a matching stage or task id.")
    parser.add_argument("--system", default=None, help="Limit next-action selection/execution to one campaign system_id.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting safe planning/raw outputs.")
    parser.add_argument("--enable-codex-escalation", action="store_true", help="Emit agent events at discrete campaign boundaries.")
    parser.add_argument("--invoke-codex", action="store_true", help="Run `codex exec` for emitted events. Implies --enable-codex-escalation.")
    args = parser.parse_args()

    try:
        summary = run_campaign(
            campaign_path=args.campaign,
            dry_run=args.dry_run,
            execute_next=args.execute_next,
            max_actions=args.max_actions,
            force=args.force,
            auto_until_blocked=args.auto_until_blocked,
            auto_smoke=args.auto_smoke,
            auto_paper_batch=args.auto_paper_batch,
            smoke_systems=parse_system_list(args.systems),
            max_walltime_seconds=args.max_walltime_seconds,
            stop_before_stage=args.stop_before_stage,
            stop_after_stage=args.stop_after_stage,
            target_system=args.system,
            enable_codex_escalation=args.enable_codex_escalation or args.invoke_codex,
            invoke_codex=args.invoke_codex,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

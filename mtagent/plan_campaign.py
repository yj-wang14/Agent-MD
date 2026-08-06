#!/usr/bin/env python3
"""Create a dry-run execution plan for an MD-GCMC campaign."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtagent import plan_claycode_inputs


STATUS_MISSING = "missing"
STATUS_READY = "ready"
STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read campaign YAML files") from exc
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Campaign YAML must contain a mapping: {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def rel(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)


def rh_tag(rh: float) -> str:
    return f"rh{rh:.2f}".replace(".", "p")


def rh_dir_name(rh: float) -> str:
    return rh_tag(rh).replace("rh", "rh_")


def layer_charge_label(x: float) -> str:
    return plan_claycode_inputs.layer_charge_tag(x)


def expected_partition(total_cation_count: int) -> dict[str, int]:
    partition = plan_claycode_inputs.ion_partition_counts(total_cation_count=total_cation_count)
    return {
        "bottom_external": int(partition["target_bottom_ions"]),
        "interlayer": int(partition["target_interlayer_ions"]),
        "top_external": int(partition["target_top_ions"]),
    }


def validate_campaign(campaign_cfg: dict[str, Any]) -> None:
    geometry = campaign_cfg.get("geometry", {})
    if not isinstance(geometry, dict):
        geometry = {}
    total_unit_cells = (
        int(geometry.get("x_cells", 5))
        * int(geometry.get("y_cells", 4))
        * int(geometry.get("n_sheets", 2))
    )

    systems = campaign_cfg.get("systems", [])
    if not isinstance(systems, list) or not systems:
        raise ValueError("campaign YAML must contain at least one system")

    for system in systems:
        if not isinstance(system, dict):
            raise ValueError("each campaign system must be a mapping")
        system_id = str(system.get("system_id", "")).strip()
        if not system_id:
            raise ValueError("each campaign system requires system_id")
        cation = str(system.get("cation", "")).strip()
        valence = int(system.get("valence", plan_claycode_inputs.cation_valence(cation)))
        x = float(system.get("substitution_amount_x"))
        total = plan_claycode_inputs.total_cation_count(
            layer_charge_magnitude=x,
            valence=valence,
            total_unit_cells=total_unit_cells,
        )
        expected_total = int(system.get("expected_total_cation_count", total))
        if total != expected_total:
            raise ValueError(
                f"{system_id}: expected_total_cation_count={expected_total} does not match "
                f"x/valence*unit_cells={total}"
            )
        partition = expected_partition(total)
        expected = system.get("expected_partition", {})
        if not isinstance(expected, dict):
            raise ValueError(f"{system_id}: expected_partition must be a mapping")
        for key, value in partition.items():
            if int(expected.get(key, value)) != value:
                raise ValueError(
                    f"{system_id}: expected_partition.{key}={expected.get(key)} does not match {value}"
                )


def file_exists(paths: list[Path]) -> bool:
    return all(path.exists() for path in paths)


def any_exists(paths: list[Path]) -> bool:
    return any(path.exists() for path in paths)


def task_status(input_files: list[Path], expected: list[Path], dependencies: list[str], status_by_id: dict[str, str]) -> str:
    if expected and file_exists(expected):
        return STATUS_COMPLETED
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    if input_files and not all(path.exists() for path in input_files):
        return STATUS_MISSING
    return STATUS_READY



def build_task(
    *,
    task_id: str,
    system_id: str,
    stage: str,
    command_preview: str,
    input_files: list[Path],
    expected_output_files: list[Path],
    dependencies: list[str],
    status_by_id: dict[str, str],
    base_dir: Path,
) -> dict[str, Any]:
    status = task_status(input_files, expected_output_files, dependencies, status_by_id)
    status_by_id[task_id] = status
    return {
        "task_id": task_id,
        "system_id": system_id,
        "stage": stage,
        "command_preview": command_preview,
        "input_files": [rel(path, base_dir) for path in input_files],
        "expected_output_files": [rel(path, base_dir) for path in expected_output_files],
        "dependencies": dependencies,
        "status": status,
    }


def equilibration_task_status(paths: dict[str, Path], dependencies: list[str], status_by_id: dict[str, str]) -> str:
    expected = [paths["equilibrated_data"], paths["pre_gcmc_restart"]]
    status_file = paths["example_dir"] / "equilibration" / "equilibration_status.json"
    if file_exists(expected):
        if status_file.exists():
            try:
                status_doc = json.loads(status_file.read_text())
            except json.JSONDecodeError:
                return STATUS_READY
            if status_doc.get("status") == "completed":
                diagnostics_file = paths.get("equilibration_diagnostics")
                if diagnostics_file and diagnostics_file.exists():
                    try:
                        diagnostics = json.loads(diagnostics_file.read_text())
                    except json.JSONDecodeError:
                        return STATUS_READY
                    if diagnostics.get("handoff_status") == "failed" or diagnostics.get("status") == "failed":
                        return STATUS_READY
                return STATUS_COMPLETED
            return STATUS_READY
        diagnostics_file = paths.get("equilibration_diagnostics")
        if diagnostics_file and diagnostics_file.exists():
            try:
                diagnostics = json.loads(diagnostics_file.read_text())
            except json.JSONDecodeError:
                return STATUS_READY
            if diagnostics.get("handoff_status") == "failed" or diagnostics.get("status") == "failed":
                return STATUS_READY
        return STATUS_COMPLETED
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    inputs = [paths["case_file"], paths["prepared_data"], paths["groups_regions"]]
    if not all(path.exists() for path in inputs):
        return STATUS_MISSING
    return STATUS_READY


def initial_rh_task_status(
    *,
    expected: list[Path],
    dependencies: list[str],
    status_by_id: dict[str, str],
    input_files: list[Path],
    status_file: Path,
) -> str:
    if expected and file_exists(expected):
        if status_file.exists():
            try:
                status_doc = json.loads(status_file.read_text())
            except json.JSONDecodeError:
                return STATUS_READY
            if status_doc.get("status") == "completed":
                return STATUS_COMPLETED
            return STATUS_READY
        return STATUS_COMPLETED
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    if input_files and not all(path.exists() for path in input_files):
        return STATUS_MISSING
    return STATUS_READY


def analyze_rh_task_status(
    *,
    analysis_json: Path,
    continuation_status: Path,
    dependencies: list[str],
    status_by_id: dict[str, str],
    input_files: list[Path],
) -> str:
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    if input_files and not all(path.exists() for path in input_files):
        return STATUS_MISSING
    if analysis_json.exists():
        if continuation_status.exists() and continuation_status.stat().st_mtime > analysis_json.stat().st_mtime:
            try:
                status_doc = json.loads(continuation_status.read_text())
            except json.JSONDecodeError:
                return STATUS_READY
            if status_doc.get("status") == "completed" and status_doc.get("decision") == "continue":
                return STATUS_READY
        return STATUS_COMPLETED
    return STATUS_READY



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


def start_next_rh_task_status(
    *,
    status_path: Path,
    previous_summary: Path,
    dependencies: list[str],
    status_by_id: dict[str, str],
    input_files: list[Path],
    base_dir: Path,
) -> str:
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    if input_files and not all(path.exists() for path in input_files):
        return STATUS_MISSING
    expected_restart = expected_restart_from_archive_summary(previous_summary, base_dir)
    if status_path.exists():
        try:
            status_doc = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return STATUS_READY
        if status_doc.get("status") == "completed":
            source_restart = status_doc.get("source_restart") or status_doc.get("selected_restart")
            if expected_restart is None:
                return STATUS_READY
            if not source_restart:
                return STATUS_READY
            source_path = Path(str(source_restart))
            if not source_path.is_absolute():
                source_path = base_dir / source_path
            if source_path.resolve() == expected_restart.resolve() and expected_restart.exists():
                return STATUS_COMPLETED
            return STATUS_READY
        return STATUS_READY
    return STATUS_READY

def archived_summary_supports_handoff(archived_summary: Path) -> bool:
    if not archived_summary.exists():
        return False
    try:
        summary = json.loads(archived_summary.read_text())
    except json.JSONDecodeError:
        return False
    status = summary.get("analysis_status", summary.get("equilibrium_status"))
    recommendation = summary.get("analysis_recommendation", summary.get("equilibrium_recommendation"))
    return status == "equilibrated" and recommendation in {"archive", "write_data_and_continue_next_rh"}


def continue_or_archive_task_status(
    *,
    analysis_json: Path,
    continuation_status: Path,
    archived_summary: Path,
    dependencies: list[str],
    status_by_id: dict[str, str],
) -> str:
    if archived_summary_supports_handoff(archived_summary):
        return STATUS_COMPLETED
    if dependencies and any(status_by_id.get(dep) not in {STATUS_COMPLETED, STATUS_SKIPPED} for dep in dependencies):
        return STATUS_BLOCKED
    if not analysis_json.exists():
        return STATUS_MISSING
    if continuation_status.exists():
        try:
            status_doc = json.loads(continuation_status.read_text())
        except json.JSONDecodeError:
            return STATUS_READY
        if status_doc.get("status") == "completed" and status_doc.get("decision") == "continue" and continuation_status.stat().st_mtime > analysis_json.stat().st_mtime:
            return STATUS_BLOCKED
    return STATUS_READY



def system_paths(system_id: str, base_dir: Path) -> dict[str, Path]:
    example_dir = base_dir / "examples" / system_id
    clay_inputs = example_dir / "claycode_inputs"
    return {
        "example_dir": example_dir,
        "clay_inputs": clay_inputs,
        "planner_yaml": clay_inputs / f"{system_id}.yaml",
        "planner_csv": clay_inputs / f"{system_id}.csv",
        "planner_metadata": clay_inputs / f"{system_id}.metadata.json",
        "planner_plan": clay_inputs / "claycode_input_plan.json",
        "case_file": base_dir / f"case.{system_id}.yaml",
        "raw_gro": example_dir / "raw" / f"{system_id}_5_4.gro",
        "raw_top": example_dir / "raw" / f"{system_id}_5_4.top",
        "prepared_data": example_dir / "inputs" / f"{system_id}_prepared.data",
        "groups_regions": example_dir / "inputs" / f"{system_id}_groups_regions.inc",
        "type_report": example_dir / "generated" / f"{system_id}_v2.type_report.csv",
        "prepared_report": example_dir / "generated" / f"{system_id}_prepared.report.json",
        "prepared_check_json": example_dir / "generated" / f"{system_id}_prepared.check.json",
        "equilibrated_data": example_dir / "inputs" / f"{system_id}_equilibrated.data",
        "pre_gcmc_restart": example_dir / "inputs" / "restart.pre_gcmc.final",
        "equilibration_diagnostics": example_dir / "generated" / f"{system_id}.run_equilibrate_diagnostics.json",
        "states_dir": example_dir / "states",
        "generated_dir": example_dir / "generated",
    }


def ignored_runtime_dirs(paths: dict[str, Path]) -> list[str]:
    found: list[str] = []
    for candidate in [paths["example_dir"] / "equilibration", paths["example_dir"] / "equilibration_smoke"]:
        if candidate.exists():
            found.append(str(candidate))
    for candidate in sorted(paths["example_dir"].glob("rh_*")):
        if candidate.is_dir():
            found.append(str(candidate))
    return found

def plan_for_system(
    *,
    campaign_cfg: dict[str, Any],
    system: dict[str, Any],
    rh_path: list[float],
    base_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    system_id = str(system["system_id"])
    cation = str(system["cation"])
    valence = int(system["valence"])
    x = float(system["substitution_amount_x"])
    total = int(system["expected_total_cation_count"])
    partition = dict(system["expected_partition"])
    paths = system_paths(system_id, base_dir)
    templates = campaign_cfg.get("templates", {})
    if not isinstance(templates, dict):
        templates = {}
    template_yaml = resolve_path(templates.get("claycode_yaml", "assets/claycode/MyMont1.yaml"), base_dir)
    template_csv = resolve_path(templates.get("claycode_csv", "assets/claycode/exp_clay.csv"), base_dir)

    status_by_id: dict[str, str] = {}
    tasks: list[dict[str, Any]] = []

    plan_task = f"{system_id}:plan_claycode_inputs"
    tasks.append(
        build_task(
            task_id=plan_task,
            system_id=system_id,
            stage="plan_claycode_inputs",
            command_preview=(
                "python3 mtagent/plan_claycode_inputs.py "
                f"--case case.{system_id}.yaml --template-yaml {rel(template_yaml, base_dir)} "
                f"--template-csv {rel(template_csv, base_dir)} --out-dir {rel(paths['clay_inputs'], base_dir)} "
                f"--cation {cation} --charge {x:g} --base-name Mt --force"
            ),
            input_files=[template_yaml, template_csv],
            expected_output_files=[
                paths["planner_yaml"],
                paths["planner_csv"],
                paths["planner_metadata"],
                paths["planner_plan"],
            ],
            dependencies=[],
            status_by_id=status_by_id,
            base_dir=base_dir,
        )
    )

    clay_task = f"{system_id}:run_claycode"
    tasks.append(
        build_task(
            task_id=clay_task,
            system_id=system_id,
            stage="run_claycode",
            command_preview=f"python3 mtagent/run_claycode.py --case case.{system_id}.yaml --dry-run",
            input_files=[paths["planner_yaml"], paths["planner_csv"]],
            expected_output_files=[paths["raw_gro"], paths["raw_top"]],
            dependencies=[plan_task],
            status_by_id=status_by_id,
            base_dir=base_dir,
        )
    )

    create_case_task = f"{system_id}:create_case_file"
    tasks.append(
        build_task(
            task_id=create_case_task,
            system_id=system_id,
            stage="create_case_file",
            command_preview=f"python3 mtagent/run_campaign.py --campaign <campaign.yaml> --execute-next --max-actions 1",
            input_files=[paths["raw_gro"], paths["raw_top"]],
            expected_output_files=[paths["case_file"]],
            dependencies=[clay_task],
            status_by_id=status_by_id,
            base_dir=base_dir,
        )
    )

    prepare_task = f"{system_id}:prepare_case"
    tasks.append(
        build_task(
            task_id=prepare_task,
            system_id=system_id,
            stage="prepare_case",
            command_preview=f"python3 mtagent/prepare_case.py --case case.{system_id}.yaml",
            input_files=[paths["case_file"], paths["raw_gro"], paths["raw_top"]],
            expected_output_files=[
                paths["prepared_data"],
                paths["groups_regions"],
                paths["prepared_report"],
                paths["type_report"],
                paths["prepared_check_json"],
            ],
            dependencies=[create_case_task],
            status_by_id=status_by_id,
            base_dir=base_dir,
        )
    )

    equil_task = f"{system_id}:run_equilibrate"
    equil_status = equilibration_task_status(paths, [prepare_task], status_by_id)
    status_by_id[equil_task] = equil_status
    tasks.append({
        "task_id": equil_task,
        "system_id": system_id,
        "stage": "run_equilibrate",
        "command_preview": (
            f"python3 mtagent/run_equilibrate.py --case case.{system_id}.yaml --run "
            "--soft-steps-override 5000 --steps-override 10000"
        ),
        "input_files": [rel(path, base_dir) for path in [paths["case_file"], paths["prepared_data"], paths["groups_regions"]]],
        "expected_output_files": [rel(path, base_dir) for path in [paths["equilibrated_data"], paths["pre_gcmc_restart"]]],
        "dependencies": [prepare_task],
        "status": equil_status,
    })

    previous_archive_task: str | None = None
    for index, rh in enumerate(rh_path):
        tag = rh_tag(rh)
        rh_name = rh_dir_name(rh)
        rh_dir = paths["example_dir"] / rh_name
        monitor = rh_dir / f"monitor_gcmc_{tag}.dat"
        initial_status = rh_dir / "initial_status.json"
        start_next_status = rh_dir / "start_next_rh_status.json"
        analysis_json = paths["generated_dir"] / f"{system_id}.{tag.replace('rh', 'rh_')}_analysis.json"
        equilibrium_status = rh_dir / "equilibrium_status.preview.json"
        manager_decision = rh_dir / "manager_decision.preview.json"
        archived_summary = paths["states_dir"] / rh_name / "summary.json"
        initial_task = f"{system_id}:run_initial_{tag}"
        if index == 0:
            initial_deps = [equil_task]
            stage = f"run_initial_{rh_name}"
            command = (
                f"python3 mtagent/run_initial.py --case case.{system_id}.yaml "
                f"--run-dir {rel(rh_dir, base_dir)} --dry-run --write-input"
            )
            initial_inputs = [paths["case_file"], paths["pre_gcmc_restart"]]
        else:
            previous_rh = rh_path[index - 1]
            start_task = f"{system_id}:start_next_{tag}"
            start_deps = [previous_archive_task] if previous_archive_task else [equil_task]
            start_inputs = [paths["case_file"], paths["states_dir"] / rh_dir_name(previous_rh) / "summary.json"]
            start_status = start_next_rh_task_status(
                status_path=start_next_status,
                previous_summary=paths["states_dir"] / rh_dir_name(previous_rh) / "summary.json",
                dependencies=start_deps,
                status_by_id=status_by_id,
                input_files=start_inputs,
                base_dir=base_dir,
            )
            status_by_id[start_task] = start_status
            tasks.append({
                "task_id": start_task,
                "system_id": system_id,
                "stage": f"start_next_{rh_name}",
                "generic_stage": "start_next_rh",
                "rh": rh,
                "rh_tag": tag,
                "rh_dir": rh_name,
                "previous_rh": previous_rh,
                "previous_rh_tag": rh_tag(previous_rh),
                "previous_rh_dir": rh_dir_name(previous_rh),
                "command_preview": (
                    "python3 mtagent/start_next_rh.py "
                    f"--case case.{system_id}.yaml --from-state "
                    f"{rel(paths['states_dir'] / rh_dir_name(previous_rh), base_dir)} "
                    f"--rh {rh:.2f} --run-dir {rel(rh_dir, base_dir)} --dry-run --write-input"
                ),
                "input_files": [rel(path, base_dir) for path in start_inputs],
                "expected_output_files": [rel(start_next_status, base_dir)],
                "dependencies": start_deps,
                "status": start_status,
            })
            initial_deps = [start_task]
            stage = f"run_initial_{rh_name}"
            command = (
                "python3 mtagent/start_next_rh.py "
                f"--case case.{system_id}.yaml --from-state "
                f"{rel(paths['states_dir'] / rh_dir_name(previous_rh), base_dir)} "
                f"--rh {rh:.2f} --run-dir {rel(rh_dir, base_dir)} --run"
            )
            initial_inputs = [paths["case_file"], start_next_status]
        initial_expected = [initial_status, monitor, rh_dir / f"restart.gcmc_{tag}.final", rh_dir / f"after_gcmc_{tag}_initial.data"]
        initial_status_value = initial_rh_task_status(
            expected=initial_expected,
            dependencies=initial_deps,
            status_by_id=status_by_id,
            input_files=initial_inputs,
            status_file=initial_status,
        )
        status_by_id[initial_task] = initial_status_value
        tasks.append({
            "task_id": initial_task,
            "system_id": system_id,
            "stage": stage,
            "generic_stage": "run_initial_rh",
            "rh": rh,
            "rh_tag": tag,
            "rh_dir": rh_name,
            "previous_rh": rh_path[index - 1] if index else None,
            "previous_rh_tag": rh_tag(rh_path[index - 1]) if index else None,
            "previous_rh_dir": rh_dir_name(rh_path[index - 1]) if index else None,
            "command_preview": command,
            "input_files": [rel(path, base_dir) for path in initial_inputs],
            "expected_output_files": [rel(path, base_dir) for path in initial_expected],
            "dependencies": initial_deps,
            "status": initial_status_value,
        })
        continuation_status = paths["generated_dir"] / f"{system_id}.{tag.replace('rh', 'rh_')}_continue_or_archive_status.json"
        analyze_task = f"{system_id}:analyze_{tag}"
        analyze_status = analyze_rh_task_status(
            analysis_json=analysis_json,
            continuation_status=continuation_status,
            dependencies=[initial_task],
            status_by_id=status_by_id,
            input_files=[monitor, initial_status],
        )
        status_by_id[analyze_task] = analyze_status
        tasks.append({
            "task_id": analyze_task,
            "system_id": system_id,
            "stage": f"analyze_{rh_name}",
            "generic_stage": "analyze_rh",
            "rh": rh,
            "rh_tag": tag,
            "rh_dir": rh_name,
            "command_preview": f"python3 mtagent/run_campaign.py --campaign <campaign.yaml> --execute-next --max-actions 1  # analyze {rh_name}",
            "input_files": [rel(path, base_dir) for path in [monitor, initial_status]],
            "expected_output_files": [rel(analysis_json, base_dir)],
            "dependencies": [initial_task],
            "status": analyze_status,
        })
        archive_task = f"{system_id}:continue_or_archive_{tag}"
        archive_status = continue_or_archive_task_status(
            analysis_json=analysis_json,
            continuation_status=continuation_status,
            archived_summary=archived_summary,
            dependencies=[analyze_task],
            status_by_id=status_by_id,
        )
        status_by_id[archive_task] = archive_status
        tasks.append({
            "task_id": archive_task,
            "system_id": system_id,
            "stage": f"continue_or_archive_{rh_name}",
            "generic_stage": "continue_or_archive_rh",
            "rh": rh,
            "rh_tag": tag,
            "rh_dir": rh_name,
            "command_preview": (
                "python3 mtagent/run_campaign.py --campaign <campaign.yaml> --execute-next --max-actions 1  # continue or archive current RH"
            ),
            "input_files": [rel(analysis_json, base_dir)],
            "expected_output_files": [rel(archived_summary, base_dir), rel(continuation_status, base_dir)],
            "dependencies": [analyze_task],
            "status": archive_status,
        })
        previous_archive_task = archive_task

    geometry = campaign_cfg.get("geometry", {})
    if not isinstance(geometry, dict):
        geometry = {}
    total_unit_cells = (
        int(geometry.get("x_cells", 5))
        * int(geometry.get("y_cells", 4))
        * int(geometry.get("n_sheets", 2))
    )
    system_plan = {
        "system_id": system_id,
        "cation": cation,
        "valence": valence,
        "substitution_amount_x": x,
        "layer_charge_per_uc_signed": -x,
        "layer_charge_label": layer_charge_label(x),
        "total_unit_cells": total_unit_cells,
        "expected_total_cation_count": total,
        "expected_partition": partition,
        "case_file": rel(paths["case_file"], base_dir),
        "example_dir": rel(paths["example_dir"], base_dir),
        "ignored_runtime_dirs_present": [rel(Path(p), base_dir) for p in ignored_runtime_dirs(paths)],
        "small_records": {
            "planner_inputs_exist": file_exists(
                [paths["planner_yaml"], paths["planner_csv"], paths["planner_metadata"], paths["planner_plan"]]
            ),
            "case_file_exists": paths["case_file"].exists(),
            "prepared_report_exists": paths["prepared_report"].exists(),
        },
    }
    return system_plan, tasks


def next_actions(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    actionable = [task for task in tasks if task["status"] in {STATUS_READY, STATUS_MISSING}]
    if actionable:
        first = actionable[0]
        action = (
            "would_run_preview_or_execute_in_future_run_campaign"
            if first["status"] == STATUS_READY
            else "missing_inputs_or_outputs_need_attention"
        )
        return [
            {
                "task_id": first["task_id"],
                "stage": first["stage"],
                "action": action,
                "command_preview": first["command_preview"],
            }
        ]
    blocked = [task for task in tasks if task["status"] == STATUS_BLOCKED]
    if blocked:
        first = blocked[0]
        return [
            {
                "task_id": first["task_id"],
                "stage": first["stage"],
                "action": "blocked_waiting_for_dependencies",
                "command_preview": first["command_preview"],
            }
        ]
    return [{"task_id": "", "stage": "", "action": "campaign_plan_has_no_ready_tasks", "command_preview": ""}]


def make_plan(campaign_path: Path, base_dir: Path | None = None) -> dict[str, Any]:
    base_dir = (base_dir or Path.cwd()).resolve()
    campaign_path = campaign_path.resolve()
    campaign_cfg = load_yaml(campaign_path)
    validate_campaign(campaign_cfg)

    campaign_meta = campaign_cfg.get("campaign", {})
    if not isinstance(campaign_meta, dict):
        campaign_meta = {}
    campaign_id = str(campaign_meta.get("id", campaign_path.stem))
    rh_path = [float(rh) for rh in campaign_cfg.get("rh_path", [])]
    if not rh_path:
        raise ValueError("campaign YAML must define rh_path")

    systems: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for system in campaign_cfg["systems"]:
        system_plan, system_tasks = plan_for_system(
            campaign_cfg=campaign_cfg,
            system=system,
            rh_path=rh_path,
            base_dir=base_dir,
        )
        systems.append(system_plan)
        tasks.extend(system_tasks)

    counts: dict[str, int] = {status: 0 for status in [STATUS_MISSING, STATUS_READY, STATUS_COMPLETED, STATUS_BLOCKED, STATUS_SKIPPED]}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1

    return {
        "schema_version": 1,
        "status": "dry_run_plan",
        "created_at": now_iso(),
        "campaign_id": campaign_id,
        "campaign_file": rel(campaign_path, base_dir),
        "dry_run_only": bool(campaign_meta.get("dry_run_only", True)),
        "rh_path": rh_path,
        "simulation_policy": campaign_cfg.get("simulation_policy", {}),
        "systems": systems,
        "planned_tasks": tasks,
        "dependencies": {task["task_id"]: task["dependencies"] for task in tasks},
        "expected_outputs": {task["task_id"]: task["expected_output_files"] for task in tasks},
        "current_status": {"task_counts": counts},
        "next_actions": next_actions(tasks),
    }


def markdown_table_row(values: list[Any]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def render_markdown(plan: dict[str, Any]) -> str:
    lines = [
        f"# Campaign Plan: {plan['campaign_id']}",
        "",
        "## Overview",
        "",
        f"- Campaign file: `{plan['campaign_file']}`",
        f"- Dry-run only: `{plan['dry_run_only']}`",
        f"- RH path: `{plan['rh_path']}`",
        "",
        "## Systems",
        "",
        markdown_table_row(["system_id", "cation", "x", "total_cations", "partition", "case_file"]),
        markdown_table_row(["---", "---", "---", "---", "---", "---"]),
    ]
    for system in plan["systems"]:
        partition = system["expected_partition"]
        lines.append(
            markdown_table_row(
                [
                    system["system_id"],
                    system["cation"],
                    system["substitution_amount_x"],
                    system["expected_total_cation_count"],
                    f"{partition['bottom_external']}:{partition['interlayer']}:{partition['top_external']}",
                    f"`{system['case_file']}`",
                ]
            )
        )
    lines.extend(["", "## Stages", ""])
    lines.append(markdown_table_row(["task_id", "stage", "status", "dependencies"]))
    lines.append(markdown_table_row(["---", "---", "---", "---"]))
    for task in plan["planned_tasks"]:
        lines.append(markdown_table_row([task["task_id"], task["stage"], task["status"], ", ".join(task["dependencies"])]))

    counts = plan["current_status"]["task_counts"]
    lines.extend(
        [
            "",
            "## Status Counts",
            "",
            markdown_table_row(["status", "count"]),
            markdown_table_row(["---", "---"]),
        ]
    )
    for status in [STATUS_COMPLETED, STATUS_READY, STATUS_BLOCKED, STATUS_MISSING, STATUS_SKIPPED]:
        lines.append(markdown_table_row([status, counts.get(status, 0)]))

    lines.extend(["", "## Next Recommended Action", ""])
    for action in plan["next_actions"]:
        lines.append(f"- `{action['task_id']}`: {action['action']}")
        if action["command_preview"]:
            lines.append(f"  - Preview: `{action['command_preview']}`")

    lines.extend(["", "## Notes", ""])
    lines.append("- This planner is read-only and does not run ClayCode, LAMMPS, GCMC, or job submission.")
    lines.append("- Runtime directories may be reported if present, but they are not required for dry-run planning.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a read-only dry-run MD-GCMC campaign plan.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    try:
        plan = make_plan(args.campaign)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    write_json(args.output, plan)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(plan))
    print(json.dumps({"status": "planned", "output": str(args.output), "markdown": str(args.markdown)}, indent=2))


if __name__ == "__main__":
    main()

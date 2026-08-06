#!/usr/bin/env python3
"""Run ClayCode and stage selected raw files for the MD-GCMC workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_case_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"case.yaml not found: {path}")
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read case.yaml") from exc
    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_nested(cfg: Dict[str, Any], keys: list[str], default: Any = None) -> Any:
    cur: Any = cfg
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def resolve_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Expected {label} to be a file: {path}")


def build_plan(case_cfg: Dict[str, Any], case_path: Path) -> Dict[str, Any]:
    repo_root = case_path.parent.resolve()
    clay_cfg = case_cfg.get("claycode", {})
    if not isinstance(clay_cfg, dict):
        clay_cfg = {}
    paths_cfg = case_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        paths_cfg = {}

    work_dir = resolve_path(clay_cfg.get("work_dir", "assets/claycode"), repo_root)
    input_yaml_name = str(clay_cfg.get("input_yaml", "MyMont1.yaml"))
    input_yaml = work_dir / input_yaml_name
    exp_csv = work_dir / str(clay_cfg.get("exp_csv", "exp_clay.csv"))
    output_dir_name = str(clay_cfg.get("output_dir") or Path(input_yaml_name).stem)
    output_dir = work_dir / output_dir_name
    selected_prefix = str(clay_cfg.get("selected_prefix", get_nested(case_cfg, ["structure", "claycode_model"], "MyMont-1_5_4")))
    command = clay_cfg.get("command", ["ClayCode", "builder", "-f", input_yaml_name])
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("claycode.command must be a list of strings")

    raw_dir = resolve_path(paths_cfg.get("raw_dir", "examples/Mt_Oct050_Na/raw"), repo_root)
    selected_gro = output_dir / f"{selected_prefix}.gro"
    selected_top = output_dir / f"{selected_prefix}.top"
    destination_gro = raw_dir / selected_gro.name
    destination_top = raw_dir / selected_top.name

    return {
        "repo_root": repo_root,
        "cwd": work_dir,
        "command": command,
        "input_yaml": input_yaml,
        "exp_csv": exp_csv,
        "output_dir": output_dir,
        "selected_prefix": selected_prefix,
        "selected_gro": selected_gro,
        "selected_top": selected_top,
        "raw_dir": raw_dir,
        "destination_gro": destination_gro,
        "destination_top": destination_top,
        "status": raw_dir / "claycode_status.json",
        "preview_status": raw_dir / "claycode_status.preview.json",
    }


def status_base(plan: Dict[str, Any], dry_run: bool, force: bool) -> Dict[str, Any]:
    destination_gro = Path(plan["destination_gro"])
    destination_top = Path(plan["destination_top"])
    return {
        "status": "dry_run" if dry_run else "running",
        "dry_run": dry_run,
        "force": force,
        "cwd": str(plan["cwd"]),
        "command": plan["command"],
        "return_code": None,
        "input_yaml": str(plan["input_yaml"]),
        "exp_csv": str(plan["exp_csv"]),
        "output_dir": str(plan["output_dir"]),
        "expected_output_dir": str(plan["output_dir"]),
        "selected_prefix": plan["selected_prefix"],
        "selected_gro": str(plan["selected_gro"]),
        "selected_top": str(plan["selected_top"]),
        "expected_selected_gro": str(plan["selected_gro"]),
        "expected_selected_top": str(plan["selected_top"]),
        "copied_raw_gro": None,
        "copied_raw_top": None,
        "destination_gro": str(destination_gro),
        "destination_top": str(destination_top),
        "destination_gro_exists": destination_gro.exists(),
        "destination_top_exists": destination_top.exists(),
        "overwrite_needed": destination_gro.exists() or destination_top.exists(),
        "warnings": [],
        "started_at": now_iso(),
        "finished_at": None,
    }


def write_status(path: Path, status: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2))


def fail(status_path: Path, status: Dict[str, Any], message: str, return_code: int | None = None) -> None:
    status["status"] = "failed"
    status["error"] = message
    if return_code is not None:
        status["return_code"] = return_code
    status["finished_at"] = now_iso()
    write_status(status_path, status)
    raise SystemExit(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ClayCode and stage selected .gro/.top outputs.")
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without running ClayCode or copying files.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting selected destination .gro/.top files.")
    args = parser.parse_args()

    case_path = args.case.resolve()
    case_cfg = load_case_yaml(case_path)
    plan = build_plan(case_cfg, case_path)
    status_path = Path(plan["preview_status"] if args.dry_run else plan["status"])
    status = status_base(plan, dry_run=args.dry_run, force=args.force)

    try:
        require_file(Path(plan["input_yaml"]), "ClayCode input YAML")
        require_file(Path(plan["exp_csv"]), "ClayCode experiment CSV")
    except FileNotFoundError as exc:
        fail(status_path, status, str(exc))

    if args.dry_run:
        if status["overwrite_needed"]:
            status["warnings"].append("Destination .gro/.top exists; --force would be required for a normal run.")
        status["finished_at"] = now_iso()
        write_status(status_path, status)
        print(json.dumps(status, indent=2))
        return

    if status["overwrite_needed"] and not args.force:
        fail(status_path, status, "Destination .gro/.top exists. Use --force to overwrite.")

    print(">>>", " ".join(plan["command"]))
    proc = subprocess.run(plan["command"], cwd=plan["cwd"])
    status["return_code"] = proc.returncode
    if proc.returncode != 0:
        fail(status_path, status, "ClayCode command failed", return_code=proc.returncode)

    try:
        require_file(Path(plan["selected_gro"]), "selected ClayCode .gro output")
        require_file(Path(plan["selected_top"]), "selected ClayCode .top output")
    except FileNotFoundError as exc:
        fail(status_path, status, str(exc), return_code=proc.returncode)

    Path(plan["raw_dir"]).mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan["selected_gro"], plan["destination_gro"])
    shutil.copy2(plan["selected_top"], plan["destination_top"])

    status["status"] = "completed"
    status["copied_raw_gro"] = str(plan["destination_gro"])
    status["copied_raw_top"] = str(plan["destination_top"])
    status["finished_at"] = now_iso()
    write_status(status_path, status)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Prepare a case from selected ClayCode raw files to LAMMPS-ready inputs.

This is an orchestration wrapper only. It validates configured paths, builds the
existing preprocessing commands, and either prints them in dry-run mode or runs
those scripts in order.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


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


def command_record(name: str, cmd: List[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "command": cmd,
        "return_code": None,
    }


def build_plan(case_cfg: Dict[str, Any], case_path: Path, repo_root: Path) -> Dict[str, Any]:
    base_dir = case_path.parent.resolve()
    paths_cfg = case_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        paths_cfg = {}

    example_dir = resolve_path(paths_cfg.get("example_dir", "examples/Mt_Oct050_Na"), base_dir)
    model = str(get_nested(case_cfg, ["structure", "claycode_model"], "MyMont-1_5_4"))

    raw_gro = resolve_path(paths_cfg.get("raw_gro", example_dir / "raw" / f"{model}.gro"), base_dir)
    raw_top = resolve_path(paths_cfg.get("raw_top", example_dir / "raw" / f"{model}.top"), base_dir)
    forcefield_file = resolve_path(paths_cfg.get("forcefield_file", "assets/forcefields/clayff-paper-2021"), base_dir)
    generated_dir = resolve_path(paths_cfg.get("generated_dir", example_dir / "generated"), base_dir)
    prepared_dir = resolve_path(paths_cfg.get("prepared_dir", example_dir / "inputs"), base_dir)

    spce_source = resolve_path(get_nested(case_cfg, ["water", "spce_source"], "assets/forcefields/SPCEH2O.txt"), base_dir)
    molecule_template = resolve_path(get_nested(case_cfg, ["water", "molecule_template"], "assets/forcefields/SPCEH2O_types_8_10.txt"), base_dir)

    converted_data = generated_dir / f"{model}_v2.data"
    summary = generated_dir / f"{model}_v2.summary.txt"
    type_report = generated_dir / f"{model}_v2.type_report.csv"
    check_json = generated_dir / f"{model}_v2.check.json"
    prepared_data = prepared_dir / f"{model}_prepared.data"
    prepared_check_json = generated_dir / f"{model}_prepared.check.json"
    prepare_report = generated_dir / f"{model}_prepared.report.json"
    lammps_include = prepared_dir / f"{model}_groups_regions.inc"
    status_path = generated_dir / "prepare_status.json"

    ion_species = str(get_nested(case_cfg, ["structure", "cation"], "Na"))
    planner_metadata_path = get_nested(case_cfg, ["structure", "planner_metadata"], None)
    planner_metadata = {}
    if planner_metadata_path:
        metadata_path = resolve_path(planner_metadata_path, base_dir)
        if metadata_path.exists():
            planner_metadata = json.loads(metadata_path.read_text())
            ion_species = str(planner_metadata.get("cation", ion_species))

    target_ion = get_nested(case_cfg, ["structure", "target_ion_distribution"], None)
    if target_ion is None:
        target_ion = get_nested(case_cfg, ["structure", "target_na_distribution"], None)
    if target_ion is None and planner_metadata:
        target_ion = {
            "bottom_external": planner_metadata.get("target_bottom_ions"),
            "interlayer": planner_metadata.get("target_interlayer_ions"),
            "top_external": planner_metadata.get("target_top_ions"),
        }
    target_ion = target_ion or {}
    bottom_ions = int(target_ion.get("bottom_external", 5))
    interlayer_ions = int(target_ion.get("interlayer", 10))
    top_ions = int(target_ion.get("top_external", 5))
    expected_ions = bottom_ions + interlayer_ions + top_ions

    converter = repo_root / "scripts" / "gro_clayff_to_lammps_v2.py"
    checker = repo_root / "scripts" / "check_lammps_data.py"
    preparer = repo_root / "scripts" / "prepare_mt_data.py"

    check_count_args = ["--expected-ion-species", ion_species, "--expected-ion-count", str(expected_ions)]
    if ion_species == "Na":
        check_count_args.extend(["--expected-na", str(expected_ions)])

    commands = [
        command_record("convert", [
            sys.executable,
            str(converter),
            "--gro", str(raw_gro),
            "--clayff", str(forcefield_file),
            "--spce", str(spce_source),
            "--out", str(converted_data),
            "--summary", str(summary),
            "--type-report", str(type_report),
        ]),
        command_record("check", [
            sys.executable,
            str(checker),
            "--data", str(converted_data),
            "--type-report", str(type_report),
            *check_count_args,
            "--json", str(check_json),
        ]),
        command_record("prepare", [
            sys.executable,
            str(preparer),
            "--data", str(converted_data),
            "--type-report", str(type_report),
            "--out", str(prepared_data),
            "--report", str(prepare_report),
            "--lammps-include", str(lammps_include),
            "--ion-species", ion_species,
            "--target-bottom-ions", str(bottom_ions),
            "--target-interlayer-ions", str(interlayer_ions),
            "--target-top-ions", str(top_ions),
        ]),
        command_record("check_prepared", [
            sys.executable,
            str(checker),
            "--data", str(prepared_data),
            "--type-report", str(type_report),
            *check_count_args,
            "--json", str(prepared_check_json),
            "--require-normalized-molecule-ids",
        ]),
    ]

    return {
        "model": model,
        "inputs": {
            "raw_gro": str(raw_gro),
            "raw_top": str(raw_top),
            "forcefield_file": str(forcefield_file),
            "spce_source": str(spce_source),
            "molecule_template": str(molecule_template),
        },
        "outputs": {
            "generated_dir": str(generated_dir),
            "prepared_dir": str(prepared_dir),
            "converted_data": str(converted_data),
            "summary": str(summary),
            "type_report": str(type_report),
            "check_json": str(check_json),
            "prepared_check_json": str(prepared_check_json),
            "prepared_data": str(prepared_data),
            "prepare_report": str(prepare_report),
            "lammps_include": str(lammps_include),
            "status": str(status_path),
        },
        "ion_preparation": {
            "ion_species": ion_species,
            "target_bottom_ions": bottom_ions,
            "target_interlayer_ions": interlayer_ions,
            "target_top_ions": top_ions,
            "expected_ions": expected_ions,
            "planner_metadata": str(resolve_path(planner_metadata_path, base_dir)) if planner_metadata_path else None,
        },
        "scripts": {
            "converter": str(converter),
            "checker": str(checker),
            "preparer": str(preparer),
        },
        "commands": commands,
    }


def validate_plan(plan: Dict[str, Any]) -> None:
    inputs = plan["inputs"]
    scripts = plan["scripts"]
    require_file(Path(inputs["raw_gro"]), "raw gro file")
    require_file(Path(inputs["raw_top"]), "raw top file")
    require_file(Path(inputs["forcefield_file"]), "forcefield file")
    require_file(Path(inputs["spce_source"]), "SPC/E source file")
    require_file(Path(inputs["molecule_template"]), "water molecule template")
    require_file(Path(scripts["converter"]), "converter script")
    require_file(Path(scripts["checker"]), "checker script")
    require_file(Path(scripts["preparer"]), "prepare script")


def write_status(status_path: Path, status: Dict[str, Any]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2))


def run_commands(commands: List[Dict[str, Any]], status: Dict[str, Any], status_path: Path) -> int:
    for item in commands:
        print()
        print(">>>", " ".join(item["command"]))
        proc = subprocess.run(item["command"])
        item["return_code"] = proc.returncode
        write_status(status_path, status)
        if proc.returncode != 0:
            status["status"] = f"failed_at_{item['name']}"
            status["finished_at"] = now_iso()
            write_status(status_path, status)
            return proc.returncode
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare selected ClayCode files into LAMMPS GCMC input assets.")
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print planned commands without running them.")
    parser.add_argument("--status", type=Path, default=None, help="Override prepare_status.json output path.")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    case_path = args.case.resolve()
    case_cfg = load_case_yaml(case_path)
    plan = build_plan(case_cfg, case_path, repo_root)
    validate_plan(plan)

    status_path = args.status.resolve() if args.status is not None else Path(plan["outputs"]["status"])
    status: Dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "running",
        "dry_run": args.dry_run,
        "started_at": now_iso(),
        "finished_at": None,
        "case": str(case_path),
        "inputs": plan["inputs"],
        "outputs": plan["outputs"],
        "ion_preparation": plan["ion_preparation"],
        "commands": plan["commands"],
    }

    for output_dir_key in ("generated_dir", "prepared_dir"):
        Path(plan["outputs"][output_dir_key]).mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        status["finished_at"] = now_iso()
        write_status(status_path, status)
        print(json.dumps(status, indent=2))
        return

    write_status(status_path, status)
    rc = run_commands(plan["commands"], status, status_path)
    if rc != 0:
        raise SystemExit(rc)

    status["status"] = "completed"
    status["finished_at"] = now_iso()
    write_status(status_path, status)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()

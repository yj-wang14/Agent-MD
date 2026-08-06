#!/usr/bin/env python3
"""Start a new RH run from an archived equilibrated RH state."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtagent import generate_gcmc_input, local_runner, run_initial


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    return json.loads(path.read_text())


def resolve_restart(from_state: Path, summary: dict[str, Any]) -> tuple[Path, str]:
    for key in ("archived_restart", "selected_restart"):
        value = summary.get(key)
        if not value:
            continue
        restart = Path(value)
        candidates = [restart] if restart.is_absolute() else [Path.cwd() / restart, from_state / restart]
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.exists():
                return candidate, key
    raise FileNotFoundError(
        f"No existing archived_restart or selected_restart found in {from_state / 'summary.json'}"
    )


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def run_lammps(
    case_cfg: dict[str, Any],
    run_dir: Path,
    input_path: Path,
    np: int | None,
    status: dict[str, Any],
) -> int:
    command = local_runner.build_command(case_cfg, np=np, input_file=input_path.name, no_mpi=False)
    stdout_path = run_dir / f"{input_path.name}.stdout"
    stderr_path = run_dir / f"{input_path.name}.stderr"
    status["runner"] = {
        "status": "running",
        "cwd": str(run_dir),
        "command": command,
        "command_string": " ".join(shlex.quote(x) for x in command),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "started_at": now_iso(),
        "finished_at": None,
        "elapsed_seconds": None,
        "return_code": None,
    }
    t0 = time.time()
    with stdout_path.open("w") as fout, stderr_path.open("w") as ferr:
        proc = subprocess.run(command, cwd=run_dir, stdout=fout, stderr=ferr, text=True)
    elapsed = time.time() - t0
    status["runner"]["finished_at"] = now_iso()
    status["runner"]["elapsed_seconds"] = elapsed
    status["runner"]["return_code"] = proc.returncode
    status["runner"]["status"] = "completed" if proc.returncode == 0 else "failed"
    return proc.returncode


def start_next_rh(
    *,
    case_path: Path,
    from_state: Path,
    rh: float,
    run_dir: Path,
    dry_run: bool = True,
    run: bool = False,
    force: bool = False,
    np: int | None = None,
    segment_steps_override: int | None = None,
    write_input: bool = True,
) -> dict[str, Any]:
    if dry_run and run:
        raise SystemExit("Use either --dry-run or --run, not both.")
    if segment_steps_override is not None and segment_steps_override <= 0:
        raise SystemExit("--segment-steps-override must be a positive integer.")

    repo_root = Path.cwd().resolve()
    case_path = case_path.resolve()
    from_state = from_state.resolve()
    run_dir = run_dir.resolve()
    summary_path = from_state / "summary.json"
    summary = load_json(summary_path)
    restart, restart_key = resolve_restart(from_state, summary)

    case_cfg = run_initial.load_case_yaml(case_path)
    tag = generate_gcmc_input.rh_to_tag(rh)
    paths = run_initial.build_paths(case_cfg, case_path, repo_root, rh, run_dir_override=run_dir)
    molecule_template = run_initial.resolve_path(
        run_initial.get_nested(case_cfg, ["water", "molecule_template"], "assets/forcefields/SPCEH2O_types_8_10.txt"),
        case_path.parent.resolve(),
    )
    run_initial.validate_inputs(paths, molecule_template, restart)

    collision_files = run_initial.find_collision_files(run_dir)
    collision_warning = None
    if collision_files:
        collision_warning = (
            f"Run directory contains existing monitor/restart files: {run_dir}. "
            "Use --force only when intentionally starting from this directory."
        )
        if run and not force:
            raise SystemExit(collision_warning)

    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / f"in.gcmc_{tag}_initial"
    input_text, original_segment_steps, effective_segment_steps, initial_relax_steps, restart_interval = (
        run_initial.generate_initial_input(
            case_cfg=case_cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            start_source=restart,
            start_source_kind="archived_restart",
            groups_regions=paths["groups_regions"],
            molecule_template=molecule_template,
            rh=rh,
            segment_steps_override=segment_steps_override,
        )
    )
    if write_input:
        run_initial.write_text_if_new_or_same(input_path, input_text, force=force)

    status_path = run_dir / ("start_next_rh_status.json" if run else "start_next_rh_status.preview.json")
    initial_status_path = run_dir / ("initial_status.json" if run else "initial_status.preview.json")
    status: dict[str, Any] = {
        "status": "dry_run" if not run else "generated",
        "dry_run": not run,
        "run_requested": run,
        "case": str(case_path),
        "from_state": str(from_state),
        "from_state_summary": str(summary_path),
        "from_rh": summary.get("rh"),
        "from_final_step": summary.get("final_step"),
        "rh": rh,
        "tag": tag,
        "rh_tag": tag,
        "run_dir": str(run_dir),
        "input_file": str(input_path),
        "input_file_written": write_input,
        "write_input": write_input,
        "restart_key": restart_key,
        "selected_restart": str(restart),
        "start_source_kind": "archived_restart",
        "start_source": str(restart),
        "groups_regions": str(paths["groups_regions"]),
        "molecule_template": str(molecule_template),
        "original_segment_steps": original_segment_steps,
        "effective_segment_steps": effective_segment_steps,
        "initial_relax_steps": initial_relax_steps,
        "restart_interval": restart_interval,
        "segment_steps_override": segment_steps_override,
        "run_line": f"run {effective_segment_steps}",
        "neighbor_settings": generate_gcmc_input.neighbor_settings(case_cfg),
        "neigh_modify": generate_gcmc_input.neighbor_modify_line(case_cfg),
        "reinitialize_velocity_on_restart": bool(
            run_initial.get_nested(case_cfg, ["md", "reinitialize_velocity_on_restart"], False)
        ),
        "force": force,
        "np": np,
        "collision_files": [str(p) for p in collision_files],
        "warnings": [collision_warning] if collision_warning else [],
        "status_file": str(status_path),
        "initial_status_file": str(initial_status_path),
        "started_at": now_iso(),
        "finished_at": None,
    }

    if run:
        status["status"] = "running"
        write_json(status_path, status)
        write_json(initial_status_path, status)
        rc = run_lammps(case_cfg, run_dir, input_path, np, status)
        output_validation = run_initial.collect_output_validation(
            run_dir,
            tag,
            restart_expected=initial_relax_steps + effective_segment_steps >= restart_interval,
        )
        status["missing_outputs"] = output_validation["missing_outputs"]
        status["found_restart_files"] = output_validation["found_restart_files"]
        status["final_restart"] = output_validation["final_restart"]
        status["warnings"].extend(output_validation["warnings"])
        status["status"] = "completed" if rc == 0 and not status["missing_outputs"] else "failed"
        status["finished_at"] = now_iso()
        write_json(status_path, status)
        write_json(initial_status_path, status)
        if rc != 0:
            raise SystemExit(rc)
        if status["missing_outputs"]:
            raise SystemExit("LAMMPS returned successfully but expected output files are missing.")
        return status

    status["finished_at"] = now_iso()
    write_json(status_path, status)
    write_json(initial_status_path, status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--from-state", type=Path, required=True)
    parser.add_argument("--rh", type=float, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Generate input and preview status without running LAMMPS.")
    parser.add_argument("--run", action="store_true", help="Run the generated input locally.")
    parser.add_argument("--write-input", action="store_true", help="Accepted for CLI parity; start_next_rh writes input by default.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--np", type=int, default=None)
    parser.add_argument("--segment-steps-override", type=int, default=None)
    args = parser.parse_args()

    status = start_next_rh(
        case_path=args.case,
        from_state=args.from_state,
        rh=args.rh,
        run_dir=args.run_dir,
        dry_run=args.dry_run or not args.run,
        run=args.run,
        force=args.force,
        np=args.np,
        segment_steps_override=args.segment_steps_override,
        write_input=True,
    )
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

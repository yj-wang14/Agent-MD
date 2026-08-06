#!/usr/bin/env python3
"""
Run one agent cycle for MD-GCMC workflow.

One cycle:
  1. Analyze monitor file -> equilibrium_status.json
  2. Manager decides next action -> manager_decision.json
  3. If action is continue_current_rh:
       generate next GCMC continuation input
  4. Optionally run the generated input locally

Usage:

Dry-run full cycle:
  python3 mtagent/run_cycle.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --case case.yaml \
    --dry-run

Actually run the generated segment:
  python3 mtagent/run_cycle.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --case case.yaml \
    --run \
    --np 16
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtagent import analyze_gcmc_equilibrium_restart


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_command(cmd: List[str], cwd: Path | None = None) -> int:
    print("\n>>>", " ".join(str(x) for x in cmd))
    proc = subprocess.run(cmd, cwd=cwd)
    return proc.returncode


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    return json.loads(path.read_text())


def load_case_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore
    except ImportError:
        print("WARNING: PyYAML is not installed. Using analyzer CLI defaults.")
        return {}

    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def rh_from_dir(run_dir: Path) -> float:
    name = run_dir.name
    m = re.search(r"rh_?([0-9]+(?:p|\.)([0-9]+))", name)
    if not m:
        raise ValueError(f"Cannot infer RH from run directory name: {name}")
    return float(m.group(1).replace("p", "."))


def rh_to_tag(rh: float) -> str:
    return f"rh{rh:.2f}".replace(".", "p")


def latest_generated_input(run_dir: Path) -> Path | None:
    candidates = sorted(run_dir.glob("in.gcmc_rh*_segment_*"))
    if not candidates:
        return None
    return candidates[-1]


def last_valid_monitor_step(path: Path) -> float:
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return -1.0

    for line in reversed(lines):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if not parts:
            continue
        try:
            return float(parts[0])
        except ValueError:
            continue
    return -1.0




def timestep_from_restart_path(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\.(\d+)$", str(value))
    return int(match.group(1)) if match else None


def infer_rh_start_step(run_dir: Path) -> int:
    for name in ("start_next_rh_status.json", "initial_status.json", "start_next_rh_status.preview.json", "initial_status.preview.json"):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            status = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("from_final_step", "rh_start_step"):
            value = status.get(key)
            if value is not None:
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    pass
        for key in ("source_restart", "source_parent_restart", "selected_restart", "from_restart"):
            step = timestep_from_restart_path(status.get(key))
            if step is not None:
                return step
    return 0


def select_monitor(run_dir: Path, rh_tag: str) -> tuple[Path, bool]:
    matching = [p for p in run_dir.glob(f"monitor_gcmc_{rh_tag}*.dat") if p.is_file()]
    if matching:
        candidates = matching
        used_fallback = False
    else:
        candidates = [p for p in run_dir.glob("monitor_gcmc_*.dat") if p.is_file()]
        used_fallback = True
        if candidates:
            print(
                f"WARNING: No monitor file matching {rh_tag} found in {run_dir}; "
                "falling back to monitor_gcmc_*.dat."
            )

    if not candidates:
        return run_dir / f"monitor_gcmc_{rh_tag}.dat", used_fallback

    return max(candidates, key=lambda p: (last_valid_monitor_step(p), p.name)), used_fallback


def add_analyzer_equilibrium_args(
    cmd: List[str],
    case_cfg: Dict[str, Any],
    cli_window_steps: int | None,
) -> Dict[str, Any]:
    settings = analyze_gcmc_equilibrium_restart.equilibrium_settings_from_config(
        case_cfg,
        cli_window_steps=cli_window_steps,
        rh_handoff=True,
    )
    option_map = {
        "window_steps": "--window-steps",
        "total_cv_max": "--total-cv-max",
        "inter_cv_max": "--inter-cv-max",
        "ext_cv_max": "--ext-cv-max",
        "total_slope_frac_per_100k": "--total-slope-frac",
        "inter_slope_frac_per_100k": "--inter-slope-frac",
        "ext_slope_frac_per_100k": "--ext-slope-frac",
        "min_water_slope_abs": "--min-water-slope-abs",
        "basal_slope_abs_per_100k": "--basal-slope-max",
        "sum_tol": "--sum-tol",
    }
    for key, option in option_map.items():
        cmd += [option, str(settings[key])]
    if settings.get("require_previous_window_slopes"):
        cmd.append("--require-previous-window-slopes")
    return settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--monitor", type=str, default=None)
    parser.add_argument("--window-steps", type=int, default=None)
    parser.add_argument("--np", type=int, default=None)
    parser.add_argument("--run", action="store_true", help="Actually run LAMMPS segment locally.")
    parser.add_argument("--dry-run", action="store_true", help="Do not run LAMMPS; only generate decision/input.")
    parser.add_argument("--skip-analyze", action="store_true", help="Use existing equilibrium_status.json.")
    parser.add_argument("--skip-generate", action="store_true", help="Do not generate continuation input.")
    parser.add_argument("--cycle-status", type=str, default="cycle_status.json")
    parser.add_argument("--segment-steps-override", type=int, default=None, help="Override only the next generated segment length for testing.")
    parser.add_argument("--max-total-steps-per-rh-override", type=int, default=None, help="Override manager max_total_steps_per_rh for this cycle.")
    parser.add_argument("--rh-start-step", type=int, default=None, help="Absolute LAMMPS timestep where this RH state started; inferred from handoff status when omitted.")
    args = parser.parse_args()

    repo_root = Path.cwd()
    run_dir = args.run_dir.resolve()

    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    if args.dry_run and args.run:
        raise SystemExit("Use either --dry-run or --run, not both.")

    if args.segment_steps_override is not None and args.segment_steps_override <= 0:
        raise SystemExit("--segment-steps-override must be a positive integer.")

    case_cfg = load_case_yaml(args.case)
    rh_start_step = max(0, int(args.rh_start_step)) if args.rh_start_step is not None else infer_rh_start_step(run_dir)
    rh = rh_from_dir(run_dir)
    rh_tag = rh_to_tag(rh)

    analyzer = repo_root / "mtagent" / "analyze_gcmc_equilibrium_restart.py"
    manager = repo_root / "mtagent" / "campaign_manager.py"
    generator = repo_root / "mtagent" / "generate_gcmc_input.py"
    runner = repo_root / "mtagent" / "local_runner.py"

    for script in [manager, generator, runner]:
        if not script.exists():
            raise FileNotFoundError(f"Required script not found: {script}")

    if not analyzer.exists() and not args.skip_analyze:
        raise FileNotFoundError(f"Analyzer script not found: {analyzer}")

    monitor_name = args.monitor
    monitor_fallback_used = False
    if monitor_name is None:
        monitor_path, monitor_fallback_used = select_monitor(run_dir, rh_tag)
    else:
        monitor_path = run_dir / monitor_name

    if args.dry_run:
        equilibrium_json = run_dir / "equilibrium_status.preview.json"
        decision_json = run_dir / "manager_decision.preview.json"
        generation_status_path = run_dir / "input_generation_status.preview.json"
        cycle_status_path = run_dir / "cycle_status.preview.json"
    else:
        equilibrium_json = run_dir / "equilibrium_status.json"
        decision_json = run_dir / "manager_decision.json"
        generation_status_path = run_dir / "input_generation_status.json"
        cycle_status_path = run_dir / args.cycle_status

    cycle_status: Dict[str, Any] = {
        "status": "started",
        "started_at": now_iso(),
        "finished_at": None,
        "run_dir": str(run_dir),
        "case": str(args.case),
        "monitor": str(monitor_path),
        "selected_monitor": str(monitor_path),
        "selected_monitor_fallback": monitor_fallback_used,
        "selected_restart": None,
        "manager_action": None,
        "rh": rh,
        "rh_tag": rh_tag,
        "segment_steps_override": args.segment_steps_override,
        "max_total_steps_per_rh_override": args.max_total_steps_per_rh_override,
        "rh_start_step": rh_start_step,
        "equilibrium_json": str(equilibrium_json),
        "decision_json": str(decision_json),
        "generated_input": None,
        "runner_status": None,
        "steps": [],
    }

    cycle_status_path.write_text(json.dumps(cycle_status, indent=2))

    # ------------------------------------------------------------
    # 1. Analyze equilibrium
    # ------------------------------------------------------------
    if not args.skip_analyze:
        if not monitor_path.exists():
            raise FileNotFoundError(f"Monitor file not found: {monitor_path}")

        analyze_cmd = [
            sys.executable,
            str(analyzer),
            str(monitor_path),
            "--json",
            str(equilibrium_json),
        ]

        analyzer_settings = add_analyzer_equilibrium_args(
            analyze_cmd,
            case_cfg=case_cfg,
            cli_window_steps=args.window_steps,
        )
        cycle_status["analyzer_settings"] = analyzer_settings

        rc = run_command(analyze_cmd, cwd=repo_root)
        cycle_status["steps"].append({
            "name": "analyze",
            "return_code": rc,
            "output": str(equilibrium_json),
        })

        if rc != 0:
            cycle_status["status"] = "failed_at_analyze"
            cycle_status["finished_at"] = now_iso()
            cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
            raise SystemExit(rc)
    else:
        if not equilibrium_json.exists():
            raise FileNotFoundError(f"--skip-analyze used but missing {equilibrium_json}")
        cycle_status["steps"].append({
            "name": "analyze",
            "skipped": True,
            "output": str(equilibrium_json),
        })

    # ------------------------------------------------------------
    # 2. Manager decision
    # ------------------------------------------------------------
    decide_cmd = [
        sys.executable,
        str(manager),
        "decide",
        str(equilibrium_json),
        "--case",
        str(args.case),
        "--out",
        str(decision_json),
        "--rh-start-step",
        str(rh_start_step),
    ]
    if args.max_total_steps_per_rh_override is not None:
        decide_cmd += ["--max-total-steps-per-rh-override", str(args.max_total_steps_per_rh_override)]

    rc = run_command(decide_cmd, cwd=repo_root)
    cycle_status["steps"].append({
        "name": "decide",
        "return_code": rc,
        "output": str(decision_json),
    })

    if rc != 0:
        cycle_status["status"] = "failed_at_decide"
        cycle_status["finished_at"] = now_iso()
        cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
        raise SystemExit(rc)

    decision = load_json(decision_json)
    action = decision.get("action")
    cycle_status["manager_action"] = action

    print("\nManager action:", action)

    # ------------------------------------------------------------
    # 3. If equilibrated, stop cycle here
    # ------------------------------------------------------------
    if action == "write_data_and_continue_next_rh":
        cycle_status["status"] = "equilibrated"
        cycle_status["finished_at"] = now_iso()
        cycle_status["message"] = "Current RH is equilibrated. Next step: write final data and prepare next RH."
        cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
        print(json.dumps({
            "cycle_status": cycle_status["status"],
            "message": cycle_status["message"],
        }, indent=2))
        return

    if action == "flag_for_manual_check":
        cycle_status["status"] = "manual_check_required"
        cycle_status["finished_at"] = now_iso()
        cycle_status["message"] = "Manager flagged this RH for manual inspection."
        cycle_status["warnings"] = decision.get("warnings", [])
        cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
        print(json.dumps({
            "cycle_status": cycle_status["status"],
            "warnings": cycle_status["warnings"],
        }, indent=2))
        return

    if action != "continue_current_rh":
        cycle_status["status"] = "unknown_action"
        cycle_status["finished_at"] = now_iso()
        cycle_status["message"] = f"Unknown action from manager: {action}"
        cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
        raise SystemExit(cycle_status["message"])

    # ------------------------------------------------------------
    # 4. Generate next continuation input
    # ------------------------------------------------------------
    generated_input: Path | None = None

    if not args.skip_generate:
        generate_cmd = [
            sys.executable,
            str(generator),
            "--run-dir",
            str(run_dir),
            "--case",
            str(args.case),
            "--decision",
            str(decision_json),
        ]
        if args.dry_run:
            generate_cmd += ["--dry-run", "--status", str(generation_status_path)]
        if args.segment_steps_override is not None:
            generate_cmd += ["--segment-steps-override", str(args.segment_steps_override)]

        rc = run_command(generate_cmd, cwd=repo_root)
        cycle_status["steps"].append({
            "name": "generate_input",
            "return_code": rc,
        })

        if rc != 0:
            cycle_status["status"] = "failed_at_generate"
            cycle_status["finished_at"] = now_iso()
            cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
            raise SystemExit(rc)

        generation_status = load_json(generation_status_path) if generation_status_path.exists() else {}
        cycle_status["selected_restart"] = generation_status.get("restart_file")

        if args.dry_run:
            preview_input = generation_status.get("input_file")
            if preview_input is None:
                cycle_status["status"] = "failed_no_generated_input_preview"
                cycle_status["finished_at"] = now_iso()
                cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
                raise SystemExit("Generator dry-run succeeded but no input preview was reported.")
            generated_input = Path(preview_input)
        else:
            generated_input = latest_generated_input(run_dir)
            if generated_input is None:
                cycle_status["status"] = "failed_no_generated_input"
                cycle_status["finished_at"] = now_iso()
                cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
                raise SystemExit("Generator succeeded but no generated input found.")

        cycle_status["generated_input"] = str(generated_input)

    else:
        generated_input = latest_generated_input(run_dir)
        if generated_input is None:
            raise FileNotFoundError("--skip-generate used but no generated input exists.")
        cycle_status["generated_input"] = str(generated_input)
        if generation_status_path.exists():
            cycle_status["selected_restart"] = load_json(generation_status_path).get("restart_file")
        cycle_status["steps"].append({
            "name": "generate_input",
            "skipped": True,
            "input": str(generated_input),
        })

    # ------------------------------------------------------------
    # 5. Optionally run locally
    # ------------------------------------------------------------
    if args.run:
        run_cmd = [
            sys.executable,
            str(runner),
            "--run-dir",
            str(run_dir),
            "--input",
            generated_input.name,
        ]

        if args.np is not None:
            run_cmd += ["--np", str(args.np)]

        rc = run_command(run_cmd, cwd=repo_root)
        cycle_status["steps"].append({
            "name": "local_run",
            "return_code": rc,
        })
        cycle_status["runner_status"] = str(run_dir / "run_status.json")

        if rc != 0:
            cycle_status["status"] = "failed_at_local_run"
            cycle_status["finished_at"] = now_iso()
            cycle_status_path.write_text(json.dumps(cycle_status, indent=2))
            raise SystemExit(rc)

        cycle_status["status"] = "completed_with_run"

    else:
        cycle_status["status"] = "completed_without_run"
        cycle_status["message"] = "Input generated. LAMMPS was not run."

    cycle_status["finished_at"] = now_iso()
    cycle_status_path.write_text(json.dumps(cycle_status, indent=2))

    print(json.dumps({
        "cycle_status": cycle_status["status"],
        "generated_input": cycle_status["generated_input"],
        "decision": str(decision_json),
        "cycle_status_file": str(cycle_status_path),
    }, indent=2))


if __name__ == "__main__":
    main()

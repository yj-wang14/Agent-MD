#!/usr/bin/env python3
"""
Safe cleanup tool for MD-GCMC Agent run directories.

Default mode is dry-run. Nothing is deleted unless --execute is used.

Typical usage:

Dry run:
  python3 mtagent/clean_run_dir.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90

Actually clean:
  python3 mtagent/clean_run_dir.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --execute

More aggressive:
  python3 mtagent/clean_run_dir.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --execute \
    --remove-old-restarts \
    --keep-last-restarts 2

This script protects:
  - monitor_gcmc_*.dat
  - equilibrium_status.json
  - manager_decision.json
  - cycle_status.json
  - case/config-like files
  - latest restart files
  - latest generated input files
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


ALWAYS_PROTECT_NAMES = {
    "equilibrium_status.json",
    "manager_decision.json",
    "cycle_status.json",
    "input_generation_status.json",
    "cleanup_report.json",
    "README.md",
    "AGENTS.md",
    "case.yaml",
}

ALWAYS_PROTECT_PATTERNS = [
    "monitor_gcmc_*.dat",
    "*.yaml",
    "*.yml",
    "*.md",
]

DEFAULT_DELETE_PATTERNS = [
    "*.stdout",
    "*.stderr",
    "dump.*",
    "*.lammpstrj",
    "screen.log",
    "slurm-*.out",
    "*.tmp",
    "*.bak",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def step_number_from_restart(path: Path) -> int:
    """
    Extract trailing numeric timestep from restart file.
    Example:
      restart.gcmc_rh0p90.1600000 -> 1600000
    """
    for token in reversed(path.name.split(".")):
        if token.isdigit():
            return int(token)
    return -1


def segment_index_from_input(path: Path) -> int:
    """
    Extract segment index from input file.
    Example:
      in.gcmc_rh0p90_segment_007 -> 7
    """
    name = path.name
    marker = "segment_"
    if marker not in name:
        return -1
    tail = name.split(marker)[-1]
    if tail.isdigit():
        return int(tail)
    return -1


def collect_by_patterns(run_dir: Path, patterns: List[str]) -> List[Path]:
    files: List[Path] = []
    for pattern in patterns:
        files.extend(run_dir.glob(pattern))
    return sorted(set(p for p in files if p.is_file()))


def latest_restarts(run_dir: Path, keep_last: int) -> List[Path]:
    restarts = sorted(
        [p for p in run_dir.glob("restart.*") if p.is_file()],
        key=step_number_from_restart,
    )
    if keep_last <= 0:
        return []
    return restarts[-keep_last:]


def old_restarts(run_dir: Path, keep_last: int) -> List[Path]:
    restarts = sorted(
        [p for p in run_dir.glob("restart.*") if p.is_file()],
        key=step_number_from_restart,
    )
    if keep_last <= 0:
        return restarts
    return restarts[:-keep_last]


def latest_generated_inputs(run_dir: Path, keep_last: int) -> List[Path]:
    inputs = sorted(
        [p for p in run_dir.glob("in.gcmc_*_segment_*") if p.is_file()],
        key=segment_index_from_input,
    )
    if keep_last <= 0:
        return []
    return inputs[-keep_last:]


def old_generated_inputs(run_dir: Path, keep_last: int) -> List[Path]:
    inputs = sorted(
        [p for p in run_dir.glob("in.gcmc_*_segment_*") if p.is_file()],
        key=segment_index_from_input,
    )
    if keep_last <= 0:
        return inputs
    return inputs[:-keep_last]


def is_protected(path: Path, protected_files: set[Path]) -> bool:
    return path in protected_files or path.name in ALWAYS_PROTECT_NAMES


def human_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def delete_file(path: Path) -> Tuple[bool, str]:
    try:
        path.unlink()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Actually delete files. Default is dry-run.")
    parser.add_argument("--remove-old-restarts", action="store_true")
    parser.add_argument("--keep-last-restarts", type=int, default=2)
    parser.add_argument("--remove-old-inputs", action="store_true")
    parser.add_argument("--keep-last-inputs", type=int, default=2)
    parser.add_argument("--remove-log", action="store_true", help="Also remove log.lammps.")
    parser.add_argument("--remove-run-status", action="store_true", help="Also remove run_status.json.")
    parser.add_argument("--report", type=str, default="cleanup_report.json")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not run_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {run_dir}")

    protected_files: set[Path] = set()

    # Always protect monitor files and core JSON/status files.
    for pattern in ALWAYS_PROTECT_PATTERNS:
        protected_files.update(p.resolve() for p in run_dir.glob(pattern) if p.is_file())

    for name in ALWAYS_PROTECT_NAMES:
        p = run_dir / name
        if p.exists():
            protected_files.add(p.resolve())

    # Protect latest restarts by default.
    protected_files.update(p.resolve() for p in latest_restarts(run_dir, args.keep_last_restarts))

    # Protect latest generated inputs by default.
    protected_files.update(p.resolve() for p in latest_generated_inputs(run_dir, args.keep_last_inputs))

    delete_candidates: set[Path] = set()

    # Default temporary/runtime files.
    for p in collect_by_patterns(run_dir, DEFAULT_DELETE_PATTERNS):
        delete_candidates.add(p.resolve())

    # Optional old restarts.
    if args.remove_old_restarts:
        for p in old_restarts(run_dir, args.keep_last_restarts):
            delete_candidates.add(p.resolve())

    # Optional old generated inputs.
    if args.remove_old_inputs:
        for p in old_generated_inputs(run_dir, args.keep_last_inputs):
            delete_candidates.add(p.resolve())

    # Optional log.
    if args.remove_log:
        p = run_dir / "log.lammps"
        if p.exists():
            delete_candidates.add(p.resolve())

    # Optional run status.
    if args.remove_run_status:
        p = run_dir / "run_status.json"
        if p.exists():
            delete_candidates.add(p.resolve())

    # Never delete protected files.
    final_candidates = []
    protected_skipped = []
    for p in sorted(delete_candidates):
        if is_protected(p, protected_files):
            protected_skipped.append(str(p))
        else:
            final_candidates.append(p)

    deleted = []
    failed = []
    total_bytes = sum(human_size(p) for p in final_candidates)

    if args.execute:
        for p in final_candidates:
            ok, err = delete_file(p)
            if ok:
                deleted.append(str(p))
            else:
                failed.append({"file": str(p), "error": err})

    report: Dict = {
        "status": "executed" if args.execute else "dry_run",
        "created_at": now_iso(),
        "run_dir": str(run_dir),
        "execute": args.execute,
        "options": {
            "remove_old_restarts": args.remove_old_restarts,
            "keep_last_restarts": args.keep_last_restarts,
            "remove_old_inputs": args.remove_old_inputs,
            "keep_last_inputs": args.keep_last_inputs,
            "remove_log": args.remove_log,
            "remove_run_status": args.remove_run_status,
        },
        "n_candidates": len(final_candidates),
        "total_candidate_bytes": total_bytes,
        "candidate_files": [str(p) for p in final_candidates],
        "protected_skipped": protected_skipped,
        "deleted_files": deleted,
        "failed": failed,
        "protected_files": sorted(str(p) for p in protected_files),
    }

    report_path = run_dir / args.report
    report_path.write_text(json.dumps(report, indent=2))

    print(json.dumps({
        "status": report["status"],
        "run_dir": report["run_dir"],
        "n_candidates": report["n_candidates"],
        "total_candidate_MB": round(total_bytes / 1024 / 1024, 3),
        "report": str(report_path),
        "execute_to_delete": "add --execute" if not args.execute else "already executed",
    }, indent=2))

    if not args.execute and final_candidates:
        print("\nFiles that would be deleted:")
        for p in final_candidates:
            print("  ", p)


if __name__ == "__main__":
    main()

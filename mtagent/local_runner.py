#!/usr/bin/env python3
"""
Local runner for MD-GCMC Agent.

Function:
  - run one LAMMPS input locally
  - record command, start/end time, return code, stdout/stderr paths
  - write run_status.json

Usage:
  python3 mtagent/local_runner.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --input in.gcmc_rh0p90_segment_001 \
    --np 16

Dry run:
  python3 mtagent/local_runner.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --input in.gcmc_rh0p90_segment_001 \
    --np 16 \
    --dry-run
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_case_yaml(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}

    try:
        import yaml  # type: ignore
    except ImportError:
        print("WARNING: PyYAML not installed. Using command-line/default runner settings.")
        return {}

    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_nested(cfg: Dict[str, Any], keys: list[str], default: Any) -> Any:
    x: Any = cfg
    for k in keys:
        if not isinstance(x, dict) or k not in x:
            return default
        x = x[k]
    return x


def build_command(
    case_cfg: Dict[str, Any],
    np: int | None,
    input_file: str,
    no_mpi: bool,
) -> List[str]:
    lammps_command = str(get_nested(case_cfg, ["local", "lammps_command"], "lmp"))
    mpi_command = str(get_nested(case_cfg, ["local", "mpi_command"], "mpirun"))
    default_np = int(get_nested(case_cfg, ["local", "default_np"], 16))

    if np is None:
        np = default_np

    if no_mpi:
        return [lammps_command, "-in", input_file]

    return [mpi_command, "-np", str(np), lammps_command, "-in", input_file]


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input", type=str, required=True, help="LAMMPS input file name inside run-dir")
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--np", type=int, default=None)
    parser.add_argument("--no-mpi", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", type=str, default="run_status.json")
    parser.add_argument("--stdout", type=str, default=None)
    parser.add_argument("--stderr", type=str, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    input_path = run_dir / args.input
    if not input_path.exists():
        raise FileNotFoundError(f"LAMMPS input not found: {input_path}")

    case_cfg = load_case_yaml(args.case)
    command = build_command(
        case_cfg=case_cfg,
        np=args.np,
        input_file=args.input,
        no_mpi=args.no_mpi,
    )

    stdout_name = args.stdout or f"{Path(args.input).name}.stdout"
    stderr_name = args.stderr or f"{Path(args.input).name}.stderr"

    stdout_path = run_dir / stdout_name
    stderr_path = run_dir / stderr_name
    status_path = run_dir / args.status

    status: Dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "running",
        "run_dir": str(run_dir),
        "input": args.input,
        "command": command,
        "command_string": " ".join(shlex.quote(x) for x in command),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "started_at": now_iso(),
        "finished_at": None,
        "elapsed_seconds": None,
        "return_code": None,
    }

    write_json(status_path, status)

    print("Run directory:", run_dir)
    print("Command:", status["command_string"])
    print("Status file:", status_path)

    if args.dry_run:
        print("Dry run only. No command executed.")
        return

    t0 = time.time()

    with stdout_path.open("w") as fout, stderr_path.open("w") as ferr:
        proc = subprocess.run(
            command,
            cwd=run_dir,
            stdout=fout,
            stderr=ferr,
            text=True,
        )

    elapsed = time.time() - t0

    status["finished_at"] = now_iso()
    status["elapsed_seconds"] = elapsed
    status["return_code"] = proc.returncode

    if proc.returncode == 0:
        status["status"] = "completed"
    else:
        status["status"] = "failed"

    # Basic post-run diagnostics.
    log_path = run_dir / "log.lammps"
    status["log_lammps_exists"] = log_path.exists()

    if log_path.exists():
        try:
            tail_lines = log_path.read_text(errors="ignore").splitlines()[-80:]
            tail_text = "\n".join(tail_lines)
            status["error_keywords_found"] = [
                kw for kw in [
                    "ERROR",
                    "Lost atoms",
                    "Out of range atoms",
                    "SHAKE",
                    "nan",
                    "NaN",
                    "Segmentation",
                    "killed",
                ]
                if kw.lower() in tail_text.lower()
            ]
        except Exception as exc:
            status["log_read_error"] = str(exc)

    write_json(status_path, status)

    print(json.dumps({
        "status": status["status"],
        "return_code": status["return_code"],
        "elapsed_seconds": round(elapsed, 2),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "status_file": str(status_path),
        "error_keywords_found": status.get("error_keywords_found", []),
    }, indent=2))

    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Archive an equilibrated RH state for later campaign steps."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mtagent.generate_gcmc_input import rh_from_dir, rh_to_tag


MONITOR_COLUMNS = [
    "step",
    "nwater_total",
    "nwater_inter",
    "nwater_bottom",
    "nwater_top",
    "nwater_ext",
    "basal_proxy",
    "zcenter",
    "iacc",
    "dacc",
    "tacc",
    "racc",
    "temp",
    "pe",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    return json.loads(path.read_text())


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def latest_monitor_row(path: Path) -> dict[str, float]:
    if not path.exists():
        raise FileNotFoundError(f"Monitor file not found: {path}")

    for line in reversed(path.read_text(errors="ignore").splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        values = stripped.split()
        if len(values) < len(MONITOR_COLUMNS):
            raise ValueError(f"Monitor row has too few columns: {stripped}")
        return {key: float(value) for key, value in zip(MONITOR_COLUMNS, values)}

    raise ValueError(f"No data rows found in monitor file: {path}")


def preferred_json(run_dir: Path, stem: str) -> Path:
    preview = run_dir / f"{stem}.preview.json"
    formal = run_dir / f"{stem}.json"

    if preview.exists():
        if stem == "equilibrium_status":
            try:
                if load_json(preview).get("status") == "equilibrated":
                    return preview
            except (OSError, json.JSONDecodeError):
                pass
        else:
            return preview

    if formal.exists():
        return formal

    if preview.exists():
        return preview

    raise FileNotFoundError(f"Neither {preview.name} nor {formal.name} exists in {run_dir}")


def restart_step_number(path: Path) -> int:
    for token in reversed(path.name.split(".")):
        if token.isdigit():
            return int(token)
    return -1


def select_restart(run_dir: Path, rh_tag: str, final_step: int | None) -> Path:
    if final_step is not None:
        exact = run_dir / f"restart.gcmc_{rh_tag}.{final_step}"
        if exact.exists():
            return exact

    numeric = sorted(
        (p for p in run_dir.glob(f"restart.gcmc_{rh_tag}.*") if p.is_file() and restart_step_number(p) >= 0),
        key=restart_step_number,
    )
    if numeric:
        return numeric[-1]

    final = run_dir / f"restart.gcmc_{rh_tag}.final"
    if final.exists():
        return final

    raise FileNotFoundError(f"No restart.gcmc_{rh_tag}.<step> or restart.gcmc_{rh_tag}.final found in {run_dir}")


def final_window_slopes(equilibrium: dict[str, Any]) -> dict[str, Any]:
    series = equilibrium.get("series", {})
    if not isinstance(series, dict):
        return {}

    slopes: dict[str, Any] = {}
    for name, values in series.items():
        if not isinstance(values, dict) or "slope_per_100k" not in values:
            continue
        entry: dict[str, Any] = {"slope_per_100k": values["slope_per_100k"]}
        for limit_key in ("slope_limit_per_100k", "slope_limit_A_per_100k"):
            if limit_key in values:
                entry[limit_key] = values[limit_key]
        slopes[name] = entry
    return slopes


def copy_artifact(src: Path, dest_dir: Path) -> Path:
    if not src.exists():
        raise FileNotFoundError(f"Archive artifact not found: {src}")
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return dest


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    slopes = summary.get("final_window_slopes", {})
    slope_lines = []
    if isinstance(slopes, dict):
        for name in ("nwater_total", "nwater_inter", "nwater_ext", "basal_proxy"):
            values = slopes.get(name)
            if not isinstance(values, dict):
                continue
            slope_lines.append(f"- {name}: {values.get('slope_per_100k')}")

    text = [
        f"# RH {summary['rh']} Equilibrated State",
        "",
        f"- Archived at: {summary['timestamp']}",
        f"- Final step: {summary['final_step']}",
        f"- Total water: {summary['total_water']}",
        f"- Interlayer water: {summary['interlayer_water']}",
        f"- External water: {summary['external_water']}",
        f"- Basal proxy: {summary['basal_proxy']}",
        f"- Analysis status: {summary.get('analysis_status', summary.get('equilibrium_status'))}",
        f"- Analysis recommendation: {summary.get('analysis_recommendation', summary.get('equilibrium_recommendation'))}",
        f"- Source restart: {summary['source_restart']}",
        f"- Archived restart: {summary['archived_restart']}",
        f"- Selected restart: {summary['selected_restart']}",
        "",
        "## Final-Window Slopes",
        *slope_lines,
        "",
        "## Warnings / Errors",
    ]

    warnings = summary.get("warnings_errors", {})
    if isinstance(warnings, dict) and warnings:
        for key, value in warnings.items():
            text.append(f"- {key}: {value}")
    else:
        text.append("- None recorded")

    path.write_text("\n".join(text) + "\n")


def build_summary(
    *,
    rh: float,
    run_dir: Path,
    archive_dir: Path,
    monitor_path: Path,
    equilibrium_path: Path,
    manager_path: Path,
    restart_path: Path,
    run_status_path: Path,
) -> dict[str, Any]:
    monitor = latest_monitor_row(monitor_path)
    equilibrium = load_json(equilibrium_path)
    manager = load_json(manager_path)
    run_status = load_json(run_status_path) if run_status_path.exists() else {}

    warnings_errors = {
        "manager_warnings": manager.get("warnings", []),
        "run_error_keywords_found": run_status.get("error_keywords_found", []),
        "run_status": run_status.get("status"),
        "run_return_code": run_status.get("return_code"),
    }

    return {
        "timestamp": now_iso(),
        "rh": rh,
        "run_dir": repo_relative(run_dir),
        "archive_dir": repo_relative(archive_dir),
        "final_step": int(monitor["step"]),
        "total_water": int(monitor["nwater_total"]),
        "interlayer_water": int(monitor["nwater_inter"]),
        "external_water": int(monitor["nwater_ext"]),
        "basal_proxy": monitor["basal_proxy"],
        "final_window_slopes": final_window_slopes(equilibrium),
        "equilibrium_status": equilibrium.get("status"),
        "equilibrium_recommendation": equilibrium.get("recommendation"),
        "manager_action": manager.get("action"),
        "source_restart": repo_relative(restart_path),
        "archived_restart": repo_relative(archive_dir / restart_path.name),
        "selected_restart": repo_relative(archive_dir / restart_path.name),
        "warnings_errors": warnings_errors,
    }


def archive_rh_result(
    run_dir: Path,
    archive_dir: Path | None = None,
    rh: float | None = None,
    summary_only: bool = False,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    rh_value = rh if rh is not None else rh_from_dir(run_dir)
    rh_tag = rh_to_tag(rh_value)
    if archive_dir is None:
        archive_dir = run_dir.parent / "states" / f"rh_{rh_value:.2f}".replace(".", "p")
    archive_dir = archive_dir.resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)

    monitor_path = run_dir / f"monitor_gcmc_{rh_tag}.dat"
    equilibrium_path = preferred_json(run_dir, "equilibrium_status")
    manager_path = preferred_json(run_dir, "manager_decision")
    initial_status_path = run_dir / "initial_status.json"
    cycle_status_path = run_dir / "cycle_status.json"
    run_status_path = run_dir / "run_status.json"

    final_step = int(latest_monitor_row(monitor_path)["step"])
    restart_path = select_restart(run_dir, rh_tag, final_step)

    artifacts = [
        restart_path,
        monitor_path,
        equilibrium_path,
        manager_path,
        initial_status_path,
        cycle_status_path,
        run_status_path,
    ]
    if summary_only:
        copied = [archive_dir / path.name for path in artifacts if (archive_dir / path.name).exists()]
    else:
        copied = [copy_artifact(path, archive_dir) for path in artifacts]

    summary = build_summary(
        rh=rh_value,
        run_dir=run_dir,
        archive_dir=archive_dir,
        monitor_path=monitor_path,
        equilibrium_path=equilibrium_path,
        manager_path=manager_path,
        restart_path=restart_path,
        run_status_path=run_status_path,
    )
    summary["archived_files"] = [repo_relative(path) for path in copied]

    write_json(archive_dir / "summary.json", summary)
    write_summary_md(archive_dir / "summary.md", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--rh", type=float, default=None)
    parser.add_argument("--summary-only", action="store_true", help="Regenerate summary files without copying artifacts.")
    args = parser.parse_args()

    summary = archive_rh_result(args.run_dir, args.archive_dir, args.rh, summary_only=args.summary_only)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

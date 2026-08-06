#!/usr/bin/env python3
"""Summarize archived RH states and optional run directories for a case."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mtagent.generate_gcmc_input import rh_from_dir, rh_to_tag


FIELDS = [
    "case_id",
    "rh",
    "status",
    "final_step",
    "total_water",
    "interlayer_water",
    "external_water",
    "basal_proxy",
    "equilibrium_status",
    "manager_action",
    "selected_restart",
    "nwater_total_slope_per_100k",
    "nwater_inter_slope_per_100k",
    "nwater_ext_slope_per_100k",
    "basal_proxy_slope_per_100k",
    "warnings",
    "errors",
    "updated_at",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def repo_relative(path_value: Any) -> str:
    if path_value in (None, ""):
        return ""
    path = Path(str(path_value))
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_case_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"case.yaml not found: {path}")
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read case.yaml") from exc
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def case_id(case_cfg: dict[str, Any], out_dir: Path) -> str:
    case_cfg_section = case_cfg.get("case", {})
    if isinstance(case_cfg_section, dict) and case_cfg_section.get("name"):
        return str(case_cfg_section["name"])
    return out_dir.name


def default_out_dir(case_cfg: dict[str, Any], case_path: Path) -> Path:
    paths = case_cfg.get("paths", {})
    if isinstance(paths, dict) and paths.get("example_dir"):
        return resolve_path(paths["example_dir"], case_path.parent)
    return resolve_path("examples/Mt_Oct050_Na", case_path.parent)


def slope(summary: dict[str, Any], name: str) -> Any:
    slopes = summary.get("final_window_slopes", {})
    if not isinstance(slopes, dict):
        return None
    values = slopes.get(name, {})
    if not isinstance(values, dict):
        return None
    return values.get("slope_per_100k")


def join_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def warnings_and_errors(summary: dict[str, Any]) -> tuple[str, str]:
    warnings_errors = summary.get("warnings_errors", {})
    if not isinstance(warnings_errors, dict):
        return "", ""

    warnings = []
    manager_warnings = warnings_errors.get("manager_warnings")
    if isinstance(manager_warnings, list):
        warnings.extend(str(item) for item in manager_warnings)
    elif manager_warnings:
        warnings.append(str(manager_warnings))

    errors = []
    run_errors = warnings_errors.get("run_error_keywords_found")
    if isinstance(run_errors, list):
        errors.extend(str(item) for item in run_errors)
    elif run_errors:
        errors.append(str(run_errors))

    return "; ".join(warnings), "; ".join(errors)


def row_from_summary(summary_path: Path, case_name: str) -> dict[str, Any]:
    summary = load_json(summary_path)
    warnings, errors = warnings_and_errors(summary)
    selected_restart = (
        summary.get("archived_restart")
        or summary.get("selected_restart")
        or summary.get("selected_restart_path")
        or summary.get("source_restart")
    )
    return {
        "case_id": case_name,
        "rh": summary.get("rh"),
        "status": "archived",
        "final_step": summary.get("final_step"),
        "total_water": summary.get("total_water"),
        "interlayer_water": summary.get("interlayer_water"),
        "external_water": summary.get("external_water"),
        "basal_proxy": summary.get("basal_proxy"),
        "equilibrium_status": summary.get("equilibrium_status"),
        "manager_action": summary.get("manager_action"),
        "selected_restart": repo_relative(selected_restart),
        "nwater_total_slope_per_100k": slope(summary, "nwater_total"),
        "nwater_inter_slope_per_100k": slope(summary, "nwater_inter"),
        "nwater_ext_slope_per_100k": slope(summary, "nwater_ext"),
        "basal_proxy_slope_per_100k": slope(summary, "basal_proxy"),
        "warnings": warnings,
        "errors": errors,
        "updated_at": summary.get("timestamp"),
    }


def row_from_run_dir(run_dir: Path, case_name: str) -> dict[str, Any]:
    rh = rh_from_dir(run_dir)
    tag = rh_to_tag(rh)
    monitor = run_dir / f"monitor_gcmc_{tag}.dat"
    final_step = None
    if monitor.exists():
        for line in reversed(monitor.read_text(errors="ignore").splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if parts:
                final_step = int(float(parts[0]))
            break

    equilibrium = {}
    for candidate in (run_dir / "equilibrium_status.preview.json", run_dir / "equilibrium_status.json"):
        if candidate.exists():
            equilibrium = load_json(candidate)
            break

    manager = {}
    for candidate in (run_dir / "manager_decision.preview.json", run_dir / "manager_decision.json"):
        if candidate.exists():
            manager = load_json(candidate)
            break

    restarts = sorted(
        (p for p in run_dir.glob(f"restart.gcmc_{tag}.*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )

    return {
        "case_id": case_name,
        "rh": rh,
        "status": "run_dir",
        "final_step": final_step,
        "total_water": None,
        "interlayer_water": None,
        "external_water": None,
        "basal_proxy": None,
        "equilibrium_status": equilibrium.get("status"),
        "manager_action": manager.get("action"),
        "selected_restart": repo_relative(restarts[-1]) if restarts else "",
        "nwater_total_slope_per_100k": None,
        "nwater_inter_slope_per_100k": None,
        "nwater_ext_slope_per_100k": None,
        "basal_proxy_slope_per_100k": None,
        "warnings": join_value(manager.get("warnings")),
        "errors": "",
        "updated_at": now_iso(),
    }


def collect_rows(out_dir: Path, case_name: str, run_dirs: list[Path]) -> list[dict[str, Any]]:
    rows = []
    states_dir = out_dir / "states"
    if states_dir.exists():
        for summary_path in sorted(states_dir.glob("rh_*/summary.json")):
            rows.append(row_from_summary(summary_path, case_name))

    archived_rh = {row.get("rh") for row in rows}
    for run_dir in run_dirs:
        row = row_from_run_dir(run_dir.resolve(), case_name)
        if row.get("rh") not in archived_rh:
            rows.append(row)

    return sorted(rows, key=lambda row: float(row["rh"]) if row.get("rh") is not None else -1.0, reverse=True)


def csv_value(value: Any) -> str:
    return "" if value is None else str(value)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in FIELDS})


def write_json(path: Path, rows: list[dict[str, Any]], case_name: str, out_dir: Path) -> None:
    payload = {
        "case_id": case_name,
        "out_dir": repo_relative(out_dir),
        "updated_at": now_iso(),
        "count": len(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_markdown(path: Path, rows: list[dict[str, Any]], case_name: str) -> None:
    headers = FIELDS
    lines = [
        f"# Campaign Status: {case_name}",
        "",
        f"Updated at: {now_iso()}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(csv_value(row.get(field)) for field in headers) + " |")
    path.write_text("\n".join(lines) + "\n")


def generate_campaign_status(case_path: Path, out_dir: Path | None = None, run_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    case_path = case_path.resolve()
    case_cfg = load_case_yaml(case_path)
    target_out_dir = out_dir.resolve() if out_dir is not None else default_out_dir(case_cfg, case_path)
    target_out_dir.mkdir(parents=True, exist_ok=True)
    name = case_id(case_cfg, target_out_dir)
    rows = collect_rows(target_out_dir, name, run_dirs or [])

    write_csv(target_out_dir / "campaign_status.csv", rows)
    write_markdown(target_out_dir / "campaign_status.md", rows, name)
    write_json(target_out_dir / "campaign_status.json", rows, name, target_out_dir)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--run-dir", type=Path, action="append", default=[])
    args = parser.parse_args()

    rows = generate_campaign_status(args.case, args.out_dir, args.run_dir)
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()

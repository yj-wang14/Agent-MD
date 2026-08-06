#!/usr/bin/env python3
"""Lightweight diagnostics for LAMMPS log/stdout/stderr files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FATAL_PATTERNS: list[tuple[str, str]] = [
    ("ERROR", r"\bERROR\b"),
    ("Lost atoms", r"Lost atoms"),
    ("PPPM out of range", r"Out of range atoms|PPPM.*out.of.range|out.of.range.*PPPM"),
    ("SHAKE failure", r"SHAKE.*(fail|missing|error)|Shake atoms missing"),
    ("NaN", r"\b(?:nan|NaN|NAN)\b"),
]

KNOWN_WARNING_PATTERNS: list[tuple[str, str]] = [
    (
        "kspace_neighbor_exclusion",
        r"Neighbor exclusions used with KSpace solver may give inconsistent Coulombic energies",
    ),
    ("net_charge", r"System is not charge neutral|net charge"),
    ("nve_limit_shake", r"Using fix nve/limit with SHAKE|nve/limit.*SHAKE|SHAKE.*nve/limit"),
    ("gcmc_full_energy", r"fix gcmc.*full_energy|full_energy option"),
]


def read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(errors="ignore")


def dangerous_builds(text: str) -> int | None:
    matches = re.findall(r"Dangerous builds\s*=\s*(\d+)", text, flags=re.IGNORECASE)
    if matches:
        return int(matches[-1])
    matches = re.findall(r"(\d+)\s+dangerous builds", text, flags=re.IGNORECASE)
    if matches:
        return int(matches[-1])
    return None


def diagnose_text(text: str, *, expected_files: list[Path] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    known_warnings: list[str] = []

    for label, pattern in FATAL_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            errors.append(label)

    for label, pattern in KNOWN_WARNING_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            known_warnings.append(label)

    db = dangerous_builds(text)
    if db is not None and db > 0:
        warnings.append(f"Dangerous builds = {db}")

    missing_outputs: list[str] = []
    for path in expected_files or []:
        if not path.exists():
            missing_outputs.append(str(path))
    if missing_outputs:
        errors.append("missing expected output files")

    status = "failed" if errors else "warning" if warnings or known_warnings else "ok"
    if status == "failed":
        recommendation = "Stop and inspect LAMMPS failure before continuing."
    elif status == "warning":
        recommendation = "Run completed with warnings; review before production use."
    else:
        recommendation = "No failure signatures detected."
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "known_warnings": known_warnings,
        "dangerous_builds": db,
        "missing_outputs": missing_outputs,
        "recommendation": recommendation,
    }


def diagnose_files(paths: list[Path], *, expected_files: list[Path] | None = None) -> dict[str, Any]:
    existing = [path for path in paths if path.exists() and path.is_file()]
    text = "\n".join(read_text(path) for path in existing)
    result = diagnose_text(text, expected_files=expected_files)
    result["input_files"] = [str(path) for path in paths]
    result["files_read"] = [str(path) for path in existing]
    return result


def is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


def parse_monitor_table(path: Path) -> tuple[list[str], list[list[float]], list[str]]:
    warnings: list[str] = []
    if not path.exists():
        return [], [], [f"Missing monitor file: {path}"]
    rows: list[list[float]] = []
    for line in path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        try:
            rows.append([float(part) for part in parts])
        except ValueError:
            warnings.append(f"Skipped non-numeric monitor line: {stripped[:80]}")
    if not rows:
        return [], [], warnings + ["Monitor file contains no numeric rows"]
    # fix ave/time output columns: timestep plus 13 monitored values.
    columns = [
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
    if len(rows[0]) < len(columns):
        return columns[: len(rows[0])], rows, warnings + ["water partition columns missing"]
    return columns, rows, warnings


def summarize_gcmc_monitor(path: Path) -> dict[str, Any]:
    columns, rows, parse_warnings = parse_monitor_table(path)
    errors: list[str] = []
    warnings: list[str] = list(parse_warnings)
    required = ["nwater_total", "nwater_inter", "nwater_ext", "basal_proxy"]
    missing = [name for name in required if name not in columns]
    if missing:
        errors.append(f"Missing monitor columns: {missing}")
    if not rows:
        return {"errors": errors or ["missing monitor data"], "warnings": warnings}
    first = dict(zip(columns, rows[0]))
    last = dict(zip(columns, rows[-1]))
    for name in required:
        if name in first and (not is_finite(first[name]) or not is_finite(last[name])):
            errors.append(f"Non-finite {name} in monitor")
    initial_basal = first.get("basal_proxy")
    final_basal = last.get("basal_proxy")
    large_initial_relaxation = False
    if initial_basal is not None and final_basal is not None and is_finite(initial_basal) and is_finite(final_basal):
        large_initial_relaxation = abs(float(final_basal) - float(initial_basal)) > 10.0
        if large_initial_relaxation:
            warnings.append("basal_proxy_large_initial_relaxation")
    summary = {
        "initial_step": first.get("step"),
        "final_step": last.get("step"),
        "initial_total_water": first.get("nwater_total"),
        "final_total_water": last.get("nwater_total"),
        "initial_interlayer_water": first.get("nwater_inter"),
        "final_interlayer_water": last.get("nwater_inter"),
        "initial_external_water": first.get("nwater_ext"),
        "final_external_water": last.get("nwater_ext"),
        "initial_basal_proxy": initial_basal,
        "basal_proxy_initial_raw": initial_basal,
        "final_basal_proxy": final_basal,
        "basal_proxy_final": final_basal,
        "basal_proxy_large_initial_relaxation": large_initial_relaxation,
        "initial_iacc": first.get("iacc"),
        "final_iacc": last.get("iacc"),
        "initial_dacc": first.get("dacc"),
        "final_dacc": last.get("dacc"),
        "initial_tacc": first.get("tacc"),
        "final_tacc": last.get("tacc"),
        "initial_racc": first.get("racc"),
        "final_racc": last.get("racc"),
        "rows": len(rows),
        "columns": columns,
        "errors": errors,
        "warnings": warnings,
    }
    return summary


def thermo_column_values(text: str, column_name: str) -> list[float]:
    values: list[float] = []
    column_index: int | None = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "Step" and column_name in parts:
            column_index = parts.index(column_name)
            continue
        if column_index is None or len(parts) <= column_index:
            continue
        try:
            # Thermo data rows start with a numeric timestep.
            float(parts[0])
            values.append(float(parts[column_index]))
        except ValueError:
            continue
    return values


def diagnose_gcmc_run(
    *,
    log_paths: list[Path],
    monitor_path: Path,
    expected_files: list[Path],
    status_json: Path | None = None,
    expected_ion_count: int | None = None,
) -> dict[str, Any]:
    result = diagnose_files(log_paths, expected_files=expected_files)
    errors = list(result.get("errors", []))
    warnings = list(result.get("warnings", []))
    status_doc: dict[str, Any] = {}
    if status_json and status_json.exists():
        try:
            status_doc = json.loads(status_json.read_text())
        except json.JSONDecodeError:
            errors.append(f"Unable to parse status JSON: {status_json}")
    elif status_json is not None:
        warnings.append(f"Missing status JSON: {status_json}")

    monitor_summary = summarize_gcmc_monitor(monitor_path)
    errors.extend(monitor_summary.get("errors", []))
    warnings.extend(monitor_summary.get("warnings", []))

    ion_summary: dict[str, Any] = {"expected_ion_count": expected_ion_count, "observed_initial": None, "observed_final": None}
    text = "\n".join(read_text(path) for path in log_paths if path.exists())
    values = thermo_column_values(text, "v_nexchangeable_ions")
    if values:
        ion_summary["observed_initial"] = values[0]
        ion_summary["observed_final"] = values[-1]
    else:
        matches = re.findall(r"v_nexchangeable_ions\s*=\s*([0-9.+-eE]+)", text)
        if matches:
            ion_summary["observed_final"] = float(matches[-1])
            ion_summary["observed_initial"] = float(matches[0])
    if expected_ion_count is not None and ion_summary["observed_final"] is not None:
        if int(round(float(ion_summary["observed_final"]))) != int(expected_ion_count):
            errors.append(
                f"Exchangeable ion count changed: expected {expected_ion_count}, observed {ion_summary['observed_final']}"
            )

    if status_doc.get("status") and status_doc.get("status") != "completed":
        errors.append(f"initial_status is {status_doc.get('status')}")
    if status_doc.get("missing_outputs"):
        errors.append(f"initial_status missing outputs: {status_doc.get('missing_outputs')}")
    if status_doc.get("final_restart"):
        ion_summary["final_restart"] = status_doc.get("final_restart")

    result["errors"] = errors
    result["warnings"] = warnings
    result["water_summary"] = monitor_summary
    result["ion_summary"] = ion_summary
    result["initial_status"] = status_doc.get("status")
    result["status"] = "failed" if errors else "warning" if warnings or result.get("known_warnings") else "ok"
    if result["status"] == "failed":
        result["recommendation"] = "Stop and inspect GCMC failure before continuing."
    elif result["status"] == "warning":
        result["recommendation"] = "GCMC completed with warnings; review before continuation."
    else:
        result["recommendation"] = "No GCMC failure signatures detected."
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose LAMMPS log/stdout/stderr files.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--expect", action="append", default=[], type=Path, help="Expected output file path.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = diagnose_files(args.paths, expected_files=args.expect)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare authoritative accepted-state trajectory data for Figures 6 and 7."""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "paper_artifacts/final_campaign/authoritative_manifest.csv"
OUTPUT_DIR = ROOT / "paper_artifacts/final_campaign/figure_source_data"
SYSTEM_LABELS = {
    "Mt_Na_LC030_N12": "Na-LC0.30",
    "Mt_Na_LC040_N16": "Na-LC0.40",
    "Mt_Na_LC050_N20": "Na-LC0.50",
    "Mt_K_LC040_N16": "K-LC0.40",
    "Mt_Ca_LC040_N8": "Ca-LC0.40",
}
FIG6_SYSTEMS = ("Na-LC0.40", "K-LC0.40", "Ca-LC0.40")
FIG7_SYSTEMS = ("Na-LC0.30", "Na-LC0.40", "Na-LC0.50")
RH_ORDER = (0.90, 0.30, 0.10)
OUTPUT_FIELDS = (
    "system",
    "RH",
    "rh_local_step",
    "total_water",
    "interlayer_water",
    "external_water",
    "basal_spacing",
)
MONITOR_FIELDS = {
    "TimeStep": "step",
    "v_nwater_mol": "total_water",
    "v_nwat_inter": "interlayer_water",
    "v_nwat_ext": "external_water",
    "v_basal_proxy": "basal_spacing",
}


def read_manifest() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = {(system_id, rh) for system_id in SYSTEM_LABELS for rh in RH_ORDER}
    observed = {(row["system_id"], float(row["RH"])) for row in rows}
    if observed != expected:
        raise ValueError("The authoritative manifest does not contain exactly the expected 15 system--RH states")
    return rows


def parse_monitor(path: Path) -> tuple[list[str], list[list[str]]]:
    columns: list[str] | None = None
    rows: list[list[str]] = []
    for line in path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if "TimeStep" in stripped and "v_nwater_mol" in stripped:
                columns = stripped.lstrip("#").split()
            continue
        if columns is None:
            continue
        values = stripped.split()
        if len(values) == len(columns):
            rows.append(values)
    if columns is None or not rows:
        raise ValueError(f"No recognized monitor data in {path}")
    missing = set(MONITOR_FIELDS) - set(columns)
    if missing:
        raise ValueError(f"Missing columns in {path}: {sorted(missing)}")
    return columns, rows


def state_trajectory(manifest_row: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, object]]:
    relative_monitor = Path(manifest_row["source_monitor_file"])
    if "states" not in relative_monitor.parts:
        raise ValueError(f"Monitor is not in an accepted-state archive: {relative_monitor}")
    monitor = ROOT / relative_monitor
    columns, raw_rows = parse_monitor(monitor)
    indices = {output: columns.index(source) for source, output in MONITOR_FIELDS.items()}
    rh_start = int(manifest_row["RH_start_step"])
    final_step = int(manifest_row["final_absolute_step"])
    calculated_local_steps = final_step - rh_start
    manifest_local_steps = int(manifest_row["elapsed_steps_within_current_RH"])
    if not math.isclose(calculated_local_steps, manifest_local_steps, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(
            f"RH-local step mismatch for {manifest_row['system_id']} RH {float(manifest_row['RH']):.2f}: "
            f"final_absolute_step ({final_step}) - RH_start_step ({rh_start}) "
            f"= {calculated_local_steps}, but manifest elapsed_steps_within_current_RH "
            f"= {manifest_local_steps}"
        )

    # Dictionary assignment deliberately retains the last occurrence of a
    # repeated timestep, matching analyze_gcmc_equilibrium_restart.py.
    by_step: dict[int, list[str]] = {}
    for values in raw_rows:
        step = int(float(values[indices["step"]]))
        if step <= final_step:
            by_step[step] = values

    system = SYSTEM_LABELS[manifest_row["system_id"]]
    rh = float(manifest_row["RH"])
    prepared: list[dict[str, object]] = []
    for step in sorted(by_step):
        if step < rh_start:
            raise ValueError(f"Monitor timestep precedes RH start for {system} RH {rh:.2f}: {step}")
        values = by_step[step]
        row = {
            "system": system,
            "RH": f"{rh:.2f}",
            "rh_local_step": step - rh_start,
            "total_water": values[indices["total_water"]],
            "interlayer_water": values[indices["interlayer_water"]],
            "external_water": values[indices["external_water"]],
            "basal_spacing": values[indices["basal_spacing"]],
        }
        total = float(row["total_water"])
        partitioned = float(row["interlayer_water"]) + float(row["external_water"])
        if abs(total - partitioned) > 1e-8:
            raise ValueError(f"Water partition mismatch for {system} RH {rh:.2f} at step {step}")
        prepared.append(row)

    if not prepared or prepared[-1]["rh_local_step"] != calculated_local_steps:
        raise ValueError(f"Trajectory does not end at the authoritative timestep for {system} RH {rh:.2f}")
    validation = {
        "system": system,
        "RH": f"{rh:.2f}",
        "points": len(prepared),
        "maximum_rh_local_step": prepared[-1]["rh_local_step"],
        "final_water": prepared[-1]["total_water"],
        "final_basal_spacing": prepared[-1]["basal_spacing"],
        "source_monitor_file": str(relative_monitor),
    }
    return prepared, validation


def write_dataset(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trajectories: dict[tuple[str, float], list[dict[str, object]]] = {}
    validations: dict[tuple[str, float], dict[str, object]] = {}
    for manifest_row in read_manifest():
        trajectory, validation = state_trajectory(manifest_row)
        key = (validation["system"], float(validation["RH"]))
        trajectories[key] = trajectory
        validations[key] = validation

    for filename, systems in (
        ("fig6_cation_trajectory.csv", FIG6_SYSTEMS),
        ("fig7_layer_charge_trajectory.csv", FIG7_SYSTEMS),
    ):
        output_rows = [row for system in systems for rh in RH_ORDER for row in trajectories[(system, rh)]]
        write_dataset(OUTPUT_DIR / filename, output_rows)
        print(f"{filename}: {len(output_rows)} trajectory points")
        for system in systems:
            for rh in RH_ORDER:
                item = validations[(system, rh)]
                print(
                    f"  {item['system']} RH {item['RH']}: points={item['points']}, "
                    f"max_rh_local_step={item['maximum_rh_local_step']}, "
                    f"final_water={item['final_water']}, final_basal_spacing={item['final_basal_spacing']}, "
                    f"source={item['source_monitor_file']}"
                )


if __name__ == "__main__":
    main()

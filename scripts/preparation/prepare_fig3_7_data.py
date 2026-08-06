#!/usr/bin/env python3
"""Build validated Figure 3--7 source tables from final campaign records.

This script does not draw figures. Scientific observables are final-window means
from accepted archive monitor files, as consolidated in fig3_campaign_outputs.csv.
Acceptance status and production effort are verified against the authoritative
campaign manifest before any derived CSV is written.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "paper_artifacts/final_campaign/figure_source_data"
SCIENCE_SOURCE = DATA_DIR / "fig3_campaign_outputs.csv"
MANIFEST_SOURCE = ROOT / "paper_artifacts/final_campaign/authoritative_manifest.csv"
RH_ORDER = (0.90, 0.30, 0.10)
SYSTEM_ORDER = (
    "Mt_Na_LC030_N12",
    "Mt_Na_LC040_N16",
    "Mt_Na_LC050_N20",
    "Mt_K_LC040_N16",
    "Mt_Ca_LC040_N8",
)
SYSTEM_LABELS = {
    "Mt_Na_LC030_N12": "Na-LC0.30",
    "Mt_Na_LC040_N16": "Na-LC0.40",
    "Mt_Na_LC050_N20": "Na-LC0.50",
    "Mt_K_LC040_N16": "K-LC0.40",
    "Mt_Ca_LC040_N8": "Ca-LC0.40",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rh_text(value: float) -> str:
    return f"{value:.2f}"


def main() -> None:
    science = read_rows(SCIENCE_SOURCE)
    manifest = read_rows(MANIFEST_SOURCE)
    science_by_key = {(row["system_id"], float(row["rh"])): row for row in science}
    manifest_by_key = {(row["system_id"], float(row["RH"])): row for row in manifest}
    expected = {(system, rh) for system in SYSTEM_ORDER for rh in RH_ORDER}

    if set(science_by_key) != expected or set(manifest_by_key) != expected:
        raise ValueError("Authoritative sources do not contain exactly the expected 15 system--RH states")

    combined: list[dict[str, object]] = []
    residuals: list[float] = []
    for system in SYSTEM_ORDER:
        for rh in RH_ORDER:
            key = (system, rh)
            obs = science_by_key[key]
            state = manifest_by_key[key]
            if obs["strict_pass"] != "True" or state["equilibrium_result"] != "strict_passed" or state["usable_for_paper"] != "True":
                raise ValueError(f"Non-authoritative state encountered: {key}")
            if Path(obs["source_archive"]) != Path(state["authoritative_archive_directory"]):
                raise ValueError(f"Archive mismatch for {key}")
            if Path(obs["source_summary_file"]) != Path(state["authoritative_summary_source"]):
                raise ValueError(f"Summary mismatch for {key}")
            for source_path in (obs["source_analysis_file"], obs["source_summary_file"]):
                if not (ROOT / source_path).is_file():
                    raise FileNotFoundError(ROOT / source_path)

            total = float(obs["total_water_mean"])
            interlayer = float(obs["interlayer_water_mean"])
            external = float(obs["external_water_mean"])
            basal = float(obs["basal_spacing_mean"])
            residual = total - interlayer - external
            residuals.append(abs(residual))
            if abs(residual) > 1e-6:
                raise ValueError(f"Water mass-balance failure for {key}: {residual}")
            if not (0.0 < total < 10000.0 and 0.0 < basal < 100.0):
                raise ValueError(f"Physically implausible plotting value for {key}")
            if not all(math.isfinite(value) for value in (total, interlayer, external, basal)):
                raise ValueError(f"Missing or non-finite plotting value for {key}")

            rh_start_step = int(state["RH_start_step"])
            final_absolute_step = int(state["final_absolute_step"])
            calculated_local_steps = final_absolute_step - rh_start_step
            manifest_local_steps = int(state["elapsed_steps_within_current_RH"])
            if not math.isclose(calculated_local_steps, manifest_local_steps, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError(
                    f"RH-local step mismatch for {system} RH {rh:.2f}: "
                    f"final_absolute_step ({final_absolute_step}) - RH_start_step ({rh_start_step}) "
                    f"= {calculated_local_steps}, but manifest elapsed_steps_within_current_RH "
                    f"= {manifest_local_steps}"
                )

            combined.append(
                {
                    "system_id": system,
                    "system": SYSTEM_LABELS[system],
                    "cation": obs["cation"],
                    "layer_charge": f"{abs(float(obs['nominal_layer_charge'])):.2f}",
                    "RH": rh_text(rh),
                    "total_water": obs["total_water_mean"],
                    "interlayer_water": obs["interlayer_water_mean"],
                    "external_water": obs["external_water_mean"],
                    "basal_spacing": obs["basal_spacing_mean"],
                    "analysis_source": obs["source_analysis_file"],
                    "rh_local_steps": calculated_local_steps,
                    "num_segments": state["segment_count"],
                }
            )

    write_rows(
        DATA_DIR / "fig3_water_evolution.csv",
        ["system", "cation", "layer_charge", "RH", "total_water", "analysis_source"],
        [{field: row[field] for field in ("system", "cation", "layer_charge", "RH", "total_water", "analysis_source")} for row in combined],
    )
    write_rows(
        DATA_DIR / "fig4_water_partition.csv",
        ["system", "RH", "total_water", "interlayer_water", "external_water", "interlayer_fraction", "external_fraction"],
        [
            {
                "system": row["system"],
                "RH": row["RH"],
                "total_water": row["total_water"],
                "interlayer_water": row["interlayer_water"],
                "external_water": row["external_water"],
                "interlayer_fraction": f"{float(row['interlayer_water']) / float(row['total_water']):.10f}",
                "external_fraction": f"{float(row['external_water']) / float(row['total_water']):.10f}",
            }
            for row in combined
        ],
    )
    write_rows(
        DATA_DIR / "fig5_basal_spacing.csv",
        ["system", "RH", "basal_spacing", "analysis_source"],
        [{field: row[field] for field in ("system", "RH", "basal_spacing", "analysis_source")} for row in combined],
    )

    def sampling_rows(labels: set[str]) -> list[dict[str, object]]:
        fields = ("system", "RH", "total_water", "rh_local_steps", "num_segments")
        return [{field: row[field] for field in fields} for row in combined if row["system"] in labels]

    write_rows(
        DATA_DIR / "fig6_cation_sampling.csv",
        ["system", "RH", "total_water", "rh_local_steps", "num_segments"],
        sampling_rows({"Na-LC0.40", "K-LC0.40", "Ca-LC0.40"}),
    )
    write_rows(
        DATA_DIR / "fig7_layer_charge_sampling.csv",
        ["system", "RH", "total_water", "rh_local_steps", "num_segments"],
        sampling_rows({"Na-LC0.30", "Na-LC0.40", "Na-LC0.50"}),
    )
    write_rows(
        DATA_DIR / "fig6_cation_sampling_vs_hydration.csv",
        ["system", "RH", "total_water", "rh_local_steps", "num_segments"],
        sampling_rows({"Na-LC0.40", "K-LC0.40", "Ca-LC0.40"}),
    )
    write_rows(
        DATA_DIR / "fig7_layer_charge_sampling_vs_hydration.csv",
        ["system", "RH", "total_water", "rh_local_steps", "num_segments"],
        sampling_rows({"Na-LC0.30", "Na-LC0.40", "Na-LC0.50"}),
    )
    print(f"Validated and wrote seven datasets ({len(combined)} states; maximum water-balance residual {max(residuals):.12g} molecules).")


if __name__ == "__main__":
    main()

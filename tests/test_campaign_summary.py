from __future__ import annotations

import csv
import json
from pathlib import Path

from mtagent.campaign_summary import generate_campaign_summary


def write_case(base: Path, system_id: str, cation: str, layer_charge: float, expected_ion_count: int) -> None:
    (base / f"case.{system_id}.yaml").write_text(
        f"""case:
  name: {system_id}
structure:
  cation: {cation}
  layer_charge_per_uc: {layer_charge}
  expected_ion_count: {expected_ion_count}
"""
    )


def write_summary(base: Path, system_id: str, rh_dir: str, payload: dict[str, object]) -> Path:
    state_dir = base / "examples" / system_id / "states" / rh_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "summary.json"
    path.write_text(json.dumps(payload))
    return path


def test_campaign_summary_writes_compact_csv_and_markdown(tmp_path: Path) -> None:
    write_case(tmp_path, "Mt_Na_LC050_N20", "Na", -0.5, 20)
    write_case(tmp_path, "Mt_Ca_LC040_N8", "Ca", -0.4, 8)
    write_summary(
        tmp_path,
        "Mt_Na_LC050_N20",
        "rh_0p90",
        {
            "rh": 0.9,
            "final_step": 4100000,
            "total_water": 462,
            "interlayer_water": 298,
            "external_water": 164,
            "basal_proxy": 20.0522,
            "analysis_status": "equilibrated",
            "analysis_recommendation": "archive",
            "fatal_errors": [],
            "known_warnings": ["gcmc_full_energy"],
            "archived_restart": "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.4100000",
        },
    )
    write_summary(
        tmp_path,
        "Mt_Na_LC050_N20",
        "rh_0p70",
        {
            "rh": 0.7,
            "final_step": 6100000,
            "total_water": 496,
            "interlayer_water": 288,
            "external_water": 208,
            "basal_proxy": 19.222,
            "equilibrium_status": "equilibrated",
            "equilibrium_recommendation": "archive",
            "selected_restart": "examples/Mt_Na_LC050_N20/states/rh_0p70/restart.gcmc_rh0p70.6100000",
        },
    )
    write_summary(
        tmp_path,
        "Mt_Ca_LC040_N8",
        "rh_0p90",
        {
            "rh": 0.9,
            "final_step": 4200000,
            "total_water": 473,
            "interlayer_water": 280,
            "external_water": 193,
            "basal_proxy": 19.5126,
            "analysis_status": "equilibrated",
            "analysis_recommendation": "archive",
            "known_warnings": ["net_charge", "gcmc_full_energy"],
            "archived_restart": "examples/Mt_Ca_LC040_N8/states/rh_0p90/restart.gcmc_rh0p90.4200000",
        },
    )

    rows = generate_campaign_summary(base_dir=tmp_path)

    assert [row["system_id"] for row in rows] == ["Mt_Ca_LC040_N8", "Mt_Na_LC050_N20", "Mt_Na_LC050_N20"]
    assert rows[0]["cation"] == "Ca"
    assert rows[0]["layer_charge"] == -0.4
    assert rows[0]["ion_count"] == 8
    assert rows[0]["metadata_status"] == "complete"
    assert rows[1]["RH"] == 0.9
    assert rows[2]["analysis_status"] == "equilibrated"
    assert rows[2]["analysis_recommendation"] == "archive"

    with (tmp_path / "generated" / "campaign_summary.csv").open(newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert csv_rows[0]["system_id"] == "Mt_Ca_LC040_N8"
    assert csv_rows[0]["metadata_status"] == "complete"
    assert csv_rows[0]["known_warnings"] == "net_charge; gcmc_full_energy"
    assert csv_rows[1]["archived_restart"].endswith("restart.gcmc_rh0p90.4100000")

    md = (tmp_path / "generated" / "campaign_summary.md").read_text()
    assert "| system_id | cation | layer_charge | RH |" in md
    assert "Mt_Na_LC050_N20" in md


def test_campaign_summary_handles_partial_and_malformed_states(tmp_path: Path) -> None:
    write_summary(
        tmp_path,
        "Mt_K_LC030_N6",
        "rh_0p90",
        {
            "rh": 0.9,
            "analysis_status": "equilibrated",
            "archived_restart": "/abs/restart.gcmc_rh0p90.1000",
        },
    )
    bad = tmp_path / "examples" / "Broken" / "states" / "rh_0p70"
    bad.mkdir(parents=True)
    (bad / "summary.json").write_text("{bad json")

    rows = generate_campaign_summary(base_dir=tmp_path)

    partial = next(row for row in rows if row["system_id"] == "Mt_K_LC030_N6")
    assert partial["cation"] == "K"
    assert partial["layer_charge"] == "-0.3"
    assert partial["ion_count"] == 6
    assert partial["metadata_status"] == "inferred"
    assert partial["total_water"] is None
    malformed = next(row for row in rows if row["system_id"] == "Broken")
    assert malformed["metadata_status"] == "missing"
    assert "malformed summary.json" in malformed["fatal_errors"][0]


def test_campaign_summary_filters_to_campaign_systems_unless_all_states(tmp_path: Path) -> None:
    campaign = tmp_path / "examples" / "campaigns" / "campaign.yaml"
    campaign.parent.mkdir(parents=True)
    campaign.write_text(
        """systems:
  - system_id: Mt_Na_LC050_N20
  - system_id: Mt_Ca_LC040_N8
"""
    )
    write_summary(tmp_path, "Mt_Na_LC050_N20", "rh_0p90", {"rh": 0.9})
    write_summary(tmp_path, "Mt_Ca_LC040_N8", "rh_0p90", {"rh": 0.9})
    write_summary(tmp_path, "Mt_Oct050_Na", "rh_0p90", {"rh": 0.9})

    rows = generate_campaign_summary(base_dir=tmp_path, campaign_path=campaign)

    assert [row["system_id"] for row in rows] == ["Mt_Ca_LC040_N8", "Mt_Na_LC050_N20"]

    all_rows = generate_campaign_summary(base_dir=tmp_path, campaign_path=campaign, all_states=True)

    assert "Mt_Oct050_Na" in {row["system_id"] for row in all_rows}

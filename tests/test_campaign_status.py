from __future__ import annotations

import csv
import json
from pathlib import Path

from mtagent.campaign_status import generate_campaign_status


def write_case(tmp_path: Path, out_dir: Path) -> Path:
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        f"""case:
  name: TestCase
paths:
  example_dir: {out_dir}
"""
    )
    return case_path


def write_summary(state_dir: Path, rh: float, total_water: int) -> None:
    state_dir.mkdir(parents=True)
    (state_dir / "summary.json").write_text(
        json.dumps(
            {
                "rh": rh,
                "timestamp": "2026-06-14T12:00:00+08:00",
                "final_step": 4100000,
                "total_water": total_water,
                "interlayer_water": 297,
                "external_water": 168,
                "basal_proxy": 19.8083,
                "equilibrium_status": "equilibrated",
                "manager_action": "write_data_and_continue_next_rh",
                "source_restart": f"${{HISTORICAL_TMP}}/run/restart.gcmc_rh{rh}.4100000",
                "archived_restart": f"${{HISTORICAL_TMP}}/archive/restart.gcmc_rh{rh}.4100000",
                "selected_restart": f"${{HISTORICAL_TMP}}/archive/restart.gcmc_rh{rh}.4100000",
                "final_window_slopes": {
                    "nwater_total": {"slope_per_100k": 2.1},
                    "nwater_inter": {"slope_per_100k": -0.05},
                    "nwater_ext": {"slope_per_100k": 2.2},
                    "basal_proxy": {"slope_per_100k": -0.03},
                },
                "warnings_errors": {
                    "manager_warnings": [],
                    "run_error_keywords_found": [],
                },
            }
        )
    )


def test_campaign_status_writes_sorted_outputs_from_archives(tmp_path: Path) -> None:
    out_dir = tmp_path / "example"
    write_summary(out_dir / "states" / "rh_0p70", 0.7, 330)
    write_summary(out_dir / "states" / "rh_0p90", 0.9, 465)
    case_path = write_case(tmp_path, out_dir)

    rows = generate_campaign_status(case_path)

    assert [row["rh"] for row in rows] == [0.9, 0.7]
    assert rows[0]["case_id"] == "TestCase"
    assert rows[0]["status"] == "archived"
    assert rows[0]["total_water"] == 465
    assert rows[0]["nwater_ext_slope_per_100k"] == 2.2
    assert rows[0]["selected_restart"] == "${HISTORICAL_TMP}/archive/restart.gcmc_rh0.9.4100000"
    assert (out_dir / "campaign_status.md").exists()
    assert (out_dir / "campaign_status.json").exists()

    with (out_dir / "campaign_status.csv").open(newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert [row["rh"] for row in csv_rows] == ["0.9", "0.7"]
    assert csv_rows[0]["external_water"] == "168"


def test_campaign_status_empty_states_writes_headers(tmp_path: Path) -> None:
    out_dir = tmp_path / "example"
    out_dir.mkdir()
    case_path = write_case(tmp_path, out_dir)

    rows = generate_campaign_status(case_path, out_dir)

    assert rows == []
    assert "case_id,rh,status,final_step" in (out_dir / "campaign_status.csv").read_text()
    md = (out_dir / "campaign_status.md").read_text()
    assert "| case_id | rh | status | final_step |" in md
    payload = json.loads((out_dir / "campaign_status.json").read_text())
    assert payload["count"] == 0
    assert payload["rows"] == []

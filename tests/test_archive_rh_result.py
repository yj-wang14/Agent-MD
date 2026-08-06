from __future__ import annotations

import json
from pathlib import Path

from mtagent.archive_rh_result import archive_rh_result


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "rh_0p90_formal"
    run_dir.mkdir()
    (run_dir / "monitor_gcmc_rh0p90.dat").write_text(
        "# TimeStep v_nwater_mol v_nwat_inter v_nwat_bottom v_nwat_top v_nwat_ext v_basal_proxy v_zcenter v_iacc v_dacc v_tacc v_racc v_temp_inst v_pe_inst\n"
        "4100000 465 297 95 73 168 19.8083 43.3734 0.001 0.002 0 0 296.9 -130990\n"
    )
    (run_dir / "restart.gcmc_rh0p90.4100000").write_text("restart")
    (run_dir / "restart.gcmc_rh0p90.final").write_text("old final")
    write_json(
        run_dir / "equilibrium_status.preview.json",
        {
            "status": "equilibrated",
            "recommendation": "write_data_and_continue_next_rh",
            "series": {
                "nwater_total": {"slope_per_100k": 2.1, "slope_limit_per_100k": 4.6},
                "nwater_inter": {"slope_per_100k": -0.05, "slope_limit_per_100k": 5.9},
                "nwater_ext": {"slope_per_100k": 2.2, "slope_limit_per_100k": 3.2},
                "basal_proxy": {"slope_per_100k": -0.03, "slope_limit_A_per_100k": 0.05},
            },
        },
    )
    write_json(
        run_dir / "manager_decision.preview.json",
        {"action": "write_data_and_continue_next_rh", "warnings": []},
    )
    write_json(run_dir / "initial_status.json", {"status": "completed"})
    write_json(run_dir / "cycle_status.json", {"status": "completed_with_run"})
    write_json(run_dir / "run_status.json", {"status": "completed", "return_code": 0, "error_keywords_found": []})
    return run_dir


def test_archive_rh_result_prefers_exact_final_step_restart(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path)

    summary = archive_rh_result(run_dir)
    archive_dir = tmp_path / "states" / "rh_0p90"

    assert summary["final_step"] == 4100000
    assert summary["total_water"] == 465
    assert summary["interlayer_water"] == 297
    assert summary["external_water"] == 168
    assert summary["basal_proxy"] == 19.8083
    assert summary["equilibrium_status"] == "equilibrated"
    assert summary["manager_action"] == "write_data_and_continue_next_rh"
    assert summary["source_restart"].endswith("rh_0p90_formal/restart.gcmc_rh0p90.4100000")
    assert summary["archived_restart"].endswith("states/rh_0p90/restart.gcmc_rh0p90.4100000")
    assert summary["selected_restart"] == summary["archived_restart"]
    assert (archive_dir / "restart.gcmc_rh0p90.4100000").read_text() == "restart"
    assert (archive_dir / "monitor_gcmc_rh0p90.dat").exists()
    assert (archive_dir / "equilibrium_status.preview.json").exists()
    assert (archive_dir / "manager_decision.preview.json").exists()
    assert (archive_dir / "summary.json").exists()
    assert (archive_dir / "summary.md").exists()

    saved = json.loads((archive_dir / "summary.json").read_text())
    assert saved["final_window_slopes"]["nwater_ext"]["slope_per_100k"] == 2.2
    assert saved["selected_restart"] == saved["archived_restart"]


def test_archive_rh_result_falls_back_to_final_restart(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path)
    (run_dir / "restart.gcmc_rh0p90.4100000").unlink()

    summary = archive_rh_result(run_dir)

    assert summary["source_restart"].endswith("restart.gcmc_rh0p90.final")
    assert summary["selected_restart"].endswith("states/rh_0p90/restart.gcmc_rh0p90.final")
    assert (tmp_path / "states" / "rh_0p90" / "restart.gcmc_rh0p90.final").exists()

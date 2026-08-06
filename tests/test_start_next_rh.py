from __future__ import annotations

import json
import sys
from pathlib import Path

from mtagent import start_next_rh
from tests.test_run_initial import minimal_initial_case


def make_state(tmp_path: Path) -> Path:
    state_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "states" / "rh_0p90"
    state_dir.mkdir(parents=True)
    restart = state_dir / "restart.gcmc_rh0p90.4100000"
    restart.write_text("restart\n")
    (state_dir / "summary.json").write_text(
        json.dumps(
            {
                "rh": 0.9,
                "final_step": 4100000,
                "source_restart": "${HISTORICAL_TMP}/original/restart.gcmc_rh0p90.4100000",
                "archived_restart": str(restart),
                "selected_restart": str(restart),
            }
        )
    )
    return state_dir


def run_start_next_cli(monkeypatch, tmp_path: Path, args: list[str]) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["start_next_rh.py", *args])
    start_next_rh.main()


def test_start_next_rh_dry_run_generates_input_from_archived_restart(tmp_path: Path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    state_dir = make_state(tmp_path)
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p70_formal"

    run_start_next_cli(
        monkeypatch,
        tmp_path,
        [
            "--case", str(case_path),
            "--from-state", str(state_dir),
            "--rh", "0.70",
            "--run-dir", str(run_dir),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )

    input_path = run_dir / "in.gcmc_rh0p70_initial"
    status = json.loads((run_dir / "start_next_rh_status.preview.json").read_text())
    input_text = input_path.read_text()
    restart = state_dir / "restart.gcmc_rh0p90.4100000"

    assert status["status"] == "dry_run"
    assert status["run_requested"] is False
    assert status["from_rh"] == 0.9
    assert status["from_final_step"] == 4100000
    assert status["rh"] == 0.7
    assert status["selected_restart"] == str(restart.resolve())
    assert status["start_source_kind"] == "archived_restart"
    assert status["input_file_written"] is True
    assert status["run_line"] == "run 1000"
    assert status["neigh_modify"] == "every 2 delay 0 check yes"
    assert status["reinitialize_velocity_on_restart"] is False

    assert f"read_restart {restart.resolve()}" in input_text
    assert "velocity mobile create ${temp}" not in input_text
    assert "# Existing mobile velocities are preserved from read_restart." in input_text
    assert "variable rh          equal 0.700000" in input_text
    assert "append monitor_gcmc_rh0p70.dat" in input_text
    assert "restart 100000 restart.gcmc_rh0p70.*" in input_text
    assert "write_restart restart.gcmc_rh0p70.final" in input_text
    assert "neigh_modify every 2 delay 0 check yes" in input_text
    assert "# Rigid clay sheets: z-translation only" in input_text


def test_start_next_rh_prefers_archived_restart_over_selected_restart(tmp_path: Path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    state_dir = make_state(tmp_path)
    archived = state_dir / "restart.gcmc_rh0p90.4100000"
    selected = state_dir / "restart.gcmc_rh0p90.final"
    selected.write_text("fallback\n")
    summary = json.loads((state_dir / "summary.json").read_text())
    summary["archived_restart"] = str(archived)
    summary["selected_restart"] = str(selected)
    (state_dir / "summary.json").write_text(json.dumps(summary))
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p70_formal"

    run_start_next_cli(
        monkeypatch,
        tmp_path,
        [
            "--case", str(case_path),
            "--from-state", str(state_dir),
            "--rh", "0.70",
            "--run-dir", str(run_dir),
            "--dry-run",
        ],
    )

    status = json.loads((run_dir / "start_next_rh_status.preview.json").read_text())
    assert status["restart_key"] == "archived_restart"
    assert status["selected_restart"] == str(archived.resolve())


def test_start_next_rh_reinitializes_velocity_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    case_path.write_text(
        case_path.read_text().replace(
            "reinitialize_velocity_on_restart: false",
            "reinitialize_velocity_on_restart: true",
        )
    )
    state_dir = make_state(tmp_path)
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p70_formal"

    run_start_next_cli(
        monkeypatch,
        tmp_path,
        [
            "--case", str(case_path),
            "--from-state", str(state_dir),
            "--rh", "0.70",
            "--run-dir", str(run_dir),
            "--dry-run",
        ],
    )

    status = json.loads((run_dir / "start_next_rh_status.preview.json").read_text())
    input_text = (run_dir / "in.gcmc_rh0p70_initial").read_text()

    assert status["start_source_kind"] == "archived_restart"
    assert status["reinitialize_velocity_on_restart"] is True
    assert "velocity mobile create ${temp}" in input_text
    assert "loop geom" in input_text


def test_start_next_rh_accepts_repo_relative_archived_restart(tmp_path: Path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    state_dir = make_state(tmp_path)
    restart = state_dir / "restart.gcmc_rh0p90.4100000"
    summary = json.loads((state_dir / "summary.json").read_text())
    summary["archived_restart"] = "examples/Mt_Oct050_Na/states/rh_0p90/restart.gcmc_rh0p90.4100000"
    summary["selected_restart"] = "examples/Mt_Oct050_Na/states/rh_0p90/restart.gcmc_rh0p90.4100000"
    (state_dir / "summary.json").write_text(json.dumps(summary))
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p70_formal"

    run_start_next_cli(
        monkeypatch,
        tmp_path,
        [
            "--case", str(case_path),
            "--from-state", str(state_dir),
            "--rh", "0.70",
            "--run-dir", str(run_dir),
            "--dry-run",
            "--write-input",
        ],
    )

    status = json.loads((run_dir / "start_next_rh_status.preview.json").read_text())
    input_text = (run_dir / "in.gcmc_rh0p70_initial").read_text()

    assert status["selected_restart"] == str(restart.resolve())
    assert f"read_restart {restart.resolve()}" in input_text
    assert "velocity mobile create ${temp}" not in input_text

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mtagent import run_initial


def minimal_initial_case(tmp_path: Path) -> Path:
    example_dir = tmp_path / "examples" / "Mt_Oct050_Na"
    prepared_dir = example_dir / "inputs"
    prepared_dir.mkdir(parents=True)
    (prepared_dir / "MyMont-1_5_4_prepared.data").write_text("LAMMPS data placeholder\n")
    (prepared_dir / "MyMont-1_5_4_groups_regions.inc").write_text("group water type 8 10\n")

    forcefield_dir = tmp_path / "assets" / "forcefields"
    forcefield_dir.mkdir(parents=True)
    molecule_template = forcefield_dir / "SPCEH2O_types_8_10.txt"
    molecule_template.write_text("# molecule template placeholder\n")

    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        """case:
  temperature: 300.0
paths:
  example_dir: examples/Mt_Oct050_Na
  prepared_dir: examples/Mt_Oct050_Na/inputs
structure:
  claycode_model: MyMont-1_5_4
water:
  molecule_template: assets/forcefields/SPCEH2O_types_8_10.txt
  oxygen_type: 8
gcmc:
  rh_path: [0.90]
  psat_pa: 1011.71
  patm_pa: 101325.0
  interval: 1000
  exchange_attempts: 100
  translation_attempts: 0
  rotation_attempts: 0
  mu: -8.1
  displacement: 0.5
  tfac_insert: 1.6666666667
  segment_steps: 500000
  restart_interval: 100000
md:
  timestep_fs: 1.0
  pair_style: lj/cut/coul/long 12.0
  kspace_style: pppm 1.0e-4
  neighbor_every: 2
  neighbor_delay: 0
  neighbor_check: yes
  reinitialize_velocity_on_restart: false
  thermo_interval: 5000
  monitor_interval: 1000
  dump_interval: 50000
local:
  lammps_command: lmp
  mpi_command: mpirun
  default_np: 1
regions:
  gcmc:
    style: block
    xlo: 0.1
    xhi: 1.0
    ylo: 0.1
    yhi: 1.0
    zlo: 0.1
    zhi: 1.0
    units: box
"""
    )
    return case_path


def run_initial_cli(monkeypatch, tmp_path: Path, args: list[str]) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_initial.py", *args])
    run_initial.main()


def test_dry_run_without_write_input_does_not_create_input_file(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)

    run_initial_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--dry-run", "--segment-steps-override", "1000"],
    )

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_path = run_dir / "in.gcmc_rh0p90_initial"
    preview = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert not input_path.exists()
    assert preview["status"] == "dry_run"
    assert preview["input_file_written"] is False
    assert preview["run_line"] == "run 1000"


def test_dry_run_with_write_input_creates_input_file(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)

    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    input_text = (
        tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90" / "in.gcmc_rh0p90_initial"
    ).read_text()
    prepared_data = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_prepared.data").resolve()
    groups_regions = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_groups_regions.inc").resolve()
    molecule_template = (tmp_path / "assets" / "forcefields" / "SPCEH2O_types_8_10.txt").resolve()
    assert f"read_data {prepared_data} &" in input_text
    assert "extra/bond/per/atom 2" in input_text
    assert "extra/angle/per/atom 1" in input_text
    assert "extra/special/per/atom 2" in input_text
    assert f"include {groups_regions}" in input_text
    assert f"molecule h2omol {molecule_template}" in input_text
    assert "neigh_modify every 2 delay 0 check yes" in input_text
    assert "append monitor_gcmc_rh0p90.dat" in input_text
    assert "restart 100000 restart.gcmc_rh0p90.*" in input_text
    assert "write_restart restart.gcmc_rh0p90.final" in input_text
    assert "# Initial NVT relaxation" in input_text
    assert "velocity mobile create ${temp}" in input_text
    assert "loop geom" in input_text
    assert "fix nvt_mobile mobile nvt temp ${temp} ${temp} 100.0" in input_text
    assert "run 10000" in input_text
    assert "# RH GCMC-MD segment" in input_text
    assert "fix mygcmc" in input_text

    assert input_text.index("# Initial NVT relaxation") < input_text.index("velocity mobile create")
    assert input_text.index("velocity mobile create") < input_text.index("run 10000")
    assert input_text.index("run 10000") < input_text.index("unfix nvt_mobile")
    assert input_text.index("unfix nvt_mobile") < input_text.index("# RH GCMC-MD segment")
    assert input_text.index("# RH GCMC-MD segment") < input_text.index("fix mygcmc")


def test_run_mode_refuses_existing_monitor_or_restart_without_force(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "monitor_gcmc_rh0p90.dat").write_text("existing monitor\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_initial.py", "--case", str(case_path), "--run"])

    with pytest.raises(SystemExit, match="existing monitor/restart"):
        run_initial.main()

    assert not (run_dir / "in.gcmc_rh0p90_initial").exists()


def test_run_mode_allows_existing_monitor_or_restart_with_force(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "restart.gcmc_rh0p90.1000").write_text("restart placeholder\n")

    def fake_run_lammps(case_cfg, repo_root, run_dir_arg, input_path, np, status):
        (run_dir_arg / "log.lammps").write_text("log\n")
        (run_dir_arg / "monitor_gcmc_rh0p90.dat").write_text("monitor\n")
        (run_dir_arg / "after_gcmc_rh0p90_initial.data").write_text("data\n")
        (run_dir_arg / "restart.gcmc_rh0p90.1000").write_text("restart\n")
        (run_dir_arg / "restart.gcmc_rh0p90.final").write_text("final restart\n")
        status["runner"] = {"status": "completed", "return_code": 0, "cwd": str(run_dir_arg)}
        return 0

    monkeypatch.setattr(run_initial, "run_lammps", fake_run_lammps)
    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--run", "--force"])

    status = json.loads((run_dir / "initial_status.json").read_text())
    assert status["status"] == "completed"
    assert status["force"] is True
    assert status["collision_files"]
    assert (run_dir / "in.gcmc_rh0p90_initial").exists()


def test_run_dir_override_is_respected(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    override = tmp_path / "custom_initial"

    run_initial_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--dry-run", "--write-input", "--run-dir", str(override)],
    )

    status = json.loads((override / "initial_status.preview.json").read_text())
    assert status["run_dir"] == str(override)
    assert Path(status["input_file"]).parent == override
    assert (override / "in.gcmc_rh0p90_initial").exists()


def test_segment_steps_override_produces_run_1000_with_write_input(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)

    run_initial_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--dry-run", "--write-input", "--segment-steps-override", "1000"],
    )

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_text = (run_dir / "in.gcmc_rh0p90_initial").read_text()
    status = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert "run 10000" in input_text
    assert "run 1000" in input_text
    assert input_text.index("fix mygcmc") < input_text.rindex("run 1000")
    assert status["run_line"] == "run 1000"


def test_run_mode_uses_input_basename_and_run_dir_cwd(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    captured = {}

    class Proc:
        returncode = 0

    def fake_subprocess_run(command, cwd, stdout, stderr, text):
        captured["command"] = command
        captured["cwd"] = cwd
        (cwd / "log.lammps").write_text("log\n")
        (cwd / "monitor_gcmc_rh0p90.dat").write_text("monitor\n")
        (cwd / "after_gcmc_rh0p90_initial.data").write_text("data\n")
        (cwd / "restart.gcmc_rh0p90.1000").write_text("restart\n")
        (cwd / "restart.gcmc_rh0p90.final").write_text("final restart\n")
        return Proc()

    monkeypatch.setattr(run_initial.subprocess, "run", fake_subprocess_run)
    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--run"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    status = json.loads((run_dir / "initial_status.json").read_text())

    assert captured["cwd"] == run_dir
    assert captured["command"] == ["mpirun", "-np", "1", "lmp", "-in", "in.gcmc_rh0p90_initial"]
    assert status["runner"]["cwd"] == str(run_dir)
    assert status["runner"]["run_dir"] == str(run_dir)
    assert status["runner"]["command"] == captured["command"]
    assert status["status"] == "completed"
    assert status["neighbor_settings"] == {"every": 2, "delay": 0, "check": "yes"}
    assert status["neigh_modify"] == "every 2 delay 0 check yes"
    assert status["reinitialize_velocity_on_restart"] is False


def test_successful_runner_with_missing_outputs_is_failed_outputs_missing(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)

    class Proc:
        returncode = 0

    def fake_subprocess_run(command, cwd, stdout, stderr, text):
        return Proc()

    monkeypatch.setattr(run_initial.subprocess, "run", fake_subprocess_run)
    with pytest.raises(SystemExit, match="expected output files are missing"):
        run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--run"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    status = json.loads((run_dir / "initial_status.json").read_text())
    assert status["status"] == "failed_outputs_missing"
    assert "log.lammps" in status["missing_outputs"]
    assert "monitor_gcmc_rh0p90.dat" in status["missing_outputs"]
    assert "after_gcmc_rh0p90_initial.data" in status["missing_outputs"]
    assert "restart.gcmc_rh0p90.final" in status["missing_outputs"]
    assert "restart.gcmc_rh0p90.*" in status["missing_outputs"]


def test_short_validation_run_does_not_require_restart(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    captured = {}

    class Proc:
        returncode = 0

    def fake_subprocess_run(command, cwd, stdout, stderr, text):
        captured["command"] = command
        captured["cwd"] = cwd
        (cwd / "log.lammps").write_text("log\n")
        (cwd / "monitor_gcmc_rh0p90.dat").write_text("monitor\n")
        (cwd / "after_gcmc_rh0p90_initial.data").write_text("data\n")
        (cwd / "restart.gcmc_rh0p90.final").write_text("final restart\n")
        return Proc()

    monkeypatch.setattr(run_initial.subprocess, "run", fake_subprocess_run)
    run_initial_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--run", "--segment-steps-override", "1000"],
    )

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    status = json.loads((run_dir / "initial_status.json").read_text())

    assert status["status"] == "completed"
    assert status["restart_interval"] == 100000
    assert status["restart_expected"] is False
    final_restart = str(run_dir / "restart.gcmc_rh0p90.final")
    assert status["found_restart_files"] == [final_restart]
    assert status["final_restart"] == final_restart
    assert "Restart not expected for short validation run." in status["warnings"]
    assert "restart.gcmc_rh0p90.final" not in status.get("missing_outputs", [])
    assert "restart.gcmc_rh0p90.*" not in status.get("missing_outputs", [])


def test_dry_run_records_restart_expectation_for_short_override(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)

    run_initial_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--dry-run", "--segment-steps-override", "1000"],
    )

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    status = json.loads((run_dir / "initial_status.preview.json").read_text())
    assert status["initial_relax_steps"] == 10000
    assert status["effective_segment_steps"] == 1000
    assert status["restart_interval"] == 100000
    assert status["restart_expected"] is False
    assert status["found_restart_files"] == []
    assert status["final_restart"] is None



def test_run_initial_selects_equilibration_restart_when_present(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    restart = tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "restart.pre_gcmc.final"
    restart.write_text("restart placeholder\n")

    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_text = (run_dir / "in.gcmc_rh0p90_initial").read_text()
    status = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert f"read_restart {restart.resolve()}" in input_text
    assert "velocity mobile create ${temp}" not in input_text
    assert "# Existing mobile velocities are preserved from read_restart." in input_text
    assert "neigh_modify every 2 delay 0 check yes" in input_text
    assert "extra/bond/per/atom" not in input_text
    assert "extra/angle/per/atom" not in input_text
    assert "extra/special/per/atom" not in input_text
    assert status["start_source_kind"] == "equilibration_restart"
    assert status["start_source"] == str(restart.resolve())
    assert status["reinitialize_velocity_on_restart"] is False
    assert not status["warnings"]


def test_run_initial_falls_back_to_prepared_data_when_equilibration_outputs_missing(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    prepared = tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_prepared.data"

    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_text = (run_dir / "in.gcmc_rh0p90_initial").read_text()
    status = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert f"read_data {prepared.resolve()} &" in input_text
    assert "extra/bond/per/atom 2" in input_text
    assert "extra/angle/per/atom 1" in input_text
    assert "extra/special/per/atom 2" in input_text
    assert status["start_source_kind"] == "prepared_data"
    assert status["topology_extra"] == {
        "extra_bond_per_atom": 2,
        "extra_angle_per_atom": 1,
        "extra_special_per_atom": 2,
    }
    assert status["start_source"] == str(prepared.resolve())
    assert "velocity mobile create ${temp}" in input_text
    assert "Pre-GCMC equilibration output not found; falling back to prepared.data." in status["warnings"]



def test_run_initial_equilibrated_data_fallback_includes_topology_extra(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    equilibrated = tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_equilibrated.data"
    equilibrated.write_text("equilibrated data placeholder\n")

    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_text = (run_dir / "in.gcmc_rh0p90_initial").read_text()
    status = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert f"read_data {equilibrated.resolve()} &" in input_text
    assert "extra/bond/per/atom 2" in input_text
    assert "extra/angle/per/atom 1" in input_text
    assert "extra/special/per/atom 2" in input_text
    assert status["start_source_kind"] == "equilibrated_data"
    assert "velocity mobile create ${temp}" in input_text


def test_run_initial_reinitializes_restart_velocity_only_when_configured(tmp_path, monkeypatch) -> None:
    case_path = minimal_initial_case(tmp_path)
    case_path.write_text(
        case_path.read_text().replace(
            "reinitialize_velocity_on_restart: false",
            "reinitialize_velocity_on_restart: true",
        )
    )
    restart = tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "restart.pre_gcmc.final"
    restart.write_text("restart placeholder\n")

    run_initial_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "rh_0p90"
    input_text = (run_dir / "in.gcmc_rh0p90_initial").read_text()
    status = json.loads((run_dir / "initial_status.preview.json").read_text())

    assert f"read_restart {restart.resolve()}" in input_text
    assert "velocity mobile create ${temp}" in input_text
    assert "loop geom" in input_text
    assert status["start_source_kind"] == "equilibration_restart"
    assert status["reinitialize_velocity_on_restart"] is True

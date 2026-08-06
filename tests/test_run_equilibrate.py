from __future__ import annotations

import json
import sys
from pathlib import Path

from mtagent import run_equilibrate


def minimal_equilibration_case(tmp_path: Path, include_output_dir: bool = True) -> Path:
    example_dir = tmp_path / "examples" / "Mt_Oct050_Na"
    prepared_dir = example_dir / "inputs"
    prepared_dir.mkdir(parents=True)
    (prepared_dir / "MyMont-1_5_4_prepared.data").write_text(
        "LAMMPS data placeholder\n\n"
        "4 atoms\n\n"
        "0 10 xlo xhi\n0 10 ylo yhi\n0 100 zlo zhi\n\n"
        "Atoms # full\n\n"
        "1 1 4 -1 0 0 10\n"
        "2 1 4 -1 1 0 10\n"
        "3 2 4 -1 0 1 30\n"
        "4 2 4 -1 1 1 30\n"
    )
    (prepared_dir / "MyMont-1_5_4_groups_regions.inc").write_text(
        "group clay_lower molecule 1\n"
        "group clay_upper molecule 2\n"
        "group water type 8 10\n"
        "group exchangeable_ions type 11\n"
    )

    equil_section = """
equilibration:
  run_dir: examples/Mt_Oct050_Na/equilibration
  soft_start_steps: 5000
  nvt_steps: 100000
  tdamp: 100.0
  velocity_seed: 4928459
  nve_limit: 0.05
  extra_bond_per_atom: 2
  extra_angle_per_atom: 1
  extra_special_per_atom: 2
  output_data: examples/Mt_Oct050_Na/inputs/MyMont-1_5_4_equilibrated.data
  output_restart: examples/Mt_Oct050_Na/inputs/restart.pre_gcmc.final
""" if include_output_dir else """
equilibration:
  soft_start_steps: 5000
  nvt_steps: 100000
"""

    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        f"""case:
  temperature: 300.0
paths:
  example_dir: examples/Mt_Oct050_Na
  prepared_dir: examples/Mt_Oct050_Na/inputs
structure:
  claycode_model: MyMont-1_5_4
md:
  timestep_fs: 1.0
  pair_style: lj/cut/coul/long 12.0
  kspace_style: pppm 1.0e-4
  neighbor_every: 2
  neighbor_delay: 0
  neighbor_check: yes
  thermo_interval: 5000
local:
  lammps_command: lmp
  mpi_command: mpirun
  default_np: 2
{equil_section}"""
    )
    return case_path


def run_equilibrate_cli(monkeypatch, tmp_path: Path, args: list[str]) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_equilibrate.py", *args])
    run_equilibrate.main()


def test_dry_run_does_not_execute_lammps_or_write_input_by_default(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)

    def fail_run(*args, **kwargs):
        raise AssertionError("LAMMPS should not run in dry-run mode")

    monkeypatch.setattr(run_equilibrate.subprocess, "run", fail_run)
    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    status = json.loads((run_dir / "equilibration_status.preview.json").read_text())
    assert status["status"] == "dry_run"
    assert status["input_file_written"] is False
    assert not (run_dir / "in.equilibrate_pre_gcmc").exists()
    assert not (run_dir / "equilibration_status.json").exists()


def test_dry_run_with_write_input_creates_expected_input(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    input_path = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration" / "in.equilibrate_pre_gcmc"
    text = input_path.read_text()
    prepared = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_prepared.data").resolve()
    groups = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_groups_regions.inc").resolve()
    out_data = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_equilibrated.data").resolve()
    out_restart = (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "restart.pre_gcmc.final").resolve()

    assert f"read_data {prepared} &" in text
    assert "extra/bond/per/atom 2" in text
    assert "extra/angle/per/atom 1" in text
    assert "extra/special/per/atom 2" in text
    assert f"include {groups}" in text
    assert "neigh_modify every 2 delay 0 check yes" in text
    assert "# clay molecule IDs are normalized: lower=1, upper=2" in text
    assert "fix rigid_clay_soft clay rigid/nve molecule force * off off off torque * off off off" in text
    assert "unfix rigid_clay_soft" in text
    assert "fix rigid_clay clay rigid/nve molecule force * off off on torque * off off off" in text
    assert "rigid/nve single" not in text
    assert "group mobile union water sodium" in text
    assert "fix basal_mon all ave/time" in text
    assert "file monitor_equilibrate_basal.dat" in text
    assert "fix lim mobile nve/limit 0.05" in text
    assert "fix nvt_mobile mobile nvt temp ${temp} ${temp} 100.0" in text
    assert text.index("fix rigid_clay_soft") < text.index("fix lim mobile nve/limit")
    assert text.index("unfix rigid_clay_soft") < text.index("fix rigid_clay clay rigid/nve")
    assert text.index("fix rigid_clay clay rigid/nve") < text.index("fix nvt_mobile mobile nvt")
    assert f"write_data {out_data}" in text
    assert f"write_restart {out_restart}" in text


def test_run_mode_records_cwd_and_command_basename(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    captured = {}

    class Proc:
        returncode = 0

    def fake_subprocess_run(command, cwd, stdout, stderr, text):
        captured["command"] = command
        captured["cwd"] = cwd
        (cwd / "log.lammps").write_text("log\n")
        (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "MyMont-1_5_4_equilibrated.data").write_text(
            "LAMMPS data placeholder\n\n"
            "4 atoms\n\n"
            "0 10 xlo xhi\n0 10 ylo yhi\n0 100 zlo zhi\n\n"
            "Atoms # full\n\n"
            "1 1 4 -1 0 0 10\n"
            "2 1 4 -1 1 0 10\n"
            "3 2 4 -1 0 1 30\n"
            "4 2 4 -1 1 1 30\n"
        )
        (tmp_path / "examples" / "Mt_Oct050_Na" / "inputs" / "restart.pre_gcmc.final").write_text("restart\n")
        return Proc()

    monkeypatch.setattr(run_equilibrate.subprocess, "run", fake_subprocess_run)
    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--run"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    status = json.loads((run_dir / "equilibration_status.json").read_text())
    assert captured["cwd"] == run_dir
    assert captured["command"] == ["mpirun", "-np", "2", "lmp", "-in", "in.equilibrate_pre_gcmc"]
    assert status["runner"]["cwd"] == str(run_dir)
    assert status["runner"]["command"] == captured["command"]
    assert status["status"] == "completed"
    assert status["neighbor_settings"] == {"every": 2, "delay": 0, "check": "yes"}
    assert status["neigh_modify"] == "every 2 delay 0 check yes"
    assert status["topology_extra"] == {
        "extra_bond_per_atom": 2,
        "extra_angle_per_atom": 1,
        "extra_special_per_atom": 2,
    }


def test_run_dir_override_is_respected(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    override = tmp_path / "custom_equil"
    run_equilibrate_cli(
        monkeypatch,
        tmp_path,
        ["--case", str(case_path), "--dry-run", "--write-input", "--run-dir", str(override)],
    )

    status = json.loads((override / "equilibration_status.preview.json").read_text())
    assert status["run_dir"] == str(override)
    assert Path(status["input_file"]).parent == override
    assert (override / "in.equilibrate_pre_gcmc").exists()


def test_steps_overrides_are_recorded_and_used(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    run_equilibrate_cli(
        monkeypatch,
        tmp_path,
        [
            "--case",
            str(case_path),
            "--dry-run",
            "--write-input",
            "--soft-steps-override",
            "10",
            "--steps-override",
            "20",
        ],
    )

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    text = (run_dir / "in.equilibrate_pre_gcmc").read_text()
    status = json.loads((run_dir / "equilibration_status.preview.json").read_text())
    assert "run 10" in text
    assert "run 20" in text
    assert status["soft_start_steps"] == 10
    assert status["nvt_steps"] == 20
    assert status["hold_clay_z_during_soft_start"] is True


def test_run_mode_refuses_collisions_without_force(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    run_dir.mkdir(parents=True)
    (run_dir / "log.lammps").write_text("old log\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_equilibrate.py", "--case", str(case_path), "--run"])
    try:
        run_equilibrate.main()
    except SystemExit as exc:
        assert "Equilibration outputs already exist" in str(exc)
    else:
        raise AssertionError("expected collision refusal")


def test_default_outputs_use_model_when_not_configured(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path, include_output_dir=False)
    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    status = json.loads((run_dir / "equilibration_status.preview.json").read_text())
    assert status["output_data"].endswith("MyMont-1_5_4_equilibrated.data")
    assert status["output_restart"].endswith("restart.pre_gcmc.final")
    assert status["topology_extra"] == {
        "extra_bond_per_atom": 2,
        "extra_angle_per_atom": 1,
        "extra_special_per_atom": 2,
    }


def test_neighbor_every_override_is_respected(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    case_path.write_text(case_path.read_text().replace("neighbor_every: 2", "neighbor_every: 4"))

    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    run_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration"
    text = (run_dir / "in.equilibrate_pre_gcmc").read_text()
    status = json.loads((run_dir / "equilibration_status.preview.json").read_text())
    assert "neigh_modify every 4 delay 0 check yes" in text
    assert status["neighbor_settings"] == {"every": 4, "delay": 0, "check": "yes"}
    assert status["neigh_modify"] == "every 4 delay 0 check yes"



def write_minimal_data(path: Path, lower_z: float, upper_z: float) -> None:
    path.write_text(
        "LAMMPS data\n\n"
        "4 atoms\n\n"
        "0 10 xlo xhi\n0 10 ylo yhi\n0 100 zlo zhi\n\n"
        "Atoms # full\n\n"
        f"1 1 4 -1 0 0 {lower_z}\n"
        f"2 1 4 -1 1 0 {lower_z}\n"
        f"3 2 4 -1 0 1 {upper_z}\n"
        f"4 2 4 -1 1 1 {upper_z}\n"
    )


def test_legacy_soft_start_z_motion_can_be_configured(tmp_path, monkeypatch) -> None:
    case_path = minimal_equilibration_case(tmp_path)
    case_path.write_text(case_path.read_text().replace("  nve_limit: 0.05\n", "  nve_limit: 0.05\n  hold_clay_z_during_soft_start: false\n"))
    run_equilibrate_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run", "--write-input"])

    text = (tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration" / "in.equilibrate_pre_gcmc").read_text()
    status = json.loads((tmp_path / "examples" / "Mt_Oct050_Na" / "equilibration" / "equilibration_status.preview.json").read_text())
    assert "fix rigid_clay_soft clay rigid/nve molecule force * off off on torque * off off off" in text
    assert status["hold_clay_z_during_soft_start"] is False


def test_handoff_diagnostic_small_drift_ok(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.data"
    equilibrated = tmp_path / "equilibrated.data"
    write_minimal_data(prepared, 10.0, 30.0)
    write_minimal_data(equilibrated, 10.5, 30.5)
    diag = run_equilibrate.handoff_basal_diagnostics(prepared, equilibrated)
    assert diag["status"] == "ok"
    assert diag["handoff_basal_drift"] == 0.0


def test_handoff_diagnostic_moderate_drift_warning(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.data"
    equilibrated = tmp_path / "equilibrated.data"
    write_minimal_data(prepared, 10.0, 30.0)
    write_minimal_data(equilibrated, 10.0, 35.0)
    diag = run_equilibrate.handoff_basal_diagnostics(prepared, equilibrated)
    assert diag["status"] == "warning"
    assert diag["handoff_basal_drift"] == 5.0


def test_handoff_diagnostic_large_drift_failed(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.data"
    equilibrated = tmp_path / "equilibrated.data"
    write_minimal_data(prepared, 10.0, 30.0)
    write_minimal_data(equilibrated, 10.0, 45.0)
    diag = run_equilibrate.handoff_basal_diagnostics(prepared, equilibrated)
    assert diag["status"] == "failed"
    assert diag["handoff_basal_drift"] == 15.0

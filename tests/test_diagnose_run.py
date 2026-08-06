from pathlib import Path

from mtagent import diagnose_run


def test_clean_log_is_ok(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("Loop time of 1 on 1 procs\nDangerous builds = 0\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "ok"
    assert result["dangerous_builds"] == 0


def test_error_is_failed(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("ERROR: Bad thing\n")
    assert diagnose_run.diagnose_files([log])["status"] == "failed"


def test_lost_atoms_is_failed(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("Lost atoms: original 10 current 9\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "failed"
    assert "Lost atoms" in result["errors"]


def test_pppm_out_of_range_is_failed(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("Out of range atoms - cannot compute PPPM\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "failed"
    assert "PPPM out of range" in result["errors"]


def test_shake_failure_is_failed(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("SHAKE atoms missing on proc 0\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "failed"
    assert "SHAKE failure" in result["errors"]


def test_dangerous_builds_parsed_as_warning(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("Dangerous builds = 7\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "warning"
    assert result["dangerous_builds"] == 7


def test_kspace_warning_is_known_warning(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("WARNING: Neighbor exclusions used with KSpace solver may give inconsistent Coulombic energies\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "warning"
    assert "kspace_neighbor_exclusion" in result["known_warnings"]


def test_net_charge_warning_is_known_warning(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("WARNING: System is not charge neutral, net charge = 0.004\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "warning"
    assert "net_charge" in result["known_warnings"]


def test_nve_limit_shake_warning_is_known_warning(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("WARNING: Using fix nve/limit with SHAKE may give inconsistent virial\n")
    result = diagnose_run.diagnose_files([log])
    assert result["status"] == "warning"
    assert "nve_limit_shake" in result["known_warnings"]


def write_gcmc_monitor(path: Path, *, final_na: int = 20, bad_basal: str | None = None, short: bool = False) -> None:
    # step total inter bottom top ext basal zcenter iacc dacc tacc racc temp pe
    basal = bad_basal or "19.8"
    if short:
        path.write_text("1000 300 300\n")
        return
    path.write_text(
        "1000 300 300 0 0 0 19.7 40 0.1 0.0 0.0 0.0 300 -1000\n"
        f"2000 320 300 10 10 20 {basal} 40 0.2 0.0 0.0 0.0 301 -999\n"
    )


def test_clean_gcmc_diagnostics_ok(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor_gcmc_rh0p90.dat"
    restart = tmp_path / "restart.gcmc_rh0p90.final"
    data = tmp_path / "after_gcmc_rh0p90_initial.data"
    status = tmp_path / "initial_status.json"
    log.write_text("Dangerous builds = 0\n")
    write_gcmc_monitor(monitor)
    restart.write_text("restart\n")
    data.write_text("data\n")
    status.write_text('{"status":"completed","final_restart":"restart.gcmc_rh0p90.final"}')
    result = diagnose_run.diagnose_gcmc_run(
        log_paths=[log], monitor_path=monitor, expected_files=[restart, data, monitor], status_json=status, expected_ion_count=20
    )
    assert result["status"] == "ok"
    assert result["water_summary"]["initial_total_water"] == 300
    assert result["water_summary"]["final_external_water"] == 20
    assert result["water_summary"]["final_basal_proxy"] == 19.8


def test_missing_monitor_is_failed(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    log.write_text("Dangerous builds = 0\n")
    result = diagnose_run.diagnose_gcmc_run(
        log_paths=[log], monitor_path=tmp_path / "missing.dat", expected_files=[], expected_ion_count=20
    )
    assert result["status"] == "failed"


def test_gcmc_error_signatures_fail(tmp_path: Path) -> None:
    for text in ["ERROR: bad", "Lost atoms", "Out of range atoms - cannot compute PPPM", "SHAKE atoms missing", "nan"]:
        log = tmp_path / "log.lammps"
        monitor = tmp_path / "monitor.dat"
        log.write_text(text)
        write_gcmc_monitor(monitor)
        result = diagnose_run.diagnose_gcmc_run(log_paths=[log], monitor_path=monitor, expected_files=[])
        assert result["status"] == "failed"



def test_gcmc_large_initial_basal_relaxation_warns(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text("Dangerous builds = 0\n")
    monitor.write_text(
        "1000 300 300 0 0 0 46.6 40 0.1 0.0 0.0 0.0 300 -1000\n"
        "2000 320 300 10 10 20 19.8 40 0.2 0.0 0.0 0.0 301 -999\n"
    )
    result = diagnose_run.diagnose_gcmc_run(log_paths=[log], monitor_path=monitor, expected_files=[])
    assert result["status"] == "warning"
    assert "basal_proxy_large_initial_relaxation" in result["warnings"]
    assert result["water_summary"]["basal_proxy_initial_raw"] == 46.6
    assert result["water_summary"]["basal_proxy_final"] == 19.8
    assert result["water_summary"]["basal_proxy_large_initial_relaxation"] is True

def test_gcmc_known_warnings_are_not_fatal(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text(
        "WARNING: Neighbor exclusions used with KSpace solver may give inconsistent Coulombic energies\n"
        "WARNING: System is not charge neutral, net charge = 0.004\n"
        "WARNING: fix gcmc using full_energy option\n"
    )
    write_gcmc_monitor(monitor)
    result = diagnose_run.diagnose_gcmc_run(log_paths=[log], monitor_path=monitor, expected_files=[])
    assert result["status"] == "warning"
    assert "gcmc_full_energy" in result["known_warnings"]


def test_gcmc_missing_water_columns_fail(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text("Dangerous builds = 0\n")
    write_gcmc_monitor(monitor, short=True)
    result = diagnose_run.diagnose_gcmc_run(log_paths=[log], monitor_path=monitor, expected_files=[])
    assert result["status"] == "failed"


def test_gcmc_nonfinite_basal_proxy_fails(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text("Dangerous builds = 0\n")
    write_gcmc_monitor(monitor, bad_basal="nan")
    result = diagnose_run.diagnose_gcmc_run(log_paths=[log], monitor_path=monitor, expected_files=[])
    assert result["status"] == "failed"


def test_gcmc_ion_count_change_fails(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text("v_nexchangeable_ions = 19\n")
    write_gcmc_monitor(monitor)
    result = diagnose_run.diagnose_gcmc_run(
        log_paths=[log], monitor_path=monitor, expected_files=[], expected_ion_count=20
    )
    assert result["status"] == "failed"


def test_gcmc_ion_count_parsed_from_thermo_table(tmp_path: Path) -> None:
    log = tmp_path / "log.lammps"
    monitor = tmp_path / "monitor.dat"
    log.write_text(
        "Step Temp v_nexchangeable_ions\n"
        "1000 300 20\n"
        "2000 301 20\n"
        "Dangerous builds = 0\n"
    )
    write_gcmc_monitor(monitor)
    result = diagnose_run.diagnose_gcmc_run(
        log_paths=[log], monitor_path=monitor, expected_files=[], expected_ion_count=20
    )
    assert result["status"] == "ok"
    assert result["ion_summary"]["observed_initial"] == 20
    assert result["ion_summary"]["observed_final"] == 20

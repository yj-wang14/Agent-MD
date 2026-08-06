from __future__ import annotations

from mtagent import generate_gcmc_input, run_cycle


def test_rh_to_tag_values() -> None:
    for module in (generate_gcmc_input, run_cycle):
        assert module.rh_to_tag(0.9) == "rh0p90"
        assert module.rh_to_tag(0.05) == "rh0p05"
        assert module.rh_to_tag(1.0) == "rh1p00"


def test_find_latest_restart_prefers_matching_rh_tag(tmp_path) -> None:
    (tmp_path / "restart.gcmc_rh0p70.9999999").write_text("")
    (tmp_path / "restart.gcmc_rh0p90.1200000").write_text("")
    (tmp_path / "restart.gcmc_rh0p90.1600000").write_text("")

    restart, tag_matched = generate_gcmc_input.find_latest_restart(tmp_path, tag="rh0p90")

    assert restart is not None
    assert restart.name == "restart.gcmc_rh0p90.1600000"
    assert tag_matched is True


def test_find_latest_restart_falls_back_when_no_matching_tag(tmp_path) -> None:
    (tmp_path / "restart.gcmc_rh0p70.1000000").write_text("")
    (tmp_path / "restart.gcmc_rh0p50.2000000").write_text("")

    restart, tag_matched = generate_gcmc_input.find_latest_restart(tmp_path, tag="rh0p90")

    assert restart is not None
    assert restart.name == "restart.gcmc_rh0p50.2000000"
    assert tag_matched is False


def test_find_latest_restart_prefers_numeric_over_matching_final(tmp_path) -> None:
    (tmp_path / "restart.gcmc_rh0p90.final").write_text("")
    (tmp_path / "restart.gcmc_rh0p90.1200000").write_text("")

    restart, tag_matched = generate_gcmc_input.find_latest_restart(tmp_path, tag="rh0p90")

    assert restart is not None
    assert restart.name == "restart.gcmc_rh0p90.1200000"
    assert tag_matched is True
    assert generate_gcmc_input.restart_kind(restart) == "numeric"


def test_find_latest_restart_uses_matching_final_when_no_numeric_exists(tmp_path) -> None:
    (tmp_path / "restart.gcmc_rh0p90.final").write_text("")

    restart, tag_matched = generate_gcmc_input.find_latest_restart(tmp_path, tag="rh0p90")

    assert restart is not None
    assert restart.name == "restart.gcmc_rh0p90.final"
    assert tag_matched is True
    assert generate_gcmc_input.restart_kind(restart) == "final"


def test_find_latest_restart_ignores_unrelated_rh_restart_when_matching_final_exists(tmp_path) -> None:
    (tmp_path / "restart.gcmc_rh0p70.9999999").write_text("")
    (tmp_path / "restart.gcmc_rh0p90.final").write_text("")

    restart, tag_matched = generate_gcmc_input.find_latest_restart(tmp_path, tag="rh0p90")

    assert restart is not None
    assert restart.name == "restart.gcmc_rh0p90.final"
    assert tag_matched is True

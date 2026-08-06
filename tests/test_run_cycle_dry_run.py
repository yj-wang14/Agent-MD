from __future__ import annotations

import json
import sys
from pathlib import Path

from mtagent import run_cycle


ROOT = Path(__file__).resolve().parents[1]


def minimal_case(tmp_path: Path) -> Path:
    molecule_template = tmp_path / "SPCEH2O_types_8_10.txt"
    molecule_template.write_text("# placeholder molecule template for CLI validation\n")
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        f"""case:
  temperature: 300.0
water:
  molecule_template: {molecule_template}
gcmc:
  segment_steps: 500000
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
equilibrium:
  window_steps: 500000
"""
    )
    return case_path


def write_monitor(path: Path) -> None:
    lines = []
    for i in range(60):
        step = i * 1000
        inter = 10.0
        bottom = float(i)
        top = 0.0
        ext = bottom + top
        total = inter + ext
        lines.append(
            f"{step} {total} {inter} {bottom} {top} {ext} "
            "20.0 40.0 0.1 0.1 0.1 0.1 300.0 -1000.0"
        )
    path.write_text("\n".join(lines) + "\n")


def test_run_cycle_dry_run_writes_preview_status_without_touching_formal_json(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    write_monitor(run_dir / "monitor_gcmc_rh0p90.dat")
    (run_dir / "restart.gcmc_rh0p90.59000").write_text("")
    case_path = minimal_case(tmp_path)

    formal_names = [
        "equilibrium_status.json",
        "manager_decision.json",
        "input_generation_status.json",
        "cycle_status.json",
    ]
    for name in formal_names:
        (run_dir / name).write_text("sentinel")

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cycle.py",
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )
    run_cycle.main()

    for name in formal_names:
        assert (run_dir / name).read_text() == "sentinel"

    for name in [
        "equilibrium_status.preview.json",
        "manager_decision.preview.json",
        "input_generation_status.preview.json",
        "cycle_status.preview.json",
    ]:
        assert (run_dir / name).exists()

    generation_preview = json.loads((run_dir / "input_generation_status.preview.json").read_text())
    cycle_preview = json.loads((run_dir / "cycle_status.preview.json").read_text())

    assert generation_preview["effective_segment_steps"] == 1000
    assert generation_preview["run_line"] == "run 1000"
    assert generation_preview["input_file_written"] is False
    assert cycle_preview["segment_steps_override"] == 1000


def previous_window_drift_monitor() -> str:
    rows = []
    for i in range(2101):
        step = i * 1000
        if step <= 1000000:
            ext = step / 100000.0 * 5.0
        else:
            ext = 50.0
        inter = 300.0
        bottom = int(ext // 2)
        top = int(round(ext - bottom))
        total = inter + bottom + top
        rows.append(
            f"{step} {total:.3f} {inter:.1f} {bottom} {top} {bottom + top:.3f} "
            "19.8 43 0.1 0.1 0 0 300 -1000"
        )
    return "\n".join(rows) + "\n"


def test_run_cycle_uses_strict_handoff_analyzer_before_equilibrated_exit(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "monitor_gcmc_rh0p90.dat").write_text(previous_window_drift_monitor())
    (run_dir / "restart.gcmc_rh0p90.2100000").write_text("restart\n")
    case_path = minimal_case(tmp_path)

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cycle.py",
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )
    run_cycle.main()

    equilibrium = json.loads((run_dir / "equilibrium_status.preview.json").read_text())
    decision = json.loads((run_dir / "manager_decision.preview.json").read_text())
    cycle = json.loads((run_dir / "cycle_status.preview.json").read_text())

    assert equilibrium["status"] == "marginal"
    assert equilibrium["checks"]["previous_external_water_slope_ok"] is False
    assert decision["action"] == "continue_current_rh"
    assert decision["next_segment_steps"] > 0
    assert cycle["status"] == "completed_without_run"
    assert cycle["analyzer_settings"]["window_steps"] == 1000000.0
    assert cycle["analyzer_settings"]["require_previous_window_slopes"] is True


def low_max_case(tmp_path: Path) -> Path:
    path = minimal_case(tmp_path)
    with path.open("a") as f:
        f.write("adaptive_extension:\n  max_total_steps_per_rh: 1000000\n")
    return path


def test_run_cycle_max_total_steps_override_allows_continuation(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "monitor_gcmc_rh0p90.dat").write_text(previous_window_drift_monitor())
    (run_dir / "restart.gcmc_rh0p90.2100000").write_text("restart\n")
    case_path = low_max_case(tmp_path)

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cycle.py",
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
            "--max-total-steps-per-rh-override", "5000000",
        ],
    )
    run_cycle.main()

    decision = json.loads((run_dir / "manager_decision.preview.json").read_text())
    cycle = json.loads((run_dir / "cycle_status.preview.json").read_text())

    assert decision["action"] == "continue_current_rh"
    assert decision["max_total_steps_per_rh"] == 5000000
    assert cycle["max_total_steps_per_rh_override"] == 5000000
    assert cycle["status"] == "completed_without_run"


def test_run_cycle_script_mode_imports_shared_analyzer(tmp_path) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    write_monitor(run_dir / "monitor_gcmc_rh0p90.dat")
    (run_dir / "restart.gcmc_rh0p90.59000").write_text("restart\n")
    case_path = minimal_case(tmp_path)

    result = run_cycle.subprocess.run(
        [
            sys.executable,
            "mtagent/run_cycle.py",
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    cycle_preview = json.loads((run_dir / "cycle_status.preview.json").read_text())
    assert cycle_preview["analyzer_settings"]["window_steps"] == 1000000.0


def test_run_cycle_infers_rh_start_step_for_inherited_timestep_budget(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p70"
    run_dir.mkdir()
    (run_dir / "equilibrium_status.preview.json").write_text(json.dumps({
        "status": "not_equilibrated",
        "recommendation": "continue_current_rh",
        "step_end": 61_000_000,
        "reasons": [],
        "series": {
            "nwater_ext": {
                "slope_per_100k": 2.0,
                "slope_limit_per_100k": 1.0,
            }
        },
    }))
    (run_dir / "start_next_rh_status.json").write_text(json.dumps({
        "status": "completed",
        "from_final_step": 42_000_000,
        "source_restart": "examples/Test/states/rh_0p90/restart.gcmc_rh0p90.42000000",
    }))
    (run_dir / "in.gcmc_rh0p70_segment_000001").write_text("run 1000\n")
    case_path = minimal_case(tmp_path)

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cycle.py",
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--skip-analyze",
            "--skip-generate",
            "--max-total-steps-per-rh-override", "60_000_000".replace("_", ""),
        ],
    )
    run_cycle.main()

    decision = json.loads((run_dir / "manager_decision.preview.json").read_text())
    cycle = json.loads((run_dir / "cycle_status.preview.json").read_text())

    assert decision["action"] == "continue_current_rh"
    assert decision["rh_start_step"] == 42_000_000
    assert decision["elapsed_steps_current_rh"] == 19_000_000
    assert cycle["rh_start_step"] == 42_000_000
    assert cycle["status"] == "completed_without_run"

from __future__ import annotations

import json
import sys
from pathlib import Path

from mtagent import generate_gcmc_input


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
md:
  neighbor_every: 2
  neighbor_delay: 0
  neighbor_check: yes
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


def write_decision(run_dir: Path, next_segment_steps: int = 500000) -> None:
    (run_dir / "manager_decision.json").write_text(
        json.dumps({"action": "continue_current_rh", "next_segment_steps": next_segment_steps})
    )


def run_generator_cli(monkeypatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["generate_gcmc_input.py", *args])
    generate_gcmc_input.main()


def test_dry_run_segment_steps_override_status_reports_run_1000(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "restart.gcmc_rh0p90.1600000").write_text("")
    write_decision(run_dir)
    case_path = minimal_case(tmp_path)

    run_generator_cli(
        monkeypatch,
        [
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )

    formal_status = run_dir / "input_generation_status.json"
    formal_status.write_text("sentinel")

    # Re-run after placing a sentinel formal status file. Dry-run must write preview only.
    run_generator_cli(
        monkeypatch,
        [
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )

    assert formal_status.read_text() == "sentinel"
    status = json.loads((run_dir / "input_generation_status.preview.json").read_text())
    assert status["original_segment_steps"] == 500000
    assert status["effective_segment_steps"] == 1000
    assert status["segment_steps_override"] == 1000
    assert status["run_line"] == "run 1000"
    assert status["input_file_written"] is False


def test_non_dry_run_writes_formal_status_and_input(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    (run_dir / "restart.gcmc_rh0p90.1600000").write_text("")
    write_decision(run_dir)
    case_path = minimal_case(tmp_path)

    run_generator_cli(
        monkeypatch,
        [
            "--run-dir", str(run_dir),
            "--case", str(case_path),
        ],
    )

    formal_status = run_dir / "input_generation_status.json"
    status = json.loads(formal_status.read_text())
    input_path = Path(status["input_file"])

    assert formal_status.exists()
    assert status["status"] == "generated"
    assert status["input_file_written"] is True
    assert status["effective_segment_steps"] == 500000
    assert input_path.exists()
    input_text = input_path.read_text()
    assert "run 500000" in input_text
    assert "neigh_modify every 2 delay 0 check yes" in input_text
    assert status["neighbor_settings"] == {"every": 2, "delay": 0, "check": "yes"}
    assert status["neigh_modify"] == "every 2 delay 0 check yes"


def test_default_segment_steps_uses_manager_decision(tmp_path) -> None:
    case_cfg = {
        "case": {"temperature": 300.0},
        "gcmc": {"segment_steps": 500000},
        "regions": {
            "gcmc": {
                "style": "block",
                "xlo": 0.1,
                "xhi": 1.0,
                "ylo": 0.1,
                "yhi": 1.0,
                "zlo": 0.1,
                "zhi": 1.0,
                "units": "box",
            }
        },
        "water": {"molecule_template": "assets/forcefields/SPCEH2O_types_8_10.txt"},
    }
    decision = {"next_segment_steps": 500000}

    text = generate_gcmc_input.generate_input(
        case_cfg=case_cfg,
        decision=decision,
        run_dir=tmp_path,
        restart_file=Path("restart.gcmc_rh0p90.1600000"),
        output_input=tmp_path / "in.gcmc_rh0p90_segment_001",
        rh=0.9,
    )

    assert "# Segment steps = 500000" in text
    assert "run 500000" in text
    assert "neigh_modify every 2 delay 0 check yes" in text


def test_dry_run_uses_final_restart_and_records_metadata(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "rh_0p90"
    run_dir.mkdir()
    final_restart = run_dir / "restart.gcmc_rh0p90.final"
    final_restart.write_text("")
    write_decision(run_dir)
    case_path = minimal_case(tmp_path)

    run_generator_cli(
        monkeypatch,
        [
            "--run-dir", str(run_dir),
            "--case", str(case_path),
            "--dry-run",
            "--segment-steps-override", "1000",
        ],
    )

    status = json.loads((run_dir / "input_generation_status.preview.json").read_text())
    assert status["restart_file"] == str(final_restart.resolve())
    assert status["selected_restart"] == str(final_restart.resolve())
    assert status["selected_restart_kind"] == "final"
    assert status["restart_tag_matched"] is True
    assert status["warnings"]
    assert "No numeric restart matching rh0p90" in status["warnings"][0]


def test_continuation_neighbor_every_override_is_respected(tmp_path) -> None:
    case_cfg = {
        "case": {"temperature": 300.0},
        "md": {"neighbor_every": 4, "neighbor_delay": 0, "neighbor_check": "yes"},
        "gcmc": {"segment_steps": 500000},
        "regions": {
            "gcmc": {
                "style": "block",
                "xlo": 0.1,
                "xhi": 1.0,
                "ylo": 0.1,
                "yhi": 1.0,
                "zlo": 0.1,
                "zhi": 1.0,
                "units": "box",
            }
        },
        "water": {"molecule_template": "assets/forcefields/SPCEH2O_types_8_10.txt"},
    }
    text = generate_gcmc_input.generate_input(
        case_cfg=case_cfg,
        decision={"next_segment_steps": 500000},
        run_dir=tmp_path,
        restart_file=Path("restart.gcmc_rh0p90.1600000"),
        output_input=tmp_path / "in.gcmc_rh0p90_segment_001",
        rh=0.9,
    )

    assert "neigh_modify every 4 delay 0 check yes" in text

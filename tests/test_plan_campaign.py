from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from mtagent import plan_campaign


def write_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "examples" / "campaigns"
    campaign_dir.mkdir(parents=True)
    campaign_path = campaign_dir / "campaign.yaml"
    campaign_path.write_text(
        """campaign:
  id: test_campaign
  dry_run_only: true
templates:
  claycode_yaml: assets/claycode/MyMont1.yaml
  claycode_csv: assets/claycode/exp_clay.csv
  water_molecule_template: assets/forcefields/SPCEH2O_types_8_10.txt
geometry:
  clay_type: D21
  x_cells: 5
  y_cells: 4
  n_sheets: 2
rh_path: [0.90, 0.70]
simulation_policy:
  pre_gcmc_equilibration_steps: 100000
  initial_rh_steps: 100000
  continuation_steps: 500000
  max_steps_per_rh: 2000000
  equilibrium_window_steps: 500000
systems:
  - system_id: Mt_Na_LC050_N20
    cation: Na
    valence: 1
    substitution_amount_x: 0.5
    expected_total_cation_count: 20
    expected_partition:
      bottom_external: 5
      interlayer: 10
      top_external: 5
  - system_id: Mt_Ca_LC040_N8
    cation: Ca
    valence: 2
    substitution_amount_x: 0.4
    expected_total_cation_count: 8
    expected_partition:
      bottom_external: 2
      interlayer: 4
      top_external: 2
"""
    )
    return campaign_path


def write_template_inputs(tmp_path: Path) -> None:
    claycode_dir = tmp_path / "assets" / "claycode"
    claycode_dir.mkdir(parents=True)
    (claycode_dir / "MyMont1.yaml").write_text("SYSNAME: MyMont-1\n")
    (claycode_dir / "exp_clay.csv").write_text("sheet,element,MyMont-1\n")
    ff_dir = tmp_path / "assets" / "forcefields"
    ff_dir.mkdir(parents=True)
    (ff_dir / "SPCEH2O_types_8_10.txt").write_text("3 atoms\n")


def test_campaign_yaml_parses_and_validates_counts(tmp_path: Path) -> None:
    campaign_path = write_campaign(tmp_path)
    data = yaml.safe_load(campaign_path.read_text())

    plan_campaign.validate_campaign(data)

    assert data["systems"][0]["expected_total_cation_count"] == 20
    assert data["systems"][0]["expected_partition"] == {
        "bottom_external": 5,
        "interlayer": 10,
        "top_external": 5,
    }
    assert data["systems"][1]["expected_total_cation_count"] == 8
    assert data["systems"][1]["expected_partition"] == {
        "bottom_external": 2,
        "interlayer": 4,
        "top_external": 2,
    }


def test_campaign_validation_rejects_wrong_partition(tmp_path: Path) -> None:
    campaign_path = write_campaign(tmp_path)
    data = yaml.safe_load(campaign_path.read_text())
    data["systems"][1]["expected_partition"]["top_external"] = 3

    with pytest.raises(ValueError, match="expected_partition.top_external"):
        plan_campaign.validate_campaign(data)


def test_dry_run_plan_contains_systems_rh_points_and_preview_commands(tmp_path: Path, monkeypatch) -> None:
    write_template_inputs(tmp_path)
    campaign_path = write_campaign(tmp_path)
    monkeypatch.chdir(tmp_path)

    plan = plan_campaign.make_plan(campaign_path, base_dir=tmp_path)

    assert plan["campaign_id"] == "test_campaign"
    assert [system["system_id"] for system in plan["systems"]] == ["Mt_Na_LC050_N20", "Mt_Ca_LC040_N8"]
    assert plan["rh_path"] == [0.9, 0.7]
    stages = {task["stage"] for task in plan["planned_tasks"]}
    assert "plan_claycode_inputs" in stages
    assert "run_claycode" in stages
    assert "prepare_case" in stages
    assert "run_equilibrate" in stages
    assert "run_initial_rh_0p90" in stages
    assert "analyze_rh_0p90" in stages
    assert "continue_or_archive_rh_0p90" in stages
    assert "start_next_rh_0p70" in stages
    assert "run_initial_rh_0p70" in stages
    assert "analyze_rh_0p70" in stages
    assert "continue_or_archive_rh_0p70" in stages
    assert all("command_preview" in task for task in plan["planned_tasks"])
    assert not any(task.get("ran") for task in plan["planned_tasks"])


def test_status_classification_missing_vs_existing_small_files(tmp_path: Path, monkeypatch) -> None:
    write_template_inputs(tmp_path)
    campaign_path = write_campaign(tmp_path)
    monkeypatch.chdir(tmp_path)

    missing_plan = plan_campaign.make_plan(campaign_path, base_dir=tmp_path)
    na_plan_task = next(
        task for task in missing_plan["planned_tasks"]
        if task["system_id"] == "Mt_Na_LC050_N20" and task["stage"] == "plan_claycode_inputs"
    )
    assert na_plan_task["status"] == "ready"

    ca_inputs = tmp_path / "examples" / "Mt_Ca_LC040_N8" / "claycode_inputs"
    ca_inputs.mkdir(parents=True)
    for name in [
        "Mt_Ca_LC040_N8.yaml",
        "Mt_Ca_LC040_N8.csv",
        "Mt_Ca_LC040_N8.metadata.json",
        "claycode_input_plan.json",
    ]:
        (ca_inputs / name).write_text("{}\n")
    (tmp_path / "case.Mt_Ca_LC040_N8.yaml").write_text("case:\n  name: Mt_Ca_LC040_N8\n")

    existing_plan = plan_campaign.make_plan(campaign_path, base_dir=tmp_path)
    ca_system = next(system for system in existing_plan["systems"] if system["system_id"] == "Mt_Ca_LC040_N8")
    assert ca_system["small_records"]["planner_inputs_exist"] is True
    assert ca_system["small_records"]["case_file_exists"] is True
    ca_plan_task = next(
        task for task in existing_plan["planned_tasks"]
        if task["system_id"] == "Mt_Ca_LC040_N8" and task["stage"] == "plan_claycode_inputs"
    )
    assert ca_plan_task["status"] == "completed"


def test_status_classification_reports_missing_required_inputs(tmp_path: Path, monkeypatch) -> None:
    campaign_path = write_campaign(tmp_path)
    monkeypatch.chdir(tmp_path)

    plan = plan_campaign.make_plan(campaign_path, base_dir=tmp_path)

    na_plan_task = next(
        task for task in plan["planned_tasks"]
        if task["system_id"] == "Mt_Na_LC050_N20" and task["stage"] == "plan_claycode_inputs"
    )
    assert na_plan_task["status"] == "missing"


def test_cli_writes_json_and_markdown_outputs(tmp_path: Path, monkeypatch) -> None:
    write_template_inputs(tmp_path)
    campaign_path = write_campaign(tmp_path)
    output = tmp_path / "plan.json"
    markdown = tmp_path / "plan.md"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan_campaign.py",
            "--campaign", str(campaign_path),
            "--output", str(output),
            "--markdown", str(markdown),
        ],
    )

    plan_campaign.main()

    saved = json.loads(output.read_text())
    assert saved["campaign_id"] == "test_campaign"
    assert len(saved["systems"]) == 2
    assert "Campaign Plan" in markdown.read_text()

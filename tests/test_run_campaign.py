from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from mtagent import plan_campaign, run_campaign


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
"""
    )
    return campaign_path


def write_templates(tmp_path: Path) -> None:
    claycode = tmp_path / "assets" / "claycode"
    claycode.mkdir(parents=True)
    (claycode / "MyMont1.yaml").write_text(
        """OUTPATH: .
SYSNAME: MyMont-1
BUILD: new
CLAY_COMP: exp_clay.csv
CLAY_TYPE: D21
X_CELLS: 5
Y_CELLS: 4
N_SHEETS: 2
"""
    )
    (claycode / "exp_clay.csv").write_text("sheet,element,MyMont-1\n")
    (tmp_path / "case.yaml").write_text(
        """case:
  name: legacy_template
  temperature: 300.0
paths:
  example_dir: examples/Mt_Oct050_Na
  template_dir: templates
  script_dir: scripts
  agent_dir: mtagent
  raw_gro: examples/Mt_Oct050_Na/raw/MyMont-1_5_4.gro
  raw_top: examples/Mt_Oct050_Na/raw/MyMont-1_5_4.top
  raw_dir: examples/Mt_Oct050_Na/raw
  forcefield_file: assets/forcefields/clayff-paper-2021
  generated_dir: examples/Mt_Oct050_Na/generated
  prepared_dir: examples/Mt_Oct050_Na/inputs
water:
  model: SPCE
  molecule_template: assets/forcefields/SPCEH2O_types_8_10.txt
  oxygen_type: 8
  hydrogen_type: 10
gcmc:
  region: gcmc_region
  temperature: 300.0
md:
  neighbor_every: 2
  neighbor_delay: 0
  neighbor_check: true
  reinitialize_velocity_on_restart: false
regions:
  interlayer_padding: 2.0
equilibration:
  run_dir: examples/Mt_Oct050_Na/equilibration
"""
    )


def planner_files(tmp_path: Path) -> list[Path]:
    base = tmp_path / "examples" / "Mt_Na_LC050_N20" / "claycode_inputs"
    return [
        base / "Mt_Na_LC050_N20.yaml",
        base / "Mt_Na_LC050_N20.csv",
        base / "Mt_Na_LC050_N20.metadata.json",
        base / "claycode_input_plan.json",
    ]


def raw_files(tmp_path: Path) -> tuple[Path, Path]:
    raw = tmp_path / "examples" / "Mt_Na_LC050_N20" / "raw"
    return raw / "Mt_Na_LC050_N20_5_4.gro", raw / "Mt_Na_LC050_N20_5_4.top"


def execute_planning_action(tmp_path: Path, campaign: Path) -> None:
    run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )


def fake_successful_claycode(command, cwd, stdout=None, stderr=None):
    assert command[:3] == ["ClayCode", "builder", "-f"]
    cwd = Path(cwd)
    output_dir = cwd / "Mt_Na_LC050_N20"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "Mt_Na_LC050_N20_5_4.gro").write_text("mock gro\n")
    (output_dir / "Mt_Na_LC050_N20_5_4.top").write_text("mock top\n")
    if stdout:
        stdout.write("mock stdout\n")
    if stderr:
        stderr.write("")
    return SimpleNamespace(returncode=0)


def test_dry_run_creates_plan_and_state_but_does_not_execute(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["status"] == "dry_run"
    assert summary["actions"][0]["stage"] == "plan_claycode_inputs"
    assert (campaign.with_suffix(".plan.json")).exists()
    assert (campaign.with_suffix(".plan.md")).exists()
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert state["campaign_id"] == "test_campaign"
    assert state["execution_history"] == []
    assert not any(path.exists() for path in planner_files(tmp_path))


def test_execute_next_runs_only_plan_claycode_inputs_and_writes_state(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "plan_claycode_inputs"
    assert summary["actions"][0]["status"] == "completed"
    assert all(path.exists() for path in planner_files(tmp_path))
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert state["completed_tasks"] == ["Mt_Na_LC050_N20:plan_claycode_inputs"]
    assert state["execution_history"][0]["mode"] == "generated"


def test_run_claycode_is_blocked_if_planning_outputs_are_missing(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    plan = plan_campaign.make_plan(campaign, base_dir=tmp_path)

    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_claycode")

    assert task["status"] == "blocked"


def test_run_claycode_is_previewed_in_dry_run_but_not_executed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("dry-run must not execute ClayCode")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "run_claycode"
    assert "run_claycode.py" in summary["actions"][0]["command_preview"]
    assert not any(path.exists() for path in raw_files(tmp_path))


def test_execute_next_runs_mocked_run_claycode_and_updates_state(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_claycode)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "run_claycode"
    assert action["status"] == "completed"
    assert action["return_code"] == 0
    assert all(path.exists() for path in raw_files(tmp_path))
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_claycode" in state["completed_tasks"]
    assert state["next_recommended_action"]["stage"] == "create_case_file"


def test_failed_mocked_run_claycode_records_failed_task_and_stops(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)

    def failed_claycode(command, cwd, stdout=None, stderr=None):
        if stderr:
            stderr.write("mock failure\n")
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(run_campaign.subprocess, "run", failed_claycode)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "failed"
    assert action["reason"] == "claycode_failed"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_claycode" in state["failed_tasks"]
    assert len(state["execution_history"]) == 2


def test_existing_raw_outputs_make_run_claycode_idempotent(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    gro, top = raw_files(tmp_path)
    gro.parent.mkdir(parents=True)
    gro.write_text("existing gro\n")
    top.write_text("existing top\n")

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("existing raw files should avoid rerunning ClayCode")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_claycode")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["mode"] == "already_exists"


def test_max_actions_one_executes_only_one_action(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_claycode)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert len(summary["actions"]) == 1
    assert summary["actions"][0]["stage"] == "run_claycode"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert len(state["execution_history"]) == 2


def test_no_lammps_gcmc_or_qsub_commands_are_called(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    seen_commands = []

    def checked_subprocess(command, cwd, stdout=None, stderr=None):
        seen_commands.append(command)
        assert command[0] == "ClayCode"
        assert not any(token in command[0] for token in ["lmp", "mpirun", "qsub"])
        return fake_successful_claycode(command, cwd, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(run_campaign.subprocess, "run", checked_subprocess)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"
    assert seen_commands == [["ClayCode", "builder", "-f", "Mt_Na_LC050_N20.yaml"]]


def write_case_file(tmp_path: Path) -> Path:
    case = tmp_path / "case.Mt_Na_LC050_N20.yaml"
    case.write_text(
        """case:
  name: Mt_Na_LC050_N20
  temperature: 300.0
paths:
  example_dir: examples/Mt_Na_LC050_N20
  raw_gro: examples/Mt_Na_LC050_N20/raw/Mt_Na_LC050_N20_5_4.gro
  raw_top: examples/Mt_Na_LC050_N20/raw/Mt_Na_LC050_N20_5_4.top
  raw_dir: examples/Mt_Na_LC050_N20/raw
  forcefield_file: assets/forcefields/clayff-paper-2021
  generated_dir: examples/Mt_Na_LC050_N20/generated
  prepared_dir: examples/Mt_Na_LC050_N20/inputs
structure:
  claycode_model: Mt_Na_LC050_N20
  cation: Na
  target_ion_distribution:
    bottom_external: 5
    interlayer: 10
    top_external: 5
water:
  molecule_template: assets/forcefields/SPCEH2O_types_8_10.txt
"""
    )
    ff = tmp_path / "assets" / "forcefields"
    ff.mkdir(parents=True, exist_ok=True)
    (ff / "SPCEH2O_types_8_10.txt").write_text("Types\n1 8\n2 10\n")
    (ff / "clayff-paper-2021").write_text("mock forcefield\n")
    return case


def write_raw_files(tmp_path: Path) -> None:
    gro, top = raw_files(tmp_path)
    gro.parent.mkdir(parents=True, exist_ok=True)
    gro.write_text("mock gro\n")
    top.write_text("mock top\n")


def write_valid_prepared_outputs(tmp_path: Path) -> None:
    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    inputs = tmp_path / "examples" / "Mt_Na_LC050_N20" / "inputs"
    generated.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "Mt_Na_LC050_N20_prepared.data").write_text("LAMMPS data\n")
    (inputs / "Mt_Na_LC050_N20_groups_regions.inc").write_text(
        "group exchangeable_ions type 11\ngroup sodium union exchangeable_ions\n"
    )
    (generated / "Mt_Na_LC050_N20_v2.type_report.csv").write_text("type,name\n")
    (generated / "Mt_Na_LC050_N20_prepared.report.json").write_text(json.dumps({
        "target_ion_distribution": {"bottom_external": 5, "interlayer": 10, "top_external": 5},
        "ion_distribution_after": {"bottom": 5, "interlayer": 10, "top": 5},
        "type_ids": {"water_oxygen": 8, "water_hydrogen": 10},
    }))
    (generated / "Mt_Na_LC050_N20_prepared.check.json").write_text(json.dumps({
        "total_charge": 0.0,
        "chemistry": {
            "exchangeable_ion_species": "Na",
            "exchangeable_ion_atoms": 20,
            "molecule_id_normalization_check": {
                "enabled": True,
                "clay_lower_mol_ids": [1],
                "clay_upper_mol_ids": [2],
                "water_mol_id_min": 3,
                "sodium_mol_ids": [0],
                "warnings": [],
                "errors": [],
            },
        },
        "warnings": [],
        "errors": [],
        "passed": True,
    }))


def setup_prepare_ready_campaign(tmp_path: Path, campaign: Path) -> None:
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    run_campaign.write_plan(campaign, tmp_path)


def test_prepare_case_is_blocked_if_raw_files_are_missing(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "prepare_case")

    assert task["status"] == "blocked"


def test_prepare_case_is_previewed_in_dry_run_but_not_executed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    write_case_file(tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("dry-run must not execute prepare_case")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "prepare_case"
    assert "prepare_case.py" in summary["actions"][0]["command_preview"]


def test_execute_next_runs_mocked_prepare_case_and_updates_state(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    write_case_file(tmp_path)

    def fake_prepare(command, cwd, stdout=None, stderr=None):
        assert "prepare_case.py" in command[1]
        write_valid_prepared_outputs(Path(cwd))
        if stdout:
            stdout.write("prepared\n")
        if stderr:
            stderr.write("")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", fake_prepare)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "prepare_case"
    assert action["status"] == "completed"
    assert action["validation"]["passed"] is True
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:prepare_case" in state["completed_tasks"]
    assert state["next_recommended_action"]["stage"] == "run_equilibrate"


def test_failed_mocked_prepare_case_records_failed_task_and_stops(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    write_case_file(tmp_path)

    def failed_prepare(command, cwd, stdout=None, stderr=None):
        if stderr:
            stderr.write("prepare failed\n")
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(run_campaign.subprocess, "run", failed_prepare)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "failed"
    assert summary["actions"][0]["reason"] == "prepare_case_failed"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:prepare_case" in state["failed_tasks"]


def test_existing_valid_prepared_outputs_make_prepare_case_idempotent(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    case_path = write_case_file(tmp_path)
    add_start_next_case_settings(case_path)
    write_valid_prepared_outputs(tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("valid prepared outputs should avoid rerunning prepare_case")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "prepare_case")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["mode"] == "already_exists"
    assert result["validation"]["passed"] is True


def test_prepare_case_max_actions_one_executes_only_one_action(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    write_case_file(tmp_path)

    def fake_prepare(command, cwd, stdout=None, stderr=None):
        write_valid_prepared_outputs(Path(cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", fake_prepare)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert len(summary["actions"]) == 1
    assert summary["actions"][0]["stage"] == "prepare_case"


def test_prepare_case_does_not_invoke_lammps_gcmc_or_qsub(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    write_case_file(tmp_path)
    seen = []

    def checked_prepare(command, cwd, stdout=None, stderr=None):
        seen.append(command)
        joined = " ".join(command)
        assert "prepare_case.py" in joined
        assert "run_equilibrate.py" not in joined
        assert "run_initial.py" not in joined
        assert "run_cycle.py" not in joined
        assert "lmp" not in joined
        assert "qsub" not in joined
        write_valid_prepared_outputs(Path(cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", checked_prepare)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"
    assert len(seen) == 1


def test_plan_contains_create_case_file_between_claycode_and_prepare(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    plan = plan_campaign.make_plan(campaign, base_dir=tmp_path)
    stages = [task["stage"] for task in plan["planned_tasks"] if task["system_id"] == "Mt_Na_LC050_N20"]

    assert stages.index("run_claycode") < stages.index("create_case_file") < stages.index("prepare_case")


def test_create_case_file_is_ready_after_raw_outputs_exist(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    plan = run_campaign.write_plan(campaign, tmp_path)
    create_task = next(task for task in plan["planned_tasks"] if task["stage"] == "create_case_file")
    prepare_task = next(task for task in plan["planned_tasks"] if task["stage"] == "prepare_case")

    assert create_task["status"] == "ready"
    assert prepare_task["status"] == "blocked"


def test_execute_next_runs_create_case_file_and_stops_before_prepare(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("create_case_file must not run subprocess commands")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "create_case_file"
    assert action["status"] == "completed"
    case_file = tmp_path / "case.Mt_Na_LC050_N20.yaml"
    assert case_file.exists()
    text = case_file.read_text()
    assert "name: Mt_Na_LC050_N20" in text
    assert "cation: Na" in text
    assert "expected_ion_count: 20" in text
    assert "raw_gro: examples/Mt_Na_LC050_N20/raw/Mt_Na_LC050_N20_5_4.gro" in text
    assert "molecule_template: assets/forcefields/SPCEH2O_types_8_10.txt" in text
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:create_case_file" in state["completed_tasks"]
    assert state["next_recommended_action"]["stage"] == "prepare_case"
    assert len(summary["actions"]) == 1


def test_create_case_file_is_idempotent_and_force_overwrites(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    first = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )
    case_file = tmp_path / "case.Mt_Na_LC050_N20.yaml"
    original = case_file.read_text()
    second_plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in second_plan["planned_tasks"] if task["stage"] == "create_case_file")
    second = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=second_plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert second["mode"] == "already_exists"
    assert case_file.read_text() == original

    case_file.write_text(original.replace("Campaign-generated", "Modified"))
    forced = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=second_plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=True,
    )
    assert first["actions"][0]["status"] == "completed"
    assert forced["status"] == "completed"
    assert forced["mode"] == "overwritten"
    assert "Campaign-generated" in case_file.read_text()



def test_create_case_file_resolves_historical_prepare_case_failure(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    state_path = campaign.with_suffix(".state.json")
    state = json.loads(state_path.read_text())
    state["failed_tasks"] = ["Mt_Na_LC050_N20:prepare_case"]
    state["execution_history"].append({
        "timestamp": "2026-01-01T00:00:00+00:00",
        "task_id": "Mt_Na_LC050_N20:prepare_case",
        "stage": "prepare_case",
        "status": "failed",
        "reason": "missing_case_file",
    })
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("create_case_file must not run subprocess commands")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "create_case_file"
    assert summary["actions"][0]["status"] == "completed"
    refreshed = json.loads(state_path.read_text())
    assert "Mt_Na_LC050_N20:prepare_case" not in refreshed["failed_tasks"]
    assert any(
        entry.get("task_id") == "Mt_Na_LC050_N20:prepare_case"
        and entry.get("reason") == "missing_case_file"
        for entry in refreshed["execution_history"]
    )
    assert any(
        entry.get("task_id") == "Mt_Na_LC050_N20:prepare_case"
        and entry.get("resolved_by_status") == "ready"
        for entry in refreshed.get("resolved_failed_tasks", [])
    )
    assert refreshed["next_recommended_action"]["stage"] == "prepare_case"


def test_successful_task_is_removed_from_active_failed_tasks(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_prepare_ready_campaign(tmp_path, campaign)
    state_path = campaign.with_suffix(".state.json")
    state = json.loads(state_path.read_text())
    state["failed_tasks"] = ["Mt_Na_LC050_N20:create_case_file"]
    state["execution_history"].append({
        "timestamp": "2026-01-01T00:00:00+00:00",
        "task_id": "Mt_Na_LC050_N20:create_case_file",
        "stage": "create_case_file",
        "status": "failed",
        "reason": "missing_raw_inputs",
    })
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("create_case_file must not run subprocess commands")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    refreshed = json.loads(state_path.read_text())
    assert "Mt_Na_LC050_N20:create_case_file" not in refreshed["failed_tasks"]
    assert any(
        entry.get("task_id") == "Mt_Na_LC050_N20:create_case_file"
        and entry.get("reason") == "missing_raw_inputs"
        for entry in refreshed["execution_history"]
    )


def setup_equilibrate_ready_campaign(tmp_path: Path, campaign: Path) -> None:
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    write_case_file(tmp_path)
    write_valid_prepared_outputs(tmp_path)
    run_campaign.write_plan(campaign, tmp_path)


def write_valid_equilibration_outputs(tmp_path: Path, dangerous_builds: int = 0, warning: str = "", handoff: dict | None = None) -> None:
    run_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "equilibration"
    inputs = tmp_path / "examples" / "Mt_Na_LC050_N20" / "inputs"
    run_dir.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "Mt_Na_LC050_N20_equilibrated.data").write_text("equilibrated data\n")
    (inputs / "restart.pre_gcmc.final").write_text("restart\n")
    (run_dir / "log.lammps").write_text(f"{warning}\nDangerous builds = {dangerous_builds}\n")
    (run_dir / "in.equilibrate_pre_gcmc.stdout").write_text("LAMMPS stdout\n")
    (run_dir / "in.equilibrate_pre_gcmc.stderr").write_text("")
    status_doc = {
        "status": "completed",
        "runner": {
            "return_code": 0,
            "stdout": str(run_dir / "in.equilibrate_pre_gcmc.stdout"),
            "stderr": str(run_dir / "in.equilibrate_pre_gcmc.stderr"),
        },
    }
    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    if handoff is not None:
        status_doc["handoff_diagnostics"] = handoff
        status_doc["handoff_status"] = handoff.get("handoff_status", handoff.get("status"))
        (generated / "Mt_Na_LC050_N20.run_equilibrate_diagnostics.json").write_text(json.dumps(handoff))
    (run_dir / "equilibration_status.json").write_text(json.dumps(status_doc))


def fake_successful_equilibrate(command, cwd, stdout=None, stderr=None, text=None):
    joined = " ".join(command)
    assert "run_equilibrate.py" in joined
    assert "--run" in command
    assert "--soft-steps-override" in command
    assert "5000" in command
    assert "--steps-override" in command
    assert "10000" in command
    assert "run_initial.py" not in joined
    assert "run_cycle.py" not in joined
    assert "qsub" not in joined
    write_valid_equilibration_outputs(Path(cwd))
    if stdout:
        stdout.write('{"status":"completed"}\n')
    if stderr:
        stderr.write("")
    return SimpleNamespace(returncode=0)


def test_run_equilibrate_blocked_if_prepare_outputs_missing(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    write_case_file(tmp_path)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_equilibrate")

    assert task["status"] == "blocked"


def test_run_equilibrate_is_previewed_in_dry_run_but_not_executed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("dry-run must not execute run_equilibrate")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "run_equilibrate"
    assert "run_equilibrate.py" in summary["actions"][0]["command_preview"]


def test_execute_next_runs_mocked_run_equilibrate_once(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_equilibrate)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "run_equilibrate"
    assert action["status"] == "completed"
    assert action["diagnostics"]["status"] == "ok"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_equilibrate" in state["completed_tasks"]
    assert state["next_recommended_action"]["stage"] == "run_initial_rh_0p90"
    assert len(summary["actions"]) == 1


def test_failed_mocked_run_equilibrate_records_failed_task(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)

    def failed_equilibrate(command, cwd, stdout=None, stderr=None, text=None):
        if stderr:
            stderr.write("failed\n")
        return SimpleNamespace(returncode=4)

    monkeypatch.setattr(run_campaign.subprocess, "run", failed_equilibrate)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "failed"
    assert summary["actions"][0]["reason"] == "run_equilibrate_failed"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_equilibrate" in state["failed_tasks"]


def test_run_equilibrate_diagnostic_failure_marks_failed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)

    def diagnostic_failure(command, cwd, stdout=None, stderr=None, text=None):
        write_valid_equilibration_outputs(Path(cwd), warning="ERROR: Lost atoms")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", diagnostic_failure)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "failed"
    assert action["reason"] == "equilibration_diagnostics_failed"
    assert action["diagnostics"]["status"] == "failed"


def test_run_equilibrate_known_warnings_do_not_fail(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)

    def known_warning(command, cwd, stdout=None, stderr=None, text=None):
        write_valid_equilibration_outputs(
            Path(cwd),
            warning="WARNING: Neighbor exclusions used with KSpace solver may give inconsistent Coulombic energies",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", known_warning)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "completed"
    assert action["diagnostics"]["status"] == "warning"
    assert "kspace_neighbor_exclusion" in action["diagnostics"]["known_warnings"]



def test_run_equilibrate_handoff_warning_records_completed_with_warnings(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)

    warning_handoff = {
        "status": "warning",
        "handoff_status": "warning",
        "handoff_basal_prepared": 20.0,
        "handoff_basal_equilibrated": 24.0,
        "handoff_basal_drift": 4.0,
        "warnings": ["handoff basal drift 4.000 A exceeds warning threshold 3.000 A"],
        "errors": [],
    }

    def handoff_warning(command, cwd, stdout=None, stderr=None, text=None):
        write_valid_equilibration_outputs(Path(cwd), handoff=warning_handoff)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", handoff_warning)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "completed"
    assert action["completion_status"] == "completed_with_warnings"
    assert action["diagnostics"]["handoff_status"] == "warning"


def test_failed_handoff_keeps_run_initial_blocked(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    failed_handoff = {
        "status": "failed",
        "handoff_status": "failed",
        "handoff_basal_prepared": 20.0,
        "handoff_basal_equilibrated": 35.0,
        "handoff_basal_drift": 15.0,
        "errors": ["handoff basal drift 15.000 A exceeds failed threshold 10.000 A"],
        "warnings": [],
    }
    write_valid_equilibration_outputs(tmp_path, handoff=failed_handoff)

    plan = run_campaign.write_plan(campaign, tmp_path)
    equil = next(task for task in plan["planned_tasks"] if task["stage"] == "run_equilibrate")
    initial = next(task for task in plan["planned_tasks"] if task["stage"] == "run_initial_rh_0p90")
    assert equil["status"] == "ready"
    assert initial["status"] == "blocked"

def test_existing_valid_equilibration_outputs_make_run_equilibrate_idempotent(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    write_valid_equilibration_outputs(tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("valid equilibration outputs should avoid rerunning LAMMPS")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_equilibrate")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["mode"] == "already_exists"


def test_run_equilibrate_does_not_invoke_gcmc_or_qsub(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    seen = []

    def checked_equilibrate(command, cwd, stdout=None, stderr=None, text=None):
        seen.append(command)
        joined = " ".join(command)
        assert "run_equilibrate.py" in joined
        assert "run_initial.py" not in joined
        assert "run_cycle.py" not in joined
        assert "qsub" not in joined
        write_valid_equilibration_outputs(Path(cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", checked_equilibrate)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"
    assert len(seen) == 1


def setup_initial_ready_campaign(tmp_path: Path, campaign: Path) -> None:
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    write_valid_equilibration_outputs(tmp_path)
    run_campaign.write_plan(campaign, tmp_path)


def write_valid_initial_outputs(tmp_path: Path, *, warning: str = "", bad_monitor: str | None = None, status: str = "completed") -> None:
    run_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p90"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "restart.gcmc_rh0p90.final").write_text("restart\n")
    (run_dir / "after_gcmc_rh0p90_initial.data").write_text("data\n")
    (run_dir / "log.lammps").write_text(
        f"{warning}\nDangerous builds = 0\n"
        "Step Temp v_nexchangeable_ions\n"
        "1000 300 20\n"
        "2000 301 20\n"
    )
    if bad_monitor is None:
        (run_dir / "monitor_gcmc_rh0p90.dat").write_text(
            "1000 300 300 0 0 0 19.7 40 0.1 0 0 0 300 -1000\n"
            "2000 320 300 10 10 20 19.8 40 0.2 0 0 0 301 -999\n"
        )
    else:
        (run_dir / "monitor_gcmc_rh0p90.dat").write_text(bad_monitor)
    (run_dir / "in.gcmc_rh0p90_initial.stdout").write_text("stdout\n")
    (run_dir / "in.gcmc_rh0p90_initial.stderr").write_text("")
    (run_dir / "initial_status.json").write_text(json.dumps({
        "status": status,
        "final_restart": str(run_dir / "restart.gcmc_rh0p90.final"),
        "missing_outputs": [],
        "runner": {
            "return_code": 0,
            "stdout": str(run_dir / "in.gcmc_rh0p90_initial.stdout"),
            "stderr": str(run_dir / "in.gcmc_rh0p90_initial.stderr"),
        },
    }))


def fake_successful_initial(command, cwd, stdout=None, stderr=None, text=None):
    joined = " ".join(command)
    assert "run_initial.py" in joined
    assert "--run" in command
    assert "--segment-steps-override" in command
    assert "100000" in command
    assert "run_cycle.py" not in joined
    assert "qsub" not in joined
    write_valid_initial_outputs(Path(cwd))
    if stdout:
        stdout.write('{"status":"completed"}\n')
    if stderr:
        stderr.write("")
    return SimpleNamespace(returncode=0)



def monitor_rows(*, stable: bool, large_basal: bool = False, malformed: bool = False) -> str:
    if malformed:
        return "not numeric\n"
    rows = []
    for i in range(2101):
        step = 1000 * i
        if stable:
            total = 330
            ext = 30
            basal = 19.8 + (0.001 if i % 2 else 0.0)
        else:
            total = 300 + i
            ext = i
            basal = 19.8
        inter = 300
        bottom = ext // 2
        top = ext - bottom
        if large_basal and i == 0:
            basal = 46.6
        rows.append(f"{step} {total} {inter} {bottom} {top} {ext} {basal} 43 0.1 0 0 0 300 -1000")
    return "\n".join(rows) + "\n"


def setup_analyze_ready_campaign(tmp_path: Path, campaign: Path, *, monitor: str | None = None, warning: str = "") -> None:
    setup_initial_ready_campaign(tmp_path, campaign)
    write_valid_initial_outputs(tmp_path, warning=warning, bad_monitor=monitor or monitor_rows(stable=False))
    run_campaign.write_plan(campaign, tmp_path)


def test_analyze_rh_missing_monitor_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign)
    monitor = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p90" / "monitor_gcmc_rh0p90.dat"
    monitor.unlink()
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "failed"
    assert result["analysis"]["recommendation"] == "inspect"


def test_analyze_rh_malformed_monitor_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False, malformed=True))
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "failed"
    assert result["analysis"]["recommendation"] == "inspect"


def test_analyze_stable_monitor_recommends_archive(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=True))
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "completed"
    assert result["analysis"]["status"] == "equilibrated"
    assert result["analysis"]["recommendation"] == "archive"
    assert (tmp_path / result["analysis_path"]).exists()


def test_analyze_increasing_water_recommends_continue(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "completed"
    assert result["analysis"]["status"] in {"not_equilibrated", "marginal"}
    assert result["analysis"]["recommendation"] == "continue"
    assert result["analysis"]["checks"]["external_water_slope_ok"] is False


def test_analyze_large_basal_relaxation_recommends_inspect(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=True, large_basal=True))
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "completed"
    assert result["analysis"]["recommendation"] == "inspect"
    assert result["analysis"]["basal_proxy_large_initial_relaxation"] is True


def test_analyze_ion_count_change_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=True))
    log = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p90" / "log.lammps"
    log.write_text("Dangerous builds = 0\nStep Temp v_nexchangeable_ions\n1000 300 20\n2000 300 19\n")
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )
    assert result["status"] == "failed"
    assert result["analysis"]["ion_count_stable"] is False


def test_analyze_rh_is_read_only_no_lammps(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("analyze action must not run subprocesses")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )
    assert summary["actions"][0]["stage"] == "analyze_rh_0p90"
    assert summary["actions"][0]["status"] == "completed"


def monitor_rows_previous_window_drift() -> str:
    rows = []
    for i in range(2101):
        step = i * 1000
        if step <= 1000000:
            ext = step / 100000.0 * 5.0
        else:
            ext = 50.0
        total = 300.0 + ext
        bottom = int(ext // 2)
        top = int(round(ext - bottom))
        rows.append(f"{step} {total:.3f} 300 {bottom} {top} {ext:.3f} 19.8 43 0.1 0 0 0 300 -1000")
    return "\n".join(rows) + "\n"


def test_analyze_previous_adjacent_window_drift_blocks_archive(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows_previous_window_drift())
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p90")

    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    analysis = result["analysis"]
    assert analysis["status"] == "marginal"
    assert analysis["recommendation"] == "continue"
    assert analysis["criteria"]["window_steps"] == 1000000.0
    assert analysis["checks"]["previous_external_water_slope_ok"] is False
    assert analysis["previous_window"]["series"]["nwater_ext"]["slope_per_100k"] > 1.0


def test_stale_archive_summary_does_not_unlock_rh0p70_handoff(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    summary = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / "rh_0p90" / "summary.json"
    doc = json.loads(summary.read_text())
    doc["analysis_status"] = "marginal"
    doc["analysis_recommendation"] = "continue"
    doc["equilibrium_status"] = "marginal"
    doc["equilibrium_recommendation"] = "continue"
    summary.write_text(json.dumps(doc))

    plan = run_campaign.write_plan(campaign, tmp_path)
    continue_task = next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p90")
    start_task = next(task for task in plan["planned_tasks"] if task["stage"] == "start_next_rh_0p70")

    assert continue_task["status"] == plan_campaign.STATUS_READY
    assert start_task["status"] == plan_campaign.STATUS_BLOCKED


def setup_analyze_rh0p70_ready_campaign(tmp_path: Path, campaign: Path, *, monitor: str | None = None) -> None:
    setup_run_initial_rh0p70_ready_campaign(tmp_path, campaign)
    write_valid_rh0p70_outputs(tmp_path)
    if monitor is not None:
        run_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p70"
        (run_dir / "monitor_gcmc_rh0p70.dat").write_text(monitor)
    run_campaign.write_plan(campaign, tmp_path)


def one_window_stable_rh0p70_monitor() -> str:
    rows = []
    for i in range(1001):
        step = 4110000 + i * 1000
        rows.append(f"{step} 484 294 95 95 190 19.46 43 0.1 0.1 0 0 300 -1000")
    return "\n".join(rows) + "\n"


def test_analyze_rh0p70_monitor_is_read_only_and_recommends_continue_without_previous_window(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_rh0p70_ready_campaign(tmp_path, campaign, monitor=one_window_stable_rh0p70_monitor())

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("analyze_rh_0p70 must not run subprocesses")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p70")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["analysis"]["rh_tag"] == "rh0p70"
    assert result["analysis"]["status"] == "marginal"
    assert result["analysis"]["recommendation"] == "continue"
    assert result["analysis"]["checks"]["previous_window_water_slopes_ok"] is False
    assert "previous adjacent window" in result["analysis"]["reasons"][0]
    assert (tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p70_analysis.json").exists()


def test_analyze_rh0p70_missing_monitor_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_rh0p70_ready_campaign(tmp_path, campaign)
    monitor = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p70" / "monitor_gcmc_rh0p70.dat"
    monitor.unlink()
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "analyze_rh_0p70")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["analysis"]["recommendation"] == "inspect"
    assert any("Missing monitor file" in err for err in result["analysis"]["fatal_errors"])


def test_shared_analyze_stage_parser_supports_rh0p90_and_rh0p70() -> None:
    assert run_campaign.rh_tag_from_analyze_stage("analyze_rh_0p90") == "rh0p90"
    assert run_campaign.rh_tag_from_analyze_stage("analyze_rh0p90") == "rh0p90"
    assert run_campaign.rh_tag_from_analyze_stage("analyze_rh_0p70") == "rh0p70"
    assert run_campaign.rh_tag_from_analyze_stage("analyze_rh0p70") == "rh0p70"
    assert run_campaign.rh_tag_from_analyze_stage("run_initial_rh_0p70") is None


def test_shared_continue_or_archive_stage_parser_supports_rh0p90_and_rh0p70() -> None:
    assert run_campaign.rh_tag_from_continue_or_archive_stage("continue_or_archive_rh_0p90") == "rh0p90"
    assert run_campaign.rh_tag_from_continue_or_archive_stage("continue_or_archive_rh0p90") == "rh0p90"
    assert run_campaign.rh_tag_from_continue_or_archive_stage("continue_or_archive_rh_0p70") == "rh0p70"
    assert run_campaign.rh_tag_from_continue_or_archive_stage("continue_or_archive_rh0p70") == "rh0p70"
    assert run_campaign.rh_tag_from_continue_or_archive_stage("analyze_rh_0p70") is None


def write_rh_analysis(tmp_path: Path, *, recommendation: str, status: str = "not_equilibrated") -> Path:
    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    analysis = generated / "Mt_Na_LC050_N20.rh_0p90_analysis.json"
    analyzer_status = "equilibrated" if status == "equilibrated" and recommendation == "archive" else status
    analyzer_recommendation = "write_data_and_continue_next_rh" if status == "equilibrated" and recommendation == "archive" else "continue_current_rh"
    analysis.write_text(json.dumps({
        "status": status,
        "recommendation": recommendation,
        "system_id": "Mt_Na_LC050_N20",
        "rh_tag": "rh0p90",
        "final_timestep": 2000,
        "fatal_errors": [],
        "known_warnings": ["gcmc_full_energy"],
        "analyzer": {"status": analyzer_status, "recommendation": analyzer_recommendation},
    }))
    return analysis


def setup_continue_or_archive_ready_campaign(tmp_path: Path, campaign: Path, *, recommendation: str = "continue", status: str = "not_equilibrated") -> None:
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    write_rh_analysis(tmp_path, recommendation=recommendation, status=status)
    run_campaign.write_plan(campaign, tmp_path)


def continue_or_archive_task(plan: dict[str, object]) -> dict[str, object]:
    return next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p90")


def fake_successful_continuation(command, cwd, stdout=None, stderr=None, text=None):
    cwd = Path(cwd)
    joined = " ".join(command)
    assert "run_cycle.py" in joined
    assert "--run" in command
    assert "--segment-steps-override" in command
    assert "100000" in command
    assert "--max-total-steps-per-rh-override" in command
    assert command[command.index("--max-total-steps-per-rh-override") + 1] == "2000000"
    assert "archive_rh_result.py" not in joined
    run_dir = cwd / "examples" / "Mt_Na_LC050_N20" / "rh_0p90"
    with (run_dir / "monitor_gcmc_rh0p90.dat").open("a") as f:
        f.write("102000 333 300 16 17 33 19.8 43 0.1 0 0 0 300 -1000\n")
    (run_dir / "restart.gcmc_rh0p90.102000").write_text("restart\n")
    (run_dir / "restart.gcmc_rh0p90.final").write_text("restart\n")
    (run_dir / "cycle_status.json").write_text(json.dumps({"status": "completed_with_run"}))
    (run_dir / "run_status.json").write_text(json.dumps({"status": "completed", "return_code": 0}))
    if stdout:
        stdout.write('{"cycle_status":"completed_with_run"}\n')
    if stderr:
        stderr.write("")
    return SimpleNamespace(returncode=0)


def fake_successful_rh0p70_continuation(command, cwd, stdout=None, stderr=None, text=None):
    cwd = Path(cwd)
    joined = " ".join(command)
    assert "run_cycle.py" in joined
    assert "--run" in command
    assert "--segment-steps-override" in command
    assert "--max-total-steps-per-rh-override" in command
    segment_steps = int(command[command.index("--segment-steps-override") + 1])
    assert segment_steps > 0
    assert "rh_0p70" in command[command.index("--run-dir") + 1]
    assert "archive_rh_result.py" not in joined
    run_dir = cwd / "examples" / "Mt_Na_LC050_N20" / "rh_0p70"
    with (run_dir / "monitor_gcmc_rh0p70.dat").open("a") as f:
        f.write("5120000 485 294 95 96 191 19.46 43 0.1 0 0 0 300 -1000\n")
    (run_dir / "restart.gcmc_rh0p70.5120000").write_text("restart\n")
    (run_dir / "restart.gcmc_rh0p70.final").write_text("restart\n")
    (run_dir / "cycle_status.json").write_text(json.dumps({"status": "completed_with_run"}))
    (run_dir / "run_status.json").write_text(json.dumps({"status": "completed", "return_code": 0}))
    if stdout:
        stdout.write('{"cycle_status":"completed_with_run"}\n')
    if stderr:
        stderr.write("")
    return SimpleNamespace(returncode=0)




def test_auto_runs_analyze_then_stops_before_missing_continue_analysis(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    analysis = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p90_analysis.json"

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=2,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "analyze_rh_0p90"
    assert summary["actions"][0]["status"] == "completed"
    analysis.unlink()
    plan = run_campaign.write_plan(campaign, tmp_path)
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p90")
    allowed, policy = run_campaign.auto_policy_for_task(task=task, state=state, base_dir=tmp_path, stop_before_stage=None)
    assert allowed is False
    assert policy["reason"] == "missing_analysis_json"


def test_auto_runs_continue_or_archive_when_analysis_says_continue(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="continue")
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_continuation)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "continue_or_archive_rh_0p90"
    assert summary["actions"][0]["decision"] == "continue"
    assert summary["actions"][0]["status"] == "completed"
    assert summary["stop_reason"] == "max_actions_reached"


def test_auto_archives_only_when_analyzer_agrees(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="archive", status="equilibrated")
    called = []

    def fake_archive(run_dir, archive_dir=None, rh=None, summary_only=False):
        called.append((run_dir, rh))
        summary_dir = Path(run_dir).parent / "states" / "rh_0p90"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "summary.json").write_text(json.dumps({"final_step": 2000}))
        return {"final_step": 2000, "selected_restart": "mock"}

    monkeypatch.setattr(run_campaign.archive_rh_result, "archive_rh_result", fake_archive)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["decision"] == "archive"
    assert called and called[0][1] == 0.90

    campaign2 = write_campaign(tmp_path / "case2")
    write_templates(tmp_path / "case2")
    setup_continue_or_archive_ready_campaign(tmp_path / "case2", campaign2, recommendation="archive", status="equilibrated")
    analysis = tmp_path / "case2" / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p90_analysis.json"
    doc = json.loads(analysis.read_text())
    doc["analyzer"] = {"status": "marginal", "recommendation": "continue_current_rh"}
    analysis.write_text(json.dumps(doc))
    summary2 = run_campaign.run_campaign(
        campaign_path=campaign2,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path / "case2",
    )
    assert summary2["actions"][0]["reason"] == "analysis_archive_mismatch"


def test_auto_stops_before_new_rh_or_system_boundary(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="archive", status="equilibrated")

    def fake_archive(run_dir, archive_dir=None, rh=None, summary_only=False):
        summary_dir = Path(run_dir).parent / "states" / "rh_0p90"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "summary.json").write_text(json.dumps({"final_step": 2000}))
        return {"final_step": 2000, "selected_restart": "mock"}

    monkeypatch.setattr(run_campaign.archive_rh_result, "archive_rh_result", fake_archive)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=2,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["decision"] == "archive"
    assert summary["actions"][1]["reason"] in {"handoff_boundary", "auto_stage_not_allowlisted"}


def test_auto_max_actions_max_walltime_and_stop_before_stage(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))

    one = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )
    assert one["stop_reason"] == "max_actions_reached"
    assert len(one["actions"]) == 1

    campaign2 = write_campaign(tmp_path / "wall")
    write_templates(tmp_path / "wall")
    setup_analyze_ready_campaign(tmp_path / "wall", campaign2, monitor=monitor_rows(stable=False))
    wall = run_campaign.run_campaign(
        campaign_path=campaign2,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        max_walltime_seconds=0,
        force=False,
        base_dir=tmp_path / "wall",
    )
    assert wall["actions"][0]["reason"] == "max_walltime_seconds_reached"

    campaign3 = write_campaign(tmp_path / "stop")
    write_templates(tmp_path / "stop")
    setup_analyze_ready_campaign(tmp_path / "stop", campaign3, monitor=monitor_rows(stable=False))
    stopped = run_campaign.run_campaign(
        campaign_path=campaign3,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        stop_before_stage="analyze_rh",
        force=False,
        base_dir=tmp_path / "stop",
    )
    assert stopped["actions"][0]["reason"] == "stop_before_stage_matched"


def test_auto_failed_inspect_missing_json_blocks(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="inspect", status="failed")
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )
    assert summary["actions"][0]["reason"] == "analysis_requires_inspection"

    campaign2 = write_campaign(tmp_path / "missing")
    write_templates(tmp_path / "missing")
    setup_continue_or_archive_ready_campaign(tmp_path / "missing", campaign2, recommendation="continue")
    plan = run_campaign.write_plan(campaign2, tmp_path / "missing")
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p90")
    (tmp_path / "missing" / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p90_analysis.json").unlink()
    state = json.loads(campaign2.with_suffix(".state.json").read_text())
    allowed, policy = run_campaign.auto_policy_for_task(task=task, state=state, base_dir=tmp_path / "missing", stop_before_stage=None)
    assert allowed is False
    assert policy["reason"] == "missing_analysis_json"

def test_continue_or_archive_rh0p70_continue_runs_one_continuation_and_recommends_analyze(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_rh0p70_ready_campaign(tmp_path, campaign, monitor=one_window_stable_rh0p70_monitor())
    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "Mt_Na_LC050_N20.rh_0p70_analysis.json").write_text(json.dumps({
        "status": "marginal",
        "recommendation": "continue",
        "system_id": "Mt_Na_LC050_N20",
        "rh_tag": "rh0p70",
        "final_timestep": 5110000,
        "fatal_errors": [],
        "known_warnings": ["gcmc_full_energy"],
        "analyzer": {"status": "marginal", "recommendation": "continue_current_rh"},
    }))
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_rh0p70_continuation)

    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p70")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["decision"] == "continue"
    assert result["return_code"] == 0
    assert result["new_final_timestep"] == 5120000
    assert result["next_recommended_action"] == "analyze_rh_0p70"


def test_continue_or_archive_continue_runs_one_continuation_and_recommends_analyze(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="continue")
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_continuation)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "continue_or_archive_rh_0p90"
    assert action["status"] == "completed"
    assert action["decision"] == "continue"
    assert action["return_code"] == 0
    assert action["new_final_timestep"] == 102000
    assert action["next_recommended_action"] == "analyze_rh_0p90"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert state["next_recommended_action"]["stage"] == "analyze_rh_0p90"


def test_continue_or_archive_archive_calls_archive_logic(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="archive", status="equilibrated")
    called = []

    def fake_archive(run_dir, archive_dir=None, rh=None, summary_only=False):
        called.append((run_dir, rh))
        summary_dir = Path(run_dir).parent / "states" / "rh_0p90"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "summary.json").write_text(json.dumps({"final_step": 2000, "analysis_status": "equilibrated", "analysis_recommendation": "archive"}))
        return {"final_step": 2000, "selected_restart": "mock", "analysis_status": "equilibrated", "analysis_recommendation": "archive"}

    def fail_if_subprocess(*args, **kwargs):  # pragma: no cover
        raise AssertionError("archive branch must not run continuation subprocess")

    monkeypatch.setattr(run_campaign.archive_rh_result, "archive_rh_result", fake_archive)
    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_subprocess)
    plan = run_campaign.write_plan(campaign, tmp_path)
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=continue_or_archive_task(plan),
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["decision"] == "archive"
    assert result["return_code"] == 0
    assert called and called[0][1] == 0.90


def test_continue_or_archive_blocks_archive_when_embedded_analyzer_disagrees(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="archive", status="equilibrated")
    analysis = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p90_analysis.json"
    doc = json.loads(analysis.read_text())
    doc["analyzer"] = {"status": "marginal", "recommendation": "continue_current_rh"}
    analysis.write_text(json.dumps(doc))

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("mismatched archive analysis must not run commands")

    monkeypatch.setattr(run_campaign.archive_rh_result, "archive_rh_result", fail_if_called)
    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=continue_or_archive_task(plan),
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["decision"] == "blocked"
    assert result["reason"] == "analysis_archive_mismatch"


def test_runtime_staging_guard_ignores_source_restart_name() -> None:
    assert run_campaign.is_runtime_or_status_path("mtagent/analyze_gcmc_equilibrium_restart.py") is False
    assert run_campaign.is_runtime_or_status_path("examples/Mt_Na_LC050_N20/rh_0p90/restart.gcmc_rh0p90.3100000") is True
    assert run_campaign.is_runtime_or_status_path("examples/Mt_Na_LC050_N20/rh_0p70/monitor_gcmc_rh0p70.dat") is True
    assert run_campaign.is_runtime_or_status_path("examples/campaigns/na_ca_lc_smoke_campaign.state.json") is True
    assert run_campaign.is_runtime_or_status_path("examples/Mt_Na_LC050_N20/states/rh_0p90/summary.json") is True


def test_continue_or_archive_failed_or_inspect_blocks_without_command(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="inspect", status="failed")

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("blocked analysis must not run commands")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=continue_or_archive_task(plan),
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["decision"] == "blocked"
    assert result["reason"] == "analysis_requires_inspection"
    assert result["command"] is None


def test_continue_or_archive_missing_analysis_json_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = {**continue_or_archive_task(plan), "status": "ready"}
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "missing_analysis_json"
    assert result["decision"] == "blocked"


def test_continue_or_archive_malformed_analysis_json_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    analysis = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated" / "Mt_Na_LC050_N20.rh_0p90_analysis.json"
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text("{bad json")
    plan = run_campaign.write_plan(campaign, tmp_path)
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=continue_or_archive_task(plan),
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "malformed_analysis_json"
    assert result["command"] is None


def write_archived_rh0p90_state(tmp_path: Path) -> Path:
    state_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / "rh_0p90"
    state_dir.mkdir(parents=True, exist_ok=True)
    restart = state_dir / "restart.gcmc_rh0p90.3100000"
    restart.write_text("restart\n")
    (state_dir / "summary.json").write_text(json.dumps({
        "rh": 0.9,
        "final_step": 3100000,
        "archived_restart": "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.3100000",
        "selected_restart": "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.3100000",
        "total_water": 439,
        "interlayer_water": 297,
        "external_water": 142,
        "basal_proxy": 19.8635,
        "analysis_status": "equilibrated",
        "analysis_recommendation": "archive",
        "equilibrium_status": "equilibrated",
        "equilibrium_recommendation": "archive",
    }))
    return state_dir


def add_start_next_case_settings(case_path: Path) -> None:
    case_path.write_text(case_path.read_text() + """gcmc:
  rh_path: [0.90, 0.70]
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
""")


def setup_start_next_rh0p70_ready_campaign(tmp_path: Path, campaign: Path) -> None:
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    case_path = write_case_file(tmp_path)
    add_start_next_case_settings(case_path)
    write_valid_prepared_outputs(tmp_path)
    write_valid_equilibration_outputs(tmp_path)
    write_valid_initial_outputs(tmp_path)
    write_rh_analysis(tmp_path, recommendation="archive", status="equilibrated")
    write_archived_rh0p90_state(tmp_path)
    run_campaign.write_plan(campaign, tmp_path)


def start_next_rh0p70_task(plan: dict[str, object]) -> dict[str, object]:
    return next(task for task in plan["planned_tasks"] if task["stage"] == "start_next_rh_0p70")


def test_start_next_rh0p70_missing_archive_fails(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    write_case_file(tmp_path)
    write_valid_prepared_outputs(tmp_path)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = {**start_next_rh0p70_task(plan), "status": "ready"}

    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "missing_rh_0p90_archive"


def test_start_next_rh0p70_prepares_from_archived_restart(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)

    def fail_if_subprocess(*args, **kwargs):  # pragma: no cover
        raise AssertionError("start_next_rh_0p70 must not run subprocesses")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_subprocess)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    run_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p70"
    expected_restart = "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.3100000"
    assert action["stage"] == "start_next_rh_0p70"
    assert action["status"] == "completed"
    assert action["source_restart"] == expected_restart
    assert action["next_recommended_action"] == "run_initial_rh_0p70"
    assert (run_dir / "in.gcmc_rh0p70_initial").exists()
    assert (run_dir / "start_next_rh_status.json").exists()
    assert not (run_dir / "monitor_gcmc_rh0p70.dat").exists()
    assert not (run_dir / "restart.gcmc_rh0p70.final").exists()


def test_start_next_rh0p70_uses_restart_from_archive_summary(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    state_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / "rh_0p90"
    old_restart = state_dir / "restart.gcmc_rh0p90.3100000"
    new_restart = state_dir / "restart.gcmc_rh0p90.4100000"
    new_restart.write_text("restart\n")
    old_restart.unlink()
    summary = json.loads((state_dir / "summary.json").read_text())
    summary["final_step"] = 4100000
    summary["archived_restart"] = "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.4100000"
    summary["selected_restart"] = summary["archived_restart"]
    (state_dir / "summary.json").write_text(json.dumps(summary))

    monkeypatch.setattr(run_campaign.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no subprocess")))
    plan = run_campaign.write_plan(campaign, tmp_path)
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task={**start_next_rh0p70_task(plan), "status": "ready"},
        campaign_path=campaign,
        base_dir=tmp_path,
        force=True,
    )

    expected = "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.4100000"
    assert result["status"] == "completed"
    assert result["source_restart"] == expected
    assert result["expected_restart"] == expected


def test_start_next_rh0p70_advances_next_action_to_run_initial(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert state["next_recommended_action"]["stage"] == "run_initial_rh_0p70"


def test_start_next_rh0p70_runtime_files_are_not_staged(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    staged = run_campaign.subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert "rh_0p70" not in staged.stdout


def write_valid_rh0p70_outputs(tmp_path: Path, *, warning: str = "") -> None:
    run_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "rh_0p70"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "restart.gcmc_rh0p70.final").write_text("restart\n")
    (run_dir / "after_gcmc_rh0p70_initial.data").write_text("data\n")
    (run_dir / "log.lammps").write_text(
        f"{warning}\nDangerous builds = 0\n"
        "Step Temp v_nexchangeable_ions\n"
        "3100000 300 20\n"
        "4100000 301 20\n"
    )
    (run_dir / "monitor_gcmc_rh0p70.dat").write_text(
        "3100000 439 297 71 71 142 19.86 43.2 0.1 0 0 0 300 -1000\n"
        "4100000 420 297 61 62 123 19.80 43.1 0.2 0 0 0 301 -999\n"
    )
    (run_dir / "in.gcmc_rh0p70_initial.stdout").write_text("stdout\n")
    (run_dir / "in.gcmc_rh0p70_initial.stderr").write_text("")
    (run_dir / "initial_status.json").write_text(json.dumps({
        "status": "completed",
        "final_restart": str(run_dir / "restart.gcmc_rh0p70.final"),
        "missing_outputs": [],
        "runner": {
            "return_code": 0,
            "stdout": str(run_dir / "in.gcmc_rh0p70_initial.stdout"),
            "stderr": str(run_dir / "in.gcmc_rh0p70_initial.stderr"),
        },
    }))


def setup_run_initial_rh0p70_ready_campaign(tmp_path: Path, campaign: Path) -> None:
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )


def test_run_initial_rh0p70_requires_start_status(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_initial_rh_0p70")
    task = {**task, "status": "ready"}

    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "missing_start_next_rh_status"


def test_run_initial_rh0p70_runs_start_next_once_and_recommends_analyze(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_run_initial_rh0p70_ready_campaign(tmp_path, campaign)
    calls = []

    def fake_start_next(**kwargs):
        calls.append(kwargs)
        write_valid_rh0p70_outputs(tmp_path, warning="WARNING: fix gcmc using full_energy option")
        run_dir = kwargs["run_dir"]
        return json.loads((run_dir / "initial_status.json").read_text()) | {
            "runner": {"return_code": 0},
            "status": "completed",
        }

    monkeypatch.setattr(run_campaign.start_next_rh, "start_next_rh", fake_start_next)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "run_initial_rh_0p70"
    assert action["status"] == "completed"
    assert action["return_code"] == 0
    assert action["final_timestep"] == 4100000.0
    assert action["total_water"] == 420.0
    assert action["interlayer_water"] == 297.0
    assert action["external_water"] == 123.0
    assert action["basal_proxy"] == 19.8
    assert action["next_recommended_action"] == "analyze_rh_0p70"
    assert len(calls) == 1
    assert calls[0]["run"] is True
    assert calls[0]["rh"] == 0.70


def test_run_initial_rh0p70_does_not_call_continuation_or_archive(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_run_initial_rh0p70_ready_campaign(tmp_path, campaign)

    def fake_start_next(**kwargs):
        write_valid_rh0p70_outputs(tmp_path)
        run_dir = kwargs["run_dir"]
        return json.loads((run_dir / "initial_status.json").read_text()) | {"runner": {"return_code": 0}, "status": "completed"}

    def fail_if_subprocess(*args, **kwargs):  # pragma: no cover
        raise AssertionError("run_initial_rh_0p70 must not invoke run_cycle/archive subprocesses")

    monkeypatch.setattr(run_campaign.start_next_rh, "start_next_rh", fake_start_next)
    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_subprocess)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"

def test_run_initial_blocked_if_pre_gcmc_restart_missing(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_equilibrate_ready_campaign(tmp_path, campaign)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_initial_rh_0p90")

    assert task["status"] == "blocked"


def test_run_initial_is_previewed_in_dry_run_but_not_executed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("dry-run must not execute run_initial")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["stage"] == "run_initial_rh_0p90"
    assert "run_initial.py" in summary["actions"][0]["command_preview"]


def test_execute_next_runs_mocked_initial_once(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_initial)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["stage"] == "run_initial_rh_0p90"
    assert action["status"] == "completed"
    assert action["diagnostics"]["status"] == "ok"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_initial_rh0p90" in state["completed_tasks"]
    assert state["next_recommended_action"]["stage"] == "analyze_rh_0p90"
    assert len(summary["actions"]) == 1


def test_failed_mocked_initial_records_failed_task(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)

    def failed_initial(command, cwd, stdout=None, stderr=None, text=None):
        if stderr:
            stderr.write("failed\n")
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(run_campaign.subprocess, "run", failed_initial)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "failed"
    assert summary["actions"][0]["reason"] == "run_initial_failed"
    state = json.loads(campaign.with_suffix(".state.json").read_text())
    assert "Mt_Na_LC050_N20:run_initial_rh0p90" in state["failed_tasks"]


def test_initial_diagnostic_failure_marks_failed(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)

    def diagnostic_failure(command, cwd, stdout=None, stderr=None, text=None):
        write_valid_initial_outputs(Path(cwd), warning="ERROR: Lost atoms")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", diagnostic_failure)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "failed"
    assert action["reason"] == "gcmc_diagnostics_failed"
    assert action["diagnostics"]["status"] == "failed"


def test_initial_known_warnings_do_not_fail(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)

    def known_warning(command, cwd, stdout=None, stderr=None, text=None):
        write_valid_initial_outputs(
            Path(cwd),
            warning="WARNING: fix gcmc using full_energy option\nWARNING: System is not charge neutral, net charge = 0.004",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", known_warning)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    action = summary["actions"][0]
    assert action["status"] == "completed"
    assert action["diagnostics"]["status"] == "warning"
    assert "gcmc_full_energy" in action["diagnostics"]["known_warnings"]


def test_existing_valid_initial_outputs_make_action_idempotent(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)
    write_valid_initial_outputs(tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("valid initial outputs should avoid rerunning GCMC")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "run_initial_rh_0p90")
    result = run_campaign.execute_task(
        campaign_cfg=plan_campaign.load_yaml(campaign),
        plan=plan,
        task=task,
        campaign_path=campaign,
        base_dir=tmp_path,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["mode"] == "already_exists"


def test_run_initial_does_not_invoke_cycle_continuation_or_qsub(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_initial_ready_campaign(tmp_path, campaign)
    seen = []

    def checked_initial(command, cwd, stdout=None, stderr=None, text=None):
        seen.append(command)
        joined = " ".join(command)
        assert "run_initial.py" in joined
        assert "run_cycle.py" not in joined
        assert "archive_rh_result.py" not in joined
        assert "qsub" not in joined
        write_valid_initial_outputs(Path(cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_campaign.subprocess, "run", checked_initial)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["status"] == "completed"
    assert len(seen) == 1


def rewrite_campaign_rh_path(campaign: Path, rh_values: list[float]) -> None:
    text = campaign.read_text()
    rh_text = ", ".join(f"{value:.2f}" for value in rh_values)
    text = text.replace("rh_path: [0.90, 0.70]", f"rh_path: [{rh_text}]")
    campaign.write_text(text)


def write_archived_rh_state(tmp_path: Path, rh_tag: str, final_step: int, *, previous_restart: str | None = None) -> Path:
    rh_dir = rh_tag.replace("rh", "rh_")
    state_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / rh_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    restart = state_dir / f"restart.gcmc_{rh_tag}.{final_step}"
    restart.write_text("restart\n")
    restart_rel = f"examples/Mt_Na_LC050_N20/states/{rh_dir}/{restart.name}"
    summary = {
        "rh": run_campaign.rh_value_from_tag(rh_tag),
        "final_step": final_step,
        "archived_restart": restart_rel,
        "selected_restart": restart_rel,
        "source_restart": previous_restart or restart_rel,
        "total_water": 400,
        "interlayer_water": 300,
        "external_water": 100,
        "basal_proxy": 20.0,
        "analysis_status": "equilibrated",
        "analysis_recommendation": "archive",
        "equilibrium_status": "equilibrated",
        "equilibrium_recommendation": "archive",
    }
    (state_dir / "summary.json").write_text(json.dumps(summary))
    return state_dir


def test_generic_rh_metadata_selects_next_rh_from_archived_previous(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)

    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Na_LC050_N20:start_next_rh0p70")

    assert task["status"] == plan_campaign.STATUS_READY
    assert task["stage"] == "start_next_rh_0p70"
    assert task["generic_stage"] == "start_next_rh"
    assert task["rh_tag"] == "rh0p70"
    assert task["previous_rh_tag"] == "rh0p90"


def test_stale_downstream_rh_start_reopens_when_upstream_archive_restart_changes(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)
    run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )
    plan = run_campaign.write_plan(campaign, tmp_path)
    start_task = next(task for task in plan["planned_tasks"] if task["stage"] == "start_next_rh_0p70")
    assert start_task["status"] == plan_campaign.STATUS_COMPLETED

    state_dir = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / "rh_0p90"
    new_restart = state_dir / "restart.gcmc_rh0p90.4100000"
    new_restart.write_text("restart\n")
    summary = json.loads((state_dir / "summary.json").read_text())
    summary["archived_restart"] = "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.4100000"
    summary["selected_restart"] = summary["archived_restart"]
    (state_dir / "summary.json").write_text(json.dumps(summary))

    refreshed = run_campaign.write_plan(campaign, tmp_path)
    stale_start = next(task for task in refreshed["planned_tasks"] if task["stage"] == "start_next_rh_0p70")

    assert stale_start["status"] == plan_campaign.STATUS_READY


def test_arbitrary_rh_path_adds_generic_handoff_for_rh0p50(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    rewrite_campaign_rh_path(campaign, [0.9, 0.7, 0.5])
    setup_run_initial_rh0p70_ready_campaign(tmp_path, campaign)
    write_valid_rh0p70_outputs(tmp_path)
    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "Mt_Na_LC050_N20.rh_0p70_analysis.json").write_text(json.dumps({
        "status": "equilibrated",
        "recommendation": "archive",
        "system_id": "Mt_Na_LC050_N20",
        "rh_tag": "rh0p70",
        "fatal_errors": [],
        "known_warnings": [],
        "analyzer": {"status": "equilibrated", "recommendation": "write_data_and_continue_next_rh"},
    }))
    write_archived_rh_state(tmp_path, "rh0p70", 6100000)

    plan = run_campaign.write_plan(campaign, tmp_path)
    start = next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Na_LC050_N20:start_next_rh0p50")
    initial = next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Na_LC050_N20:run_initial_rh0p50")
    analyze = next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Na_LC050_N20:analyze_rh0p50")
    cont = next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Na_LC050_N20:continue_or_archive_rh0p50")

    assert start["stage"] == "start_next_rh_0p50"
    assert start["generic_stage"] == "start_next_rh"
    assert start["previous_rh_tag"] == "rh0p70"
    assert start["status"] == plan_campaign.STATUS_READY
    assert initial["generic_stage"] == "run_initial_rh"
    assert analyze["generic_stage"] == "analyze_rh"
    assert cont["generic_stage"] == "continue_or_archive_rh"


def test_auto_until_blocked_stops_at_generic_rh_handoff_boundary(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="archive", status="equilibrated")

    def fake_archive(run_dir, archive_dir=None, rh=None, summary_only=False):
        summary_dir = Path(run_dir).parent / "states" / "rh_0p90"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "summary.json").write_text(json.dumps({
            "analysis_status": "equilibrated",
            "analysis_recommendation": "archive",
            "archived_restart": "mock",
            "selected_restart": "mock",
        }))
        return {"final_step": 2000, "selected_restart": "mock"}

    monkeypatch.setattr(run_campaign.archive_rh_result, "archive_rh_result", fake_archive)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=2,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["decision"] == "archive"
    assert summary["actions"][1]["reason"] == "handoff_boundary"


def test_legacy_rh_aliases_and_generic_stage_metadata_work() -> None:
    assert run_campaign.rh_tag_from_analyze_stage("analyze_rh_0p90") == "rh0p90"
    assert run_campaign.rh_tag_from_continue_or_archive_stage("continue_or_archive_rh0p70") == "rh0p70"
    task = {"stage": "analyze_rh", "generic_stage": "analyze_rh", "rh_tag": "rh0p50"}
    assert run_campaign.canonical_rh_stage(task) == "analyze_rh"
    assert run_campaign.rh_tag_for_task(task, "analyze_rh") == "rh0p50"


def write_multi_cation_campaign(tmp_path: Path) -> Path:
    campaign_dir = tmp_path / "examples" / "campaigns"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    campaign_path = campaign_dir / "multi_cation_campaign.yaml"
    campaign_path.write_text(
        """campaign:
  id: multi_cation_smoke
  dry_run_only: true
templates:
  claycode_yaml: assets/claycode/MyMont1.yaml
  claycode_csv: assets/claycode/exp_clay.csv
geometry:
  clay_type: D21
  x_cells: 5
  y_cells: 4
  n_sheets: 2
rh_path: [0.90, 0.70]
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
  - system_id: Mt_K_LC050_N20
    cation: K
    valence: 1
    substitution_amount_x: 0.5
    expected_total_cation_count: 20
    expected_partition:
      bottom_external: 5
      interlayer: 10
      top_external: 5
  - system_id: Mt_Ba_LC040_N8
    cation: Ba
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


def write_system_raw_files(tmp_path: Path, system_id: str) -> None:
    raw = tmp_path / "examples" / system_id / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{system_id}_5_4.gro").write_text("mock gro\n")
    (raw / f"{system_id}_5_4.top").write_text("mock top\n")


def test_multi_cation_smoke_campaign_plans_k_and_ba_counts_and_partitions(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_multi_cation_campaign(tmp_path)

    plan = plan_campaign.make_plan(campaign, base_dir=tmp_path)

    systems = {system["system_id"]: system for system in plan["systems"]}
    assert set(systems) == {"Mt_Na_LC050_N20", "Mt_Ca_LC040_N8", "Mt_K_LC050_N20", "Mt_Ba_LC040_N8"}
    assert systems["Mt_K_LC050_N20"]["cation"] == "K"
    assert systems["Mt_K_LC050_N20"]["valence"] == 1
    assert systems["Mt_K_LC050_N20"]["expected_total_cation_count"] == 20
    assert systems["Mt_K_LC050_N20"]["expected_partition"] == {"bottom_external": 5, "interlayer": 10, "top_external": 5}
    assert systems["Mt_Ba_LC040_N8"]["cation"] == "Ba"
    assert systems["Mt_Ba_LC040_N8"]["valence"] == 2
    assert systems["Mt_Ba_LC040_N8"]["expected_total_cation_count"] == 8
    assert systems["Mt_Ba_LC040_N8"]["expected_partition"] == {"bottom_external": 2, "interlayer": 4, "top_external": 2}
    assert next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_K_LC050_N20:plan_claycode_inputs")["status"] == plan_campaign.STATUS_READY
    assert next(task for task in plan["planned_tasks"] if task["task_id"] == "Mt_Ba_LC040_N8:plan_claycode_inputs")["status"] == plan_campaign.STATUS_READY


def test_create_case_file_supports_k_and_ba_without_subprocess(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_multi_cation_campaign(tmp_path)
    cfg = plan_campaign.load_yaml(campaign)
    plan = plan_campaign.make_plan(campaign, base_dir=tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("case generation for K/Ba must not run subprocess commands")

    monkeypatch.setattr(run_campaign.subprocess, "run", fail_if_called)
    for system_id, cation, count, partition in [
        ("Mt_K_LC050_N20", "K", 20, {"bottom_external": 5, "interlayer": 10, "top_external": 5}),
        ("Mt_Ba_LC040_N8", "Ba", 8, {"bottom_external": 2, "interlayer": 4, "top_external": 2}),
    ]:
        write_system_raw_files(tmp_path, system_id)
        task = next(task for task in plan["planned_tasks"] if task["task_id"] == f"{system_id}:create_case_file")
        result = run_campaign.execute_task(
            campaign_cfg=cfg,
            plan=plan,
            task={**task, "status": plan_campaign.STATUS_READY},
            campaign_path=campaign,
            base_dir=tmp_path,
            force=False,
        )
        case_file = tmp_path / f"case.{system_id}.yaml"
        case_cfg = plan_campaign.load_yaml(case_file)
        assert result["status"] == "completed"
        assert result["cation"] == cation
        assert result["expected_ion_count"] == count
        assert result["expected_partition"] == partition
        assert case_cfg["structure"]["cation"] == cation
        assert case_cfg["structure"]["expected_ion_count"] == count
        assert case_cfg["structure"]["target_ion_distribution"] == partition


def write_completed_archive_summary(tmp_path: Path, system_id: str, rh_tag: str, final_step: int = 1000) -> str:
    rh_dir = rh_tag.replace("rh", "rh_")
    state_dir = tmp_path / "examples" / system_id / "states" / rh_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    restart = state_dir / f"restart.gcmc_{rh_tag}.{final_step}"
    restart.write_text("restart\n")
    restart_rel = f"examples/{system_id}/states/{rh_dir}/{restart.name}"
    (state_dir / "summary.json").write_text(json.dumps({
        "rh": run_campaign.rh_value_from_tag(rh_tag),
        "final_step": final_step,
        "archived_restart": restart_rel,
        "selected_restart": restart_rel,
        "analysis_status": "equilibrated",
        "analysis_recommendation": "archive",
        "equilibrium_status": "equilibrated",
        "equilibrium_recommendation": "archive",
    }))
    return restart_rel


def write_system_prereq_outputs_for_plan(tmp_path: Path, system_id: str) -> None:
    clay = tmp_path / "examples" / system_id / "claycode_inputs"
    clay.mkdir(parents=True, exist_ok=True)
    (clay / f"{system_id}.yaml").write_text("mock\n")
    (clay / f"{system_id}.csv").write_text("mock\n")
    (clay / f"{system_id}.metadata.json").write_text("{}\n")
    (clay / "claycode_input_plan.json").write_text("{}\n")
    write_system_raw_files(tmp_path, system_id)
    (tmp_path / f"case.{system_id}.yaml").write_text(f"case:\n  name: {system_id}\n")
    inputs = tmp_path / "examples" / system_id / "inputs"
    generated = tmp_path / "examples" / system_id / "generated"
    inputs.mkdir(parents=True, exist_ok=True)
    generated.mkdir(parents=True, exist_ok=True)
    (inputs / f"{system_id}_prepared.data").write_text("data\n")
    (inputs / f"{system_id}_groups_regions.inc").write_text("groups\n")
    (generated / f"{system_id}_prepared.report.json").write_text("{}\n")
    (generated / f"{system_id}_v2.type_report.csv").write_text("type,name\n")
    (generated / f"{system_id}_prepared.check.json").write_text("{}\n")
    (inputs / f"{system_id}_equilibrated.data").write_text("data\n")
    (inputs / "restart.pre_gcmc.final").write_text("restart\n")
    equil = tmp_path / "examples" / system_id / "equilibration"
    equil.mkdir(parents=True, exist_ok=True)
    (equil / "equilibration_status.json").write_text(json.dumps({"status": "completed"}))


def write_completed_rh_runtime_for_plan(tmp_path: Path, system_id: str, rh_tag: str, previous_restart: str | None = None) -> str:
    rh_dir = rh_tag.replace("rh", "rh_")
    run_dir = tmp_path / "examples" / system_id / rh_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    if previous_restart is not None:
        (run_dir / "start_next_rh_status.json").write_text(json.dumps({
            "status": "completed",
            "source_restart": previous_restart,
            "selected_restart": previous_restart,
        }))
    (run_dir / "initial_status.json").write_text(json.dumps({"status": "completed"}))
    (run_dir / f"monitor_gcmc_{rh_tag}.dat").write_text("0 0 0 0 0 0 0 0 0 0 0 0 300 0\n")
    (run_dir / f"restart.gcmc_{rh_tag}.final").write_text("restart\n")
    (run_dir / f"after_gcmc_{rh_tag}_initial.data").write_text("data\n")
    generated = tmp_path / "examples" / system_id / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / f"{system_id}.{rh_tag.replace('rh', 'rh_')}_analysis.json").write_text(json.dumps({
        "status": "equilibrated",
        "recommendation": "archive",
        "analyzer": {"status": "equilibrated", "recommendation": "write_data_and_continue_next_rh"},
    }))
    return write_completed_archive_summary(tmp_path, system_id, rh_tag)


def setup_target_filter_campaign_state(tmp_path: Path) -> Path:
    write_templates(tmp_path)
    campaign = write_multi_cation_campaign(tmp_path)
    for system_id in ["Mt_Na_LC050_N20", "Mt_Ca_LC040_N8"]:
        write_system_prereq_outputs_for_plan(tmp_path, system_id)
    na_rh90_restart = write_completed_rh_runtime_for_plan(tmp_path, "Mt_Na_LC050_N20", "rh0p90")
    write_completed_rh_runtime_for_plan(tmp_path, "Mt_Na_LC050_N20", "rh0p70", previous_restart=na_rh90_restart)
    write_completed_rh_runtime_for_plan(tmp_path, "Mt_Ca_LC040_N8", "rh0p90")
    return campaign


def test_system_filter_keeps_global_next_action_as_ca_rh_handoff(tmp_path: Path) -> None:
    campaign = setup_target_filter_campaign_state(tmp_path)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["actions"][0]["task_id"] == "Mt_Ca_LC040_N8:start_next_rh0p70"
    assert summary["next_recommended_action"]["task_id"] == "Mt_Ca_LC040_N8:start_next_rh0p70"


def test_system_filter_returns_k_and_ba_next_actions(tmp_path: Path) -> None:
    campaign = setup_target_filter_campaign_state(tmp_path)

    k_summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
        target_system="Mt_K_LC050_N20",
    )
    ba_summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=True,
        execute_next=False,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
        target_system="Mt_Ba_LC040_N8",
    )

    assert k_summary["actions"][0]["task_id"] == "Mt_K_LC050_N20:plan_claycode_inputs"
    assert k_summary["next_recommended_action"]["task_id"] == "Mt_K_LC050_N20:plan_claycode_inputs"
    assert ba_summary["actions"][0]["task_id"] == "Mt_Ba_LC040_N8:plan_claycode_inputs"
    assert ba_summary["next_recommended_action"]["task_id"] == "Mt_Ba_LC040_N8:plan_claycode_inputs"


def test_system_filter_execute_next_runs_filtered_system_only(tmp_path: Path) -> None:
    campaign = setup_target_filter_campaign_state(tmp_path)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
        target_system="Mt_K_LC050_N20",
    )

    assert summary["actions"][0]["task_id"] == "Mt_K_LC050_N20:plan_claycode_inputs"
    assert summary["actions"][0]["status"] == "completed"
    assert summary["next_recommended_action"]["task_id"] == "Mt_K_LC050_N20:run_claycode"
    assert (tmp_path / "examples" / "Mt_K_LC050_N20" / "claycode_inputs" / "Mt_K_LC050_N20.yaml").exists()
    assert not (tmp_path / "examples" / "Mt_Ba_LC040_N8" / "claycode_inputs" / "Mt_Ba_LC040_N8.yaml").exists()


def test_system_filter_unknown_system_fails_clearly(tmp_path: Path) -> None:
    campaign = setup_target_filter_campaign_state(tmp_path)

    try:
        run_campaign.run_campaign(
            campaign_path=campaign,
            dry_run=True,
            execute_next=False,
            max_actions=1,
            force=False,
            base_dir=tmp_path,
            target_system="Mt_Bad_LC999_N0",
        )
    except ValueError as exc:
        assert "Unknown campaign system" in str(exc)
        assert "Mt_K_LC050_N20" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown --system should fail clearly")


def test_auto_smoke_systems_filter_runs_k_ba_only_and_writes_summary(tmp_path: Path) -> None:
    campaign = setup_target_filter_campaign_state(tmp_path)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_smoke=True,
        smoke_systems=["Mt_K_LC050_N20", "Mt_Ba_LC040_N8"],
        max_actions=2,
        force=False,
        base_dir=tmp_path,
    )

    assert [action["task_id"] for action in summary["actions"]] == [
        "Mt_K_LC050_N20:plan_claycode_inputs",
        "Mt_Ba_LC040_N8:plan_claycode_inputs",
    ]
    assert (tmp_path / "generated" / "campaign_smoke_summary.json").exists()
    smoke = json.loads((tmp_path / "generated" / "campaign_smoke_summary.json").read_text())
    assert {row["system_id"] for row in smoke["systems"]} == {"Mt_K_LC050_N20", "Mt_Ba_LC040_N8"}


def test_auto_smoke_blocks_continuation_archive_stage() -> None:
    allowed, policy = run_campaign.smoke_policy_for_task({
        "task_id": "Mt_Na_LC050_N20:continue_or_archive_rh0p90",
        "stage": "continue_or_archive_rh_0p90",
        "generic_stage": "continue_or_archive_rh",
        "rh_tag": "rh0p90",
    })

    assert allowed is False
    assert policy["reason"] == "smoke_stage_blocked"


def test_auto_smoke_stops_after_analyze_rh0p90(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_analyze_ready_campaign(tmp_path, campaign, monitor=monitor_rows(stable=False))
    calls = []
    real_execute = run_campaign.execute_task

    def tracking_execute(**kwargs):
        calls.append(kwargs["task"]["stage"])
        return real_execute(**kwargs)

    monkeypatch.setattr(run_campaign, "execute_task", tracking_execute)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_smoke=True,
        smoke_systems=["Mt_Na_LC050_N20"],
        max_actions=5,
        force=False,
        base_dir=tmp_path,
    )

    assert calls == ["analyze_rh_0p90"]
    assert summary["actions"][0]["stage"] == "analyze_rh_0p90"
    assert summary["stop_reason"] == "smoke_complete"


def test_auto_smoke_failed_prepare_blocks_later_stages(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    execute_planning_action(tmp_path, campaign)
    write_raw_files(tmp_path)
    run_campaign.run_campaign(campaign_path=campaign, dry_run=False, execute_next=True, max_actions=1, force=False, base_dir=tmp_path)
    seen = []
    real_execute = run_campaign.execute_task

    def fake_execute(**kwargs):
        stage = kwargs["task"]["stage"]
        seen.append(stage)
        if stage == "prepare_case":
            return {"status": "failed", "reason": "mock_prepare_failed", "stage": stage, "system_id": kwargs["task"]["system_id"]}
        return real_execute(**kwargs)

    monkeypatch.setattr(run_campaign, "execute_task", fake_execute)
    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_smoke=True,
        smoke_systems=["Mt_Na_LC050_N20"],
        max_actions=5,
        force=False,
        base_dir=tmp_path,
    )

    assert seen == ["prepare_case"]
    assert summary["actions"][0]["reason"] == "mock_prepare_failed"
    assert not any(action.get("stage") == "run_equilibrate" for action in summary["actions"])


def test_auto_until_blocked_behavior_unchanged_with_auto_smoke_added(tmp_path: Path, monkeypatch) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    setup_continue_or_archive_ready_campaign(tmp_path, campaign, recommendation="continue")
    monkeypatch.setattr(run_campaign.subprocess, "run", fake_successful_continuation)

    summary = run_campaign.run_campaign(
        campaign_path=campaign,
        dry_run=False,
        execute_next=False,
        auto_until_blocked=True,
        max_actions=1,
        force=False,
        base_dir=tmp_path,
    )

    assert summary["status"] == "auto_stopped"
    assert summary["actions"][0]["stage"] == "continue_or_archive_rh_0p90"
    assert summary["actions"][0]["decision"] == "continue"


def test_paper_policy_max_total_steps_uses_elapsed_current_rh(tmp_path: Path) -> None:
    write_templates(tmp_path)
    campaign = write_campaign(tmp_path)
    rewrite_campaign_rh_path(campaign, [0.9, 0.7])
    setup_start_next_rh0p70_ready_campaign(tmp_path, campaign)

    previous_summary = tmp_path / "examples" / "Mt_Na_LC050_N20" / "states" / "rh_0p90" / "summary.json"
    previous = json.loads(previous_summary.read_text())
    restart_rel = "examples/Mt_Na_LC050_N20/states/rh_0p90/restart.gcmc_rh0p90.42000000"
    (tmp_path / restart_rel).write_text("restart\n")
    previous["archived_restart"] = restart_rel
    previous["selected_restart"] = restart_rel
    previous["final_step"] = 42_000_000
    previous_summary.write_text(json.dumps(previous))

    generated = tmp_path / "examples" / "Mt_Na_LC050_N20" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    analysis_path = generated / "Mt_Na_LC050_N20.rh_0p70_analysis.json"
    analysis_path.write_text(json.dumps({
        "status": "not_equilibrated",
        "recommendation": "continue",
        "system_id": "Mt_Na_LC050_N20",
        "rh_tag": "rh0p70",
        "final_timestep": 61_000_000,
        "fatal_errors": [],
        "ion_count_stable": True,
    }))

    campaign_cfg = plan_campaign.load_yaml(campaign)
    campaign_cfg["simulation_policy"]["max_total_steps_per_rh"] = 60_000_000
    plan = run_campaign.write_plan(campaign, tmp_path)
    task = next(task for task in plan["planned_tasks"] if task["stage"] == "continue_or_archive_rh_0p70")

    allowed, policy = run_campaign.paper_policy_for_task(
        campaign_cfg=campaign_cfg,
        task={**task, "status": plan_campaign.STATUS_READY},
        state={"execution_history": []},
        base_dir=tmp_path,
    )

    assert allowed is True
    assert policy["reason"] == "analysis_recommends_continue"

    analysis = json.loads(analysis_path.read_text())
    analysis["final_timestep"] = 102_000_000
    analysis_path.write_text(json.dumps(analysis))

    allowed, policy = run_campaign.paper_policy_for_task(
        campaign_cfg=campaign_cfg,
        task={**task, "status": plan_campaign.STATUS_READY},
        state={"execution_history": []},
        base_dir=tmp_path,
    )

    assert allowed is False
    assert policy["reason"] == "max_total_steps_per_rh_reached"
    assert policy["rh_start_step"] == 42_000_000
    assert policy["elapsed_steps_current_rh"] == 60_000_000

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mtagent import prepare_case


def write_minimal_case(
    tmp_path: Path,
    raw_gro: Path,
    raw_top: Path,
    forcefield: Path,
    spce_source: Path,
    molecule_template: Path,
) -> Path:
    case_path = tmp_path / "case.yaml"
    generated_dir = tmp_path / "generated"
    prepared_dir = tmp_path / "inputs"
    case_path.write_text(
        f"""paths:
  example_dir: {tmp_path}
  raw_gro: {raw_gro}
  raw_top: {raw_top}
  forcefield_file: {forcefield}
  generated_dir: {generated_dir}
  prepared_dir: {prepared_dir}
structure:
  claycode_model: MyMont-1_5_4
  cation: Na
  target_ion_distribution:
    bottom_external: 5
    interlayer: 10
    top_external: 5
water:
  spce_source: {spce_source}
  molecule_template: {molecule_template}
"""
    )
    return case_path


def test_prepare_case_dry_run_validates_paths_and_writes_status(tmp_path, monkeypatch) -> None:
    raw_gro = tmp_path / "MyMont-1_5_4.gro"
    raw_top = tmp_path / "MyMont-1_5_4.top"
    forcefield = tmp_path / "clayff-paper-2021"
    spce_source = tmp_path / "SPCEH2O.txt"
    molecule_template = tmp_path / "SPCEH2O_types_8_10.txt"
    for path in (raw_gro, raw_top, forcefield, spce_source, molecule_template):
        path.write_text("placeholder")

    case_path = write_minimal_case(tmp_path, raw_gro, raw_top, forcefield, spce_source, molecule_template)
    status_path = tmp_path / "prepare_status.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_case.py",
            "--case", str(case_path),
            "--dry-run",
            "--status", str(status_path),
        ],
    )
    prepare_case.main()

    status = json.loads(status_path.read_text())
    assert status["status"] == "dry_run"
    assert status["dry_run"] is True
    assert status["inputs"]["raw_gro"] == str(raw_gro)
    assert status["inputs"]["raw_top"] == str(raw_top)
    assert status["inputs"]["spce_source"] == str(spce_source)
    assert status["inputs"]["molecule_template"] == str(molecule_template)
    assert len(status["commands"]) == 4
    assert [cmd["name"] for cmd in status["commands"]] == ["convert", "check", "prepare", "check_prepared"]
    assert all(cmd["return_code"] is None for cmd in status["commands"])
    convert_command = status["commands"][0]["command"]
    assert convert_command[convert_command.index("--spce") + 1] == str(spce_source)
    check_command = status["commands"][1]["command"]
    assert check_command[check_command.index("--expected-ion-species") + 1] == "Na"
    assert check_command[check_command.index("--expected-ion-count") + 1] == "20"
    prepare_command = status["commands"][2]["command"]
    assert prepare_command[prepare_command.index("--ion-species") + 1] == "Na"
    assert prepare_command[prepare_command.index("--target-bottom-ions") + 1] == "5"


def test_prepare_case_dry_run_fails_for_missing_required_input(tmp_path, monkeypatch) -> None:
    raw_gro = tmp_path / "missing.gro"
    raw_top = tmp_path / "MyMont-1_5_4.top"
    forcefield = tmp_path / "clayff-paper-2021"
    spce_source = tmp_path / "SPCEH2O.txt"
    molecule_template = tmp_path / "SPCEH2O_types_8_10.txt"
    for path in (raw_top, forcefield, spce_source, molecule_template):
        path.write_text("placeholder")

    case_path = write_minimal_case(tmp_path, raw_gro, raw_top, forcefield, spce_source, molecule_template)

    monkeypatch.setattr(sys, "argv", ["prepare_case.py", "--case", str(case_path), "--dry-run"])

    with pytest.raises(FileNotFoundError, match="raw gro file"):
        prepare_case.main()


def test_prepare_case_uses_planner_metadata_for_ca_targets(tmp_path, monkeypatch) -> None:
    raw_gro = tmp_path / "Mt_Ca_LC040_N8.gro"
    raw_top = tmp_path / "Mt_Ca_LC040_N8.top"
    forcefield = tmp_path / "clayff-paper-2021"
    spce_source = tmp_path / "SPCEH2O.txt"
    molecule_template = tmp_path / "SPCEH2O_types_8_10.txt"
    metadata = tmp_path / "Mt_Ca_LC040_N8.metadata.json"
    for path in (raw_gro, raw_top, forcefield, spce_source, molecule_template):
        path.write_text("placeholder")
    metadata.write_text(json.dumps({
        "cation": "Ca",
        "target_bottom_ions": 2,
        "target_interlayer_ions": 4,
        "target_top_ions": 2,
    }))

    case_path = tmp_path / "case.yaml"
    generated_dir = tmp_path / "generated"
    prepared_dir = tmp_path / "inputs"
    case_path.write_text(f"""paths:
  example_dir: {tmp_path}
  raw_gro: {raw_gro}
  raw_top: {raw_top}
  forcefield_file: {forcefield}
  generated_dir: {generated_dir}
  prepared_dir: {prepared_dir}
structure:
  claycode_model: Mt_Ca_LC040_N8
  cation: Ca
  planner_metadata: {metadata}
water:
  spce_source: {spce_source}
  molecule_template: {molecule_template}
""")

    status_path = tmp_path / "prepare_status.json"
    monkeypatch.setattr(sys, "argv", ["prepare_case.py", "--case", str(case_path), "--dry-run", "--status", str(status_path)])
    prepare_case.main()

    status = json.loads(status_path.read_text())
    assert status["ion_preparation"]["ion_species"] == "Ca"
    assert status["ion_preparation"]["target_bottom_ions"] == 2
    assert status["ion_preparation"]["target_interlayer_ions"] == 4
    assert status["ion_preparation"]["target_top_ions"] == 2
    check_command = status["commands"][1]["command"]
    assert check_command[check_command.index("--expected-ion-species") + 1] == "Ca"
    assert check_command[check_command.index("--expected-ion-count") + 1] == "8"
    assert "--expected-na" not in check_command
    prepare_command = status["commands"][2]["command"]
    assert prepare_command[prepare_command.index("--ion-species") + 1] == "Ca"
    assert prepare_command[prepare_command.index("--target-bottom-ions") + 1] == "2"
    assert prepare_command[prepare_command.index("--target-interlayer-ions") + 1] == "4"
    assert prepare_command[prepare_command.index("--target-top-ions") + 1] == "2"

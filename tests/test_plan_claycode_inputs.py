from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
import yaml

from mtagent import plan_claycode_inputs


def write_templates(tmp_path: Path) -> tuple[Path, Path, Path]:
    work_dir = tmp_path / "assets" / "claycode"
    work_dir.mkdir(parents=True)
    template_yaml = work_dir / "MyMont1.yaml"
    template_yaml.write_text(
        """OUTPATH: .
SYSNAME: MyMont-1
BUILD: new
CLAY_COMP: exp_clay.csv
CLAY_TYPE: D21
X_CELLS: 5
Y_CELLS: 4
N_SHEETS: 2
IL_SOLV: true
SPACING_WATERS: 10
"""
    )
    template_csv = work_dir / "exp_clay.csv"
    template_csv.write_text(
        """sheet,element,MyMont-1
T,Si,8
O,Al,3.5
O,Mg,0.5
I,Na,0.5
C,O,-0.5
C,tot,-0.5
"""
    )
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        f"""claycode:
  work_dir: {work_dir}
  input_yaml: MyMont1.yaml
  exp_csv: exp_clay.csv
"""
    )
    return case_path, template_yaml, template_csv


def read_composition(path: Path, sysname: str) -> dict[tuple[str, str], str]:
    with path.open(newline="") as f:
        rows = csv.DictReader(f)
        return {(row["sheet"], row["element"]): row[sysname] for row in rows}


def test_generate_plan_writes_na_charge_series(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    out_dir = tmp_path / "planned"
    monkeypatch.chdir(tmp_path)

    plan = plan_claycode_inputs.generate_plan(
        case_path=case_path,
        template_yaml=None,
        template_csv=None,
        out_dir=out_dir,
        cations=["Na"],
        charges=[0.5],
        base_name="Mt",
        force=False,
    )

    assert len(plan["variants"]) == 1
    first = plan["variants"][0]
    assert first["sysname"] == "Mt_Na_LC050_N20"
    assert first["substitution_amount_x"] == 0.5
    assert first["layer_charge_per_uc_signed"] == -0.5
    assert first["layer_charge_label"] == "LC050"
    assert first["total_unit_cells"] == 40
    assert first["total_cation_count"] == 20
    assert first["target_bottom_ions"] == 5
    assert first["target_interlayer_ions"] == 10
    assert first["target_top_ions"] == 5
    assert first["interlayer_cation_per_uc"] == 0.5

    yaml_data = yaml.safe_load((out_dir / "Mt_Na_LC050_N20.yaml").read_text())
    assert yaml_data["SYSNAME"] == "Mt_Na_LC050_N20"
    assert yaml_data["CLAY_COMP"] == "Mt_Na_LC050_N20.csv"
    assert yaml_data["CLAY_TYPE"] == "D21"
    assert yaml_data["X_CELLS"] == 5
    assert yaml_data["Y_CELLS"] == 4
    assert yaml_data["N_SHEETS"] == 2
    assert "PLANNER_METADATA" not in yaml_data

    comp = read_composition(out_dir / "Mt_Na_LC050_N20.csv", "Mt_Na_LC050_N20")
    assert comp[("T", "Si")] == "8"
    assert comp[("O", "Al")] == "3.5"
    assert comp[("O", "Mg")] == "0.5"
    assert comp[("I", "Na")] == "0.5"
    assert comp[("C", "O")] == "-0.5"
    assert comp[("C", "tot")] == "-0.5"

    saved = json.loads((out_dir / "claycode_input_plan.json").read_text())
    assert saved["composition_rule"]["I_cation"] == "x / valence"
    assert saved["composition_rule"]["substitution_amount_x"] == "x"
    assert saved["composition_rule"]["layer_charge_per_uc_signed"] == "-x"
    assert saved["composition_rule"]["total_cation_count"] == "x / valence * X_CELLS * Y_CELLS * N_SHEETS"
    assert saved["total_unit_cells"] == 40
    assert saved["ion_partition_ratio"] == [1, 2, 1]
    assert saved["variants"][0]["substitution_amount_x"] == 0.5
    assert saved["variants"][0]["layer_charge_per_uc_signed"] == -0.5
    assert saved["variants"][0]["target_bottom_ions"] == 5
    sidecar = json.loads((out_dir / "Mt_Na_LC050_N20.metadata.json").read_text())
    assert sidecar["substitution_amount_x"] == 0.5
    assert sidecar["layer_charge_per_uc_signed"] == -0.5
    assert sidecar["layer_charge_label"] == "LC050"
    assert sidecar["total_cation_count"] == 20
    assert sidecar["target_interlayer_ions"] == 10


def test_generate_plan_uses_divalent_cation_amount_and_partition(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    out_dir = tmp_path / "planned"
    monkeypatch.chdir(tmp_path)

    plan_claycode_inputs.generate_plan(
        case_path=case_path,
        template_yaml=None,
        template_csv=None,
        out_dir=out_dir,
        cations=["Ca"],
        charges=[0.4],
        base_name="Mt",
        force=False,
    )

    comp = read_composition(out_dir / "Mt_Ca_LC040_N8.csv", "Mt_Ca_LC040_N8")
    assert comp[("O", "Al")] == "3.6"
    assert comp[("O", "Mg")] == "0.4"
    assert comp[("I", "Ca")] == "0.2"
    assert comp[("I", "Na")] == ""
    saved = json.loads((out_dir / "claycode_input_plan.json").read_text())
    variant = saved["variants"][0]
    assert variant["sysname"] == "Mt_Ca_LC040_N8"
    assert variant["total_cation_count"] == 8
    assert variant["target_bottom_ions"] == 2
    assert variant["target_interlayer_ions"] == 4
    assert variant["target_top_ions"] == 2


def test_cli_generates_without_running_claycode(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    out_dir = tmp_path / "planned"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "plan_claycode_inputs.py",
            "--case", str(case_path),
            "--out-dir", str(out_dir),
            "--cation", "Na",
            "--charge", "0.5",
            "--base-name", "Mt",
        ],
    )

    plan_claycode_inputs.main()

    assert (out_dir / "Mt_Na_LC050_N20.yaml").exists()
    assert (out_dir / "Mt_Na_LC050_N20.csv").exists()


def test_generate_plan_fails_for_noninteger_total_cation_count(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="Interlayer cation count is not an integer") as excinfo:
        plan_claycode_inputs.generate_plan(
            case_path=case_path,
            template_yaml=None,
            template_csv=None,
            out_dir=tmp_path / "planned",
            cations=["Ca"],
            charges=[0.33],
            base_name="Mt",
            force=False,
        )

    assert "Change layer_charge or supercell size" in str(excinfo.value)


def test_ca_lc050_fails_partition_validation(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="not compatible.*1:2:1"):
        plan_claycode_inputs.generate_plan(
            case_path=case_path,
            template_yaml=None,
            template_csv=None,
            out_dir=tmp_path / "planned",
            cations=["Ca"],
            charges=[0.5],
            base_name="Mt",
            force=False,
        )


def test_ca_lc050_can_be_written_when_uneven_partition_is_allowed(tmp_path: Path, monkeypatch) -> None:
    case_path, _, _ = write_templates(tmp_path)
    out_dir = tmp_path / "planned"
    monkeypatch.chdir(tmp_path)

    plan = plan_claycode_inputs.generate_plan(
        case_path=case_path,
        template_yaml=None,
        template_csv=None,
        out_dir=out_dir,
        cations=["Ca"],
        charges=[0.5],
        base_name="Mt",
        force=False,
        allow_uneven_partition=True,
    )

    variant = plan["variants"][0]
    assert variant["sysname"] == "Mt_Ca_LC050_N10"
    assert variant["total_cation_count"] == 10
    assert variant["target_bottom_ions"] is None
    assert (out_dir / "Mt_Ca_LC050_N10.yaml").exists()

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "gro_clayff_to_lammps_v2.py"
spec = importlib.util.spec_from_file_location("gro_clayff_to_lammps_v2", MODULE_PATH)
assert spec and spec.loader
converter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = converter
spec.loader.exec_module(converter)


FORCEFIELD_PATH = Path(__file__).resolve().parents[1] / "assets" / "forcefields" / "clayff-paper-2021"


def write_single_atom_gro(path: Path, atom_name: str, resname: str | None = None) -> None:
    residue = resname or atom_name
    path.write_text(
        f"""{atom_name} smoke
1
    1{residue:<5}{atom_name:>5}    1   0.100   0.200   0.300
   1.00000   1.00000   1.00000
"""
    )


def minimal_clayff_without_exchangeable_mg(path: Path) -> None:
    path.write_text(
        """LAMMPS

Pair Coeffs # lj/cut/coul/long
  4 0.0000009030 5.2643258688 # mgo octahedral Mg 1.36

Bond Coeffs # harmonic
  1 553.935 1.0000 # o*-h*

Angle Coeffs # harmonic
  1 45.753 109.47 # h*-o*-h*
"""
    )


def test_parse_gro_recognizes_exchangeable_ba_ion_and_explicit_pair_coeff(tmp_path: Path) -> None:
    if not FORCEFIELD_PATH.exists():
        pytest.skip("ClayFF asset omitted pending redistribution review")
    gro = tmp_path / "ba.gro"
    write_single_atom_gro(gro, "Ba")

    atoms, box = converter.parse_gro(gro, converter.DEFAULT_CHARGE_BY_ORIG_TYPE)
    pair, _, _ = converter.parse_clayff_coeffs(FORCEFIELD_PATH)

    assert box == (10.0, 10.0, 10.0)
    assert len(atoms) == 1
    atom = atoms[0]
    assert atom.base == "Ba"
    assert atom.orig_type_id == 23
    assert atom.charge == 2.0
    assert 23 in pair
    assert "Ba barium ion" in pair[23].comment


def test_exchangeable_mg_without_explicit_parameters_fails_clearly(tmp_path: Path) -> None:
    gro = tmp_path / "mg.gro"
    clayff = tmp_path / "clayff"
    out = tmp_path / "out.data"
    write_single_atom_gro(gro, "Mg")
    minimal_clayff_without_exchangeable_mg(clayff)

    atoms, box = converter.parse_gro(gro, converter.DEFAULT_CHARGE_BY_ORIG_TYPE)
    orig_to_new_atom = converter.compact_atom_types(atoms)
    pair, bond, angle = converter.parse_clayff_coeffs(clayff)

    assert atoms[0].orig_type_id == 25
    assert 25 not in pair
    with pytest.raises(ValueError, match="Exchangeable Mg parameters are not available in the force-field file"):
        converter.write_lammps_data(out, atoms, [], [], box, orig_to_new_atom, {}, {}, pair, bond, angle)


def test_structural_mg_remains_supported(tmp_path: Path) -> None:
    gro = tmp_path / "mgo.gro"
    clayff = tmp_path / "clayff"
    out = tmp_path / "out.data"
    write_single_atom_gro(gro, "MGO")
    minimal_clayff_without_exchangeable_mg(clayff)

    atoms, box = converter.parse_gro(gro, converter.DEFAULT_CHARGE_BY_ORIG_TYPE)
    orig_to_new_atom = converter.compact_atom_types(atoms)
    pair, bond, angle = converter.parse_clayff_coeffs(clayff)

    assert atoms[0].base == "MGO"
    assert atoms[0].orig_type_id == 4
    assert atoms[0].charge == 1.36
    converter.write_lammps_data(out, atoms, [], [], box, orig_to_new_atom, {}, {}, pair, bond, angle)
    assert "original 4: mgo octahedral Mg" in out.read_text()


def test_prepare_type_report_keeps_structural_mg_out_of_exchangeable_ions(tmp_path: Path) -> None:
    prepare_path = Path(__file__).resolve().parents[1] / "scripts" / "preparation" / "prepare_mt_data.py"
    prepare_spec = importlib.util.spec_from_file_location("prepare_mt_data", prepare_path)
    assert prepare_spec and prepare_spec.loader
    prepare_module = importlib.util.module_from_spec(prepare_spec)
    sys.modules[prepare_spec.name] = prepare_module
    prepare_spec.loader.exec_module(prepare_module)

    report = tmp_path / "type_report.csv"
    report.write_text(
        "section,new_type,original_type,label,count,charge,total_charge,atom_bases\n"
        "atom,3,4,mgo octahedral Mg,16,1.36,21.76,MGO:16\n"
        "atom,8,16,o* SPC/E water O,10,-0.8476,-8.476,OW:10\n"
        "atom,10,18,h* SPC/E water H,20,0.4238,8.476,HW:20\n"
        "atom,11,25,Mg magnesium ion,8,2.0,16.0,Mg:8\n"
    )

    type_info = prepare_module.load_type_report(report, ion_species="Mg")

    assert type_info["ion_types"] == [11]
    assert type_info["atom_type_info"][11]["charge"] == 2.0
    assert type_info["atom_type_info"][3]["label"] == "mgo octahedral Mg"

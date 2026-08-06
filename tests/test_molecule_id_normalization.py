from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module(name: str, rel_path: str):
    path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prepare_mt_data = load_module("prepare_mt_data_for_tests", "scripts/preparation/prepare_mt_data.py")
check_lammps_data = load_module("check_lammps_data_for_tests", "scripts/validation/check_lammps_data.py")


def test_normalize_molecule_ids_assigns_two_clay_bodies_water_from_three_and_ions_zero() -> None:
    atoms = [
        prepare_mt_data.Atom(1, 10, 1, 0.0, 0.0, 0.0, 10.0),
        prepare_mt_data.Atom(2, 11, 1, 0.0, 0.0, 0.0, 10.2),
        prepare_mt_data.Atom(3, 20, 1, 0.0, 0.0, 0.0, 30.0),
        prepare_mt_data.Atom(4, 21, 1, 0.0, 0.0, 0.0, 30.2),
        prepare_mt_data.Atom(5, 30, 8, -0.8, 0.0, 0.0, 15.0),
        prepare_mt_data.Atom(6, 30, 10, 0.4, 0.0, 0.0, 15.1),
        prepare_mt_data.Atom(7, 30, 10, 0.4, 0.0, 0.0, 15.2),
        prepare_mt_data.Atom(8, 31, 8, -0.8, 0.0, 0.0, 16.0),
        prepare_mt_data.Atom(9, 31, 10, 0.4, 0.0, 0.0, 16.1),
        prepare_mt_data.Atom(10, 31, 10, 0.4, 0.0, 0.0, 16.2),
        prepare_mt_data.Atom(11, 99, 11, 1.0, 0.0, 0.0, 18.0),
    ]
    bonds = [
        prepare_mt_data.Bond(1, 1, 5, 6),
        prepare_mt_data.Bond(2, 1, 5, 7),
        prepare_mt_data.Bond(3, 1, 8, 9),
        prepare_mt_data.Bond(4, 1, 8, 10),
    ]
    sheet = {
        "lower_atom_ids": [1, 2],
        "upper_atom_ids": [3, 4],
    }

    report = prepare_mt_data.normalize_molecule_ids(
        atoms=atoms,
        bonds=bonds,
        sheet=sheet,
        water_o_types={8},
        water_h_types={10},
        ion_types={11},
    )

    by_id = {a.atom_id: a for a in atoms}
    assert {by_id[i].mol_id for i in [1, 2]} == {1}
    assert {by_id[i].mol_id for i in [3, 4]} == {2}
    assert {by_id[i].mol_id for i in [5, 6, 7]} == {3}
    assert {by_id[i].mol_id for i in [8, 9, 10]} == {4}
    assert by_id[11].mol_id == 0
    assert report["clay_lower_mol_ids_after"] == [1]
    assert report["clay_upper_mol_ids_after"] == [2]
    assert report["exchangeable_ion_mol_ids_after"] == [0]
    assert report["sodium_mol_ids_after"] == [0]
    assert report["water_mol_id_min_after"] == 3
    assert report["water_mol_id_max_after"] == 4
    assert report["water_molecule_count"] == 2
    assert report["warnings"] == []


def test_checker_catches_clay_sheet_with_multiple_molecule_ids() -> None:
    atoms = {
        1: check_lammps_data.Atom(1, 10, 1, 0.0, 0.0, 0.0, 10.0),
        2: check_lammps_data.Atom(2, 11, 1, 0.0, 0.0, 0.0, 10.2),
        3: check_lammps_data.Atom(3, 20, 1, 0.0, 0.0, 0.0, 30.0),
        4: check_lammps_data.Atom(4, 20, 1, 0.0, 0.0, 0.0, 30.2),
        5: check_lammps_data.Atom(5, 3, 8, 0.0, 0.0, 0.0, 15.0),
        6: check_lammps_data.Atom(6, 3, 10, 0.0, 0.0, 0.0, 15.1),
        7: check_lammps_data.Atom(7, 3, 10, 0.0, 0.0, 0.0, 15.2),
        8: check_lammps_data.Atom(8, 0, 11, 0.0, 0.0, 0.0, 18.0),
    }

    result = check_lammps_data.molecule_id_normalization_check(
        atoms=atoms,
        water_o={5},
        water_h={6, 7},
        na_atoms={8},
    )

    assert result["clay_lower_mol_ids"] == [10, 11]
    assert result["clay_upper_mol_ids"] == [20]
    assert any("clay_lower has multiple molecule IDs" in msg for msg in result["errors"])

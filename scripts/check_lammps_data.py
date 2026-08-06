#!/usr/bin/env python3
"""
Check a LAMMPS data file generated from ClayCode .gro + ClayFF/SPC/E rules.

Designed for atom_style full files with sections such as:
  Masses, Pair Coeffs, Bond Coeffs, Angle Coeffs, Atoms, Bonds, Angles

If a type report CSV from gro_clayff_to_lammps_v2.py is supplied, the checker
can perform chemistry-aware checks for SPC/E water, Na, hydroxyl bonds, and
mineral M-O-H angles.

Usage:
  python3 check_lammps_data.py --data MyMont-1_5_4.data \
    --type-report MyMont-1_5_4.type_report.csv \
    --expected-na 20 --expected-water 300 \
    --json MyMont-1_5_4.check.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class Atom:
    atom_id: int
    mol_id: int
    type_id: int
    charge: float
    x: float
    y: float
    z: float


@dataclass
class Bond:
    bond_id: int
    type_id: int
    a: int
    b: int


@dataclass
class Angle:
    angle_id: int
    type_id: int
    a: int
    b: int
    c: int


SECTION_NAMES = {
    "Masses", "Pair Coeffs", "Bond Coeffs", "Angle Coeffs", "Dihedral Coeffs",
    "Improper Coeffs", "Atoms", "Velocities", "Bonds", "Angles", "Dihedrals", "Impropers"
}


def strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def detect_section(line: str) -> Optional[str]:
    s = line.strip()
    if not s:
        return None
    # Section may be "Atoms # full" or "Pair Coeffs # lj/cut/coul/long"
    head = s.split("#", 1)[0].strip()
    if head in SECTION_NAMES:
        return head
    return None


def parse_lammps_data(path: Path):
    lines = path.read_text(errors="replace").splitlines()

    header_counts = {}
    box = {"xlo": None, "xhi": None, "ylo": None, "yhi": None, "zlo": None, "zhi": None}
    sections = defaultdict(list)
    current = None

    count_patterns = [
        ("atoms", re.compile(r"^\s*(\d+)\s+atoms\b")),
        ("bonds", re.compile(r"^\s*(\d+)\s+bonds\b")),
        ("angles", re.compile(r"^\s*(\d+)\s+angles\b")),
        ("atom types", re.compile(r"^\s*(\d+)\s+atom\s+types\b")),
        ("bond types", re.compile(r"^\s*(\d+)\s+bond\s+types\b")),
        ("angle types", re.compile(r"^\s*(\d+)\s+angle\s+types\b")),
    ]
    box_patterns = [
        ("xlo", "xhi", re.compile(r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+xlo\s+xhi\b")),
        ("ylo", "yhi", re.compile(r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+ylo\s+yhi\b")),
        ("zlo", "zhi", re.compile(r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+zlo\s+zhi\b")),
    ]

    for raw in lines:
        sec = detect_section(raw)
        if sec is not None:
            current = sec
            continue

        if current is None:
            for name, pat in count_patterns:
                m = pat.match(raw)
                if m:
                    header_counts[name] = int(m.group(1))
            for lo, hi, pat in box_patterns:
                m = pat.match(raw)
                if m:
                    box[lo], box[hi] = float(m.group(1)), float(m.group(2))
        else:
            if raw.strip():
                sections[current].append(raw)

    masses = {}
    for raw in sections.get("Masses", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 2:
            masses[int(parts[0])] = float(parts[1])

    pair_coeffs = {}
    for raw in sections.get("Pair Coeffs", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 3:
            pair_coeffs[int(parts[0])] = tuple(map(float, parts[1:]))

    bond_coeffs = {}
    for raw in sections.get("Bond Coeffs", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 3:
            bond_coeffs[int(parts[0])] = tuple(map(float, parts[1:]))

    angle_coeffs = {}
    for raw in sections.get("Angle Coeffs", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 3:
            angle_coeffs[int(parts[0])] = tuple(map(float, parts[1:]))

    atoms: Dict[int, Atom] = {}
    for raw in sections.get("Atoms", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) < 7:
            continue
        # atom_style full: id mol type q x y z [nx ny nz]
        atom = Atom(
            atom_id=int(parts[0]), mol_id=int(parts[1]), type_id=int(parts[2]),
            charge=float(parts[3]), x=float(parts[4]), y=float(parts[5]), z=float(parts[6])
        )
        atoms[atom.atom_id] = atom

    bonds: Dict[int, Bond] = {}
    for raw in sections.get("Bonds", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 4:
            b = Bond(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
            bonds[b.bond_id] = b

    angles: Dict[int, Angle] = {}
    for raw in sections.get("Angles", []):
        s = strip_comment(raw)
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 5:
            a = Angle(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
            angles[a.angle_id] = a

    return header_counts, box, masses, pair_coeffs, bond_coeffs, angle_coeffs, atoms, bonds, angles


def load_type_report(path: Optional[Path]):
    if path is None:
        return {}, {}, {}
    rows = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    by_type = {}
    by_label = defaultdict(list)
    for row in rows:
        # Accept converter reports containing atom/bond/angle sections.
        if row.get("section", "atom") != "atom":
            continue
        # Accept several possible field names from earlier script versions.
        tid_raw = row.get("new_type_id") or row.get("new_type") or row.get("type_id") or row.get("lammps_type")
        if tid_raw in (None, ""):
            continue
        tid = int(tid_raw)
        label = row.get("label") or row.get("atom_label") or row.get("clayff_label") or row.get("name")
        atom_bases = row.get("atom_bases") or ""
        base_from_counts = atom_bases.split(":", 1)[0].strip() if atom_bases else None
        base = row.get("base") or row.get("atom_base") or base_from_counts or label
        charge = row.get("charge") or row.get("atom_charge")
        count = row.get("count") or row.get("n") or "0"
        rec = {
            "type_id": tid,
            "label": str(label),
            "base": str(base),
            "charge": float(charge) if charge not in (None, "") else None,
            "count": int(float(count)) if count not in (None, "") else None,
            "raw": row,
        }
        by_type[tid] = rec
        by_label[str(label)].append(tid)
    by_base = defaultdict(list)
    for tid, rec in by_type.items():
        by_base[rec["base"]].append(tid)
    return by_type, dict(by_label), dict(by_base)


def consecutive(ids: List[int]) -> bool:
    return sorted(ids) == list(range(1, len(ids) + 1))


def minimum_image_delta(p1, p2, box_lengths):
    out = []
    for i, L in enumerate(box_lengths):
        d = p1[i] - p2[i]
        if L and L > 0:
            d -= round(d / L) * L
        out.append(d)
    return tuple(out)


def pbc_distance(a: Atom, b: Atom, box_lengths):
    dx, dy, dz = minimum_image_delta((a.x, a.y, a.z), (b.x, b.y, b.z), box_lengths)
    return math.sqrt(dx * dx + dy * dy + dz * dz)




def molecule_id_normalization_check(atoms: Dict[int, Atom], water_o: set[int], water_h: set[int], na_atoms: set[int]) -> Dict[str, object]:
    water_ids = water_o | water_h
    clay_ids = set(atoms) - water_ids - na_atoms
    if not clay_ids:
        return {"enabled": True, "warnings": [], "errors": ["No clay atoms available for molecule-ID check."]}

    clay_atoms = [atoms[aid] for aid in clay_ids]
    by_mol: Dict[int, List[Atom]] = defaultdict(list)
    for atom in clay_atoms:
        by_mol[atom.mol_id].append(atom)

    mol_centers = sorted((mid, sum(a.z for a in vals) / len(vals), len(vals)) for mid, vals in by_mol.items())
    if len(mol_centers) == 2:
        lower_mols = [min(mol_centers, key=lambda x: x[1])[0]]
        upper_mols = [max(mol_centers, key=lambda x: x[1])[0]]
    else:
        sorted_centers = sorted(mol_centers, key=lambda x: x[1])
        gaps = [(sorted_centers[i + 1][1] - sorted_centers[i][1], i) for i in range(len(sorted_centers) - 1)]
        if not gaps:
            return {"enabled": True, "warnings": [], "errors": ["Could not split clay atoms into lower/upper sheets."]}
        _, split_idx = max(gaps, key=lambda x: x[0])
        lower_mols = [m for m, _, _ in sorted_centers[: split_idx + 1]]
        upper_mols = [m for m, _, _ in sorted_centers[split_idx + 1 :]]

    lower_ids = {aid for aid in clay_ids if atoms[aid].mol_id in set(lower_mols)}
    upper_ids = {aid for aid in clay_ids if atoms[aid].mol_id in set(upper_mols)}
    lower_mol_ids = sorted({atoms[aid].mol_id for aid in lower_ids})
    upper_mol_ids = sorted({atoms[aid].mol_id for aid in upper_ids})
    water_mol_ids = sorted({atoms[aid].mol_id for aid in water_ids})
    sodium_mol_ids = sorted({atoms[aid].mol_id for aid in na_atoms})

    errors = []
    warnings = []
    if len(lower_mol_ids) != 1:
        errors.append(f"clay_lower has multiple molecule IDs: {lower_mol_ids}")
    if len(upper_mol_ids) != 1:
        errors.append(f"clay_upper has multiple molecule IDs: {upper_mol_ids}")
    if lower_mol_ids and upper_mol_ids and lower_mol_ids == upper_mol_ids:
        errors.append(f"clay_lower and clay_upper share molecule ID(s): {lower_mol_ids}")
    if set(water_mol_ids) & {1, 2}:
        errors.append(f"water uses clay molecule ID 1 or 2: {sorted(set(water_mol_ids) & {1, 2})}")
    if set(sodium_mol_ids) & {1, 2}:
        errors.append(f"sodium uses clay molecule ID 1 or 2: {sorted(set(sodium_mol_ids) & {1, 2})}")

    return {
        "enabled": True,
        "clay_lower_mol_ids": lower_mol_ids,
        "clay_upper_mol_ids": upper_mol_ids,
        "water_mol_id_min": min(water_mol_ids) if water_mol_ids else None,
        "water_mol_id_max": max(water_mol_ids) if water_mol_ids else None,
        "sodium_mol_ids": sodium_mol_ids,
        "warnings": warnings,
        "errors": errors,
    }

def check(args):
    header, box, masses, pair_coeffs, bond_coeffs, angle_coeffs, atoms, bonds, angles = parse_lammps_data(Path(args.data))
    by_type, by_label, by_base = load_type_report(Path(args.type_report) if args.type_report else None)

    errors = []
    warnings = []

    def require(cond: bool, msg: str):
        if not cond:
            errors.append(msg)

    def warn(cond: bool, msg: str):
        if not cond:
            warnings.append(msg)

    # Header/count checks
    require(len(atoms) == header.get("atoms", len(atoms)), f"Atom count mismatch: header {header.get('atoms')} vs parsed {len(atoms)}")
    require(len(bonds) == header.get("bonds", len(bonds)), f"Bond count mismatch: header {header.get('bonds')} vs parsed {len(bonds)}")
    require(len(angles) == header.get("angles", len(angles)), f"Angle count mismatch: header {header.get('angles')} vs parsed {len(angles)}")
    require(consecutive(list(atoms)), "Atom IDs are not consecutive from 1")
    require(consecutive(list(bonds)) or len(bonds) == 0, "Bond IDs are not consecutive from 1")
    require(consecutive(list(angles)) or len(angles) == 0, "Angle IDs are not consecutive from 1")

    atom_type_count = header.get("atom types")
    bond_type_count = header.get("bond types")
    angle_type_count = header.get("angle types")
    if atom_type_count is not None:
        require(all(1 <= a.type_id <= atom_type_count for a in atoms.values()), "Some atom type IDs exceed declared atom types")
    if bond_type_count is not None:
        require(all(1 <= b.type_id <= bond_type_count for b in bonds.values()), "Some bond type IDs exceed declared bond types")
    if angle_type_count is not None:
        require(all(1 <= a.type_id <= angle_type_count for a in angles.values()), "Some angle type IDs exceed declared angle types")

    require(set(a.type_id for a in atoms.values()).issubset(set(masses)), "Some atom types are missing from Masses")
    warn(set(a.type_id for a in atoms.values()).issubset(set(pair_coeffs)), "Some atom types are missing from Pair Coeffs")
    if bonds:
        require(set(b.type_id for b in bonds.values()).issubset(set(bond_coeffs)), "Some bond types are missing from Bond Coeffs")
    if angles:
        require(set(a.type_id for a in angles.values()).issubset(set(angle_coeffs)), "Some angle types are missing from Angle Coeffs")

    # Reference checks
    atom_ids = set(atoms)
    for b in bonds.values():
        require(b.a in atom_ids and b.b in atom_ids, f"Bond {b.bond_id} references missing atom")
        require(b.a != b.b, f"Bond {b.bond_id} has identical atoms")
    for an in angles.values():
        require(an.a in atom_ids and an.b in atom_ids and an.c in atom_ids, f"Angle {an.angle_id} references missing atom")
        require(len({an.a, an.b, an.c}) == 3, f"Angle {an.angle_id} contains repeated atom")

    type_counts = Counter(a.type_id for a in atoms.values())
    type_charge_sums = defaultdict(float)
    for a in atoms.values():
        type_charge_sums[a.type_id] += a.charge
    total_charge = sum(a.charge for a in atoms.values())
    warn(abs(total_charge) <= args.charge_tol, f"Total charge {total_charge:.8g} exceeds tolerance {args.charge_tol}")

    # Optional report consistency
    if by_type:
        for tid, rec in by_type.items():
            if rec["count"] is not None:
                require(type_counts.get(tid, 0) == rec["count"], f"Type-report count mismatch for type {tid}: report {rec['count']} vs data {type_counts.get(tid, 0)}")
            if rec["charge"] is not None and tid in type_counts:
                observed_qs = {round(a.charge, 8) for a in atoms.values() if a.type_id == tid}
                require(len(observed_qs) == 1 and abs(next(iter(observed_qs)) - rec["charge"]) < 1e-6,
                        f"Type-report charge mismatch for type {tid}: report {rec['charge']} vs data {sorted(observed_qs)}")

    # Chemistry-aware checks if type report is present.
    def types_for_bases(*bases):
        s = set()
        for base in bases:
            s.update(by_base.get(base, []))
        return s

    water_o_types = types_for_bases("OW", "OW_spce", "o_spce")
    water_h_types = types_for_bases("HW", "HW1", "HW2", "H_spce", "h_spce")
    na_types = types_for_bases("Na", "NA")
    ion_species = getattr(args, "expected_ion_species", None) or "Na"
    ion_types = types_for_bases(ion_species, ion_species.upper())
    ho_types = types_for_bases("HO")
    oh_types = types_for_bases("OH", "OHS")
    metal_types = types_for_bases("AO", "MGO", "ST")

    chemistry = {}
    if by_type:
        water_o = {aid for aid, a in atoms.items() if a.type_id in water_o_types}
        water_h = {aid for aid, a in atoms.items() if a.type_id in water_h_types}
        na_atoms = {aid for aid, a in atoms.items() if a.type_id in na_types}
        ion_atoms = {aid for aid, a in atoms.items() if a.type_id in ion_types}
        ho_atoms = {aid for aid, a in atoms.items() if a.type_id in ho_types}
        oh_atoms = {aid for aid, a in atoms.items() if a.type_id in oh_types}
        metal_atoms = {aid for aid, a in atoms.items() if a.type_id in metal_types}

        chemistry.update({
            "water_oxygen_atoms": len(water_o),
            "water_hydrogen_atoms": len(water_h),
            "water_molecules_by_O_count": len(water_o),
            "na_atoms": len(na_atoms),
            "exchangeable_ion_species": ion_species,
            "exchangeable_ion_atoms": len(ion_atoms),
            "mineral_HO_atoms": len(ho_atoms),
            "mineral_OH_or_OHS_atoms": len(oh_atoms),
            "metal_atoms_AO_MGO_ST": len(metal_atoms),
        })

        if args.expected_na is not None:
            require(len(na_atoms) == args.expected_na, f"Na count mismatch: expected {args.expected_na}, found {len(na_atoms)}")
        if getattr(args, "expected_ion_count", None) is not None:
            require(len(ion_atoms) == args.expected_ion_count, f"{ion_species} ion count mismatch: expected {args.expected_ion_count}, found {len(ion_atoms)}")
        if args.expected_water is not None:
            require(len(water_o) == args.expected_water, f"Water count mismatch: expected {args.expected_water}, found {len(water_o)}")
            require(len(water_h) == 2 * args.expected_water, f"Water H count mismatch: expected {2 * args.expected_water}, found {len(water_h)}")

        # Water molecule check by molecule ID.
        water_by_mol = defaultdict(list)
        for aid in water_o | water_h:
            water_by_mol[atoms[aid].mol_id].append(aid)
        bad_water_mols = []
        for mid, ids in water_by_mol.items():
            n_o = sum(1 for aid in ids if aid in water_o)
            n_h = sum(1 for aid in ids if aid in water_h)
            if not (n_o == 1 and n_h == 2):
                bad_water_mols.append((mid, n_o, n_h))
        require(not bad_water_mols, f"Bad water molecule composition for molecule IDs: {bad_water_mols[:10]}")

        # Bond adjacency
        bond_adj = defaultdict(list)
        for b in bonds.values():
            bond_adj[b.a].append((b.b, b.type_id, b.bond_id))
            bond_adj[b.b].append((b.a, b.type_id, b.bond_id))

        bad_water_bonds = []
        for ow in water_o:
            neigh = [j for j, _, _ in bond_adj[ow]]
            n_wh = sum(1 for j in neigh if j in water_h)
            if n_wh != 2:
                bad_water_bonds.append((ow, n_wh))
        require(not bad_water_bonds, f"Water O atoms without exactly two H bonds: {bad_water_bonds[:10]}")

        bad_ho_bonds = []
        mineral_oh_bonds = []
        for ho in ho_atoms:
            neigh = [j for j, _, _ in bond_adj[ho]]
            o_neigh = [j for j in neigh if j in oh_atoms]
            if len(o_neigh) != 1:
                bad_ho_bonds.append((ho, o_neigh))
            else:
                mineral_oh_bonds.append((o_neigh[0], ho))
        require(not bad_ho_bonds, f"Mineral HO atoms without exactly one OH/OHS bond: {bad_ho_bonds[:10]}")

        # Angle checks.
        water_angle_count = 0
        bad_water_angles = []
        mineral_angle_by_ho = defaultdict(int)
        bad_mineral_angles = []
        for an in angles.values():
            ids = (an.a, an.b, an.c)
            # Water H-O-H angle: center is water O, ends are water H.
            if an.b in water_o and an.a in water_h and an.c in water_h:
                water_angle_count += 1
            elif an.c in water_o and an.a in water_h and an.b in water_h:
                # Unusual order, but record it.
                bad_water_angles.append((an.angle_id, ids, "water angle has unusual center"))
            # Mineral M-O-H angle: M-O-H, center O, terminal H.
            if an.b in oh_atoms and an.c in ho_atoms and an.a in metal_atoms:
                mineral_angle_by_ho[an.c] += 1
            elif an.b in oh_atoms and an.a in ho_atoms and an.c in metal_atoms:
                mineral_angle_by_ho[an.a] += 1
            elif (an.a in ho_atoms or an.c in ho_atoms or an.b in ho_atoms):
                # Only flag angles containing mineral HO that are not recognized.
                if any(i in ho_atoms for i in ids):
                    bad_mineral_angles.append((an.angle_id, ids))

        require(water_angle_count == len(water_o), f"Water angle count mismatch: expected {len(water_o)}, found {water_angle_count}")
        warn(not bad_water_angles, f"Unusual water angles: {bad_water_angles[:10]}")
        require(not bad_mineral_angles, f"Unrecognized mineral HO-containing angles: {bad_mineral_angles[:10]}")

        bad_angle_per_ho = [(ho, c) for ho, c in mineral_angle_by_ho.items() if c != args.expected_mineral_angles_per_ho]
        missing_angle_ho = [ho for ho in ho_atoms if ho not in mineral_angle_by_ho]
        require(not missing_angle_ho, f"Mineral HO atoms with no M-O-H angle: {missing_angle_ho[:10]}")
        require(not bad_angle_per_ho, f"Mineral HO atoms with wrong angle count: expected {args.expected_mineral_angles_per_ho}, examples {bad_angle_per_ho[:10]}")

        if args.require_normalized_molecule_ids:
            mol_check = molecule_id_normalization_check(atoms, water_o, water_h, ion_atoms)
            chemistry["molecule_id_normalization_check"] = mol_check
            for msg in mol_check.get("warnings", []):
                warnings.append(msg)
            for msg in mol_check.get("errors", []):
                errors.append(msg)

        chemistry.update({
            "water_angle_count": water_angle_count,
            "mineral_oh_bond_count": len(mineral_oh_bonds),
            "mineral_moh_angle_count": sum(mineral_angle_by_ho.values()),
            "mineral_angles_per_HO_distribution": dict(Counter(mineral_angle_by_ho.values())),
        })

        # Optional bond length diagnostics with PBC.
        if all(box[k] is not None for k in ("xlo", "xhi", "ylo", "yhi", "zlo", "zhi")):
            L = (box["xhi"] - box["xlo"], box["yhi"] - box["ylo"], box["zhi"] - box["zlo"])
            water_bond_lengths = []
            mineral_oh_lengths = []
            for b in bonds.values():
                a1, a2 = atoms[b.a], atoms[b.b]
                if (b.a in water_o and b.b in water_h) or (b.b in water_o and b.a in water_h):
                    water_bond_lengths.append(pbc_distance(a1, a2, L))
                if (b.a in ho_atoms and b.b in oh_atoms) or (b.b in ho_atoms and b.a in oh_atoms):
                    mineral_oh_lengths.append(pbc_distance(a1, a2, L))
            def stats(xs):
                if not xs:
                    return None
                return {"min": min(xs), "max": max(xs), "mean": sum(xs) / len(xs)}
            chemistry["water_OH_bond_length_A"] = stats(water_bond_lengths)
            chemistry["mineral_OH_bond_length_A"] = stats(mineral_oh_lengths)

    summary = {
        "data_file": str(args.data),
        "header_counts": header,
        "parsed_counts": {"atoms": len(atoms), "bonds": len(bonds), "angles": len(angles)},
        "box": box,
        "total_charge": total_charge,
        "atom_type_counts": dict(sorted(type_counts.items())),
        "atom_type_charge_sums": {str(k): v for k, v in sorted(type_charge_sums.items())},
        "chemistry": chemistry,
        "warnings": warnings,
        "errors": errors,
        "passed": len(errors) == 0,
    }

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))

    print("LAMMPS data check summary")
    print("========================")
    print(f"Data file: {args.data}")
    print(f"Atoms/Bonds/Angles: {len(atoms)} / {len(bonds)} / {len(angles)}")
    print(f"Total charge: {total_charge:.8f} e")
    print(f"Atom types used: {len(type_counts)}")
    if chemistry:
        for k, v in chemistry.items():
            print(f"{k}: {v}")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")
        print("\nFAILED")
        return 1
    print("\nPASSED")
    return 0


def main():
    p = argparse.ArgumentParser(description="Check a LAMMPS data file generated from ClayCode/ClayFF/SPC/E.")
    p.add_argument("--data", required=True, help="LAMMPS data file")
    p.add_argument("--type-report", help="CSV type report from converter")
    p.add_argument("--expected-na", type=int, help="Expected number of Na atoms")
    p.add_argument("--expected-ion-species", default="Na", help="Exchangeable ion species for generic count/molecule-ID checks")
    p.add_argument("--expected-ion-count", type=int, help="Expected number of exchangeable ions")
    p.add_argument("--expected-water", type=int, help="Expected number of water molecules")
    p.add_argument("--expected-mineral-angles-per-ho", type=int, default=2, help="Expected M-O-H angles per mineral HO atom")
    p.add_argument("--charge-tol", type=float, default=1.0e-2, help="Allowed absolute total charge tolerance")
    p.add_argument("--json", help="Optional JSON output path")
    p.add_argument("--require-normalized-molecule-ids", action="store_true", help="Require clay_lower mol=1, clay_upper mol=2, and no water/Na use of 1 or 2")
    args = p.parse_args()
    sys.exit(check(args))


if __name__ == "__main__":
    main()

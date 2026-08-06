#!/usr/bin/env python3
"""
Convert a ClayCode .gro file to a compact LAMMPS data file using CLAYFF + SPC/E.

This version intentionally writes ONLY the atom/bond/angle types that are actually
present in the .gro-derived topology. It also ignores the Morse bond section in
the CLAYFF parameter file and keeps only harmonic bond coefficients.

Designed for ClayCode-generated montmorillonite systems such as:
  D2020/D2022 clay residues + iSL SPC/E waters + Na/K/Ca/Ba ions; structural Mg remains supported for mineral sites.

Main assumptions
----------------
1. .gro atom names encode CLAYFF atom types, e.g. HO1 -> ho, OH1 -> oh,
   OHS3 -> ohs, AO1 -> ao, MGO3 -> mgo, ST1 -> st.
2. Mineral hydroxyl bonds are inferred by matching numeric suffixes inside each
   clay residue: HO1-OH1, HO3-OHS3, etc.
3. Mineral M-O-H angles are inferred geometrically with minimum-image PBC:
   for each OH/OHS-HO bond, all AO/MGO/ST atoms within --mo-cutoff Å from
   the hydroxyl oxygen generate M-O-H angles.
4. Water residues contain one OW and two HW atoms; water bonds/angle come from
   the SPC/E template or built-in defaults.
5. Clay framework bonds are not generated except hydroxyl O-H bonds.

Usage
-----
python3 gro_clayff_to_lammps_v2.py \
  --gro MyMont-1_5_4.gro \
  --clayff clayff-paper-2021 \
  --spce SPCEH2O.txt \
  --out MyMont-1_5_4.data \
  --summary MyMont-1_5_4.summary.txt \
  --type-report MyMont-1_5_4.type_report.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class Atom:
    id: int
    resid: int
    resname: str
    name: str
    base: str
    orig_type_id: int
    type_id: int
    charge: float
    mol: int
    x: float
    y: float
    z: float


@dataclass
class Coeff:
    orig_id: int
    values: str
    comment: str = ""


# Original CLAYFF/LAMMPS type IDs follow the uploaded clayff-paper-2021 file.
TYPE_BY_BASE = {
    "ST": 1,
    "AO": 2,
    "AT": 3,
    "MGO": 4,
    "MGH": 5,
    "CAO": 6,
    "CAH": 7,
    "FEO": 8,
    "LIO": 9,
    "OB": 10,
    # In this specific octahedral Mg-for-Al substituted D2022 model, ClayCode's
    # OBS atoms should be interpreted as CLAYFF obos, not obss.
    "OBS": 13,
    "OBSS": 11,
    "OBTS": 12,
    "OBOS": 13,
    "OHS": 14,
    "OH": 15,
    "OW": 16,
    "O": 16,
    "HO": 17,
    "HW": 18,
    "H": 18,
    "Na": 19,
    "NA": 19,
    "K": 20,
    "Cs": 21,
    "CS": 21,
    "Ca": 22,
    "CA": 22,
    "Mg": 25,
    "MG": 25,
    "Ba": 23,
    "BA": 23,
    "Cl": 24,
    "CL": 24,
}

LABEL_BY_ORIG_TYPE = {
    1: "st tetrahedral Si",
    2: "ao octahedral Al",
    3: "at tetrahedral Al",
    4: "mgo octahedral Mg",
    5: "mgh hydroxide Mg",
    6: "cao octahedral Ca",
    7: "cah hydroxide Ca",
    8: "feo octahedral Fe",
    9: "lio octahedral Li",
    10: "ob bridging oxygen",
    11: "obss oxygen double substituted",
    12: "obts oxygen tetrahedral substituted",
    13: "obos oxygen octahedral substituted",
    14: "ohs substituted hydroxyl O",
    15: "oh hydroxyl O",
    16: "o* SPC/E water O",
    17: "ho hydroxyl H",
    18: "h* SPC/E water H",
    19: "Na sodium ion",
    20: "K potassium ion",
    21: "Cs cesium ion",
    22: "Ca calcium ion",
    23: "Ba barium ion",
    24: "Cl chloride ion",
    25: "Mg magnesium ion",
}

MASS_BY_ORIG_TYPE = {
    1: 28.0855,
    2: 26.9815385,
    3: 26.9815385,
    4: 24.305,
    5: 24.305,
    6: 40.078,
    7: 40.078,
    8: 55.845,
    9: 6.94,
    10: 15.9994,
    11: 15.9994,
    12: 15.9994,
    13: 15.9994,
    14: 15.9994,
    15: 15.9994,
    16: 15.9994,
    17: 1.008,
    18: 1.008,
    19: 22.98976928,
    20: 39.0983,
    21: 132.90545196,
    22: 40.078,
    23: 137.327,
    24: 35.45,
    25: 24.305,
}

DEFAULT_CHARGE_BY_ORIG_TYPE = {
    1: 2.1,
    2: 1.575,
    3: 1.575,
    4: 1.36,
    5: 1.05,
    6: 1.36,
    7: 1.05,
    8: 1.575,
    9: 0.525,
    10: -1.05,
    11: -1.2996,
    12: -1.1688,
    13: -1.1808,
    14: -1.0808,
    15: -0.95,
    16: -0.8476,  # overwritten by SPC/E template if provided
    17: 0.425,
    18: 0.4238,   # overwritten by SPC/E template if provided
    19: 1.0,
    20: 1.0,
    21: 1.0,
    22: 2.0,
    23: 2.0,
    24: -1.0,
    25: 2.0,
}

# Original bond and angle type meaning in clayff-paper-2021.
ORIG_BOND_LABELS = {
    1: "o*-h* water",
    2: "oh-ho hydroxyl",
    3: "ohs-ho substituted hydroxyl",
}
ORIG_ANGLE_LABELS = {
    1: "h*-o*-h* water",
    2: "ao-oh/ohs-ho surface hydroxyl",
    3: "ao-oh/ohs-ho bulk hydroxyl",
    4: "mgo-oh/ohs-ho surface hydroxyl",
    5: "mgo-oh/ohs-ho bulk hydroxyl",
    6: "st-oh/ohs-ho hydroxyl",
}


def strip_suffix(atom_name: str) -> str:
    return re.sub(r"\d+$", "", atom_name.strip())


def suffix(atom_name: str) -> Optional[str]:
    m = re.search(r"(\d+)$", atom_name)
    return m.group(1) if m else None


def read_spce_charges(spce_path: Optional[Path]) -> Tuple[float, float]:
    """Return (oxygen_charge, hydrogen_charge)."""
    if spce_path is None:
        return -0.8476, 0.4238
    text = spce_path.read_text().splitlines()
    in_charges = False
    vals: List[Tuple[int, float]] = []
    for line in text:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower() == "charges":
            in_charges = True
            continue
        if in_charges:
            if re.match(r"^[A-Za-z]", s):
                break
            parts = s.split()
            if len(parts) >= 2 and parts[0].isdigit():
                vals.append((int(parts[0]), float(parts[1])))
            if len(vals) >= 3:
                break
    if len(vals) >= 3:
        # Template convention in the uploaded file: atom 1 O, atoms 2/3 H.
        return vals[0][1], vals[1][1]
    return -0.8476, 0.4238


def parse_gro(gro_path: Path, charges: Dict[int, float]) -> Tuple[List[Atom], Tuple[float, float, float]]:
    lines = gro_path.read_text().splitlines()
    if len(lines) < 3:
        raise ValueError(f"Invalid .gro file: {gro_path}")
    try:
        n_atoms = int(lines[1].strip())
    except ValueError as exc:
        raise ValueError("Second line of .gro must contain atom count") from exc

    atom_lines = lines[2:2 + n_atoms]
    if len(atom_lines) != n_atoms:
        raise ValueError(".gro atom count does not match number of atom lines")
    box_vals = [float(x) for x in lines[2 + n_atoms].split()]
    if len(box_vals) < 3:
        raise ValueError("Only orthorhombic .gro boxes with 3 box lengths are supported")
    box = tuple(v * 10.0 for v in box_vals[:3])  # nm -> Å

    atoms: List[Atom] = []
    for idx, line in enumerate(atom_lines, start=1):
        resid_s = line[0:5].strip()
        resname = line[5:10].strip()
        name = line[10:15].strip()
        try:
            resid = int(resid_s)
        except ValueError:
            resid = idx
        try:
            x = float(line[20:28]) * 10.0
            y = float(line[28:36]) * 10.0
            z = float(line[36:44]) * 10.0
        except ValueError:
            parts = line.split()
            name = parts[1] if len(parts) >= 5 else name
            x, y, z = (float(parts[-3]) * 10.0, float(parts[-2]) * 10.0, float(parts[-1]) * 10.0)
        base = strip_suffix(name)
        if base not in TYPE_BY_BASE:
            raise KeyError(f"Unknown atom name/base '{name}' -> '{base}' at atom {idx}")
        orig_type_id = TYPE_BY_BASE[base]
        mol = resid
        atoms.append(
            Atom(
                id=idx,
                resid=resid,
                resname=resname,
                name=name,
                base=base,
                orig_type_id=orig_type_id,
                type_id=orig_type_id,  # compacted later
                charge=charges[orig_type_id],
                mol=mol,
                x=x,
                y=y,
                z=z,
            )
        )
    return atoms, box


def parse_coeff_line(line: str) -> Coeff:
    left, sep, comment = line.partition("#")
    parts = left.split()
    if len(parts) < 2 or not parts[0].isdigit():
        raise ValueError(f"Invalid coefficient line: {line}")
    return Coeff(orig_id=int(parts[0]), values=" ".join(parts[1:]), comment=comment.strip())


def parse_clayff_coeffs(clayff_path: Path) -> Tuple[Dict[int, Coeff], Dict[int, Coeff], Dict[int, Coeff]]:
    """Parse pair coeffs, harmonic bond coeffs, and harmonic angle coeffs.

    The uploaded file contains both `Bond Coeffs # harmonic` and
    `Bond Coeffs # morse`. This converter intentionally ignores the Morse
    section because the generated LAMMPS data is meant for `bond_style harmonic`.
    """
    pair: Dict[int, Coeff] = {}
    bond_harmonic: Dict[int, Coeff] = {}
    angle_harmonic: Dict[int, Coeff] = {}
    current: Optional[str] = None

    for raw in clayff_path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("pair coeffs"):
            current = "pair"
            continue
        if lower.startswith("bond coeffs"):
            if "harmonic" in lower:
                current = "bond_harmonic"
            else:
                current = "ignore"  # Morse or any unsupported bond section
            continue
        if lower.startswith("angle coeffs"):
            if "harmonic" in lower:
                current = "angle_harmonic"
            else:
                current = "ignore"
            continue
        if current is None or current == "ignore" or stripped.startswith("#"):
            continue
        if not re.match(r"^\d+\s+", stripped):
            continue
        coeff = parse_coeff_line(stripped)
        if current == "pair":
            pair[coeff.orig_id] = coeff
        elif current == "bond_harmonic":
            bond_harmonic[coeff.orig_id] = coeff
        elif current == "angle_harmonic":
            angle_harmonic[coeff.orig_id] = coeff

    if not pair:
        raise ValueError("No Pair Coeffs parsed from CLAYFF file")
    if not bond_harmonic:
        raise ValueError("No harmonic Bond Coeffs parsed from CLAYFF file")
    if not angle_harmonic:
        raise ValueError("No harmonic Angle Coeffs parsed from CLAYFF file")
    return pair, bond_harmonic, angle_harmonic


def minimum_image_delta(a: Tuple[float, float, float], b: Tuple[float, float, float], box: Tuple[float, float, float]) -> Tuple[float, float, float]:
    out = []
    for i, L in enumerate(box):
        d = a[i] - b[i]
        if L > 0:
            d -= round(d / L) * L
        out.append(d)
    return out[0], out[1], out[2]


def pbc_distance(a: Atom, b: Atom, box: Tuple[float, float, float]) -> float:
    dx, dy, dz = minimum_image_delta((a.x, a.y, a.z), (b.x, b.y, b.z), box)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def group_by_residue(atoms: Iterable[Atom]) -> Dict[Tuple[int, str], List[Atom]]:
    d: Dict[Tuple[int, str], List[Atom]] = defaultdict(list)
    for a in atoms:
        d[(a.resid, a.resname)].append(a)
    return d


def generate_topology(atoms: List[Atom], box: Tuple[float, float, float], mo_cutoff: float):
    """Return original-type bonds and angles.

    Bond tuple: (orig_bond_type, atom1, atom2)
    Angle tuple: (orig_angle_type, atom1, atom2, atom3)
    """
    by_res = group_by_residue(atoms)
    bonds: List[Tuple[int, int, int]] = []
    angles: List[Tuple[int, int, int, int]] = []
    mineral_oh_bonds: List[Tuple[Atom, Atom]] = []  # (O, H)

    # Water: one OW and two HW per iSL residue.
    bad_waters = []
    for key, lst in by_res.items():
        resname = key[1]
        if resname == "iSL" or any(a.base in ("OW", "HW") for a in lst):
            ow = [a for a in lst if a.base == "OW"]
            hw = [a for a in lst if a.base == "HW"]
            if len(ow) == 1 and len(hw) == 2:
                o = ow[0]
                h1, h2 = sorted(hw, key=lambda x: x.name)
                bonds.append((1, o.id, h1.id))
                bonds.append((1, o.id, h2.id))
                angles.append((1, h1.id, o.id, h2.id))
            else:
                bad_waters.append((key, len(ow), len(hw)))
    if bad_waters:
        raise ValueError(f"Found water residues not matching 1 OW + 2 HW: {bad_waters[:5]}")

    # Mineral hydroxyl O-H bonds by matching suffix inside each D**** residue.
    missing_oh = []
    for key, lst in by_res.items():
        resname = key[1]
        if not resname.startswith("D"):
            continue
        by_name = {a.name: a for a in lst}
        for h in [a for a in lst if a.base == "HO"]:
            suf = suffix(h.name)
            if suf is None:
                missing_oh.append((key, h.name, "no numeric suffix"))
                continue
            o = by_name.get(f"OH{suf}") or by_name.get(f"OHS{suf}")
            if o is None:
                missing_oh.append((key, h.name, f"no OH{suf}/OHS{suf}"))
                continue
            orig_bond_type = 2 if o.base == "OH" else 3
            bonds.append((orig_bond_type, o.id, h.id))
            mineral_oh_bonds.append((o, h))
    if missing_oh:
        raise ValueError(f"Missing hydroxyl O for some HO atoms: {missing_oh[:10]}")

    # Mineral M-O-H angles. Search globally with PBC because OH groups at unit-cell
    # boundaries may coordinate to metal atoms in neighbouring residues.
    metal_atoms = [a for a in atoms if a.resname.startswith("D") and a.base in ("AO", "MGO", "ST")]
    angle_counts_per_oh = Counter()
    for o, h in mineral_oh_bonds:
        local_count = 0
        for m in metal_atoms:
            d = pbc_distance(o, m, box)
            if d <= mo_cutoff:
                if m.base == "AO":
                    orig_angle_type = 3  # bulk ao-oh/ohs-ho
                elif m.base == "MGO":
                    orig_angle_type = 5  # bulk mgo-oh/ohs-ho
                elif m.base == "ST":
                    orig_angle_type = 6  # st-oh/ohs-ho
                else:
                    continue
                angles.append((orig_angle_type, m.id, o.id, h.id))
                local_count += 1
        angle_counts_per_oh[local_count] += 1
    if angle_counts_per_oh.get(0, 0) > 0:
        raise ValueError(f"Some hydroxyl O-H bonds generated no M-O-H angle: {angle_counts_per_oh}")
    return bonds, angles, angle_counts_per_oh


def compact_atom_types(atoms: List[Atom]) -> Dict[int, int]:
    used_orig_types = sorted({a.orig_type_id for a in atoms})
    orig_to_new = {orig: new for new, orig in enumerate(used_orig_types, start=1)}
    for a in atoms:
        a.type_id = orig_to_new[a.orig_type_id]
    return orig_to_new


def compact_bond_types(bonds: List[Tuple[int, int, int]]) -> Tuple[List[Tuple[int, int, int]], Dict[int, int]]:
    used = sorted({bt for bt, _, _ in bonds})
    mapping = {orig: new for new, orig in enumerate(used, start=1)}
    return [(mapping[bt], a1, a2) for bt, a1, a2 in bonds], mapping


def compact_angle_types(angles: List[Tuple[int, int, int, int]]) -> Tuple[List[Tuple[int, int, int, int]], Dict[int, int]]:
    used = sorted({at for at, _, _, _ in angles})
    mapping = {orig: new for new, orig in enumerate(used, start=1)}
    return [(mapping[at], a1, a2, a3) for at, a1, a2, a3 in angles], mapping


def coeff_with_new_id(coeffs: Dict[int, Coeff], orig_to_new: Dict[int, int]) -> List[str]:
    lines = []
    for orig, new in sorted(orig_to_new.items(), key=lambda kv: kv[1]):
        if orig not in coeffs:
            if orig == 25:
                raise ValueError("Exchangeable Mg parameters are not available in the force-field file.")
            raise KeyError(f"Missing coefficient for original type {orig}")
        c = coeffs[orig]
        comment = f" # original {orig}: {c.comment}" if c.comment else f" # original {orig}"
        lines.append(f"{new:4d} {c.values}{comment}")
    return lines


def write_lammps_data(
    out_path: Path,
    atoms: List[Atom],
    bonds: List[Tuple[int, int, int]],
    angles: List[Tuple[int, int, int, int]],
    box: Tuple[float, float, float],
    orig_to_new_atom: Dict[int, int],
    orig_to_new_bond: Dict[int, int],
    orig_to_new_angle: Dict[int, int],
    pair_coeffs: Dict[int, Coeff],
    bond_coeffs: Dict[int, Coeff],
    angle_coeffs: Dict[int, Coeff],
):
    atom_types = len(orig_to_new_atom)
    bond_types = len(orig_to_new_bond)
    angle_types = len(orig_to_new_angle)

    pair_lines = coeff_with_new_id(pair_coeffs, orig_to_new_atom)
    bond_lines = coeff_with_new_id(bond_coeffs, orig_to_new_bond)
    angle_lines = coeff_with_new_id(angle_coeffs, orig_to_new_angle)

    with out_path.open("w") as f:
        f.write("LAMMPS data generated from ClayCode .gro using compact CLAYFF/SPC/E rules\n\n")
        f.write(f"{len(atoms)} atoms\n")
        f.write(f"{len(bonds)} bonds\n")
        f.write(f"{len(angles)} angles\n\n")
        f.write(f"{atom_types} atom types\n")
        f.write(f"{bond_types} bond types\n")
        f.write(f"{angle_types} angle types\n\n")
        f.write(f"0.0 {box[0]:.10f} xlo xhi\n")
        f.write(f"0.0 {box[1]:.10f} ylo yhi\n")
        f.write(f"0.0 {box[2]:.10f} zlo zhi\n\n")

        f.write("Masses\n\n")
        for orig, new in sorted(orig_to_new_atom.items(), key=lambda kv: kv[1]):
            f.write(f"{new:4d} {MASS_BY_ORIG_TYPE[orig]:.8f} # original {orig}: {LABEL_BY_ORIG_TYPE.get(orig, '')}\n")
        f.write("\n")

        f.write("Pair Coeffs # lj/cut/coul/long\n\n")
        for line in pair_lines:
            f.write(line + "\n")
        f.write("\n")

        f.write("Bond Coeffs # harmonic\n\n")
        for line in bond_lines:
            f.write(line + "\n")
        f.write("\n")

        f.write("Angle Coeffs # harmonic\n\n")
        for line in angle_lines:
            f.write(line + "\n")
        f.write("\n")

        f.write("Atoms # full\n\n")
        for a in atoms:
            f.write(f"{a.id:8d} {a.mol:8d} {a.type_id:4d} {a.charge: .8f} {a.x: .10f} {a.y: .10f} {a.z: .10f}\n")
        f.write("\n")

        f.write("Bonds\n\n")
        for i, (bt, a1, a2) in enumerate(bonds, start=1):
            f.write(f"{i:8d} {bt:4d} {a1:8d} {a2:8d}\n")
        f.write("\n")

        f.write("Angles\n\n")
        for i, (at, a1, a2, a3) in enumerate(angles, start=1):
            f.write(f"{i:8d} {at:4d} {a1:8d} {a2:8d} {a3:8d}\n")
        f.write("\n")


def write_type_report(
    path: Path,
    atoms: List[Atom],
    orig_to_new_atom: Dict[int, int],
    orig_to_new_bond: Dict[int, int],
    orig_to_new_angle: Dict[int, int],
):
    counts = Counter(a.orig_type_id for a in atoms)
    base_counts_by_orig = defaultdict(Counter)
    for a in atoms:
        base_counts_by_orig[a.orig_type_id][a.base] += 1
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section", "new_type", "original_type", "label", "count", "charge", "total_charge", "atom_bases"])
        for orig, new in sorted(orig_to_new_atom.items(), key=lambda kv: kv[1]):
            count = counts[orig]
            # All atoms of one original type use same charge in this converter.
            charge_values = {a.charge for a in atoms if a.orig_type_id == orig}
            charge = sorted(charge_values)[0]
            bases = ";".join(f"{b}:{c}" for b, c in sorted(base_counts_by_orig[orig].items()))
            w.writerow(["atom", new, orig, LABEL_BY_ORIG_TYPE.get(orig, ""), count, f"{charge:.8f}", f"{charge * count:.8f}", bases])
        for orig, new in sorted(orig_to_new_bond.items(), key=lambda kv: kv[1]):
            w.writerow(["bond", new, orig, ORIG_BOND_LABELS.get(orig, ""), "", "", "", ""])
        for orig, new in sorted(orig_to_new_angle.items(), key=lambda kv: kv[1]):
            w.writerow(["angle", new, orig, ORIG_ANGLE_LABELS.get(orig, ""), "", "", "", ""])


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert ClayCode .gro to compact LAMMPS data using CLAYFF/SPC/E rules.")
    ap.add_argument("--gro", required=True, type=Path, help="Input ClayCode .gro file")
    ap.add_argument("--clayff", required=True, type=Path, help="CLAYFF LAMMPS coeff file, e.g. clayff-paper-2021")
    ap.add_argument("--spce", type=Path, default=None, help="Original SPC/E source file with Charges section")
    ap.add_argument("--out", required=True, type=Path, help="Output LAMMPS data file")
    ap.add_argument("--mo-cutoff", type=float, default=2.20, help="M-O cutoff in Å for mineral M-O-H angles")
    ap.add_argument("--summary", type=Path, default=None, help="Optional text summary file")
    ap.add_argument("--type-report", type=Path, default=None, help="Optional CSV report of used atom/bond/angle types")
    args = ap.parse_args()

    charges = dict(DEFAULT_CHARGE_BY_ORIG_TYPE)
    ow_q, hw_q = read_spce_charges(args.spce)
    charges[16] = ow_q
    charges[18] = hw_q

    atoms, box = parse_gro(args.gro, charges)
    bonds_orig, angles_orig, angle_counts = generate_topology(atoms, box, args.mo_cutoff)

    orig_to_new_atom = compact_atom_types(atoms)
    bonds, orig_to_new_bond = compact_bond_types(bonds_orig)
    angles, orig_to_new_angle = compact_angle_types(angles_orig)

    pair_coeffs, bond_coeffs, angle_coeffs = parse_clayff_coeffs(args.clayff)
    write_lammps_data(
        args.out,
        atoms,
        bonds,
        angles,
        box,
        orig_to_new_atom,
        orig_to_new_bond,
        orig_to_new_angle,
        pair_coeffs,
        bond_coeffs,
        angle_coeffs,
    )

    if args.type_report:
        write_type_report(args.type_report, atoms, orig_to_new_atom, orig_to_new_bond, orig_to_new_angle)

    type_counts = Counter(a.type_id for a in atoms)
    orig_type_counts = Counter(a.orig_type_id for a in atoms)
    base_counts = Counter(a.base for a in atoms)
    res_counts = Counter(a.resname for a in atoms)
    bond_counts = Counter(bt for bt, _, _ in bonds)
    angle_type_counts = Counter(at for at, _, _, _ in angles)
    total_charge = sum(a.charge for a in atoms)

    water_new_type = orig_to_new_atom.get(16)
    water_h_new_type = orig_to_new_atom.get(18)
    water_bond_new_type = orig_to_new_bond.get(1)
    water_angle_new_type = orig_to_new_angle.get(1)

    summary_lines = []
    summary_lines.append(f"Wrote: {args.out}")
    summary_lines.append(f"Box (Å): x={box[0]:.6f}, y={box[1]:.6f}, z={box[2]:.6f}")
    summary_lines.append(f"Atoms: {len(atoms)}")
    summary_lines.append(f"Bonds: {len(bonds)}")
    summary_lines.append(f"Angles: {len(angles)}")
    summary_lines.append(f"Atom types used: {len(orig_to_new_atom)}")
    summary_lines.append(f"Bond types used: {len(orig_to_new_bond)}")
    summary_lines.append(f"Angle types used: {len(orig_to_new_angle)}")
    summary_lines.append(f"Total charge: {total_charge:.8f} e")
    summary_lines.append(f"Residue counts: {dict(res_counts)}")
    summary_lines.append(f"Atom base counts: {dict(base_counts)}")
    summary_lines.append(f"Original atom type counts: {dict(sorted(orig_type_counts.items()))}")
    summary_lines.append(f"New atom type counts: {dict(sorted(type_counts.items()))}")
    summary_lines.append(f"Original->new atom type map: {orig_to_new_atom}")
    summary_lines.append(f"Original->new bond type map: {orig_to_new_bond}")
    summary_lines.append(f"Original->new angle type map: {orig_to_new_angle}")
    summary_lines.append(f"Bond type counts (new): {dict(sorted(bond_counts.items()))}")
    summary_lines.append(f"Angle type counts (new): {dict(sorted(angle_type_counts.items()))}")
    summary_lines.append(f"M-O-H angle counts per hydroxyl: {dict(sorted(angle_counts.items()))}")
    summary_lines.append(f"Water O new type: {water_new_type}; water H new type: {water_h_new_type}")
    summary_lines.append(f"Water bond new type: {water_bond_new_type}; water angle new type: {water_angle_new_type}")
    if args.type_report:
        summary_lines.append(f"Type report: {args.type_report}")
    summary = "\n".join(summary_lines)
    print(summary)
    if args.summary:
        args.summary.write_text(summary + "\n")

    if abs(total_charge) > 1e-3:
        print("WARNING: total charge is not close to zero. Check atom type/charge mapping.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Prepare a ClayCode-derived LAMMPS data file for montmorillonite vapor sorption simulations.

This script is intended to run AFTER gro_clayff_to_lammps_v2.py and check_lammps_data.py.
It performs three operations:

1. Detect lower/upper clay sheets from clay molecule z-centers.
2. Increase z box length and recenter the system so the clay stack is centered with
   a user-defined external vapor space above and below.
3. Redistribute ONLY external exchangeable ions to a target bottom/interlayer/top count while
   keeping interlayer ions fixed.

Default target for the current 5x4, 2-sheet, charge -0.5 Na-Mt model:
    bottom external ions = 5
    interlayer ions      = 10  (kept unchanged)
    top external ions    = 5

Outputs:
    prepared LAMMPS data file
    JSON report with sheet ranges, exchangeable-ion distribution, type IDs, and suggested LAMMPS groups
    optional LAMMPS include file with group/type/region definitions

Assumptions:
    - atom_style full: id mol type charge x y z
    - type_report.csv produced by gro_clayff_to_lammps_v2.py is available
    - clay atoms are all atoms except water OW/HW and configured exchangeable ions
    - exchangeable ions have no bonds/angles, so moving them does not affect topology
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class Atom:
    atom_id: int
    mol_id: int
    atom_type: int
    charge: float
    x: float
    y: float
    z: float


@dataclass
class Bond:
    bond_id: int
    bond_type: int
    a: int
    b: int


@dataclass
class Bounds:
    xlo: float
    xhi: float
    ylo: float
    yhi: float
    zlo: float
    zhi: float

    @property
    def lx(self) -> float:
        return self.xhi - self.xlo

    @property
    def ly(self) -> float:
        return self.yhi - self.ylo

    @property
    def lz(self) -> float:
        return self.zhi - self.zlo


SECTION_NAMES = (
    "Masses",
    "Pair Coeffs",
    "Bond Coeffs",
    "Angle Coeffs",
    "Atoms",
    "Bonds",
    "Angles",
    "Velocities",
    "Dihedrals",
    "Impropers",
)


def is_section_header(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(name) for name in SECTION_NAMES)


def section_key(line: str) -> str:
    stripped = line.strip()
    for name in SECTION_NAMES:
        if stripped.startswith(name):
            return name
    raise ValueError(f"Not a section header: {line!r}")


def parse_data(path: Path) -> Tuple[str, Dict[str, List[str]], List[str], Bounds, List[Atom], List[Bond]]:
    """Return title, sections, header lines, bounds, atoms, bonds."""
    lines = path.read_text().splitlines()
    if not lines:
        raise ValueError("Empty LAMMPS data file")

    title = lines[0]
    sections: Dict[str, List[str]] = {}
    section_headers: Dict[str, str] = {}
    header_lines: List[str] = []

    current = None
    current_lines: List[str] = []
    before_first_section = True

    for line in lines[1:]:
        if is_section_header(line):
            if before_first_section:
                before_first_section = False
            else:
                if current is not None:
                    sections[current] = current_lines
            current = section_key(line)
            section_headers[current] = line
            current_lines = [line]
        else:
            if before_first_section:
                header_lines.append(line)
            else:
                if current is not None:
                    current_lines.append(line)
    if current is not None:
        sections[current] = current_lines

    bounds = parse_bounds(header_lines)
    atoms = parse_atoms(sections.get("Atoms", []))
    bonds = parse_bonds(sections.get("Bonds", []))
    if not atoms:
        raise ValueError("No atoms parsed from Atoms section")
    return title, sections, header_lines, bounds, atoms, bonds


def parse_bounds(header_lines: List[str]) -> Bounds:
    xlo = xhi = ylo = yhi = zlo = zhi = None
    pat = re.compile(r"^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([xyz])lo\s+\3hi")
    for line in header_lines:
        m = pat.match(line)
        if not m:
            continue
        lo = float(m.group(1))
        hi = float(m.group(2))
        axis = m.group(3)
        if axis == "x":
            xlo, xhi = lo, hi
        elif axis == "y":
            ylo, yhi = lo, hi
        elif axis == "z":
            zlo, zhi = lo, hi
    if None in (xlo, xhi, ylo, yhi, zlo, zhi):
        raise ValueError("Could not parse x/y/z box bounds")
    return Bounds(xlo, xhi, ylo, yhi, zlo, zhi)


def parse_atoms(atom_section: List[str]) -> List[Atom]:
    atoms: List[Atom] = []
    for line in atom_section:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("Atoms"):
            continue
        parts = s.split()
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        atoms.append(
            Atom(
                atom_id=int(parts[0]),
                mol_id=int(parts[1]),
                atom_type=int(parts[2]),
                charge=float(parts[3]),
                x=float(parts[4]),
                y=float(parts[5]),
                z=float(parts[6]),
            )
        )
    return atoms


def parse_bonds(bond_section: List[str]) -> List[Bond]:
    bonds: List[Bond] = []
    for line in bond_section:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("Bonds"):
            continue
        parts = s.split()
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        bonds.append(Bond(bond_id=int(parts[0]), bond_type=int(parts[1]), a=int(parts[2]), b=int(parts[3])))
    return bonds


def load_type_report(path: Path, ion_species: str = "Na") -> Dict[str, object]:
    water_o_types = set()
    water_h_types = set()
    ion_types = set()
    atom_type_info = {}
    ion_base_names = {ion_species, ion_species.upper()}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("section") != "atom":
                continue
            t = int(row["new_type"])
            bases = row.get("atom_bases", "")
            label = row.get("label", "")
            charge = float(row["charge"]) if row.get("charge") else None
            count = int(row["count"]) if row.get("count") else None
            atom_type_info[t] = {"label": label, "charge": charge, "count": count, "bases": bases}
            if "OW:" in bases:
                water_o_types.add(t)
            if "HW:" in bases:
                water_h_types.add(t)
            base_counts = {
                part.split(":", 1)[0].strip()
                for part in bases.split(";")
                if ":" in part
            }
            if base_counts & ion_base_names:
                ion_types.add(t)
    if not water_o_types or not water_h_types or not ion_types:
        raise ValueError(f"Could not identify water O/H or {ion_species} ion types from type_report.csv")
    return {
        "water_o_types": sorted(water_o_types),
        "water_h_types": sorted(water_h_types),
        "water_types": sorted(water_o_types | water_h_types),
        "ion_species": ion_species,
        "ion_types": sorted(ion_types),
        "na_types": sorted(ion_types) if ion_species == "Na" else [],
        "atom_type_info": atom_type_info,
    }


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals)


def detect_clay_sheets(atoms: List[Atom], water_types: set, ion_types: set) -> Dict[str, object]:
    clay_atoms = [a for a in atoms if a.atom_type not in water_types and a.atom_type not in ion_types]
    if not clay_atoms:
        raise ValueError("No clay atoms detected")

    atoms_by_mol: Dict[int, List[Atom]] = defaultdict(list)
    for a in clay_atoms:
        atoms_by_mol[a.mol_id].append(a)

    mol_centers = []
    for mol, mol_atoms in atoms_by_mol.items():
        mol_centers.append((mol, mean(a.z for a in mol_atoms), len(mol_atoms)))
    if len(mol_centers) < 2:
        raise ValueError("Need at least two clay molecules/unit cells to detect two sheets")
    mol_centers.sort(key=lambda x: x[1])

    # Split at the largest gap in molecule z-centers.
    gaps = [(mol_centers[i + 1][1] - mol_centers[i][1], i) for i in range(len(mol_centers) - 1)]
    max_gap, split_idx = max(gaps, key=lambda x: x[0])
    lower_mols = [m for m, _, _ in mol_centers[: split_idx + 1]]
    upper_mols = [m for m, _, _ in mol_centers[split_idx + 1 :]]
    if not lower_mols or not upper_mols:
        raise ValueError("Failed to split clay molecules into lower/upper sheets")

    lower_atoms = [a for a in clay_atoms if a.mol_id in set(lower_mols)]
    upper_atoms = [a for a in clay_atoms if a.mol_id in set(upper_mols)]
    if max_gap < 2.0:
        raise ValueError(f"Largest clay-sheet z gap is only {max_gap:.3f} Å; sheet detection may be wrong")

    return {
        "clay_atom_count": len(clay_atoms),
        "lower_mols": sorted(lower_mols),
        "upper_mols": sorted(upper_mols),
        "lower_atom_ids": sorted(a.atom_id for a in lower_atoms),
        "upper_atom_ids": sorted(a.atom_id for a in upper_atoms),
        "lower_zmin": min(a.z for a in lower_atoms),
        "lower_zmax": max(a.z for a in lower_atoms),
        "upper_zmin": min(a.z for a in upper_atoms),
        "upper_zmax": max(a.z for a in upper_atoms),
        "largest_gap_between_sheet_centers": max_gap,
    }




def normalize_molecule_ids(
    atoms: List[Atom],
    bonds: List[Bond],
    sheet: Dict[str, object],
    water_o_types: set,
    water_h_types: set,
    ion_types: set,
    ion_label: str = "exchangeable ions",
) -> Dict[str, object]:
    atom_by_id = {a.atom_id: a for a in atoms}
    lower_ids = set(sheet["lower_atom_ids"])
    upper_ids = set(sheet["upper_atom_ids"])
    water_o_ids = {a.atom_id for a in atoms if a.atom_type in water_o_types}
    water_h_ids = {a.atom_id for a in atoms if a.atom_type in water_h_types}
    ion_ids = {a.atom_id for a in atoms if a.atom_type in ion_types}

    bond_adj: Dict[int, List[int]] = defaultdict(list)
    for b in bonds:
        bond_adj[b.a].append(b.b)
        bond_adj[b.b].append(b.a)

    water_groups: List[List[int]] = []
    used_h: set[int] = set()
    malformed: List[object] = []
    for ow in sorted(water_o_ids):
        bonded_h = sorted(n for n in bond_adj.get(ow, []) if n in water_h_ids)
        if len(bonded_h) != 2:
            malformed.append({"oxygen_atom_id": ow, "bonded_hydrogen_ids": bonded_h})
            continue
        overlap = sorted(h for h in bonded_h if h in used_h)
        if overlap:
            malformed.append({"oxygen_atom_id": ow, "duplicate_hydrogen_ids": overlap})
            continue
        used_h.update(bonded_h)
        water_groups.append([ow] + bonded_h)

    unused_h = sorted(water_h_ids - used_h)
    if unused_h:
        malformed.append({"unassigned_hydrogen_ids": unused_h[:20], "count": len(unused_h)})
    if malformed:
        raise ValueError(f"Malformed water molecules during molecule-ID normalization: {malformed[:10]}")

    for atom_id in lower_ids:
        atom_by_id[atom_id].mol_id = 1
    for atom_id in upper_ids:
        atom_by_id[atom_id].mol_id = 2

    next_mol = 3
    for group in water_groups:
        if len(group) != 3:
            raise ValueError(f"Internal error: water group is not 3 atoms: {group}")
        for atom_id in group:
            atom_by_id[atom_id].mol_id = next_mol
        next_mol += 1

    for atom_id in ion_ids:
        atom_by_id[atom_id].mol_id = 0

    clay_lower_mol_ids = sorted({atom_by_id[i].mol_id for i in lower_ids})
    clay_upper_mol_ids = sorted({atom_by_id[i].mol_id for i in upper_ids})
    water_mol_ids = sorted({atom_by_id[i].mol_id for i in water_o_ids | water_h_ids})
    ion_mol_ids = sorted({atom_by_id[i].mol_id for i in ion_ids})

    warnings = []
    if set(water_mol_ids) & {1, 2}:
        warnings.append("Water molecule IDs overlap clay IDs 1 or 2 after normalization.")
    if set(ion_mol_ids) & {1, 2}:
        warnings.append(f"{ion_label} molecule IDs overlap clay IDs 1 or 2 after normalization.")

    return {
        "enabled": True,
        "clay_lower_mol_ids_after": clay_lower_mol_ids,
        "clay_upper_mol_ids_after": clay_upper_mol_ids,
        "exchangeable_ion_mol_ids_after": ion_mol_ids,
        "sodium_mol_ids_after": ion_mol_ids,
        "water_mol_id_min_after": min(water_mol_ids) if water_mol_ids else None,
        "water_mol_id_max_after": max(water_mol_ids) if water_mol_ids else None,
        "water_molecule_count": len(water_groups),
        "warnings": warnings,
    }

def classify_ions(atoms: List[Atom], ion_types: set, lower_zmin: float, lower_zmax: float, upper_zmin: float, upper_zmax: float) -> Dict[str, List[Atom]]:
    ion_atoms = [a for a in atoms if a.atom_type in ion_types]
    return {
        "bottom": [a for a in ion_atoms if a.z < lower_zmin],
        "interlayer": [a for a in ion_atoms if lower_zmax < a.z < upper_zmin],
        "top": [a for a in ion_atoms if a.z > upper_zmax],
        "inside_clay_or_ambiguous": [a for a in ion_atoms if not (a.z < lower_zmin or lower_zmax < a.z < upper_zmin or a.z > upper_zmax)],
    }


def grid_positions(n: int, bounds: Bounds, margin_fraction: float = 0.12) -> List[Tuple[float, float]]:
    """Deterministic quasi-uniform x-y positions inside the periodic cell."""
    if n <= 0:
        return []
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    x_margin = bounds.lx * margin_fraction
    y_margin = bounds.ly * margin_fraction
    if cols == 1:
        xs = [(bounds.xlo + bounds.xhi) / 2.0]
    else:
        xs = [bounds.xlo + x_margin + i * (bounds.lx - 2 * x_margin) / (cols - 1) for i in range(cols)]
    if rows == 1:
        ys = [(bounds.ylo + bounds.yhi) / 2.0]
    else:
        ys = [bounds.ylo + y_margin + j * (bounds.ly - 2 * y_margin) / (rows - 1) for j in range(rows)]
    pts = []
    for j in range(rows):
        for i in range(cols):
            if len(pts) >= n:
                break
            pts.append((xs[i], ys[j]))
    return pts


def wrap_xy(a: Atom, bounds: Bounds) -> None:
    if bounds.lx > 0:
        a.x = bounds.xlo + ((a.x - bounds.xlo) % bounds.lx)
    if bounds.ly > 0:
        a.y = bounds.ylo + ((a.y - bounds.ylo) % bounds.ly)


def prepare(
    atoms: List[Atom],
    old_bounds: Bounds,
    water_types: set,
    ion_types: set,
    external_space: float,
    target_bottom_ions: int,
    target_interlayer_ions: int,
    target_top_ions: int,
    ion_surface_distance: float,
    ion_species: str,
    water_o_types: set,
    water_h_types: set,
    bonds: List[Bond],
) -> Tuple[Bounds, Dict[str, object]]:
    # Detect initial sheets.
    sheet0 = detect_clay_sheets(atoms, water_types, ion_types)
    stack_zmin0 = sheet0["lower_zmin"]
    stack_zmax0 = sheet0["upper_zmax"]
    stack_height = stack_zmax0 - stack_zmin0

    new_bounds = Bounds(old_bounds.xlo, old_bounds.xhi, old_bounds.ylo, old_bounds.yhi, 0.0, stack_height + 2.0 * external_space)
    z_shift = external_space - stack_zmin0

    for a in atoms:
        a.z += z_shift
        wrap_xy(a, new_bounds)

    # Re-detect after shift.
    sheet = detect_clay_sheets(atoms, water_types, ion_types)
    lower_zmin = sheet["lower_zmin"]
    lower_zmax = sheet["lower_zmax"]
    upper_zmin = sheet["upper_zmin"]
    upper_zmax = sheet["upper_zmax"]

    before_ions = classify_ions(atoms, ion_types, lower_zmin, lower_zmax, upper_zmin, upper_zmax)
    interlayer_ions = before_ions["interlayer"]
    external_ions = sorted(before_ions["bottom"] + before_ions["top"], key=lambda a: a.atom_id)

    if before_ions["inside_clay_or_ambiguous"]:
        ids = [a.atom_id for a in before_ions["inside_clay_or_ambiguous"]]
        raise ValueError(f"{ion_species} ions inside clay/ambiguous region before redistribution: {ids}")
    if len(interlayer_ions) != target_interlayer_ions:
        raise ValueError(
            f"Interlayer {ion_species} ion count is {len(interlayer_ions)}, expected {target_interlayer_ions}. "
            f"This script keeps interlayer {ion_species} ions fixed, so inspect the structure first."
        )
    if len(external_ions) != target_bottom_ions + target_top_ions:
        raise ValueError(
            f"External {ion_species} ion count is {len(external_ions)}, expected {target_bottom_ions + target_top_ions}. "
            "Cannot redistribute to requested bottom/top counts."
        )

    bottom_ions = external_ions[:target_bottom_ions]
    top_ions = external_ions[target_bottom_ions: target_bottom_ions + target_top_ions]

    bottom_xy = grid_positions(target_bottom_ions, new_bounds)
    top_xy = grid_positions(target_top_ions, new_bounds)
    # Stagger top relative to bottom to avoid artificial vertical alignment.
    top_xy = [
        (new_bounds.xlo + ((x + 0.5 * new_bounds.lx / max(1, math.ceil(math.sqrt(target_top_ions))) - new_bounds.xlo) % new_bounds.lx), y)
        for x, y in top_xy
    ]

    bottom_z_base = lower_zmin - ion_surface_distance
    top_z_base = upper_zmax + ion_surface_distance
    if bottom_z_base <= new_bounds.zlo + 0.5:
        raise ValueError(f"Bottom {ion_species} ion z position too close to lower box boundary. Increase --external-space.")
    if top_z_base >= new_bounds.zhi - 0.5:
        raise ValueError(f"Top {ion_species} ion z position too close to upper box boundary. Increase --external-space.")

    for i, a in enumerate(bottom_ions):
        a.x, a.y = bottom_xy[i]
        a.z = bottom_z_base + (i - (target_bottom_ions - 1) / 2.0) * 0.05
    for i, a in enumerate(top_ions):
        a.x, a.y = top_xy[i]
        a.z = top_z_base + (i - (target_top_ions - 1) / 2.0) * 0.05

    after_ions = classify_ions(atoms, ion_types, lower_zmin, lower_zmax, upper_zmin, upper_zmax)
    mol_norm = normalize_molecule_ids(
        atoms=atoms,
        bonds=bonds,
        sheet=sheet,
        water_o_types=water_o_types,
        water_h_types=water_h_types,
        ion_types=ion_types,
        ion_label=f"{ion_species} ions",
    )

    report = {
        "old_box": asdict(old_bounds),
        "new_box": asdict(new_bounds),
        "external_space_each_side_A": external_space,
        "z_shift_A": z_shift,
        "sheet_detection": sheet,
        "regions": {
            "bottom_external_z": [new_bounds.zlo, lower_zmin],
            "interlayer_z": [lower_zmax, upper_zmin],
            "top_external_z": [upper_zmax, new_bounds.zhi],
        },
        "ion_species": ion_species,
        "target_ion_distribution": {"bottom_external": target_bottom_ions, "interlayer": target_interlayer_ions, "top_external": target_top_ions},
        "ion_distribution_before": {k: len(v) for k, v in before_ions.items()},
        "ion_distribution_after": {k: len(v) for k, v in after_ions.items()},
        "na_distribution_before": {k: len(v) for k, v in before_ions.items()} if ion_species == "Na" else None,
        "na_distribution_after": {k: len(v) for k, v in after_ions.items()} if ion_species == "Na" else None,
        "moved_bottom_ion_ids": [a.atom_id for a in bottom_ions],
        "moved_top_ion_ids": [a.atom_id for a in top_ions],
        "moved_bottom_na_ids": [a.atom_id for a in bottom_ions] if ion_species == "Na" else [],
        "moved_top_na_ids": [a.atom_id for a in top_ions] if ion_species == "Na" else [],
        "type_ids": {
            "water_types": sorted(water_types),
            "ion_types": sorted(ion_types),
            "na_types": sorted(ion_types) if ion_species == "Na" else [],
        },
        "molecule_id_normalization": mol_norm,
        "suggested_lammps_groups": {
            "clay_lower_molecules": [1],
            "clay_upper_molecules": [2],
            "water_types": sorted(water_types),
            "ion_species": ion_species,
            "ion_types": sorted(ion_types),
            "na_types": sorted(ion_types) if ion_species == "Na" else [],
        },
    }
    return new_bounds, report


def replace_atoms_section(section: List[str], atoms: List[Atom]) -> List[str]:
    out = []
    header_written = False
    atom_map = {a.atom_id: a for a in atoms}
    for line in section:
        s = line.strip()
        if s.startswith("Atoms"):
            out.append(line)
            header_written = True
            continue
        if not s:
            out.append(line)
            continue
        parts = s.split()
        if len(parts) >= 7 and parts[0].isdigit():
            atom_id = int(parts[0])
            a = atom_map[atom_id]
            out.append(
                f"{a.atom_id:8d} {a.mol_id:8d} {a.atom_type:4d} {a.charge: .8f} "
                f"{a.x: .10f} {a.y: .10f} {a.z: .10f}"
            )
        else:
            out.append(line)
    if not header_written:
        raise ValueError("Atoms section header not found")
    return out


def update_header_bounds(header_lines: List[str], new_bounds: Bounds) -> List[str]:
    out = []
    for line in header_lines:
        if re.search(r"\sxlo\s+xhi", line):
            out.append(f"{new_bounds.xlo:.10f} {new_bounds.xhi:.10f} xlo xhi")
        elif re.search(r"\sylo\s+yhi", line):
            out.append(f"{new_bounds.ylo:.10f} {new_bounds.yhi:.10f} ylo yhi")
        elif re.search(r"\szlo\s+zhi", line):
            out.append(f"{new_bounds.zlo:.10f} {new_bounds.zhi:.10f} zlo zhi")
        else:
            out.append(line)
    return out


def write_data(path: Path, title: str, header_lines: List[str], sections: Dict[str, List[str]], atoms: List[Atom], new_bounds: Bounds) -> None:
    header = update_header_bounds(header_lines, new_bounds)
    sections_out = dict(sections)
    sections_out["Atoms"] = replace_atoms_section(sections["Atoms"], atoms)

    order = ["Masses", "Pair Coeffs", "Bond Coeffs", "Angle Coeffs", "Atoms", "Bonds", "Angles"]
    with path.open("w") as f:
        f.write(title + "\n")
        for line in header:
            f.write(line + "\n")
        for key in order:
            if key not in sections_out:
                continue
            f.write("\n")
            for line in sections_out[key]:
                f.write(line + "\n")


def write_lammps_include(path: Path, report: Dict[str, object], bounds: Bounds) -> None:
    g = report["suggested_lammps_groups"]
    regions = report["regions"]
    lower_mols = " ".join(str(i) for i in g["clay_lower_molecules"])
    upper_mols = " ".join(str(i) for i in g["clay_upper_molecules"])
    water_types = " ".join(str(i) for i in g["water_types"])
    ion_types = " ".join(str(i) for i in g["ion_types"])

    with path.open("w") as f:
        f.write("# Auto-generated by prepare_mt_data.py\n")
        f.write(f"group clay_lower molecule {lower_mols}\n")
        f.write(f"group clay_upper molecule {upper_mols}\n")
        f.write("group clay union clay_lower clay_upper\n")
        f.write(f"group water type {water_types}\n")
        f.write(f"group exchangeable_ions type {ion_types}\n")
        f.write("group sodium union exchangeable_ions\n")
        f.write("group mobile union water exchangeable_ions\n")
        f.write("\n")
        f.write(f"region r_bottom_external block INF INF INF INF {regions['bottom_external_z'][0]:.6f} {regions['bottom_external_z'][1]:.6f} units box\n")
        f.write(f"region r_interlayer block INF INF INF INF {regions['interlayer_z'][0]:.6f} {regions['interlayer_z'][1]:.6f} units box\n")
        f.write(f"region r_top_external block INF INF INF INF {regions['top_external_z'][0]:.6f} {regions['top_external_z'][1]:.6f} units box\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare ClayCode-derived montmorillonite LAMMPS data for GCMC-MD.")
    ap.add_argument("--data", required=True, type=Path, help="Input LAMMPS data file from converter")
    ap.add_argument("--type-report", required=True, type=Path, help="type_report.csv from converter")
    ap.add_argument("--out", required=True, type=Path, help="Prepared output LAMMPS data")
    ap.add_argument("--report", default=None, type=Path, help="JSON report path")
    ap.add_argument("--lammps-include", default=None, type=Path, help="Optional LAMMPS group/region include file")
    ap.add_argument("--external-space", type=float, default=30.0, help="External vapor space on each side, Å; default 30")
    ap.add_argument("--ion-species", default="Na", help="Exchangeable ion species label to detect in type_report.csv")
    ap.add_argument("--target-bottom-ions", type=int, default=None)
    ap.add_argument("--target-interlayer-ions", type=int, default=None)
    ap.add_argument("--target-top-ions", type=int, default=None)
    ap.add_argument("--target-bottom-na", type=int, default=None, help="Deprecated alias for --target-bottom-ions")
    ap.add_argument("--target-interlayer-na", type=int, default=None, help="Deprecated alias for --target-interlayer-ions")
    ap.add_argument("--target-top-na", type=int, default=None, help="Deprecated alias for --target-top-ions")
    ap.add_argument("--ion-surface-distance", type=float, default=3.0, help="Exchangeable-ion distance from external clay surface, Å; default 3")
    ap.add_argument("--na-surface-distance", type=float, default=None, help="Deprecated alias for --ion-surface-distance")
    args = ap.parse_args()

    title, sections, header_lines, bounds, atoms, bonds = parse_data(args.data)
    type_info = load_type_report(args.type_report, ion_species=args.ion_species)
    water_types = set(type_info["water_types"])
    water_o_types = set(type_info["water_o_types"])
    water_h_types = set(type_info["water_h_types"])
    ion_types = set(type_info["ion_types"])
    target_bottom_ions = args.target_bottom_ions if args.target_bottom_ions is not None else args.target_bottom_na
    target_interlayer_ions = args.target_interlayer_ions if args.target_interlayer_ions is not None else args.target_interlayer_na
    target_top_ions = args.target_top_ions if args.target_top_ions is not None else args.target_top_na
    target_bottom_ions = 5 if target_bottom_ions is None else target_bottom_ions
    target_interlayer_ions = 10 if target_interlayer_ions is None else target_interlayer_ions
    target_top_ions = 5 if target_top_ions is None else target_top_ions
    ion_surface_distance = args.na_surface_distance if args.na_surface_distance is not None else args.ion_surface_distance

    new_bounds, report = prepare(
        atoms=atoms,
        old_bounds=bounds,
        water_types=water_types,
        ion_types=ion_types,
        external_space=args.external_space,
        target_bottom_ions=target_bottom_ions,
        target_interlayer_ions=target_interlayer_ions,
        target_top_ions=target_top_ions,
        ion_surface_distance=ion_surface_distance,
        ion_species=args.ion_species,
        water_o_types=water_o_types,
        water_h_types=water_h_types,
        bonds=bonds,
    )

    write_data(args.out, title + " | prepared for vapor GCMC", header_lines, sections, atoms, new_bounds)

    report_path = args.report or args.out.with_suffix(".prepare_report.json")
    report_path.write_text(json.dumps(report, indent=2))

    if args.lammps_include:
        write_lammps_include(args.lammps_include, report, new_bounds)

    print(f"Wrote prepared data: {args.out}")
    print(f"Wrote report: {report_path}")
    if args.lammps_include:
        print(f"Wrote LAMMPS include: {args.lammps_include}")
    print(f"{args.ion_species} ion distribution before:", report["ion_distribution_before"])
    print(f"{args.ion_species} ion distribution after: ", report["ion_distribution_after"])
    print("New z box:", report["new_box"]["zlo"], report["new_box"]["zhi"])


if __name__ == "__main__":
    main()

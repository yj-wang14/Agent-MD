#!/usr/bin/env python3
"""Generate ClayCode YAML/CSV input pairs for charge and cation series."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_VALENCE = {
    "Li": 1,
    "Na": 1,
    "K": 1,
    "Rb": 1,
    "Cs": 1,
    "Mg": 2,
    "Ca": 2,
    "Sr": 2,
    "Ba": 2,
}

COMPOSITION_ROWS = [
    ("T", "Si"),
    ("T", "Al"),
    ("T", "Fe"),
    ("O", "Fe"),
    ("O", "Fe3"),
    ("O", "Fe2"),
    ("O", "Al"),
    ("O", "Mg"),
    ("O", "Mn"),
    ("O", "Ti"),
    ("I", "Ca"),
    ("I", "Na"),
    ("I", "Mg"),
    ("I", "K"),
    ("I", "Cl"),
    ("C", "T"),
    ("C", "O"),
    ("C", "tot"),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read/write ClayCode YAML inputs") from exc
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read/write ClayCode YAML inputs") from exc
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def load_case_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_yaml(path)


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def fmt_number(value: float) -> str:
    if abs(value) < 5e-13:
        value = 0.0
    text = f"{value:.12g}"
    return "0" if text == "-0" else text


def charge_tag(charge: float) -> str:
    return fmt_number(charge).replace("-", "m").replace(".", "p")


def layer_charge_tag(charge: float) -> str:
    return f"LC{int(round(charge * 100)):03d}"


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def variant_name(base_name: str, cation: str, charge: float, total_cation_count: int) -> str:
    return f"{safe_name(base_name)}_{cation}_{layer_charge_tag(charge)}_N{total_cation_count}"


def cation_valence(cation: str, valence_overrides: dict[str, int] | None = None) -> int:
    overrides = valence_overrides or {}
    valence = overrides.get(cation, DEFAULT_VALENCE.get(cation))
    if valence is None:
        raise ValueError(f"No valence known for cation {cation}; pass --valence {cation}:N")
    if valence <= 0:
        raise ValueError(f"Cation valence must be positive for {cation}, got {valence}")
    return int(valence)


def parse_valence_overrides(items: list[str]) -> dict[str, int]:
    overrides = {}
    for item in items:
        if ":" not in item:
            raise ValueError(f"Valence override must be ELEMENT:VALENCE, got {item}")
        element, raw = item.split(":", 1)
        overrides[element] = int(raw)
    return overrides


def composition_value(sheet: str, element: str, cation: str, charge: float, valence: int) -> str:
    x = charge
    if sheet == "T" and element == "Si":
        return "8"
    if sheet == "O" and element == "Al":
        return fmt_number(4.0 - x)
    if sheet == "O" and element == "Mg":
        return fmt_number(x)
    if sheet == "I" and element == cation:
        return fmt_number(x / valence)
    if sheet == "C" and element == "T":
        return "0"
    if sheet == "C" and element in {"O", "tot"}:
        return fmt_number(-x)
    return ""


def write_composition_csv(path: Path, sysname: str, cation: str, charge: float, valence: int) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sheet", "element", sysname])
        for sheet, element in COMPOSITION_ROWS:
            writer.writerow([sheet, element, composition_value(sheet, element, cation, charge, valence)])


def validate_charge(charge: float) -> None:
    if charge < 0:
        raise ValueError(f"Layer-charge magnitude must be non-negative, got {charge}")
    if charge > 4:
        raise ValueError(f"Octahedral Mg substitution x must be <= 4 so Al=4-x stays non-negative, got {charge}")


def total_cation_count(
    *,
    layer_charge_magnitude: float,
    valence: int,
    total_unit_cells: int,
    tolerance: float = 1.0e-6,
) -> int:
    raw_count = layer_charge_magnitude / valence * total_unit_cells
    nearest = round(raw_count)
    if abs(raw_count - nearest) > tolerance:
        raise ValueError(
            "Interlayer cation count is not an integer: "
            f"layer_charge/valence*X_CELLS*Y_CELLS*N_SHEETS = "
            f"{layer_charge_magnitude}/{valence}*{total_unit_cells} = {raw_count:.12g}. "
            "Change layer_charge or supercell size so the total cation count is integral."
        )
    return int(nearest)



def ion_partition_counts(
    *,
    total_cation_count: int,
    ratio: tuple[int, int, int] = (1, 2, 1),
    allow_uneven: bool = False,
) -> dict[str, int | list[int]]:
    ratio_sum = sum(ratio)
    if ratio_sum <= 0 or any(x < 0 for x in ratio):
        raise ValueError(f"Ion partition ratio must contain non-negative counts with positive sum, got {ratio}")
    if not allow_uneven and total_cation_count % ratio_sum != 0:
        raise ValueError(
            "Ion partition count is not compatible with the default bottom:interlayer:top "
            f"ratio {ratio[0]}:{ratio[1]}:{ratio[2]}: total_cation_count={total_cation_count} "
            f"is not divisible by {ratio_sum}. Change layer_charge or supercell size, "
            "or pass --allow-uneven-partition to generate the ClayCode inputs without "
            "integer preparation targets."
        )
    if total_cation_count % ratio_sum != 0:
        return {
            "ion_partition_ratio": list(ratio),
            "target_bottom_ions": None,
            "target_interlayer_ions": None,
            "target_top_ions": None,
        }
    scale = total_cation_count // ratio_sum
    return {
        "ion_partition_ratio": list(ratio),
        "target_bottom_ions": ratio[0] * scale,
        "target_interlayer_ions": ratio[1] * scale,
        "target_top_ions": ratio[2] * scale,
    }

def build_yaml(template: dict[str, Any], sysname: str, csv_name: str) -> dict[str, Any]:
    data = dict(template)
    data["SYSNAME"] = sysname
    data["CLAY_COMP"] = csv_name
    data["CLAY_TYPE"] = "D21"
    data["X_CELLS"] = 5
    data["Y_CELLS"] = 4
    data["N_SHEETS"] = 2
    return data


def default_paths_from_case(case_path: Path) -> tuple[Path, Path, Path]:
    case_cfg = load_case_yaml(case_path)
    base_dir = case_path.parent.resolve()
    clay_cfg = case_cfg.get("claycode", {})
    if not isinstance(clay_cfg, dict):
        clay_cfg = {}
    work_dir = resolve_path(clay_cfg.get("work_dir", "assets/claycode"), base_dir)
    template_yaml = work_dir / str(clay_cfg.get("input_yaml", "MyMont1.yaml"))
    template_csv = work_dir / str(clay_cfg.get("exp_csv", "exp_clay.csv"))
    return work_dir, template_yaml, template_csv


def generate_plan(
    *,
    case_path: Path,
    template_yaml: Path | None,
    template_csv: Path | None,
    out_dir: Path | None,
    cations: list[str],
    charges: list[float],
    base_name: str | None,
    valence_overrides: dict[str, int] | None = None,
    force: bool = False,
    ion_partition_ratio: tuple[int, int, int] = (1, 2, 1),
    allow_uneven_partition: bool = False,
) -> dict[str, Any]:
    work_dir, default_yaml, default_csv = default_paths_from_case(case_path)
    template_yaml = (template_yaml or default_yaml).resolve()
    template_csv = (template_csv or default_csv).resolve()
    out_dir = (out_dir or (work_dir / "planned_inputs")).resolve()

    if not template_yaml.exists():
        raise FileNotFoundError(f"Template YAML not found: {template_yaml}")
    if not template_csv.exists():
        raise FileNotFoundError(f"Template CSV not found: {template_csv}")
    if not cations:
        raise ValueError("At least one cation is required")
    if not charges:
        raise ValueError("At least one charge is required")

    template = load_yaml(template_yaml)
    base = base_name or str(template.get("SYSNAME", template_yaml.stem))
    out_dir.mkdir(parents=True, exist_ok=True)
    x_cells = 5
    y_cells = 4
    n_sheets = 2
    total_unit_cells = x_cells * y_cells * n_sheets

    variants = []
    for cation in cations:
        valence = cation_valence(cation, valence_overrides)
        for charge in charges:
            validate_charge(charge)
            total_cations = total_cation_count(
                layer_charge_magnitude=charge,
                valence=valence,
                total_unit_cells=total_unit_cells,
            )
            partition = ion_partition_counts(
                total_cation_count=total_cations,
                ratio=ion_partition_ratio,
                allow_uneven=allow_uneven_partition,
            )
            layer_charge_per_uc = -charge
            sysname = variant_name(base, cation, charge, total_cations)
            csv_name = f"{sysname}.csv"
            yaml_name = f"{sysname}.yaml"
            csv_path = out_dir / csv_name
            yaml_path = out_dir / yaml_name
            if not force:
                existing = [str(path) for path in (csv_path, yaml_path) if path.exists()]
                if existing:
                    raise FileExistsError(f"Refusing to overwrite existing planned inputs: {existing}")
            write_composition_csv(csv_path, sysname, cation, charge, valence)
            write_yaml(yaml_path, build_yaml(template, sysname, csv_name))
            metadata_path = out_dir / f"{sysname}.metadata.json"
            metadata = {
                "sysname": sysname,
                "cation": cation,
                "valence": valence,
                "substitution_amount_x": charge,
                "layer_charge_per_uc_signed": layer_charge_per_uc,
                "layer_charge_label": layer_charge_tag(charge),
                "interlayer_cation_per_uc": charge / valence,
                "total_unit_cells": total_unit_cells,
                "total_cation_count": total_cations,
                **partition,
                "yaml": str(yaml_path),
                "csv": str(csv_path),
                "metadata": str(metadata_path),
            }
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
            variants.append(metadata)

    plan = {
        "status": "generated",
        "created_at": now_iso(),
        "case": str(case_path),
        "template_yaml": str(template_yaml),
        "template_csv": str(template_csv),
        "out_dir": str(out_dir),
        "fixed_geometry": {"CLAY_TYPE": "D21", "X_CELLS": x_cells, "Y_CELLS": y_cells, "N_SHEETS": n_sheets},
        "total_unit_cells": total_unit_cells,
        "ion_partition_ratio": list(ion_partition_ratio),
        "allow_uneven_partition": allow_uneven_partition,
        "composition_rule": {
            "T_Si": 8,
            "O_Al": "4 - x",
            "O_Mg": "x",
            "substitution_amount_x": "x",
            "layer_charge_per_uc_signed": "-x",
            "I_cation": "x / valence",
            "total_ionic_charge": "x * X_CELLS * Y_CELLS * N_SHEETS",
            "total_cation_count": "x / valence * X_CELLS * Y_CELLS * N_SHEETS",
            "ion_partition_counts": "total_cation_count split by bottom:interlayer:top ratio",
            "C_O": "-x",
            "C_tot": "-x",
        },
        "variants": variants,
    }
    (out_dir / "claycode_input_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ClayCode YAML/CSV input pairs without running ClayCode.")
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--template-yaml", type=Path, default=None)
    parser.add_argument("--template-csv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--cation", action="append", dest="cations", default=[])
    parser.add_argument("--charge", action="append", dest="charges", type=float, default=[])
    parser.add_argument("--base-name", default=None)
    parser.add_argument("--valence", action="append", default=[], help="Override cation valence as ELEMENT:VALENCE")
    parser.add_argument("--allow-uneven-partition", action="store_true", help="Allow total cation counts that cannot be split by the ion partition ratio")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        plan = generate_plan(
            case_path=args.case,
            template_yaml=args.template_yaml,
            template_csv=args.template_csv,
            out_dir=args.out_dir,
            cations=args.cations,
            charges=args.charges,
            base_name=args.base_name,
            valence_overrides=parse_valence_overrides(args.valence),
            force=args.force,
            allow_uneven_partition=args.allow_uneven_partition,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()

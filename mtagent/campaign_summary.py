#!/usr/bin/env python3
"""Export a compact summary table for archived campaign RH states."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mtagent import plan_campaign

FIELDS = [
    "system_id",
    "cation",
    "layer_charge",
    "RH",
    "final_step",
    "total_water",
    "interlayer_water",
    "external_water",
    "basal_proxy",
    "ion_count",
    "metadata_status",
    "analysis_status",
    "analysis_recommendation",
    "fatal_errors",
    "known_warnings",
    "archived_restart",
]

SYSTEM_RE = re.compile(r"^Mt_(?P<cation>[A-Za-z0-9]+)_LC(?P<lc>[0-9]+)_N(?P<count>[0-9]+)$")


def repo_relative(path_value: Any, base_dir: Path) -> str:
    if path_value in (None, ""):
        return ""
    path = Path(str(path_value))
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path)


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def load_json_graceful(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        return {}, [f"could not read summary.json: {exc}"]
    except json.JSONDecodeError as exc:
        return {}, [f"malformed summary.json: {exc}"]
    if not isinstance(data, dict):
        return {}, ["summary.json is not an object"]
    return data, []


def load_case_metadata(system_dir: Path, system_id: str) -> tuple[dict[str, Any], bool]:
    candidates = [
        system_dir.parent.parent / f"case.{system_id}.yaml",
        system_dir / "case.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            cfg = plan_campaign.load_yaml(path)
        except Exception:
            continue
        return (cfg if isinstance(cfg, dict) else {}), True
    return {}, False


def metadata_from_system_id(system_id: str) -> dict[str, Any]:
    match = SYSTEM_RE.match(system_id)
    if not match:
        return {}
    lc_digits = match.group("lc")
    layer_charge = f"LC{lc_digits}"
    try:
        layer_charge = str(-int(lc_digits) / 100.0)
    except ValueError:
        pass
    return {
        "cation": match.group("cation"),
        "layer_charge": layer_charge,
        "ion_count": int(match.group("count")),
    }


def system_metadata(system_dir: Path, system_id: str) -> dict[str, Any]:
    parsed = metadata_from_system_id(system_id)
    cfg, found_case = load_case_metadata(system_dir, system_id)
    case = cfg.get("case", {}) if isinstance(cfg.get("case"), dict) else {}
    structure = cfg.get("structure", {}) if isinstance(cfg.get("structure"), dict) else {}
    metadata = dict(parsed)
    if structure.get("cation"):
        metadata["cation"] = structure.get("cation")
    if structure.get("layer_charge_per_uc") is not None:
        metadata["layer_charge"] = structure.get("layer_charge_per_uc")
    elif case.get("name") and not metadata.get("layer_charge"):
        metadata["layer_charge"] = case.get("name")
    if structure.get("expected_ion_count") is not None:
        metadata["ion_count"] = structure.get("expected_ion_count")
    if metadata.get("cation") and metadata.get("layer_charge") not in (None, "") and metadata.get("ion_count") not in (None, ""):
        metadata["metadata_status"] = "complete" if found_case else "inferred"
    else:
        metadata["metadata_status"] = "missing"
    return metadata


def campaign_system_ids(campaign_path: Path) -> set[str]:
    campaign = plan_campaign.load_yaml(campaign_path)
    systems = campaign.get("systems", []) if isinstance(campaign, dict) else []
    result: set[str] = set()
    if not isinstance(systems, list):
        return result
    for item in systems:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict):
            system_id = item.get("system_id") or item.get("id") or item.get("name")
            if system_id:
                result.add(str(system_id))
    return result


def row_from_summary(summary_path: Path, base_dir: Path) -> dict[str, Any]:
    rh_dir = summary_path.parent
    system_dir = rh_dir.parent.parent
    system_id = system_dir.name
    summary, load_errors = load_json_graceful(summary_path)
    meta = system_metadata(system_dir, system_id)
    fatal_errors = []
    if isinstance(summary.get("fatal_errors"), list):
        fatal_errors.extend(str(item) for item in summary.get("fatal_errors", []))
    fatal_errors.extend(load_errors)

    ion_count = (
        summary.get("ion_count_final")
        or summary.get("ion_count")
        or summary.get("expected_ion_count")
        or meta.get("ion_count")
    )
    archived_restart = (
        summary.get("archived_restart")
        or summary.get("selected_restart")
        or summary.get("selected_restart_path")
        or summary.get("source_restart")
    )
    return {
        "system_id": system_id,
        "cation": meta.get("cation", ""),
        "layer_charge": meta.get("layer_charge", ""),
        "RH": summary.get("rh") or rh_dir.name.replace("rh_", "").replace("p", "."),
        "final_step": summary.get("final_step"),
        "total_water": summary.get("total_water"),
        "interlayer_water": summary.get("interlayer_water"),
        "external_water": summary.get("external_water"),
        "basal_proxy": summary.get("basal_proxy"),
        "ion_count": ion_count,
        "metadata_status": meta.get("metadata_status", "missing"),
        "analysis_status": summary.get("analysis_status") or summary.get("equilibrium_status"),
        "analysis_recommendation": summary.get("analysis_recommendation") or summary.get("equilibrium_recommendation"),
        "fatal_errors": fatal_errors,
        "known_warnings": summary.get("known_warnings", []),
        "archived_restart": repo_relative(archived_restart, base_dir),
    }


def collect_campaign_summary(
    *,
    examples_dir: Path,
    base_dir: Path,
    campaign_path: Path | None = None,
    all_states: bool = False,
) -> list[dict[str, Any]]:
    allowed_systems = None
    if campaign_path is not None and not all_states:
        allowed_systems = campaign_system_ids(campaign_path)
    rows = []
    for summary_path in sorted(examples_dir.glob("*/states/rh_*/summary.json")):
        system_id = summary_path.parent.parent.parent.name
        if allowed_systems is not None and system_id not in allowed_systems:
            continue
        rows.append(row_from_summary(summary_path, base_dir))
    return sorted(rows, key=lambda row: (str(row.get("system_id", "")), -float(row.get("RH") or 0.0)))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in FIELDS})


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Campaign Summary",
        "",
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(csv_value(row.get(field)) for field in FIELDS) + " |")
    path.write_text("\n".join(lines) + "\n")


def generate_campaign_summary(
    *,
    base_dir: Path,
    out_dir: Path | None = None,
    examples_dir: Path | None = None,
    campaign_path: Path | None = None,
    all_states: bool = False,
) -> list[dict[str, Any]]:
    base_dir = base_dir.resolve()
    target_examples = (examples_dir or base_dir / "examples").resolve()
    target_out = (out_dir or base_dir / "generated").resolve()
    target_campaign = campaign_path.resolve() if campaign_path is not None else None
    rows = collect_campaign_summary(
        examples_dir=target_examples,
        base_dir=base_dir,
        campaign_path=target_campaign,
        all_states=all_states,
    )
    write_csv(target_out / "campaign_summary.csv", rows)
    write_markdown(target_out / "campaign_summary.md", rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Export compact campaign archive summary tables.")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--examples-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--campaign", type=Path, default=None)
    parser.add_argument("--all-states", action="store_true", help="Include archived states outside the selected campaign.")
    args = parser.parse_args()
    rows = generate_campaign_summary(
        base_dir=args.base_dir,
        out_dir=args.out_dir,
        examples_dir=args.examples_dir,
        campaign_path=args.campaign,
        all_states=args.all_states,
    )
    print(json.dumps({"rows": len(rows), "csv": "generated/campaign_summary.csv", "markdown": "generated/campaign_summary.md"}, indent=2))


if __name__ == "__main__":
    main()

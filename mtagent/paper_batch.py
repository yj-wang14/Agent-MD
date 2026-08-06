#!/usr/bin/env python3
"""Export paper RH-water uptake batch tables, figures, and final reports."""

from __future__ import annotations

import argparse
import base64
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
from mtagent.campaign_summary import csv_value, repo_relative, system_metadata

PAPER_CSV = "paper_rh_water_uptake.csv"
PAPER_MD = "paper_rh_water_uptake.md"
FIG_CATION = "fig_rh_water_cation_LC040.png"
FIG_NA_CEC = "fig_rh_water_Na_CEC.png"
REPORT_MD = "paper_batch_final_report.md"
REPORT_JSON = "paper_batch_final_summary.json"

FIELDS = [
    "system_id",
    "cation",
    "layer_charge",
    "RH",
    "rh_tag",
    "status",
    "recommendation",
    "final_step",
    "total_water",
    "interlayer_water",
    "external_water",
    "basal_proxy",
    "ion_count_initial",
    "ion_count_final",
    "ion_count_stable",
    "fatal_errors",
    "known_warnings",
    "block_reason",
    "archived_restart",
]

SYSTEM_RE = re.compile(r"^Mt_(?P<cation>[A-Za-z]+)_LC(?P<lc>[0-9]+)_N(?P<count>[0-9]+)$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def rh_tag(rh: float) -> str:
    return plan_campaign.rh_tag(float(rh))


def rh_dir(tag: str) -> str:
    return tag.replace("rh", "rh_")


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def campaign_systems(campaign_path: Path) -> list[dict[str, Any]]:
    cfg = plan_campaign.load_yaml(campaign_path)
    systems = cfg.get("systems", []) if isinstance(cfg, dict) else []
    if not isinstance(systems, list):
        return []
    return [dict(item) for item in systems if isinstance(item, dict)]


def campaign_rh_path(campaign_path: Path) -> list[float]:
    cfg = plan_campaign.load_yaml(campaign_path)
    return [float(rh) for rh in cfg.get("rh_path", [])]


def archive_summary_path(base_dir: Path, system_id: str, tag: str) -> Path:
    return base_dir / "examples" / system_id / "states" / rh_dir(tag) / "summary.json"


def analysis_path(base_dir: Path, system_id: str, tag: str) -> Path:
    return base_dir / "examples" / system_id / "generated" / f"{system_id}.{tag.replace('rh', 'rh_')}_analysis.json"


def continue_status_path(base_dir: Path, system_id: str, tag: str) -> Path:
    return base_dir / "examples" / system_id / "generated" / f"{system_id}.{tag.replace('rh', 'rh_')}_continue_or_archive_status.json"


def row_for_system_rh(base_dir: Path, system: dict[str, Any], rh: float) -> dict[str, Any]:
    system_id = str(system["system_id"])
    tag = rh_tag(rh)
    system_dir = base_dir / "examples" / system_id
    meta = system_metadata(system_dir, system_id)
    cation = system.get("cation") or meta.get("cation", "")
    layer_charge = -float(system.get("substitution_amount_x")) if system.get("substitution_amount_x") is not None else meta.get("layer_charge", "")
    summary_path = archive_summary_path(base_dir, system_id, tag)
    analysis_file = analysis_path(base_dir, system_id, tag)
    status_file = continue_status_path(base_dir, system_id, tag)
    summary = load_json(summary_path)
    analysis = load_json(analysis_file)
    status_doc = load_json(status_file)
    source = summary or analysis or status_doc

    archived_restart = summary.get("archived_restart") or summary.get("selected_restart") or summary.get("selected_restart_path")
    status = summary.get("analysis_status") or summary.get("equilibrium_status") or analysis.get("status") or status_doc.get("status") or "missing"
    recommendation = summary.get("analysis_recommendation") or summary.get("equilibrium_recommendation") or analysis.get("recommendation") or status_doc.get("next_recommended_action")
    fatal_errors = source.get("fatal_errors") or source.get("errors") or []
    known_warnings = source.get("known_warnings") or []
    block_reason = ""
    if not summary:
        block_reason = status_doc.get("reason") or analysis.get("reasons") or analysis.get("recommendation") or "not_archived"
    if isinstance(block_reason, list):
        block_reason = "; ".join(str(item) for item in block_reason)

    return {
        "system_id": system_id,
        "cation": cation,
        "layer_charge": layer_charge,
        "RH": float(rh),
        "rh_tag": tag,
        "status": status,
        "recommendation": recommendation,
        "final_step": summary.get("final_step") or analysis.get("final_timestep"),
        "total_water": summary.get("total_water") or analysis.get("total_water_final"),
        "interlayer_water": summary.get("interlayer_water") or analysis.get("interlayer_water_final"),
        "external_water": summary.get("external_water") or analysis.get("external_water_final"),
        "basal_proxy": summary.get("basal_proxy") or analysis.get("basal_proxy_final"),
        "ion_count_initial": analysis.get("ion_count_initial"),
        "ion_count_final": summary.get("ion_count_final") or summary.get("ion_count") or analysis.get("ion_count_final") or system.get("expected_total_cation_count"),
        "ion_count_stable": analysis.get("ion_count_stable", ""),
        "fatal_errors": fatal_errors,
        "known_warnings": known_warnings,
        "block_reason": block_reason,
        "archived_restart": repo_relative(archived_restart, base_dir),
    }




def state_path_for(campaign_path: Path) -> Path:
    return campaign_path.with_suffix(".state.json")


def system_failure_reasons(base_dir: Path, campaign_path: Path) -> dict[str, str]:
    state = load_json(state_path_for(campaign_path))
    reasons: dict[str, list[str]] = {}
    for item in state.get("execution_history", []):
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status == "completed":
            continue
        system_id = item.get("system_id") or str(item.get("task_id", "")).split(":", 1)[0]
        if not system_id:
            continue
        parts = []
        for key in ["task_id", "stage", "reason", "error", "message"]:
            value = item.get(key)
            if value:
                parts.append(f"{key}={value}")
        if item.get("return_code") not in (None, ""):
            parts.append(f"return_code={item.get('return_code')}")
        if parts:
            reason = ", ".join(str(part) for part in parts)
            bucket = reasons.setdefault(str(system_id), [])
            if reason not in bucket:
                bucket.append(reason)
    return {system_id: " | ".join(entries[-3:]) for system_id, entries in reasons.items()}


def apply_failure_reasons(rows: list[dict[str, Any]], failure_reasons: dict[str, str]) -> None:
    for row in rows:
        reason = failure_reasons.get(str(row.get("system_id")))
        if reason and row.get("status") in {"missing", "failed", "blocked"}:
            row["status"] = "blocked"
            row["block_reason"] = reason


def collect_rows(base_dir: Path, campaign_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system in campaign_systems(campaign_path):
        for rh in campaign_rh_path(campaign_path):
            rows.append(row_for_system_rh(base_dir, system, rh))
    return rows


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
        "# Paper RH Water Uptake Summary",
        "",
        "| " + " | ".join(FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(csv_value(row.get(field)) for field in FIELDS) + " |")
    path.write_text("\n".join(lines) + "\n")


def minimal_png(path: Path) -> None:
    # 1x1 transparent PNG fallback when matplotlib is unavailable.
    data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    path.write_bytes(base64.b64decode(data))


def plot_rows(rows: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        minimal_png(out_dir / FIG_CATION)
        minimal_png(out_dir / FIG_NA_CEC)
        return

    lc040 = [row for row in rows if as_float(row.get("layer_charge")) == -0.4 and row.get("cation") in {"Na", "K", "Ca", "Ba"}]
    fig, ax = plt.subplots(figsize=(6, 4))
    for cation in ["Na", "K", "Ca", "Ba"]:
        series = sorted([row for row in lc040 if row.get("cation") == cation], key=lambda row: float(row["RH"]))
        x = [float(row["RH"]) for row in series if as_float(row.get("total_water")) is not None]
        y = [float(row["total_water"]) for row in series if as_float(row.get("total_water")) is not None]
        if x:
            ax.plot(x, y, marker="o", label=cation)
    ax.set_xlabel("Relative humidity")
    ax.set_ylabel("Total water")
    ax.set_title("LC040 cation RH-water uptake")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_dir / FIG_CATION, dpi=160)
    plt.close(fig)

    na_rows = [row for row in rows if row.get("cation") == "Na"]
    fig, ax = plt.subplots(figsize=(6, 4))
    for layer_charge in sorted({as_float(row.get("layer_charge")) for row in na_rows if as_float(row.get("layer_charge")) is not None}):
        series = sorted([row for row in na_rows if as_float(row.get("layer_charge")) == layer_charge], key=lambda row: float(row["RH"]))
        x = [float(row["RH"]) for row in series if as_float(row.get("total_water")) is not None]
        y = [float(row["total_water"]) for row in series if as_float(row.get("total_water")) is not None]
        if x:
            ax.plot(x, y, marker="o", label=f"LC{abs(layer_charge):.2f}")
    ax.set_xlabel("Relative humidity")
    ax.set_ylabel("Total water")
    ax.set_title("Na layer-charge RH-water uptake")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_dir / FIG_NA_CEC, dpi=160)
    plt.close(fig)


def status_by_system(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    completed: list[str] = []
    blocked: list[dict[str, Any]] = []
    by_system: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_system.setdefault(str(row["system_id"]), []).append(row)
    for system_id, system_rows in sorted(by_system.items()):
        if all(row.get("status") == "equilibrated" and row.get("recommendation") in {"archive", "write_data_and_continue_next_rh"} for row in system_rows):
            completed.append(system_id)
        else:
            blocked.append({
                "system_id": system_id,
                "rh_status": {str(row["rh_tag"]): {"status": row.get("status"), "recommendation": row.get("recommendation"), "reason": row.get("block_reason")} for row in system_rows},
            })
    return completed, blocked


def write_final_report(path: Path, rows: list[dict[str, Any]], completed: list[str], blocked: list[dict[str, Any]], generated_paths: dict[str, str]) -> None:
    lines = [
        "# Paper Batch Final Report",
        "",
        "## Completed systems",
    ]
    lines.extend(f"- {system_id}" for system_id in completed)
    if not completed:
        lines.append("- none")
    lines.extend(["", "## Blocked systems"])
    if blocked:
        for item in blocked:
            lines.append(f"- {item['system_id']}: {json.dumps(item['rh_status'], sort_keys=True)}")
    else:
        lines.append("- none")
    lines.extend(["", "## RH status table"])
    write_markdown_lines = ["| system_id | RH | status | recommendation | total | interlayer | external | basal | ion_count_final | block_reason |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        write_markdown_lines.append("| " + " | ".join(csv_value(row.get(key)) for key in ["system_id", "RH", "status", "recommendation", "total_water", "interlayer_water", "external_water", "basal_proxy", "ion_count_final", "block_reason"]) + " |")
    lines.extend(write_markdown_lines)
    lines.extend(["", "## Generated files"])
    for key, value in generated_paths.items():
        lines.append(f"- {key}: `{value}`")
    path.write_text("\n".join(lines) + "\n")


def generate_paper_outputs(*, base_dir: Path, campaign_path: Path, out_dir: Path | None = None) -> dict[str, Any]:
    base_dir = base_dir.resolve()
    campaign_path = campaign_path.resolve()
    target_out = (out_dir or base_dir / "generated").resolve()
    target_out.mkdir(parents=True, exist_ok=True)
    rows = collect_rows(base_dir, campaign_path)
    apply_failure_reasons(rows, system_failure_reasons(base_dir, campaign_path))
    completed, blocked = status_by_system(rows)
    paths = {
        "csv": repo_relative(target_out / PAPER_CSV, base_dir),
        "markdown": repo_relative(target_out / PAPER_MD, base_dir),
        "figure_cation_lc040": repo_relative(target_out / FIG_CATION, base_dir),
        "figure_na_cec": repo_relative(target_out / FIG_NA_CEC, base_dir),
        "report_md": repo_relative(target_out / REPORT_MD, base_dir),
        "summary_json": repo_relative(target_out / REPORT_JSON, base_dir),
    }
    write_csv(target_out / PAPER_CSV, rows)
    write_markdown(target_out / PAPER_MD, rows)
    plot_rows(rows, target_out)
    summary = {
        "campaign": repo_relative(campaign_path, base_dir),
        "completed_systems": completed,
        "blocked_systems": blocked,
        "rows": rows,
        "generated_files": paths,
    }
    write_final_report(target_out / REPORT_MD, rows, completed, blocked, paths)
    (target_out / REPORT_JSON).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export paper RH-water uptake batch outputs.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    result = generate_paper_outputs(base_dir=args.base_dir, campaign_path=args.campaign, out_dir=args.out_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

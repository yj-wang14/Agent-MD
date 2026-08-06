#!/usr/bin/env python3
"""Export a read-only validation report for archived campaign workflow results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mtagent.campaign_summary import campaign_system_ids, csv_value, row_from_summary
from mtagent import plan_campaign

REPORT_MD = "workflow_validation_report.md"
REPORT_JSON = "workflow_validation_summary.json"

RECOVERY_CASES = [
    {
        "title": "pre-GCMC basal drift fixed by holding clay z during soft-start",
        "summary": "Soft-start equilibration was corrected to restrain clay z motion before GCMC handoff, reducing pre-GCMC basal drift risk.",
    },
    {
        "title": "stricter RH handoff analyzer after marginal RH=0.9",
        "summary": "RH handoff analysis now uses the final 1M-step window and requires the adjacent previous water-slope window to pass before archive.",
    },
    {
        "title": "analyzer mismatch between run_campaign and run_cycle",
        "summary": "The campaign action and cycle runner were aligned on one strict analyzer path so continuation cannot be skipped by legacy criteria.",
    },
    {
        "title": "stale RH=0.7 state invalidated after upstream RH=0.9 restart changed",
        "summary": "Downstream RH=0.7 runtime was treated as smoke-only until regenerated from the latest RH=0.9 archive restart.",
    },
    {
        "title": "partial RH generalization: analyzer generalized before executor",
        "summary": "Read-only RH analysis was generalized first, then continuation/archive execution was generalized once the analyzer behavior was validated.",
    },
    {
        "title": "unsupported exchangeable Mg replaced by Ba smoke target",
        "summary": "Exchangeable Mg was rejected because no explicit ClayFF exchangeable Mg parameters are available; Ba LC040 uses explicit Ba parameters with a validated 2:4:2 partition, and no further Ba GCMC smoke is required at this stage.",
    },
]

LIMITATIONS = [
    "generic arbitrary RH path",
    "HPC/PBS submit/check/resume",
    "production-scale multi-cation/multi-charge campaigns, with Ba as the supported divalent smoke replacement for unsupported exchangeable Mg",
    "physical interpretation of Na RH=0.7 water increase needs further review",
]

TABLE_FIELDS = [
    "system_id",
    "RH",
    "final_step",
    "total_water",
    "interlayer_water",
    "external_water",
    "basal_proxy",
    "ion_count",
    "analysis_status",
    "analysis_recommendation",
    "archived_restart",
]


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def campaign_name(campaign_path: Path | None) -> str:
    if campaign_path is None:
        return "all archived states"
    campaign = plan_campaign.load_yaml(campaign_path)
    meta = campaign.get("campaign", {}) if isinstance(campaign, dict) else {}
    if isinstance(meta, dict) and meta.get("id"):
        return str(meta["id"])
    return campaign_path.stem


def iter_summary_paths(*, examples_dir: Path, campaign_path: Path | None, all_states: bool) -> list[Path]:
    allowed_systems = None
    if campaign_path is not None and not all_states:
        allowed_systems = campaign_system_ids(campaign_path)
    paths: list[Path] = []
    for summary_path in sorted(examples_dir.glob("*/states/rh_*/summary.json")):
        system_id = summary_path.parent.parent.parent.name
        if allowed_systems is not None and system_id not in allowed_systems:
            continue
        paths.append(summary_path)
    return paths


def status_file_counts(*, examples_dir: Path, campaign_path: Path | None, all_states: bool) -> dict[str, int]:
    allowed_systems = None
    if campaign_path is not None and not all_states:
        allowed_systems = campaign_system_ids(campaign_path)
    generated = 0
    archived = 0
    for path in examples_dir.glob("*/generated/*.json"):
        if allowed_systems is not None and path.parent.parent.name not in allowed_systems:
            continue
        generated += 1
    for path in examples_dir.glob("*/states/rh_*/*.json"):
        if allowed_systems is not None and path.parent.parent.parent.name not in allowed_systems:
            continue
        archived += 1
    return {"generated_status_files": generated, "archived_state_json_files": archived}


def build_archive_records(*, base_dir: Path, examples_dir: Path, campaign_path: Path | None, all_states: bool) -> list[dict[str, Any]]:
    records = []
    for summary_path in iter_summary_paths(examples_dir=examples_dir, campaign_path=campaign_path, all_states=all_states):
        row = row_from_summary(summary_path, base_dir)
        raw = load_json(summary_path)
        records.append({"summary_path": str(summary_path.relative_to(base_dir)), "row": row, "summary": raw})
    return records


def check_value(summary: dict[str, Any], key: str) -> bool | None:
    checks = summary.get("checks", {})
    if not isinstance(checks, dict) or key not in checks:
        return None
    return bool(checks[key])


def build_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    fatal_errors: list[str] = []
    known_warnings: set[str] = set()
    basal_checks: list[bool] = []
    ion_counts_present: list[bool] = []
    for record in records:
        row = record["row"]
        summary = record["summary"]
        fatal = row.get("fatal_errors") or []
        if isinstance(fatal, list):
            fatal_errors.extend(str(item) for item in fatal)
        elif fatal:
            fatal_errors.append(str(fatal))
        warnings = row.get("known_warnings") or []
        if isinstance(warnings, list):
            known_warnings.update(str(item) for item in warnings)
        elif warnings:
            known_warnings.add(str(warnings))
        basal_ok = check_value(summary, "basal_slope_ok")
        if basal_ok is not None:
            basal_checks.append(basal_ok)
        ion_counts_present.append(row.get("ion_count") not in (None, ""))
    return {
        "ion_count_stability": "passed" if records and all(ion_counts_present) else "unknown",
        "basal_stability": "passed" if basal_checks and all(basal_checks) else "unknown",
        "fatal_errors": fatal_errors,
        "no_fatal_errors": not fatal_errors,
        "known_warnings": sorted(known_warnings),
    }


def markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(TABLE_FIELDS) + " |",
        "| " + " | ".join("---" for _ in TABLE_FIELDS) + " |",
    ]
    if not rows:
        lines.append("| " + " | ".join("" for _ in TABLE_FIELDS) + " |")
        return lines
    for row in rows:
        lines.append("| " + " | ".join(csv_value(row.get(field)) for field in TABLE_FIELDS) + " |")
    return lines


def write_report_md(path: Path, *, overview: dict[str, Any], rows: list[dict[str, Any]], diagnostics: dict[str, Any], pipeline: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Workflow Validation Report",
        "",
        "## Campaign overview",
        f"- Campaign: {overview['campaign']}",
        f"- Campaign systems: {overview['campaign_system_count']}",
        f"- Archived RH states included: {overview['archived_state_count']}",
        f"- Scope: {'all archived states' if overview['all_states'] else 'campaign systems only'}",
        "",
        "## Completed archived states table",
        *markdown_table(rows),
        "",
        "## Action pipeline summary",
        f"- Generated status/history JSON files considered: {pipeline['generated_status_files']}",
        f"- Archived state JSON files considered: {pipeline['archived_state_json_files']}",
        "- Report mode: read-only; no simulation, continuation, or archive action executed.",
        "",
        "## Key diagnostics passed",
        f"- Ion count stability: {diagnostics['ion_count_stability']}",
        f"- Basal stability: {diagnostics['basal_stability']}",
        f"- No fatal errors: {'passed' if diagnostics['no_fatal_errors'] else 'failed'}",
        f"- Known warnings: {csv_value(diagnostics['known_warnings']) or 'none'}",
        "",
        "## Recovery / correction case studies",
    ]
    for case in RECOVERY_CASES:
        lines.append(f"- {case['title']}: {case['summary']}")
    lines.extend([
        "",
        "## Remaining limitations",
    ])
    lines.extend(f"- {item}" for item in LIMITATIONS)
    path.write_text("\n".join(lines) + "\n")


def generate_workflow_report(
    *,
    base_dir: Path,
    campaign_path: Path | None,
    out_dir: Path | None = None,
    examples_dir: Path | None = None,
    all_states: bool = False,
) -> dict[str, Any]:
    base_dir = base_dir.resolve()
    target_examples = (examples_dir or base_dir / "examples").resolve()
    target_out = (out_dir or base_dir / "generated").resolve()
    target_campaign = campaign_path.resolve() if campaign_path is not None else None
    records = build_archive_records(
        base_dir=base_dir,
        examples_dir=target_examples,
        campaign_path=target_campaign,
        all_states=all_states,
    )
    rows = [record["row"] for record in records]
    diagnostics = build_diagnostics(records)
    pipeline = status_file_counts(examples_dir=target_examples, campaign_path=target_campaign, all_states=all_states)
    system_count = len(campaign_system_ids(target_campaign)) if target_campaign is not None and not all_states else len({row.get("system_id") for row in rows})
    overview = {
        "campaign": campaign_name(target_campaign),
        "campaign_system_count": system_count,
        "archived_state_count": len(rows),
        "all_states": all_states,
    }
    result = {
        "overview": overview,
        "archived_states": rows,
        "action_pipeline_summary": pipeline,
        "key_diagnostics_passed": diagnostics,
        "recovery_correction_case_studies": RECOVERY_CASES,
        "remaining_limitations": LIMITATIONS,
    }
    target_out.mkdir(parents=True, exist_ok=True)
    (target_out / REPORT_JSON).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    write_report_md(target_out / REPORT_MD, overview=overview, rows=rows, diagnostics=diagnostics, pipeline=pipeline)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a read-only workflow validation report for archived campaign states.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    parser.add_argument("--examples-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--all-states", action="store_true", help="Include archived states outside the selected campaign.")
    args = parser.parse_args()
    result = generate_workflow_report(
        base_dir=args.base_dir,
        campaign_path=args.campaign,
        out_dir=args.out_dir,
        examples_dir=args.examples_dir,
        all_states=args.all_states,
    )
    print(json.dumps({"archived_states": result["overview"]["archived_state_count"], "markdown": f"generated/{REPORT_MD}", "json": f"generated/{REPORT_JSON}"}, indent=2))


if __name__ == "__main__":
    main()

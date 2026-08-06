#!/usr/bin/env python3
"""
Campaign manager for MD-GCMC Agent.

First-version function:
  - read equilibrium_status.json
  - read case.yaml if available
  - decide whether to continue current RH or move to next RH
  - estimate planned_extra_steps from slope severity
  - write manager_decision.json

Usage:
  python3 mtagent/campaign_manager.py decide examples/Mt_Oct050_Na/rh_0p90/equilibrium_status.json

Optional:
  python3 mtagent/campaign_manager.py decide examples/Mt_Oct050_Na/rh_0p90/equilibrium_status.json \
    --case case.yaml \
    --out examples/Mt_Oct050_Na/rh_0p90/manager_decision.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


DEFAULT_ADAPTIVE = {
    "small_drift_ratio": 1.5,
    "moderate_drift_ratio": 3.0,
    "small_extra_steps": 1_000_000,
    "moderate_extra_steps": 2_000_000,
    "large_extra_steps": 3_000_000,
    "segment_size": 500_000,
    "early_stop_allowed": True,
    "max_total_steps_per_rh": 5_000_000,
}


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text())


def load_case_yaml(path: Path | None) -> Dict[str, Any]:
    """
    Load case.yaml if PyYAML is installed.
    If not available or file missing, return empty dict and use defaults.
    """
    if path is None or not path.exists():
        return {}

    try:
        import yaml  # type: ignore
    except ImportError:
        print("WARNING: PyYAML is not installed. Using default manager settings.")
        return {}

    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_adaptive_config(case_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = DEFAULT_ADAPTIVE.copy()
    user_cfg = case_cfg.get("adaptive_extension", {})
    if isinstance(user_cfg, dict):
        cfg.update(user_cfg)
    return cfg


def slope_ratio_for_series(series_item: Dict[str, Any]) -> float | None:
    """
    Compute |slope| / allowed_slope from one series item.
    Compatible with analyzer output:
      - slope_per_100k
      - slope_limit_per_100k
      - slope_limit_A_per_100k
    """
    if "slope_per_100k" not in series_item:
        return None

    slope = abs(float(series_item["slope_per_100k"]))

    if "slope_limit_per_100k" in series_item:
        limit = abs(float(series_item["slope_limit_per_100k"]))
    elif "slope_limit_A_per_100k" in series_item:
        limit = abs(float(series_item["slope_limit_A_per_100k"]))
    else:
        return None

    if limit <= 0:
        return None

    return slope / limit


def find_limiting_variable(eq: Dict[str, Any]) -> Tuple[str | None, float]:
    """
    Find the variable with the largest slope ratio.
    We focus on variables relevant to equilibration.
    """
    series = eq.get("series", {})
    candidates = [
        "nwater_total",
        "nwater_inter",
        "nwater_ext",
        "basal_proxy",
    ]

    limiting_var = None
    max_ratio = 0.0

    for key in candidates:
        item = series.get(key)
        if not isinstance(item, dict):
            continue
        ratio = slope_ratio_for_series(item)
        if ratio is None:
            continue
        if ratio > max_ratio:
            max_ratio = ratio
            limiting_var = key

    return limiting_var, max_ratio


def planned_steps_from_ratio(ratio: float, adaptive: Dict[str, Any]) -> Tuple[int, str]:
    """
    Convert slope severity ratio into planned additional steps.

    Rule:
      R <= 1.0: equilibrated candidate
      1.0 < R <= small_drift_ratio: small drift -> 1M
      small_drift_ratio < R <= moderate_drift_ratio: moderate drift -> 2M
      R > moderate_drift_ratio: large drift -> 3M
    """
    small_ratio = float(adaptive["small_drift_ratio"])
    moderate_ratio = float(adaptive["moderate_drift_ratio"])

    if ratio <= 1.0:
        return int(adaptive["segment_size"]), "confirmation"

    if ratio <= small_ratio:
        return int(adaptive["small_extra_steps"]), "small_drift"

    if ratio <= moderate_ratio:
        return int(adaptive["moderate_extra_steps"]), "moderate_drift"

    return int(adaptive["large_extra_steps"]), "large_drift"


def decide(
    eq: Dict[str, Any],
    case_cfg: Dict[str, Any],
    max_total_steps_per_rh_override: int | None = None,
    rh_start_step: int = 0,
) -> Dict[str, Any]:
    adaptive = get_adaptive_config(case_cfg)
    if max_total_steps_per_rh_override is not None:
        adaptive["max_total_steps_per_rh"] = int(max_total_steps_per_rh_override)

    status = eq.get("status", "unknown")
    recommendation = eq.get("recommendation", "unknown")
    step_end = int(eq.get("step_end", -1))
    rh_start_step = max(0, int(rh_start_step))
    elapsed_steps_current_rh = max(0, step_end - rh_start_step) if step_end >= 0 else 0
    reasons = eq.get("reasons", [])

    limiting_var, max_ratio = find_limiting_variable(eq)
    planned_extra_steps, drift_class = planned_steps_from_ratio(max_ratio, adaptive)

    segment_size = int(adaptive["segment_size"])
    max_total_steps = int(adaptive["max_total_steps_per_rh"])

    # Default next segment should not exceed segment_size.
    next_segment_steps = min(segment_size, planned_extra_steps)

    decision: Dict[str, Any] = {
        "input_status": status,
        "input_recommendation": recommendation,
        "step_end": step_end,
        "rh_start_step": rh_start_step,
        "elapsed_steps_current_rh": elapsed_steps_current_rh,
        "action": None,
        "limiting_variable": limiting_var,
        "max_slope_ratio": max_ratio,
        "drift_class": drift_class,
        "planned_extra_steps": planned_extra_steps,
        "next_segment_steps": next_segment_steps,
        "segment_size": segment_size,
        "early_stop_allowed": bool(adaptive["early_stop_allowed"]),
        "max_total_steps_per_rh": max_total_steps,
        "reasons": reasons,
        "warnings": [],
    }

    if status == "equilibrated":
        decision["action"] = "write_data_and_continue_next_rh"
        decision["planned_extra_steps"] = 0
        decision["next_segment_steps"] = 0
        return decision

    if status == "not_enough_data":
        decision["action"] = "continue_current_rh"
        decision["planned_extra_steps"] = segment_size
        decision["next_segment_steps"] = segment_size
        decision["drift_class"] = "not_enough_data"
        return decision

    if status in {"not_equilibrated", "marginal"}:
        decision["action"] = "continue_current_rh"

        if elapsed_steps_current_rh >= max_total_steps:
            decision["action"] = "flag_for_manual_check"
            decision["warnings"].append(
                f"Current RH has reached max_total_steps_per_rh={max_total_steps}, "
                "but equilibrium criteria are still not satisfied."
            )

        if drift_class == "large_drift":
            decision["warnings"].append(
                "Large drift detected. Check GCMC region, possible condensation, "
                "restart stability, and physical setup before blindly extending."
            )

        return decision

    decision["action"] = "flag_for_manual_check"
    decision["warnings"].append(f"Unknown analyzer status: {status}")
    return decision


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_decide = sub.add_parser("decide", help="Decide next action from equilibrium_status.json")
    p_decide.add_argument("equilibrium_json", type=Path)
    p_decide.add_argument("--case", type=Path, default=Path("case.yaml"))
    p_decide.add_argument("--out", type=Path, default=None)
    p_decide.add_argument("--max-total-steps-per-rh-override", type=int, default=None)
    p_decide.add_argument("--rh-start-step", type=int, default=0)

    args = parser.parse_args()

    if args.command == "decide":
        eq = load_json(args.equilibrium_json)
        case_cfg = load_case_yaml(args.case)

        decision = decide(
            eq,
            case_cfg,
            max_total_steps_per_rh_override=args.max_total_steps_per_rh_override,
            rh_start_step=args.rh_start_step,
        )

        out_path = args.out
        if out_path is None:
            out_path = args.equilibrium_json.parent / "manager_decision.json"

        out_path.write_text(json.dumps(decision, indent=2))

        print(json.dumps({
            "action": decision["action"],
            "limiting_variable": decision["limiting_variable"],
            "max_slope_ratio": decision["max_slope_ratio"],
            "drift_class": decision["drift_class"],
            "planned_extra_steps": decision["planned_extra_steps"],
            "next_segment_steps": decision["next_segment_steps"],
            "out": str(out_path),
            "warnings": decision["warnings"],
        }, indent=2))


if __name__ == "__main__":
    main()

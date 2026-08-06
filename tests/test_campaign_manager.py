from __future__ import annotations

from mtagent.campaign_manager import decide


def adaptive_case() -> dict:
    return {
        "adaptive_extension": {
            "small_drift_ratio": 1.5,
            "moderate_drift_ratio": 3.0,
            "small_extra_steps": 1000000,
            "moderate_extra_steps": 2000000,
            "large_extra_steps": 3000000,
            "segment_size": 500000,
            "early_stop_allowed": True,
            "max_total_steps_per_rh": 5000000,
        }
    }


def equilibrium_with_ratio(status: str, ratio: float) -> dict:
    return {
        "status": status,
        "recommendation": "continue_current_rh",
        "step_end": 1000000,
        "reasons": [],
        "series": {
            "nwater_ext": {
                "slope_per_100k": ratio,
                "slope_limit_per_100k": 1.0,
            }
        },
    }


def test_equilibrated_moves_to_next_rh() -> None:
    decision = decide({"status": "equilibrated", "step_end": 1000000, "series": {}}, adaptive_case())

    assert decision["action"] == "write_data_and_continue_next_rh"
    assert decision["planned_extra_steps"] == 0
    assert decision["next_segment_steps"] == 0


def test_moderate_drift_continues_with_next_segment_capped() -> None:
    decision = decide(equilibrium_with_ratio("not_equilibrated", ratio=2.0), adaptive_case())

    assert decision["action"] == "continue_current_rh"
    assert decision["drift_class"] == "moderate_drift"
    assert decision["planned_extra_steps"] == 2000000
    assert decision["next_segment_steps"] == 500000


def test_large_drift_continues_with_larger_planned_steps() -> None:
    decision = decide(equilibrium_with_ratio("not_equilibrated", ratio=4.0), adaptive_case())

    assert decision["action"] == "continue_current_rh"
    assert decision["drift_class"] == "large_drift"
    assert decision["planned_extra_steps"] == 3000000
    assert decision["next_segment_steps"] == 500000
    assert decision["warnings"]


def test_max_total_steps_uses_elapsed_steps_with_inherited_timestep() -> None:
    eq = equilibrium_with_ratio("not_equilibrated", ratio=2.0)
    eq["step_end"] = 61_000_000

    decision = decide(eq, adaptive_case(), max_total_steps_per_rh_override=60_000_000, rh_start_step=42_000_000)

    assert decision["action"] == "continue_current_rh"
    assert decision["rh_start_step"] == 42_000_000
    assert decision["elapsed_steps_current_rh"] == 19_000_000


def test_max_total_steps_blocks_when_elapsed_current_rh_reaches_limit() -> None:
    eq = equilibrium_with_ratio("not_equilibrated", ratio=2.0)
    eq["step_end"] = 102_000_000

    decision = decide(eq, adaptive_case(), max_total_steps_per_rh_override=60_000_000, rh_start_step=42_000_000)

    assert decision["action"] == "flag_for_manual_check"
    assert decision["elapsed_steps_current_rh"] == 60_000_000

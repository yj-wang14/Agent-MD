from __future__ import annotations

import json
from pathlib import Path

from mtagent import paper_batch, run_campaign


def write_campaign(base: Path) -> Path:
    path = base / "examples" / "campaigns" / "paper.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """campaign:
  id: paper
rh_path: [0.90, 0.30]
systems:
  - system_id: Mt_Na_LC040_N16
    cation: Na
    valence: 1
    substitution_amount_x: 0.4
    expected_total_cation_count: 16
    expected_partition:
      bottom_external: 4
      interlayer: 8
      top_external: 4
  - system_id: Mt_Ba_LC040_N8
    cation: Ba
    valence: 2
    substitution_amount_x: 0.4
    expected_total_cation_count: 8
    expected_partition:
      bottom_external: 2
      interlayer: 4
      top_external: 2
"""
    )
    return path


def write_archive(base: Path, system_id: str, rh_dir: str, rh: float, final_step: int, total: int) -> None:
    state_dir = base / "examples" / system_id / "states" / rh_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    restart = state_dir / f"restart.gcmc_{rh_dir.replace('_', '')}.{final_step}"
    restart.write_text("restart\n")
    (state_dir / "summary.json").write_text(json.dumps({
        "rh": rh,
        "final_step": final_step,
        "total_water": total,
        "interlayer_water": total - 10,
        "external_water": 10,
        "basal_proxy": 19.8,
        "analysis_status": "equilibrated",
        "analysis_recommendation": "archive",
        "ion_count_final": 16 if "Na" in system_id else 8,
        "fatal_errors": [],
        "known_warnings": ["gcmc_full_energy"],
        "archived_restart": str(restart.relative_to(base)),
    }))


def test_paper_batch_exports_required_outputs_for_partial_campaign(tmp_path: Path) -> None:
    campaign = write_campaign(tmp_path)
    write_archive(tmp_path, "Mt_Na_LC040_N16", "rh_0p90", 0.9, 1000, 300)
    write_archive(tmp_path, "Mt_Na_LC040_N16", "rh_0p30", 0.3, 2000, 220)

    summary = paper_batch.generate_paper_outputs(base_dir=tmp_path, campaign_path=campaign)

    generated = tmp_path / "generated"
    for name in [
        "paper_rh_water_uptake.csv",
        "paper_rh_water_uptake.md",
        "fig_rh_water_cation_LC040.png",
        "fig_rh_water_Na_CEC.png",
        "paper_batch_final_report.md",
        "paper_batch_final_summary.json",
    ]:
        assert (generated / name).exists()
    assert summary["completed_systems"] == ["Mt_Na_LC040_N16"]
    assert summary["blocked_systems"][0]["system_id"] == "Mt_Ba_LC040_N8"
    report = (generated / "paper_batch_final_report.md").read_text()
    assert "Mt_Na_LC040_N16" in report
    assert "Mt_Ba_LC040_N8" in report


def test_paper_policy_rejects_unsupported_exchangeable_mg(tmp_path: Path) -> None:
    campaign_cfg = {
        "rh_path": [0.9, 0.3],
        "systems": [{"system_id": "Mt_Mg_LC040_N8", "cation": "Mg", "expected_total_cation_count": 8}],
    }
    task = {"task_id": "Mt_Mg_LC040_N8:plan_claycode_inputs", "system_id": "Mt_Mg_LC040_N8", "stage": "plan_claycode_inputs", "status": "ready"}

    allowed, policy = run_campaign.paper_policy_for_task(campaign_cfg=campaign_cfg, task=task, state={}, base_dir=tmp_path)

    assert allowed is False
    assert policy["reason"] == "unsupported_cation"


def test_paper_policy_blocks_rh03_before_rh09_archive(tmp_path: Path) -> None:
    campaign_cfg = {
        "rh_path": [0.9, 0.3],
        "systems": [{"system_id": "Mt_Na_LC040_N16", "cation": "Na", "expected_total_cation_count": 16}],
    }
    task = {
        "task_id": "Mt_Na_LC040_N16:start_next_rh0p30",
        "system_id": "Mt_Na_LC040_N16",
        "stage": "start_next_rh_0p30",
        "generic_stage": "start_next_rh",
        "rh_tag": "rh0p30",
        "previous_rh_tag": "rh0p90",
        "status": "ready",
    }

    allowed, policy = run_campaign.paper_policy_for_task(campaign_cfg=campaign_cfg, task=task, state={}, base_dir=tmp_path)

    assert allowed is False
    assert policy["reason"] == "missing_previous_rh_archive"

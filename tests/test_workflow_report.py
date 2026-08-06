from __future__ import annotations

import json
from pathlib import Path

from mtagent.workflow_report import generate_workflow_report


def write_campaign(base: Path) -> Path:
    path = base / "examples" / "campaigns" / "campaign.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """campaign:
  id: smoke
systems:
  - system_id: Mt_Na_LC050_N20
  - system_id: Mt_Ca_LC040_N8
"""
    )
    return path


def write_case(base: Path, system_id: str, cation: str, layer_charge: float, expected_ion_count: int) -> None:
    (base / f"case.{system_id}.yaml").write_text(
        f"""case:
  name: {system_id}
structure:
  cation: {cation}
  layer_charge_per_uc: {layer_charge}
  expected_ion_count: {expected_ion_count}
"""
    )


def write_summary(base: Path, system_id: str, rh_dir: str, payload: dict[str, object]) -> None:
    state_dir = base / "examples" / system_id / "states" / rh_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "summary.json").write_text(json.dumps(payload))


def sample_summary(rh: float, final_step: int, total: int, inter: int, ext: int, basal: float) -> dict[str, object]:
    return {
        "rh": rh,
        "final_step": final_step,
        "total_water": total,
        "interlayer_water": inter,
        "external_water": ext,
        "basal_proxy": basal,
        "analysis_status": "equilibrated",
        "analysis_recommendation": "archive",
        "fatal_errors": [],
        "known_warnings": ["gcmc_full_energy"],
        "checks": {"basal_slope_ok": True},
        "archived_restart": f"examples/restart.{final_step}",
    }


def test_workflow_report_generation_with_sample_archives(tmp_path: Path) -> None:
    campaign = write_campaign(tmp_path)
    write_case(tmp_path, "Mt_Na_LC050_N20", "Na", -0.5, 20)
    write_case(tmp_path, "Mt_Ca_LC040_N8", "Ca", -0.4, 8)
    write_summary(tmp_path, "Mt_Na_LC050_N20", "rh_0p90", sample_summary(0.9, 4100000, 462, 298, 164, 20.0522))
    write_summary(tmp_path, "Mt_Ca_LC040_N8", "rh_0p90", sample_summary(0.9, 4200000, 473, 280, 193, 19.5126))

    result = generate_workflow_report(base_dir=tmp_path, campaign_path=campaign)

    assert result["overview"]["campaign"] == "smoke"
    assert result["overview"]["archived_state_count"] == 2
    assert result["key_diagnostics_passed"]["no_fatal_errors"] is True
    assert result["key_diagnostics_passed"]["basal_stability"] == "passed"
    report = (tmp_path / "generated" / "workflow_validation_report.md").read_text()
    assert "## Campaign overview" in report
    assert "## Completed archived states table" in report
    assert "Mt_Na_LC050_N20" in report
    summary = json.loads((tmp_path / "generated" / "workflow_validation_summary.json").read_text())
    assert summary["overview"]["archived_state_count"] == 2


def test_workflow_report_missing_states_handled_gracefully(tmp_path: Path) -> None:
    campaign = write_campaign(tmp_path)

    result = generate_workflow_report(base_dir=tmp_path, campaign_path=campaign)

    assert result["overview"]["archived_state_count"] == 0
    assert result["key_diagnostics_passed"]["ion_count_stability"] == "unknown"
    report = (tmp_path / "generated" / "workflow_validation_report.md").read_text()
    assert "Archived RH states included: 0" in report


def test_workflow_report_excludes_legacy_states_unless_requested(tmp_path: Path) -> None:
    campaign = write_campaign(tmp_path)
    write_summary(tmp_path, "Mt_Na_LC050_N20", "rh_0p90", sample_summary(0.9, 4100000, 462, 298, 164, 20.0522))
    write_summary(tmp_path, "Mt_Oct050_Na", "rh_0p90", sample_summary(0.9, 1000000, 100, 80, 20, 15.0))

    result = generate_workflow_report(base_dir=tmp_path, campaign_path=campaign)

    assert [row["system_id"] for row in result["archived_states"]] == ["Mt_Na_LC050_N20"]

    all_result = generate_workflow_report(base_dir=tmp_path, campaign_path=campaign, all_states=True)

    assert "Mt_Oct050_Na" in {row["system_id"] for row in all_result["archived_states"]}


def test_workflow_report_recovery_case_section_present(tmp_path: Path) -> None:
    campaign = write_campaign(tmp_path)

    generate_workflow_report(base_dir=tmp_path, campaign_path=campaign)

    report = (tmp_path / "generated" / "workflow_validation_report.md").read_text()
    assert "## Recovery / correction case studies" in report
    assert "pre-GCMC basal drift fixed by holding clay z during soft-start" in report
    assert "analyzer mismatch between run_campaign and run_cycle" in report
    assert "partial RH generalization" in report
    assert "unsupported exchangeable Mg replaced by Ba smoke target" in report
    assert "no explicit ClayFF exchangeable Mg parameters" in report

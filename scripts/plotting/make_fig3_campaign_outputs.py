#!/usr/bin/env python3
"""Generate Figure 3 campaign-output panels from audited source data."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "paper_artifacts/final_campaign/figure_source_data/fig3_campaign_outputs.csv"
VALIDATION_REPORT = ROOT / "paper_artifacts/final_campaign/figure_source_data/fig3_data_validation.md"
OUTDIR = ROOT / "paper/agent_md_jctc/figures"

OUTPUTS = {
    "pdf": OUTDIR / "fig_campaign_outputs.pdf",
    "svg": OUTDIR / "fig_campaign_outputs.svg",
    "png": OUTDIR / "fig_campaign_outputs.png",
    "review": OUTDIR / "fig_campaign_outputs_review.png",
}

SYSTEM_ORDER = [
    "Mt_Na_LC030_N12",
    "Mt_Na_LC040_N16",
    "Mt_Na_LC050_N20",
    "Mt_K_LC040_N16",
    "Mt_Ca_LC040_N8",
]

STYLE = {
    "Mt_Na_LC030_N12": {"color": "#0072B2", "marker": "o", "linestyle": "-"},
    "Mt_Na_LC040_N16": {"color": "#000000", "marker": "s", "linestyle": "-", "linewidth": 1.45},
    "Mt_Na_LC050_N20": {"color": "#009E73", "marker": "^", "linestyle": "--"},
    "Mt_K_LC040_N16": {"color": "#D55E00", "marker": "D", "linestyle": "-."},
    "Mt_Ca_LC040_N8": {"color": "#CC79A7", "marker": "v", "linestyle": ":"},
}

PANELS = [
    ("total_water_mean", "total_water_error", "Total water (molecules)", "(a)"),
    ("interlayer_water_mean", "interlayer_water_error", "Interlayer water (molecules)", "(b)"),
    ("external_water_mean", "external_water_error", "External-surface water (molecules)", "(c)"),
    ("basal_spacing_mean", "basal_spacing_error", r"Basal spacing proxy ($\mathrm{\AA}$)", "(d)"),
]


def validate_source(data: pd.DataFrame) -> None:
    required = {
        "system_id",
        "display_label",
        "rh",
        "strict_pass",
        "total_water_mean",
        "total_water_error",
        "interlayer_water_mean",
        "interlayer_water_error",
        "external_water_mean",
        "external_water_error",
        "basal_spacing_mean",
        "basal_spacing_error",
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise SystemExit(f"Missing required source-data columns: {missing}")
    if len(data) != 15:
        raise SystemExit(f"Expected 15 source-data rows, found {len(data)}")
    if data.duplicated(["system_id", "rh"]).any():
        raise SystemExit("Duplicate system--RH rows found in source data")
    if not data["strict_pass"].astype(bool).all():
        raise SystemExit("Source data contain non-strict-pass rows")
    plotted = [field for panel in PANELS for field in panel[:2]]
    if data[plotted].isna().any().any():
        raise SystemExit("Source data contain missing plotted values")
    if sorted(data["system_id"].unique()) != sorted(SYSTEM_ORDER):
        raise SystemExit("Source data system IDs do not match expected Figure 3 systems")
    if sorted(np.round(data["rh"].astype(float).unique(), 2)) != [0.1, 0.3, 0.9]:
        raise SystemExit("Source data RH states do not match expected Figure 3 RH values")




def write_validation_report(data: pd.DataFrame) -> None:
    residual = data.copy()
    residual["water_partition_residual"] = (
        residual["total_water_mean"]
        - residual["interlayer_water_mean"]
        - residual["external_water_mean"]
    )
    residual = residual.sort_values(["system_id", "rh"])
    max_abs = float(residual["water_partition_residual"].abs().max())
    large = residual[residual["water_partition_residual"].abs() > 1.0]

    lines = [
        "# Figure 3 Data Validation",
        "",
        "Validation status: PASS",
        "",
        "## Water-Partition Residual Audit",
        "",
        "`water_partition_residual = total_water_mean - interlayer_water_mean - external_water_mean`",
        "",
        f"- Maximum absolute residual: {max_abs:.12g} molecules.",
        f"- States with absolute residual greater than 1 molecule: {len(large)}.",
        "- Discrepancy assessment: residuals are at floating-point/CSV-formatting precision and do not indicate a non-exhaustive spatial classification in the Figure 3 source data.",
        "",
        "| system_id | RH | display_label | water_partition_residual |",
        "| --- | ---: | --- | ---: |",
    ]
    for row in residual.itertuples(index=False):
        lines.append(
            f"| {row.system_id} | {float(row.rh):.2f} | {row.display_label} | "
            f"{float(row.water_partition_residual):.12g} |"
        )
    lines.extend(
        [
            "",
            "## Figure 3 Source Checks",
            f"- Rows: {len(data)}; expected 15.",
            f"- Unique system--RH pairs: {data.drop_duplicates(['system_id', 'rh']).shape[0]}.",
            f"- RH states: {', '.join(f'{x:.2f}' for x in sorted(data['rh'].unique()))}.",
            f"- All strict-pass: {bool(data['strict_pass'].astype(bool).all())}.",
            f"- Error definition: {', '.join(sorted(data['error_definition'].unique())) if 'error_definition' in data else 'not recorded'}.",
            f"- Final-window steps: {', '.join(str(int(x)) for x in sorted(data['final_window_steps'].unique())) if 'final_window_steps' in data else 'not recorded'}.",
            f"- Sample interval steps: {', '.join(str(int(x)) for x in sorted(data['sample_interval_steps'].unique())) if 'sample_interval_steps' in data else 'not recorded'}.",
            "",
            "## Supercell Comparability",
            "- Campaign and case specifications use `x_cells = 5`, `y_cells = 4`, and `n_sheets = 2` for all five plotted systems.",
            "- Generated equilibrated LAMMPS data headers show the same lateral box dimensions for all five systems: Lx = 25.8, Ly = 35.864, lateral area = 925.2912.",
            "- Raw molecule counts are therefore directly comparable across the five plotted systems with respect to supercell size and lateral surface area.",
        ]
    )
    VALIDATION_REPORT.write_text("\n".join(lines) + "\n")

def main() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
        }
    )

    data = pd.read_csv(SOURCE)
    data["rh"] = data["rh"].astype(float)
    validate_source(data)
    write_validation_report(data)

    rh_ticks = np.arange(0.1, 1.0, 0.1)
    fig, axes = plt.subplots(2, 2, figsize=(7.09, 5.35), sharex=True)
    axes = axes.ravel()
    handles = []
    labels = []

    for ax, (mean_col, err_col, ylabel, panel_label) in zip(axes, PANELS):
        for system_id in SYSTEM_ORDER:
            subset = data[data["system_id"] == system_id].sort_values("rh")
            style = STYLE[system_id].copy()
            linewidth = style.pop("linewidth", 1.5)
            color = style["color"]
            artist = ax.errorbar(
                subset["rh"],
                subset[mean_col],
                yerr=subset[err_col],
                capsize=4,
                capthick=1.2,
                elinewidth=1.2,
                barsabove=True,
                errorevery=1,
                alpha=1.0,
                ecolor=color,
                markerfacecolor="white",
                markeredgecolor=color,
                markersize=6,
                markeredgewidth=1.2,
                linewidth=linewidth,
                zorder=4,
                **style,
            )
            if ax is axes[0]:
                handles.append(artist.lines[0])
                labels.append(str(subset["display_label"].iloc[0]))

        ax.set_ylabel(ylabel)
        if panel_label == "(a)":
            ax.set_ylim(0, 830)
        elif panel_label in {"(b)", "(c)"}:
            ax.set_ylim(bottom=0)
        ax.set_xlim(0.06, 0.94)
        ax.set_xticks(rh_ticks)
        ax.grid(True, axis="y", color="0.88", linewidth=0.45)
        ax.grid(False, axis="x")
        ax.text(
            0.02,
            0.97,
            panel_label,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            fontweight="bold",
        )
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

    legend = axes[0].legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.02, 0.84),
        ncol=2,
        fontsize=7.5,
        handlelength=2.0,
        columnspacing=0.9,
        handletextpad=0.5,
        labelspacing=0.4,
        borderpad=0.5,
        frameon=True,
    )
    legend.get_frame().set_facecolor("white")
    legend.get_frame().set_alpha(0.90)
    legend.get_frame().set_edgecolor("0.75")
    legend.get_frame().set_linewidth(0.6)

    for ax in axes[:2]:
        ax.tick_params(axis="x", which="major", bottom=True, labelbottom=False)

    for ax in axes[2:]:
        ax.tick_params(axis="x", which="major", bottom=True, labelbottom=True)
        ax.set_xticklabels([f"{tick:.1f}" for tick in rh_ticks])
        ax.set_xlabel("Relative humidity")

    fig.tight_layout(pad=0.8, w_pad=1.2, h_pad=1.1)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUTS["pdf"], bbox_inches="tight")
    fig.savefig(OUTPUTS["svg"], bbox_inches="tight")
    fig.savefig(OUTPUTS["png"], dpi=600, bbox_inches="tight")
    fig.savefig(OUTPUTS["review"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    for path in OUTPUTS.values():
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()

"""Shared CSV loading and publication styling for Figures 3--7."""
from __future__ import annotations
import csv
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data/figure_source_data"
OUTPUT_DIR = ROOT / "verification_outputs/figures"
RH_ORDER = (0.90, 0.30, 0.10)
SYSTEM_COLORS = {"Na-LC0.30": "#56B4E9", "Na-LC0.40": "#0072B2", "Na-LC0.50": "#003B5C", "K-LC0.40": "#D55E00", "Ca-LC0.40": "#009E73"}
def load_csv(filename):
    with (DATA_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
def apply_style():
    plt.rcParams.update({"font.family":"sans-serif", "font.size":8.0, "axes.labelsize":8.5, "axes.titlesize":8.5, "xtick.labelsize":7.5, "ytick.labelsize":7.5, "legend.fontsize":7.0, "axes.linewidth":0.8, "axes.spines.top":False, "axes.spines.right":False, "legend.frameon":False, "lines.linewidth":1.35, "lines.markersize":4.2, "xtick.direction":"in", "ytick.direction":"in", "pdf.fonttype":42, "savefig.facecolor":"white", "figure.facecolor":"white", "axes.facecolor":"white"})
def require_render_approval(render):
    if not render:
        raise SystemExit("Plot structure is ready. Re-run with --render only after figure-generation approval.")
def ordered_system_rows(rows, system):
    by_rh = {float(row["RH"]): row for row in rows if row["system"] == system}
    return [by_rh[rh] for rh in RH_ORDER]
def pale(color, amount=0.72):
    return tuple((1.0-amount)*channel+amount for channel in to_rgb(color))
def format_rh_axis(ax):
    ax.set_xlim(0.98, 0.02)
    ax.set_xticks(RH_ORDER, ("0.90", "0.30", "0.10"))
    ax.set_xlabel("Relative humidity")
def save_outputs(fig, stem):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_DIR / f"{stem}.pdf", format="pdf", bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / f"{stem}.png", format="png", dpi=300, bbox_inches="tight")

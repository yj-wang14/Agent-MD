#!/usr/bin/env python3
"""Figure 5: basal-spacing response along the desorption path."""
import argparse
import matplotlib.pyplot as plt
from figure_plot_common import SYSTEM_COLORS, apply_style, format_rh_axis, load_csv, ordered_system_rows, require_render_approval, save_outputs
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--render",action="store_true"); args=parser.parse_args(); require_render_approval(args.render)
    rows=load_csv("fig5_basal_spacing.csv"); apply_style(); fig,ax=plt.subplots(figsize=(3.45,2.65),constrained_layout=True)
    for system in SYSTEM_COLORS:
        selected=ordered_system_rows(rows,system); ax.plot([float(r["RH"]) for r in selected],[float(r["basal_spacing"]) for r in selected],marker="o",color=SYSTEM_COLORS[system],label=system)
    format_rh_axis(ax); ax.set_ylabel("Basal spacing proxy (Å)"); ax.set_ylim(11.2,20.8); ax.legend(ncol=2,loc="upper right",columnspacing=0.9,handlelength=1.7); save_outputs(fig,"fig5")
if __name__ == "__main__": main()

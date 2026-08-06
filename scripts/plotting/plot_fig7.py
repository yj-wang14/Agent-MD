#!/usr/bin/env python3
"""Figure 7: layer-charge-dependent hydration and RH-local effort."""
import argparse
import matplotlib.pyplot as plt
from figure_plot_common import SYSTEM_COLORS, apply_style, format_rh_axis, load_csv, ordered_system_rows, require_render_approval, save_outputs
SYSTEMS=('Na-LC0.30', 'Na-LC0.40', 'Na-LC0.50')
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--render",action="store_true"); args=parser.parse_args(); require_render_approval(args.render)
    rows=load_csv("fig7_layer_charge_sampling.csv"); apply_style(); fig,axes=plt.subplots(1,2,figsize=(7.0,2.65),constrained_layout=True); width=0.055
    for index,system in enumerate(SYSTEMS):
        selected=ordered_system_rows(rows,system); rh=[float(r["RH"]) for r in selected]
        axes[0].plot(rh,[float(r["total_water"]) for r in selected],marker="o",color=SYSTEM_COLORS[system],label=system)
        axes[1].bar([value+(1-index)*width for value in rh],[int(r["rh_local_steps"])/1e6 for r in selected],width=width*0.86,color=SYSTEM_COLORS[system],label=system)
    axes[0].set_ylabel("Total water molecules"); axes[1].set_ylabel("RH-local MD steps (×10⁶)")
    for ax in axes: format_rh_axis(ax); ax.set_ylim(bottom=0)
    axes[0].set_title("(a)",loc="left",fontweight="bold",pad=3); axes[1].set_title("(b)",loc="left",fontweight="bold",pad=3); axes[0].legend(loc="upper right"); save_outputs(fig,"fig7")
if __name__ == "__main__": main()

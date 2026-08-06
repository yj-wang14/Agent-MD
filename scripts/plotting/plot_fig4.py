#!/usr/bin/env python3
"""Figure 4: interlayer/external water partition fractions."""
import argparse
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from figure_plot_common import SYSTEM_COLORS, apply_style, load_csv, ordered_system_rows, pale, require_render_approval, save_outputs
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--render",action="store_true"); args=parser.parse_args(); require_render_approval(args.render)
    rows=load_csv("fig4_water_partition.csv"); apply_style(); systems=tuple(SYSTEM_COLORS); fig,ax=plt.subplots(figsize=(7.0,2.85),constrained_layout=True); width=0.22; ticks=[]; labels=[]
    for group,system in enumerate(systems):
        for offset,row in enumerate(ordered_system_rows(rows,system)):
            x=group+(offset-1)*width; inter=100*float(row["interlayer_fraction"]); ext=100*float(row["external_fraction"]); color=SYSTEM_COLORS[system]
            ax.bar(x,inter,width=width*0.88,color=color,edgecolor="white",linewidth=0.4); ax.bar(x,ext,bottom=inter,width=width*0.88,color=pale(color),edgecolor="white",linewidth=0.4); ticks.append(x); labels.append(row["RH"])
    ax.set_xticks(ticks,labels,rotation=90); ax.set_xlabel("Relative humidity within each system (0.90 → 0.30 → 0.10)"); ax.set_ylabel("Fraction of total water (%)"); ax.set_ylim(0,100)
    for group,system in enumerate(systems): ax.text(group,-0.23,system,color=SYSTEM_COLORS[system],ha="center",va="top",transform=ax.get_xaxis_transform(),fontsize=7.5,fontweight="bold")
    ax.legend(handles=(Patch(facecolor="#555555",label="Interlayer"),Patch(facecolor="#CCCCCC",label="External surface")),ncol=2,loc="upper center",bbox_to_anchor=(0.5,1.02)); save_outputs(fig,"fig4")
if __name__ == "__main__": main()

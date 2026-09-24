#!/usr/bin/env python3
"""Original Figure 3: a clean, non-overlapping dimensionality reduction schematic."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle, Polygon

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
OUT_SVG = DOCS_DIR / "assets" / "figure3-original.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure3-original.pdf"

BLUE = "#2147c6"
GREEN = "#0c8140"
PURPLE = "#9695c9"
RULE = "#d3d8ea"

plt.rcParams.update({"font.family":"sans-serif",
                   "font.sans-serif":["Source Sans Pro","Helvetica Neue","Arial","sans-serif"]})


def arrow(ax, p, q, color=BLUE, lw=2.0, ms=24):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=ms, linewidth=lw, color=color, zorder=20))


def main():
    fig, ax = plt.subplots(figsize=(14,10), dpi=100)
    ax.set_xlim(0,100); ax.set_ylim(0,71.428); ax.axis('off')

    # Outer frame
    ax.add_patch(FancyBboxPatch((2,2), 96, 67.428, boxstyle="round,pad=0,rounding_size=0.8", edgecolor=RULE, facecolor='none', lw=1.2, zorder=1))

    # Four panels across: Stage 1-4
    w = 28
    gap = 4
    y = 9
    x1 = 6
    x2 = x1 + w + gap
    x3 = x2 + w + gap
    x4 = x3 + w + gap

    # Panel 1: raw data box (red), minimal abstract icons
    ax.add_patch(Rectangle((x1, y), w, 44, color=RED if False else '#ed2024', alpha=0.07))
    ax.add_patch(FancyBboxPatch((x1,y), w, 44, boxstyle="round,pad=0,rounding_size=0.4", edgecolor=BLUE, facecolor='none', lw=2.0))
    ax.text(x1+w/2, y+41, 'Stage 1: Raw', ha='center', va='center', color=PURPLE, fontsize=13, fontweight='bold')
    # small icon block
    ax.add_patch(Circle((x1+6, y+30), 2, facecolor=BLUE, edgecolor='none'))
    ax.add_patch(Circle((x1+10, y+30), 2, facecolor=BLUE, edgecolor='none'))

    # Panel 2: preprocessed
    ax.add_patch(FancyBboxPatch((x2,y), w, 44, boxstyle="round,pad=0,rounding_size=0.4", edgecolor=GREEN, facecolor='none', lw=2.0))
    ax.text(x2+w/2, y+41, 'Stage 2: Processed', ha='center', va='center', color=GREEN, fontsize=13, fontweight='bold')
    # processing arrows
    ax.add_patch(Polygon([[x2+2, y+6],[x2+6, y+6],[x2+4, y+14]], closed=True, facecolor=GREEN, edgecolor=GREEN, lw=0.8, alpha=0.8))

    # Panel 3: reduced space
    ax.add_patch(FancyBboxPatch((x3,y), w, 44, boxstyle="round,pad=0,rounding_size=0.4", edgecolor=PURPLE, facecolor='none', lw=2.0))
    ax.text(x3+w/2, y+41, 'Stage 3: Reduced', ha='center', va='center', color=PURPLE, fontsize=13, fontweight='bold')

    # Panel 4: analyzed space
    ax.add_patch(Rectangle((x4,y), w, 44, color=PURPLE, alpha=0.07))

    # connectors
    arrow(ax,(x1+w+0.5, y+22),(x2-0.5, y+22))
    arrow(ax,(x2+w+0.5, y+22),(x3-0.5, y+22))
    arrow(ax,(x3+w+0.5, y+22),(x4-0.5, y+22))

    fig.savefig(OUT_SVG, format='svg', bbox_inches='tight', pad_inches=0)
    fig.savefig(OUT_PDF, format='pdf', bbox_inches='tight', pad_inches=0)
    plt.close(fig)

if __name__ == '__main__':
    main()

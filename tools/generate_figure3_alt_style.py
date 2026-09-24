#!/usr/bin/env python3
"""Alternate Figure 3: a separate, non-overlapping dimensionality schematic with a different layout style."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
OUT_SVG = DOCS_DIR / "assets" / "figure3-alt-style.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure3-alt-style.pdf"

RED = "#ed2024"
GREEN = "#0c8140"
PURPLE = "#9695c9"
BLACK = "#1b2638"
RULE = "#d3d8ea"

plt.rcParams.update({"font.family":"sans-serif",
                   "font.sans-serif":["Source Sans Pro","Helvetica Neue","Arial","sans-serif"]})


def draw_block(ax, pos, color, label):
    x, y = pos
    w, h = 28, 44
    ax.add_patch(FancyBboxPatch((x,y), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor=color, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x,y), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor='none', edgecolor=color, lw=2.0, zorder=2))
    ax.text(x+w/2, y+h-4, label, ha='center', va='center', fontsize=12, color=color, fontweight='bold')


def main():
    fig, ax = plt.subplots(figsize=(14,10), dpi=120)
    ax.set_xlim(0,100); ax.set_ylim(0,71.428); ax.axis('off')

    # Four blocks in a row: Input, Transform, Reduce, Output
    positions = [(6, 9), (6+28+6, 9), (6+28+6+28+6, 9), (6+28+6+28+6+28+6, 9)]
    draw_block(ax, positions[0], RED, 'Input Signals')
    draw_block(ax, positions[1], GREEN, 'Projection & Alignment')
    draw_block(ax, positions[2], PURPLE, 'Dimensionality Reduction')
    draw_block(ax, positions[3], RED, 'Decision Output')

    # Arrows
    for i in range(3):
        x_from = positions[i][0] + 28
        y_from = positions[i][1] + 22
        x_to = positions[i+1][0]
        y_to = positions[i+1][1] + 22
        ax.add_patch(FancyArrowPatch((x_from, y_from), (x_to-2, y_to), arrowstyle='-|>', mutation_scale=24, lw=2.0, color=BLACK, zorder=20))

    fig.savefig(OUT_SVG, format='svg', bbox_inches='tight', pad_inches=0)
    fig.savefig(OUT_PDF, format='pdf', bbox_inches='tight', pad_inches=0)
    plt.close(fig)

if __name__=='__main__':
    main()

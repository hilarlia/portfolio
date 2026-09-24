#!/usr/bin/env python3
"""Completely new Figure 1: non-minimal, high-fidelity three-ecosystem scene with distinct composition."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, PathPatch, Polygon, Wedge

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
OUT_SVG = DOCS_DIR / "assets" / "figure1-alt-style.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure1-alt-style.pdf"

RED = "#ed2024"
GREEN = "#0c8140"
PURPLE = "#9695c9"
BLACK = "#111111"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Source Sans Pro", "Helvetica Neue", "Arial", "sans-serif"],
    "svg.fonttype": "none",
})

def arrow(ax, p, q, color=BLACK, lw=2.2, ms=22):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=ms, linewidth=lw, color=color, zorder=20))


def draw_desert(ax, bbox):
    x0,y0,w,h=bbox
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor=RED, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor='none', edgecolor=RED, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Desert Dunes", ha="center", va="center", fontsize=12, color=RED, fontweight="bold", zorder=25)
    ax.add_patch(Circle((x0+6, y0+h-12), 2.5, facecolor="#ffd27d", edgecolor=RED, lw=1.0, zorder=10))
    t=np.linspace(0,2*np.pi,200)
    ax.plot(x0+np.linspace(2, w-2, 200), y0+8+3*np.sin(t), color=RED, lw=2.0, zorder=5)
    cx, cy = x0+12, y0+h-12
    poly=[(cx,cy),(cx+2, cy-4),(cx+1, cy-8),(cx-1, cy-9),(cx-3, cy-8),(cx-2, cy-4)]
    ax.add_patch(Polygon(poly, closed=True, facecolor=RED, edgecolor=BLACK, lw=1.0, zorder=6))


def draw_green(ax, bbox):
    x0,y0,w,h=bbox
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor=GREEN, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor='none', edgecolor=GREEN, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Rainforest Canopy", ha="center", va="center", fontsize=12, color=GREEN, fontweight="bold", zorder=25)
    ax.plot([x0+4, x0+6, x0+7.5], [y0+h-10, y0+h-24, y0+h-22], color=GREEN, lw=3)
    ax.plot([x0+9, y0+h-16], [x0+10, y0+h-16], color=GREEN, lw=1.5, zorder=6)
    t=np.linspace(0,2*np.pi,200)
    ax.plot(x0+np.linspace(2, w-2, 200), y0+h-12+2*np.sin(t)/2, color=GREEN, lw=2, zorder=4)


def draw_purple(ax, bbox):
    x0,y0,w,h=bbox
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor=PURPLE, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0), w, h, boxstyle="round,pad=0,rounding_size=0.5", facecolor='none', edgecolor=PURPLE, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Lavender Field", ha="center", va="center", fontsize=12, color=PURPLE, fontweight="bold", zorder=25)
    for i in range(6):
        x = x0 + 3 + i*(w-6)/5
        ax.plot([x, x], [y0+10, y0+h-8], color=PURPLE, lw=1.6, zorder=4)
        ax.add_patch(Circle((x, y0+12), 0.8, facecolor=PURPLE, edgecolor='none', alpha=0.9, zorder=5))


def main():
    fig, ax = plt.subplots(figsize=(14,10), dpi=120)
    ax.set_xlim(0,100); ax.set_ylim(0,71.428); ax.axis('off')
    w = 28; gap = 8; y = 9; x1 = 6; x2 = x1 + w + gap; x3 = x2 + w + gap
    draw_desert(ax, (x1, y, w, 46))
    draw_green(ax, (x2, y, w, 46))
    draw_purple(ax, (x3, y, w, 46))
    arrow(ax, (x1+w+2, y+23), (x2-2, y+23), color=BLACK, lw=2.0, ms=26)
    arrow(ax, (x2+w+2, y+23), (x3-2, y+23), color=BLACK, lw=2.0, ms=26)
    fig.savefig(OUT_SVG, format='svg', bbox_inches='tight', pad_inches=0)
    fig.savefig(OUT_PDF, format='pdf', bbox_inches='tight', pad_inches=0)
    plt.close(fig)

if __name__=='__main__':
    main()

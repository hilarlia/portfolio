#!/usr/bin/env python3
"""Original, non-minimal Figure 1: three rich panels with distinct ecosystems."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
OUT_SVG = DOCS_DIR / "assets" / "figure1-original.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure1-original.pdf"

# Colors per requirement
RED = "#ed2024"
GREEN = "#0c8140"
PURPLE = "#9695c9"
BLACK = "#1b2638"
RULE = "#d3d8ea"

plt.rcParams.update({"font.family":"sans-serif",
                   "font.sans-serif":["Source Sans Pro","Helvetica Neue","Arial","sans-serif"]})

def arrow(ax, p, q, color=BLACK, lw=2.0, ms=24):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=ms, linewidth=lw, color=color, zorder=20))


def draw_red_panel(ax, bbox):
    x0,y0,w,h = bbox
    # border + interior
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor=RED, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor='none', edgecolor=RED, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Desert & Dunes", ha="center", va="center", color=RED, fontsize=12, fontweight="bold", zorder=25)
    # desert features
    # sun disc
    ax.add_patch(Circle((x0+5, y0+h-9), 3.5, facecolor="#FFD27D", edgecolor=RED, lw=1.2, zorder=6))
    # dunes as waves
    t = np.linspace(0, 2*np.pi, 200)
    y = y0 + 1.5 + 0.75*np.sin(t)
    ax.plot( x0 + np.linspace(0.6,w-0.6,200), y, color=RED, lw=2.0, zorder=3)
    # cactus simple silhouette
    cx, cy = x0 + 9, y0 + h - 12
    pts = [(cx, cy),(cx+0.5, cy-3),(cx+0.3, cy-6),(cx-0.3, cy-8),(cx-0.9, cy-8),(cx-0.6, cy-3)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=RED, edgecolor=BLACK, lw=1.0, zorder=5))

def draw_green_panel(ax, bbox):
    x0,y0,w,h=bbox
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6", facecolor=GREEN, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6", facecolor='none', edgecolor=GREEN, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Rainforest Canopy", ha="center", va="center", color=GREEN, fontsize=12, fontweight="bold", zorder=25)
    # vines and leaves
    ax.plot([x0+2, x0+2.5, x0+3.2], [y0+h-10, y0+h-22, y0+h-24], color=GREEN, lw=3)
    # canopy hills
    t = np.linspace(0, 2*np.pi, 200)
    ax.plot(x0+np.linspace(0.5, w-0.5, 200), y0+ h - 12 + 2*np.sin(t)/2, color=GREEN, lw=2)
    # leaf silhouette
    ax.add_patch(Polygon([[x0+8,y0+h-14],[x0+9,y0+h-18],[x0+10,y0+h-14]], closed=True, facecolor="#0a572a", edgecolor=GREEN, lw=1.2, zorder=6))

def draw_purple_panel(ax, bbox):
    x0,y0,w,h=bbox
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6", facecolor=PURPLE, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0,y0),w,h, boxstyle="round,pad=0,rounding_size=0.6", facecolor='none', edgecolor=PURPLE, lw=2.0, zorder=2))
    ax.text(x0+w/2, y0+h-3.0, "Lavender Fields", ha="center", va="center", color=PURPLE, fontsize=12, fontweight="bold", zorder=25)
    # lavender rows
    for i in range(6):
        y = y0 + 10 + i*6
        ax.plot([x0+3, x0+w-3], [y, y], color=PURPLE, lw=1.2)
        ax.add_patch(Polygon([[x0+5, y-1],[x0+6, y+1],[x0+4, y+1]], closed=True, facecolor=PURPLE, edgecolor=BLACK, lw=0.5, zorder=6))

    # small decorative hill
    ax.plot([x0+1, x0+w-1], [y0+6, y0+6], color="#7a7a98", lw=2, zorder=4)

def main():
    # 7:5 aspect ratio
    fig, ax = plt.subplots(figsize=(14,10), dpi=100)
    ax.set_xlim(0,100); ax.set_ylim(0,71.428); ax.axis('off')

    # panels
    w_panel = 28.0
    gap = 4.0
    y_panel = 9.0
    x1 = 6.0
    x2 = x1 + w_panel + gap
    x3 = x2 + w_panel + gap

    draw_red_panel(ax, (x1, y_panel, w_panel, 50))
    draw_green_panel(ax, (x2, y_panel, w_panel, 50))
    draw_purple_panel(ax, (x3, y_panel, w_panel, 50))

    # connectors
    yline = y_panel + 25
    arrow(ax,(x1+w_panel+1, yline-2),(x2-1, yline-2), lw=2.0, ms=18)
    arrow(ax,(x2+w_panel+1, yline-2),(x3-1, yline-2), lw=2.0, ms=18)

    # caption line
    ax.plot([6, 86], [7,7], color=RULE, lw=1.2)
    ax.text(50, 4, "Adaptive state transformation under varying environmental task conditions.", ha="center", va="center", color=BLACK, fontsize=15)

    fig.savefig(OUT_SVG, format="svg", bbox_inches="tight", pad_inches=0)
    fig.savefig(OUT_PDF, format="pdf", bbox_inches="tight", pad_inches=0)
    plt.close(fig)

if __name__ == '__main__':
    main()

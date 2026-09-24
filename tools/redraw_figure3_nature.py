#!/usr/bin/env python3
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "figure3-effective-dimension.svg"

BLUE = "#2147c6"
INK = "#1b2638"
MUTED = "#5f6777"
ORANGE = "#d4881f"
GREEN = "#3a8652"
LAV = "#5b6ec0"
CREAM = "#ffe7bd"
RULE = "#d3d8ea"
LIGHT = "#c6d0ee"

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 13,
    "mathtext.fontset": "cm",
})


def arrow(ax, p, q, color=INK, lw=1.8, ms=24, style='-|>'):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, linewidth=lw, color=color))


def main():
    fig, ax = plt.subplots(figsize=(14.4, 7.4), dpi=100)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.axis("off")

    # outer frame
    ax.add_patch(FancyBboxPatch((1.5, 1.5), 97, 57, boxstyle="round,pad=0.3,rounding_size=1.0",
                                linewidth=1.2, edgecolor=RULE, facecolor="none"))

    # ---------- Step 1: full representation ----------
    ax.text(12.0, 54.2, r"$1$  full state", color=INK, fontsize=17, fontweight="bold", ha="center")
    ax.add_patch(FancyBboxPatch((4.8, 17.0), 30.2, 33.0, boxstyle="round,pad=0.5,rounding_size=0.2",
                                linewidth=1.6, edgecolor=INK, facecolor="#f4f7ff"))

    x = np.linspace(7.2, 33.4, 250)
    base = np.linspace(19.4, 47.4, 12)
    keep_idx = [2, 6, 9]
    keep_col = [LAV, ORANGE, BLUE]

    for i, y0 in enumerate(base):
        wig = 0.35 * np.sin(0.22 * x + i * 0.7)
        col, lw = (LIGHT, 1.15)
        if i in keep_idx:
            col = keep_col[keep_idx.index(i)]
            lw = 2.9
        ax.plot(x, y0 + wig, color=col, lw=lw, solid_capstyle='round')

    ax.text(20.0, 12.1, r"$\Xi_s\in\mathcal{D}(\mathcal{H})$, with $d^2-1$ coordinates", ha="center", color=MUTED, fontsize=17)

    # ---------- Step 2: reward relevance filter ----------
    arrow(ax, (35.3, 33.5), (39.6, 33.5), color=INK, lw=1.8, ms=24)
    ax.text(48.8, 54.2, r"$2$  reward filter", color=INK, fontsize=17, fontweight="bold", ha="center")

    filt = np.array([[40.0, 19.0], [54.5, 19.0], [58.0, 33.5], [54.5, 48.0], [40.0, 48.0]])
    ax.add_patch(Polygon(filt, closed=True, facecolor="#fff3dc", edgecolor=INK, linewidth=1.6))
    ax.text(48.8, 36.2, r"retain only", ha="center", fontsize=17, color=INK)
    ax.text(48.8, 32.8, r"coordinates that", ha="center", fontsize=17, color=INK)
    ax.text(48.8, 29.4, r"affect future", ha="center", fontsize=17, color=INK)
    ax.text(48.8, 26.0, r"reward", ha="center", fontsize=17, color=INK)

    # discarded lines terminate at filter wall
    wall_x = 40.0
    for i, y0 in enumerate(base):
        if i in keep_idx:
            continue
        yi = y0 + 0.35 * np.sin(0.22 * wall_x + i * 0.7)
        ax.plot([35.0, wall_x], [yi, yi], color=RULE, lw=1.2)
        ax.add_patch(Circle((wall_x + 0.8, yi), 0.35, facecolor=RULE, edgecolor='none'))

    # retained lines mapped through filter
    in_x0 = 33.4
    in_x1 = 40.0
    out_x0 = 58.0
    out_x1 = 68.0
    y_out = [41.0, 33.5, 26.0]
    for idx, col, yo in zip(keep_idx, keep_col, y_out):
        yi = base[idx] + 0.35 * np.sin(0.22 * in_x0 + idx * 0.7)
        ax.plot([in_x0, in_x1], [yi, yo], color=col, lw=3.0)
        ax.plot([out_x0, out_x1], [yo, yo], color=col, lw=3.0)

    # ---------- Step 3: reduced coordinates ----------
    arrow(ax, (58.2, 33.5), (62.0, 33.5), color=INK, lw=1.8, ms=24)
    ax.text(70.5, 54.2, r"$3$  reduced coords", color=INK, fontsize=15, fontweight="bold", ha="center")

    x2 = np.linspace(68.0, 80.8, 120)
    y_shift = [0.8, -0.6, 0.9]
    for yo, dy, col in zip(y_out, y_shift, keep_col):
        y2 = yo + dy * np.sin(0.35*(x2-68.0))
        ax.plot(x2, y2, color=col, lw=3.0)
        ax.add_patch(Circle((80.8, y2[-1]), 0.8, facecolor=col, edgecolor=INK, linewidth=1.0))

    ax.text(72.0, 19.6, r"$z_s\in\mathbb{R}^{r^2-1}$ with $r\ll d$", ha="center", color=MUTED, fontsize=16)

    # ---------- Step 4: action search ----------
    arrow(ax, (81.8, 33.5), (85.2, 33.5), color=INK, lw=1.8, ms=24)
    ax.text(90.8, 54.2, r"$4$  action set", color=INK, fontsize=15, fontweight="bold", ha="center")

    yA = [40.2, 33.5, 26.8]
    xA = 93.2
    for y0, col in zip(yA, keep_col):
        ax.plot([81.6, xA-2.1], [y0, y0], color=INK, lw=1.8)
        edge = ORANGE if col == ORANGE else INK
        lw = 2.3 if col == ORANGE else 1.6
        face = CREAM if col == ORANGE else "white"
        ax.add_patch(Circle((xA, y0), 2.0, facecolor=face, edgecolor=edge, linewidth=lw))
        ax.text(xA, y0, r"$A$", ha="center", va="center", color=edge, fontsize=19)

    ax.text(84.8, 16.8, r"near-optimal action", ha="center", color=ORANGE, fontsize=16)

    # ---------- Complexity statement ----------
    ax.plot([8.0, 92.5], [9.0, 9.0], color=RULE, lw=1.5)
    ax.text(50.0, 5.7,
            r"$\mathcal{O}\!\left((S^3A/\delta)^{d^2-1}\right)\ \longrightarrow\ \mathcal{O}\!\left((S^3A/\delta)^{r^2-1}\right)$",
            ha="center", color=MUTED, fontsize=18)

    fig.savefig(OUT, format="svg", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


if __name__ == "__main__":
    main()

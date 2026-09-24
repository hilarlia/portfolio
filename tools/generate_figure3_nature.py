#!/usr/bin/env python3
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon
import matplotlib.font_manager as fm
from fontTools.ttLib import TTFont

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
FONT_DIR = DOCS_DIR / "assets" / "fonts"
TMP_DIR = Path("/tmp")

for weight in ["regular", "bold", "italic"]:
    woff2_path = FONT_DIR / f"source-sans-pro-{weight}.woff2"
    ttf_path = TMP_DIR / f"source-sans-pro-{weight}.ttf"
    if woff2_path.exists():
        tt = TTFont(woff2_path)
        tt.flavor = None
        tt.save(ttf_path)
        fm.fontManager.addfont(str(ttf_path))

OUT_SVG = DOCS_DIR / "assets" / "figure3-effective-dimension.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure3-effective-dimension.pdf"

BLUE = "#2147c6"
INK = "#1b2638"
MUTED = "#555d6e"
ORANGE = "#d4881f"
LAV = "#5b6ec0"
CREAM = "#ffe7bd"
RULE = "#d3d8ea"
LIGHT = "#c6d0ee"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Source Sans Pro", "Helvetica Neue", "Arial", "sans-serif"],
    "svg.fonttype": "none",
    "mathtext.fontset": "cm",
})


def arrow(ax, p, q, color=INK, lw=1.8, ms=24):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=ms, linewidth=lw, color=color))


def main():
    # Aspect ratio exactly 7:5 (14 x 10 inches)
    fig, ax = plt.subplots(figsize=(14, 10), dpi=100)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 71.428)  # 100 * (5/7) = 71.428
    ax.axis("off")

    # Boundary box visible
    ax.add_patch(FancyBboxPatch((1.5, 1.5), 97, 68.428, boxstyle="round,pad=0,rounding_size=0.8",
                                linewidth=1.2, edgecolor=RULE, facecolor="none"))

    # Stage headers
    ax.text(19.0, 64.0, r"$1$  Full state coordinates", color=INK, fontsize=18, fontweight="bold", ha="center")
    ax.text(47.5, 64.0, r"$2$  Reward filter", color=INK, fontsize=18, fontweight="bold", ha="center")
    ax.text(70.5, 64.0, r"$3$  Effective coordinates", color=INK, fontsize=18, fontweight="bold", ha="center")
    ax.text(89.5, 64.0, r"$4$  Action search", color=INK, fontsize=18, fontweight="bold", ha="center")

    # ----- Step 1: Full State Space -----
    ax.add_patch(FancyBboxPatch((4.8, 20.0), 28.4, 38.0, boxstyle="round,pad=0,rounding_size=0.3",
                                linewidth=1.5, edgecolor=INK, facecolor="#f4f7ff"))

    x_full = np.linspace(7.0, 31.2, 200)
    y_base = np.linspace(23.0, 55.0, 12)
    keep_idx = [2, 6, 9]
    keep_cols = [LAV, ORANGE, BLUE]

    for i, y0 in enumerate(y_base):
        wig = 0.4 * np.sin(0.25 * x_full + i * 0.7)
        if i in keep_idx:
            c = keep_cols[keep_idx.index(i)]
            lw = 3.0
        else:
            c = LIGHT
            lw = 1.15
        ax.plot(x_full, y0 + wig, color=c, lw=lw, solid_capstyle='round')

    ax.text(19.0, 15.0, r"$d^2-1$ directions", ha="center", color=MUTED, fontsize=17)

    # ----- Step 2: Reward Relevance Filter -----
    arrow(ax, (33.8, 39.0), (38.2, 39.0), color=INK, lw=1.8, ms=24)

    filt_poly = np.array([[38.5, 22.0], [54.0, 22.0], [57.5, 39.0], [54.0, 56.0], [38.5, 56.0]])
    ax.add_patch(Polygon(filt_poly, closed=True, facecolor="#fff3dc", edgecolor=INK, linewidth=1.5))
    ax.text(47.0, 42.5, r"retain only", ha="center", fontsize=16, color=INK)
    ax.text(47.0, 38.8, r"directions that", ha="center", fontsize=16, color=INK)
    ax.text(47.0, 35.1, r"affect future", ha="center", fontsize=16, color=INK)
    ax.text(47.0, 31.4, r"reward", ha="center", fontsize=16, color=INK)

    # Discarded routes stop at filter boundary
    wall_x = 38.5
    for i, y0 in enumerate(y_base):
        if i in keep_idx:
            continue
        yi = y0 + 0.4 * np.sin(0.25 * wall_x + i * 0.7)
        ax.plot([33.8, wall_x], [yi, yi], color=RULE, lw=1.2)
        ax.add_patch(Circle((wall_x + 0.8, yi), 0.35, facecolor=RULE, edgecolor='none'))

    # Retained routing
    in_x0, in_x1 = 31.2, 38.5
    out_x0, out_x1 = 57.5, 64.0
    y_out = [47.5, 39.0, 30.5]

    for idx, col, yo in zip(keep_idx, keep_cols, y_out):
        yi = y_base[idx] + 0.4 * np.sin(0.25 * in_x0 + idx * 0.7)
        ax.plot([in_x0, in_x1], [yi, yo], color=col, lw=3.0)
        ax.plot([out_x0, out_x1], [yo, yo], color=col, lw=3.0)

    # ----- Step 3: Effective Coordinates -----
    arrow(ax, (57.8, 39.0), (62.2, 39.0), color=INK, lw=1.8, ms=24)

    x2 = np.linspace(64.0, 77.0, 100)
    y_shifts = [0.8, -0.6, 0.9]
    for yo, dy, col in zip(y_out, y_shifts, keep_cols):
        y2 = yo + dy * np.sin(0.35 * (x2 - 64.0))
        ax.plot(x2, y2, color=col, lw=3.0)
        ax.add_patch(Circle((77.0, y2[-1]), 0.8, facecolor=col, edgecolor=INK, linewidth=1.0))

    ax.text(70.5, 15.0, r"$r^2-1$ retained directions", ha="center", color=MUTED, fontsize=17)

    # ----- Step 4: Smaller Action Search -----
    arrow(ax, (78.2, 39.0), (82.5, 39.0), color=INK, lw=1.8, ms=24)

    y_actions = [46.8, 39.0, 31.2]
    xA = 91.5
    for y0, col in zip(y_actions, keep_cols):
        ax.plot([78.0, xA - 2.1], [y0, y0], color=INK, lw=1.6)
        edge = ORANGE if col == ORANGE else INK
        lw = 2.4 if col == ORANGE else 1.6
        face = CREAM if col == ORANGE else "white"
        ax.add_patch(Circle((xA, y0), 2.1, facecolor=face, edgecolor=edge, linewidth=lw))
        ax.text(xA, y0, r"$A$", ha="center", va="center", color=edge, fontsize=18)

    ax.text(89.0, 22.0, r"near-optimal action", ha="center", color=ORANGE, fontsize=17)

    # ----- Bottom Complexity Equation -----
    ax.plot([6.0, 94.0], [10.5, 10.5], color=RULE, lw=1.4)
    ax.text(50.0, 5.5,
            r"$\mathcal{O}\!\left((S^3A/\delta)^{d^2-1}\right)\ \longrightarrow\ \mathcal{O}\!\left((S^3A/\delta)^{r^2-1}\right)$",
            ha="center", va="center", color=MUTED, fontsize=19)

    fig.savefig(OUT_SVG, format="svg", bbox_inches="tight", pad_inches=0)
    fig.savefig(OUT_PDF, format="pdf", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


if __name__ == "__main__":
    main()

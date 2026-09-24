#!/usr/bin/env python3
"""Ultra-high-fidelity, non-minimal Figure 1 generation script."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon
import matplotlib.font_manager as fm
from fontTools.ttLib import TTFont

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
FONT_DIR = DOCS_DIR / "assets" / "fonts"
TMP_DIR = Path("/tmp")

# Register Source Sans Pro font files
for weight in ["regular", "bold", "italic"]:
    woff2_path = FONT_DIR / f"source-sans-pro-{weight}.woff2"
    ttf_path = TMP_DIR / f"source-sans-pro-{weight}.ttf"
    if woff2_path.exists():
        tt = TTFont(woff2_path)
        tt.flavor = None
        tt.save(ttf_path)
        fm.fontManager.addfont(str(ttf_path))

OUT_SVG = DOCS_DIR / "assets" / "figure1-chameleon.svg"
OUT_PDF = DOCS_DIR / "assets" / "figure1-chameleon.pdf"

RED = "#ed2024"
GREEN = "#0c8140"
PURPLE = "#9695c9"
INK = "#1b2638"
MUTED = "#525c6e"
RULE = "#d3d8ea"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Source Sans Pro", "Helvetica Neue", "Arial", "sans-serif"],
    "svg.fonttype": "none",
    "mathtext.fontset": "cm",
})


def arrow(ax, p, q, color=INK, lw=2.2, ms=24):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=ms, linewidth=lw, color=color, zorder=30))


def draw_realistic_chameleon(ax, center, scale, base_hex, dark_hex, light_hex):
    """Draws a highly detailed, textured biological illustration of a chameleon."""
    cx, cy = center

    # 1. Thick textured tree bough
    bx = np.linspace(cx - 3.8 * scale, cx + 3.8 * scale, 120)
    by = cy - 1.30 * scale + 0.20 * scale * np.sin(np.linspace(0, 1.2 * np.pi, 120))
    # Outer bark
    ax.plot(bx, by, color="#36261b", lw=6.5 * scale, solid_capstyle='round', zorder=5)
    ax.plot(bx, by, color="#543e2e", lw=4.5 * scale, solid_capstyle='round', zorder=6)
    # Bark grain striations
    ax.plot(bx[10:-10], by[10:-10] + 0.15 * scale, color="#785c45", lw=1.4 * scale, alpha=0.8, zorder=7)
    ax.plot(bx[15:-15], by[15:-15] - 0.15 * scale, color="#22160f", lw=1.2 * scale, alpha=0.6, zorder=7)

    # 2. Prehensile Tail: Logarithmic spiral with ribbed scale segments
    t_out = np.linspace(0, 3.4 * np.pi, 120)
    r_out = scale * (1.30 - 0.28 * t_out / np.pi)
    tx_out = (cx + 1.85 * scale) + r_out * np.cos(t_out)
    ty_out = (cy + 0.18 * scale) + r_out * np.sin(t_out)

    t_in = np.linspace(3.4 * np.pi, 0, 120)
    r_in = scale * np.maximum(0.04, 0.98 - 0.28 * t_in / np.pi)
    tx_in = (cx + 1.85 * scale) + r_in * np.cos(t_in)
    ty_in = (cy + 0.18 * scale) + r_in * np.sin(t_in)

    tail_poly = np.vstack([np.column_stack([tx_out, ty_out]), np.column_stack([tx_in, ty_in])])
    ax.add_patch(Polygon(tail_poly, closed=True, facecolor=base_hex, edgecolor=INK, lw=1.3 * scale, zorder=8))

    # Transverse scale rings on tail
    for i in range(10, 105, 5):
        ax.plot([tx_out[i], tx_in[120 - 1 - i]], [ty_out[i], ty_in[120 - 1 - i]],
                color=dark_hex, lw=0.9 * scale, alpha=0.7, zorder=9)

    # 3. Main Torso: Anatomical Profile
    body_pts = np.array([
        [cx - 2.3 * scale, cy + 0.10 * scale],  # Snout tip
        [cx - 2.0 * scale, cy + 0.75 * scale],  # Nasal ridge
        [cx - 1.5 * scale, cy + 1.60 * scale],  # Parietal casque peak
        [cx - 0.9 * scale, cy + 1.50 * scale],  # Occipital crest
        [cx - 0.2 * scale, cy + 1.68 * scale],  # Nape
        [cx + 0.5 * scale, cy + 1.72 * scale],  # Back arch peak
        [cx + 1.3 * scale, cy + 1.38 * scale],  # Lumbar
        [cx + 1.9 * scale, cy + 0.70 * scale],  # Sacrum
        [cx + 1.85 * scale, cy - 0.10 * scale], # Tail base
        [cx + 1.3 * scale, cy - 0.82 * scale],  # Posterior belly
        [cx + 0.3 * scale, cy - 1.05 * scale],  # Mid belly
        [cx - 0.7 * scale, cy - 0.85 * scale],  # Abdomen
        [cx - 1.4 * scale, cy - 0.50 * scale],  # Gular pouch
        [cx - 2.0 * scale, cy - 0.18 * scale],  # Lower jaw
    ])
    ax.add_patch(Polygon(body_pts, closed=True, facecolor=base_hex, edgecolor=INK, lw=1.6 * scale, zorder=10))

    # Subtle mouth cleft (small 0.35 line)
    ax.plot([cx - 2.3 * scale, cx - 1.9 * scale], [cy + 0.10 * scale, cy + 0.02 * scale], color=INK, lw=1.2 * scale, zorder=11)

    # Tuberculate Scale Texture across flanks (scattered polygonal scales)
    grid_x, grid_y = np.meshgrid(np.linspace(-1.5, 1.5, 12), np.linspace(-0.6, 1.2, 8))
    for gx, gy in zip(grid_x.flatten(), grid_y.flatten()):
        # Check if inside body approximation
        if (gx/1.6)**2 + (gy/1.2)**2 < 0.85 and not (gx < -0.8 and gy > 0.4):
            sx, sy = cx + gx * scale, cy + gy * scale
            ax.add_patch(Circle((sx, sy), 0.09 * scale, facecolor=light_hex, edgecolor=dark_hex, lw=0.4 * scale, alpha=0.6, zorder=11))

    # Camouflage Flank Band
    flank_x = np.linspace(cx - 0.8 * scale, cx + 1.3 * scale, 25)
    flank_y = cy + 0.38 * scale - 0.16 * scale * ((flank_x - cx) / scale)**2
    ax.plot(flank_x, flank_y, color=light_hex, lw=2.4 * scale, alpha=0.8, zorder=12, solid_capstyle='round')

    # Dorsal Crest Scutes (triangular spines along vertebral ridge)
    spike_xs = np.linspace(cx - 0.8 * scale, cx + 1.5 * scale, 11)
    for sx in spike_xs:
        sy = cy + 1.70 * scale - 0.30 * scale * ((sx - (cx + 0.2 * scale)) / scale)**2
        sp = Polygon([
            [sx - 0.09 * scale, sy - 0.02 * scale],
            [sx, sy + 0.24 * scale],
            [sx + 0.09 * scale, sy - 0.02 * scale]
        ], closed=True, facecolor=light_hex, edgecolor=INK, lw=0.8 * scale, zorder=11)
        ax.add_patch(sp)

    # 4. Detailed Eye Turret (conical ocular dome with radial skin folds)
    ex, ey = cx - 1.40 * scale, cy + 0.65 * scale
    # Outer ocular cone
    ax.add_patch(Circle((ex, ey), 0.54 * scale, facecolor=dark_hex, edgecolor=INK, lw=1.4 * scale, zorder=13))
    # Radial skin folds
    for ang in np.linspace(0, 2*np.pi, 8, endpoint=False):
        ax.plot([ex + 0.35*scale*np.cos(ang), ex + 0.52*scale*np.cos(ang)],
                [ey + 0.35*scale*np.sin(ang), ey + 0.52*scale*np.sin(ang)],
                color=INK, lw=0.8 * scale, zorder=14)
    # Eyelid dome
    ax.add_patch(Circle((ex, ey), 0.36 * scale, facecolor=base_hex, edgecolor=INK, lw=1.0 * scale, zorder=15))
    # Pupil aperture & Iris
    ax.add_patch(Circle((ex - 0.04 * scale, ey + 0.02 * scale), 0.18 * scale, facecolor=light_hex, zorder=16))
    ax.add_patch(Circle((ex - 0.06 * scale, ey + 0.02 * scale), 0.10 * scale, facecolor=INK, zorder=17))
    # Specular catchlight reflections
    ax.add_patch(Circle((ex - 0.10 * scale, ey + 0.06 * scale), 0.04 * scale, facecolor="white", zorder=18))
    ax.add_patch(Circle((ex - 0.02 * scale, ey - 0.02 * scale), 0.02 * scale, facecolor="white", zorder=18))

    # 5. Limbs & Zygodactyl Feet clutching branch
    # Foreleg
    fore_verts = [[cx - 0.7 * scale, cy - 0.3 * scale], [cx - 1.1 * scale, cy - 0.85 * scale], [cx - 0.9 * scale, cy - 1.30 * scale]]
    ax.plot([v[0] for v in fore_verts], [v[1] for v in fore_verts], color=dark_hex, lw=3.8 * scale, solid_capstyle='round', zorder=8)
    ax.plot([v[0] for v in fore_verts], [v[1] for v in fore_verts], color=INK, lw=1.2 * scale, zorder=8)
    ax.add_patch(Circle((cx - 0.9 * scale, cy - 1.30 * scale), 0.26 * scale, facecolor=base_hex, edgecolor=INK, lw=1.1 * scale, zorder=9))

    # Hindleg
    hind_verts = [[cx + 0.8 * scale, cy - 0.2 * scale], [cx + 1.2 * scale, cy - 0.85 * scale], [cx + 0.95 * scale, cy - 1.30 * scale]]
    ax.plot([v[0] for v in hind_verts], [v[1] for v in hind_verts], color=dark_hex, lw=4.0 * scale, solid_capstyle='round', zorder=8)
    ax.plot([v[0] for v in hind_verts], [v[1] for v in hind_verts], color=INK, lw=1.2 * scale, zorder=8)
    ax.add_patch(Circle((cx + 0.95 * scale, cy - 1.30 * scale), 0.26 * scale, facecolor=base_hex, edgecolor=INK, lw=1.1 * scale, zorder=9))


def draw_realistic_oak_leaf(ax, center, scale, angle_deg, color):
    cx, cy = center
    rad = np.radians(angle_deg)
    # Lobed oak/autumn leaf
    pts = []
    # Right side lobes
    for t in np.linspace(0, np.pi, 30):
        r = 0.8 * scale * np.sin(t) * (1 + 0.35 * np.sin(5 * t))
        x = r * np.sin(t)
        y = 2.2 * scale * (1 - np.cos(t)) * 0.5
        pts.append([x, y])
    # Left side lobes
    for t in np.linspace(np.pi, 0, 30):
        r = 0.8 * scale * np.sin(t) * (1 + 0.35 * np.sin(5 * t))
        x = -r * np.sin(t)
        y = 2.2 * scale * (1 - np.cos(t)) * 0.5
        pts.append([x, y])
    pts = np.array(pts)
    R = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
    rot_pts = pts @ R.T + np.array([cx, cy])
    ax.add_patch(Polygon(rot_pts, closed=True, facecolor=color, edgecolor=INK, lw=0.9, alpha=0.90, zorder=4))
    # Midrib & lateral veins
    apex = np.array([0, 2.2 * scale]) @ R.T + np.array([cx, cy])
    ax.plot([cx, apex[0]], [cy, apex[1]], color=INK, lw=0.9, alpha=0.7, zorder=5)


def draw_realistic_monstera_leaf(ax, center, scale, angle_deg, color):
    cx, cy = center
    rad = np.radians(angle_deg)
    pts = []
    for t in np.linspace(0, np.pi, 36):
        r = 1.4 * scale * np.sin(t)
        if 0.30 < t < 0.45 or 0.60 < t < 0.75:
            r *= 0.45
        x = r * np.sin(t)
        y = 2.5 * scale * (1 - np.cos(t)) * 0.5
        pts.append([x, y])
    for t in np.linspace(np.pi, 0, 36):
        r = 1.4 * scale * np.sin(t)
        if 0.30 < t < 0.45 or 0.60 < t < 0.75:
            r *= 0.45
        x = -r * np.sin(t)
        y = 2.5 * scale * (1 - np.cos(t)) * 0.5
        pts.append([x, y])
    pts = np.array(pts)
    R = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
    rot_pts = pts @ R.T + np.array([cx, cy])
    ax.add_patch(Polygon(rot_pts, closed=True, facecolor=color, edgecolor=INK, lw=1.0, alpha=0.90, zorder=4))
    apex = np.array([0, 2.5 * scale]) @ R.T + np.array([cx, cy])
    ax.plot([cx, apex[0]], [cy, apex[1]], color=INK, lw=1.0, alpha=0.7, zorder=5)


def draw_realistic_lavender_field(ax, x0, y0, w, h, color):
    # Multiple layered botanical lavender stalks
    for stem_x in np.linspace(x0 + 1.8, x0 + w - 1.8, 8):
        ax.plot([stem_x, stem_x], [y0 + 5.0, y0 + 19.0], color="#4d6346", lw=1.5, zorder=3)
        # Basal linear leaves
        for ly in np.linspace(y0 + 6.0, y0 + 11.0, 3):
            ax.plot([stem_x, stem_x - 0.6], [ly, ly + 0.3], color="#4d6346", lw=1.1, zorder=3)
            ax.plot([stem_x, stem_x + 0.6], [ly, ly + 0.3], color="#4d6346", lw=1.1, zorder=3)
        # Tiered floral calyx whorls
        for by in np.linspace(y0 + 11.5, y0 + 19.0, 7):
            ax.add_patch(Circle((stem_x - 0.32, by), 0.28, facecolor=color, edgecolor=INK, lw=0.7, alpha=0.92, zorder=4))
            ax.add_patch(Circle((stem_x + 0.32, by), 0.28, facecolor=color, edgecolor=INK, lw=0.7, alpha=0.92, zorder=4))
            ax.add_patch(Circle((stem_x, by + 0.12), 0.22, facecolor="#c5c4e8", edgecolor=INK, lw=0.6, alpha=0.95, zorder=5))


def draw_panel_1_red(ax, bbox):
    # Panel 1: Red (#ed2024) - Terracotta Desert & Autumn Canopy
    x0, y0, w, h = bbox
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor=RED, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor='none', edgecolor=RED, lw=2.2, zorder=2))

    # Header label
    ax.text(x0 + 0.5 * w, y0 + h - 2.8, "Red Desert & Autumn Canopy",
            ha="center", va="center", color=RED, fontsize=13, fontweight="bold", zorder=20)

    # Desert Sand Dune Ridges in background
    for dy, alph in [(y0 + 8.0, 0.12), (y0 + 11.0, 0.20), (y0 + 14.5, 0.28)]:
        dxs = np.linspace(x0 + 0.8, x0 + w - 0.8, 60)
        dys = dy + 0.9 * np.sin(np.linspace(0, 2.5 * np.pi, 60))
        ax.fill_between(dxs, y0 + 0.8, dys, color=RED, alpha=alph, zorder=2)
        ax.plot(dxs, dys, color=RED, lw=1.0, alpha=0.4, zorder=3)

    # Rich autumn leaves
    for lx, ly, rot, sc in [
        (x0 + 3.2, y0 + h - 8.5, 30, 1.4),
        (x0 + 7.2, y0 + h - 6.5, -20, 1.3),
        (x0 + w - 3.8, y0 + h - 8.0, 25, 1.4),
        (x0 + 2.8, y0 + 15.5, -45, 1.2),
        (x0 + w - 3.0, y0 + 16.0, 40, 1.2),
    ]:
        draw_realistic_oak_leaf(ax, (lx, ly), scale=sc, angle_deg=rot, color=RED)

    # Chameleon
    branch_y = y0 + 20.5
    draw_realistic_chameleon(ax, (x0 + 0.50 * w, branch_y + 4.8), scale=1.35,
                             base_hex=RED, dark_hex="#aa1215", light_hex="#ff7b7d")

    # Bottom descriptor
    ax.text(x0 + 0.5 * w, y0 + 3.2, "Namib dunes · terracotta foliage",
            ha="center", va="center", color=MUTED, fontsize=11.5, zorder=20)


def draw_panel_2_green(ax, bbox):
    # Panel 2: Green (#0c8140) - Tropical Rainforest Canopy
    x0, y0, w, h = bbox
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor=GREEN, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor='none', edgecolor=GREEN, lw=2.2, zorder=2))

    # Header label
    ax.text(x0 + 0.5 * w, y0 + h - 2.8, "Tropical Rainforest Canopy",
            ha="center", va="center", color=GREEN, fontsize=13, fontweight="bold", zorder=20)

    # Misty rainforest canopy background
    for dy, alph in [(y0 + 8.5, 0.12), (y0 + 11.5, 0.20), (y0 + 14.5, 0.28)]:
        dxs = np.linspace(x0 + 0.8, x0 + w - 0.8, 60)
        dys = dy + 0.8 * np.sin(np.linspace(0.5, 3.0 * np.pi, 60))
        ax.fill_between(dxs, y0 + 0.8, dys, color=GREEN, alpha=alph, zorder=2)
        ax.plot(dxs, dys, color=GREEN, lw=1.0, alpha=0.4, zorder=3)

    # Hanging jungle vine
    vx = np.linspace(x0 + 2.0, x0 + 7.5, 50)
    vy = y0 + h - 5.5 - 4.2 * np.sin(np.linspace(0, np.pi, 50))
    ax.plot(vx, vy, color="#055328", lw=2.2, zorder=3)

    # Tropical Monstera leaves
    for lx, ly, rot, sc in [
        (x0 + 3.2, y0 + h - 8.5, 25, 1.5),
        (x0 + w - 3.8, y0 + h - 8.0, -35, 1.4),
        (x0 + 2.8, y0 + 16.0, -45, 1.2),
        (x0 + w - 3.2, y0 + 15.5, 45, 1.2),
    ]:
        draw_realistic_monstera_leaf(ax, (lx, ly), scale=sc, angle_deg=rot, color=GREEN)

    # Chameleon
    branch_y = y0 + 20.5
    draw_realistic_chameleon(ax, (x0 + 0.50 * w, branch_y + 4.8), scale=1.35,
                             base_hex=GREEN, dark_hex="#065429", light_hex="#38c976")

    # Bottom descriptor
    ax.text(x0 + 0.5 * w, y0 + 3.2, "Lush understory · humid canopy",
            ha="center", va="center", color=MUTED, fontsize=11.5, zorder=20)


def draw_panel_3_purple(ax, bbox):
    # Panel 3: Purple (#9695c9) - Alpine Lavender & Heathland
    x0, y0, w, h = bbox
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor=PURPLE, alpha=0.07, edgecolor='none', zorder=1))
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.6",
                                facecolor='none', edgecolor=PURPLE, lw=2.2, zorder=2))

    # Header label
    ax.text(x0 + 0.5 * w, y0 + h - 2.8, "Alpine Lavender & Heathland",
            ha="center", va="center", color=PURPLE, fontsize=13, fontweight="bold", zorder=20)

    # Alpine mountain ridges
    for dy, alph in [(y0 + 8.5, 0.12), (y0 + 11.5, 0.20), (y0 + 14.5, 0.28)]:
        dxs = np.linspace(x0 + 0.8, x0 + w - 0.8, 60)
        dys = dy + 1.2 * np.cos(np.linspace(0, 2.2 * np.pi, 60))
        ax.fill_between(dxs, y0 + 0.8, dys, color=PURPLE, alpha=alph, zorder=2)
        ax.plot(dxs, dys, color=PURPLE, lw=1.0, alpha=0.4, zorder=3)

    # Botanical lavender field
    draw_realistic_lavender_field(ax, x0, y0, w, h, PURPLE)

    # Chameleon
    branch_y = y0 + 20.5
    draw_realistic_chameleon(ax, (x0 + 0.50 * w, branch_y + 4.8), scale=1.35,
                             base_hex=PURPLE, dark_hex="#68679b", light_hex="#cfceee")

    # Bottom descriptor
    ax.text(x0 + 0.5 * w, y0 + 3.2, "Montane dusk · floral heath",
            ha="center", va="center", color=MUTED, fontsize=11.5, zorder=20)


def main():
    # Exactly 7:5 ratio (14 x 10 in)
    fig, ax = plt.subplots(figsize=(14, 10), dpi=100)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 71.428)  # 100 * (5/7) = 71.428
    ax.axis("off")

    # Outer boundary frame
    ax.add_patch(FancyBboxPatch((1.5, 1.5), 97, 68.428, boxstyle="round,pad=0,rounding_size=0.8",
                                linewidth=1.2, edgecolor=RULE, facecolor="none", zorder=30))

    w_panel = 27.2
    h_panel = 51.0
    y_panel = 11.5
    x1 = 5.0
    x2 = 36.4
    x3 = 67.8

    # 1. Three environments in exact order: Red, Green, Purple
    draw_panel_1_red(ax, (x1, y_panel, w_panel, h_panel))
    draw_panel_2_green(ax, (x2, y_panel, w_panel, h_panel))
    draw_panel_3_purple(ax, (x3, y_panel, w_panel, h_panel))

    # 2. Flat horizontal connecting arrows
    arrow_y = y_panel + 0.5 * h_panel
    arrow(ax, (x1 + w_panel + 0.8, arrow_y), (x2 - 0.8, arrow_y), color=INK, lw=2.2, ms=24)
    arrow(ax, (x2 + w_panel + 0.8, arrow_y), (x3 - 0.8, arrow_y), color=INK, lw=2.2, ms=24)

    # 3. Footnote inside boundary box
    ax.plot([6.0, 94.0], [7.0, 7.0], color=RULE, lw=1.2, zorder=20)
    ax.text(50.0, 4.0, "Adaptive state transformation under varying environmental task conditions.",
            ha="center", va="center", color=MUTED, fontsize=15, zorder=20)

    fig.savefig(OUT_SVG, format="svg", bbox_inches="tight", pad_inches=0)
    fig.savefig(OUT_PDF, format="pdf", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


if __name__ == "__main__":
    main()

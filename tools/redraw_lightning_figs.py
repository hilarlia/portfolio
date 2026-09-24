#!/usr/bin/env python3
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"

BLUE = "#2147c6"
INK = "#1b2638"
MUTED = "#5f6777"
ORANGE = "#d4881f"
GREEN = "#3a8652"
LAV = "#5b6ec0"
MID = "#5f7fd1"
CREAM = "#ffe7bd"
RULE = "#d3d8ea"

plt.rcParams.update({"font.family": "serif", "font.size": 13, "mathtext.fontset": "cm"})


def arrow(ax, p, q, color=INK, lw=1.8, ms=24, style='-|>'):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=ms, linewidth=lw, color=color))


def draw_state(ax, xy, r, color, label):
    x, y = xy
    ax.add_patch(Circle((x, y), r, facecolor="#eef2ff", edgecolor=INK, linewidth=1.4))
    ax.plot([x - 0.65*r, x + 0.65*r], [y - 0.45*r, y - 0.45*r], color=color, lw=1.5)
    ax.add_patch(Circle((x - 0.35*r, y - 0.1*r), 0.12*r, facecolor="white", edgecolor=INK, lw=1.0))
    ax.add_patch(Circle((x + 0.05*r, y + 0.25*r), 0.16*r, facecolor=color, edgecolor=INK, lw=1.0))
    ax.add_patch(Circle((x + 0.35*r, y - 0.2*r), 0.09*r, facecolor="white", edgecolor=INK, lw=1.0))
    ax.text(x, y - 1.72*r, label, ha="center", va="top", color=BLUE, fontsize=15)


def draw_action(ax, xy, r, idx):
    x, y = xy
    ax.add_patch(Circle((x, y), r, facecolor=CREAM, edgecolor=INK, linewidth=1.3))
    ax.text(x, y, rf"$\mathcal{{A}}^{{({idx})}}$", ha="center", va="center", color=ORANGE, fontsize=13)


def draw_task(ax, xy, r, idx, color):
    x, y = xy
    ax.add_patch(Circle((x, y), r, facecolor="white", edgecolor=INK, linewidth=1.4))
    ax.add_patch(Circle((x, y), 0.72*r, facecolor="none", edgecolor=color, linewidth=2.3))
    ax.text(x, y, rf"$\mathcal{{T}}^{{({idx})}}$", ha="center", va="center", color=color, fontsize=15)


def fig2():
    fig, ax = plt.subplots(figsize=(14.8, 6.8), dpi=100)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 50)
    ax.axis("off")

    ax.add_patch(FancyBboxPatch((1.5, 1.5), 97, 47, boxstyle="round,pad=0.3,rounding_size=1.0",
                                linewidth=1.2, edgecolor=RULE, facecolor="none"))

    ax.text(50, 46.5, r"Controller policy  $\pi=\{\mu_s\}_{s\in\mathbb{N}_S}$",
            ha="center", va="center", color=BLUE, fontsize=20)
    ax.plot([18, 82], [42.2, 42.2], color=BLUE, lw=1.6)

    states = [(8, 28), (40, 28), (68, 28), (90, 28)]
    actions = [(20, 28), (48, 28), (76, 28)]
    tasks = [(30, 28), (58, 28), (86, 28)]
    task_colors = [GREEN, ORANGE, LAV]

    draw_state(ax, states[0], 3.8, BLUE, r"$\Xi_0$")
    draw_state(ax, states[1], 3.0, GREEN, r"$\Xi^{(1)}_{y_1}$")
    draw_state(ax, states[2], 3.0, ORANGE, r"$\Xi^{(2)}_{y_{1:2}}$")
    draw_state(ax, states[3], 3.0, LAV, r"$\Xi^{(3)}_{y_{1:3}}$")

    for i in range(3):
        draw_action(ax, actions[i], 1.9, i+1)
        draw_task(ax, tasks[i], 4.2, i+1, task_colors[i])

    # stage flow
    for p, q in [((11.9,28),(18.2,28)),((21.9,28),(25.5,28)),((34.2,28),(36.8,28)),
                 ((43.0,28),(46.2,28)),((49.9,28),(53.8,28)),((62.2,28),(65.0,28)),
                 ((71.1,28),(74.2,28)),((77.9,28),(81.7,28))]:
        arrow(ax, p, q)

    ax.text(24.0, 19.9, r"stage $1$", color=MUTED, ha="center", fontsize=14)
    ax.text(52.0, 19.9, r"stage $2$", color=MUTED, ha="center", fontsize=14)
    ax.text(80.0, 19.9, r"stage $3$", color=MUTED, ha="center", fontsize=14)

    # outcome branches to controller
    for i, (tx, ty) in enumerate(tasks, 1):
        ax.plot([tx, tx-2.4, tx-2.4], [ty+4.2, ty+8.8, 38.0], color=BLUE, lw=1.4, ls=(0, (4, 3)))
        ax.plot([tx, tx+2.4, tx+2.4], [ty+4.2, ty+8.8, 38.0], color=BLUE, lw=1.4, ls=(0, (4, 3)))
        ax.add_patch(Circle((tx-2.4, 38.7), 0.46, facecolor='white', edgecolor=BLUE, lw=1.2))
        ax.add_patch(Circle((tx+2.4, 38.7), 0.46, facecolor='white', edgecolor=BLUE, lw=1.2))
        arrow(ax, (tx+2.4, 39.2), (tx+2.4, 41.9), color=BLUE, lw=1.2, ms=18)
        ax.text(tx+6.2, 36.7, rf"$y_{i}\in\mathbb{{Y}}$", color=MUTED, fontsize=14, ha="left")

    # controller to actions
    for axx, _ in actions:
        ax.plot([axx, axx], [42.2, 30.3], color=BLUE, lw=1.2, ls=(0, (4, 3)))
        arrow(ax, (axx, 30.3), (axx, 29.8), color=BLUE, lw=1.2, ms=17)

    reward_y = 14.7
    reward_r = 1.35
    for i, tx in enumerate([30, 58, 86], 1):
        ax.plot([tx, tx], [23.8, reward_y + reward_r], color=ORANGE, lw=1.6)
        ax.add_patch(Circle((tx, reward_y), reward_r, facecolor=CREAM, edgecolor=INK, lw=1.2))
        ax.text(tx, reward_y-0.05, rf"$R^{{({i})}}$", ha="center", va="center", color=ORANGE, fontsize=14)

    # cumulative line segments touch reward balls exactly at tangency
    ax.plot([30 + reward_r, 58 - reward_r], [reward_y, reward_y], color=RULE, lw=1.6)
    ax.plot([58 + reward_r, 86 - reward_r], [reward_y, reward_y], color=RULE, lw=1.6)
    ax.text(44.0, reward_y, r"$+$", ha="center", va="center", color=MUTED, fontsize=24)
    ax.text(72.0, reward_y, r"$+$", ha="center", va="center", color=MUTED, fontsize=24)
    arrow(ax, (86 + reward_r, reward_y), (94.8, reward_y), color=INK, lw=1.8, ms=24)
    ax.text(95.6, reward_y, r"$\sum_{s=1}^{S} R^{(s)}$", ha="left", va="center", color=ORANGE, fontsize=20)

    ax.text(50, 6.2, r"maximize $\mathbb{E}\!\left[\sum_{s=1}^{S} R^{(s)}\right]$ while preserving future decision quality",
            ha="center", color=MUTED, fontsize=16)

    fig.savefig(OUT / "figure2-quantum-tasks.svg", format="svg", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def fig3():
    fig, ax = plt.subplots(figsize=(14.4, 7.4), dpi=100)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.axis("off")

    ax.add_patch(FancyBboxPatch((1.5, 1.5), 97, 57, boxstyle="round,pad=0.3,rounding_size=1.0",
                                linewidth=1.2, edgecolor=RULE, facecolor="none"))

    # concise, non-overlapping headers
    ax.text(11.0, 53.3, r"$1$  full state", color=INK, fontsize=17, fontweight="bold", ha="center")
    ax.text(45.0, 53.3, r"$2$  filter", color=INK, fontsize=17, fontweight="bold", ha="center")
    ax.text(67.0, 53.3, r"$3$  retained coords", color=INK, fontsize=17, fontweight="bold", ha="center")
    ax.text(88.5, 53.3, r"$4$  action set", color=INK, fontsize=17, fontweight="bold", ha="center")

    # step 1
    ax.add_patch(FancyBboxPatch((5.0, 16.0), 24.0, 34.0, boxstyle="round,pad=0.4,rounding_size=0.2",
                                linewidth=1.6, edgecolor=INK, facecolor="#f3f5fd"))
    ys = [18.5 + i * 2.9 for i in range(11)]
    keep = {2: MID, 5: ORANGE, 8: BLUE}
    for i, y in enumerate(ys):
        c = keep.get(i, "#c7cde0")
        lw = 3.0 if i in keep else 1.1
        ax.plot([7.2, 27.3], [y, y + (0.35 if i % 2 else -0.35)], color=c, lw=lw)
    ax.text(17.0, 12.0, r"$d^2-1$ directions", color=MUTED, fontsize=17, ha="center")

    # step 2
    arrow(ax, (29.8, 33.0), (36.2, 33.0), color=INK, lw=1.8, ms=24)
    ax.add_patch(FancyBboxPatch((36.5, 18.8), 18.0, 28.2, boxstyle="round,pad=0.45,rounding_size=0.2",
                                linewidth=1.6, edgecolor=INK, facecolor="#fff2d8"))
    for txt, y in [("retain only",35.6),("directions that",32.4),("affect",29.2),("future reward",26.0)]:
        ax.text(45.5, y, txt, fontsize=16, ha="center", color=INK)

    # map full->filter->effective
    in_x, out_x = 36.5, 54.5
    eff_x0, eff_x1 = 62.0, 76.8
    y_in = [ys[k] for k in sorted(keep)]
    y_out = [40.4, 33.0, 25.6]
    cols = [MID, ORANGE, BLUE]
    for yi, yo, c in zip(y_in, y_out, cols):
        ax.plot([27.3, in_x], [yi, yo], color=c, lw=3.0)
        ax.plot([out_x, eff_x0], [yo, yo], color=c, lw=3.0)

    # step 3
    arrow(ax, (55.0, 33.0), (61.2, 33.0), color=INK, lw=1.8, ms=24)
    for y, c in zip(y_out, cols):
        y2 = y + (0.65 if c != ORANGE else -0.65)
        ax.plot([eff_x0, eff_x1], [y, y2], color=c, lw=3.0)
        ax.add_patch(Circle((eff_x1, y2), 0.78, facecolor=c, edgecolor=INK, lw=1.0))
    ax.text(69.5, 19.9, r"$r^2-1$ retained directions", color=MUTED, fontsize=17, ha="center")

    # step 4
    arrow(ax, (77.9, 33.0), (84.0, 33.0), color=INK, lw=1.8, ms=24)
    action_x = 93.0
    for y, edge, lw in ((40.2, INK, 1.6), (33.0, ORANGE, 2.3), (25.8, INK, 1.6)):
        ax.add_patch(Circle((action_x, y), 1.95, facecolor=(CREAM if edge == ORANGE else "white"), edgecolor=edge, lw=lw))
        ax.text(action_x, y, r"$A$", ha="center", va="center", fontsize=18, color=edge)
    ax.plot([77.7, 90.9], [40.6, 40.2], color=INK, lw=1.8)
    ax.plot([77.7, 90.9], [33.0, 33.0], color=INK, lw=1.8)
    ax.plot([77.7, 90.9], [25.4, 25.8], color=INK, lw=1.8)
    ax.text(87.0, 20.2, r"near-optimal action", color=ORANGE, fontsize=19)

    ax.plot([8.5, 91.0], [8.3, 8.3], color=RULE, lw=1.5)
    ax.text(49.7, 4.2, r"Plan on reduced coordinates while preserving reward-relevant structure.",
            ha="center", fontsize=18, color=MUTED)

    fig.savefig(OUT / "figure3-effective-dimension.svg", format="svg", bbox_inches="tight", pad_inches=0)
    plt.close(fig)


if __name__ == "__main__":
    fig2()
    fig3()

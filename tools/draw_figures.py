#!/usr/bin/env python3
"""Generate the three hand-illustrated figures used by docs/project.html."""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
INK, BLUE, MID, LIGHT, CREAM, ORANGE, PAPER, RULE, MUTED = (
    "#182332", "#2449ae", "#5978c3", "#91a8dd", "#ffe4b8",
    "#ff8b20", "#ffffff", "#c9cfe2", "#626674"
)
FONT = "Source Sans Pro, Helvetica Neue, Helvetica, Arial, sans-serif"


def text(x, y, value, size=20, fill=INK, weight="400", anchor="middle", italic=False):
    style = ' font-style="italic"' if italic else ''
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}"{style}>{value}</text>'


def svg(w, h, label, body, defs=""):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{label}">
<defs>{defs}</defs><rect width="{w}" height="{h}" fill="{PAPER}"/>
<g stroke-linejoin="round" stroke-linecap="round">
<rect x="20" y="20" width="{w-40}" height="{h-40}" rx="10" fill="none" stroke="{RULE}" stroke-width="1.4"/>{body}</g></svg>'''


def marker(name, color):
    return f'<marker id="{name}" markerWidth="9" markerHeight="9" refX="7.5" refY="3.5" orient="auto"><path d="M0 0L0 7L8 3.5Z" fill="{color}"/></marker>'


def chameleon(x, y, color, scale=.78):
    """Small natural-profile chameleon, drawn with one restrained ink contour."""
    return f'''<g transform="translate({x} {y}) scale({scale})" fill="none" stroke="{INK}" stroke-width="2.4">
      <path d="M66 92 C48 78 24 82 18 103 C13 122 29 137 47 130 C60 125 61 109 50 104 C42 100 36 107 39 115" stroke="{color}" stroke-width="8"/>
      <path d="M64 94 C58 68 75 44 104 38 C130 33 151 42 166 55
               C178 48 194 49 204 59 C214 69 210 82 198 89
               C187 96 175 94 164 90 C153 112 131 126 104 128
               C82 130 67 117 64 94Z" fill="{color}" fill-opacity=".15"/>
      <path d="M82 53 Q88 42 94 52 Q101 39 108 50 Q116 39 123 51 Q131 43 138 54" stroke="{color}" stroke-width="3.2"/>
      <path d="M88 119 Q82 139 92 148 Q98 152 104 145 M96 148 Q90 153 84 149
               M147 108 Q154 125 151 141 Q153 150 162 149 M161 149 Q168 151 170 144"/>
      <circle cx="186" cy="65" r="9.5" fill="{PAPER}"/><circle cx="189" cy="64" r="3" fill="{INK}" stroke="none"/>
      <path d="M176 82 Q188 85 198 78 M93 76 Q109 66 128 74 M86 108 Q107 119 132 108" stroke="{color}" stroke-width="1.7"/>
      <circle cx="111" cy="90" r="3.6" fill="{color}" stroke="none"/><circle cx="130" cy="93" r="2.8" fill="{color}" stroke="none"/>
    </g>'''


def figure1():
    w, h = 1400, 650
    defs = marker("flat-arrow", MID)
    body = ""
    panels = [(50, "#eaf3e4", "#4f8f4a", "leafy understory"),
              (525, "#fff0db", "#d18a22", "dry scrub"),
              (1000, "#edf0fb", "#5566b8", "cool forest shade")]
    for i, (x, wash, color, label) in enumerate(panels, 1):
        body += f'<rect x="{x}" y="135" width="350" height="350" rx="15" fill="{wash}" stroke="{INK}" stroke-width="1.5"/>'
        body += f'<circle cx="{x+30}" cy="165" r="15" fill="{PAPER}" stroke="{INK}" stroke-width="1.5"/>{text(x+30,171,str(i),16,weight="700")}'
        if i == 1:  # leaves, vine, ground cover
            body += f'<path d="M{x+28} 230 Q{x+62} 195 {x+94} 230 Q{x+60} 250 {x+28} 230Z M{x+248} 204 Q{x+285} 170 {x+318} 207 Q{x+280} 230 {x+248} 204Z" fill="none" stroke="{color}" stroke-width="2"/>'
            body += f'<path d="M{x+314} 137 Q{x+288} 190 {x+318} 246 M{x+18} 425 q35 -30 70 0 q-35 25 -70 0 M{x+265} 435 q31 -28 64 0 q-32 23 -64 0" fill="none" stroke="{color}" stroke-width="2"/>'
        elif i == 2:  # sun, dunes, stones, dry shrub
            body += f'<circle cx="{x+285}" cy="195" r="29" fill="{CREAM}" stroke="none"/><path d="M{x+15} 430 Q{x+105} 380 {x+195} 426 T{x+340} 405" fill="none" stroke="{color}" stroke-width="2"/>'
            body += f'<path d="M{x+55} 405 l-12 -30 m12 30 l13 -24 m-13 9 l-17 -8 M{x+275} 438 q12 -12 24 0" fill="none" stroke="{color}" stroke-width="2"/><circle cx="{x+302}" cy="444" r="7" fill="{color}" opacity=".35"/>'
        else:  # canopy, rock, fern, shafts of shade
            body += f'<path d="M{x+15} 200 Q{x+65} 155 {x+115} 200 M{x+225} 188 Q{x+280} 145 {x+335} 192" fill="none" stroke="{color}" stroke-width="2"/>'
            body += f'<path d="M{x+25} 440 q25 -35 50 0 m-25 -22 l-18 -8 m18 8 l19 -11 M{x+273} 438 q22 -28 45 0" fill="none" stroke="{color}" stroke-width="2"/><path d="M{x+270} 145 L{x+220} 330 M{x+325} 145 L{x+280} 330" stroke="{LIGHT}" stroke-width="10" opacity=".18"/>'
        body += f'<path d="M{x+67} 386 Q{x+175} 378 {x+284} 386" fill="none" stroke="#7b5b3a" stroke-width="5"/>'
        body += chameleon(x+90, 268, color)
        body += text(x+175, 525, label, 20)
    # Flat transitions occupy their own clear 125px gaps.
    for x1, x2 in ((412, 510), (887, 985)):
        body += f'<path d="M{x1} 310 H{x2}" stroke="{MID}" stroke-width="2.5" marker-end="url(#flat-arrow)"/>'
    body += text(w/2, 590, "The same animal changes colour as its surroundings change.", 21, MUTED)
    (OUT / "figure1-chameleon.svg").write_text(svg(w, h, "Three detailed habitat sketches show a small line-drawn chameleon changing colour from a leafy understory to dry scrub and cool forest shade. Flat arrows connect the environments.", body, defs))


def state_glyph(x, y, color, variant):
    """Simple abstract density-state glyph: an outlined droplet with changing internal weights."""
    shifts = [(0, 0), (5, -4), (-4, 5), (3, 3)][variant]
    return f'''<g transform="translate({x} {y})" fill="none" stroke="{INK}" stroke-width="1.7">
      <path d="M0 -34 C28 -30 42 -8 31 17 C21 39 -14 43 -31 22 C-48 1 -31 -29 0 -34Z" fill="{color}" fill-opacity=".2"/>
      <circle cx="{-15+shifts[0]}" cy="{3+shifts[1]}" r="5" fill="{PAPER}"/>
      <circle cx="{2+shifts[0]}" cy="{-8+shifts[1]}" r="8" fill="{color}"/>
      <circle cx="{19-shifts[0]}" cy="{8-shifts[1]}" r="4" fill="{PAPER}"/>
      <path d="M-23 22 Q0 {12+shifts[1]} 23 22" stroke="{color}" stroke-width="2"/>
    </g>'''


def figure2():
    """General-audience redraw of manuscript Fig. 1: state, action, task, outcome, reward."""
    w, h = 1480, 680
    defs = marker("flow-arrow", INK) + marker("control-arrow", BLUE)
    body = text(740, 70, "controller", 22, BLUE, "700")
    body += text(740, 98, "observes outcomes and chooses the next action", 18, BLUE)
    body += f'<path d="M185 120 H1295" stroke="{BLUE}" stroke-width="1.7"/>'

    states = [95, 495, 895, 1295]
    actions = [220, 620, 1020]
    tasks = [345, 745, 1145]
    colors = ["#4f8f4a", "#d18a22", "#5566b8"]
    for i, sx in enumerate(states):
        body += state_glyph(sx, 300, MID if i in (0, 3) else colors[i-1], i)
    body += text(states[0], 362, "initial quantum state", 18, BLUE)
    body += text(states[-1], 362, "final state", 18, MUTED)

    for i, (ax, tx, color) in enumerate(zip(actions, tasks, colors), 1):
        # Unbroken stage pipeline, matching the logic of manuscript Fig. 1.
        body += f'<path d="M{states[i-1]+43} 300 H{ax-20}" stroke="{INK}" stroke-width="2" marker-end="url(#flow-arrow)"/>'
        body += f'<circle cx="{ax}" cy="300" r="19" fill="{CREAM}" stroke="{INK}" stroke-width="1.6"/>{text(ax,307,f"A{i}",16,ORANGE,"700")}'
        body += text(ax, 350, "action", 16, MUTED)
        body += f'<path d="M{ax+21} 300 H{tx-50}" stroke="{INK}" stroke-width="2" marker-end="url(#flow-arrow)"/>'
        # Task instrument: compact ring, no unexplained box.
        body += f'<circle cx="{tx}" cy="300" r="48" fill="{PAPER}" stroke="{INK}" stroke-width="1.7"/><circle cx="{tx}" cy="300" r="34" fill="none" stroke="{color}" stroke-width="3"/>{text(tx,307,f"T{i}",18,color,"700")}'
        body += text(tx, 370, f"task {i}", 18, color)
        body += f'<path d="M{tx+50} 300 H{states[i]-44}" stroke="{INK}" stroke-width="2" marker-end="url(#flow-arrow)"/>'
        # Outcome branches return to the controller; reward descends to cumulative sum.
        body += f'<path d="M{tx} 251 C{tx-5} 220 {tx-27} 205 {tx-27} 174 M{tx} 251 C{tx+5} 220 {tx+27} 205 {tx+27} 174" fill="none" stroke="{MID}" stroke-width="1.6" stroke-dasharray="6 5"/>'
        body += f'<circle cx="{tx-27}" cy="166" r="5" fill="{PAPER}" stroke="{MID}" stroke-width="1.5"/><circle cx="{tx+27}" cy="166" r="5" fill="{PAPER}" stroke="{MID}" stroke-width="1.5"/><path d="M{tx-27} 160 V128 M{tx+27} 160 V128" stroke="{MID}" stroke-width="1.6" stroke-dasharray="6 5" marker-end="url(#control-arrow)"/>'
        body += text(tx+66, 194, f"outcome y{i}", 15, MUTED, anchor="start")
        body += f'<path d="M{tx} 349 V461" stroke="{ORANGE}" stroke-width="1.8"/><circle cx="{tx}" cy="478" r="18" fill="{CREAM}" stroke="{INK}" stroke-width="1.5"/>{text(tx,485,f"R{i}",16,ORANGE,"700")}'
        # Controller chooses this stage's action.
        body += f'<path d="M{ax} 120 V273" stroke="{BLUE}" stroke-width="1.6" stroke-dasharray="6 5" marker-end="url(#control-arrow)"/>'
        body += text((states[i-1]+states[i])/2, 410, f"stage {i}", 16, MUTED)

    body += f'<path d="M320 535 H1190" stroke="{RULE}" stroke-width="1.4"/>'
    body += text(545, 543, "+", 25, MUTED) + text(945, 543, "+", 25, MUTED)
    body += f'<path d="M1190 535 H1260" stroke="{INK}" stroke-width="2" marker-end="url(#flow-arrow)"/>{text(1280,542,"cumulative reward",20,ORANGE,"700",anchor="start")}'
    body += text(w/2, 615, "The controller balances each stage's reward against the state left for later tasks.", 21, MUTED)
    (OUT / "figure2-quantum-tasks.svg").write_text(svg(w, h, "A manuscript-inspired three-stage quantum decision process. At each stage a controller selects an action, a task transforms the quantum state, random outcomes return to the controller, and stage rewards add to a cumulative reward.", body, defs))


def figure3():
    """One continuous map: full coordinates -> reward filter -> effective coordinates -> actions."""
    w, h = 1440, 740
    defs = marker("reduce-arrow", INK)
    body = text(75, 90, "1", 20, BLUE, "700") + text(103, 90, "full state", 21, INK, "700", anchor="start")
    # Twelve coordinates: three coloured directions will matter to future rewards.
    ys = [165 + i * 30 for i in range(12)]
    relevant = {2: MID, 6: ORANGE, 9: BLUE}
    for i, y in enumerate(ys):
        color = relevant.get(i, RULE)
        sw = 3.5 if i in relevant else 1.6
        body += f'<path d="M105 {y} C205 {y-12} 305 {y+12} 405 {y}" fill="none" stroke="{color}" stroke-width="{sw}"/>'
    body += f'<path d="M75 135 Q255 108 435 135 V525 Q255 552 75 525Z" fill="none" stroke="{INK}" stroke-width="1.5"/>'
    body += text(255, 585, "many state-space directions", 19, MUTED)

    body += f'<path d="M445 330 H515" stroke="{INK}" stroke-width="2" marker-end="url(#reduce-arrow)"/>'
    body += text(610, 90, "2", 20, BLUE, "700") + text(638, 90, "future-reward filter", 21, INK, "700", anchor="start")
    # Filter explicitly connects left and right: grey directions stop, coloured pass.
    body += f'<path d="M545 150 L690 150 L740 330 L690 510 L545 510Z" fill="{CREAM}" fill-opacity=".42" stroke="{INK}" stroke-width="1.7"/>'
    body += text(628, 255, "which directions", 18) + text(628, 282, "can change", 18) + text(628, 309, "future rewards?", 18)
    for i, y in enumerate(ys):
        if i not in relevant:
            body += f'<path d="M545 {y} H585" stroke="{RULE}" stroke-width="1.6"/><circle cx="592" cy="{y}" r="3.5" fill="{RULE}"/>'
    out_y = [245, 330, 415]
    for (idx, color), oy in zip(relevant.items(), out_y):
        iy = ys[idx]
        body += f'<path d="M405 {iy} C480 {iy} 500 {oy} 545 {oy} M690 {oy} H805" fill="none" stroke="{color}" stroke-width="3.5"/>'
    body += f'<path d="M752 330 H825" stroke="{INK}" stroke-width="2" marker-end="url(#reduce-arrow)"/>'

    body += text(855, 90, "3", 20, BLUE, "700") + text(883, 90, "effective coordinates", 21, INK, "700", anchor="start")
    for oy, color in zip(out_y, [MID, ORANGE, BLUE]):
        body += f'<path d="M825 {oy} C905 {oy-20} 965 {oy+20} 1045 {oy}" fill="none" stroke="{color}" stroke-width="4"/><circle cx="1055" cy="{oy}" r="8" fill="{color}" stroke="{INK}" stroke-width="1.2"/>'
    body += text(940, 480, "three retained directions", 19, MUTED)

    body += f'<path d="M1070 330 H1125" stroke="{INK}" stroke-width="2" marker-end="url(#reduce-arrow)"/>'
    body += text(1160, 90, "4", 20, BLUE, "700") + text(1188, 90, "smaller action search", 21, INK, "700", anchor="start")
    actions = [(1325, 245), (1325, 330), (1325, 415)]
    for (ax, ay), color in zip(actions, [MID, ORANGE, BLUE]):
        body += f'<path d="M1135 330 Q1215 {ay} {ax-27} {ay}" fill="none" stroke="{INK}" stroke-width="1.8"/>'
        fill, stroke = (CREAM, ORANGE) if ay == 330 else (PAPER, INK)
        body += f'<circle cx="{ax}" cy="{ay}" r="22" fill="{fill}" stroke="{stroke}" stroke-width="{2.4 if ay==330 else 1.6}"/>{text(ax,ay+7,"A",18,stroke,"700")}'
    body += text(1240, 480, "near-optimal action", 19, ORANGE)

    body += f'<path d="M110 625 H1330" stroke="{RULE}" stroke-width="1.4"/>'
    body += text(w/2, 675, "Keep only directions that can affect future rewards, then search for actions in that smaller space.", 21, MUTED)
    (OUT / "figure3-effective-dimension.svg").write_text(svg(w, h, "A continuous four-step effective-dimension diagram. Twelve full-state directions enter a future-reward filter; irrelevant grey directions stop, three coloured directions pass through as effective coordinates, and these support a smaller search over candidate actions.", body, defs))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    figure1(); figure2(); figure3()

#!/usr/bin/env python3
"""Rebuild the autumn campus SVG and spot artwork (Python standard library only).

This is an illustrated interpretation, not a measured architectural elevation.
Photo references and artwork notes are documented in docs/assets/README.md.
"""
from pathlib import Path
import random

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
INK = "#182332"
CREAM = "#ffe4b8"
BLUE = "#2449ae"
MID = "#5978c3"
LIGHT = "#91a8dd"
DARK = "#203946"
ORANGE = "#ff8b20"
GOLD = "#e3ae45"
AMBER = "#d88035"
RUST = "#b84f36"
BURGUNDY = "#783b38"
parts = []


def add(s):
    parts.append(s)


def path(d, fill="none", stroke=INK, width=1.8, extra=""):
    add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" {extra}/>')


def poly(points, fill, stroke=INK, width=1.8, extra=""):
    add(f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" {extra}/>')


def rect(x, y, w, h, fill, stroke=INK, width=1.5, extra=""):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" {extra}/>')


def circle(x, y, r, fill, stroke=INK, width=1.5):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')


def group(transform="", extra=""):
    add(f'<g transform="{transform}" {extra}>')


def end():
    add('</g>')


def window(x, y, w=30, h=43, tilt=0, lit=False):
    group(f'translate({x} {y}) skewY({tilt})')
    poly(f'0,0 {w},0 {w+6},5 6,5', '#fcf1d9', width=1)
    poly(f'{w},0 {w+6},5 {w+6},{h+5} {w},{h}', '#536682', width=1)
    rect(0, 0, w, h, '#e9e4d9', width=1.1)
    rect(4, 4, w-8, h-8, '#ffe083' if lit else '#203c59', width=.7)
    path(f'M{w/2} 4 V{h-4}', stroke='#fff3bb' if lit else '#c6daf1', width=1.7)
    path(f'M5 5 H{w-5} V{h/2}', stroke='#fff3bb' if lit else '#527cb3', width=1)
    path(f'M-2 {h+2} H{w+4}', stroke=INK, width=1.8)
    end()


def windows(x, y, cols, rows, dx, dy, w=28, h=39, tilt=0, lit_windows=()):
    """Draw a grid; lit_windows contains zero-based (row, column) positions."""
    for row in range(rows):
        for col in range(cols):
            window(x+col*dx, y+row*dy, w, h, tilt, lit=(row, col) in lit_windows)


def tree(x, y, scale=1, color=MID):
    group(f'translate({x} {y}) scale({scale})')
    path('M-17 6 Q-3 -28 -8 -83 L-39 -129 -32 -137 -4 -107 1 -160 9 -161 13 -118 42 -147 48 -137 14 -96 19 -17 35 7 Z', DARK)
    path('M-103 -110 C-119 -135 -99 -167 -79 -165 C-87 -195 -56 -214 -31 -204 C-9 -242 35 -223 42 -201 C80 -213 98 -185 91 -163 C129 -145 111 -110 89 -108 C68 -87 46 -101 33 -95 C4 -87 -18 -95 -32 -97 C-53 -83 -91 -88 -103 -110Z', color)
    path('M-66 -162 Q-37 -146 -10 -121 M44 -175 Q25 -152 15 -126', stroke=INK, width=1.1)
    end()


def autumn_leaf(x, y, scale=1, angle=0, color=GOLD):
    group(f'translate({x} {y}) rotate({angle}) scale({scale})')
    path('M-12 0Q-5 -11 13 -5Q9 9 -3 7Q-9 6 -12 0Z', color, width=1)
    path('M-16 4L8 -3 M-3 0L-4 -5 M2 -1L5 3', width=.7)
    end()


def person(x, y, scale=1, shirt=ORANGE, pose="walk"):
    group(f'translate({x} {y}) scale({scale})')
    if pose == 'sit':
        path('M-7 -24 L-14 -5 9 0 38 -3 39 -8 13 -9 7 -19Z', MID, width=1.5)
        path('M-7 -47 Q-15 -35 -11 -22 L9 -18 12 -37 4 -48Z', shirt, width=1.5)
        path('M5 -39 L17 -25 28 -25', stroke=CREAM, width=4)
        circle(-1, -55, 7, CREAM, width=1)
        path('M-8 -57 Q-7 -66 0 -63 L6 -60', DARK, width=1)
        poly('11,-25 29,-25 33,-14 16,-14', '#dfded0', width=1)
    else:
        path('M-8 -33 L-5 -14 -12 9 -7 11 3 -9 9 10 15 10 10 -15 8 -34Z', DARK, width=1.5)
        path('M-8 -62 Q0 -67 10 -60 L15 -34 Q2 -28 -13 -34 L-15 -51Z', shirt, width=1.5)
        circle(0, -72, 8, CREAM, width=1.2)
        path('M-7 -76 Q-3 -85 5 -79 L9 -73 -3 -75Z', DARK, width=1)
        path('M-12 -55 L-20 -39 -15 -27 M11 -56 L17 -41 26 -37', stroke=INK, width=5)
        path('M-12 -55 L-20 -39 -15 -27 M11 -56 L17 -41 26 -37', stroke=CREAM, width=3)
        path('M-12 11 H-3 M9 12 H19', stroke=INK, width=3)
    end()


def start(w, h, title, desc, viewbox=None):
    parts.clear()
    vb = viewbox or f'0 0 {w} {h}'
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}" role="img" aria-labelledby="title desc">')
    add(f'<title id="title">{title}</title><desc id="desc">{desc}</desc>')


def save(name):
    add('</svg>')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text('\n'.join(parts) + '\n')


def campus():
    start(6144, 2304, 'Autumn at Stata Center and Hockfield Court — an illustrated interpretation',
          'A panoramic ink-and-color drawing of MIT’s Stata Center in autumn, with golden, amber, and rust-red trees, '
          'fallen leaves on an ochre lawn, students, quantum diagrams, and a red steel interpretation of Mark di Suvero’s Aesop’s Fables, II.',
          '0 0 2560 960')
    add('''<defs>
      <pattern id="brick" width="28" height="12" patternUnits="userSpaceOnUse">
        <path d="M0 0H28M0 6H28M14 0V6M0 6V12M28 6V12" fill="none" stroke="#804c36" stroke-width=".65" opacity=".26"/>
      </pattern>
      <pattern id="metal" width="38" height="38" patternUnits="userSpaceOnUse" patternTransform="rotate(36)">
        <path d="M0 0H38V38" fill="none" stroke="#4a638c" stroke-width=".7" opacity=".5"/>
      </pattern>
      <filter id="paper" x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency=".7" numOctaves="3" seed="12" stitchTiles="stitch"/>
        <feColorMatrix type="saturate" values="0"/>
      </filter>
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M0 0L10 5 0 10Z" fill="#182332"/>
      </marker>
    </defs>''')
    group(extra='stroke-linejoin="round" stroke-linecap="round"')
    rect(0, 0, 2560, 960, '#e8d9c2', stroke='none')
    # Thin drifting clouds leave the architecture clear.
    path('M280 248 Q350 229 414 244 M900 64 Q986 45 1060 67 M1930 322 Q2044 297 2155 313', stroke='#fff1d9', width=2)

    # Small quantum-information motifs, arranged in the open sky.
    group('translate(645 83) rotate(-4)')
    path('M0 62H313 M0 108H313', stroke=INK, width=1.6)
    for x, y, color in [(32,62,ORANGE),(91,108,CREAM),(204,62,BLUE),(279,108,ORANGE)]:
        circle(x, y, 8, color)
    for x in [75, 151, 250]:
        rect(x, 45, 31, 33, CREAM if x != 151 else LIGHT)
    path('M151 62V108', width=1.5)
    circle(151, 108, 12, 'none')
    path('M143 108H159 M151 100V116', width=1.2)
    path('M86 52V69 M96 52V69 M86 60H96 M258 55L274 70 M274 55L258 70', width=1.5)
    end()
    group('translate(1900 93) rotate(8)')
    circle(0, 0, 68, '#9aafe0')
    add('<ellipse cx="0" cy="0" rx="68" ry="23" fill="none" stroke="#182332" stroke-width="1.3"/>')
    add('<ellipse cx="0" cy="0" rx="26" ry="68" fill="none" stroke="#182332" stroke-width="1.3"/>')
    path('M0 84V-87 M-83 0H87 M-48 48L51 -51', width=1.3, extra='marker-end="url(#arrow)"')
    path('M0 0L43 -47', width=2.3)
    circle(43, -47, 6, ORANGE)
    end()
    group('translate(2132 161)')
    poly('0,-72 90,-28 73,61 -17,82 -67,11', '#ffa334')
    poly('0,-72 -7,7 90,-28', '#ffd28d')
    poly('-7,7 73,61 -17,82', '#ffb451')
    poly('-7,7 -67,11 0,-72', '#ff9016')
    path('M-7 7L73 61 M-7 7L-17 82', width=1.3)
    end()
    path('M988 197 C1009 181 1020 210 1038 182 S1066 141 1080 171 1109 205 1123 156 1151 139 1161 158', width=1.6, extra='marker-end="url(#arrow)"')
    for x, y, r, c in [(1030,105,6,ORANGE),(1090,75,4,CREAM),(1774,87,5,BLUE),(2249,54,10,ORANGE)]:
        circle(x,y,r,c)

    # Distant laboratory wings and the terrace along the back of the court.
    poly('193,550 357,533 379,667 180,683', '#f2d4a5')
    poly('2020,487 2256,473 2375,516 2375,682 1998,683', '#f2e5cb')
    poly('2020,487 2234,462 2369,506 2256,498', '#9daed0')
    for x in range(2040,2350,37):
        rect(x, 539, 22, 80, '#3d557b', width=1)
        path(f'M{x+11} 539V619 M{x} 576H{x+22}', stroke='#c4d2e7', width=1)
    path('M2003 530H2372 M2000 638H2372', stroke=INK, width=2)

    # Left brick tower: distinct warm wall, side plane, and regularly spaced windows.
    group('translate(330 322) skewY(2)')
    poly('0,0 204,0 211,331 0,341', '#e6a367')
    poly('204,0 244,23 250,323 211,331', '#ba6d3b')
    poly('0,0 204,0 211,331 0,341', 'url(#brick)', stroke='none')
    windows(24,42,3,4,58,70,29,43,lit_windows=((2, 0),))
    end()
    # Silver cylindrical volume with visible panel seams and projecting windows.
    path('M536 366 C571 341 629 342 659 369 L680 650 Q605 679 538 652Z', '#c5d1df')
    path('M615 350 Q643 355 659 369 L680 650 637 661Z', '#8c9ec5', width=1.3)
    path('M536 366 C571 341 629 342 659 369 L680 650 Q605 679 538 652Z', 'url(#metal)', stroke='none')
    windows(554,400,2,3,56,72,25,40)
    # Back gold tower and connecting glass bridge.
    poly('694,395 828,369 872,643 712,655', '#e6b465')
    poly('828,369 876,394 907,624 872,643', '#c18a42')
    windows(716,427,2,3,61,67,28,39,-5)
    poly('641,392 699,404 711,565 658,550', '#496d99')
    for x in [650,665,680,695]:
        path(f'M{x} 404L{x+12} 554', stroke='#b1c3df', width=1)
    for y in [431,465,501,537]:
        path(f'M650 {y}L704 {y+10}', stroke='#bed0e8', width=1)
    # Sculptural, slanted lower volumes: silver folded surfaces and yellow drum.
    poly('822,545 914,471 1029,521 1035,664 819,664', '#f1eadb')
    poly('914,471 928,582 894,665 1035,664 1029,521', '#a9bbd6')
    poly('822,545 914,471 1029,521 1035,664 819,664', 'url(#metal)', stroke='none')
    path('M945 607 Q930 540 972 449 Q1003 430 1036 442 L1065 652 985 680Z', '#ffd349')
    path('M972 449 Q1003 467 1036 442 M966 488L1041 471 M951 534L1049 506 M949 578L1055 549 M960 623L1060 592', stroke='#a9792c', width=1)
    path('M1031 442 Q1009 563 1038 660L1065 652Z', '#eea530')
    # Mid-ground brick wedge and dark glazed entrance.
    poly('729,554 810,529 839,659 720,674', '#d89557')
    poly('729,554 810,529 839,659 720,674', 'url(#brick)', stroke='none')
    poly('778,586 822,573 833,646 787,658', '#263c58')
    path('M792 582L804 654 M808 578L818 650', stroke='#b6c6da', width=1)

    # The tall central cluster: angled stainless-steel façade to the left.
    poly('1076,280 1192,226 1280,646 1150,673', '#e4e7e4')
    poly('1076,280 1192,226 1280,646 1150,673', 'url(#metal)', stroke='none')
    poly('1192,226 1240,252 1325,629 1280,646', '#829abb')
    poly('1050,359 1094,311 1159,562 1119,584', '#b8cbe1')
    group('translate(1103 302) rotate(-10)')
    windows(0,0,1,4,0,76,36,49)
    end()
    group('translate(1183 292) rotate(-7)')
    windows(0,0,1,4,0,77,32,49)
    end()
    # Main brick slab, deliberately tall so Stata is the subject, not scenery.
    poly('1240,173 1466,203 1500,653 1278,679', '#e5a16b')
    poly('1240,173 1209,201 1249,665 1278,679', '#b97248')
    poly('1240,173 1466,203 1500,653 1278,679', 'url(#brick)', stroke='none')
    group('translate(1268 234) matrix(1 .12 .065 1 0 0)')
    windows(0,0,3,5,63,73,33,46)
    end()
    # Stepped lower brick façade preserves the characteristic setback.
    poly('1286,538 1507,542 1517,686 1294,698', '#dc9258')
    poly('1286,538 1507,542 1517,686 1294,698', 'url(#brick)', stroke='none')
    windows(1320,566,3,1,65,0,33,51)
    # Right steel tower, with a leaning roof and staggered projections.
    poly('1466,268 1595,239 1653,633 1501,653', '#d8e3e9')
    poly('1595,239 1648,272 1695,618 1653,633', '#839bc2')
    poly('1466,268 1595,239 1653,633 1501,653', 'url(#metal)', stroke='none')
    group('translate(1490 306) rotate(-6)')
    windows(0,0,2,4,63,77,31,44)
    end()
    # Rear stepped brick block and a further tilted silver form.
    poly('1648,297 1794,310 1816,681 1672,675', '#d59864')
    poly('1648,297 1794,310 1816,681 1672,675', 'url(#brick)', stroke='none')
    windows(1674,344,2,4,67,77,32,45)
    poly('1789,403 1907,365 1959,662 1820,684', '#dde3de')
    poly('1907,365 1961,409 1991,650 1959,662', '#8fadd0')
    poly('1789,403 1907,365 1959,662 1820,684', 'url(#metal)', stroke='none')
    group('translate(1821 439) rotate(-7)')
    windows(0,0,2,3,62,70,29,39)
    end()
    # Low lobby and broad steps towards Hockfield Court.
    poly('1044,631 1269,647 1294,698 1039,700', '#f2d0a0')
    poly('1057,651 1248,662 1250,697 1054,697', '#243b56')
    for x in range(1068,1250,22):
        path(f'M{x} 654V696', stroke='#bfd0e5', width=1)
    poly('1294,668 1634,660 1674,723 1227,735', '#ead3af')
    for y in range(677,724,8):
        path(f'M{1285-(y-677)*1.1} {y}L{1641+(y-677)*.55} {y-4}', stroke='#897c74', width=1)
    path('M1280 689L1232 724 M1639 686L1660 713', stroke=INK, width=2)
    # Dry autumn lawn and gently converging walking paths.
    path('M0 704 Q353 676 607 704 T1165 716 Q1684 698 1974 696 T2560 711 L2560 960H0Z', '#bba16b')
    path('M0 725 Q421 704 805 732 T1520 730 Q2130 703 2560 740L2560 760 Q2041 733 1560 749T746 749Q342 723 0 744Z', '#cdd0ca', width=1)
    path('M1261 728L1302 729 876 960H665Z', '#d4d1c7', width=1)
    path('M1568 735L1605 733 2396 960H2198Z', '#d4d1c7', width=1)
    # Fallen leaves remain visible even when the decorative animation is disabled.
    leaves = random.Random(23)
    for _ in range(85):
        autumn_leaf(leaves.randint(180, 2500), leaves.randint(720, 952),
                    leaves.uniform(.28, .65), leaves.randint(-180, 180),
                    leaves.choice([GOLD, AMBER, RUST, BURGUNDY]))
    # Autumn trees at the terrace, open enough to keep the facades legible.
    for x,y,s,c in [(256,702,.92,AMBER),(372,713,.68,RUST),(563,703,.62,GOLD),(708,716,.58,AMBER),
                    (930,714,.52,RUST),(1123,718,.5,GOLD),(1768,711,.72,AMBER),(1927,709,.75,RUST),
                    (2065,715,.94,GOLD),(2277,716,1.02,AMBER),(2440,731,1.16,RUST)]:
        tree(x,y,s,c)
    # Benches and characteristic inverted-cone lamps.
    for x,y in [(420,722),(695,730),(2038,731),(2240,741)]:
        group(f'translate({x} {y})')
        path('M0 0V-9H68V1 M5 -5V7 M63 -5V7 M-3 -3H72', stroke=INK, width=2)
        path('M0 -13H68 M0 -9H68', stroke=CREAM, width=3)
        end()
    for x,y in [(775,706),(1714,699),(2180,713)]:
        path(f'M{x} {y}V{y-112}', stroke=INK, width=3)
        poly(f'{x-14},{y-114} {x+14},{y-114} {x+4},{y-104} {x-4},{y-104}', DARK, width=1)

    # Aesop’s Fables, II: red I-beams, crossed supports and a twisting ring.
    group('translate(1340 650) scale(.86)')
    path('M-66 181Q112 159 351 183L456 215 142 231 -91 200Z', '#998358', stroke='none')
    poly('273,17 293,17 393,190 373,194', '#9c3543')
    poly('373,194 393,190 400,192 380,198', '#682d40', width=1)
    poly('-22,180 1,186 115,8 96,2', '#c74648')
    poly('1,186 7,189 122,9 115,8', '#7d3041', width=1)
    poly('39,-26 44,-8 328,7 329,-11', '#c24447')
    poly('39,-26 47,-30 337,-16 329,-11', '#ef7361', width=1)
    poly('329,-11 337,-16 336,3 328,7', '#762b3c', width=1)
    poly('292,186 313,189 281,3 261,3', '#d24b4f')
    poly('313,189 321,186 289,0 281,3', '#9e3443', width=1)
    poly('232,183 249,185 333,-12 315,-16', '#c64a4d')
    poly('249,185 256,184 340,-11 333,-12', '#8c2e40', width=1)
    poly('-56,26 -42,16 146,209 126,212', '#ce4b51')
    poly('-42,16 -34,17 155,209 146,209', '#ef7265', width=1)
    poly('33,-13 54,-17 91,181 71,191', '#b93547')
    # A non-circular, ribbon-like steel loop rather than an invented statue.
    path('M23 31C70 -25 122 29 98 82C83 118 29 101 40 139C50 169 85 172 87 187C28 190 -20 144 6 109C28 81 77 78 72 49C69 28 46 35 34 51Z', '#cc4650')
    path('M23 31C70 -25 122 29 98 82 M6 109C-13 146 29 184 87 187', stroke='#f67c69', width=3)
    path('M40 139Q46 165 71 165L87 187 M35 50Q48 42 57 43', stroke='#782c41', width=4)
    poly('44,135 55,118 170,200 198,216 159,211', '#b13947')
    poly('55,118 64,119 198,212 198,216', '#ed7762', width=1)
    end()

    # Small, hand-outlined students animate the court without obscuring the subject.
    for args in [(473,759,.40,CREAM),(827,740,.32,ORANGE),(1003,761,.46,BLUE),
                 (1746,762,.40,CREAM),(1856,811,.67,ORANGE),(1949,805,.58,BLUE),
                 (644,827,.57,CREAM),(2160,839,.73,ORANGE)]:
        person(*args)
    for args in [(955,853,.8,ORANGE),(1012,858,.75,CREAM),(1638,876,.8,CREAM),
                 (1701,884,.75,BLUE),(481,787,.51,ORANGE),(2065,772,.4,CREAM)]:
        person(*args,pose='sit')
    # Foreground observer at left; the building remains entirely unobstructed.
    person(335,909,1.78,BLUE)
    path('M316 788L340 814 361 801', stroke=INK, width=2)
    # Fine, sparse grass marks give the lawn an ink-drawn rhythm.
    rng = random.Random(8)
    for _ in range(140):
        x,y = rng.randint(100,2490),rng.randint(756,950)
        if 1210 < x < 1710 and y < 850:
            continue
        path(f'M{x} {y}l3 -5m1 5 4 -3', stroke='#8c774d', width=.7)

    # Autumn framing tree, asymmetric organic foliage and fine bark lines.
    path('M0 0H499Q530 40 500 66T399 103Q341 159 274 148Q225 202 125 171Q49 206 0 167Z', RUST)
    path('M0 191Q47 142 126 171Q163 208 123 247Q70 272 0 253Z', GOLD)
    path('M0 105Q78 61 144 89Q193 108 170 163Q110 196 51 180L0 192Z', BURGUNDY)
    path('M39 792Q112 677 99 457L123 220 90 163 73 72 90 66 128 142 154 41 171 39 159 175 199 127 253 92 260 105 202 161 162 236 151 433Q154 678 116 809Z', '#142830')
    path('M140 328Q203 239 295 218L313 229Q211 267 151 383Z', '#142830')
    path('M262 217Q316 189 351 221Q408 191 438 224Q477 249 444 278Q419 300 373 286Q313 315 284 279Q236 279 243 243Z', AMBER)
    for x, y, angle, color in [(471, 166, 35, GOLD), (211, 327, -45, RUST),
                               (380, 379, 70, AMBER), (2337, 555, -20, GOLD)]:
        autumn_leaf(x, y, .8, angle, color)
    for i in range(15):
        x=70+i*5
        path(f'M{x} 759Q{x+31} 626 {x+22} 458', stroke='#35536c', width=.9)
    # Lower foreground foliage gives the drawing a full-bleed, editorial frame.
    path('M0 844Q109 806 193 849Q244 841 292 875Q375 875 413 921Q598 909 749 960H0Z', BURGUNDY)
    path('M2222 960Q2258 892 2327 908Q2335 853 2411 866Q2463 811 2560 838V960Z', RUST)
    path('M2440 960L2434 882 M2436 930L2380 904 M2437 920L2491 870 M2436 910L2410 871 M2438 949L2530 910', stroke=INK, width=3)
    for x,y in [(91,939),(171,960),(226,942)]:
        path(f'M{x} {y}q-30 -87 -74 -93q25 59 74 93q-7 -78 25 -120q14 78 -25 120Z', AMBER)
        path(f'M{x} {y}l-51 -69 M{x} {y}l19 -91', stroke=INK, width=1)
    end()
    # Subtle print grain; all architecture and outlines above remain vectors.
    rect(0,0,2560,960,'#fff',stroke='none',extra='filter="url(#paper)" opacity=".045" pointer-events="none"')
    save('stata-center.svg')


def spots():
    start(300,250,'Quantum research','An ink-drawn quantum sphere, a decision graph and a notebook.')
    group(extra='stroke-linejoin="round" stroke-linecap="round"')
    path('M28 211Q152 186 268 215L232 227 58 228Z', '#ebedf5', stroke='none')
    poly('37,175 133,149 234,183 143,218', CREAM)
    path('M143 218V226L37 184V175 M143 226L234 192V183', '#f0ba77')
    path('M134 155L143 210 M59 177L105 166 M73 187L112 176 M164 172L208 187', stroke=INK, width=1.3)
    circle(183,86,57,LIGHT)
    add('<ellipse cx="183" cy="86" rx="57" ry="19" fill="none" stroke="#182332" stroke-width="1.5"/>')
    add('<ellipse cx="183" cy="86" rx="23" ry="57" fill="none" stroke="#182332" stroke-width="1.5"/>')
    path('M183 22V149 M119 86H247 M183 86L210 46', width=1.4)
    circle(210,46,6,ORANGE)
    path('M42 60H89V116H48 M89 60L105 41', width=1.5)
    for x,y,c in [(42,60,BLUE),(89,60,ORANGE),(89,116,CREAM),(48,116,MID),(105,41,CREAM)]:
        circle(x,y,9,c)
    end()
    save('research.svg')

    start(300,250,'The research notebook','A blue notebook, a pencil and a trail of steps.')
    group(extra='stroke-linejoin="round" stroke-linecap="round"')
    path('M39 222Q119 195 257 213L252 228 48 235Z', '#ebedf5', stroke='none')
    poly('60,53 180,35 220,204 99,226', BLUE)
    poly('71,53 179,39 217,199 108,218', '#c4d2eb')
    poly('81,44 188,29 222,191 109,210', CREAM)
    for y in range(73,178,20):
        path(f'M104 {y}l74 -12', stroke='#8d9abb', width=1.5)
    for y in range(63,193,22):
        path(f'M76 {y}q-14 -3 -12 5q0 10 16 5', stroke=INK, width=2)
    poly('224,53 234,55 204,178 192,194 192,175', ORANGE)
    poly('192,175 204,178 192,194', CREAM)
    path('M192 189L192 194 197 189 M229 56L199 176', width=1)
    path('M37 85Q12 115 42 155 M241 145Q281 133 269 92', stroke=INK, width=1.5, extra='stroke-dasharray="3 6"')
    circle(38,77,7,ORANGE)
    circle(268,86,7,MID)
    end()
    save('notebook.svg')

    start(300,250,'Notes beyond research','A coffee cup, an open book and a blue-leafed plant.')
    group(extra='stroke-linejoin="round" stroke-linecap="round"')
    path('M25 215Q141 198 271 212L244 229 42 231Z', '#ebedf5', stroke='none')
    poly('35,189 108,173 161,190 217,180 269,205 168,231', '#a1b5df')
    path('M35 185L107 168Q140 167 160 185Q180 167 216 174L266 200Q204 185 168 222Q112 194 35 185Z', CREAM)
    path('M160 185L168 222 M63 182L128 188 M183 188L220 187 M93 177L133 180', width=1)
    path('M169 159L161 113 212 111 202 161Z', '#f0ab4c')
    path('M185 114Q173 79 190 37 M185 98Q213 72 225 59', stroke=INK, width=2)
    path('M186 83Q150 80 156 52Q185 53 186 83 M188 60Q178 27 204 23Q216 49 188 60 M201 83Q209 50 236 55Q236 80 201 83', MID)
    path('M206 77L224 63 M183 76L164 61 M192 54L201 31', width=1)
    path('M92 125Q119 116 119 138Q117 160 98 153', ORANGE, width=5)
    path('M42 111L50 163Q72 182 96 161L103 110Z', ORANGE)
    add('<ellipse cx="72" cy="111" rx="31" ry="10" fill="#ffe4b8" stroke="#182332" stroke-width="1.8"/>')
    add('<ellipse cx="72" cy="113" rx="24" ry="5" fill="#67473c"/>')
    path('M62 93Q49 80 61 66T62 42 M82 94Q96 83 83 68', width=1.3)
    end()
    save('coffee.svg')


if __name__ == '__main__':
    campus()
    spots()
    print('Rebuilt docs/assets/stata-center.svg and three spot illustrations.')

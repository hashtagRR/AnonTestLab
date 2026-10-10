"""Generate the README overview figure (SVG) for AnonTestLab.

Usage: python docs/img/make_overview.py docs/img

Writes anontestlab-overview.svg. The three stage colours are categorical
slots 1 to 3 of the shared data-viz palette, checked for colour-vision
deficiency; text always uses the neutral ink colours, never a stage colour.
"""

import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

THEMES = {
    "light": {
        "bg": "#ffffff",
        "card": "#f6f8fa",
        "chip": "#ffffff",
        "line": "#d0d7de",
        "fg": "#1f2328",
        "muted": "#59636e",
        "faint": "#8c959f",
        "net": "#2a78d6",
        "attack": "#eb6834",
        "result": "#1baf7a",
        "net_soft": "#e7f0fb",
        "attack_soft": "#fdeee8",
    },
}

W, H = 1576, 832
TOP, BOT = 196, 690  # shared top and bottom edge of the four stage cards
PAD = 22  # inner padding of every card
GAP = 40  # room for the arrow between two cards

INPUT = (48, 250)
NET = (INPUT[0] + INPUT[1] + GAP, 500)
ATTACK = (NET[0] + NET[1] + GAP, 350)
RESULT = (ATTACK[0] + ATTACK[1] + GAP, W - 48 - (ATTACK[0] + ATTACK[1] + GAP))

YAML = [
    ("mode", ": custom"),
    ("routing", ":"),
    ("  paths", ": 2"),
    ("  split_strategy", ": iid"),
    ("mixing", ":"),
    ("  strategy", ": exponential"),
    ("traffic", ":"),
    ("  distribution", ": burst"),
    ("adversary", ":"),
    ("  types", ": [correlation_suite]"),
]

# what a run can vary, one row of chips each
KNOBS = [
    ("Split", ["iid", "round-robin", "batch", "latency", "random"]),
    ("Mixing", ["constant", "exponential", "pool"]),
    ("Traffic", ["Poisson", "constant", "Pareto", "burst", "+ cover"]),
    ("Crypto", ["AES-GCM", "GCM-SIV", "OCB3", "ChaCha20-Poly1305"]),
    ("Keys", ["x25519", "x448", "p256"]),
    ("Links", ["latency", "jitter", "loss", "bandwidth"]),
]

# adversaries: name, kind badge, description
ATTACKS = [
    ("correlation_suite", "passive", "A0 to A3 correlators, with model predictions"),
    ("global_observer", "passive", "timing correlation, AS-level visibility"),
    ("watermark", "active", "injects a delay pattern, detects it later"),
    ("hop_depth", "passive", "hop position from the cell-size sequence"),
    ("path_compromise", "no packets", "Monte Carlo over the chosen paths"),
]

MEASURED = ["latency", "delivery", "bandwidth", "leg shares"]
SCORES = ["confident linkage", "TPR at fixed FPR", "AUC"]
FILES = ["metrics.csv", "report.md", "configuration.yaml", "seed.txt"]

TOOLS = [
    ("atl compare", "A against B"),
    ("atl sweep", "vary one field"),
    ("atl paired", "same seeds, CI"),
    ("atl predict", "closed-form model"),
    ("atl fidelity", "host-noise check"),
    ("atl dashboard", "local web UI"),
]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tw(s, size, mono=False):
    # rough text width: good enough to size chips around their labels
    return len(s) * size * (0.61 if mono else 0.56)


def text(x, y, s, size, fill, weight=400, family=FONT, anchor="start", spacing=None):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}>{esc(s)}</text>'
    )


def rect(x, y, w, h, fill, stroke=None, rx=10, dash=None):
    st = f' stroke="{stroke}"' if stroke else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"{st}{da}/>'


def chip(x, y, label, t, mono=False, size=12.5, dot=None, h=24):
    """A small rounded box around a label; returns (svg, width)."""
    w = tw(label, size, mono) + 18 + (12 if dot else 0)
    o = rect(x, y, w, h, t["chip"], t["line"], rx=6)
    tx = x + 9
    if dot:
        o += f'<circle cx="{x + 12:.1f}" cy="{y + h / 2:.1f}" r="3.5" fill="{dot}"/>'
        tx += 12
    o += text(tx, y + h / 2 + size * 0.36, label, size, t["fg"], family=MONO if mono else FONT)
    return o, w


def chip_row(x, y, labels, t, max_x, mono=False, dot=None, size=12.5, h=24, gap=6):
    """Lay chips left to right, wrapping at max_x; returns (svg, bottom y)."""
    o, cx, cy = [], x, y
    for lab in labels:
        w = tw(lab, size, mono) + 18 + (12 if dot else 0)
        if cx + w > max_x and cx > x:
            cx, cy = x, cy + h + gap
        s, w = chip(cx, cy, lab, t, mono=mono, size=size, dot=dot, h=h)
        o.append(s)
        cx += w + gap
    return "".join(o), cy + h


def stage_head(x, y, num, title, color, t):
    return (
        f'<circle cx="{x + 11}" cy="{y - 5}" r="11" fill="{color}"/>'
        + text(x + 11, y - 0.5, str(num), 12.5, "#ffffff", 700, anchor="middle")
        + text(x + 30, y, title, 13, t["fg"], 700, spacing="1.2")
    )


def stage_card(x, w, color, t):
    return rect(x, TOP, w, BOT - TOP, t["card"], t["line"]) + (
        f'<rect x="{x + 1}" y="{TOP + 1}" width="{w - 2}" height="4" rx="2" fill="{color}"/>'
    )


def arrow(x1, y1, x2, y2, t, dashed=False):
    dash = ' stroke-dasharray="6 6"' if dashed else ""
    return (
        f'<path d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}" stroke="{t["faint"]}" stroke-width="2"{dash} '
        'fill="none" marker-end="url(#ah)"/>'
    )


def input_stage(t):
    x, w = INPUT
    cx = x + PAD
    o = [
        stage_card(x, w, t["faint"], t),
        stage_head(cx, TOP + 38, 1, "CONFIGURE", t["faint"], t),
        text(cx, TOP + 64, "One YAML file describes the", 13.5, t["muted"]),
        text(cx, TOP + 82, "network, traffic and attackers.", 13.5, t["muted"]),
    ]
    # the config file, drawn as a small editor pane
    by, bh = TOP + 100, len(YAML) * 19 + 38
    o.append(rect(cx, by, w - 2 * PAD, bh, t["chip"], t["line"], rx=8))
    o.append(text(cx + 12, by + 20, "cfg.yaml", 11.5, t["muted"], family=MONO))
    o.append(f'<line x1="{cx}" y1="{by + 30}" x2="{x + w - PAD}" y2="{by + 30}" stroke="{t["line"]}"/>')
    for i, (k, v) in enumerate(YAML):
        y = by + 50 + i * 19
        o.append(
            f'<text x="{cx + 12}" y="{y}" font-family="{MONO}" font-size="12" xml:space="preserve">'
            f'<tspan fill="{t["net"]}">{esc(k)}</tspan><tspan fill="{t["fg"]}">{esc(v)}</tspan></text>'
        )
    # modes
    my = by + bh + 26
    o.append(text(cx, my, "Mode", 12, t["muted"], 700, spacing="0.8"))
    s, w1 = chip(cx, my + 8, "tor_like", t, mono=True)
    o.append(s)
    o.append(text(cx + w1 + 8, my + 25, "fixed 3-hop preset", 12, t["muted"]))
    s, w2 = chip(cx, my + 38, "custom", t, mono=True)
    o.append(s)
    o.append(text(cx + w2 + 8, my + 55, "every setting open", 12, t["muted"]))
    # command
    o.append(rect(cx, BOT - 54, w - 2 * PAD, 34, t["fg"], rx=8))
    o.append(text(cx + 12, BOT - 32, "$ atl run cfg.yaml", 13, t["bg"], family=MONO))
    return o


def node(x, y, label, t, stroke, fill, r=16):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>' + text(
        x, y + 4.2, label, 11.5, t["fg"], 700, anchor="middle"
    )


def edge(x1, y1, x2, y2, color, width=2, r=16):
    dx, dy = x2 - x1, y2 - y1
    n = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / n, dy / n
    return (
        f'<line x1="{x1 + ux * r:.1f}" y1="{y1 + uy * r:.1f}" x2="{x2 - ux * r:.1f}" y2="{y2 - uy * r:.1f}" '
        f'stroke="{color}" stroke-width="{width}"/>'
    )


def cells(x1, y1, x2, y2, color, n=3):
    # small squares along a link: the cells of the flow
    o = []
    for i in range(n):
        f = (i + 1) / (n + 1)
        cx, cy = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
        o.append(f'<rect x="{cx - 3.5:.1f}" y="{cy - 3.5:.1f}" width="7" height="7" rx="1.5" fill="{color}"/>')
    return "".join(o)


def network_stage(t):
    x, w = NET
    cx = x + PAD
    o = [
        stage_card(x, w, t["net"], t),
        stage_head(cx, TOP + 38, 2, "RUN A LIVE NETWORK", t["net"], t),
        text(cx, TOP + 64, "Each relay is a real OS process on its own 127.0.0.x, with real", 13.5, t["muted"]),
        text(cx, TOP + 82, "handshakes and per-hop encryption over real sockets.", 13.5, t["muted"]),
    ]
    # drawing panel: one session split over two legs that rejoin at the exit
    py, ph = TOP + 98, 164
    o.append(rect(cx, py, w - 2 * PAD, ph, t["chip"], t["line"], rx=8))
    ya, yb, ym = py + 62, py + 126, py + 94
    xs, xg, xm, xe, xd = cx + 40, cx + 130, cx + 220, cx + 318, cx + 410
    leg = t["net"]
    for a, b in [((xs, ym), (xg, ya)), ((xg, ya), (xm, ya)), ((xm, ya), (xe, ym))]:
        o.append(edge(*a, *b, leg, 2.5))
    for a, b in [((xs, ym), (xg, yb)), ((xg, yb), (xm, yb)), ((xm, yb), (xe, ym))]:
        o.append(edge(*a, *b, t["faint"], 2))
    o.append(edge(xe, ym, xd, ym, t["fg"], 2.5))
    o.append(cells(xg, ya, xm, ya, leg))
    o.append(cells(xg, yb, xm, yb, t["faint"]))
    o.append(cells(xe, ym, xd, ym, t["fg"], n=4))
    o += [
        node(xs, ym, "C", t, t["fg"], t["chip"]),
        node(xg, ya, "G1", t, leg, t["net_soft"]),
        node(xm, ya, "M1", t, leg, t["net_soft"]),
        node(xg, yb, "G2", t, t["faint"], t["card"]),
        node(xm, yb, "M2", t, t["faint"], t["card"]),
        node(xe, ym, "X", t, t["fg"], t["chip"]),
        node(xd, ym, "S", t, t["fg"], t["chip"]),
        text(xs, ym + 34, "client", 11.5, t["muted"], anchor="middle"),
        text(xd, ym + 34, "server", 11.5, t["muted"], anchor="middle"),
        text((xg + xm) / 2, ya - 11, "leg 1", 11.5, t["muted"], anchor="middle"),
        text((xg + xm) / 2, yb + 26, "leg 2", 11.5, t["muted"], anchor="middle"),
        text(xe, ym + 40, "common exit", 11.5, t["muted"], anchor="middle"),
    ]
    # observation points, in the attacker's colour
    for ox, oy, lab, anchor, lx in [
        (xg, ya, "observed entry", "middle", xg),
        (xe, ym, "observed merged exit", "middle", xe + 26),
    ]:
        o.append(
            f'<circle cx="{ox}" cy="{oy}" r="23" fill="none" stroke="{t["attack"]}" stroke-width="2" '
            'stroke-dasharray="4 3"/>'
        )
        ly = oy - 30
        o.append(text(lx, ly, lab, 11.5, t["fg"], 600, anchor=anchor))
    o.append(
        f'<circle cx="{cx + w - 2 * PAD - 128}" cy="{py + 18}" r="5" fill="none" stroke="{t["attack"]}" '
        'stroke-width="2" stroke-dasharray="3 2"/>'
    )
    o.append(text(cx + w - 2 * PAD - 118, py + 22, "adversary watches", 11, t["muted"]))
    # the knobs, as chips
    y = py + ph + 22
    for label, items in KNOBS:
        o.append(text(cx, y + 16.5, label, 12.5, t["fg"], 700))
        s, bottom = chip_row(cx + 66, y, items, t, x + w - PAD)
        o.append(s)
        y = bottom + 9
    return o


def attack_stage(t):
    x, w = ATTACK
    cx = x + PAD
    o = [
        stage_card(x, w, t["attack"], t),
        stage_head(cx, TOP + 38, 3, "ATTACK", t["attack"], t),
        text(cx, TOP + 64, "Pluggable adversaries; run one or several", 13.5, t["muted"]),
        text(cx, TOP + 82, "on the same traffic.", 13.5, t["muted"]),
    ]
    y, bw, bh = TOP + 98, w - 2 * PAD, 62
    for name, kind, desc in ATTACKS:
        o.append(rect(cx, y, bw, bh, t["chip"], t["line"], rx=8))
        o.append(f'<rect x="{cx}" y="{y + 8}" width="3" height="{bh - 16}" rx="1.5" fill="{t["attack"]}"/>')
        o.append(text(cx + 14, y + 23, name, 13, t["fg"], 700, family=MONO))
        kw = tw(kind, 10.5) + 14
        dash = "3 2" if kind == "no packets" else None
        fill = t["attack_soft"] if kind == "active" else t["chip"]
        o.append(rect(cx + bw - kw - 10, y + 10, kw, 18, fill, t["line"], rx=9, dash=dash))
        o.append(text(cx + bw - kw / 2 - 10, y + 22.5, kind, 10.5, t["muted"], 600, anchor="middle"))
        o.append(text(cx + 14, y + 46, desc, 12, t["muted"]))
        y += bh + 12
    return o


def result_stage(t):
    x, w = RESULT
    cx = x + PAD
    o = [
        stage_card(x, w, t["result"], t),
        stage_head(cx, TOP + 38, 4, "KEEP RESULTS", t["result"], t),
        text(cx, TOP + 64, "Every run is saved, so", 13.5, t["muted"]),
        text(cx, TOP + 82, "designs can be compared.", 13.5, t["muted"]),
        text(cx, TOP + 118, "Measured", 12, t["muted"], 700, spacing="0.8"),
    ]
    s, y = chip_row(cx, TOP + 128, MEASURED, t, x + w - PAD, dot=t["net"])
    o.append(s)
    o.append(text(cx, y + 30, "Attack scores", 12, t["muted"], 700, spacing="0.8"))
    s, y = chip_row(cx, y + 40, SCORES, t, x + w - PAD, dot=t["attack"])
    o.append(s)
    # output folder
    fy = y + 30
    o.append(text(cx, fy, "Files", 12, t["muted"], 700, spacing="0.8"))
    fy += 12
    fh = 32 + len(FILES) * 20
    o.append(rect(cx, fy, w - 2 * PAD, fh, t["chip"], t["line"], rx=8))
    o.append(text(cx + 12, fy + 22, "results/<name>/", 12, t["fg"], 700, family=MONO))
    for i, f in enumerate(FILES):
        yy = fy + 44 + i * 20
        o.append(f'<path d="M{cx + 18},{yy - 14} V{yy - 4} H{cx + 26}" stroke="{t["line"]}" fill="none"/>')
        o.append(text(cx + 30, yy, f, 12, t["muted"], family=MONO))
    return o


def tools_strip(t):
    y = BOT + 46
    o = [text(W / 2, y - 14, "COMPARE AND ITERATE", 12, t["muted"], 700, anchor="middle", spacing="1.2")]
    n = len(TOOLS)
    bw = (W - 96 - (n - 1) * 12) / n
    for i, (cmd, what) in enumerate(TOOLS):
        bx = 48 + i * (bw + 12)
        o.append(rect(bx, y, bw, 52, t["card"], t["line"], rx=8))
        o.append(text(bx + 14, y + 22, cmd, 13, t["fg"], 700, family=MONO))
        o.append(text(bx + 14, y + 41, what, 12, t["muted"]))
    # loop: results feed the tools, the tools feed the next config
    rx = RESULT[0] + RESULT[1] / 2
    ix = INPUT[0] + INPUT[1] / 2
    o.append(arrow(rx, BOT + 6, rx, y - 8, t))
    o.append(arrow(ix, y - 8, ix, BOT + 8, t, dashed=True))
    o.append(text(ix + 14, BOT + 30, "change one setting, rerun", 12, t["muted"]))
    return o


def figure(t):
    mid = TOP + 160
    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        'aria-label="AnonTestLab overview in four stages. 1 Configure: one YAML file, mode tor_like or '
        "custom, run with atl run. 2 Run a live network: real relay processes on one machine, a session "
        "split over two legs that rejoin at a common exit, with configurable split policy, mixing, traffic, "
        "crypto and link conditions; the adversary watches the entry and the merged exit. 3 Attack: "
        "correlation_suite, global_observer, watermark, hop_depth and path_compromise. 4 Keep results: "
        "measured latency, delivery, bandwidth and leg shares, attack scores, and a results folder. "
        'atl compare, sweep, paired, predict, fidelity and dashboard close the loop.">',
        f'<defs><marker id="ah" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{t["faint"]}"/></marker></defs>',
        f'<rect width="{W}" height="{H}" rx="12" fill="{t["bg"]}"/>',
        text(48, 62, "ANONTESTLAB", 13, t["net"], 700, spacing="1.5"),
        text(48, 100, "Does this anonymity design hide who talks to whom?", 32, t["fg"], 700),
        text(
            48,
            132,
            "Run the design as a real network on one machine, attack its traffic, "
            "and keep every measurement for comparison.",
            16.5,
            t["muted"],
        ),
    ]
    o += input_stage(t) + network_stage(t) + attack_stage(t) + result_stage(t) + tools_strip(t)
    for a, b in [(INPUT, NET), (NET, ATTACK), (ATTACK, RESULT)]:
        o.append(arrow(a[0] + a[1] + 7, mid, b[0] - 9, mid, t))
    o.append("</svg>")
    return "\n".join(o)


path = OUT / "anontestlab-overview.svg"
path.write_text(figure(THEMES["light"]) + "\n")
print(path)

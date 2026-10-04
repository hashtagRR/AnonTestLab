"""PDF reports: the same evidence the Results, Compare and Paired pages
show, laid out as documents someone can save, print or attach to an
email. Built with matplotlib's PdfPages rather than a browser print or a
heavier dependency (reportlab, weasyprint): matplotlib comes with the
dashboard extra (pip install -e ".[dashboard]"), and headless PDF
generation needs no display and nothing tied to the headless-Chromium
flakiness this sandbox has shown.

Charts here are deliberately simpler than the web page's interactive SVG
charts (no hover, coarser detail): the goal is a readable static page, not
a port of charts.js.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: no display, this runs inside a web request
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from . import store

PAGE_SIZE = (8.5, 11)  # inches, US letter
_INK = "#172033"
_MUTED = "#647089"
_LINE = "#dfe5ee"
_S1, _S2, _S3, _S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"


def _fig():
    fig = plt.figure(figsize=PAGE_SIZE, dpi=150)
    fig.patch.set_facecolor("white")
    return fig


def _strip(ax) -> None:
    ax.set_facecolor("white")
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(_LINE)
    ax.tick_params(colors=_MUTED, labelsize=7)


def _header(fig, title: str, subtitle: str, page_label: str) -> None:
    fig.text(0.07, 0.965, "AnonTestLab", fontsize=9, color=_MUTED, weight="bold")
    fig.text(0.93, 0.965, page_label, fontsize=9, color=_MUTED, ha="right")
    fig.text(0.07, 0.93, title, fontsize=18, color=_INK, weight="bold")
    fig.text(0.07, 0.905, subtitle, fontsize=9, color=_MUTED)
    fig.add_artist(plt.Line2D([0.07, 0.93], [0.89, 0.89], color=_LINE, linewidth=0.8, transform=fig.transFigure))


def _footer(fig, note: str = "") -> None:
    fig.add_artist(plt.Line2D([0.07, 0.93], [0.055, 0.055], color=_LINE, linewidth=0.8, transform=fig.transFigure))
    fig.text(0.07, 0.035, note or "Measured by a local AnonTestLab emulator run.", fontsize=7, color=_MUTED)


def _fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if v != v:  # NaN
            return "n/a"
        return f"{v:.{digits}f}"
    return str(v)


def _kv_table(ax, rows: list[tuple[str, str]], fontsize: int = 9) -> None:
    ax.axis("off")
    y = 1.0
    step = 1.0 / max(len(rows), 1)
    for label, value in rows:
        ax.text(0.0, y - step * 0.3, label, fontsize=fontsize, color=_MUTED, va="top")
        ax.text(0.62, y - step * 0.3, value, fontsize=fontsize, color=_INK, va="top", weight="medium")
        y -= step


def _metric_tiles(fig, rect: tuple[float, float, float, float], tiles: list[tuple[str, str, str]]) -> None:
    left, bottom, width, height = rect
    n = len(tiles)
    w = width / n
    for i, (label, value, sub) in enumerate(tiles):
        x = left + i * w
        fig.add_artist(plt.Rectangle((x + 0.005, bottom), w - 0.01, height, transform=fig.transFigure,
                                      facecolor="#f8fafc", edgecolor=_LINE, linewidth=0.7))
        fig.text(x + 0.015, bottom + height - 0.02, label.upper(), fontsize=6.5, color=_MUTED, weight="bold")
        fig.text(x + 0.015, bottom + height * 0.45, value, fontsize=14, color=_INK, weight="bold")
        if sub:
            fig.text(x + 0.015, bottom + 0.012, sub, fontsize=6.5, color=_MUTED)


def _design_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    lens = "+".join(str(x) for x in (summary.get("path_lengths") or []))
    paths = f"{summary.get('paths')} ({lens} hops)"
    if summary.get("paths", 1) > 1:
        paths += f", {summary['merge']}"
    traffic = f"{summary.get('traffic')}, {_fmt(summary.get('real_rate'), 1)} pkt/s"
    if (summary.get("cover_rate") or 0) > 0:
        traffic += f", cover {_fmt(summary.get('cover_rate'), 1)}"
    if summary.get("mix") == "pool":
        defense = f"pool {_fmt(summary.get('pool_interval_ms'), 0)} ms"
    else:
        defense = summary.get("mix") or "none"
    return [
        ("Relays", str(summary.get("nodes"))),
        ("Sessions", str(summary.get("sessions"))),
        ("Seed", str(summary.get("seed"))),
        ("Paths", paths),
        ("Traffic", traffic),
        ("Defense", defense),
        ("Crypto", str(summary.get("crypto"))),
        ("Adversaries", ", ".join(summary.get("adversaries") or []) or "none"),
    ]


def _overview_page(pdf: PdfPages, run_id: str, detail: dict[str, Any]) -> None:
    import datetime

    fig = _fig()
    s, mt = detail["summary"], detail["metrics"]
    written = datetime.datetime.fromtimestamp(detail.get("mtime", 0)).strftime("%Y-%m-%d %H:%M")
    _header(fig, detail["config"]["name"], f"{run_id}  |  written {written}  |  single-run result", "Overview")
    delivered_sub = f"{_fmt(mt.get('real_packets_delivered'), 0)} delivered"
    _metric_tiles(fig, (0.07, 0.72, 0.86, 0.12), [
        ("Delivery rate", f"{(mt.get('delivery_rate') or 0) * 100:.1f}%", delivered_sub),
        ("Median one-way", f"{(mt.get('oneway_delay_p50_s') or 0) * 1000:.1f} ms", ""),
        ("P95 one-way", f"{(mt.get('oneway_delay_p95_s') or 0) * 1000:.1f} ms", ""),
        ("Bandwidth overhead", f"{_fmt(mt.get('bandwidth_overhead_x'), 2)}x", ""),
    ])
    ax1 = fig.add_axes((0.07, 0.40, 0.40, 0.26))
    fig.text(0.07, 0.68, "Configuration", fontsize=11, color=_INK, weight="bold")
    _kv_table(ax1, _design_rows(s))
    if "tpr_at_fpr_0.001" in mt:
        ax2 = fig.add_axes((0.53, 0.40, 0.40, 0.26))
        fig.text(0.53, 0.68, "Global observer", fontsize=11, color=_INK, weight="bold")
        _kv_table(ax2, [
            ("TPR at FPR 1e-3", _fmt(mt.get("tpr_at_fpr_0.001"))),
            ("AUC", _fmt(mt.get("auc"))),
            ("Realized FPR", _fmt(mt.get("realized_fpr_0.001"))),
            ("Sessions failed", _fmt(mt.get("sessions_failed"), 0)),
        ])
    fig.text(0.07, 0.33, "Interpretation", fontsize=11, color=_INK, weight="bold")
    fig.text(0.07, 0.29, "This page describes one seeded execution. A paired multi-seed analysis is needed\n"
                         "before reading a difference from another configuration as an experimental effect.",
             fontsize=8.5, color=_MUTED, va="top")
    _footer(fig, f"Reproduce: atl run {detail['dir']}/experiment.yaml" if detail.get("runnable_spec")
            else "This run predates a stored runnable spec; rebuild one from configuration.yaml.")
    pdf.savefig(fig)
    plt.close(fig)


def _roc_axes(ax, attackers: list[dict[str, Any]], ids: list[str], colors: list[str]) -> None:
    by_id = {a["id"]: a for a in attackers}
    ax.plot([0, 1], [0, 1], color=_LINE, linewidth=1, linestyle="--")
    for attacker_id, color in zip(ids, colors):
        a = by_id.get(attacker_id)
        if not a or not a["roc"]:
            continue
        xs = [p[0] for p in a["roc"]]
        ys = [p[1] for p in a["roc"]]
        ax.plot(xs, ys, color=color, linewidth=1.6, label=attacker_id)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("false positive rate", fontsize=7.5, color=_MUTED)
    ax.set_ylabel("true positive rate", fontsize=7.5, color=_MUTED)
    ax.legend(fontsize=6.5, frameon=False, loc="lower right")
    _strip(ax)


def _suite_page(pdf: PdfPages, root: Path, run_id: str, detail: dict[str, Any]) -> None:
    try:
        evidence = store.suite_evidence(root, run_id)
    except (ValueError, FileNotFoundError, KeyError):
        return
    if not evidence.get("attackers"):
        return
    fig = _fig()
    _header(fig, "Correlation suite", f"{run_id}  |  {evidence.get('test_sessions', 0)} test sessions", "Page 2")
    ids = sorted({a["id"] for a in evidence["attackers"]})
    a1_ids = sorted((i for i in ids if i.startswith("a1_w")), key=lambda i: float(i.split("_w")[1]))
    pick = a1_ids[: min(4, len(a1_ids))] or ids[:4]
    ax1 = fig.add_axes((0.09, 0.50, 0.38, 0.33))
    _roc_axes(ax1, evidence["attackers"], pick, [_S1, _S2, _S3, _S4])
    fig.text(0.09, 0.85, "Attacker ROC (A1, by bin width)", fontsize=10, color=_INK, weight="bold")

    first = evidence["attackers"][0]
    ax2 = fig.add_axes((0.55, 0.50, 0.38, 0.33))
    edges, true, imp = first["hist"]["edges"], first["hist"]["true"], first["hist"]["impostor"]
    if edges:
        centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(edges) - 1)]
        width = (edges[1] - edges[0]) * 0.9 if len(edges) > 1 else 1
        ax2.bar(centers, imp, width=width, color=_S1, alpha=0.35, label=f"impostors ({first['impostor_pairs']})")
        ax2.bar(centers, true, width=width, color=_S2, alpha=0.45, label=f"true pairs ({first['true_pairs']})")
        ax2.legend(fontsize=6.5, frameon=False)
    ax2.set_xlabel(f"{first['id']} score", fontsize=7.5, color=_MUTED)
    _strip(ax2)
    fig.text(0.55, 0.85, "True vs impostor scores", fontsize=10, color=_INK, weight="bold")

    ax3 = fig.add_axes((0.09, 0.14, 0.84, 0.28))
    rows = [("Metric", *pick)]
    mt = detail["metrics"]
    for label, suffix in [("TPR at FPR 1e-3", "tpr_at_fpr_0.001"), ("AUC", "auc"), ("mu hat", "mu_hat")]:
        rows.append((label, *[_fmt(mt.get(f"{aid}_{suffix}")) for aid in pick]))
    _table(ax3, rows)
    fig.text(0.09, 0.44, "Attacker matrix", fontsize=10, color=_INK, weight="bold")
    _footer(fig, "No metric here is colored good or bad: the direction depends on the research question.")
    pdf.savefig(fig)
    plt.close(fig)


def _table(ax, rows: list[tuple]) -> None:
    ax.axis("off")
    t = ax.table(cellText=rows[1:], colLabels=rows[0], loc="center", cellLoc="left")
    t.auto_set_font_size(False)
    t.set_fontsize(7.5)
    t.scale(1, 1.5)
    for (r, _c), cell in t.get_celld().items():
        cell.set_edgecolor(_LINE)
        if r == 0:
            cell.set_text_props(weight="bold", color=_INK)
            cell.set_facecolor("#f8fafc")
        else:
            cell.set_facecolor("white")


def _latency_page(pdf: PdfPages, root: Path, run_id: str, detail: dict[str, Any]) -> None:
    try:
        delays = store.oneway_delays(root, run_id, points=800)
    except (ValueError, FileNotFoundError):
        return
    if not delays.get("n"):
        return
    fig = _fig()
    _header(fig, "Latency", f"{run_id}  |  {delays['n']} delivered real packets", "Page 3")
    ax = fig.add_axes((0.11, 0.40, 0.8, 0.42))
    ax.plot([v * 1000 for v in delays["values"]], delays["cdf"], color=_S1, linewidth=1.6)
    ax.set_xlabel("one-way delay (ms)", fontsize=8, color=_MUTED)
    ax.set_ylabel("cumulative fraction", fontsize=8, color=_MUTED)
    ax.set_ylim(0, 1.02)
    _strip(ax)
    fig.text(0.11, 0.84, "Empirical CDF of entry-to-exit delay", fontsize=11, color=_INK, weight="bold")
    mt = detail["metrics"]
    ax2 = fig.add_axes((0.11, 0.16, 0.8, 0.14))
    _kv_table(ax2, [
        ("P50", f"{(mt.get('oneway_delay_p50_s') or 0) * 1000:.2f} ms"),
        ("P95", f"{(mt.get('oneway_delay_p95_s') or 0) * 1000:.2f} ms"),
        ("P99", f"{(mt.get('oneway_delay_p99_s') or 0) * 1000:.2f} ms"),
    ], fontsize=9)
    _footer(fig, "Not just the p50/p95/p99 in metrics.json: this is every delivered real packet.")
    pdf.savefig(fig)
    plt.close(fig)


def _metrics_pages(pdf: PdfPages, run_id: str, detail: dict[str, Any]) -> None:
    mt = detail["metrics"]
    keys = sorted(mt)
    rows_per_page = 42
    pages = [keys[i:i + rows_per_page] for i in range(0, len(keys), rows_per_page)] or [[]]
    for i, chunk in enumerate(pages):
        fig = _fig()
        _header(fig, "Raw metrics", f"{run_id}  |  {len(keys)} values", f"Page {4 + i} of {3 + len(pages)}")
        ax = fig.add_axes((0.09, 0.08, 0.84, 0.78))
        table_rows = [("Metric", "Value")] + [(k, _fmt(mt[k])) for k in chunk]
        _table(ax, table_rows)
        _footer(fig)
        pdf.savefig(fig)
        plt.close(fig)


def build_run_report(root: Path, run_id: str) -> bytes:
    """A multi-page PDF covering the same evidence as the Results page:
    overview and configuration, the correlation suite (if present),
    latency (if any packets were delivered), and the full metrics table."""
    detail = store.output_detail(root, run_id)
    if detail["kind"] != "run":
        raise ValueError(f"{run_id!r} is not an experiment run")
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _overview_page(pdf, run_id, detail)
        _suite_page(pdf, root, run_id, detail)
        _latency_page(pdf, root, run_id, detail)
        _metrics_pages(pdf, run_id, detail)
        info = pdf.infodict()
        info["Title"] = f"AnonTestLab report: {detail['config']['name']}"
        info["Subject"] = run_id
        info["Author"] = "AnonTestLab dashboard"
    return buf.getvalue()


# ------------------------------------------------------------- comparison


def _compare_overview_page(pdf: PdfPages, cmp: dict[str, Any]) -> None:
    fig = _fig()
    a, b = cmp["a"], cmp["b"]
    _header(fig, f"{a['name']} vs {b['name']}", f"A: {a['id']} (seed {a['seed']})  |  B: {b['id']} (seed {b['seed']})",
            "Comparison")
    diff = cmp["config_diff"]
    fig.text(0.07, 0.855, "Configuration diff", fontsize=11, color=_INK, weight="bold")
    if diff:
        ax1 = fig.add_axes((0.07, 0.56, 0.86, 0.28))
        rows = [("Field", "A", "B")] + [(d["key"], _fmt(d["a"], 3), _fmt(d["b"], 3)) for d in diff[:14]]
        _table(ax1, rows)
        if len(diff) > 14:
            fig.text(0.07, 0.545, f"...and {len(diff) - 14} more fields; see the web Compare page for all of them.",
                      fontsize=7.5, color=_MUTED)
    else:
        fig.text(0.07, 0.80, "The configurations are identical apart from the name.", fontsize=9, color=_MUTED)

    headline = ["delivery_rate", "oneway_delay_p50_s", "oneway_delay_p95_s", "bandwidth_overhead_x",
                "tpr_at_fpr_0.001", "auc", "sessions_failed"]
    by_metric = {r["metric"]: r for r in cmp["rows"]}
    fig.text(0.07, 0.49, "Outcome difference (delta is B minus A)", fontsize=11, color=_INK, weight="bold")
    ax2 = fig.add_axes((0.07, 0.20, 0.86, 0.26))
    rows2 = [("Metric", "A", "B", "Delta")]
    for key in headline:
        r = by_metric.get(key)
        if r:
            rows2.append((key, _fmt(r["a"]), _fmt(r["b"]), _fmt(r["delta"])))
    _table(ax2, rows2)
    _footer(fig, "Single-run comparison: a matched seed controls experiment choices, but runtime timing is still "
                 "subject to process and socket scheduling. A paired multi-seed analysis estimates an effect; "
                 "this page does not.")
    pdf.savefig(fig)
    plt.close(fig)


def build_compare_report(root: Path, a_id: str, b_id: str) -> bytes:
    """A one-page PDF of the same diff the Compare page shows for two
    stored runs: what changed in the configuration, then what moved in
    the metrics."""
    cmp = store.compare_runs(root, a_id, b_id)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _compare_overview_page(pdf, cmp)
        info = pdf.infodict()
        info["Title"] = f"AnonTestLab comparison: {cmp['a']['name']} vs {cmp['b']['name']}"
        info["Subject"] = f"{a_id} vs {b_id}"
        info["Author"] = "AnonTestLab dashboard"
    return buf.getvalue()


# ----------------------------------------------------------------- paired


_VERDICT_TEXT = {
    "meaningful_effect": "Meaningful effect: the 95% interval excludes zero and the mean difference is at least "
                         "the margin. This is an effect classification, not a software pass.",
    "no_meaningful_effect": "No meaningful effect: the whole 95% interval lies inside the equivalence region.",
    "inconclusive": "Inconclusive: the interval crosses the edge of the equivalence region. More seeds, or a "
                     "margin chosen for the question, would be needed to classify it.",
}


def _paired_page(pdf: PdfPages, run_id: str, detail: dict[str, Any]) -> None:
    fig = _fig()
    s = detail["summary"]
    _header(fig, "Paired multi-seed analysis", f"{s['reference']} vs {s['treatment']}  |  metric: {s['metric']}",
            "Overview")
    _metric_tiles(fig, (0.07, 0.80, 0.86, 0.12), [
        ("Seeds", str(s["n_pairs"]), "matched reference/treatment"),
        ("Mean paired effect", _fmt(s["mean_delta"]), "treatment minus reference"),
        ("95% CI", f"[{_fmt(s['ci_low'])}, {_fmt(s['ci_high'])}]", "bootstrap over seed pairs"),
        ("Margin", f"+/-{_fmt(s['margin'])}", "pre-specified"),
    ])
    verdict = _VERDICT_TEXT.get(s["classification"], s["classification"])
    fig.text(0.07, 0.74, s["classification"].replace("_", " ").title(), fontsize=13, color=_INK, weight="bold")
    fig.text(0.07, 0.705, verdict, fontsize=8.5, color=_MUTED, va="top", wrap=True)

    rows = detail.get("rows") or []
    if rows:
        # paired_runs.csv always uses fixed "reference"/"treatment" column
        # names (see write_paired) so the two never collide into one key
        # when the configs share a name; these are the display labels,
        # disambiguated the same way for that case.
        same_name = s["reference"] == s["treatment"]
        ref_label = f"{s['reference']} (reference)" if same_name else s["reference"]
        treat_label = f"{s['treatment']} (treatment)" if same_name else s["treatment"]
        ref_v = [r.get("reference") for r in rows]
        treat_v = [r.get("treatment") for r in rows]
        ax = fig.add_axes((0.11, 0.37, 0.8, 0.28))
        for rv, tv in zip(ref_v, treat_v):
            if isinstance(rv, (int, float)) and isinstance(tv, (int, float)):
                ax.plot([0, 1], [rv, tv], color=_LINE, linewidth=1)
                ax.scatter([0], [rv], color=_S1, s=18, zorder=3)
                ax.scatter([1], [tv], color=_S2, s=18, zorder=3)
        ax.set_xlim(-0.15, 1.15)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([ref_label, treat_label], fontsize=7.5)
        _strip(ax)
        fig.text(0.11, 0.655, "Matched-seed outcomes", fontsize=10, color=_INK, weight="bold")

        ax2 = fig.add_axes((0.11, 0.08, 0.8, 0.22))
        table_rows = [("Seed", ref_label, treat_label, "Delta")]
        for r in rows[:16]:
            table_rows.append((str(r["seed"]), _fmt(r.get("reference")), _fmt(r.get("treatment")),
                                _fmt(r.get("delta"))))
        _table(ax2, table_rows)
        if len(rows) > 16:
            fig.text(0.11, 0.065, f"...and {len(rows) - 16} more seeds; see paired_runs.csv for all of them.",
                      fontsize=7.5, color=_MUTED)
    _footer(fig, "CI method: paired bootstrap, 10,000 resamples.")
    pdf.savefig(fig)
    plt.close(fig)


def build_paired_report(root: Path, run_id: str) -> bytes:
    """A one-page PDF of a stored paired analysis: the verdict, the
    matched-seed outcomes, and the per-seed table."""
    detail = store.output_detail(root, run_id)
    if detail["kind"] != "paired":
        raise ValueError(f"{run_id!r} is not a paired analysis")
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _paired_page(pdf, run_id, detail)
        info = pdf.infodict()
        p = detail["summary"]
        info["Title"] = f"AnonTestLab paired analysis: {p['reference']} vs {p['treatment']}"
        info["Subject"] = run_id
        info["Author"] = "AnonTestLab dashboard"
    return buf.getvalue()

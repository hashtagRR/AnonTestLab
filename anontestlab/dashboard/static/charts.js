// Small SVG charts. Each function renders into a container element and
// wires its own hover layer. Series colors are CSS tokens (--s1..--s4),
// assigned to entities in fixed order by the caller, never by rank.
import { escapeHtml, num } from './core.js';

const W = 600;
const PAD = { l: 52, r: 96, t: 14, b: 38 };
export const SERIES = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'];

function scale(d0, d1, r0, r1, log = false) {
  if (log) {
    const a = Math.log10(d0), b = Math.log10(d1);
    return (v) => r0 + ((Math.log10(Math.max(v, d0)) - a) / (b - a || 1)) * (r1 - r0);
  }
  return (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
}

function niceTicks(lo, hi, n = 5) {
  if (!(hi > lo)) return [lo];
  const step0 = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(+v.toFixed(12));
  return ticks;
}

function extent(values, pad = 0) {
  const v = values.filter((x) => Number.isFinite(x));
  if (!v.length) return [0, 1];
  let lo = Math.min(...v), hi = Math.max(...v);
  if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
  const p = (hi - lo) * pad;
  return [lo - p, hi + p];
}

function tooltip(el) {
  let tip = el.querySelector('.tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'tooltip hidden';
    el.appendChild(tip);
  }
  return tip;
}

function placeTip(el, svg, tip, x, y, content) {
  const r = svg.getBoundingClientRect();
  const k = r.width / W;
  tip.innerHTML = content;
  tip.classList.remove('hidden');
  const left = Math.min(Math.max(x * k, 70), r.width - 70);
  tip.style.left = `${left}px`;
  tip.style.top = `${y * k}px`;
}

function svgPoint(svg, evt) {
  const r = svg.getBoundingClientRect();
  return { x: ((evt.clientX - r.left) / r.width) * W, y: ((evt.clientY - r.top) / r.width) * W };
}

// De-overlaps end-of-line labels: sorted by y, each at least `gap` below the last.
function spreadLabels(items, gap, lo, hi) {
  items.sort((a, b) => a.y - b.y);
  for (let i = 1; i < items.length; i++) items[i].y = Math.max(items[i].y, items[i - 1].y + gap);
  const over = items.length ? items[items.length - 1].y - hi : 0;
  if (over > 0) items.forEach((it) => { it.y = Math.max(lo, it.y - over); });
  return items;
}

/**
 * Multi-series line chart with a crosshair tooltip.
 * opts: series [{name, color, points: [[x, y], ...]}], xLabel, yLabel,
 * xFormat, yFormat, xDomain, yDomain, xLog, height, xTicks (categorical
 * tick values), markers, diagonal (draws y = x as a reference).
 */
export function lineChart(el, opts) {
  const H = opts.height || 260;
  const series = opts.series.filter((s) => s.points.length);
  const xf = opts.xFormat || ((v) => num(v, 2));
  const yf = opts.yFormat || ((v) => num(v, 3));
  const xs = series.flatMap((s) => s.points.map((p) => p[0]));
  const ys = series.flatMap((s) => s.points.map((p) => p[1]));
  const [x0, x1] = opts.xDomain || extent(xs);
  const [y0, y1] = opts.yDomain || extent(ys, 0.08);
  const r = series.length > 1 || opts.endLabels ? PAD.r : 18;
  const sx = scale(x0, x1, PAD.l, W - r, opts.xLog);
  const sy = scale(y0, y1, H - PAD.b, PAD.t);
  const xt = opts.xTicks || (opts.xLog ? logTicks(x0, x1) : niceTicks(x0, x1));
  const yt = niceTicks(y0, y1, 4);

  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(opts.aria || opts.yLabel || 'chart')}">`;
  s += '<g class="axis">';
  for (const t of yt) {
    s += `<line class="gridline" x1="${PAD.l}" x2="${W - r}" y1="${sy(t)}" y2="${sy(t)}"/>`;
    s += `<text x="${PAD.l - 8}" y="${sy(t) + 3}" text-anchor="end">${escapeHtml(yf(t))}</text>`;
  }
  for (const t of xt) s += `<text x="${sx(t)}" y="${H - PAD.b + 16}" text-anchor="middle">${escapeHtml(xf(t))}</text>`;
  s += `<line x1="${PAD.l}" x2="${W - r}" y1="${H - PAD.b}" y2="${H - PAD.b}"/>`;
  if (opts.xLabel) s += `<text x="${(PAD.l + W - r) / 2}" y="${H - 4}" text-anchor="middle">${escapeHtml(opts.xLabel)}</text>`;
  if (opts.yLabel) s += `<text transform="translate(12 ${(PAD.t + H - PAD.b) / 2}) rotate(-90)" text-anchor="middle">${escapeHtml(opts.yLabel)}</text>`;
  s += '</g>';
  if (opts.diagonal) s += `<line class="crosshair" x1="${sx(x0)}" y1="${sy(y0)}" x2="${sx(x1)}" y2="${sy(y1)}"/>`;
  for (const se of series) {
    const d = se.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
    s += `<path class="series" d="${d}" stroke="${se.color}"/>`;
    if (opts.markers) for (const p of se.points) {
      s += `<circle cx="${sx(p[0])}" cy="${sy(p[1])}" r="4.5" fill="${se.color}" stroke="var(--panel)" stroke-width="2"/>`;
    }
  }
  if (series.length > 1 || opts.endLabels) {
    const labels = spreadLabels(series.map((se) => {
      const last = se.points[se.points.length - 1];
      return { name: se.name, color: se.color, y: sy(last[1]) + 4, x: sx(last[0]) };
    }), 13, PAD.t + 4, H - PAD.b);
    for (const l of labels) s += `<text class="label" x="${l.x + 8}" y="${l.y}">${escapeHtml(l.name)}</text>`;
  }
  s += `<line class="crosshair hidden" data-cross y1="${PAD.t}" y2="${H - PAD.b}"/>`;
  s += `<g data-dots></g>`;
  s += `<rect class="hit" x="${PAD.l}" y="0" width="${W - r - PAD.l}" height="${H}"/>`;
  s += '</svg>';
  const legend = series.length > 1
    ? `<div class="legend">${series.map((se) => `<span><i class="sw" style="background:${se.color}"></i>${escapeHtml(se.name)}</span>`).join('')}</div>`
    : '';
  el.classList.add('chart');
  el.innerHTML = s + legend;

  const svg = el.querySelector('svg');
  const cross = svg.querySelector('[data-cross]');
  const dots = svg.querySelector('[data-dots]');
  const tip = tooltip(el);
  const hit = svg.querySelector('.hit');
  const nearest = (pts, x) => {
    let best = pts[0];
    for (const p of pts) if (Math.abs(sx(p[0]) - x) < Math.abs(sx(best[0]) - x)) best = p;
    return best;
  };
  hit.addEventListener('mousemove', (evt) => {
    const { x } = svgPoint(svg, evt);
    const anchor = nearest(series[0].points, x);
    const cx = opts.snap === false ? x : sx(anchor[0]);
    cross.setAttribute('x1', cx);
    cross.setAttribute('x2', cx);
    cross.classList.remove('hidden');
    let rows = '';
    let dotSvg = '';
    let topY = H;
    for (const se of series) {
      const p = nearest(se.points, cx);
      dotSvg += `<circle cx="${sx(p[0])}" cy="${sy(p[1])}" r="4" fill="${se.color}" stroke="var(--panel)" stroke-width="2"/>`;
      topY = Math.min(topY, sy(p[1]));
      rows += `<div>${series.length > 1 ? `<i class="sw" style="background:${se.color}"></i> ${escapeHtml(se.name)}: ` : ''}<b>${escapeHtml(yf(p[1]))}</b></div>`;
    }
    dots.innerHTML = dotSvg;
    const head = `<div class="muted">${escapeHtml(opts.xLabel || 'x')}: ${escapeHtml(xf(anchor[0]))}</div>`;
    placeTip(el, svg, tip, cx, topY, head + rows);
  });
  hit.addEventListener('mouseleave', () => {
    cross.classList.add('hidden');
    dots.innerHTML = '';
    tip.classList.add('hidden');
  });
}

function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.ceil(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) out.push(10 ** e);
  return out;
}

/**
 * Two overlaid density histograms (true pairs vs impostors) as step areas,
 * with an optional vertical marker.
 */
export function densityChart(el, { edges, a, b, aName, bName, height = 240, xLabel }) {
  const H = height;
  const n = a.length;
  if (!n) { el.innerHTML = '<div class="empty">No scores in this split.</div>'; return; }
  const sx = scale(edges[0], edges[n], PAD.l, W - 18);
  const top = Math.max(...a, ...b) || 1;
  const sy = scale(0, top * 1.1, H - PAD.b, PAD.t);
  const step = (vals) => {
    let d = `M${sx(edges[0])},${sy(0)}`;
    vals.forEach((v, i) => { d += `L${sx(edges[i])},${sy(v)}L${sx(edges[i + 1])},${sy(v)}`; });
    return d + `L${sx(edges[n])},${sy(0)}Z`;
  };
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="score distributions"><g class="axis">`;
  for (const t of niceTicks(edges[0], edges[n])) s += `<text x="${sx(t)}" y="${H - PAD.b + 16}" text-anchor="middle">${escapeHtml(num(t, 2))}</text>`;
  for (const t of niceTicks(0, top * 1.1, 3)) {
    s += `<line class="gridline" x1="${PAD.l}" x2="${W - 18}" y1="${sy(t)}" y2="${sy(t)}"/>`;
    s += `<text x="${PAD.l - 8}" y="${sy(t) + 3}" text-anchor="end">${escapeHtml((t * 100).toFixed(0))}%</text>`;
  }
  s += `<line x1="${PAD.l}" x2="${W - 18}" y1="${H - PAD.b}" y2="${H - PAD.b}"/>`;
  if (xLabel) s += `<text x="${(PAD.l + W) / 2}" y="${H - 4}" text-anchor="middle">${escapeHtml(xLabel)}</text>`;
  s += '</g>';
  s += `<path d="${step(b)}" fill="var(--s1)" fill-opacity=".18" stroke="var(--s1)" stroke-width="2"/>`;
  s += `<path d="${step(a)}" fill="var(--s2)" fill-opacity=".18" stroke="var(--s2)" stroke-width="2"/>`;
  const bw = (W - 18 - PAD.l) / n;
  for (let i = 0; i < n; i++) s += `<rect class="hit" data-i="${i}" x="${sx(edges[i])}" y="0" width="${bw}" height="${H - PAD.b}"/>`;
  s += '</svg>';
  s += `<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>${escapeHtml(bName)}</span><span><i class="sw" style="background:var(--s2)"></i>${escapeHtml(aName)}</span></div>`;
  el.classList.add('chart');
  el.innerHTML = s;
  const svg = el.querySelector('svg');
  const tip = tooltip(el);
  svg.querySelectorAll('.hit').forEach((r) => {
    r.addEventListener('mousemove', () => {
      const i = +r.dataset.i;
      placeTip(el, svg, tip, sx((edges[i] + edges[i + 1]) / 2), sy(Math.max(a[i], b[i])),
        `<div class="muted">score ${num(edges[i], 3)} to ${num(edges[i + 1], 3)}</div>` +
        `<div><i class="sw" style="background:var(--s2)"></i> ${escapeHtml(aName)}: <b>${(a[i] * 100).toFixed(1)}%</b></div>` +
        `<div><i class="sw" style="background:var(--s1)"></i> ${escapeHtml(bName)}: <b>${(b[i] * 100).toFixed(1)}%</b></div>`);
    });
    r.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

/** Paired slope chart: one line per seed from reference to treatment. */
export function slopeChart(el, { seeds, ref, treat, refName, treatName, yFormat = (v) => num(v, 3), height = 280 }) {
  const H = height;
  const [y0, y1] = extent([...ref, ...treat], 0.1);
  const sy = scale(y0, y1, H - PAD.b, PAD.t);
  const xa = 170, xb = 430;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="matched seed outcomes"><g class="axis">`;
  for (const t of niceTicks(y0, y1, 4)) {
    s += `<line class="gridline" x1="${PAD.l}" x2="${W - 40}" y1="${sy(t)}" y2="${sy(t)}"/>`;
    s += `<text x="${PAD.l - 8}" y="${sy(t) + 3}" text-anchor="end">${escapeHtml(yFormat(t))}</text>`;
  }
  s += `<text x="${xa}" y="${H - 12}" text-anchor="middle">${escapeHtml(refName)}</text>`;
  s += `<text x="${xb}" y="${H - 12}" text-anchor="middle">${escapeHtml(treatName)}</text></g>`;
  seeds.forEach((seed, i) => {
    s += `<g class="pair" data-i="${i}"><line x1="${xa}" y1="${sy(ref[i])}" x2="${xb}" y2="${sy(treat[i])}" stroke="var(--faint)" stroke-width="1.5" stroke-opacity=".6"/>`;
    s += `<circle cx="${xa}" cy="${sy(ref[i])}" r="5" fill="var(--s1)" stroke="var(--panel)" stroke-width="2"/>`;
    s += `<circle cx="${xb}" cy="${sy(treat[i])}" r="5" fill="var(--s2)" stroke="var(--panel)" stroke-width="2"/>`;
    s += `<line class="hit" x1="${xa}" y1="${sy(ref[i])}" x2="${xb}" y2="${sy(treat[i])}" stroke="transparent" stroke-width="12"/></g>`;
  });
  s += '</svg>';
  s += `<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>${escapeHtml(refName)}</span><span><i class="sw" style="background:var(--s2)"></i>${escapeHtml(treatName)}</span></div>`;
  el.classList.add('chart');
  el.innerHTML = s;
  const svg = el.querySelector('svg');
  const tip = tooltip(el);
  svg.querySelectorAll('.pair').forEach((g) => {
    const i = +g.dataset.i;
    g.addEventListener('mousemove', () => {
      placeTip(el, svg, tip, (xa + xb) / 2, Math.min(sy(ref[i]), sy(treat[i])),
        `<div class="muted">seed ${seeds[i]}</div><div>${escapeHtml(refName)}: <b>${escapeHtml(yFormat(ref[i]))}</b></div>` +
        `<div>${escapeHtml(treatName)}: <b>${escapeHtml(yFormat(treat[i]))}</b></div><div>delta: <b>${escapeHtml(num(treat[i] - ref[i], 3))}</b></div>`);
    });
    g.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

/** Mean paired difference with its CI against a shaded +/- margin band. */
export function intervalChart(el, { mean, lo, hi, margin, height = 170 }) {
  const H = height;
  const span = Math.max(Math.abs(lo), Math.abs(hi), margin) * 1.35 || 1;
  const sx = scale(-span, span, PAD.l, W - 30);
  const y = 74;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="paired difference interval"><g class="axis">`;
  for (const t of niceTicks(-span, span, 6)) s += `<text x="${sx(t)}" y="${H - 22}" text-anchor="middle">${escapeHtml(num(t, 3))}</text>`;
  s += `<line x1="${PAD.l}" x2="${W - 30}" y1="${H - 36}" y2="${H - 36}"/></g>`;
  s += `<rect x="${sx(-margin)}" y="24" width="${sx(margin) - sx(-margin)}" height="${H - 60}" fill="var(--seg)" stroke="var(--line)"/>`;
  s += `<text class="label muted" x="${(sx(-margin) + sx(margin)) / 2}" y="40" text-anchor="middle">equivalence region +/-${escapeHtml(num(margin, 3))}</text>`;
  s += `<line class="crosshair" x1="${sx(0)}" x2="${sx(0)}" y1="24" y2="${H - 36}"/>`;
  s += `<line x1="${sx(lo)}" x2="${sx(hi)}" y1="${y}" y2="${y}" stroke="var(--s1)" stroke-width="4" stroke-linecap="round"/>`;
  s += `<circle cx="${sx(mean)}" cy="${y}" r="7" fill="var(--s1)" stroke="var(--panel)" stroke-width="2"/>`;
  s += `<text class="label" x="${sx(mean)}" y="${y - 14}" text-anchor="middle">${escapeHtml(num(mean, 3))}</text>`;
  s += `<text class="label muted" x="${sx(lo)}" y="${y + 22}" text-anchor="middle">${escapeHtml(num(lo, 3))}</text>`;
  s += `<text class="label muted" x="${sx(hi)}" y="${y + 22}" text-anchor="middle">${escapeHtml(num(hi, 3))}</text>`;
  s += '</svg>';
  el.classList.add('chart');
  el.innerHTML = s;
}

/**
 * One session's actual executed circuit(s): real relay node ids, from a
 * session_complete/session_failed event's `paths` field (one list of node
 * ids per leg, in hop order). Unlike pathDiagram (the configured design),
 * every node here is a relay that really carried this session's cells.
 */
/**
 * Force-directed graph of real relay connectivity, aggregated from every
 * session_complete/session_failed event's `paths` field seen so far (not
 * a geographic or physical network map: relay positions are a physics
 * layout, nothing about them is measured). positions is a Map<nodeId,
 * {x,y}> the caller keeps across calls, so new nodes/edges settle in
 * smoothly instead of the whole graph jumping; call once per redraw with
 * the running aggregate, not just the latest session.
 */
export function createTopologyLayout() {
  const positions = new Map();
  return {
    positions,
    reset() { positions.clear(); },
    /** nodes: Set<string> of relay ids seen so far. edges: Map<"a|b", count>. */
    step(nodes, edges, { width = 600, height = 360, iterations = 50 } = {}) {
      const ids = [...nodes];
      if (!ids.length) return;
      const area = width * height;
      const k = Math.sqrt(area / Math.max(ids.length, 1)) * 0.9;
      for (const id of ids) {
        if (!positions.has(id)) {
          const angle = Math.random() * Math.PI * 2;
          const r = Math.min(width, height) * 0.3;
          positions.set(id, { x: width / 2 + Math.cos(angle) * r, y: height / 2 + Math.sin(angle) * r });
        }
      }
      for (const id of [...positions.keys()]) if (!nodes.has(id)) positions.delete(id);
      const edgeList = [...edges.entries()].map(([key, weight]) => {
        const [a, b] = key.split("|");
        return { a, b, weight };
      });
      let temp = Math.max(width, height) * 0.03;
      for (let iter = 0; iter < iterations; iter++) {
        const disp = new Map(ids.map((id) => [id, { x: 0, y: 0 }]));
        for (let i = 0; i < ids.length; i++) {
          for (let j = i + 1; j < ids.length; j++) {
            const pa = positions.get(ids[i]);
            const pb = positions.get(ids[j]);
            let dx = pa.x - pb.x;
            let dy = pa.y - pb.y;
            let dist = Math.hypot(dx, dy) || 0.01;
            const force = (k * k) / dist;
            dx = (dx / dist) * force;
            dy = (dy / dist) * force;
            disp.get(ids[i]).x += dx; disp.get(ids[i]).y += dy;
            disp.get(ids[j]).x -= dx; disp.get(ids[j]).y -= dy;
          }
        }
        for (const { a, b, weight } of edgeList) {
          if (!positions.has(a) || !positions.has(b)) continue;
          const pa = positions.get(a);
          const pb = positions.get(b);
          const dx = pa.x - pb.x;
          const dy = pa.y - pb.y;
          const dist = Math.hypot(dx, dy) || 0.01;
          // Busier edges (more sessions sharing this hop) pull a little
          // tighter, so the layout reads as real usage, not just structure.
          const force = ((dist * dist) / k) * (0.6 + 0.4 / Math.sqrt(weight));
          const ux = (dx / dist) * force;
          const uy = (dy / dist) * force;
          disp.get(a).x -= ux; disp.get(a).y -= uy;
          disp.get(b).x += ux; disp.get(b).y += uy;
        }
        for (const id of ids) {
          const d = disp.get(id);
          const len = Math.hypot(d.x, d.y) || 0.01;
          const p = positions.get(id);
          p.x += (d.x / len) * Math.min(len, temp);
          p.y += (d.y / len) * Math.min(len, temp);
          p.x = Math.max(24, Math.min(width - 24, p.x));
          p.y = Math.max(24, Math.min(height - 24, p.y));
        }
        temp *= 0.96;
      }
    },
  };
}

/** Renders the current layout (after step()) as an SVG node-link graph. */
export function topologyGraph(el, { layout, nodes, edges, lit = new Set(), width = 600, height = 360 }) {
  const pos = layout.positions;
  const maxWeight = Math.max(1, ...edges.values());
  let s = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="relay connectivity graph">`;
  for (const [key, weight] of edges) {
    const [a, b] = key.split("|");
    const pa = pos.get(a), pb = pos.get(b);
    if (!pa || !pb) continue;
    const w = 0.6 + (weight / maxWeight) * 2.2;
    s += `<line x1="${pa.x.toFixed(1)}" y1="${pa.y.toFixed(1)}" x2="${pb.x.toFixed(1)}" y2="${pb.y.toFixed(1)}" stroke="var(--faint)" stroke-width="${w.toFixed(2)}" stroke-opacity=".55"/>`;
  }
  for (const id of nodes) {
    const p = pos.get(id);
    if (!p) continue;
    const isLit = lit.has(id);
    const r = isLit ? 9 : 6.5;
    s += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}" fill="${isLit ? 'var(--s1)' : 'var(--panel-2)'}" stroke="${isLit ? 'var(--s1)' : 'var(--faint)'}" stroke-width="1.5"/>`;
    s += `<text x="${p.x.toFixed(1)}" y="${(p.y - r - 3).toFixed(1)}" text-anchor="middle" class="label${isLit ? '' : ' muted'}" font-size="8">${escapeHtml(id)}</text>`;
  }
  s += "</svg>";
  el.classList.add("chart");
  el.innerHTML = s;
}

export function circuitDiagram(paths, { failed = false } = {}) {
  const colors = ['var(--s1)', 'var(--s3)', 'var(--s2)', 'var(--s4)'];
  const dim = failed ? 'var(--bad-ink)' : null;
  const rows = paths.map((hops, i) => {
    const color = dim || colors[i % colors.length];
    let line = `<div class="path-line"><span class="tag">${paths.length > 1 ? `Leg ${i + 1}` : 'Circuit'}</span>`;
    line += `<span class="node" style="border-color:${color};color:${color}">C</span>`;
    hops.forEach((nodeId, h) => {
      const exit = h === hops.length - 1;
      line += `<span class="edge" style="background:${color}"></span>`;
      line += `<span class="node mono" style="border-color:${color};color:${color};font-size:8px">${escapeHtml(nodeId)}</span>`;
      if (exit) line += `<span class="edge" style="background:${color}"></span><span class="node" style="border-color:${color};color:${color}">E</span>`;
    });
    return line + '</div>';
  }).join('');
  return `<div>${rows}</div>`;
}

/** Configured path design (not executed paths): client, hops, exit per leg. */
export function pathDiagram(paths, { merge = 'disjoint', observed = null } = {}) {
  // paths: [{length, label}], observed: set of observed leg indices or null (all)
  const colors = ['var(--s1)', 'var(--s3)', 'var(--s2)', 'var(--s4)'];
  const rows = paths.map((p, i) => {
    const color = colors[i % colors.length];
    const seen = !observed || observed.has(i);
    let line = `<div class="path-line"><span class="tag">${escapeHtml(p.label || `Path ${i + 1}`)}${seen ? '' : '<br>unobserved'}</span>`;
    line += `<span class="node" style="border-color:${color};color:${color}">C</span>`;
    for (let h = 1; h <= p.length; h++) {
      const exit = h === p.length;
      const shared = exit && merge === 'common_exit';
      line += `<span class="edge" style="background:${color};${seen ? '' : 'opacity:.35'}"></span>`;
      line += `<span class="node" style="border-color:${shared ? 'var(--faint)' : color};color:${shared ? 'var(--ink)' : color}">${exit ? 'E' : h}</span>`;
    }
    return line + '</div>';
  }).join('');
  return `<div>${rows}</div>`;
}

// Workbench views: experiments library, runs, live job, results, artifacts.
import {
  $, JOB_ROUTE, ago, api, bytes, copy, defenseText, designText, duration, enc, errorBox, fmtMetric, html,
  job, kindBadge, meta, metricCard, mount, ms, num, outputs, pageHead, pct, raw, trafficText,
} from './core.js';
import { SERIES, circuitDiagram, createTopologyLayout, densityChart, lineChart, pathDiagram, topologyGraph } from './charts.js';

// ------------------------------------------------- suite metric parsing

// Keys look like a1_w0.25_tpr_at_fpr_0.001 or a3_q0.5_auc. Bin widths and
// FPR targets are read from the keys, never rebuilt from numbers: Python
// writes 1.0 and 1e-05 where JavaScript would write 1 and 0.00001.
export function suiteIndex(metrics) {
  const by = {};
  const get = (id) => (by[id] ||= { tpr: {}, realized: {}, support: {}, lpsi: {} });
  for (const [k, v] of Object.entries(metrics)) {
    let m = k.match(/^(a[0-3](?:_[wq][^_]+)?)_(tpr_at_fpr|realized_fpr|fpr_support)_(.+)$/);
    if (m) { get(m[1])[{ tpr_at_fpr: 'tpr', realized_fpr: 'realized', fpr_support: 'support' }[m[2]]][m[3]] = v; continue; }
    m = k.match(/^(a[0-3](?:_[wq][^_]+)?)_(mu_hat|auc)$/);
    if (m) { get(m[1])[m[2]] = v; continue; }
    m = k.match(/^(a[0-3](?:_[wq][^_]+)?)_lpsi_([^_]+)_br_(.+)$/);
    if (m) get(m[1]).lpsi[`psi ${m[2]}, base rate ${m[3]}`] = v;
  }
  const ids = Object.keys(by);
  const widths = [...new Set(ids.map((id) => id.match(/_w(.+)$/)?.[1]).filter(Boolean))].sort((a, b) => a - b);
  const quantiles = [...new Set(ids.map((id) => id.match(/_q(.+)$/)?.[1]).filter(Boolean))].sort((a, b) => a - b);
  const fprs = [...new Set(ids.flatMap((id) => Object.keys(by[id].tpr)))].sort((a, b) => b - a);
  return { by, ids, widths, quantiles, fprs };
}

export function modelIndex(metrics) {
  const rows = {};
  for (const [k, v] of Object.entries(metrics || {})) {
    const m = k.match(/^model_a1_w([^_]+)_(.+)$/);
    if (m) (rows[m[1]] ||= {})[m[2]] = v;
  }
  return rows;
}

const ATTACKER_NAME = { a0: 'A0 zero-lag', a1: 'A1 lag-aware', a2: 'A2 likelihood ratio', a3: 'A3 timing window' };
const fprLabel = (f) => `FPR ${Number(f).toExponential(0)}`;

// ----------------------------------------------------------- experiments

export async function experimentsView(el) {
  const [m, all] = await Promise.all([meta(), outputs(true)]);
  const runs = all.filter((o) => o.kind === 'run');
  const examples = Object.keys(m.templates).filter((k) => k.startsWith('example:'));
  const live = job.state && job.state.active && job.state.kind === 'run' ? job.state.label : null;

  mount(el, html`
    ${pageHead('Experiments', 'Build controlled anonymous-network experiments, run them locally, and keep enough evidence to compare or reproduce the result.',
      html`<a class="btn" href="#/new">Open builder</a><a class="btn primary" href="#/new?template=blank">New experiment</a>`)}
    <div class="grid g3">
      <div class="card template"><span><span class="badge blue"><span class="dot"></span>Start from a model</span></span>
        <h3>Tor-like baseline</h3><p>One 3-hop path, random relay selection, no cover traffic, no mixing.</p>
        <a class="btn" href="#/new?template=tor_like">Use template</a></div>
      <div class="card template"><span><span class="badge amber"><span class="dot"></span>Multipath</span></span>
        <h3>Path-splitting experiment</h3><p>Two 3-hop paths with IID splitting, an observer on one path, and the correlation suite.</p>
        <a class="btn" href="#/new?template=path_splitting">Use template</a></div>
      <div class="card template"><span><span class="badge"><span class="dot"></span>Custom</span></span>
        <h3>Blank experiment</h3><p>Every field at its default. Build the configuration from scratch.</p>
        <div class="row"><a class="btn" href="#/new?template=blank">Create blank</a>
        ${examples.length ? html`<select class="select" id="example-pick" style="width:auto" aria-label="Start from an example spec"><option value="">From an example...</option>${examples.map((k) => html`<option value="${k}">${k.slice(8)}</option>`)}</select>` : ''}</div></div>
    </div>
    <div class="section-title">Experiment library</div>
    <div class="card">
      <div class="card-head"><div><h3>Stored runs</h3><p>Every run under <span class="mono">${m.results_root}</span>, from the CLI or this dashboard. Rerunning a name overwrites its directory.</p></div>
        <input class="input" id="lib-filter" placeholder="Filter" style="width:200px" aria-label="Filter experiments"></div>
      ${runs.length || live ? html`<div class="table-wrap"><table class="table" id="lib">
        <thead><tr><th>Experiment</th><th>Design</th><th>Traffic</th><th>Defense</th><th>Adversaries</th><th>Last run</th><th>Status</th></tr></thead>
        <tbody>
          ${live && !runs.some((r) => r.id === live) ? html`<tr class="clickable" data-href="#/runs/live"><td><b>${live}</b></td><td colspan="4" class="muted">running now</td><td></td><td><span class="badge blue"><span class="dot pulse"></span>Running</span></td></tr>` : ''}
          ${runs.map((r) => html`<tr class="clickable" data-href="#/results/${r.id}" data-text="${[r.id, r.name, designText(r.summary), trafficText(r.summary), defenseText(r.summary), (r.summary.adversaries || []).join(' ')].join(' ').toLowerCase()}">
            <td><b>${r.name}</b>${r.name !== r.id ? html`<div class="mono muted small">${r.id}</div>` : ''}</td>
            <td>${designText(r.summary)}</td><td>${trafficText(r.summary)}</td><td>${defenseText(r.summary)}</td>
            <td>${(r.summary.adversaries || []).join(', ')}</td><td>${live === r.id ? 'running now' : ago(r.mtime)}</td>
            <td>${live === r.id ? html`<span class="badge blue"><span class="dot pulse"></span>Running</span>`
              : r.metrics.sessions_failed ? html`<span class="badge amber">${r.metrics.sessions_failed} failed</span>` : html`<span class="badge green">Complete</span>`}</td></tr>`)}
        </tbody></table></div>`
        : html`<div class="empty">No runs yet. Start from a template above, or run <span class="mono">atl run examples/tor_like.yaml</span> in this directory.</div>`}
    </div>
    <div class="section-title">Research posture</div>
    <div class="grid g3">
      <div class="card template"><h3>Reproducible by design</h3><p>Every run keeps its configuration, seed and a runnable spec beside the measurements.</p></div>
      <div class="card template"><h3>Evidence before decoration</h3><p>Path views show the configured design. They do not invent a geographic or physical network map.</p></div>
      <div class="card template"><h3>One run is one draw</h3><p>Use paired multi-seed analysis before reading a difference between configurations as an effect.</p></div>
    </div>`);

  el.addEventListener('click', (evt) => {
    const tr = evt.target.closest('tr[data-href]');
    if (tr) location.hash = tr.dataset.href;
  });
  $('#example-pick', el)?.addEventListener('change', (evt) => {
    if (evt.target.value) location.hash = `#/new?template=${encodeURIComponent(evt.target.value)}`;
  });
  $('#lib-filter', el)?.addEventListener('input', (evt) => {
    const q = evt.target.value.trim().toLowerCase();
    el.querySelectorAll('#lib tbody tr[data-text]').forEach((tr) => { tr.hidden = q && !tr.dataset.text.includes(q); });
  });
}

// ------------------------------------------------------------------ runs

function outputSummary(o) {
  const s = o.summary || {};
  if (o.kind === 'run') return `${designText(s)}; ${defenseText(s)}`;
  if (o.kind === 'sweep') return `${s.param}, ${s.points} points`;
  if (o.kind === 'paired') return s.metric ? `${s.metric}: ${String(s.classification || '').replaceAll('_', ' ')}` : '';
  if (o.kind === 'fidelity') return s.passes === undefined ? '' : s.passes ? 'passes' : 'fails';
  return '';
}

export const routeFor = (o) => (o.kind === 'run' ? `#/results/${o.id}` : o.kind === 'compare' ? `#/artifacts/${o.id}` : `#/${o.kind}/${o.id}`);

export async function runsView(el) {
  const all = await outputs(true);
  const s = job.state;
  mount(el, html`
    ${pageHead('Runs', 'Everything under results/: experiment runs and the analyses built from them. One job runs at a time, because concurrent relays would add host noise to each other\'s timing.')}
    ${s && s.kind ? html`<div class="card" style="margin-bottom:16px"><div class="card-head">
      <div><h3>${s.active ? 'Running now' : 'Last job'}: ${s.label}</h3><p>${s.kind}, started ${ago(s.started_at)}${s.error ? ', failed' : ''}</p></div>
      <a class="btn ${s.active ? 'primary' : ''}" href="#/runs/live">${s.active ? 'Watch progress' : 'Open job log'}</a></div></div>` : ''}
    <div class="card">
      ${all.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Output</th><th>Kind</th><th>Summary</th><th>Written</th><th></th></tr></thead>
        <tbody>${all.map((o) => html`<tr class="clickable" data-href="${routeFor(o)}"><td><b>${o.id}</b></td><td>${kindBadge(o.kind)}</td>
          <td class="muted">${outputSummary(o)}</td><td>${ago(o.mtime)}</td><td><a class="link" href="#/artifacts/${o.id}">Evidence</a></td></tr>`)}</tbody></table></div>`
        : html`<div class="empty">Nothing under results/ yet.</div>`}
    </div>`);
  el.addEventListener('click', (evt) => {
    if (evt.target.closest('a')) return;
    const tr = evt.target.closest('tr[data-href]');
    if (tr) location.hash = tr.dataset.href;
  });
}

// ------------------------------------------------------------- live job

const PHASES = ['Starting relays', 'Running sessions', 'Adversary analysis', 'Evidence written'];

function phaseOf(state, events) {
  if (!state.active) return state.error ? -1 : 4;
  const types = new Set(events.map((e) => e.type));
  if (types.has('experiment_complete')) return 2;
  if (types.has('relays_ready')) return 1;
  return 0;
}

function logLine(e) {
  const t = new Date(e.t * 1000).toLocaleTimeString([], { hour12: false });
  let cls = 'info', word = 'INFO', msg = e.type;
  if (e.type === 'relays_ready') { cls = 'ok'; word = 'READY'; msg = `relay pool started count=${e.num_nodes}`; }
  if (e.type === 'session_complete') { cls = 'ok'; word = 'DONE'; msg = `session s-${e.session_id} real=${e.real_delivered}/${e.real_sent} circuit_build=${(e.build_delay_s * 1000).toFixed(0)}ms (${e.completed}/${e.total})`; }
  if (e.type === 'session_failed') { cls = 'bad'; word = 'FAIL'; msg = `session s-${e.session_id}: ${e.error}`; }
  if (e.type === 'experiment_complete') { word = 'INFO'; msg = `sessions finished, ${e.sessions_failed} failed; scoring adversaries`; }
  return html`<div><span class="t">${t}</span> <span class="${cls}">${word}</span> ${msg}</div>`;
}

export function liveView(el) {
  let autoscroll = true;
  let built = false;
  let stopping = false;
  let lastCircuitKey = null; // (step, session_id) already rendered, so the flash animation only fires once per circuit
  let topologyEpoch = null; // (started_at, step): relays restart from n0 each run, so the layout resets per step
  const topologyLayout = createTopologyLayout();
  const unsub = job.subscribe(update);
  if (!job.state) job.poll();
  el.addEventListener('click', async (evt) => {
    if (evt.target.id === 'autoscroll') {
      autoscroll = !autoscroll;
      evt.target.setAttribute('aria-pressed', String(autoscroll));
    }
    if (evt.target.id === 'stop-run' && !stopping) {
      if (!confirm('Stop the running job? Relay processes are killed; any in-flight sessions are lost, but points or seeds already finished are kept.')) return;
      stopping = true;
      evt.target.disabled = true;
      evt.target.textContent = 'Stopping...';
      try {
        await job.stop();
      } catch (e) {
        stopping = false;
        evt.target.disabled = false;
        evt.target.textContent = 'Stop run';
        const slot = $('#live-stop-error', el);
        if (slot) mount(slot, errorBox(e));
      }
    }
  });

  function update(s, events) {
    if (!el.isConnected) { unsub(); return; }
    if (!s.kind) {
      mount(el, html`${pageHead('Runs', '')}<div class="card empty">No job has run since the dashboard started. <a class="link" href="#/new">Build an experiment</a> or start an analysis.</div>`);
      return;
    }
    const cur = events.filter((e) => e.step === s.step);
    const ready = cur.find((e) => e.type === 'relays_ready');
    const done = cur.filter((e) => e.type === 'session_complete');
    const failed = cur.filter((e) => e.type === 'session_failed');
    const total = cur.find((e) => e.total)?.total;
    const sent = done.reduce((a, e) => a + e.real_sent, 0);
    const delivered = done.reduce((a, e) => a + e.real_delivered, 0);
    const phase = phaseOf(s, cur);
    const elapsed = (s.finished_at || Date.now() / 1000) - s.started_at;
    const status = s.stopped
      ? (s.active ? html`<span class="badge amber"><span class="dot pulse"></span>Stopping...</span>` : html`<span class="badge amber">Stopped</span>`)
      : s.active ? html`<span class="badge blue"><span class="dot pulse"></span>Running</span>`
      : s.error ? html`<span class="badge red">Failed</span>` : html`<span class="badge green">Complete</span>`;
    const multi = s.steps > 1;
    // A stopped single run or fidelity probe usually has nothing written
    // (see _stopped_result in server.py); a stopped sweep or paired job
    // keeps whatever points/seeds finished before the stop.
    const hasOutput = !s.stopped || (s.result && s.result.has_output);
    const finished = !s.active && !s.error && s.out_id && hasOutput && s.browsable;
    // A compare job's "result" lives on the two component runs it diffed,
    // read live by the Compare page from their query params, not under
    // the job's own out_id (that id only names the diff artifact, which
    // /compare doesn't read back from disk). extra carries both ids even
    // through a stop or an error in run_in_background's generic path.
    const target = !finished ? null
      : s.kind === 'compare'
        ? (s.extra && s.extra.a_out_id ? `#/compare?a=${encodeURIComponent(s.extra.a_out_id)}&b=${encodeURIComponent(s.extra.b_out_id)}` : null)
        : `#/${JOB_ROUTE[s.kind]}/${s.out_id}`;
    const targetLabel = s.kind === 'compare' ? 'Open comparison' : 'Open results';
    const progress = total ? (done.length + failed.length) / total : 0;

    if (!built) {
      built = true;
      mount(el, html`
        <div id="live-head"></div>
        <div class="card" style="margin-bottom:16px"><div class="timeline" id="live-phases"></div></div>
        <div class="grid g4" id="live-cards" style="margin-bottom:16px"></div>
        <div class="card" style="margin-bottom:16px" id="live-circuit-card">
          <div class="card-head"><div><h3>Live circuit</h3><p>The real relay processes, and the most recent session's actual chosen path. Not every executed session, just the latest one.</p></div></div>
          <div class="card-body stack">
            <div class="relay-grid" id="live-relays"></div>
            <div class="path-diagram" id="live-circuit-diagram"><div class="empty">Waiting for a session to build a circuit.</div></div>
          </div>
        </div>
        <div class="card" style="margin-bottom:16px" id="live-topology-card">
          <div class="card-head"><div><h3>Relay connectivity</h3><p>Built from every session's actual chosen relays so far, this run only. Node positions are a physics layout, not a geographic or physical network map.</p></div></div>
          <div class="card-body"><div id="live-topology"><div class="empty">Waiting for sessions to build circuits.</div></div></div>
        </div>
        <div class="grid g2" style="margin-bottom:16px">
          <div class="card"><div class="card-head"><div><h3>Progress</h3><p>Research lifecycle of the current run.</p></div></div><div class="card-body" id="live-progress"></div></div>
          <div class="card"><div class="card-head"><div><h3>Sessions</h3><p>Transport counts as each session finishes.</p></div></div><div class="table-wrap" id="live-sessions" style="max-height:330px"></div></div>
        </div>
        <div class="card"><div class="card-head"><div><h3>Run log</h3><p>Progress events from the emulator. Full outputs land in the results directory.</p></div>
          <button class="btn small" type="button" id="autoscroll" aria-pressed="true">Auto-scroll</button></div>
          <div class="card-body"><div class="log" id="live-log" aria-live="polite"></div></div></div>`);
    }
    const stopBtn = s.active
      ? html`<button class="btn" type="button" id="stop-run" ${s.stopped ? raw('disabled') : ''}>${s.stopped ? 'Stopping...' : 'Stop run'}</button>` : '';
    mount($('#live-head', el), pageHead(s.label, `${s.kind}${multi ? `, ${s.steps} runs` : ''}, started ${ago(s.started_at)}. Host timing is non-deterministic; seeds fix controlled choices only.`,
      html`${stopBtn}${target ? html`<a class="btn primary" href="${target}">${targetLabel}</a>` : ''}`,
      html`${status} <span class="mono muted">${s.kind}</span><div id="live-stop-error"></div>`));
    if (s.stopped) stopping = true;
    mount($('#live-phases', el), PHASES.map((p, i) => html`<div class="phase ${phase === -1 ? (i === 0 ? 'failed' : '') : i < phase ? 'done' : i === phase ? 'active' : ''}">${p}</div>`));
    mount($('#live-cards', el), [
      metricCard(multi ? 'Run' : 'Sessions', multi ? `${Math.min(s.step + (s.active ? 1 : 0), s.steps)} / ${s.steps}` : total ? `${done.length + failed.length} / ${total}` : 'n/a',
        multi ? s.step_label || '' : `${done.length} successful, ${failed.length} failed`),
      metricCard('Relay processes', ready ? ready.num_nodes : s.active ? 'starting' : 'n/a', ready ? 'all ready' : ''),
      metricCard('Real delivered', sent ? pct(delivered / sent) : 'n/a', 'across completed sessions'),
      metricCard('Elapsed', duration(elapsed), s.finished_at ? 'finished' : 'running'),
    ]);
    const circuitEvents = cur.filter((e) => (e.type === 'session_complete' || e.type === 'session_failed') && e.paths);
    const latestCircuit = circuitEvents[circuitEvents.length - 1];
    const relaysBox = $('#live-relays', el);
    if (relaysBox) {
      const litNodes = latestCircuit ? new Set(latestCircuit.paths.flat()) : new Set();
      mount(relaysBox, ready
        ? Array.from({ length: ready.num_nodes }, (_, i) => `n${i}`)
          .map((id) => html`<span class="relay-chip ${litNodes.has(id) ? 'lit' : ''}">${id}</span>`)
        : html`<span class="muted small">Relay processes have not started yet.</span>`);
    }
    const diagramBox = $('#live-circuit-diagram', el);
    if (diagramBox && latestCircuit) {
      const circuitKey = `${latestCircuit.step}:${latestCircuit.session_id}`;
      mount(diagramBox, html`
        ${raw(circuitDiagram(latestCircuit.paths, { failed: latestCircuit.type === 'session_failed' }))}
        <div class="hint" style="margin-top:4px">session s-${String(latestCircuit.session_id).padStart(3, '0')}${latestCircuit.type === 'session_failed' ? ', failed' : ', real relay ids'}</div>`);
      if (circuitKey !== lastCircuitKey) {
        lastCircuitKey = circuitKey;
        diagramBox.classList.remove('circuit-flash');
        void diagramBox.offsetWidth; // restart the CSS animation on a diagram that was already flashed once
        diagramBox.classList.add('circuit-flash');
      }
    }
    const topoBox = $('#live-topology', el);
    if (topoBox && circuitEvents.length) {
      const epoch = `${s.started_at}:${s.step}`;
      if (epoch !== topologyEpoch) {
        topologyEpoch = epoch;
        topologyLayout.reset();
      }
      const nodes = new Set(ready ? Array.from({ length: ready.num_nodes }, (_, i) => `n${i}`) : []);
      const edges = new Map();
      for (const e of circuitEvents) {
        for (const leg of e.paths) {
          leg.forEach((id) => nodes.add(id));
          for (let i = 0; i < leg.length - 1; i++) {
            const key = [leg[i], leg[i + 1]].sort().join('|');
            edges.set(key, (edges.get(key) || 0) + 1);
          }
        }
      }
      if (nodes.size) {
        topologyLayout.step(nodes, edges, { width: 600, height: 340 });
        topologyGraph(topoBox, { layout: topologyLayout, nodes, edges, lit: new Set(latestCircuit ? latestCircuit.paths.flat() : []) });
      }
    }
    mount($('#live-progress', el), html`
      ${multi ? html`<div class="summary-row"><span>Overall</span><span>${Math.round(((s.step + (s.active ? progress : 1)) / s.steps) * 100)}%</span></div>
        <div class="progress" style="margin-bottom:14px"><span style="width:${((s.step + (s.active ? progress : 1)) / s.steps) * 100}%"></span></div>` : ''}
      <div class="summary-row"><span>Session completion${multi ? ' (current run)' : ''}</span><span>${total ? Math.round(progress * 100) + '%' : s.kind === 'fidelity' ? 'not reported' : 'waiting'}</span></div>
      <div class="progress" style="margin-bottom:6px"><span style="width:${(s.active ? progress : s.error ? progress : 1) * 100}%"></span></div>
      <div class="summary-row"><span>Successful</span><span>${done.length}</span></div>
      <div class="summary-row"><span>Failed</span><span>${failed.length}</span></div>
      <div class="summary-row"><span>Pending</span><span>${total ? total - done.length - failed.length : 'n/a'}</span></div>
      <div class="summary-row"><span>Current stage</span><span>${s.stopped ? (s.active ? 'stopping' : 'stopped') : s.error ? 'failed' : PHASES[Math.max(0, Math.min(phase, 3))]}</span></div>
      ${s.step_label ? html`<div class="summary-row"><span>Current run</span><span>${s.step_label}</span></div>` : ''}
      ${s.error ? html`<div class="callout bad" style="margin-top:12px">${s.error}</div>` : ''}
      ${s.stopped && s.active ? html`<div class="callout warn" style="margin-top:12px">Stopping: killing relay processes so the current run ends. In-flight sessions are lost; points or seeds already finished stay on disk.</div>` : ''}
      ${s.stopped && !s.active ? html`<div class="callout warn" style="margin-top:12px">Stopped by request${s.result && s.result.message ? `: ${s.result.message}` : ''}. ${hasOutput ? 'Whatever finished before the stop was written to disk.' : 'Nothing was written: a single run or fidelity probe only writes its output at the very end, and this one was stopped before reaching it.'}</div>` : ''}
      ${!s.browsable && s.out_dir ? html`<div class="callout" style="margin-top:12px">Written to a custom directory outside <span class="mono">results/</span>, so this dashboard's Runs and Artifacts browser can't show it. Find it at <span class="mono">${s.out_dir}</span>.</div>` : ''}`);
    const rows = [...done, ...failed].sort((a, b) => a.session_id - b.session_id);
    mount($('#live-sessions', el), rows.length ? html`<table class="table"><thead><tr><th>Session</th><th>Status</th><th class="num">Sent</th><th class="num">Delivered</th><th class="num">Circuit build</th></tr></thead><tbody>
      ${rows.map((e) => html`<tr><td class="mono">s-${String(e.session_id).padStart(3, '0')}</td><td>${e.type === 'session_complete' ? html`<span class="badge green">Complete</span>` : html`<span class="badge red" title="${e.error}">Failed</span>`}</td>
        <td class="num">${e.real_sent ?? ''}</td><td class="num">${e.real_delivered ?? ''}</td><td class="num">${e.build_delay_s !== undefined ? ms(e.build_delay_s) : ''}</td></tr>`)}</tbody></table>`
      : html`<div class="empty">${s.kind === 'fidelity' ? 'The fidelity probe does not report per-session progress.' : 'No sessions finished yet.'}</div>`);
    const log = $('#live-log', el);
    mount(log, events.length ? events.slice(-400).map(logLine) : html`<div class="t">waiting for events</div>`);
    if (autoscroll) log.scrollTop = log.scrollHeight;
  }
}

// --------------------------------------------------------------- results

export async function resultsView(el, { id, query }) {
  if (!id) {
    const latest = (await outputs(true)).find((o) => o.kind === 'run');
    if (latest) { location.replace(`#/results/${latest.id}`); return; }
    mount(el, html`${pageHead('Results', '')}<div class="card empty">No runs yet. <a class="link" href="#/new">Build an experiment</a>.</div>`);
    return;
  }
  const d = await api(`/api/outputs/${enc(id)}`);
  if (d.kind !== 'run') { location.replace(`#/artifacts/${id}`); return; }
  const tab = query.get('tab') || 'summary';
  const mt = d.metrics;
  const s = d.summary;
  const suite = suiteIndex(mt);
  const hasModel = Object.keys(modelIndex(mt)).length > 0;
  const tabs = [['summary', 'Summary'], ['adversary', 'Adversaries'], ...(hasModel ? [['model', 'Model']] : []), ['paths', 'Paths'], ['raw', 'Raw metrics']];
  const failed = mt.sessions_failed;

  mount(el, html`
    ${pageHead(d.config.name, `Seed ${s.seed}, ${s.sessions} sessions, ${s.nodes} relays. Written ${ago(d.mtime)}. Single-run result.`,
      html`<a class="btn" href="#/artifacts/${id}">Evidence</a><a class="btn" href="/api/outputs/${enc(id)}/report.pdf" download>Download PDF</a>
           <a class="btn" href="#/new?from=${encodeURIComponent(id)}">Edit as new</a>
           <a class="btn" href="#/compare?a=${encodeURIComponent(id)}">Compare</a><a class="btn primary" href="#/paired?ref=${encodeURIComponent(id)}">Run paired analysis</a>`,
      html`${failed ? html`<span class="badge amber">${failed} session${failed > 1 ? 's' : ''} failed</span>` : html`<span class="badge green">Complete</span>`} <span class="mono muted">${id}</span>`)}
    <nav class="tabs" aria-label="Result sections">${tabs.map(([k, label]) => html`<a href="#/results/${id}?tab=${k}" class="${k === tab ? 'active' : ''}" ${k === tab ? raw('aria-current="page"') : ''}>${label}</a>`)}</nav>
    <div id="tab-body"></div>
    <div class="callout warn" style="margin-top:18px"><b>Interpretation:</b> this page describes one seeded execution. Use Paired analysis before treating a difference from another configuration as an experimental effect.</div>`);
  const body = $('#tab-body', el);

  if (tab === 'summary') return summaryTab(body, id, d, suite);
  if (tab === 'adversary') return adversaryTab(body, mt, suite);
  if (tab === 'model') return modelTab(body, mt, null);
  if (tab === 'paths') return pathsTab(body, d);
  return rawTab(body, id, mt);
}

function transportCards(mt) {
  return html`<div class="grid g4">
    ${metricCard('Delivery rate', pct(mt.delivery_rate), `${num(mt.real_packets_delivered)} of ${num(mt.real_packets_sent)} real packets`)}
    ${metricCard('Median one-way', ms(mt.oneway_delay_p50_s), 'entry to exit')}
    ${metricCard('P95 one-way', ms(mt.oneway_delay_p95_s), `P99 ${ms(mt.oneway_delay_p99_s)}`)}
    ${metricCard('Bandwidth overhead', typeof mt.bandwidth_overhead_x === 'number' ? `${mt.bandwidth_overhead_x.toFixed(2)}x` : 'n/a', `cover ${num(mt.cover_packets_sent)} packets`)}
  </div>`;
}

function attackerColumns(suite, w, q) {
  const cols = [];
  for (const fam of ['a0', 'a1', 'a2', 'a3']) {
    const id = fam === 'a2' ? 'a2' : fam === 'a3' ? `a3_q${q}` : `${fam}_w${w}`;
    if (suite.by[id]) cols.push({ fam, id, name: ATTACKER_NAME[fam] + (fam === 'a3' ? ` (q ${q})` : fam === 'a2' ? '' : ` (${w} s)`) });
  }
  return cols;
}

function suiteControls(suite, w, q) {
  return html`<div class="row">
    ${suite.widths.length ? html`<label class="hint" for="sel-w">Bin width</label><select class="select" id="sel-w" style="width:auto">${suite.widths.map((x) => html`<option ${x === w ? raw('selected') : ''}>${x}</option>`)}</select>` : ''}
    ${suite.quantiles.length > 1 ? html`<label class="hint" for="sel-q">A3 quantile</label><select class="select" id="sel-q" style="width:auto">${suite.quantiles.map((x) => html`<option ${x === q ? raw('selected') : ''}>${x}</option>`)}</select>` : ''}
  </div>`;
}

async function summaryTab(body, id, d, suite) {
  const mt = d.metrics;
  const advs = d.summary.adversaries;
  const blocks = [html`${transportCards(mt)}`];
  blocks.push(html`<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Latency CDF</h3><p>Empirical distribution of entry-to-exit delay across every delivered real packet, not just the p50/p95/p99 above.</p></div></div>
    <div class="card-body"><div id="latency-cdf"></div><p class="hint" id="latency-cdf-note" style="margin:6px 0 0"></p></div></div>`);
  if (advs.includes('global_observer')) {
    blocks.push(html`<div class="section-title">Global observer</div><div class="grid g4">
      ${metricCard('TPR at FPR 1e-3', num(mt['tpr_at_fpr_0.001']), mt.suite_test_sessions ? 'calibrated threshold' : 'threshold from the same pairs')}
      ${metricCard('Realized FPR', num(mt['realized_fpr_0.001']), 'at the chosen threshold')}
      ${metricCard('FPR support', num(mt['fpr_support_0.001'], 1), 'expected false positives')}
      ${metricCard('AUC', num(mt.auc), 'Pearson correlation score')}</div>`);
  }
  const other = [];
  if (advs.includes('path_compromise')) other.push(metricCard('Full path compromise', pct(mt.full_compromise_rate, 2), `95% CI +/- ${pct(mt.full_compromise_ci95, 2)}`), metricCard('Any path compromised', pct(mt.any_path_compromise_rate, 2), `${num(mt.compromise_trials)} trials`));
  if (advs.includes('hop_depth')) other.push(metricCard('Hop position accuracy', pct(mt.hop_position_accuracy), 'hop depth adversary'));
  if (advs.includes('watermark')) {
    const wk = Object.keys(mt).filter((k) => k.startsWith('watermark'));
    wk.slice(0, 2).forEach((k) => other.push(metricCard(k, fmtMetric(k, mt[k]), 'watermark adversary')));
  }
  if (other.length) blocks.push(html`<div class="section-title">Other adversaries</div><div class="grid g4">${other}</div>`);
  if (suite.ids.length) {
    blocks.push(html`<div class="section-title">Correlation suite</div>
      <div class="grid g2">
        <div class="card"><div class="card-head"><div><h3>Attacker ROC</h3><p>Empirical, on the held-out test sessions.</p></div><div id="roc-ctl"></div></div><div class="card-body"><div id="roc"></div><p class="hint" id="roc-note"></p></div></div>
        <div class="card"><div class="card-head"><div><h3>True vs impostor scores</h3><p>Separability of one attacker's scores.</p></div><select class="select" id="dist-pick" style="width:auto" aria-label="Attacker"></select></div><div class="card-body"><div id="dist"></div></div></div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Attacker matrix</h3><p>No metric is colored good or bad: the direction depends on the research question.</p></div></div><div class="table-wrap" id="matrix"></div></div>`);
  }
  if ((d.summary.paths || 1) > 1) blocks.push(html`<div class="section-title">Path design</div>${pathsCard(d)}`);
  mount(body, blocks);

  try {
    const delays = await api(`/api/outputs/${enc(id)}/latencies`);
    const cdfBox = $('#latency-cdf', body);
    if (!delays.n) {
      mount(cdfBox, html`<div class="empty">No delivered real packets to measure (or this run predates this chart).</div>`);
    } else {
      lineChart(cdfBox, {
        series: [{ name: 'delivered real packets', color: SERIES[0], points: delays.values.map((v, i) => [v, delays.cdf[i]]) }],
        yDomain: [0, 1], xLabel: 'one-way delay', yLabel: 'cumulative fraction', markers: delays.n <= 40,
        xFormat: (v) => ms(v), yFormat: (v) => pct(v, 0), aria: 'latency CDF',
      });
      $('#latency-cdf-note', body).textContent = delays.n > delays.values.length
        ? `${delays.n} delivered packets, thinned to ${delays.values.length} points for the chart.`
        : `${delays.n} delivered packets.`;
    }
  } catch (e) {
    mount($('#latency-cdf', body), errorBox(e));
  }

  if (!suite.ids.length) return;

  let w = suite.widths.includes('0.5') ? '0.5' : suite.widths[0];
  let q = suite.quantiles[0];
  let evidence = null;
  try {
    evidence = await api(`/api/outputs/${enc(id)}/suite`);
  } catch (e) {
    mount($('#roc', body), errorBox(e));
  }
  const draw = () => {
    const cols = attackerColumns(suite, w, q);
    mount($('#roc-ctl', body), suiteControls(suite, w, q));
    mount($('#matrix', body), matrixTable(suite, cols));
    if (!evidence) return;
    const byId = Object.fromEntries(evidence.attackers.map((a) => [a.id, a]));
    lineChart($('#roc', body), {
      series: cols.filter((c) => byId[c.id]).map((c) => ({ name: c.name.replace(/ \(.*\)/, ''), color: SERIES[['a0', 'a1', 'a2', 'a3'].indexOf(c.fam)], points: byId[c.id].roc })),
      xDomain: [0, 1], yDomain: [0, 1], xLabel: 'false positive rate', yLabel: 'true positive rate', diagonal: true, snap: false,
      xFormat: (v) => num(v, 2), yFormat: (v) => num(v, 2), aria: 'ROC curves',
    });
    const first = evidence.attackers[0];
    $('#roc-note', body).textContent = `${evidence.test_sessions} test sessions: ${first ? first.true_pairs : 0} true pairs, ${first ? first.impostor_pairs : 0} impostor pairs. The reported TPR at FPR uses a threshold chosen on the calibration sessions, so it can differ from a point read off this curve.`;
    const pick = $('#dist-pick', body);
    const current = pick.value || `a1_w${w}`;
    mount(pick, evidence.attackers.map((a) => html`<option value="${a.id}" ${a.id === current ? raw('selected') : ''}>${a.id}</option>`));
    drawDist();
  };
  const drawDist = () => {
    const a = evidence.attackers.find((x) => x.id === $('#dist-pick', body).value) || evidence.attackers[0];
    densityChart($('#dist', body), { edges: a.hist.edges, a: a.hist.true, b: a.hist.impostor, aName: `true pairs (${a.true_pairs})`, bName: `impostors (${a.impostor_pairs})`, xLabel: `${a.id} score` });
  };
  body.addEventListener('change', (evt) => {
    if (evt.target.id === 'sel-w') { w = evt.target.value; draw(); }
    if (evt.target.id === 'sel-q') { q = evt.target.value; draw(); }
    if (evt.target.id === 'dist-pick') drawDist();
  });
  draw();
}

function matrixTable(suite, cols) {
  const rows = [];
  for (const f of suite.fprs) {
    rows.push([`TPR at ${fprLabel(f)}`, (c) => suite.by[c.id].tpr[f]]);
    rows.push([`Realized FPR (target ${f})`, (c) => suite.by[c.id].realized[f]]);
    rows.push([`FPR support (target ${f})`, (c) => suite.by[c.id].support[f], 1]);
  }
  rows.push(['AUC', (c) => suite.by[c.id].auc], ['Signal estimate (mu hat)', (c) => suite.by[c.id].mu_hat]);
  return html`<table class="table"><thead><tr><th>Metric</th>${cols.map((c) => html`<th class="num">${c.name}</th>`)}</tr></thead><tbody>
    ${rows.map(([label, get, digits]) => html`<tr><td>${label}</td>${cols.map((c) => html`<td class="num">${num(get(c), digits ?? 3)}</td>`)}</tr>`)}</tbody></table>`;
}

function adversaryTab(body, mt, suite) {
  if (!suite.ids.length) {
    mount(body, html`<div class="card empty">This run did not include the correlation suite. Other adversary metrics are under Summary and Raw metrics.</div>`);
    return;
  }
  const lpsiKeys = [...new Set(suite.ids.flatMap((id) => Object.keys(suite.by[id].lpsi)))];
  mount(body, html`
    <div class="grid g4" style="margin-bottom:16px">
      ${metricCard('Calibration sessions', num(mt.suite_calibration_sessions), 'choose thresholds')}
      ${metricCard('Test sessions', num(mt.suite_test_sessions), 'scored')}
      ${metricCard('Lag search limit', `${num(mt.suite_lag_max_s, 2)} s`, `horizon ${num(mt.suite_horizon_s, 2)} s`)}
      ${metricCard('Overrun sessions', num(mt.suite_overrun_sessions), `${num(mt.suite_dropped_timestamps)} timestamps dropped`)}
    </div>
    <div class="card"><div class="card-head"><div><h3>Every attacker</h3><p>All bin widths and window quantiles, with confident linkage at each psi and base rate.</p></div></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>Attacker</th>${suite.fprs.map((f) => html`<th class="num">TPR at ${fprLabel(f)}</th>`)}<th class="num">AUC</th><th class="num">mu hat</th>${lpsiKeys.map((k) => html`<th class="num">Linkage ${k}</th>`)}</tr></thead>
    <tbody>${suite.ids.map((id) => html`<tr><td class="mono">${id}</td>${suite.fprs.map((f) => html`<td class="num">${num(suite.by[id].tpr[f])}</td>`)}<td class="num">${num(suite.by[id].auc)}</td><td class="num">${num(suite.by[id].mu_hat)}</td>${lpsiKeys.map((k) => html`<td class="num">${num(suite.by[id].lpsi[k])}</td>`)}</tr>`)}</tbody></table></div></div>`);
}

export function modelTab(body, mt, predictions) {
  // predictions: model_* values from /api/predict, or null to read them
  // out of a run's metrics (the suite stores them beside its measurements).
  const model = modelIndex(predictions || mt);
  const widths = Object.keys(model).sort((a, b) => a - b);
  if (!widths.length) {
    mount(body, html`<div class="card empty">No model predictions for this configuration.</div>`);
    return;
  }
  const tprKey = (row) => Object.keys(row).find((k) => k.startsWith('tpr_at_fpr_'));
  const measured = mt ? suiteIndex(mt) : null;
  const meas = (w, f) => (measured && measured.by[`a1_w${w}`] ? measured.by[`a1_w${w}`].tpr[f] : undefined);
  const measMu = (w) => (measured && measured.by[`a1_w${w}`] ? measured.by[`a1_w${w}`].mu_hat : undefined);
  const haveMeasured = widths.some((w) => measMu(w) !== undefined);
  const series = [{ name: 'Model', color: SERIES[0], points: widths.map((w) => [Number(w), model[w].mu_hat]).filter((p) => typeof p[1] === 'number') }];
  if (haveMeasured) series.push({ name: 'Measured', color: SERIES[1], points: widths.map((w) => [Number(w), measMu(w)]).filter((p) => typeof p[1] === 'number') });
  mount(body, html`
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Signal estimate by bin width</h3><p>A1 lag-aware correlator: mu hat${haveMeasured ? ', model and measured' : ''}.</p></div><span class="badge blue">MODEL</span></div><div class="card-body"><div id="mu-chart"></div></div></div>
      <div class="card"><div class="card-head"><div><h3>${haveMeasured ? 'Predicted vs measured' : 'Prediction'}</h3><p>Model output is not evidence until it is set against an actual run.</p></div></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Bin width</th><th class="num">Model TPR</th>${haveMeasured ? html`<th class="num">Measured TPR</th><th class="num">Difference</th>` : ''}<th class="num">Model mu hat</th>${haveMeasured ? html`<th class="num">Measured mu hat</th>` : ''}<th class="num">Gaussian mu hat</th></tr></thead>
      <tbody>${widths.map((w) => {
        const k = tprKey(model[w]);
        const f = k ? k.slice('tpr_at_fpr_'.length) : null;
        const mv = f ? meas(w, f) : undefined;
        return html`<tr><td>${w} s</td><td class="num">${num(model[w][k])}</td>${haveMeasured ? html`<td class="num">${num(mv)}</td><td class="num">${typeof mv === 'number' && typeof model[w][k] === 'number' ? num(mv - model[w][k]) : 'n/a'}</td>` : ''}
          <td class="num">${num(model[w].mu_hat)}</td>${haveMeasured ? html`<td class="num">${num(measMu(w))}</td>` : ''}<td class="num">${num(model[w].mu_hat_gaussian)}</td></tr>`;
      })}</tbody></table></div>
      <div class="card-body hint">TPR is at the first configured FPR target. The Gaussian column is the fully closed-form value, accurate for Poisson traffic and optimistic for bursty traffic.</div></div>
    </div>`);
  lineChart($('#mu-chart', body), { series, markers: true, xTicks: widths.map(Number), xLabel: 'bin width (s)', yLabel: 'mu hat', xFormat: (v) => `${v}`, aria: 'signal estimate by bin width', endLabels: true });
}

function pathsCard(d) {
  const c = d.config;
  const paths = [{ length: c.path_length }, ...(c.extra_paths || []).map((p) => ({ length: p.path_length }))];
  const observed = c.observed_legs ? new Set(c.observed_legs) : c.observed_path_count ? new Set([...Array(c.observed_path_count).keys()]) : null;
  const shares = paths.map((_, i) => d.metrics[`leg_${i}_real_share`]);
  const colors = ['var(--s1)', 'var(--s3)', 'var(--s2)', 'var(--s4)'];
  return html`<div class="card"><div class="card-head"><div><h3>Configured paths</h3><p>The design every session used. Executed per-session relay choices are not stored with the run.</p></div></div>
    <div class="card-body grid g2">
      <div class="path-diagram">${raw(pathDiagram(paths, { merge: c.merge, observed }))}</div>
      <div class="stack">
        ${paths.length > 1 && shares.every((x) => typeof x === 'number') ? html`
          <div><div class="summary-row"><span>Measured real-traffic share per leg</span><span>${c.split_strategy}</span></div>
          <div class="stackbar" role="img" aria-label="leg shares">${shares.map((x, i) => html`<span style="width:${x * 100}%;background:${raw(colors[i % 4])}" title="leg ${i}: ${pct(x)}"></span>`)}</div>
          <div class="legend" style="margin-top:8px">${shares.map((x, i) => html`<span><i class="sw" style="background:${raw(colors[i % 4])}"></i>Path ${i + 1}: ${pct(x)}</span>`)}</div></div>` : ''}
        <div class="summary-row"><span>Merge</span><span>${c.merge}</span></div>
        <div class="summary-row"><span>Observed</span><span>${observed ? [...observed].map((i) => `path ${i + 1}`).join(', ') : 'all paths'}</span></div>
        <div class="summary-row"><span>Egress observation</span><span>${c.egress_observation}</span></div>
      </div>
    </div></div>`;
}

function pathsTab(body, d) {
  mount(body, pathsCard(d));
}

function rawTab(body, id, mt) {
  const keys = Object.keys(mt);
  mount(body, html`<div class="card"><div class="card-head"><div><h3>All metrics</h3><p>${keys.length} values from metrics.json.</p></div>
    <div class="row"><input class="input" id="raw-filter" placeholder="Filter keys" style="width:220px" aria-label="Filter metrics">
    <a class="btn small" href="/api/outputs/${enc(id)}/files/metrics.csv?download=1">metrics.csv</a></div></div>
    <div class="table-wrap" style="max-height:640px"><table class="table" id="raw"><thead><tr><th>Metric</th><th class="num">Value</th></tr></thead>
    <tbody>${keys.map((k) => html`<tr data-k="${k.toLowerCase()}"><td class="mono">${k}</td><td class="num">${typeof mt[k] === 'number' ? num(mt[k], 4) : mt[k] === null ? 'nan' : String(mt[k])}</td></tr>`)}</tbody></table></div></div>`);
  $('#raw-filter', body).addEventListener('input', (evt) => {
    const q = evt.target.value.trim().toLowerCase();
    body.querySelectorAll('#raw tbody tr').forEach((tr) => { tr.hidden = q && !tr.dataset.k.includes(q); });
  });
}

// ------------------------------------------------------------- artifacts

const FILE_INFO = {
  'experiment.yaml': 'Runnable spec: what atl run reads',
  'reference.yaml': 'Runnable spec of the reference condition',
  'treatment.yaml': 'Runnable spec of the treatment condition',
  'configuration.yaml': 'Resolved configuration as a flat field dict (not readable by atl run)',
  'seed.txt': 'Seed for controlled experiment choices',
  'metrics.csv': 'Flat metric export',
  'metrics.json': 'Structured metric export',
  'report.md': 'Human-readable run summary',
  'correlation_suite.npz': 'Score matrices, split and raw timing observations',
  'sweep.csv': 'One row per sweep value with every metric',
  'sweep_meta.json': 'Sweep parameter and values',
  'paired_runs.csv': 'Per-seed reference and treatment values',
  'paired_summary.json': 'Mean delta, bootstrap CI and classification',
  'paired_meta.json': 'Seeds, metric and margin',
  'comparison.csv': 'Metric table of a CLI compare',
  'comparison.md': 'Markdown table of a CLI compare',
  'fidelity.json': 'Host-noise probe report',
};

function reproduceCommand(d) {
  const dir = d.dir;
  if (d.kind === 'run') return d.specs.includes('experiment.yaml') ? `atl run ${dir}/experiment.yaml` : null;
  if (d.kind === 'paired' && d.specs.length === 2) {
    const m = d.meta || {};
    return `atl paired ${dir}/reference.yaml ${dir}/treatment.yaml --seeds ${(m.seeds || []).join(',')} --metric ${m.metric} --margin ${m.margin}`;
  }
  if (d.kind === 'fidelity' && d.specs.includes('experiment.yaml')) return `atl fidelity ${dir}/experiment.yaml --limit-fraction ${d.summary.limit_fraction}`;
  if (d.kind === 'sweep' && d.points && d.points.length) {
    const vals = d.rows.map((r) => r[d.param]).join(',');
    return `atl sweep ${dir}/points/${d.points[0]}/experiment.yaml --param ${d.param} --values ${vals}`;
  }
  return null;
}

export async function artifactsView(el, { id }) {
  if (!id) {
    const all = await outputs(true);
    mount(el, html`${pageHead('Artifacts', 'Pick an output to inspect its evidence: the files needed to check or reproduce it.')}
      <div class="card">${all.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Output</th><th>Kind</th><th>Written</th></tr></thead>
        <tbody>${all.map((o) => html`<tr class="clickable" data-href="#/artifacts/${o.id}"><td><b>${o.id}</b></td><td>${kindBadge(o.kind)}</td><td>${ago(o.mtime)}</td></tr>`)}</tbody></table></div>` : html`<div class="empty">Nothing under results/ yet.</div>`}</div>`);
    el.addEventListener('click', (evt) => { const tr = evt.target.closest('tr[data-href]'); if (tr) location.hash = tr.dataset.href; });
    return;
  }
  const d = await api(`/api/outputs/${enc(id)}`);
  const cmd = reproduceCommand(d);
  const names = new Set(d.files.map((f) => f.name));
  const evidence = d.kind === 'run' ? [
    ['Runnable spec', names.has('experiment.yaml'), 'rebuilt on demand from configuration.yaml'],
    ['Configuration', names.has('configuration.yaml')],
    ['Metrics', names.has('metrics.json')],
    ['Correlation evidence', names.has('correlation_suite.npz'), (d.summary.adversaries || []).includes('correlation_suite') ? 'missing' : 'suite not selected'],
    ['Report', names.has('report.md')],
  ] : d.files.map((f) => [f.name, true]);
  mount(el, html`
    ${pageHead('Run evidence', html`Everything needed to inspect or reproduce <span class="mono">${id}</span> stays grouped with it, in <span class="mono">${d.dir}</span>.`,
      html`<a class="btn" href="/api/outputs/${enc(id)}/bundle.zip">Download bundle</a>${['run', 'paired'].includes(d.kind) ? html`<a class="btn" href="/api/outputs/${enc(id)}/report.pdf" download>Download PDF</a>` : ''}${cmd ? html`<button class="btn primary" type="button" id="copy-cmd">Copy reproduce command</button>` : ''}`,
      html`${kindBadge(d.kind)} ${d.kind === 'run' ? html`<a class="link small" href="#/results/${id}">Open results</a>` : d.kind === 'compare' ? '' : html`<a class="link small" href="#/${d.kind}/${id}">Open analysis</a>`}`)}
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="card-head"><div><h3>Reproduce</h3><p>A run started here can be repeated from the terminal.</p></div></div>
        <div class="card-body stack">
          ${cmd ? html`<pre class="code" style="white-space:pre-wrap">${cmd}</pre>` : d.kind === 'run' ? html`<div class="callout">This run came from the CLI, so it has no stored spec. <a class="link" href="/api/outputs/${enc(id)}/spec" download="${d.config.name}.yaml">Download a spec rebuilt from configuration.yaml</a>, then <span class="mono">atl run ${d.config.name}.yaml</span>.</div>` : html`<div class="callout">No stored spec for this output.</div>`}
          ${d.kind === 'run' ? html`<div><div class="summary-row"><span>Seed</span><span class="mono">${d.config.seed}</span></div><div class="summary-row"><span>Experiment</span><span>${d.config.name}</span></div></div>` : ''}
          <p class="hint" style="margin:0">Rerunning repeats the controlled choices. Timing-dependent metrics still vary with host scheduling.</p>
        </div></div>
      <div class="card"><div class="card-head"><div><h3>Evidence state</h3><p>Which outputs this directory holds.</p></div></div>
        <div class="card-body">${evidence.map(([label, ok, why]) => html`<div class="summary-row"><span>${label}</span><span>${ok ? html`<span class="badge green">Present</span>` : html`<span class="badge ${why === 'suite not selected' || (why || '').startsWith('rebuilt') ? '' : 'amber'}">${why || 'Missing'}</span>`}</span></div>`)}</div></div>
    </div>
    <div class="card"><div class="card-head"><div><h3>Files</h3><p>Machine-readable data beside human-readable summaries.</p></div></div>
      <div class="card-body">
        ${d.files.map((f) => html`<div class="artifact"><div class="left"><span class="fileicon">${f.suffix}</span><div><div class="name">${f.name}</div><div class="hint">${FILE_INFO[f.name] || ''} ${bytes(f.size)}</div></div></div>
          <div class="row">${f.suffix === 'npz' ? html`<button class="btn small" type="button" data-npz="${f.name}">Inspect</button>` : ['yaml', 'txt', 'csv', 'json', 'md'].includes(f.suffix) ? html`<button class="btn small" type="button" data-open="${f.name}">Open</button>` : ''}
          <a class="btn small" href="/api/outputs/${enc(id)}/files/${encodeURIComponent(f.name)}?download=1">Download</a></div></div>`)}
        ${d.points && d.points.length ? html`<div class="section-title">Sweep points</div>${d.points.map((p) => html`<div class="artifact"><div class="left"><span class="fileicon">dir</span><div class="name">points/${p}</div></div><a class="btn small" href="#/results/${id}/points/${p}">Open run</a></div>`)}` : ''}
      </div></div>
    <div class="card hidden" id="viewer" style="margin-top:16px"><div class="card-head"><div><h3 id="viewer-title"></h3></div><button class="btn small" type="button" id="viewer-close">Close</button></div><div class="card-body" id="viewer-body"></div></div>`);

  el.addEventListener('click', async (evt) => {
    const b = evt.target.closest('button');
    if (!b) return;
    const viewer = $('#viewer', el);
    if (b.id === 'copy-cmd') copy(cmd);
    if (b.id === 'viewer-close') viewer.classList.add('hidden');
    if (b.dataset.open || b.dataset.npz) {
      viewer.classList.remove('hidden');
      $('#viewer-title', el).textContent = b.dataset.open || b.dataset.npz;
      const vb = $('#viewer-body', el);
      try {
        if (b.dataset.open) {
          const text = await api(`/api/outputs/${enc(id)}/files/${encodeURIComponent(b.dataset.open)}`, { text: true });
          mount(vb, html`<pre class="code"></pre>`);
          vb.querySelector('pre').textContent = text;
        } else {
          const arrays = await api(`/api/outputs/${enc(id)}/npz/${encodeURIComponent(b.dataset.npz)}`);
          mount(vb, html`<div class="table-wrap"><table class="table"><thead><tr><th>Array</th><th>Shape</th><th>dtype</th><th class="num">Min</th><th class="num">Mean</th><th class="num">Max</th></tr></thead>
            <tbody>${arrays.map((a) => html`<tr><td class="mono">${a.key}</td><td class="mono">${a.shape.join(' x ') || 'scalar'}</td><td class="mono">${a.dtype}</td><td class="num">${num(a.min)}</td><td class="num">${num(a.mean)}</td><td class="num">${num(a.max)}</td></tr>`)}</tbody></table></div>
            <p class="hint">Load with <span class="mono">numpy.load("${d.dir}/${b.dataset.npz}")</span>. Scores are indexed [ingress session, egress session]; true pairs are the diagonal.</p>`);
        }
      } catch (e) {
        mount(vb, errorBox(e));
      }
      viewer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}


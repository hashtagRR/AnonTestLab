// Research tools: compare, sweep, paired, predict, fidelity.
import {
  $, api, download, enc, errorBox, fmtMetric, html, job, meta, metricCard, mount, ms, num, outDirField, outputs,
  pageHead, pct, pretty, raw, readOutDir, readSource, signed, sourcePicker, wireSourcePicker,
} from './core.js';
import { SERIES, intervalChart, lineChart, slopeChart } from './charts.js';
import { modelTab } from './views.js';

async function suiteFor(runId) {
  try {
    return await api(`/api/outputs/${enc(runId)}/suite`);
  } catch {
    return null; // this run has no correlation_suite evidence
  }
}

const HEADLINE = ['delivery_rate', 'oneway_delay_p50_s', 'oneway_delay_p95_s', 'bandwidth_overhead_x',
  'circuit_build_delay_s', 'tpr_at_fpr_0.001', 'auc', 'sessions_failed'];

const runsOnly = (all) => all.filter((o) => o.kind === 'run');

function startButton(label, id = 'go') {
  return html`<button class="btn primary" type="button" id="${id}">${label}</button>`;
}

async function startJob(el, path, body) {
  const box = $('#job-error', el);
  mount(box, '');
  try {
    await job.start(path, body);
    location.hash = '#/runs/live';
  } catch (e) {
    mount(box, errorBox(e));
  }
}

function storedPicker(items, kind, current) {
  if (!items.length) return '';
  return html`<select class="select" id="load-stored" style="width:auto" aria-label="Load a stored ${kind}">
    <option value="">Load stored ${kind}...</option>${items.map((o) => html`<option value="${o.id}" ${o.id === current ? raw('selected') : ''}>${o.id}</option>`)}</select>`;
}

function wireStored(el, kind) {
  $('#load-stored', el)?.addEventListener('change', (evt) => {
    if (evt.target.value) location.hash = `#/${kind}/${evt.target.value}`;
  });
}

// --------------------------------------------------------------- compare

function newComparisonCard(runs) {
  return html`<div class="card" style="margin-bottom:16px">
    <div class="card-head"><div><h3>Run a new comparison</h3><p>Run two configs (fresh, or a stored one rerun under its own name) and diff them in one action. Unlike the view below, neither needs to exist yet; both get written to their own results/&lt;name&gt;/, same as a plain run.</p></div></div>
    <div class="card-body stack">
      <div class="grid g2">
        <div class="field"><label for="new-a">A: reference</label>${sourcePicker('new-a', runs)}</div>
        <div class="field"><label for="new-b">B: treatment</label>${sourcePicker('new-b', runs)}</div>
      </div>
      <div style="max-width:420px">${outDirField('new-out-dir', 'results/<A name>_vs_<B name>/ (the diff only; each run still gets its own default)')}</div>
      <div class="row"><button class="btn primary" type="button" id="new-cmp-go">Run both and compare</button></div>
      <div id="job-error"></div>
    </div>
  </div>`;
}

function wireNewComparison(el) {
  wireSourcePicker(el, 'new-a');
  wireSourcePicker(el, 'new-b');
  $('#new-cmp-go', el).addEventListener('click', async () => {
    try {
      const [a, b] = [await readSource(el, 'new-a'), await readSource(el, 'new-b')];
      await startJob(el, '/api/compare_run', { a, b, out_dir: readOutDir(el, 'new-out-dir') });
    } catch (e) {
      mount($('#job-error', el), errorBox(e));
    }
  });
}

export async function compareView(el, { query }) {
  const runs = runsOnly(await outputs(true));
  if (runs.length < 2) {
    mount(el, html`${pageHead('Compare', 'Compare two stored runs, or run two fresh configs and compare them in one action.')}${newComparisonCard(runs)}`);
    wireNewComparison(el);
    return;
  }
  const a = query.get('a') || runs[1].id;
  const b = query.get('b') || runs.find((r) => r.id !== a).id;
  const sel = (id, value) => html`<select class="select" id="${id}">${runs.map((r) => html`<option value="${r.id}" ${r.id === value ? raw('selected') : ''}>${r.id}</option>`)}</select>`;
  mount(el, html`
    ${pageHead('Compare', 'Two completed runs side by side. Configuration differences come before outcome differences.',
      html`<button class="btn" type="button" id="swap">Swap A and B</button>
           <a class="btn" href="/api/compare/report.pdf?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}" download>Download PDF</a>
           <button class="btn primary" type="button" id="export">Export comparison</button>`)}
    <details style="margin-bottom:16px"><summary class="hint" style="cursor:pointer; margin-bottom:10px">Run a new comparison instead of picking from stored runs</summary>${newComparisonCard(runs)}</details>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card card-body field"><label for="pick-a">A: reference</label>${sel('pick-a', a)}<div class="hint" id="meta-a"></div></div>
      <div class="card card-body field"><label for="pick-b">B: treatment</label>${sel('pick-b', b)}<div class="hint" id="meta-b"></div></div>
    </div>
    <div id="cmp"></div>`);
  wireNewComparison(el);
  const go = () => { location.hash = `#/compare?a=${encodeURIComponent($('#pick-a', el).value)}&b=${encodeURIComponent($('#pick-b', el).value)}`; };
  $('#pick-a', el).addEventListener('change', go);
  $('#pick-b', el).addEventListener('change', go);
  $('#swap', el).addEventListener('click', () => { location.hash = `#/compare?a=${encodeURIComponent(b)}&b=${encodeURIComponent(a)}`; });

  let d;
  try {
    d = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  } catch (e) {
    mount($('#cmp', el), errorBox(e));
    return;
  }
  $('#meta-a', el).textContent = `${d.a.name}, seed ${d.a.seed}`;
  $('#meta-b', el).textContent = `${d.b.name}, seed ${d.b.seed}`;
  const yamlish = (v) => (v === null ? 'null' : typeof v === 'object' ? JSON.stringify(v) : String(v));
  const head = d.rows.filter((r) => HEADLINE.includes(r.metric)).sort((x, y) => HEADLINE.indexOf(x.metric) - HEADLINE.indexOf(y.metric));
  const sameSeed = d.a.seed === d.b.seed;
  mount($('#cmp', el), html`
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Configuration diff</h3><p>What changed comes before what moved.</p></div></div>
        <div class="card-body stack">
          ${d.config_diff.length ? html`<pre class="code diff">${d.config_diff.map((x) => html`<span class="minus">- ${x.key}: ${yamlish(x.a)}</span>\n<span class="plus">+ ${x.key}: ${yamlish(x.b)}</span>\n`)}</pre>` : html`<div class="callout">The configurations are identical apart from the name.</div>`}
          <div class="callout warn"><b>Scope:</b> this is a single-run comparison.${sameSeed ? ' The matched seed controls experiment choices, but' : ' The seeds differ, and'} runtime timing is still subject to process and socket scheduling. Use Paired for a multi-seed effect estimate.
            <div style="margin-top:8px"><a class="btn small" href="#/paired?ref=${encodeURIComponent(a)}&treat=${encodeURIComponent(b)}">Open paired analysis</a></div></div>
        </div></div>
      <div class="card"><div class="card-head"><div><h3>Outcome difference</h3><p>Delta is B minus A.</p></div></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Metric</th><th class="num">A</th><th class="num">B</th><th class="num">Delta</th></tr></thead>
        <tbody>${head.map((r) => html`<tr><td>${pretty(r.metric)}</td><td class="num">${fmtMetric(r.metric, r.a)}</td><td class="num">${fmtMetric(r.metric, r.b)}</td><td class="num">${signed(r.delta)}</td></tr>`)}</tbody></table></div></div>
    </div>
    <div class="card hidden" id="roc-overlay-card" style="margin-top:16px">
      <div class="card-head"><div><h3>Correlation resistance</h3><p>Same attacker, scored on each run's own held-out test sessions.</p></div>
        <select class="select" id="roc-overlay-pick" style="width:auto" aria-label="Attacker"></select></div>
      <div class="card-body"><div id="roc-overlay"></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>All metrics</h3><p>${d.rows.length} metrics in either run.</p></div><input class="input" id="cmp-filter" placeholder="Filter keys" style="width:220px" aria-label="Filter metrics"></div>
      <div class="table-wrap" style="max-height:560px"><table class="table" id="cmp-all"><thead><tr><th>Metric</th><th class="num">A</th><th class="num">B</th><th class="num">Delta</th></tr></thead>
      <tbody>${d.rows.map((r) => html`<tr data-k="${r.metric.toLowerCase()}"><td class="mono">${r.metric}</td><td class="num">${num(r.a, 4)}</td><td class="num">${num(r.b, 4)}</td><td class="num">${signed(r.delta, 4)}</td></tr>`)}</tbody></table></div></div>`);
  $('#cmp-filter', el).addEventListener('input', (evt) => {
    const q = evt.target.value.trim().toLowerCase();
    el.querySelectorAll('#cmp-all tbody tr').forEach((tr) => { tr.hidden = q && !tr.dataset.k.includes(q); });
  });

  const [suiteA, suiteB] = await Promise.all([suiteFor(a), suiteFor(b)]);
  if (suiteA && suiteB) {
    const byIdA = Object.fromEntries(suiteA.attackers.map((x) => [x.id, x]));
    const byIdB = Object.fromEntries(suiteB.attackers.map((x) => [x.id, x]));
    const common = suiteA.attackers.map((x) => x.id).filter((id) => byIdB[id]);
    if (common.length) {
      $('#roc-overlay-card', el).classList.remove('hidden');
      const defaultId = common.includes('a1_w0.5') ? 'a1_w0.5' : common[0];
      mount($('#roc-overlay-pick', el), common.map((id) => html`<option ${id === defaultId ? raw('selected') : ''}>${id}</option>`));
      const drawOverlay = () => {
        const id = $('#roc-overlay-pick', el).value;
        lineChart($('#roc-overlay', el), {
          series: [
            { name: `A: ${d.a.id}`, color: SERIES[0], points: byIdA[id].roc },
            { name: `B: ${d.b.id}`, color: SERIES[1], points: byIdB[id].roc },
          ],
          xDomain: [0, 1], yDomain: [0, 1], xLabel: 'false positive rate', yLabel: 'true positive rate',
          diagonal: true, snap: false, xFormat: (v) => num(v, 2), yFormat: (v) => num(v, 2), aria: `${id} ROC, A vs B`,
        });
      };
      $('#roc-overlay-pick', el).addEventListener('change', drawOverlay);
      drawOverlay();
    }
  }

  $('#export', el).addEventListener('click', () => {
    const lines = ['metric,a,b,delta', ...d.rows.map((r) => [r.metric, r.a ?? '', r.b ?? '', r.delta ?? ''].join(','))];
    download(`${d.a.id}_vs_${d.b.id}.csv`, lines.join('\n') + '\n', 'text/csv');
  });
}

// ----------------------------------------------------------------- sweep

function parseValues(text) {
  return text.split(',').map((t) => t.trim()).filter(Boolean).map((t) => {
    if (t === 'true') return true;
    if (t === 'false') return false;
    if (t === 'null') return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : t;
  });
}

export async function sweepView(el, { id }) {
  const [m, all] = await Promise.all([meta(), outputs(true)]);
  const sweeps = all.filter((o) => o.kind === 'sweep');
  if (id) return sweepResult(el, id, sweeps);
  const runs = runsOnly(all);
  mount(el, html`
    ${pageHead('Parameter sweep', 'Vary one parameter across values and inspect privacy and performance trade-offs as separate charts, without collapsing them onto one axis.', storedPicker(sweeps, 'sweep'))}
    <div class="grid g3">
      <div class="card card-body field"><label for="src">Base configuration</label>${sourcePicker('src', runs)}</div>
      <div class="card card-body field"><label for="param">Sweep parameter</label>
        <select class="select" id="param">${m.sweepable.map((p) => html`<option ${p === 'mix_delay_ms' ? raw('selected') : ''}>${p}</option>`)}</select>
        <div class="hint">Any scalar ExperimentConfig field, as <span class="mono">atl sweep --param</span> takes it.</div></div>
      <div class="card card-body field"><label for="values">Values</label><input class="input mono" id="values" value="10, 50, 100, 250">
        <div class="hint">Comma separated. Each value is one full emulator run; make sure the base config enables the mechanism being swept.</div></div>
    </div>
    <div class="card card-body" style="margin-top:16px; max-width:420px">${outDirField('out-dir', 'results/<base name>_sweep_<param>/')}</div>
    <div class="row" style="margin-top:16px">${startButton('Run sweep')}<span class="hint" id="cost"></span></div>
    <div id="job-error" style="margin-top:12px"></div>`);
  wireSourcePicker(el, 'src');
  wireStored(el, 'sweep');
  const cost = () => { $('#cost', el).textContent = `${parseValues($('#values', el).value).length} runs, one after another.`; };
  $('#values', el).addEventListener('input', cost);
  cost();
  $('#go', el).addEventListener('click', async () => {
    try {
      const source = await readSource(el, 'src');
      await startJob(el, '/api/sweep', { source, param: $('#param', el).value, values: parseValues($('#values', el).value), out_dir: readOutDir(el, 'out-dir') });
    } catch (e) {
      mount($('#job-error', el), errorBox(e));
    }
  });
}

async function sweepResult(el, id, sweeps) {
  const d = await api(`/api/outputs/${enc(id)}`);
  const p = d.param;
  const rows = d.rows;
  const numericKeys = rows.length ? Object.keys(rows[0]).filter((k) => k !== p && rows.some((r) => typeof r[k] === 'number')) : [];
  const corr = numericKeys.filter((k) => /tpr_at_fpr|auc|mu_hat|lpsi|compromise|accuracy|correlation/.test(k));
  let metric = corr.find((k) => k === 'a1_w0.5_tpr_at_fpr_0.001') || corr.find((k) => k === 'tpr_at_fpr_0.001') || corr[0] || numericKeys[0];
  let cost = numericKeys.includes('oneway_delay_p95_s') ? 'oneway_delay_p95_s' : numericKeys[0];
  const xs = rows.map((r) => r[p]);
  const numericX = xs.every((x) => typeof x === 'number');
  const pts = (k) => rows.map((r, i) => [numericX ? r[p] : i, r[k]]).filter((q) => typeof q[1] === 'number');
  const opt = (keys, v) => keys.map((k) => html`<option ${k === v ? raw('selected') : ''}>${k}</option>`);

  mount(el, html`
    ${pageHead(`Sweep of ${p}`, `${rows.length} values${d.base ? ` on ${d.base}` : ''}. Each row is a separately reproducible configuration.`,
      html`${storedPicker(sweeps, 'sweep', id)}<a class="btn" href="#/artifacts/${id}">Evidence</a><a class="btn primary" href="#/sweep">New sweep</a>`)}
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Correlation outcome</h3><p id="m-label"></p></div><select class="select" id="pick-m" style="width:auto" aria-label="Outcome metric">${opt(corr.length ? corr : numericKeys, metric)}</select></div><div class="card-body"><div id="c1"></div></div></div>
      <div class="card"><div class="card-head"><div><h3>Performance cost</h3><p id="c-label"></p></div><select class="select" id="pick-c" style="width:auto" aria-label="Cost metric">${opt(numericKeys, cost)}</select></div><div class="card-body"><div id="c2"></div></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Sweep table</h3><p>Open a row for that point's full results.</p></div></div><div class="table-wrap" id="tbl"></div></div>`);
  wireStored(el, 'sweep');
  const draw = () => {
    $('#m-label', el).textContent = pretty(metric);
    $('#c-label', el).textContent = pretty(cost);
    const common = { markers: true, xLabel: p, xTicks: numericX ? xs : xs.map((_, i) => i), xFormat: numericX ? (v) => num(v, 2) : (i) => String(xs[i]) };
    lineChart($('#c1', el), { ...common, series: [{ name: metric, color: SERIES[0], points: pts(metric) }], yFormat: (v) => fmtMetric(metric, v), aria: metric });
    lineChart($('#c2', el), { ...common, series: [{ name: cost, color: SERIES[1], points: pts(cost) }], yFormat: (v) => fmtMetric(cost, v), aria: cost });
    mount($('#tbl', el), html`<table class="table"><thead><tr><th>${p}</th><th class="num">${metric}</th><th class="num">${cost}</th><th class="num">Delivery</th><th>Evidence</th></tr></thead>
      <tbody>${rows.map((r, i) => html`<tr><td class="mono">${String(r[p])}</td><td class="num">${fmtMetric(metric, r[metric])}</td><td class="num">${fmtMetric(cost, r[cost])}</td><td class="num">${pct(r.delivery_rate)}</td>
        <td>${d.points[i] ? html`<a class="link" href="#/results/${id}/points/${d.points[i]}">Open</a>` : html`<span class="muted">CLI sweep, not stored</span>`}</td></tr>`)}</tbody></table>`);
  };
  $('#pick-m', el).addEventListener('change', (evt) => { metric = evt.target.value; draw(); });
  $('#pick-c', el).addEventListener('change', (evt) => { cost = evt.target.value; draw(); });
  draw();
}

// ---------------------------------------------------------------- paired

const VERDICT = {
  meaningful_effect: ['Meaningful effect', 'The 95% interval excludes zero and the mean difference is at least the margin. This is an effect classification, not a software pass.', ''],
  no_meaningful_effect: ['No meaningful effect', 'The whole 95% interval lies inside the equivalence region.', ''],
  inconclusive: ['Inconclusive', 'The interval crosses the edge of the equivalence region. More seeds, or a margin chosen for the question, are needed to classify it.', 'amber'],
};
const ICON = {
  '': '<svg viewBox="0 0 24 24" fill="none" stroke="var(--good-ink)" stroke-width="2.4"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
  amber: '<svg viewBox="0 0 24 24" fill="none" stroke="var(--warn-ink)" stroke-width="2.4"><path d="M12 7v6M12 16.5v.5"/><circle cx="12" cy="12" r="9.5"/></svg>',
  red: '<svg viewBox="0 0 24 24" fill="none" stroke="var(--bad-ink)" stroke-width="2.4"><path d="M7 7l10 10M17 7L7 17"/></svg>',
};

export async function pairedView(el, { id, query }) {
  const all = await outputs(true);
  const paireds = all.filter((o) => o.kind === 'paired');
  if (id) return pairedResult(el, id, paireds);
  const runs = runsOnly(all);
  mount(el, html`
    ${pageHead('Paired multi-seed analysis', 'Estimate a treatment effect across matched seeds and compare its interval against an explicit equivalence margin.', storedPicker(paireds, 'analysis'))}
    <div class="grid g2">
      <div class="card card-body field"><label for="ref">Reference</label>${sourcePicker('ref', runs, { selected: query.get('ref') || '' })}</div>
      <div class="card card-body field"><label for="treat">Treatment</label>${sourcePicker('treat', runs, { selected: query.get('treat') || '' })}</div>
    </div>
    <div class="card card-body form-grid" style="margin-top:16px; grid-template-columns:repeat(4,minmax(0,1fr))">
      <div class="field"><label for="first">First seed</label><input class="input" id="first" value="1" inputmode="numeric"></div>
      <div class="field"><label for="count">Seeds</label><input class="input" id="count" value="12" inputmode="numeric"><div class="hint">Or list them below.</div></div>
      <div class="field"><label for="metric">Metric</label><input class="input mono" id="metric" value="tpr_at_fpr_0.001" list="metric-keys"><datalist id="metric-keys"></datalist></div>
      <div class="field"><label for="margin">Equivalence margin</label><input class="input" id="margin" value="0.05" inputmode="decimal"><div class="hint">Fix it before looking at results.</div></div>
      <div class="field wide"><label for="seed-list">Explicit seed list</label><input class="input mono" id="seed-list" placeholder="optional, e.g. 11, 12, 13"></div>
    </div>
    <div class="card card-body" style="margin-top:16px; max-width:420px">${outDirField('out-dir', 'results/<reference>_vs_<treatment>_paired/')}</div>
    <div class="row" style="margin-top:16px">${startButton('Run paired analysis')}<span class="hint" id="cost"></span></div>
    <div id="job-error" style="margin-top:12px"></div>`);
  wireSourcePicker(el, 'ref');
  wireSourcePicker(el, 'treat');
  wireStored(el, 'paired');
  if (query.get('treat') && !query.get('ref')) $('#ref', el).selectedIndex = 0;
  if (query.get('ref') && !query.get('treat')) {
    const t = $('#treat', el);
    const other = [...t.options].find((o) => o.value !== `run:${query.get('ref')}` && o.value.startsWith('run:'));
    if (other) t.value = other.value;
  }
  const seeds = () => {
    const list = $('#seed-list', el).value.trim();
    if (list) return list.split(',').map((x) => Number(x.trim())).filter((x) => Number.isInteger(x));
    const first = Number($('#first', el).value), n = Number($('#count', el).value);
    return Number.isInteger(first) && Number.isInteger(n) && n > 0 ? [...Array(n).keys()].map((i) => first + i) : [];
  };
  const cost = () => { $('#cost', el).textContent = `${seeds().length} seeds, ${2 * seeds().length} runs, one after another.`; };
  el.addEventListener('input', cost);
  cost();
  // Suggest metric keys from the reference run, when it is a stored one.
  const suggest = async () => {
    const v = $('#ref', el).value;
    if (!v.startsWith('run:')) return;
    try {
      const d = await api(`/api/outputs/${enc(v.slice(4))}`);
      mount($('#metric-keys', el), Object.keys(d.metrics).filter((k) => typeof d.metrics[k] === 'number').map((k) => html`<option value="${k}">`));
    } catch { /* suggestions are optional */ }
  };
  $('#ref', el).addEventListener('change', suggest);
  suggest();
  $('#go', el).addEventListener('click', async () => {
    try {
      const [reference, treatment] = [await readSource(el, 'ref'), await readSource(el, 'treat')];
      await startJob(el, '/api/paired', { reference, treatment, seeds: seeds(), metric: $('#metric', el).value.trim(), margin: Number($('#margin', el).value), out_dir: readOutDir(el, 'out-dir') });
    } catch (e) {
      mount($('#job-error', el), errorBox(e));
    }
  });
}

async function pairedResult(el, id, paireds) {
  const d = await api(`/api/outputs/${enc(id)}`);
  const s = d.summary;
  const [title, text, color] = VERDICT[s.classification] || [s.classification, '', 'amber'];
  const rows = d.rows || [];
  const refKey = s.reference, treatKey = s.treatment;
  mount(el, html`
    ${pageHead('Paired multi-seed analysis', `${s.reference} vs ${s.treatment} on ${s.metric}.`,
      html`${storedPicker(paireds, 'analysis', id)}<a class="btn" href="#/artifacts/${id}">Evidence</a>
           <a class="btn" href="/api/outputs/${enc(id)}/report.pdf" download>Download PDF</a>
           <a class="btn primary" href="#/paired">New analysis</a>`)}
    <div class="grid g4">
      ${metricCard('Seeds', num(s.n_pairs), 'matched reference and treatment')}
      ${metricCard('Mean paired effect', signed(s.mean_delta), 'treatment minus reference')}
      ${metricCard('95% CI', `[${num(s.ci_low)}, ${num(s.ci_high)}]`, 'bootstrap over seed pairs')}
      ${metricCard('Equivalence margin', `+/-${num(s.margin)}`, 'pre-specified')}
    </div>
    <div class="verdict ${color}" style="margin:16px 0">${raw(ICON[color])}<div><h4>${title}</h4><p>${text}</p></div></div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>Matched-seed outcomes</h3><p>Reference and treatment joined within each seed.</p></div></div><div class="card-body"><div id="slope"></div></div></div>
      <div class="card"><div class="card-head"><div><h3>Paired difference interval</h3><p>Shaded region is the +/-${num(s.margin)} equivalence margin.</p></div></div><div class="card-body"><div id="interval"></div></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Analysis definition</h3><p>The inferential choices, kept beside the result.</p></div></div>
      <div class="card-body grid g2" style="gap:0 28px">
        <div class="summary-row"><span>Reference</span><span>${s.reference}</span></div><div class="summary-row"><span>Treatment</span><span>${s.treatment}</span></div>
        <div class="summary-row"><span>Metric</span><span class="mono">${s.metric}</span></div><div class="summary-row"><span>Seeds</span><span class="mono">${rows.map((r) => r.seed).join(', ')}</span></div>
        <div class="summary-row"><span>CI method</span><span>paired bootstrap, 10,000 resamples</span></div><div class="summary-row"><span>Equivalence margin</span><span>+/-${num(s.margin)}</span></div>
      </div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Per-seed values</h3></div></div><div class="table-wrap"><table class="table">
      <thead><tr><th>Seed</th><th class="num">${refKey}</th><th class="num">${treatKey}</th><th class="num">Delta</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="mono">${r.seed}</td><td class="num">${num(r[refKey])}</td><td class="num">${num(r[treatKey])}</td><td class="num">${signed(r.delta)}</td></tr>`)}</tbody></table></div></div>`);
  wireStored(el, 'paired');
  const ok = rows.filter((r) => typeof r[refKey] === 'number' && typeof r[treatKey] === 'number');
  slopeChart($('#slope', el), { seeds: ok.map((r) => r.seed), ref: ok.map((r) => r[refKey]), treat: ok.map((r) => r[treatKey]), refName: refKey, treatName: treatKey });
  intervalChart($('#interval', el), { mean: s.mean_delta, lo: s.ci_low, hi: s.ci_high, margin: s.margin });
}

// --------------------------------------------------------------- predict

export async function predictView(el, { query }) {
  const runs = runsOnly(await outputs(true));
  mount(el, html`
    ${pageHead('Analytical prediction', 'Estimate expected correlation behaviour without running relays, then set the model output against measured evidence.')}
    <div class="card card-body row" style="align-items:flex-end">
      <div class="field" style="flex:1; min-width:240px"><label for="src">Configuration</label>${sourcePicker('src', runs, { selected: query.get('run') || '' })}</div>
      ${startButton('Run prediction')}
    </div>
    <div id="job-error" style="margin-top:12px"></div>
    <div id="out" style="margin-top:16px"></div>`);
  wireSourcePicker(el, 'src');
  const go = async () => {
    const out = $('#out', el);
    mount($('#job-error', el), '');
    mount(out, html`<div class="card empty">Computing...</div>`);
    try {
      const src = await readSource(el, 'src');
      const r = await api('/api/predict', { method: 'POST', body: src });
      const s = r.summary;
      mount(out, html`
        <div class="grid g4" style="margin-bottom:16px">
          ${metricCard('Observed share', pct(r.predictions.model_observed_share), 'of real traffic the observer sees')}
          ${metricCard('Paths', s.paths > 1 ? `${s.paths}, ${s.split}` : '1', `${s.merge}`)}
          ${metricCard('Traffic', `${s.traffic} ${num(s.real_rate, 1)}/s`, s.mix === 'none' ? 'no mixing' : `${s.mix} mixing`)}
          ${metricCard('Target FPR', num(r.fpr), `psi ${r.psi}, base rate ${r.base_rate}`)}
        </div>
        ${r.measured ? '' : html`<div class="callout" style="margin-bottom:16px">Pick a stored run to see the model set against its measured values.</div>`}
        <div id="model"></div>`);
      modelTab($('#model', out), r.measured, r.predictions);
    } catch (e) {
      mount(out, '');
      mount($('#job-error', el), errorBox(e));
    }
  };
  $('#go', el).addEventListener('click', go);
  if (query.get('run')) go();
}

// -------------------------------------------------------------- fidelity

export async function fidelityView(el, { id, query }) {
  const all = await outputs(true);
  const stored = all.filter((o) => o.kind === 'fidelity');
  if (id) return fidelityResult(el, id, stored);
  const runs = runsOnly(all);
  mount(el, html`
    ${pageHead('Timing fidelity', 'Check whether host-induced timing noise is small next to the timing scale the experiment is trying to measure.', storedPicker(stored, 'check'))}
    <div class="grid g2">
      <div class="card card-body field"><label for="src">Experiment</label>${sourcePicker('src', runs, { selected: query.get('run') || '' })}</div>
      <div class="card card-body field"><label for="limit">Limit fraction</label><input class="input" id="limit" value="0.1" inputmode="decimal">
        <div class="hint">Passes when host noise at P95 is at most this fraction of the reference timing scale.</div></div>
    </div>
    <div class="row" style="margin-top:16px">${startButton('Run fidelity check')}<span class="hint">Reruns the cell with mixing off and no adversaries; in wave mode only two waves.</span></div>
    <div id="job-error" style="margin-top:12px"></div>
    ${methodCard()}`);
  wireSourcePicker(el, 'src');
  wireStored(el, 'fidelity');
  $('#go', el).addEventListener('click', async () => {
    try {
      const source = await readSource(el, 'src');
      await startJob(el, '/api/fidelity', { source, limit_fraction: Number($('#limit', el).value) });
    } catch (e) {
      mount($('#job-error', el), errorBox(e));
    }
  });
}

function methodCard() {
  return html`<div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Method</h3><p>What the check establishes.</p></div></div>
    <div class="card-body"><ol class="hint" style="margin:0;padding-left:18px;line-height:1.9">
      <li>Rerun the configuration with relay mixing switched off; topology, load and link settings unchanged.</li>
      <li>Measure the remaining entry-to-exit delay, which is host and link time.</li>
      <li>Subtract the configured link latency and compare the P95 residual with the smallest per-hop mixing delay (or, with no mixing, the smallest attacker bin width).</li>
      <li>Flag the cell when the residual exceeds the limit.</li></ol>
      <p class="hint">It does not establish external validity. It only guards against a loaded local host dominating the timing under study.</p></div></div>`;
}

async function fidelityResult(el, id, stored) {
  const d = await api(`/api/outputs/${enc(id)}`);
  const r = d.summary;
  const ratio = r.reference_scale_s ? r.host_noise_p95_s / r.reference_scale_s : null;
  const color = r.passes ? '' : 'red';
  const bars = [['Host residual (P95)', r.host_noise_p95_s, 'var(--s1)'], ['Allowed envelope', r.limit_s, 'var(--faint)'], ['Reference timing scale', r.reference_scale_s, 'var(--s2)']];
  const top = Math.max(...bars.map((b) => Math.abs(b[1] || 0))) || 1;
  mount(el, html`
    ${pageHead('Timing fidelity', `${r.experiment}: ${r.probe_sessions} probe sessions with mixing off.`,
      html`${storedPicker(stored, 'check', id)}<a class="btn" href="#/artifacts/${id}">Evidence</a><a class="btn primary" href="#/fidelity">New check</a>`)}
    <div class="verdict ${color}" style="margin-bottom:16px">${raw(ICON[color])}<div><h4>${r.passes ? 'Pass: host noise is within the limit' : 'Fail: host noise exceeds the limit'}</h4>
      <p>The P95 residual delay is ${ratio === null ? 'n/a' : pct(ratio)} of the ${ms(r.reference_scale_s)} ${r.reference}; the limit is ${pct(r.limit_fraction, 0)}.${r.passes ? '' : ' Reduce concurrent sessions or use a less loaded host before reading timing-sensitive results.'}</p></div></div>
    <div class="grid g4">
      ${metricCard('Residual host P95', ms(r.host_noise_p95_s), 'mixing disabled')}
      ${metricCard('Reference scale', ms(r.reference_scale_s), r.reference)}
      ${metricCard('Noise ratio', ratio === null ? 'n/a' : pct(ratio), 'residual / reference')}
      ${metricCard('Threshold', `at most ${pct(r.limit_fraction, 0)}`, `${ms(r.limit_s)} allowed`)}
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>Scale comparison</h3><p>Host noise should stay small next to the timing effect under study.</p></div></div>
        <div class="card-body stack">${bars.map(([label, v, c]) => html`<div><div class="summary-row" style="border:0;padding-bottom:4px"><span>${label}</span><span>${ms(v)}</span></div>
          <div class="progress" style="height:12px"><span style="width:${Math.max(0, (v || 0) / top) * 100}%;background:${raw(c)}"></span></div></div>`)}</div></div>
      <div class="card"><div class="card-head"><div><h3>Probe measurements</h3></div></div><div class="card-body">
        <div class="summary-row"><span>One-way delay P50</span><span>${ms(r.oneway_delay_p50_s)}</span></div>
        <div class="summary-row"><span>One-way delay P95</span><span>${ms(r.oneway_delay_p95_s)}</span></div>
        <div class="summary-row"><span>One-way delay P99</span><span>${ms(r.oneway_delay_p99_s)}</span></div>
        <div class="summary-row"><span>Configured link latency (path)</span><span>${ms(r.configured_link_latency_s)}</span></div>
        <div class="summary-row"><span>Delivery rate</span><span>${pct(r.delivery_rate)}</span></div>
        <div class="summary-row"><span>Original mixing</span><span>${r.mix_strategy}</span></div>
        <div class="summary-row"><span>Concurrency</span><span>${r.max_concurrent_sessions ? `waves of ${r.max_concurrent_sessions}` : `all ${r.num_sessions} at once`}</span></div>
      </div></div>
    </div>
    ${methodCard()}`);
  wireStored(el, 'fidelity');
}

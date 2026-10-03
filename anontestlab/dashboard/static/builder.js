// Experiment builder. The form edits the flat config dict (one key per
// ExperimentConfig field); the server turns it into the runnable YAML spec
// and validates it on every change (/api/spec), so the YAML shown here is
// exactly what `atl run` would read.
import {
  $, $$, api, copy, download, errorBox, html, infoIcon, job, local, meta, mount, num, outDirField, pageHead,
  raw, readOutDir, toast,
} from './core.js';
import { pathDiagram } from './charts.js';

const ADVERSARY_INFO = {
  global_observer: ['Global observer', 'Binned-count Pearson correlation of entry and exit timing.'],
  correlation_suite: ['Correlation suite (A0 to A3)', 'Several training-free attackers on one shared calibration/test split.'],
  path_compromise: ['Path compromise', 'Monte Carlo estimate of how often compromised relays sit on a path.'],
  hop_depth: ['Hop depth', 'Infers a relay\'s position in the path from what it observes.'],
  watermark: ['Watermark', 'A hop-1 relay delays every k-th real packet; checks if the pattern survives to egress.'],
};

const isMulti = (c) => (c.extra_paths || []).length > 0;
const has = (c, a) => (c.adversaries || []).includes(a);

// Field declarations per section. type: text | int | float | optint |
// optfloat | list | optlist | bool | select | seg. `show` hides a field
// whose value the current configuration would ignore.
const SECTIONS = [
  {
    id: 'experiment', title: 'Experiment identity', step: 'Experiment',
    desc: 'Seeds reproduce controlled choices (paths, schedules); host scheduling and socket timing stay non-deterministic.',
    fields: [
      { k: 'name', label: 'Experiment name', type: 'text', hint: 'Results go to results/<name>/. Letters, digits, ".", "_", "-".' },
      { k: 'seed', label: 'Seed', type: 'int', hint: 'Path selection and traffic scheduling use this seed.', random: true },
      { k: 'num_sessions', label: 'Sessions', type: 'int', tip: 'How many independent sessions this experiment runs; each is one circuit lifetime.' },
      { k: 'max_concurrent_sessions', label: 'Max concurrent sessions', type: 'optint', hint: 'Blank runs every session at once. Set it to run in waves; timestamps then become per-session.' },
      { k: 'duration_s', label: 'Duration per session', type: 'float', unit: 's', tip: 'How long each session emits traffic for, before the grace period.' },
      { k: 'grace_period_s', label: 'Grace period', type: 'float', unit: 's', hint: 'Wait for in-flight cells after the last emission. Raise it when mixing adds delay.' },
      { k: 'mode', label: 'Mode', type: 'select', opts: ['custom', 'tor_like'], hint: 'Informational preset marker only.' },
      { k: 'baseline', label: 'Baseline spec', type: 'opttext', hint: 'Optional path to a baseline YAML, diffed into report.md. Relative paths resolve from the dashboard\'s working directory.' },
    ],
  },
  {
    id: 'network', title: 'Network conditions', step: 'Network',
    desc: 'Relay pool size and link characteristics, applied inside each relay\'s forwarding path (no tc or netem).',
    fields: [
      { k: 'num_nodes', label: 'Relays', type: 'int', hint: 'At most 254 (loopback subnet).' },
      { k: 'num_as_groups', label: 'AS groups', type: 'int', hint: 'More than 1 enables the AS-level partial observer.' },
      { k: 'link_latency_ms', label: 'Latency per hop', type: 'float', unit: 'ms', tip: 'One-way propagation delay applied at every hop, before jitter.' },
      { k: 'link_jitter_ms', label: 'Jitter', type: 'float', unit: 'ms', tip: 'Random variation added on top of the base latency, per packet.' },
      { k: 'link_loss_probability', label: 'Packet loss probability', type: 'float', hint: 'Between 0 and 1.' },
      { k: 'link_bandwidth_kbps', label: 'Bandwidth', type: 'optfloat', unit: 'kbps', hint: 'Blank means unlimited.' },
      { k: 'link_heterogeneous', label: 'Heterogeneous nodes', type: 'bool', hint: 'Each relay scales the base values by its own factor.' },
      { k: 'link_per_edge', label: 'Per-edge factors', type: 'bool', hint: 'Also scales each relay-to-peer send by a pair factor. Forward direction only.' },
      { k: 'link_heterogeneity_spread', label: 'Heterogeneity spread', type: 'float', hint: 'Factor ~ Uniform(1 - spread, 1 + spread), spread in [0, 1).', show: (c) => c.link_heterogeneous || c.link_per_edge },
    ],
    note: (c) => (c.link_per_edge ? html`<div class="callout warn wide">Per-edge conditions model the configured forward direction only. Keep that in mind when reading asymmetric timing results.</div>` : ''),
  },
  {
    id: 'routing', title: 'Routing and multipath', step: 'Routing',
    desc: 'Paths are selected per session. The diagram shows the configured design, not executed paths.',
    custom: 'paths',
    fields: [
      { k: 'merge', label: 'Path merge', type: 'seg', opts: 'merge', show: isMulti, hint: 'common_exit ends every leg at one exit relay (Conflux style).' },
      { k: 'split_strategy', label: 'Traffic split', type: 'select', opts: 'split_strategy', show: isMulti, tip: 'How real traffic is divided across paths each session.' },
      { k: 'split_weights', label: 'Per-leg weights', type: 'optlist', show: (c) => isMulti(c) && ['iid', 'batch', 'round_robin'].includes(c.split_strategy), hint: 'One positive value per path, comma separated. Blank splits evenly.' },
      { k: 'split_batch_mean_s', label: 'Mean batch duration', type: 'float', unit: 's', show: (c) => isMulti(c) && c.split_strategy === 'batch', tip: 'Mean duration of one batch before the scheduler switches legs.' },
      { k: 'split_leg_rtt_ms', label: 'Nominal RTT per leg', type: 'optlist', unit: 'ms', show: (c) => isMulti(c) && c.split_strategy === 'latency', hint: 'Blank uses 50, 100, 150, ...' },
      { k: 'split_leg_window', label: 'Cells in flight per leg', type: 'int', show: (c) => isMulti(c) && c.split_strategy === 'latency', tip: 'How many cells a leg may have in flight within one RTT before the scheduler holds back.' },
    ],
    note: (c) => (isMulti(c) && c.split_strategy === 'latency' ? html`<div class="callout wide">Nominal RTT guides the scheduler only; it does not change the emulated link latency.</div>` : ''),
  },
  {
    id: 'traffic', title: 'Traffic', step: 'Traffic',
    desc: 'Real traffic generation is separate from the cover-traffic policy.',
    fields: [
      { k: 'real_traffic_distribution', label: 'Real traffic', type: 'seg', opts: 'traffic_distribution', tip: 'Inter-arrival distribution for genuine traffic.' },
      { k: 'real_rate', label: 'Real rate', type: 'float', unit: 'pkt/s', tip: 'Mean real packets per second (or per burst, for the burst distribution).' },
      { k: 'burst_mean_cells', label: 'Mean cells per burst', type: 'float', show: (c) => c.real_traffic_distribution === 'burst', tip: 'Average number of cells in one burst.' },
      { k: 'burst_gap_ms', label: 'Gap within a burst', type: 'float', unit: 'ms', show: (c) => c.real_traffic_distribution === 'burst', tip: 'Gap between cells within the same burst.' },
      { k: 'cover_rate', label: 'Cover rate', type: 'float', unit: 'pkt/s', hint: '0 disables cover traffic.' },
      { k: 'cover_traffic_distribution', label: 'Cover distribution', type: 'select', opts: 'traffic_distribution', show: (c) => c.cover_rate > 0, tip: 'Inter-arrival distribution for cover traffic, independent of real traffic.' },
      { k: 'cover_drop_mode', label: 'Cover disposal', type: 'seg', opts: 'cover_drop_mode', show: (c) => c.cover_rate > 0, hint: 'random_hop: one hop per cover cell absorbs it.' },
      { k: 'cover_drop_probability', label: 'Drop probability per hop', type: 'float', show: (c) => c.cover_rate > 0 && c.cover_drop_mode === 'per_hop', tip: 'Chance a cover cell is dropped at each hop it passes.' },
    ],
  },
  {
    id: 'defenses', title: 'Defenses', step: 'Defenses',
    desc: 'Relay mixing and fixed-rate shaping are independent mechanisms.',
    fields: [
      { k: 'mix_strategy', label: 'Relay mixing', type: 'seg', opts: 'mix_strategy', hint: 'Applied at every hop to data cells.' },
      { k: 'mix_delay_ms', label: 'Delay per hop', type: 'float', unit: 'ms', show: (c) => ['constant', 'exponential'].includes(c.mix_strategy), hint: 'The constant delay, or the exponential mean.' },
      { k: 'pool_interval_ms', label: 'Flush interval', type: 'float', unit: 'ms', show: (c) => c.mix_strategy === 'pool', tip: 'How often the pool releases its held cells.' },
      { k: 'pool_release_probability', label: 'Release probability', type: 'float', show: (c) => c.mix_strategy === 'pool', hint: '1 empties the pool each flush; below 1 keeps a binomial pool.' },
      { k: 'pool_interval_jitter', label: 'Interval jitter', type: 'float', show: (c) => c.mix_strategy === 'pool', hint: 'Flush interval x (1 +/- U(jitter)), in [0, 1).' },
      { k: 'cell_size', label: 'Pad cells to', type: 'optint', unit: 'bytes', hint: 'Blank disables padding.' },
      { k: 'traffic_mode', label: 'Send schedule', type: 'seg', opts: 'traffic_mode', tip: 'variable sends cells as traffic demands; fixed_rate sends on a fixed wire schedule regardless of demand.' },
      { k: 'fixed_rate', label: 'Fixed wire rate', type: 'float', unit: 'pkt/s', show: (c) => c.traffic_mode === 'fixed_rate', tip: 'Cells per second sent on the wire when the schedule is fixed_rate.' },
    ],
  },
  {
    id: 'crypto', title: 'Cryptography', step: 'Crypto',
    desc: 'Per-hop ECDHE handshake with a configurable AEAD.',
    fields: [
      { k: 'crypto_algorithm', label: 'AEAD', type: 'select', opts: 'crypto_algorithm', tip: 'Cipher for per-hop payload encryption.' },
      { k: 'crypto_keyexchange', label: 'Key exchange curve', type: 'select', opts: 'crypto_keyexchange', tip: 'Elliptic curve for the per-hop ECDHE handshake.' },
    ],
  },
  {
    id: 'adversary', title: 'Adversary', step: 'Adversary',
    desc: 'Every selected module scores the same run.',
    custom: 'adversaries',
    fields: [
      { k: 'observed_path_count', label: 'Observed paths', type: 'optint', show: (c) => isMulti(c) && c.num_as_groups <= 1, hint: 'Blank: the adversary sees every path.' },
      { k: 'observed_legs', label: 'Observed legs', type: 'optlist', int: true, show: isMulti, hint: 'Explicit 0-based leg indices; overrides observed paths.' },
      { k: 'egress_observation', label: 'Egress observation', type: 'seg', opts: 'egress_observation', show: isMulti, hint: 'merged: the exit side sees every leg\'s cells.' },
      { k: 'observed_as_count', label: 'Observed AS groups', type: 'optint', show: (c) => c.num_as_groups > 1, hint: 'Blank: all AS groups.' },
      { k: 'observer_calibration_fraction', label: 'Calibration fraction', type: 'float', hint: 'Share of sessions that choose thresholds; the rest are scored. 0 means in-sample for the global observer; the suite uses 0.5 then.' },
      { k: 'observer_bin_width_ms', label: 'Observer bin width', type: 'float', unit: 'ms', show: (c) => has(c, 'global_observer'), tip: 'Time bin width the global observer uses to correlate ingress and egress timing.' },
      { k: 'observer_classifier', label: 'Observer classifier', type: 'select', opts: 'observer_classifier', show: (c) => has(c, 'global_observer'), tip: 'Scoring method the global observer uses on binned timing.' },
      { k: 'observer_threshold', label: 'Observer threshold', type: 'float', show: (c) => has(c, 'global_observer'), tip: 'Decision threshold the global observer applies to its correlation score.' },
      { k: 'compromised_fraction', label: 'Compromised relay fraction', type: 'float', show: (c) => has(c, 'path_compromise'), tip: 'Share of relays treated as compromised in each Monte Carlo trial.' },
      { k: 'compromise_trials', label: 'Monte Carlo trials', type: 'int', show: (c) => has(c, 'path_compromise'), tip: 'Number of trials used to estimate path compromise probability.' },
      { k: 'watermark_period', label: 'Watermark period', type: 'int', show: (c) => has(c, 'watermark'), hint: 'Delay every k-th real packet; 0 disables.' },
      { k: 'watermark_delay_ms', label: 'Watermark delay', type: 'float', unit: 'ms', show: (c) => has(c, 'watermark'), tip: 'How long the watermarking relay delays each marked packet.' },
      { k: 'suite_bin_widths_s', label: 'Suite bin widths', type: 'list', unit: 's', show: (c) => has(c, 'correlation_suite'), tip: "Time bin widths A0/A1 score at; one TPR curve per width." },
      { k: 'suite_fpr_targets', label: 'Target FPRs', type: 'list', show: (c) => has(c, 'correlation_suite'), tip: 'False-positive rates the suite reports TPR at.' },
      { k: 'suite_lag_max_s', label: 'Lag search limit', type: 'optfloat', unit: 's', show: (c) => has(c, 'correlation_suite'), hint: 'Blank: max(2 s, P99 of added delay) + 0.5 s.' },
      { k: 'suite_psi', label: 'Confidence levels (psi)', type: 'list', show: (c) => has(c, 'correlation_suite'), tip: 'True-pair probabilities used for the confident-linkage calculation.' },
      { k: 'suite_base_rates', label: 'Base rates', type: 'list', show: (c) => has(c, 'correlation_suite'), tip: 'Assumed base rate of true pairs among all pairs, for confident linkage.' },
      { k: 'suite_window_quantiles', label: 'A3 window quantiles', type: 'list', show: (c) => has(c, 'correlation_suite'), tip: "Delay quantiles that set the A3 timing-window attacker's window width." },
      { k: 'suite_latency_floor_ms', label: 'A3 latency floor', type: 'float', unit: 'ms', show: (c) => has(c, 'correlation_suite'), tip: "Fixed floor added to A3's window, for processing and link time outside the delay model." },
      { k: 'suite_lr_step_ms', label: 'A2 time grid step', type: 'float', unit: 'ms', show: (c) => has(c, 'correlation_suite'), tip: "Time grid resolution for A2's likelihood-ratio search." },
    ],
  },
];

const ALL_FIELDS = SECTIONS.flatMap((s) => s.fields);

/** key -> { section, label } for every field the builder edits, plus the
 * handful of fields only reachable through a section's "custom" editor
 * (paths, adversaries) rather than a plain fields[] entry - path_length,
 * extra_paths and routing_strategy (routing), adversaries (adversary).
 * Exported so the Compare page can group and label its raw config diff
 * the same way the builder organizes these fields, instead of a flat,
 * alphabetized list of snake_case keys from one shared source of truth,
 * so the two can't drift apart. */
export const FIELD_INFO = Object.fromEntries([
  ...SECTIONS.flatMap((s) => s.fields.map((f) => [f.k, { section: s.title, label: f.label }])),
  ['routing_strategy', { section: 'Routing and multipath', label: 'Relay selection' }],
  ['path_length', { section: 'Routing and multipath', label: 'Hops' }],
  ['extra_paths', { section: 'Routing and multipath', label: 'Extra paths' }],
  ['adversaries', { section: 'Adversary', label: 'Adversary modules' }],
]);
export const SECTION_ORDER = SECTIONS.map((s) => s.title);

function fieldInput(f, c, options) {
  const v = c[f.k];
  const id = `f-${f.k}`;
  // The tooltip repeats the always-visible hint when there is one, so a
  // field never says two different things depending on whether you hover
  // or read; tip is only for fields with nothing below them yet.
  const tip = f.hint || f.tip;
  const icon = tip ? infoIcon(tip) : '';
  let control;
  if (f.type === 'bool') {
    return html`<div class="field" data-k="${f.k}"><label class="check"><input type="checkbox" id="${id}" data-field="${f.k}" ${v ? raw('checked') : ''}> ${f.label}</label>${icon}${f.hint ? html`<div class="hint">${f.hint}</div>` : ''}</div>`;
  }
  const opts = Array.isArray(f.opts) ? f.opts : options[f.opts] || [];
  if (f.type === 'select') {
    control = html`<select class="select" id="${id}" data-field="${f.k}">${opts.map((o) => html`<option value="${o}" ${o === v ? raw('selected') : ''}>${o}</option>`)}</select>`;
  } else if (f.type === 'seg') {
    control = html`<div class="seg" role="group" aria-label="${f.label}" data-seg="${f.k}">${opts.map((o) => html`<button type="button" data-value="${o}" aria-pressed="${o === v ? 'true' : 'false'}">${o}</button>`)}</div>`;
  } else {
    const text = Array.isArray(v) ? v.join(', ') : v === null || v === undefined ? '' : String(v);
    const mode = ['int', 'float', 'optint', 'optfloat'].includes(f.type) ? 'decimal' : 'text';
    const input = html`<input class="input" id="${id}" data-field="${f.k}" value="${text}" inputmode="${mode}" autocomplete="off" spellcheck="false">`;
    control = f.unit ? html`<div class="unit">${input}<span>${f.unit}</span></div>` : input;
    if (f.random) control = html`<div class="row" style="flex-wrap:nowrap">${control}<button class="btn" type="button" data-random="${f.k}">Random</button></div>`;
  }
  return html`<div class="field" data-k="${f.k}"><div class="label-row"><label for="${id}">${f.label}</label>${icon}</div>${control}${f.hint ? html`<div class="hint">${f.hint}</div>` : ''}<div class="hint field-err" style="color:var(--bad-ink)"></div></div>`;
}

// Parses an input's text for field f. Returns {ok, value} or {ok: false, msg}.
function parseField(f, text) {
  const t = text.trim();
  const optional = f.type.startsWith('opt');
  if (t === '' && optional) return { ok: true, value: null };
  if (f.type === 'text' || f.type === 'opttext') return t || !optional ? { ok: true, value: t } : { ok: true, value: null };
  if (f.type.endsWith('list')) {
    if (t === '') return { ok: false, msg: 'Give at least one value' };
    const parts = t.split(',').map((x) => x.trim()).filter(Boolean);
    const vals = parts.map(Number);
    if (vals.some((x) => !Number.isFinite(x))) return { ok: false, msg: 'Comma-separated numbers' };
    if (f.int && vals.some((x) => !Number.isInteger(x))) return { ok: false, msg: 'Whole numbers only' };
    return { ok: true, value: vals };
  }
  const n = Number(t);
  if (t === '' || !Number.isFinite(n)) return { ok: false, msg: 'Enter a number' };
  if (f.type.includes('int') && !Number.isInteger(n)) return { ok: false, msg: 'Enter a whole number' };
  return { ok: true, value: n };
}

function pathsEditor(c, options) {
  const paths = [{ strategy: c.routing_strategy, path_length: c.path_length }, ...(c.extra_paths || [])];
  const observed = c.observed_legs ? new Set(c.observed_legs)
    : c.observed_path_count ? new Set([...Array(c.observed_path_count).keys()]) : null;
  return html`
    <div class="grid g2 wide">
      <div class="stack" style="gap:10px">
        ${paths.map((p, i) => html`
          <div class="path-card">
            <div class="row"><b>Path ${i + 1}</b>${i > 0 ? html`<button class="btn small" type="button" data-remove-path="${i}">Remove</button>` : html`<span class="hint">leg 0</span>`}</div>
            <div class="form-grid">
              <div class="field"><label for="p-${i}-s">Relay selection</label>
                <select class="select" id="p-${i}-s" data-path="${i}" data-pk="strategy">${options.routing_strategy.map((o) => html`<option ${o === p.strategy ? raw('selected') : ''}>${o}</option>`)}</select></div>
              <div class="field"><label for="p-${i}-l">Hops</label>
                <input class="input" id="p-${i}-l" data-path="${i}" data-pk="path_length" value="${p.path_length}" inputmode="numeric"></div>
            </div>
          </div>`)}
        <div><button class="btn" type="button" data-add-path>Add path</button></div>
      </div>
      <div class="path-diagram">${raw(pathDiagram(paths.map((p) => ({ length: p.path_length })), { merge: c.merge, observed }))}</div>
    </div>`;
}

function adversaryEditor(c, options) {
  return html`
    <div class="grid g2 wide">
      ${options.adversaries.map((a) => {
        const [title, desc] = ADVERSARY_INFO[a] || [a, ''];
        return html`<label class="path-card" style="cursor:pointer">
          <span class="check"><input type="checkbox" data-adversary="${a}" ${has(c, a) ? raw('checked') : ''}> <b>${title}</b></span>
          <span class="hint">${desc}</span></label>`;
      })}
    </div>
    <div class="field wide" data-k="suite_attackers" ${has(c, 'correlation_suite') ? '' : raw('hidden')}>
      <div class="label">Suite attackers</div>
      <div class="row">${['a0', 'a1', 'a2', 'a3'].map((a) => html`<label class="check"><input type="checkbox" data-suite="${a}" ${(c.suite_attackers || []).includes(a) ? raw('checked') : ''}> ${a.toUpperCase()}</label>`)}</div>
      <div class="hint">A0 zero-lag correlation, A1 lag-aware correlation, A2 likelihood ratio with the known delay density, A3 timing-window matcher.</div>
    </div>`;
}

function summaryRows(c) {
  const paths = [c.path_length, ...(c.extra_paths || []).map((p) => p.path_length)];
  const rows = [
    ['Relays', c.num_nodes],
    ['Sessions', `${c.num_sessions}${c.max_concurrent_sessions ? `, waves of ${c.max_concurrent_sessions}` : ''}`],
    ['Paths', paths.length > 1 ? `${paths.length} (${paths.join(' + ')} hops)` : `1 x ${paths[0]}-hop`],
  ];
  if (paths.length > 1) rows.push(['Merge', c.merge], ['Split', c.split_strategy]);
  rows.push(['Traffic', `${c.real_traffic_distribution}, ${num(c.real_rate, 1)} pkt/s`]);
  rows.push(['Cover', c.cover_rate > 0 ? `${num(c.cover_rate, 1)} pkt/s` : 'off']);
  rows.push(['Mixing', c.mix_strategy === 'pool' ? `pool, ${num(c.pool_interval_ms, 0)} ms` : c.mix_strategy === 'none' ? 'none' : `${c.mix_strategy}, ${num(c.mix_delay_ms, 0)} ms`]);
  rows.push(['Shaping', `${c.traffic_mode}${c.cell_size ? `, ${c.cell_size} B cells` : ''}`]);
  rows.push(['AEAD', c.crypto_algorithm], ['Adversaries', (c.adversaries || []).join(', ') || 'none']);
  if (paths.length > 1) rows.push(['Observer', c.observed_legs ? `legs ${c.observed_legs.join(', ')}` : c.observed_path_count ? `${c.observed_path_count} of ${paths.length} paths` : 'all paths']);
  return rows;
}

export async function builderView(el, { query }) {
  const m = await meta();
  const options = m.options;
  let cfg;
  let sourceNote = '';
  try {
    if (query.get('from')) {
      const d = await api(`/api/outputs/${query.get('from').split('/').map(encodeURIComponent).join('/')}`);
      cfg = { ...d.config };
      sourceNote = `Loaded from run ${query.get('from')}.`;
    } else if (query.get('template') && m.templates[query.get('template')]) {
      cfg = { ...m.templates[query.get('template')] };
      sourceNote = `Started from the ${query.get('template').replace('example:', 'example ')} template.`;
    }
  } catch (e) {
    sourceNote = `Could not load: ${e.message}`;
  }
  if (!cfg) {
    cfg = local.get('atl.draft') || { ...m.templates.blank };
    if (local.get('atl.draft')) sourceNote = 'Restored your last draft.';
  }
  // Fill any field a stored config predates, so the form covers every key.
  cfg = { ...m.defaults, ...cfg };

  let yamlOverride = null; // set when the user edits YAML directly
  let lastSpec = null;
  let timer = null;

  function render() {
    mount(el, html`
      ${pageHead('New experiment', 'Configure the experimental assumptions first. Execution, adversary analysis and evidence stay tied to this configuration.',
        html`<label class="btn" for="import-file">Import YAML</label><input type="file" id="import-file" accept=".yaml,.yml,text/yaml" class="hidden">
             <a class="btn primary" href="#/new" data-goto="review">Review and run</a>`)}
      ${sourceNote ? html`<div class="callout" style="margin-bottom:16px">${sourceNote}</div>` : ''}
      <nav class="steps" aria-label="Builder sections">
        ${SECTIONS.map((s) => html`<a href="#/new" data-goto="${s.id}" data-step="${s.id}">${s.step}</a>`)}
        <a href="#/new" data-goto="review" data-step="review">Review</a>
      </nav>
      <div class="split">
        <div class="stack">
          ${SECTIONS.map((s, i) => html`
            <section class="card" id="sec-${s.id}">
              <div class="card-head"><div><h3>${i + 1}. ${s.title}</h3><p>${s.desc}</p></div></div>
              <div class="card-body form-grid">
                ${s.custom === 'paths' ? pathsEditor(cfg, options) : ''}
                ${s.custom === 'adversaries' ? adversaryEditor(cfg, options) : ''}
                ${s.fields.map((f) => fieldInput(f, cfg, options))}
                <div class="wide" data-note="${s.id}"></div>
              </div>
            </section>`)}
          <section class="card" id="sec-review">
            <div class="card-head"><div><h3>${SECTIONS.length + 1}. Review and run</h3><p>The runnable spec, exactly as <span class="mono">atl run</span> reads it.</p></div>
              <div class="actions">
                <button class="btn small" type="button" id="yaml-edit">Edit YAML</button>
                <button class="btn small" type="button" id="yaml-copy">Copy</button>
                <button class="btn small" type="button" id="yaml-dl">Download</button>
              </div></div>
            <div class="card-body stack">
              <div id="issues" class="issues"></div>
              <pre class="code" id="yaml-view"></pre>
              <div id="yaml-edit-box" class="stack hidden">
                <textarea class="textarea tall" id="yaml-text" spellcheck="false" aria-label="Experiment YAML"></textarea>
                <div class="row"><button class="btn" type="button" id="yaml-apply">Apply YAML to form</button><button class="btn" type="button" id="yaml-discard">Discard edits</button>
                <span class="hint">Running uses the edited YAML as written.</span></div>
              </div>
              <div style="max-width:420px">${outDirField('out-dir', `results/${cfg.name || 'experiment'}/`)}</div>
              <div class="row"><button class="btn primary" type="button" id="run-btn">Run experiment</button><span class="hint" id="run-hint"></span></div>
              <div id="run-error"></div>
            </div>
          </section>
        </div>
        <aside class="summary-box">
          <div class="card">
            <div class="card-head"><div><h3>Experiment summary</h3><p>Updates as the configuration changes.</p></div></div>
            <div class="card-body" id="summary"></div>
          </div>
          <div class="card card-body">
            <span class="badge amber">Model boundary</span>
            <p class="hint" style="margin:10px 0 0">Relays run as local processes on this host, and link conditions are emulated inside them. There is no geographic relay placement and no Tor guard or exit policy. Seeds fix controlled choices only; host timing still varies between runs.</p>
          </div>
        </aside>
      </div>`);
    wire();
    refresh();
  }

  function applyVisibility() {
    for (const f of ALL_FIELDS) {
      const w = el.querySelector(`.field[data-k="${f.k}"]`);
      if (w) w.classList.toggle('hidden', f.show ? !f.show(cfg) : false);
    }
    const suite = el.querySelector('.field[data-k="suite_attackers"]');
    if (suite) suite.hidden = !has(cfg, 'correlation_suite');
    for (const s of SECTIONS) {
      const n = el.querySelector(`[data-note="${s.id}"]`);
      if (n) mount(n, s.note ? s.note(cfg) : '');
    }
  }

  function refresh() {
    applyVisibility();
    mount($('#summary', el), summaryRows(cfg).map(([k, v]) => html`<div class="summary-row"><span>${k}</span><span>${v}</span></div>`));
    local.set('atl.draft', cfg);
    clearTimeout(timer);
    timer = setTimeout(fetchSpec, 200);
  }

  async function fetchSpec() {
    const issues = $('#issues', el);
    if (!issues) return;
    try {
      lastSpec = await api('/api/spec', { method: 'POST', body: { config: cfg } });
    } catch (e) {
      lastSpec = null;
      mount(issues, errorBox(e));
      return;
    }
    if (yamlOverride === null) $('#yaml-view', el).textContent = lastSpec.yaml;
    const errs = lastSpec.errors;
    const items = [
      ...errs.map((e) => html`<div class="callout bad">${e}</div>`),
      ...lastSpec.warnings.map((w) => html`<div class="callout warn">${w}</div>`),
    ];
    if (lastSpec.results_exist) items.push(html`<div class="callout warn">results/${cfg.name}/ already exists; running will overwrite it.</div>`);
    if (!items.length) items.push(html`<div class="callout">Configuration is valid.</div>`);
    mount(issues, items);
    // Mark the sections and fields an error message names.
    for (const s of SECTIONS) {
      const keys = s.fields.map((f) => f.k).concat(s.custom === 'paths' ? ['path', 'routing'] : []).concat(s.custom === 'adversaries' ? ['suite_attackers', 'adversar'] : []);
      const bad = errs.some((e) => keys.some((k) => e.includes(k)));
      const step = el.querySelector(`[data-step="${s.id}"]`);
      if (step) mount(step, html`${s.step}${bad ? html` <span class="err">!</span>` : ''}`);
    }
    for (const f of ALL_FIELDS) {
      const input = el.querySelector(`[data-field="${f.k}"]`);
      if (input && input.tagName === 'INPUT' && input.type !== 'checkbox') {
        const msg = errs.find((e) => e.startsWith(f.k + ' ') || e.includes(` ${f.k} `) || e.includes(`${f.k}=`));
        if (msg) input.setAttribute('aria-invalid', 'true');
        else if (!input.dataset.localError) input.removeAttribute('aria-invalid');
      }
    }
    $('#run-btn', el).disabled = errs.length > 0 && yamlOverride === null;
    $('#run-hint', el).textContent = errs.length && yamlOverride === null ? 'Fix the errors above to run.' : '';
  }

  function setPaths(paths) {
    cfg.routing_strategy = paths[0].strategy;
    cfg.path_length = paths[0].path_length;
    cfg.extra_paths = paths.slice(1);
    if (cfg.split_weights && cfg.split_weights.length !== paths.length) cfg.split_weights = null;
    if (cfg.split_leg_rtt_ms && cfg.split_leg_rtt_ms.length !== paths.length) cfg.split_leg_rtt_ms = null;
  }
  const currentPaths = () => [{ strategy: cfg.routing_strategy, path_length: cfg.path_length }, ...(cfg.extra_paths || []).map((p) => ({ ...p }))];

  // Delegated listeners live on `el`, which survives re-renders, so they
  // are attached once; only the file input is replaced on every render.
  el.addEventListener('input', onInput);
  el.addEventListener('change', onChange);
  el.addEventListener('click', onClick);

  function wire() {
    $('#import-file', el).addEventListener('change', async (evt) => {
      const file = evt.target.files[0];
      if (!file) return;
      await applyYaml(await file.text());
      evt.target.value = '';
    });
  }

  function onInput(evt) {
    const t = evt.target;
    if (t.dataset.field) {
      const f = ALL_FIELDS.find((x) => x.k === t.dataset.field);
      if (f.type === 'bool') return;
      if (t.tagName === 'SELECT') return;
      const r = parseField(f, t.value);
      const errEl = t.closest('.field').querySelector('.field-err');
      if (r.ok) {
        cfg[f.k] = r.value;
        delete t.dataset.localError;
        t.removeAttribute('aria-invalid');
        if (errEl) errEl.textContent = '';
        refresh();
      } else {
        t.dataset.localError = '1';
        t.setAttribute('aria-invalid', 'true');
        if (errEl) errEl.textContent = r.msg;
      }
    } else if (t.dataset.path !== undefined && t.dataset.pk === 'path_length') {
      const n = Number(t.value);
      if (Number.isInteger(n) && n > 0) {
        const paths = currentPaths();
        paths[+t.dataset.path].path_length = n;
        setPaths(paths);
        refreshDiagram();
        refresh();
      }
    } else if (t.id === 'yaml-text') {
      yamlOverride = t.value;
    }
  }

  function onChange(evt) {
    const t = evt.target;
    if (t.dataset.field) {
      const f = ALL_FIELDS.find((x) => x.k === t.dataset.field);
      if (f.type === 'bool') cfg[f.k] = t.checked;
      else if (t.tagName === 'SELECT') cfg[f.k] = t.value;
      else return;
      refresh();
    } else if (t.dataset.path !== undefined && t.dataset.pk === 'strategy') {
      const paths = currentPaths();
      paths[+t.dataset.path].strategy = t.value;
      setPaths(paths);
      refresh();
    } else if (t.dataset.adversary) {
      const set = new Set(cfg.adversaries || []);
      if (t.checked) set.add(t.dataset.adversary); else set.delete(t.dataset.adversary);
      cfg.adversaries = options.adversaries.filter((a) => set.has(a));
      refresh();
    } else if (t.dataset.suite) {
      const set = new Set(cfg.suite_attackers || []);
      if (t.checked) set.add(t.dataset.suite); else set.delete(t.dataset.suite);
      cfg.suite_attackers = ['a0', 'a1', 'a2', 'a3'].filter((a) => set.has(a));
      refresh();
    }
  }

  function refreshDiagram() {
    const box = el.querySelector('.path-diagram');
    if (!box) return;
    const paths = currentPaths();
    const observed = cfg.observed_legs ? new Set(cfg.observed_legs)
      : cfg.observed_path_count ? new Set([...Array(cfg.observed_path_count).keys()]) : null;
    box.innerHTML = pathDiagram(paths.map((p) => ({ length: p.path_length })), { merge: cfg.merge, observed });
  }

  async function onClick(evt) {
    const t = evt.target.closest('button, a');
    if (!t) return;
    if (t.dataset.goto) {
      evt.preventDefault();
      const sec = $(`#sec-${t.dataset.goto}`, el);
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (t.dataset.value !== undefined && t.closest('[data-seg]')) {
      const seg = t.closest('[data-seg]');
      cfg[seg.dataset.seg] = t.dataset.value;
      $$('button', seg).forEach((b) => b.setAttribute('aria-pressed', String(b === t)));
      if (seg.dataset.seg === 'merge') refreshDiagram();
      refresh();
      return;
    }
    if (t.dataset.random) {
      cfg.seed = Math.floor(Math.random() * 2 ** 31);
      $('#f-seed', el).value = cfg.seed;
      refresh();
      return;
    }
    if (t.hasAttribute('data-add-path')) {
      const paths = currentPaths();
      paths.push({ strategy: 'random', path_length: paths[paths.length - 1].path_length });
      setPaths(paths);
      render();
      return;
    }
    if (t.dataset.removePath) {
      const paths = currentPaths();
      paths.splice(+t.dataset.removePath, 1);
      setPaths(paths);
      if (cfg.observed_legs) cfg.observed_legs = cfg.observed_legs.filter((i) => i < paths.length);
      if (cfg.observed_legs && !cfg.observed_legs.length) cfg.observed_legs = null;
      render();
      return;
    }
    switch (t.id) {
      case 'yaml-edit': {
        const text = yamlOverride ?? (lastSpec ? lastSpec.yaml : '');
        $('#yaml-text', el).value = text;
        yamlOverride = text;
        $('#yaml-edit-box', el).classList.remove('hidden');
        $('#yaml-view', el).classList.add('hidden');
        $('#yaml-text', el).focus();
        fetchSpec();
        break;
      }
      case 'yaml-discard':
        yamlOverride = null;
        $('#yaml-edit-box', el).classList.add('hidden');
        $('#yaml-view', el).classList.remove('hidden');
        fetchSpec();
        break;
      case 'yaml-apply':
        await applyYaml($('#yaml-text', el).value);
        break;
      case 'yaml-copy':
        copy(yamlOverride ?? lastSpec?.yaml ?? '');
        break;
      case 'yaml-dl':
        download(`${cfg.name || 'experiment'}.yaml`, yamlOverride ?? lastSpec?.yaml ?? '', 'text/yaml');
        break;
      case 'run-btn':
        await run();
        break;
      default:
    }
  }

  async function applyYaml(text) {
    try {
      const r = await api('/api/parse', { method: 'POST', body: { yaml_text: text } });
      cfg = { ...m.defaults, ...r.config };
      yamlOverride = null;
      sourceNote = 'Loaded from YAML.';
      render();
      toast('YAML applied to the form');
    } catch (e) {
      const box = $('#run-error', el);
      mount(box, errorBox(e));
      box.scrollIntoView({ block: 'center' });
    }
  }

  async function run() {
    const btn = $('#run-btn', el);
    const box = $('#run-error', el);
    mount(box, '');
    btn.disabled = true;
    try {
      const text = yamlOverride ?? lastSpec?.yaml;
      if (!text) throw new Error('No spec to run yet');
      await job.start('/api/run', { yaml_text: text, out_dir: readOutDir(el, 'out-dir') });
      location.hash = '#/runs/live';
    } catch (e) {
      mount(box, errorBox(e));
      btn.disabled = false;
    }
  }

  render();
}

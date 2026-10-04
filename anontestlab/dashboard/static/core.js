// Shared helpers: escaping templates, API calls, formatting, job polling.

// Experiment names, metric keys and file contents all come from
// user-editable YAML or files on disk, so they are untrusted text by the
// time they reach innerHTML. `html` escapes every interpolated value
// unless it is itself the output of `html` (or wrapped in raw() for
// markup this code built, such as an SVG string).
class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}
export const raw = (s) => new Raw(String(s));

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function render(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(render).join('');
  if (v === null || v === undefined || v === false) return '';
  return escapeHtml(v);
}

export function html(strings, ...values) {
  let out = '';
  strings.forEach((s, i) => {
    out += s;
    if (i < values.length) out += render(values[i]);
  });
  return new Raw(out);
}

export function mount(el, content) {
  el.innerHTML = render(content);
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---------------------------------------------------------------- API

export async function api(path, { method = 'GET', body, text = false } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return text ? resp.text() : resp.json();
}

export const enc = (id) => id.split('/').map(encodeURIComponent).join('/');

let metaPromise = null;
export function meta() {
  if (!metaPromise) metaPromise = api('/api/meta');
  return metaPromise;
}

let outputsCache = null;
export async function outputs(force = false) {
  if (force || !outputsCache) outputsCache = api('/api/outputs');
  try {
    return await outputsCache;
  } catch (e) {
    outputsCache = null;
    throw e;
  }
}
export function invalidateOutputs() { outputsCache = null; }

// ----------------------------------------------------------- formatting

export function num(v, digits = 3) {
  if (v === null || v === undefined || v === '') return 'n/a';
  if (typeof v !== 'number') return String(v);
  if (Number.isInteger(v)) return v.toLocaleString('en-US');
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(2);
  return v.toFixed(digits);
}
export function signed(v, digits = 3) {
  if (typeof v !== 'number') return 'n/a';
  return (v > 0 ? '+' : '') + num(v, digits);
}
export function pct(v, digits = 1) {
  return typeof v === 'number' ? `${(v * 100).toFixed(digits)}%` : 'n/a';
}
export function ms(seconds) {
  if (typeof seconds !== 'number') return 'n/a';
  const m = seconds * 1000;
  return m >= 100 ? `${m.toFixed(0)} ms` : `${m.toFixed(1)} ms`;
}
export function ago(epochSeconds) {
  if (!epochSeconds) return '';
  const s = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
export function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  return m ? `${m}m ${s % 60}s` : `${s}s`;
}
export function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const PRETTY = {
  delivery_rate: 'Delivery rate',
  oneway_delay_p50_s: 'Median one-way delay',
  oneway_delay_p95_s: 'P95 one-way delay',
  oneway_delay_p99_s: 'P99 one-way delay',
  bandwidth_overhead_x: 'Bandwidth overhead',
  circuit_build_delay_s: 'Circuit build delay',
  sessions_failed: 'Sessions failed',
  auc: 'AUC (global observer)',
  'tpr_at_fpr_0.001': 'TPR at FPR 1e-3 (global observer)',
};
export const pretty = (k) => PRETTY[k] || k;

export function fmtMetric(key, v) {
  if (typeof v !== 'number') return v === null || v === undefined ? 'n/a' : String(v);
  if (key.endsWith('_s') && !key.startsWith('suite_')) return ms(v);
  if (key === 'delivery_rate' || key.endsWith('_share') || key.endsWith('_rate')) return pct(v);
  if (key === 'bandwidth_overhead_x') return `${v.toFixed(2)}x`;
  return num(v);
}

/** Same unit conversion as fmtMetric (ms, %, x), with a +/- sign, for a
 * delta shown beside fmtMetric-formatted A/B columns - so e.g. a one-way
 * delay delta reads "+0.3 ms" next to "0.9 ms" / "0.6 ms", not a bare
 * seconds figure like "3.00e-4" that silently drops the unit the other
 * two columns are in. */
export function signedMetric(key, v) {
  if (typeof v !== 'number') return 'n/a';
  const formatted = fmtMetric(key, v);
  // A tiny negative value can round to "-0.0 ms" / "-0%" at the display
  // precision above; that reads as a negative change when it is really
  // indistinguishable from none at the shown precision, so the sign is
  // dropped once the rounded leading number is zero (an exponential tail
  // like "1.00e-7" is left alone: that notation already carries its own
  // sign meaningfully, at full precision).
  const lead = /^-?\d+(?:\.\d+)?/.exec(formatted);
  const isZero = lead !== null && Number(lead[0]) === 0;
  const unsigned = isZero && formatted.startsWith('-') ? formatted.slice(1) : formatted;
  return (v > 0 && !isZero ? '+' : '') + unsigned;
}

export function kindBadge(kind) {
  const map = { run: ['Run', 'blue'], sweep: ['Sweep', 'amber'], paired: ['Paired', 'green'],
    compare: ['Compare', ''], fidelity: ['Fidelity', 'green'] };
  const [label, color] = map[kind] || [kind, ''];
  return html`<span class="badge ${color}">${label}</span>`;
}

export function designText(s) {
  if (!s) return '';
  const lens = (s.path_lengths || []).join('+');
  const paths = s.paths > 1 ? `${s.paths} paths (${lens} hops), ${s.merge === 'common_exit' ? 'common exit' : 'disjoint'}` : `1 x ${lens}-hop`;
  return paths;
}
export function trafficText(s) {
  if (!s) return '';
  let t = `${s.traffic} ${num(s.real_rate, 1)}/s`;
  if (s.split) t += `, ${s.split}`;
  if (s.cover_rate > 0) t += `, cover ${num(s.cover_rate, 1)}/s`;
  return t;
}
export function defenseText(s) {
  if (!s) return '';
  const parts = [];
  if (s.mix === 'pool') parts.push(`pool ${num(s.pool_interval_ms, 0)} ms`);
  else if (s.mix && s.mix !== 'none') parts.push(`${s.mix} mix ${num(s.mix_delay_ms, 0)} ms`);
  if (s.shaping === 'fixed_rate') parts.push('fixed rate');
  if (s.cell_size) parts.push(`pad ${s.cell_size} B`);
  return parts.join(', ') || 'none';
}

export function toast(message) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied');
  } catch {
    toast('Copy failed: the clipboard needs a secure context');
  }
}

export function download(filename, text, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Per-viewer conveniences only (the builder draft, the theme). Storage can
// be unavailable or throw in private windows, so every access is guarded.
export const local = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  },
};

// ------------------------------------------------------------ job state

// One job at a time on the server. The poller keeps a single copy of its
// state, fetching only events it hasn't seen, and notifies subscribers.
export const job = {
  state: null,
  events: [],
  listeners: new Set(),
  timer: null,
  subscribe(fn) {
    this.listeners.add(fn);
    if (this.state) fn(this.state, this.events);
    return () => this.listeners.delete(fn);
  },
  async poll() {
    clearTimeout(this.timer);
    try {
      const since = this.events.length;
      const s = await api(`/api/status?since=${since}`);
      // Polls can overlap (the shell and a view both poll on a fresh load):
      // a reply to a `since` that is no longer current would append the same
      // events twice, so only the reply matching the current count is used.
      if (this.events.length !== since) return;
      // A new job, or the server restarted: its events count from 0, so read
      // them again from the start instead of appending from the old offset.
      if (since > 0 && ((this.state && s.started_at !== this.state.started_at) || s.events_total < since)) {
        this.events = [];
        return this.poll();
      }
      this.events.push(...s.events);
      const wasActive = this.state && this.state.active;
      this.state = s;
      if (wasActive && !s.active) invalidateOutputs();
      this.listeners.forEach((fn) => fn(s, this.events));
      if (s.active) this.timer = setTimeout(() => this.poll(), 800);
    } catch {
      this.timer = setTimeout(() => this.poll(), 3000);
    }
  },
  async start(path, body) {
    const r = await api(path, { method: 'POST', body });
    this.events = [];
    this.state = null;
    await this.poll();
    return r;
  },
  async stop() {
    const r = await api('/api/stop', { method: 'POST' });
    await this.poll();
    return r;
  },
};

export const JOB_ROUTE = { run: 'results', sweep: 'sweep', paired: 'paired', fidelity: 'fidelity' };

// ------------------------------------------------------- source picker

// Optional output directory, the dashboard's equivalent of the CLI's
// --out: a text input plus an info tooltip. readOutDir() reads it back as
// a trimmed string or null (for a job request body's out_dir field).
export function outDirField(id, defaultPath) {
  return html`<div class="field">
    <div class="label-row"><label for="${id}">Output directory (optional)</label>${infoIcon(`Matches the CLI's --out. Leave blank for the default ${defaultPath}. A custom path outside results/ will not show up in this dashboard's Runs or Artifacts browser; find it on disk at the path you gave.`)}</div>
    <input class="input mono" id="${id}" placeholder="${defaultPath}" autocomplete="off" spellcheck="false">
  </div>`;
}
export function readOutDir(root, id) {
  return $(`#${id}`, root).value.trim() || null;
}

// A config source for analyses: a stored run, the builder draft, or a
// pasted YAML spec. Rendered as a select plus an optional textarea.
export function sourcePicker(id, runs, { selected = '', allowDraft = true } = {}) {
  const draft = local.get('atl.draft');
  return html`
    <div class="field">
      <select class="select" id="${id}" data-source>
        ${runs.length ? html`<optgroup label="Stored runs">${runs.map((r) => html`<option value="run:${r.id}" ${selected === r.id ? raw('selected') : ''}>${r.id}</option>`)}</optgroup>` : ''}
        ${allowDraft && draft ? html`<option value="draft">Builder draft: ${draft.name}</option>` : ''}
        <option value="paste">Paste YAML spec</option>
      </select>
      <textarea class="textarea hidden" id="${id}-yaml" placeholder="experiment:&#10;  name: ..." aria-label="YAML spec"></textarea>
    </div>`;
}

export function wireSourcePicker(root, id) {
  const sel = $(`#${id}`, root);
  const ta = $(`#${id}-yaml`, root);
  const sync = () => ta.classList.toggle('hidden', sel.value !== 'paste');
  sel.addEventListener('change', sync);
  sync();
}

export async function readSource(root, id) {
  const v = $(`#${id}`, root).value;
  if (v.startsWith('run:')) return { run_id: v.slice(4) };
  if (v === 'draft') {
    const spec = await api('/api/spec', { method: 'POST', body: { config: local.get('atl.draft') } });
    if (spec.errors.length) throw new Error('The builder draft has errors: ' + spec.errors.join('; '));
    return { yaml_text: spec.yaml };
  }
  const text = $(`#${id}-yaml`, root).value;
  if (!text.trim()) throw new Error('Paste a YAML spec first');
  return { yaml_text: text };
}

export function sourceLabel(root, id) {
  const sel = $(`#${id}`, root);
  return sel.options[sel.selectedIndex]?.textContent || '';
}

// A small hover/focus-only info icon next to a label, explaining what the
// control does. CSS-only (see .info-btn in styles.css): `html` escapes
// `tip` the same as any other interpolated value, since it is plain copy
// here, never markup.
export function infoIcon(tip) {
  return html`<button type="button" class="info-btn" aria-label="${tip}" data-tip="${tip}"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 5.1v.1" stroke-linecap="round"/></svg></button>`;
}

export function pageHead(title, desc, actions = '', eyebrow = '') {
  return html`
    <div class="page-head">
      <div>${eyebrow ? html`<div class="eyebrow">${eyebrow}</div>` : ''}<h2>${title}</h2>${desc ? html`<p>${desc}</p>` : ''}</div>
      ${actions ? html`<div class="actions">${actions}</div>` : ''}
    </div>`;
}

export function errorBox(e) {
  return html`<div class="callout bad" role="alert">${e && e.message ? e.message : String(e)}</div>`;
}

/** warn: true flags a caveat that changes how the headline value should be
 * read (e.g. an uncalibrated/optimistic threshold) - not just a plain
 * footnote, so it gets a visible triangle and warning color rather than
 * the same quiet grey as a normal "sub" caption like a unit or a count. */
export function metricCard(label, value, sub = '', warn = false) {
  return html`<div class="card metric${warn ? ' warn' : ''}"><div class="label">${label}</div><div class="value">${value}</div>${sub ? html`<div class="sub">${warn ? '⚠ ' : ''}${sub}</div>` : ''}</div>`;
}

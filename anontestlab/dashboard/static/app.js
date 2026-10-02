// Hash router and app shell.
import { $, $$, errorBox, html, job, local, mount } from './core.js';
import { builderView } from './builder.js';
import { artifactsView, experimentsView, liveView, resultsView, runsView } from './views.js';
import { compareView, fidelityView, pairedView, predictView, sweepView } from './analyses.js';

const ROUTES = {
  experiments: [experimentsView, 'Experiments'],
  new: [builderView, 'New experiment'],
  runs: [runsView, 'Runs'],
  results: [resultsView, 'Results'],
  compare: [compareView, 'Analyses / Compare'],
  sweep: [sweepView, 'Analyses / Sweep'],
  paired: [pairedView, 'Analyses / Paired'],
  predict: [predictView, 'Analyses / Predict'],
  fidelity: [fidelityView, 'Analyses / Fidelity'],
  artifacts: [artifactsView, 'Artifacts'],
};

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs = ''] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { route: parts[0] || 'experiments', id: parts.slice(1).join('/') || null, query: new URLSearchParams(qs) };
}

let navToken = 0;

async function navigate() {
  const { route, id, query } = parseHash();
  const live = route === 'runs' && id === 'live';
  const [view, crumb] = ROUTES[route] || ROUTES.experiments;
  const token = ++navToken;

  // A fresh element per navigation, so listeners a view attached to its
  // root can't fire on the next view.
  const old = $('#view');
  const el = old.cloneNode(false);
  old.replaceWith(el);

  $$('.nav a').forEach((a) => {
    const on = a.dataset.nav === route;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  mount($('#crumbs'), html`AnonTestLab / <b>${crumb}${live ? ' / live' : id ? ` / ${id}` : ''}</b>`);
  document.title = `${crumb.split(' / ').pop()}${id && !live ? `: ${id}` : ''} - AnonTestLab Dashboard`;
  mount(el, html`<div class="empty">Loading...</div>`);
  try {
    if (live) liveView(el);
    else await view(el, { id, query });
  } catch (e) {
    if (token === navToken) mount(el, html`<div class="page-head"><div><h2>Something went wrong</h2></div></div>${errorBox(e)}`);
  }
  if (token === navToken) window.scrollTo(0, 0);
}

function sideJob(s) {
  const foot = $('#side-foot');
  if (s && s.active) {
    mount(foot, html`<a href="#/runs/live" class="job"><span class="dot pulse"></span> ${s.kind}: ${s.label}</a>
      <div>${s.steps > 1 ? `run ${s.step + 1} of ${s.steps}` : 'running'}</div>`);
  } else {
    mount(foot, html`Local dashboard. Values come from this machine's emulator runs.`);
  }
}

function initTheme() {
  const btn = $('#theme-btn');
  const apply = (t) => {
    if (t) document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
    btn.textContent = t === 'dark' ? 'Dark' : t === 'light' ? 'Light' : 'Auto';
    btn.setAttribute('aria-label', `Color theme: ${btn.textContent}. Click to change.`);
  };
  let theme = local.get('atl.theme');
  apply(theme);
  btn.addEventListener('click', () => {
    theme = theme === null ? 'light' : theme === 'light' ? 'dark' : null;
    local.set('atl.theme', theme);
    apply(theme);
  });
}

initTheme();
job.subscribe(sideJob);
job.poll();
window.addEventListener('hashchange', navigate);
navigate();

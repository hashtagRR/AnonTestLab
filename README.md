# AnonTestLab

**[hashtagRR.github.io/AnonTestLab](https://hashtagRR.github.io/AnonTestLab)**

A real, local network emulator and experimentation framework for
evaluating anonymous communication network designs.

Relay nodes run as **real OS processes**, each on its own loopback IP
(`127.0.0.1`, `127.0.0.2`, ...), connected by a telescoping
(Tor-inspired) circuit with real per-hop AEAD encryption (several
algorithms selectable, see Crypto below) and a real ECDHE handshake per
hop (x25519 by default, x448 or p256 also selectable), with hop-local
circuit IDs so no identifier is shared across two links of the same
path. Latency, delivery and correlation numbers are measured by running
the protocol over sockets; there is no timing model.

This is a research harness with its own simple wire protocol; it does
not reimplement Tor's protocol. There are no fixed-size cells by
default (opt in via `traffic_shaping`), no directory/consensus system,
and the wire format is custom.

## Architecture

```
                     Experiment (YAML) ──▶ ExperimentConfig
                                                  │
                              ┌───────────────────┼───────────────────┐
                              ▼                   ▼                   ▼
                    spawn_relays()         RoutingStrategy      TrafficGenerator
                    N real subprocesses,   picks nodes per      real: Poisson/const/pareto
                    each 127.0.0.<n>       path (1..N paths)    cover: Poisson/const/pareto/fixed_rate
                              │                   │                   │
                              └───────────────────│───────────────────┘
                                                  ▼
                                    per session: build_circuit(), a
                                    real telescoping handshake (ECDHE +
                                    HKDF, hop-local circuit IDs), then send
                                    real onion-wrapped DATA cells (optionally
                                    padded to a fixed cell_size) over real
                                    sockets, each hop optionally modeling
                                    WAN latency/jitter/loss/bandwidth
                                                    │
                              ┌─────────────────────│────────────────────────────┐
                              ▼                                                  ▼
                    MetricsCollector                                   Adversary (pluggable)
                    (real measured latency,                            global_observer: Observation
                     delivery, bandwidth)                                 -> Feature -> Decision, with
                                                                           AS-level partial visibility
                                                                        path_compromise: fast Monte Carlo
                                                                        watermark: active delay-pattern
                                                                         injection + detection
                              │                                                    │
                              └─────────────────────────┬──────────────────────────┘
                                                        ▼
                                     results/<name>/{configuration.yaml, seed.txt,
                                       metrics.csv, report.md (+ baseline diff if set)}
```

A small discrete-event core (`anontestlab.core.Simulation`) exists only as a
generic utility. Nothing in the pipeline above depends on it: the
compromise-probability adversary is pure combinatorics on the paths
`RoutingStrategy` chose, and no packets need to move for it.

## Modes

`tor_like` is a fixed preset: one path, three hops, random relay
selection, no cover traffic, no splitting. `custom` makes every
dimension below configurable.

```
                       AnonTestLab experiment
                                │
                 ┌──────────────┴──────────────┐
                 ▼                              ▼
            tor_like                          custom
         (fixed preset)                (every stage below is configurable)
                 │                              │
      1 path, 3 hops,                           ▼
      random selection,             network.nodes, as_groups
      no cover, no split                        │
                                                 ▼
                                     routing.paths (1..N paths, each its own
                                     strategy: random | bandwidth_weighted, +
                                     path_length), split_strategy
                                                 │
                                                 ▼
                                     traffic.real_rate, cover_rate,
                                     distribution: poisson | constant | pareto | burst,
                                     cover_behaviour.drop_probability
                                                 │
                                                 ▼
                                     traffic_shaping: cell_size (fixed-size cell
                                     padding, independent toggle), mode (variable |
                                     fixed_rate, the send schedule)
                                                 │
                                                 ▼
                                     crypto.algorithm, keyexchange (handshake curve)
                                                 │
                                                 ▼
                                     link_conditions: latency, jitter, loss,
                                     bandwidth (WAN realism), heterogeneous
                                     (per-node variation), per_edge (per-link
                                     variation, directional-only)
                                                 │
                                                 ▼
                                     adversary.types + per-type params
                                     (observed_paths/observed_as, compromise
                                     fraction/trials, watermark period/delay,
                                     observation/classifier)
                                                 │
                                                 ▼
                                     baseline (optional diff against
                                     another experiment config)
```

## Quickstart

Commands below are for Linux/macOS. On Windows, use PowerShell with a
standard python.org Python (not the one bundled with MSYS2/Git Bash);
see [INSTALL.md](INSTALL.md) for the full platform-specific guide and a
Windows troubleshooting checklist.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/atl run examples/tor_like.yaml
.venv/bin/atl wizard                    # interactive: pick a mode, fill in params
.venv/bin/atl compare examples/tor_like.yaml examples/cover_traffic_evaluation.yaml
.venv/bin/atl sweep examples/tor_like.yaml --param path_length --values 2,3,4

.venv/bin/pip install -e ".[dashboard]"     # optional: local web UI
.venv/bin/atl dashboard                  # http://127.0.0.1:8765
```

`atl run` and `atl wizard` print live progress as relays spawn and each
session completes, so a multi-second run shows its progress:

```
Running tor-like...
  10 relays ready
  session 1/10 complete (37/37 real delivered, build 34ms)
  session 2/10 complete (37/37 real delivered, build 29ms)
  ...

Results for tor-like
────────────────────────────────────────
real_packets_sent              375
delivery_rate                  1.0000
avg_latency_s                  0.0006      (measured localhost latency)
circuit_build_delay_s          0.0315      (measured handshake time)
correlation_success_rate       1.0000
auc                            1.0000
precision                      1.0000
recall                         1.0000
...
```

The dashboard shows the same progress live: it starts the run in the
background and polls for updates, so the page stays responsive while the
experiment runs, and draws each leg of the running session relay by relay.

## Writing an experiment

```yaml
experiment:
  name: custom-multipath
  seed: 20260903
  duration_s: 8

network:
  nodes: 15
  as_groups: 4              # for the AS-level partial observer

sessions:
  count: 10
  max_concurrent: 20        # optional: run sessions in waves of this size (see Fidelity below)

routing:
  paths:
    - strategy: bandwidth_weighted   # or "random"
      path_length: 3
    - strategy: random
      path_length: 4
  split_strategy: round_robin   # round_robin | random | iid | batch | latency (see Multipath below)
  split_weights: [0.7, 0.3]     # per-leg shares for iid, batch and weighted round_robin; default even
  merge: disjoint               # or common_exit: every leg ends at one exit relay (Conflux-style)

traffic:
  distribution: pareto            # "poisson" (default) | "constant" | "pareto" (heavy-tailed gaps) | "burst"
  real_rate: 6
  cover_rate: 0                  # >0 to enable cover traffic
  # burst: bursts of back-to-back cells, Poisson burst starts, geometric
  # burst sizes; per-bin counts have index of dispersion about
  # 2 * burst_mean_cells - 1 (real Tor downstream traffic: median about 40 at 0.1 s)
  burst_mean_cells: 12
  burst_gap_ms: 2

cover_behaviour:
  drop_mode: random_hop            # "per_hop" (default: each hop drops cover with drop_probability)
                                     # | "random_hop": each cover cell dies at one hop the client picks

mixing:                            # relay-side mixing at every hop (data cells only)
  strategy: pool                   # "none" (default) | "constant" | "exponential" (Loopix-style) | "pool"
  delay_ms: 50                     # constant delay, or exponential mean, per hop
  pool_interval_ms: 250            # pool: flush period, shared by all circuits through a relay
  release_probability: 1.0         # pool: 1.0 empties each flush; < 1 retains cells (binomial pool)
  interval_jitter: 0.0             # pool: randomized flush, interval * (1 +/- U(jitter))

traffic_shaping:
  enabled: true                    # turns on fixed-size cell padding below
  cell_size: 512                  # every cell padded to this many wire bytes
  mode: fixed_rate                 # "variable" (default) | "fixed_rate": the send
                                     # schedule, independent of cell_size padding
  rate: 20                          # packets/sec on the wire when mode == "fixed_rate"

link_conditions:                   # WAN realism, applied per-hop via asyncio.sleep
  latency_ms: 50
  jitter_ms: 10
  loss_probability: 0.02
  bandwidth_kbps: 512
  heterogeneous: true              # vary these per node instead of uniform
  per_edge: true                    # also vary per (relay, peer) link, directional-only
  heterogeneity_spread: 0.5         # shared spread for both: factor ~ Uniform(1-spread, 1+spread)

crypto:
  algorithm: chacha20poly1305   # none | aes128gcm | aes256gcm | aes256gcmsiv | aes256ocb3 | chacha20poly1305
  keyexchange: x448              # x25519 (default) | x448 | p256, the handshake curve

adversary:
  types: [global_observer, path_compromise]
  observed_paths: 1              # "all" or a path count (mutually exclusive with observed_as)
  observed_as: 1                  # "all" or an AS-group count, independent entry/exit visibility
  observation: {bin_width_ms: 100}
  classifier: {type: pearson, threshold: 0.7}
  evaluation: {calibration_fraction: 0.5}   # hold out: cut chosen on half the sessions, TPR read on the rest
  compromised_fraction: 0.15     # for path_compromise
  compromise_trials: 3000

baseline: baseline.yaml           # optional: diffs this run against another config in report.md
```

See `examples/` for a Tor-like preset, a cover-traffic experiment, and a
multi-path custom config.

## Multipath

`routing.split_strategy` decides which leg carries each cell:

- `round_robin`: legs in turn; with `split_weights`, a smooth weighted round-robin (deterministic, evenly spread)
- `random`: a uniformly chosen leg per cell
- `iid`: leg *i* with probability `split_weights[i]` per cell
- `batch`: batches of exponential duration (mean `split_batch_mean_s`, default 2 s), each sent entirely on one leg drawn with the weights
- `latency`: the lowest-RTT leg with room in its window (`split_leg_window` cells per RTT), using the nominal RTTs in `split_leg_rtt_ms`; modeled on the lowest-RTT-first idea in Tor's Conflux proposal. The RTTs drive the scheduling decision only.

`routing.merge: common_exit` makes all legs of a session end at one exit relay, with no other relay shared between legs, so each leg has its own entry. On the adversary side, `observed_legs: [0]` fixes which legs are visible at the entry, and `egress_observation: merged` makes the exit side see every leg's cells (the flow after the legs rejoin). Runs with more than one leg report `leg_<i>_real_share`, the measured share of real cells per leg.

## Crypto

`crypto.algorithm` picks the per-hop AEAD:

- `none`: plaintext passthrough, still real framing/transport (isolates transport cost from crypto cost)
- `aes128gcm`, `aes256gcm`
- `aes256gcmsiv`: nonce-misuse resistant variant of GCM
- `aes256ocb3`: a faster construction
- `chacha20poly1305`

`crypto.keyexchange` picks the ECDHE curve for the per-hop handshake:

- `x25519` (default): Curve25519
- `x448`: RFC 7748, larger keys, higher security margin
- `p256`: NIST secp256r1, for interop-focused comparisons

Notes:

- Both are whole-experiment settings, fixed for every hop: every relay in a circuit must agree on them. The EXTEND cell's public-key field is length-prefixed, so it fits every curve's key size and the wire format doesn't need to encode which curve is in use.
- A larger handshake key (x448's 56 bytes, p256's 65-byte uncompressed point, vs x25519's 32) eats more of the fixed-size cell padding budget; a very small `cell_size` combined with a long path may need raising.
- `aes256gcmsiv` needs `cryptography>=42.0` (pinned in pyproject.toml) built against OpenSSL 3.2+. The `cryptography` package's own prebuilt wheels satisfy this on every common platform, so a normal `pip install` needs nothing extra.

## Testing tools

- `atl run <yaml>`: runs one experiment, prints one metrics table (plus a baseline diff if `baseline:` is set)
- `atl compare <yaml_a> <yaml_b>`: runs both, diffs every metric
- `atl sweep <yaml> --param X --values a,b,c`: reruns one config varying a single field, one CSV row per value
- `atl paired <ref_yaml> <treatment_yaml> --seeds 12 --metric tpr_at_fpr_0.001`: runs both configs under the same seeds, bootstraps the paired per-seed difference, and classifies it against an equivalence margin (`--margin`, default 0.05) as `meaningful_effect`, `no_meaningful_effect` (whole CI inside the margin) or `inconclusive`
- `atl predict <yaml>`: prints the closed-form predictions for the lag-aware correlator (per-bin correlation, signal, TPR at FPR, confident linkage) for an experiment, without running it. The model takes the traffic's mean and index of dispersion per bin from the configured generator, so bursty traffic gets the dispersion forms of the split and delay factors (`model_dispersion_w<bin>` in the output). Cover traffic is split over the legs like real cells, so an observed leg carries its share of the cover
- `atl fidelity <yaml>`: reruns an experiment's load with relay mixing switched off and reports the one-way delay that remains (host and link time). It passes when the 95th percentile, minus configured link latency, is at most 10% of the smallest per-hop mixing delay (or of the smallest attacker bin width when there is no mixing). Relays share one machine, so a failing load adds timing noise that looks like a defense; lower `sessions.max_concurrent` or use a larger machine.
- `atl wizard`: walks through picking `tor_like` or `custom`, filling in parameters, reviewing the assembled YAML before running
- `atl dashboard` (needs `pip install -e ".[dashboard]"`): a local web workbench at `http://127.0.0.1:8765`, running the same `anontestlab.experiment.run_experiment` as the CLI:
  - **Builder:** every experiment option as a form, kept in sync with the YAML it generates (which can also be edited or loaded directly), with an output folder per run.
  - **Live run:** progress per session, a sender-to-receiver drawing of each leg of the current session (legs sized by their measured share of real cells, a shared exit drawn once), the relay graph, and a stop button that ends the run's relay processes.
  - **Results:** stored runs with their metrics, ROC and score-distribution charts, latency CDF, and downloads of the run folder as a zip and of a PDF report.
  - **Research tools:** compare (two stored runs, or two new configs run and diffed in one step), sweep, paired, predict and fidelity, each on its own page with charts, and PDF reports for comparisons and paired analyses.

### Adversaries

- **`global_observer`**: composes swappable Observation (binning), Feature (`pearson` correlation, pluggable), and Decision stages, reporting correlation accuracy, TPR at fixed FPR, AUC, precision, and recall. The TPR@FPR cut is conservative under tied scores (the realized FPR never exceeds the target), and each target also reports `realized_fpr_*` and `fpr_support_*` (expected impostor exceedances, i.e. how much tail backs the estimate). With `evaluation.calibration_fraction` > 0 the cut is chosen on calibration sessions and scored on disjoint test sessions. Visibility can be restricted by path count (`observed_paths`) or AS-group membership (`observed_as`): entry and exit are independently visible based on which mock AS group their hop belongs to, a more structured partial-observer model than a bare fraction.
- **`correlation_suite`**: runs training-free correlation attackers side by side on one shared calibration/test split: `a0` zero-lag and `a1` lag-aware binned-count correlation at each bin width (`bin_widths_s`, default 0.1, 0.25, 0.5, 1.0 s; lags up to max(2 s, P99 of the added delay) + 0.5 s), `a2` a likelihood-ratio attacker using the known delay distribution (Danezis's Poisson-intensity approximation), and `a3` a timing-window matcher (useful for sparse flows). Each attacker reports confident linkage `lpsi_<psi>_br_<base rate>` (share of true pairs the attacker would accept with posterior at least psi when that fraction of candidate pairs are true), TPR at fixed FPR with realized FPR, the signal estimate `mu_hat` and AUC. The run also reports the model's predictions (`model_*`) next to them, and saves the score matrices to `correlation_suite.npz`. Configure under `adversary.correlation_suite`.
- **`path_compromise`**: an independent-compromise Monte Carlo that needs no packets to move: if an adversary controls fraction *f* of relays, what's the probability a session's path(s) are fully compromised (the textbook *f^k*, generalized empirically to multi-path sessions). Deliberately independent-only, no correlated or shared-operator modeling.
- **`watermark`**: an active attack: a designated relay, always pinned to hop 1, delays every `period`-th real packet by a fixed amount, then checks whether the pattern survives to the observed exit timing. Best used with a single path per session.
- **`hop_depth`**: structural like `path_compromise` (no packets need to move): once fixed-size cell padding is on, quantifies the disclosed hop-position leak directly from `cell_size`/`crypto_algorithm`. Reports whether an observer at one hop can recover its exact position from size alone (`hop_position_accuracy`, 1.0 once shaping is enabled) and whether an observer at hop 1 can tell circuits of different lengths apart from size alone (`path_length_leak_at_hop1`, 0.0 by design; `nan` if only one circuit length appears in the experiment).

## Known limitations (v0.5)

Simplifications of this version, stated so that results are read with them in mind:

- **Fixed-size cells still leak hop position.** Cells are exactly `cell_size` bytes at hop 1 regardless of path length, but shrink by a fixed amount per hop *position* within a circuit. A single-link observer can't distinguish path lengths or real/cover/EXTEND from size alone, but a global observer watching multiple hops of the same circuit could infer hop depth from the size sequence (the `hop_depth` adversary measures exactly this).
- **Per-edge link conditions are directional-only.** `link_conditions.per_edge` scales a relay's forward-direction send to a specific peer and is directional: only the connection-initiating side is scaled (it always knows both endpoints locally); the receiving side's own upstream-facing sends on that connection still use its plain per-node value, since telling it would need a wire-protocol change this scope didn't take on.
- **No relay identity or directory system.** Keys are ephemeral only, so there's no TOFU question to answer, but also no persistent relay reputation.
- **Wave mode changes the timestamp origin.** With `sessions.max_concurrent`, each session's timestamps start at that session's own start, so flows from different waves line up as if concurrent. Without it, all sessions share the experiment clock.
- **The `latency` split policy uses nominal RTTs.** Legs are not given different real latencies; only the scheduling decision follows the configured RTTs.
- **`bandwidth_weighted` routing doesn't model guard/exit-flag constraints.** It selects without replacement in proportion to each node's configured weight and leaves out Tor's position rules on purpose.
- **Timing varies run to run.** The experiment *design* (path choices, traffic schedule) is reproducible from the seed, but real measured latency and timing will vary like any real system's would, since sessions run concurrently over real sockets and each relay subprocess has its own independent random state for loss/drop/watermark rolls.

## Extending it

Routing strategies, traffic generators, and adversaries are small
classes registered in a lookup dict (`anontestlab.routing.STRATEGIES`,
`anontestlab.traffic.GENERATORS`, `anontestlab.adversary.ADVERSARIES`). Add one
by subclassing the relevant base class and registering it. The crypto
layer follows the same pattern but isn't class-based: AEAD ciphers are
registered in `anontestlab.crypto.ALGORITHMS` (plus a matching entry in
`KEY_LENGTHS`), and handshake curves are a fixed if/elif in
`anontestlab.emulator.crypto_layer.generate_ephemeral_keypair`/`derive_key`
instead of a dict, since each curve's key-generation and ECDH calls
have a different shape (see `KEYEXCHANGES` for the current
set).

## Provenance
AnonTestLab began as a generalization of the evaluation methodology and
test harness built for Anon-Sec-Net, a research prototype for dual-path
anonymous communication, and reuses portions of that codebase and test
suite. It is a protocol-agnostic emulator with pluggable adversary models
and configurable routing, usable for designs other than the one it came
from.

Version 0.4 adds multipath split policies, relay mixing, a bursty traffic
generator, training-free correlation attackers with model predictions, and
a host-noise fidelity check. It is the measurement instrument of a paper on
correlation risk in multipath anonymous communication, currently under
review; a reference will be added here on publication.

### Versions

- **`v0.4.0`** (tag, commit 199deae) is the version the paper's experiments
  ran. Its code matches the frozen bundle of the study apart from comments
  and documentation.
- **`v0.5.0`** adds the rebuilt dashboard with PDF reports and a fix to the
  model's predictions for cover traffic on split legs (see `CHANGELOG.md`).
  Measurements are unchanged.

## License

GPL-3.0-or-later. See `LICENSE`.

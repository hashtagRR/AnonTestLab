# AnonTestLab

A real, local network emulator and experimentation framework for
evaluating anonymous communication network designs.

Relay nodes run as **real OS processes**, each on its own loopback IP
(`127.0.0.1`, `127.0.0.2`, ...), connected by a genuine telescoping
(Tor-inspired) circuit with real per-hop AEAD encryption (AES-256-GCM /
ChaCha20-Poly1305, real X25519 handshake per hop, and hop-local circuit
IDs, so no identifier is shared across two links of the same path).
Nothing here is a timing model. Latency, delivery, and correlation
numbers all come from actually running the protocol over actual sockets.

This is a research harness with its own simple wire protocol, not a
protocol-level reimplementation of Tor. There are no fixed-size cells by
default (opt in via `traffic_shaping`), no directory/consensus system,
and the wire format is custom.

## Architecture

```
                     Experiment (YAML) ──▶ ExperimentConfig
                                                  │
                              ┌───────────────────┼───────────────────┐
                              ▼                   ▼                   ▼
                    spawn_relays()         RoutingStrategy      TrafficGenerator
                    N real subprocesses,   picks nodes per      real: Poisson/const
                    each 127.0.0.<n>       path (1..N paths)    cover: Poisson/const/fixed_rate
                              │                   │                   │
                              └───────────────────┴─────────┬─────────┘
                                                              ▼
                                         per session: build_circuit(), a
                                         real telescoping handshake (X25519 +
                                         HKDF, hop-local circuit IDs), then send
                                         real onion-wrapped DATA cells (optionally
                                         padded to a fixed cell_size) over real
                                         sockets, each hop optionally modeling
                                         WAN latency/jitter/loss/bandwidth
                                                              │
                              ┌───────────────────────────────┼───────────────────┐
                              ▼                                                    ▼
                    MetricsCollector                                   Adversary (pluggable)
                    (real measured latency,                            global_observer: Observation
                     delivery, bandwidth)                                 → Feature → Decision, with
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
selection, no cover traffic, no splitting. `custom` makes everything
configurable: relay count, path count and splitting, cover traffic,
crypto algorithm, traffic shaping, WAN conditions, and which adversaries
run.

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

```
Results for tor-like
────────────────────────────────────────
real_packets_sent              375
delivery_rate                  1.0000
avg_latency_s                  0.0006      ← real measured localhost latency
circuit_build_delay_s          0.0315      ← real measured handshake time
correlation_success_rate       1.0000
auc                            1.0000
precision                      1.0000
recall                         1.0000
...
```

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

routing:
  paths:
    - strategy: random
      path_length: 3
    - strategy: random
      path_length: 4
  split_strategy: round_robin   # or "random"

traffic:
  real_rate: 6
  cover_rate: 0                  # >0 to enable cover traffic

traffic_shaping:
  enabled: true
  cell_size: 512                  # every cell padded to this many wire bytes
  mode: fixed_size                 # "fixed_size" | "fixed_rate" | "none"

link_conditions:                   # WAN realism, applied per-hop via asyncio.sleep
  latency_ms: 50
  jitter_ms: 10
  loss_probability: 0.02
  bandwidth_kbps: 512

crypto:
  algorithm: chacha20poly1305   # "none" | "aes256gcm" | "chacha20poly1305"

adversary:
  types: [global_observer, path_compromise]
  observed_paths: 1              # "all" or a path count (mutually exclusive with observed_as)
  observed_as: 1                  # "all" or an AS-group count, independent entry/exit visibility
  observation: {bin_width_ms: 100}
  classifier: {type: pearson, threshold: 0.7}
  compromised_fraction: 0.15     # for path_compromise
  compromise_trials: 3000

baseline: baseline.yaml           # optional: diffs this run against another config in report.md
```

See `examples/` for a Tor-like preset, a cover-traffic experiment, and a
multi-path custom config.

## Testing tools

`atl run <yaml>` runs one experiment and prints one metrics table
(plus a baseline diff if `baseline:` is set). `atl compare <yaml_a>
<yaml_b>` runs both and diffs every metric. `atl sweep <yaml>
--param X --values a,b,c` reruns one config varying a single field, one
CSV row per value. `atl wizard` walks through picking `tor_like` or
`custom`, filling in parameters, and reviewing the assembled YAML before
running. `atl dashboard` (needs `pip install -e ".[dashboard]"`)
starts a local web UI at `http://127.0.0.1:8765`: the same form as the
wizard, generating the same YAML, with an editable textarea for advanced
options the form doesn't expose (traffic shaping, link conditions, AS
groups, watermarking). It's the same `anontestlab.experiment.run_experiment`
under the hood, just reached over HTTP instead of the CLI.

Three adversaries are available. `global_observer` composes swappable
Observation (binning), Feature (`pearson` correlation, pluggable), and
Decision stages, reporting correlation accuracy, TPR at fixed FPR, AUC,
precision, and recall. Its visibility can be restricted by path count
(`observed_paths`) or by AS-group membership (`observed_as`): entry and
exit are independently visible based on which mock AS group their hop
belongs to, a more structured partial-observer model than a bare
fraction. `path_compromise` is an independent-compromise Monte Carlo
that needs no packets to move at all: if an adversary controls fraction
*f* of relays, what's the probability a session's path(s) are fully
compromised (the textbook *f^k*, generalized empirically to multi-path
sessions), deliberately independent-only with no correlated or
shared-operator modeling. `watermark` is an active attack: a designated
relay, always pinned to hop 1, delays every `period`-th real packet by a
fixed amount, and this adversary checks whether the pattern survives to
the observed exit timing. It's best used with a single path per session.

## Known limitations (v0.2)

These are disclosed simplifications, not claims of security properties
this doesn't have. The return path (delivery confirmations) isn't
re-encrypted per hop on the way back, and isn't subject to link
conditions either, since an unbounded read in circuit-build has no
retry (see the note in
`emulator/relay_process.py::forward_downstream_to_upstream`). Fixed-size
cells still shrink by a fixed amount per hop when enabled: it's the same
size at the same hop *position* for every circuit of that length, not
truly hop-invariant like Tor's non-expanding CTR construction, and
there's no fragmentation for payloads that don't fit the padding budget
(a clear error instead). WAN link conditions are uniform across every
link in the network, not per-edge, so there's no heterogeneous topology
modeling. Keys are ephemeral only, with no relay identity/directory
system, so there's no TOFU question to answer, but also no persistent
relay reputation. Only one path-selection strategy exists (uniform
random); the interesting axis here is path *count* and splitting, not
selection sophistication. On determinism: the experiment *design* (path
choices, traffic schedule) is reproducible from the seed, but real
measured latency and timing will vary run to run like any real system's
would, since sessions run concurrently over real sockets.

## Extending it

Routing strategies, traffic generators, and adversaries are small
classes registered in a lookup dict (`anontestlab.routing.STRATEGIES`,
`anontestlab.traffic.GENERATORS`, `anontestlab.adversary.ADVERSARIES`). Add one
by subclassing the relevant base class and registering it.

## License

GPL-3.0-or-later. See `LICENSE`.

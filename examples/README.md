# Experiment configs

Every experiment is one YAML file. `atl run <file>` runs it; `atl wizard`
and the dashboard's builder produce the same files.

## The examples

| File | What it shows |
|---|---|
| [`tor_like.yaml`](tor_like.yaml) | the `tor_like` preset: one path, three hops, random relays, no cover, no splitting |
| [`cover_traffic_evaluation.yaml`](cover_traffic_evaluation.yaml) | Poisson cover traffic at twice the real rate, dropped at intermediate hops, against a global observer |
| [`custom_multipath.yaml`](custom_multipath.yaml) | two paths with round-robin splitting; the adversary sees only one path |
| [`mixnet_pool.yaml`](mixnet_pool.yaml) | Loopix/Nym-style pool mixing at every hop, with the `atl paired` command to measure what it buys |

## Modes

`tor_like` (`experiment.mode: tor_like`) is a fixed preset. `custom`
makes every section below configurable.

## Every option

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
  max_concurrent: 20        # optional: run sessions in waves of this size (see `atl fidelity` in [the tools guide](../docs/tools.md))

routing:
  paths:
    - strategy: bandwidth_weighted   # or "random"
      path_length: 3
    - strategy: random
      path_length: 4
  split_strategy: round_robin   # round_robin | random | iid | batch | latency (see [Multipath](#multipath))
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

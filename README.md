# AnonTestLab

**[hashtagRR.github.io/AnonTestLab](https://hashtagRR.github.io/AnonTestLab)**

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23211927.svg)](https://doi.org/10.5281/zenodo.23211927)

<p align="center">
  <img src="docs/img/anontestlab-overview.svg" width="100%"
       alt="AnonTestLab overview in four stages. 1 Configure: one YAML file, mode tor_like or custom, run with atl run. 2 Run a live network: real relay processes on one machine, a session split over two legs that rejoin at a common exit, with configurable split policy, mixing, traffic, crypto, key exchange and link conditions; the adversary watches the entry and the merged exit. 3 Attack: correlation_suite, global_observer, watermark, hop_depth and path_compromise. 4 Keep results: measured latency, delivery, bandwidth and leg shares, attack scores, and a results folder. atl compare, sweep, paired, predict, fidelity and dashboard close the loop.">
</p>

A local network emulator for testing anonymous communication designs.
Each relay runs as a real OS process on its own loopback address
(`127.0.0.1`, `127.0.0.2`, ...). Circuits are built with a real
telescoping ECDHE handshake and per-hop AEAD encryption, and cells
travel over real sockets, so latency, delivery and attack results are
measured rather than modelled.

AnonTestLab uses its own simple wire protocol and does not reimplement
Tor: there is no directory or consensus system, and fixed-size cells are
opt-in.

## Quickstart

On Linux or macOS (Windows: see [INSTALL.md](INSTALL.md)):

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/atl run examples/tor_like.yaml
.venv/bin/atl compare examples/tor_like.yaml examples/cover_traffic_evaluation.yaml

.venv/bin/pip install -e ".[dashboard]"     # optional: local web UI
.venv/bin/atl dashboard                     # http://127.0.0.1:8765
```

`atl wizard` builds a config interactively. [What a run prints](docs/tools.md#what-a-run-prints).

## How a run works

1. The YAML is read into an `ExperimentConfig`.
2. `spawn_relays()` starts the relay processes.
3. For each session, `RoutingStrategy` picks the path or paths and `TrafficGenerator` produces the real and cover cells.
4. `build_circuit()` runs the per-hop handshakes (ECDHE + HKDF, hop-local circuit IDs) and sends onion-wrapped cells, with optional padding, relay mixing and WAN link conditions.
5. `MetricsCollector` records latency, delivery and bandwidth, and each configured adversary scores the observed traffic.
6. Results go to `results/<name>/`: `configuration.yaml`, `seed.txt`, `metrics.csv` and `report.md`.

## Configuring an experiment

`tor_like` is a fixed preset (one path, three hops, no cover, no
splitting); `custom` opens every section below. The full reference, with
every option and the four example files, is in
[examples/README.md](examples/README.md).

| Section | What it sets |
|---|---|
| `network`, `sessions` | relay count, AS groups, number of sessions, wave size |
| `routing` | paths, their selection strategy and length, and the [split policy](examples/README.md#multipath) across legs |
| `traffic`, `cover_behaviour` | rates, distribution (`poisson`, `constant`, `pareto`, `burst`), cover traffic and where it is dropped |
| `mixing` | relay-side delay at every hop: `constant`, `exponential`, `pool` |
| `traffic_shaping` | fixed-size cell padding and a fixed-rate send schedule |
| `crypto` | [per-hop AEAD and handshake curve](examples/README.md#crypto) |
| `link_conditions` | latency, jitter, loss and bandwidth, uniform or varied per node and per link |
| `adversary` | which [adversaries](anontestlab/adversary/README.md) run, and what they can see |
| `baseline` | another config to diff this run against |

## Tools

| Command | What it does |
|---|---|
| `atl run` | runs one experiment and prints its metrics |
| `atl compare` | runs two configs and diffs every metric |
| `atl sweep` | reruns one config over values of a single field |
| `atl paired` | runs two configs under the same seeds and tests the difference |
| `atl predict` | prints the model's predictions for a config without running it |
| `atl fidelity` | checks that host timing noise is small enough for the result to hold |
| `atl wizard` | builds a config interactively |
| `atl dashboard` | a local web workbench for all of the above |

Options and output of each: [docs/tools.md](docs/tools.md).

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

Routing strategies, traffic generators and adversaries are small classes
registered in a lookup dict (`anontestlab.routing.STRATEGIES`,
`anontestlab.traffic.GENERATORS`, `anontestlab.adversary.ADVERSARIES`).
Subclass the base class and register the new one; see
[anontestlab/adversary/README.md](anontestlab/adversary/README.md#adding-one)
for an adversary. AEAD ciphers are registered in
`anontestlab.crypto.ALGORITHMS` (with a matching `KEY_LENGTHS` entry);
handshake curves are listed in `KEYEXCHANGES` and handled in
`anontestlab.emulator.crypto_layer`.

A small discrete-event core (`anontestlab.core.Simulation`) is kept as a
generic utility; nothing in the run pipeline depends on it.

## Provenance

AnonTestLab began as a generalisation of the evaluation harness built for
Anon-Sec-Net, a dual-path anonymous communication prototype, and reuses
parts of that codebase. It is protocol-agnostic and works for other
designs.

It is the measurement instrument of a paper on correlation risk in
multipath anonymous communication, currently under review.

- **`v0.4.0`** (commit 199deae, [10.5281/zenodo.23211928](https://doi.org/10.5281/zenodo.23211928)) is the version the paper's experiments ran. Its code matches the study's frozen bundle apart from comments and documentation.
- **`v0.5.0`** adds the rebuilt dashboard with PDF reports and fixes the model's predictions for cover traffic on split legs. Measurements are unchanged. See [CHANGELOG.md](CHANGELOG.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

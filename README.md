# AnonTestLab

**[hashtagRR.github.io/AnonTestLab](https://hashtagRR.github.io/AnonTestLab)**

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23211927.svg)](https://doi.org/10.5281/zenodo.23211927)

<p align="center">
  <img src="docs/img/anontestlab-overview.svg" width="100%"
       alt="AnonTestLab overview in four stages. 1 Configure: one YAML file, mode tor_like or custom, run with atl run. 2 Run a live network: real relay processes on one machine, a session split over two legs that rejoin at a common exit, with configurable split policy, mixing, traffic, crypto, key exchange and link conditions; the adversary watches the entry and the merged exit. 3 Attack: correlation_suite, global_observer, watermark, hop_depth and path_compromise. 4 Keep results: measured latency, delivery, bandwidth and leg shares, attack scores, and a results folder. atl compare, sweep, paired, predict, fidelity and dashboard close the loop.">
</p>

A local network emulator for testing anonymous communication designs.
Relays run as real processes with real handshakes, encryption and
sockets, so latency, delivery and attack results are measured rather than
modelled.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/atl run examples/tor_like.yaml        # run an example experiment
.venv/bin/pip install -e ".[dashboard]" && .venv/bin/atl dashboard   # optional web UI
```

Windows and troubleshooting: [INSTALL.md](INSTALL.md).

## Documentation

| Guide | What it covers |
|---|---|
| [Experiment configs](examples/README.md) | every YAML option, split policies, crypto, and the four example configs |
| [Tools](docs/tools.md) | the `atl` commands (run, compare, sweep, paired, predict, fidelity, wizard) and the dashboard |
| [Adversaries](anontestlab/adversary/README.md) | the five attackers, what each measures, and how to add one |
| [Architecture](docs/architecture.md) | what happens during a run, and how to extend routing, traffic, crypto or adversaries |
| [Known limitations](docs/limitations.md) | simplifications to keep in mind when reading results |
| [Install guide](INSTALL.md) | platform setup, including Windows |
| [Changelog](CHANGELOG.md) | what changed in each version |
| [Project site](https://hashtagRR.github.io/AnonTestLab) | the project's overview page |

## Versions

- **`v0.5.0`** (latest): rebuilt dashboard with PDF reports, and a fix to the model's predictions for cover traffic on split legs.
- **`v0.4.0`** ([10.5281/zenodo.23211928](https://doi.org/10.5281/zenodo.23211928)): the version used for the experiments of a paper on correlation risk in multipath anonymous communication (under review).

AnonTestLab grew out of the test harness of Anon-Sec-Net, a dual-path
anonymous communication prototype, and works for other designs too.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

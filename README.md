# AnonTestLab

**[hashtagRR.github.io/AnonTestLab](https://hashtagRR.github.io/AnonTestLab)**

[![PyPI](https://img.shields.io/pypi/v/anontestlab.svg)](https://pypi.org/project/anontestlab/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23211927.svg)](https://doi.org/10.5281/zenodo.23211927)

<p align="center">
  <img src="https://raw.githubusercontent.com/hashtagRR/AnonTestLab/main/docs/img/anontestlab-overview.svg" width="100%"
       alt="AnonTestLab overview in four stages. 1 Configure: one YAML file, mode tor_like or custom, run with atl run. 2 Run a live network: real relay processes on one machine, a session split over two legs that rejoin at a common exit, with configurable split policy, mixing, traffic, crypto, key exchange and link conditions; the adversary watches the entry and the merged exit. 3 Attack: correlation_suite, global_observer, watermark, hop_depth and path_compromise. 4 Keep results: measured latency, delivery, bandwidth and leg shares, attack scores, and a results folder. atl compare, sweep, paired, predict, fidelity and dashboard close the loop.">
</p>

A local network emulator for testing anonymous communication designs.
Relays run as real processes with real handshakes, encryption and
sockets, so latency, delivery and attack results are measured rather than
modelled.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install "anontestlab[dashboard]"
curl -O https://raw.githubusercontent.com/hashtagRR/AnonTestLab/main/examples/tor_like.yaml
.venv/bin/atl run tor_like.yaml                 # run an example experiment
.venv/bin/atl dashboard                         # optional web UI
```

The other example configs are in [examples/](https://github.com/hashtagRR/AnonTestLab/tree/main/examples).
Windows, installing from the source code, and troubleshooting: [INSTALL.md](https://github.com/hashtagRR/AnonTestLab/blob/main/INSTALL.md).

## Documentation

| Guide | What it covers |
|---|---|
| [Experiment configs](https://github.com/hashtagRR/AnonTestLab/blob/main/examples/README.md) | every YAML option, split policies, crypto, and the four example configs |
| [Tools](https://github.com/hashtagRR/AnonTestLab/blob/main/docs/tools.md) | the `atl` commands (run, compare, sweep, paired, predict, fidelity, wizard) and the dashboard |
| [Adversaries](https://github.com/hashtagRR/AnonTestLab/blob/main/anontestlab/adversary/README.md) | the five attackers, what each measures, and how to add one |
| [Architecture](https://github.com/hashtagRR/AnonTestLab/blob/main/docs/architecture.md) | what happens during a run, and how to extend routing, traffic, crypto or adversaries |
| [Known limitations](https://github.com/hashtagRR/AnonTestLab/blob/main/docs/limitations.md) | simplifications to keep in mind when reading results |
| [Install guide](https://github.com/hashtagRR/AnonTestLab/blob/main/INSTALL.md) | platform setup, including Windows |
| [Contributing](https://github.com/hashtagRR/AnonTestLab/blob/main/CONTRIBUTING.md) | development setup and how releases are made |
| [Changelog](https://github.com/hashtagRR/AnonTestLab/blob/main/CHANGELOG.md) | what changed in each version |
| [Project site](https://hashtagRR.github.io/AnonTestLab) | the project's overview page |

## Versions

Every release and its changes are in the [changelog](https://github.com/hashtagRR/AnonTestLab/blob/main/CHANGELOG.md); each one is archived on Zenodo under the concept DOI above.

- **`v0.5.0`**: rebuilt dashboard with PDF reports, and a fix to the model's predictions for cover traffic on split legs.
- **`v0.4.0`** ([10.5281/zenodo.23211928](https://doi.org/10.5281/zenodo.23211928)): the version used for the experiments of a paper on correlation risk in multipath anonymous communication (under review).

AnonTestLab grew out of the test harness of Anon-Sec-Net, a dual-path
anonymous communication prototype, and works for other designs too.

## License

GPL-3.0-or-later. See [LICENSE](https://github.com/hashtagRR/AnonTestLab/blob/main/LICENSE).

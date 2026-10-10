# Tools

All tools take the same experiment YAML files as `atl run` (see
[the config reference](../examples/README.md)).

## At a glance

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

## Commands

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

## What a run prints

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

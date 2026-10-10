# Architecture

The [overview figure](../README.md) shows the four stages. This page covers the code behind them.

## How a run works

1. The YAML is read into an `ExperimentConfig`.
2. `spawn_relays()` starts the relay processes.
3. For each session, `RoutingStrategy` picks the path or paths and `TrafficGenerator` produces the real and cover cells.
4. `build_circuit()` runs the per-hop handshakes (ECDHE + HKDF, hop-local circuit IDs) and sends onion-wrapped cells, with optional padding, relay mixing and WAN link conditions.
5. `MetricsCollector` records latency, delivery and bandwidth, and each configured adversary scores the observed traffic.
6. Results go to `results/<name>/`: `configuration.yaml`, `seed.txt`, `metrics.csv` and `report.md`.

## Extending it

Routing strategies, traffic generators and adversaries are small classes
registered in a lookup dict (`anontestlab.routing.STRATEGIES`,
`anontestlab.traffic.GENERATORS`, `anontestlab.adversary.ADVERSARIES`).
Subclass the base class and register the new one; see
[the adversary guide](../anontestlab/adversary/README.md#adding-one)
for an adversary. AEAD ciphers are registered in
`anontestlab.crypto.ALGORITHMS` (with a matching `KEY_LENGTHS` entry);
handshake curves are listed in `KEYEXCHANGES` and handled in
`anontestlab.emulator.crypto_layer`.

A small discrete-event core (`anontestlab.core.Simulation`) is kept as a
generic utility; nothing in the run pipeline depends on it.

Known simplifications of the current version are listed in [limitations.md](limitations.md).

# Changelog

## 0.4.0

### Added
- Multipath splitting (`routing.split_strategy`): `iid`, weighted `round_robin`, `batch` and lowest-RTT `latency`, with `routing.merge: common_exit`, per-leg observation (`adversary.observed_legs`), a merged exit-side view (`adversary.egress_observation: merged`) and measured per-leg shares in the metrics.
- Relay-side mixing at every hop (`mixing.strategy`: `constant`, `exponential`, `pool`) and random-hop cover drop (`cover_behaviour.drop_mode: random_hop`).
- A bursty traffic generator (`traffic.distribution: burst`, `burst_mean_cells`, `burst_gap_ms`).
- The `correlation_suite` adversary: training-free attackers A0 (zero-lag), A1 (lag-aware binned correlation), A2 (likelihood ratio with the known delay density) and A3 (timing window), scored on one shared calibration/test split, with confident linkage, TPR at fixed FPR, signal estimate and AUC. Raw observations and score matrices are saved to `correlation_suite.npz`.
- Closed-form model predictions for the lag-aware attacker, recorded with every suite run and available as `atl predict`.
- `atl fidelity`, a check on host-induced timing noise, and wave mode (`sessions.max_concurrent`).
- `atl paired`, paired-seed comparisons with a bootstrap interval and an equivalence margin.
- `examples/mixnet_pool.yaml`.

### Changed
- TPR at a fixed FPR is conservative under tied scores (0 instead of 1), and the cut can be chosen on held-out calibration sessions (`adversary.evaluation.calibration_fraction`).

## 0.3.0

Real-process emulator with telescoping circuits, per-hop AEAD, selectable ciphers and curves, WAN link conditions, and the `global_observer`, `path_compromise`, `watermark` and `hop_depth` adversaries.

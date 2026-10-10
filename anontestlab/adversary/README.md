# Adversaries

Each adversary is a class registered in `ADVERSARIES` (`__init__.py`).
Pick one or several with `adversary.types` in the experiment YAML; their
parameters are listed in [the config reference](../../examples/README.md#every-option).

- **`global_observer`**: composes swappable Observation (binning), Feature (`pearson` correlation, pluggable), and Decision stages, reporting correlation accuracy, TPR at fixed FPR, AUC, precision, and recall. The TPR@FPR cut is conservative under tied scores (the realized FPR never exceeds the target), and each target also reports `realized_fpr_*` and `fpr_support_*` (expected impostor exceedances, i.e. how much tail backs the estimate). With `evaluation.calibration_fraction` > 0 the cut is chosen on calibration sessions and scored on disjoint test sessions. Visibility can be restricted by path count (`observed_paths`) or AS-group membership (`observed_as`): entry and exit are independently visible based on which mock AS group their hop belongs to, a more structured partial-observer model than a bare fraction.
- **`correlation_suite`**: runs training-free correlation attackers side by side on one shared calibration/test split: `a0` zero-lag and `a1` lag-aware binned-count correlation at each bin width (`bin_widths_s`, default 0.1, 0.25, 0.5, 1.0 s; lags up to max(2 s, P99 of the added delay) + 0.5 s), `a2` a likelihood-ratio attacker using the known delay distribution (Danezis's Poisson-intensity approximation), and `a3` a timing-window matcher (useful for sparse flows). Each attacker reports confident linkage `lpsi_<psi>_br_<base rate>` (share of true pairs the attacker would accept with posterior at least psi when that fraction of candidate pairs are true), TPR at fixed FPR with realized FPR, the signal estimate `mu_hat` and AUC. The run also reports the model's predictions (`model_*`) next to them, and saves the score matrices to `correlation_suite.npz`. Configure under `adversary.correlation_suite`.
- **`path_compromise`**: an independent-compromise Monte Carlo that needs no packets to move: if an adversary controls fraction *f* of relays, what's the probability a session's path(s) are fully compromised (the textbook *f^k*, generalized empirically to multi-path sessions). Deliberately independent-only, no correlated or shared-operator modeling.
- **`watermark`**: an active attack: a designated relay, always pinned to hop 1, delays every `period`-th real packet by a fixed amount, then checks whether the pattern survives to the observed exit timing. Best used with a single path per session.
- **`hop_depth`**: structural like `path_compromise` (no packets need to move): once fixed-size cell padding is on, quantifies the disclosed hop-position leak directly from `cell_size`/`crypto_algorithm`. Reports whether an observer at one hop can recover its exact position from size alone (`hop_position_accuracy`, 1.0 once shaping is enabled) and whether an observer at hop 1 can tell circuits of different lengths apart from size alone (`path_length_leak_at_hop1`, 0.0 by design; `nan` if only one circuit length appears in the experiment).

## Adding one

Subclass `Adversary` (`base.py`), implement `from_config` and
`attack(ctx, rng)`, which returns an `AdversaryResult`, and register the
class in `ADVERSARIES`.

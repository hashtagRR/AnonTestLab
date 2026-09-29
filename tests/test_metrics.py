import math

import numpy as np
import pytest

from anontestlab.adversary.decision import evaluate_scores
from anontestlab.metrics.stats import (
    cut_at_fpr,
    paired_bootstrap_delta,
    precision_recall_at_threshold,
    roc_auc,
    tpr_at_fpr,
    tpr_at_fpr_detail,
    wilson_ci,
)


def test_wilson_ci_zero_n():
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_reasonable_bounds():
    center, half_width = wilson_ci(50, 100)
    assert 0.4 < center < 0.6
    assert 0 < half_width < 0.15


def test_wilson_ci_narrows_with_more_samples():
    _, hw_small = wilson_ci(5, 10)
    _, hw_large = wilson_ci(500, 1000)
    assert hw_large < hw_small


def test_tpr_at_fpr_perfect_separation():
    true_scores = [0.9, 0.95, 0.99]
    impostor_scores = [0.1, 0.2, 0.3, 0.15, 0.05]
    result = tpr_at_fpr(true_scores, impostor_scores, [0.1, 0.5])
    assert result[0.1] == 1.0
    assert result[0.5] == 1.0


def test_tpr_at_fpr_no_separation():
    true_scores = [0.5, 0.5, 0.5]
    impostor_scores = [0.5, 0.5, 0.5, 0.5, 0.5]
    result = tpr_at_fpr(true_scores, impostor_scores, [0.1])
    # Every impostor ties the true scores, so any cut that flags a true pair
    # also flags 100% of impostors, far above the 10% target. The conservative
    # cut flags nothing. (This used to report 1.0 at a realized FPR of 1.0.)
    assert result[0.1] == 0.0


def test_roc_auc_perfect_separation():
    assert roc_auc([0.9, 0.95], [0.1, 0.2, 0.3]) == 1.0


def test_roc_auc_no_separation_is_half():
    assert roc_auc([0.5, 0.5], [0.5, 0.5]) == 0.5  # all ties -> 0.5 credit each


def test_roc_auc_empty_inputs_is_nan():
    import math

    assert math.isnan(roc_auc([], [0.1]))
    assert math.isnan(roc_auc([0.1], []))


def test_precision_recall_perfect_separation():
    precision, recall = precision_recall_at_threshold([0.9, 0.8], [0.1, 0.2, 0.3], threshold=0.5)
    assert (precision, recall) == (1.0, 1.0)


def test_precision_recall_no_separation():
    precision, recall = precision_recall_at_threshold([0.5, 0.5], [0.5, 0.5, 0.5], threshold=0.5)
    assert precision == 2 / 5  # 2 true positives out of 5 flagged
    assert recall == 1.0


def test_cut_never_exceeds_target_fpr_under_ties():
    impostor = np.array([0.9, 0.9, 0.9, 0.5, 0.5, 0.1, 0.1, 0.1, 0.1, 0.1])
    for fpr in (0.1, 0.2, 0.3, 0.5, 0.9):
        cut = cut_at_fpr(impostor, fpr)
        assert np.mean(impostor > cut) <= fpr + 1e-12


def test_cut_allows_everything_at_fpr_one():
    assert cut_at_fpr(np.array([0.2, 0.4]), 1.0) == -math.inf


def test_detail_reports_realized_fpr_and_support():
    rng = np.random.default_rng(0)
    cal = rng.normal(size=2000)
    test = rng.normal(size=2000)
    point = tpr_at_fpr_detail([3.0, 4.0], cal, [0.01], test_impostor_scores=test)[0.01]
    assert point.tpr == 1.0
    assert point.expected_exceedances == pytest.approx(20.0)
    assert 0.0 <= point.realized_fpr < 0.03  # held-out FPR close to the target


def test_held_out_split_uses_disjoint_sessions():
    rng = np.random.default_rng(1)
    n = 40
    scores = rng.normal(size=(n, n))
    np.fill_diagonal(scores, 5.0)  # perfectly separable true pairs
    m = evaluate_scores(scores, 0.7, (0.01,), calibration_fraction=0.5, rng=np.random.default_rng(2))
    assert m["calibration_sessions"] + m["test_sessions"] == n
    assert m["tpr_at_fpr_0.01"] == 1.0
    assert m["realized_fpr_0.01"] <= 0.05


def test_paired_bootstrap_classifies_equivalence():
    ref = [0.50, 0.52, 0.49, 0.51, 0.50, 0.48, 0.52, 0.50, 0.51, 0.49, 0.50, 0.51]
    same = [x + d for x, d in zip(ref, [0.01, -0.01, 0.0, 0.01, -0.01, 0.0, 0.01, 0.0, -0.01, 0.0, 0.01, -0.01])]
    assert paired_bootstrap_delta(ref, same).classification == "no_meaningful_effect"


def test_paired_bootstrap_classifies_effect():
    ref = [0.50] * 12
    lower = [0.30 + 0.01 * (i % 3) for i in range(12)]
    effect = paired_bootstrap_delta(ref, lower)
    assert effect.classification == "meaningful_effect"
    assert effect.mean_delta < -0.05 and effect.ci_high < 0


def test_paired_bootstrap_noisy_null_is_inconclusive_not_null():
    ref = [0.5] * 12
    noisy = [0.5 + (0.15 if i % 2 else -0.15) for i in range(12)]
    assert paired_bootstrap_delta(ref, noisy).classification == "inconclusive"


def test_paired_bootstrap_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        paired_bootstrap_delta([0.1, 0.2], [0.1])

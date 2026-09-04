from anontestlab.metrics.stats import wilson_ci, tpr_at_fpr, roc_auc, precision_recall_at_threshold


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
    assert result[0.1] == 1.0  # threshold ties everything at 0.5


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

from benchmarks.ranking.runner import _compare, _quality_gates


def test_quality_gate_rejects_low_top5_even_when_comparative_baseline_matches():
    metrics = {
        "top_5_precision": 0.2,
        "top_10_recall": 1.0,
        "test_recommendation_precision": 1.0,
        "noise_ratio": 0.0,
        "explanation_completeness": 1.0,
        "default_entities_are_actionable": 1.0,
    }
    expected = {"expected_top_5_entities": ["file:service.py"], "expected_tests": []}
    gates = _quality_gates(metrics, expected, 0.2)
    comparison = _compare(metrics, {"policy": {"ranking_policy_version": "review-ranking/v1.2"}, "metrics": metrics})
    assert gates["status"] == "failed"
    assert "top_5_precision" in gates["failed"]
    assert gates["policy_independent"] is True
    assert comparison["status"] == "ignored_non_independent_baseline"


def test_quality_gate_does_not_call_missing_test_labels_perfect_precision():
    metrics = {
        "top_5_precision": 1.0,
        "top_10_recall": 1.0,
        "test_recommendation_precision": 1.0,
        "noise_ratio": 0.0,
        "explanation_completeness": 1.0,
        "default_entities_are_actionable": 1.0,
    }
    gates = _quality_gates(metrics, {"expected_top_5_entities": ["x"], "expected_tests": []}, 0.2)
    assert gates["checks"]["test_recommendation_precision"]["passed"] is None
    assert "test_recommendation_precision" in gates["not_evaluable"]

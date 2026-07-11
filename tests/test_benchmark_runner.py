from pathlib import Path

from impact_engine.benchmarks import run_benchmark_fixture, run_determinism_check, run_mutation_suite, run_benchmark_suite
from impact_engine.benchmarks.runner import aggregate_metrics


ROOT = Path(__file__).resolve().parents[1]


def test_python_golden_benchmark_reports_precision_and_forbidden_edges():
    result = run_benchmark_fixture(ROOT / "benchmarks/fixtures/python/constructor_di/benchmark_manifest.json")
    assert result["status"] == "passed"
    assert result["true_positive"] == 1
    assert result["false_positive"] == 0
    assert result["recall"] == 1.0


def test_golden_fixture_is_deterministic():
    result = run_determinism_check(ROOT / "examples/golden_cases/python_di_basic", runs=3)
    assert result["status"] == "ok"
    assert result["coverage_equal"] is True


def test_python_benchmark_suite_has_negative_fixture_and_quality_metrics():
    result = run_benchmark_suite(ROOT / "benchmarks")
    assert result["fixtures"] >= 8
    assert result["status"] == "ok"
    assert result["overall"]["precision"] >= 0.95
    assert result["overall"]["forbidden_violations"] == 0
    assert result["by_fixture"]["python_ambiguous_constructor"]["false_positive"] == 0


def test_mutation_suite_runs_at_least_ten_scenarios_without_false_positive_regression():
    result = run_mutation_suite(ROOT / "benchmarks")
    assert result["mutations"] >= 10
    assert result["mutation_failed"] == 0
    assert result["quality_gates"]["mutation_failures_zero"] is True


def test_positive_function_rules_are_real_positive_cases():
    for fixture_id in ("python_direct_local", "python_imported_function", "python_alias_import"):
        result = run_benchmark_suite(ROOT / "benchmarks")["by_fixture"][fixture_id]
        assert result["expected_edges"] >= 1
        assert result["true_positive"] >= 1
        assert result["coverage"]["totals"]["resolved_exact"] >= 1


def test_metrics_do_not_claim_precision_for_empty_rule_scope():
    result = aggregate_metrics([])
    assert result["status"] == "no_positive_cases"
    assert result["precision"] is None
    assert result["recall"] is None

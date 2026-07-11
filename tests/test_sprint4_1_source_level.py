import json
from pathlib import Path

from impact_engine.benchmarks.source_typescript import run_source_typescript_benchmark


def test_source_level_sprint4_1_benchmark_passes():
    result = run_source_typescript_benchmark(".")
    assert result["status"] == "ok"
    assert result["fact_level_fixtures"] == 0
    assert result["source_level_fixtures"] == 8
    assert result["source_level_precision"] >= 0.95
    assert result["mutation_failures"] == 0
    assert result["determinism"] is True


def test_react_pack_has_real_trust_contract():
    pack = json.loads(Path("support_packs/javascript/react/support_pack.json").read_text(encoding="utf-8"))
    assert pack["trust_level"] == "verified_on_fixture"
    assert len(pack["fixtures"]) >= 4
    assert len(pack["negative_cases"]) >= 2
    assert len(pack["mutation_scenarios"]) >= 3
    assert pack["resolver_hooks"]

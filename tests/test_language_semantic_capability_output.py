from __future__ import annotations

from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core


def test_analyze_output_includes_honest_language_semantic_capabilities():
    project = Path(__file__).parent / "fixtures" / "polyglot_real"

    result = analyze_project_core(str(project))

    capabilities = result["graph"]["metadata"]["language_semantic_capabilities"]
    diagnostics_capabilities = result["diagnostics"]["language_semantic_capabilities"]

    assert capabilities == diagnostics_capabilities
    assert capabilities["javascript"]["capabilities"]["production_semantic_baseline"] is False
    assert capabilities["javascript"]["capabilities"]["endpoint_resolution"] is True
    assert capabilities["typescript"]["capabilities"]["call_resolution"] == "limited"
    assert capabilities["go"]["capabilities"]["endpoint_resolution"] is False
    assert capabilities["java"]["capabilities"]["framework_rules"] is False
    assert "not full" in " ".join(capabilities["typescript"]["capabilities"]["notes"]).lower()


def test_python_output_declares_only_python_as_production_semantic_baseline():
    project = Path(__file__).parent / "fixtures" / "python_semantics_project"

    result = analyze_project_core(str(project))

    capabilities = result["graph"]["metadata"]["language_semantic_capabilities"]
    assert list(capabilities) == ["python"]
    assert capabilities["python"]["capabilities"]["production_semantic_baseline"] is True
    assert capabilities["python"]["capabilities"]["call_resolution"] == "semantic"

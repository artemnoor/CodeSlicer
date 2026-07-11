import sys
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core


def test_core_analysis_works_without_graphify_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "graphify", None)
    project = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
    res = analyze_project_core(str(project))
    assert res["status"] == "ok"
    assert res["nodes"] > 0
    assert res["edges"] > 0

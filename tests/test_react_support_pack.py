from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument


def test_react_support_pack_emits_low_confidence_support_pack_edge():
    project = Path(__file__).parent / "fixtures" / "e2e_polyglot_project"
    res = analyze_project_core(str(project))
    graph = GraphDocument.from_dict(res["graph"])
    react_edges = [e for e in graph.edges if e.properties.get("support_pack_library") == "react" and e.kind == "DEPENDS_ON"]
    assert react_edges
    for edge in react_edges:
        assert edge.source == "SUPPORT_PACK"
        assert edge.confidence < 0.80
        assert edge.properties.get("support_pack_rule_id") == "react_jsx_usage"
        assert edge.evidence

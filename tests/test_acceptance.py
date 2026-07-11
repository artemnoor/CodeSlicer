import pytest
import json
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.impact import impact_query, explain_edge
from impact_engine.support_packs.registry import validate_support_pack_file
from impact_engine.research.workflow import init_workflow

GOLDEN_PROJECT = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"
POLYGLOT_PROJECT = Path(__file__).parent / "fixtures" / "e2e_polyglot_project"
SUPPORT_PACK_FILE = Path(__file__).parent.parent / "support_packs" / "python" / "fastapi" / "support_pack.json"


def test_acceptance_golden_mvp_edge():
    res = analyze_project_core(str(GOLDEN_PROJECT))
    assert res["status"] == "ok"
    
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    # Verify golden MVP edge:
    # services.OrderService.create_order CALLS repositories.OrderRepository.save
    # confidence >= 0.80
    # evidence_count >= 1
    mvp_edge = next((e for e in graph.edges if e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save"), None)
    assert mvp_edge is not None
    assert mvp_edge.kind == "CALLS"
    assert mvp_edge.source == "INFERRED"
    assert mvp_edge.confidence >= 0.80
    assert len(mvp_edge.evidence) >= 1


def test_acceptance_polyglot_fixture():
    res = analyze_project_core(str(POLYGLOT_PROJECT))
    assert res["status"] == "ok"
    assert "javascript" in res["languages"]
    assert "typescript" in res["languages"]


def test_acceptance_support_pack_validation():
    res = validate_support_pack_file(str(SUPPORT_PACK_FILE))
    assert res["valid"] is True
    assert res["library"] == "fastapi"


def test_acceptance_research_workflow_creation_without_internet():
    wf_id = init_workflow(str(GOLDEN_PROJECT), "some_unknown_lib", "python")
    assert wf_id is not None
    # Verify files created inside the workflow directory locally
    wf_dir = Path(".impact_engine/research_workflows") / wf_id
    assert wf_dir.exists()
    assert (wf_dir / "research_request.json").exists()


def test_acceptance_impact_query_and_explain_edge():
    res = analyze_project_core(str(GOLDEN_PROJECT))
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    impact_res = impact_query(
        graph,
        target="repositories.OrderRepository.save",
        direction="upstream"
    )
    affected_ids = [n["id"] for n in impact_res["affected_nodes"]]
    assert "services.OrderService.create_order" in affected_ids
    
    exp_res = explain_edge(
        graph,
        from_symbol="services.OrderService.create_order",
        to_symbol="repositories.OrderRepository.save"
    )
    assert exp_res["found"] is True
    assert len(exp_res["evidence_chain"]) >= 1
    assert len(exp_res["reasoning_steps"]) >= 1


def test_acceptance_graphify_is_optional():
    from impact_engine.adapters.graphify import is_graphify_available
    available = is_graphify_available()
    assert isinstance(available, bool)
    # Removing graphify sample/module must not break core analysis
    res = analyze_project_core(str(GOLDEN_PROJECT))
    assert res["status"] == "ok"


def test_acceptance_tree_sitter_availability_diagnostics():
    # Tree-sitter availability diagnostics should be clean and readable in the result
    res = analyze_project_core(str(GOLDEN_PROJECT))
    assert "diagnostics" in res
    assert isinstance(res["diagnostics"], dict)

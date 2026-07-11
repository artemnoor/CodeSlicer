from __future__ import annotations

import json
from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import explain_edge
from impact_engine.models import GraphDocument, Node
from impact_engine.support_packs.resolution import apply_support_pack_rules
from impact_engine.support_packs.schema import support_pack_from_dict


ROOT = Path(__file__).parent.parent
FASTAPI_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "fastapi_realistic"
DI_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "dependency_injector_realistic"
REACT_REALISTIC = Path(__file__).parent / "fixtures" / "frameworks" / "react_realistic"


def _assert_unified_provenance(edge, *, support_pack: str, rule_id: str, resolver_hook: str):
    provenance = edge.properties.get("support_pack")
    assert isinstance(provenance, dict), f"{edge.id} missing unified support_pack provenance"
    assert provenance["support_pack"] == support_pack
    assert provenance["rule_id"] == rule_id
    assert provenance["rule_version"] == "1.0.0"
    assert provenance["trust_level"] in {"verified_on_real_project", "trusted", "verified_on_fixture", "experimental"}
    assert provenance["resolver_hook"] == resolver_hook
    assert "matched_pattern" in provenance
    assert isinstance(provenance["evidence"], list)
    assert provenance["evidence"]


def test_fastapi_edges_have_unified_provenance_and_explain_rule_attribution():
    result = analyze_project_core(str(FASTAPI_REALISTIC))
    graph = GraphDocument.from_dict(result["graph"])

    edge = next(
        e
        for e in graph.edges
        if e.from_node == "HTTP POST /api/orders/" and e.to_node == "app.routers.create_order"
    )
    _assert_unified_provenance(
        edge,
        support_pack="python/fastapi",
        rule_id="fastapi-router-post-route",
        resolver_hook="decorator_entrypoint",
    )

    explanation = explain_edge(graph, edge.from_node, edge.to_node, edge.kind)
    assert explanation["found"] is True
    assert explanation["rule_attribution"] == edge.properties["support_pack"]
    assert explanation["support_pack_rules_used"] == ["fastapi-router-post-route"]


def test_dependency_injector_edges_have_unified_provenance_and_explain_rule_attribution():
    result = analyze_project_core(str(DI_REALISTIC))
    graph = GraphDocument.from_dict(result["graph"])

    edge = next(
        e
        for e in graph.edges
        if e.from_node == "app.container.Container.order_service"
        and e.to_node == "app.services.OrderService"
    )
    _assert_unified_provenance(
        edge,
        support_pack="python/dependency_injector",
        rule_id="dependency-injector-resolver-rule",
        resolver_hook="dependency_injector_resolver",
    )

    explanation = explain_edge(graph, edge.from_node, edge.to_node, edge.kind)
    assert explanation["found"] is True
    assert explanation["rule_attribution"] == edge.properties["support_pack"]
    assert explanation["support_pack_rules_used"] == ["dependency-injector-resolver-rule"]


def test_react_edges_have_unified_provenance_and_explain_rule_attribution():
    result = analyze_project_core(str(REACT_REALISTIC))
    graph = GraphDocument.from_dict(result["graph"])

    graph.add_node(Node(id="HTTP POST /api/orders/", name="HTTP POST /api/orders/", kind="ROUTE"))
    react_pack_path = ROOT / "support_packs" / "javascript" / "react" / "support_pack.json"
    react_pack = support_pack_from_dict(json.loads(react_pack_path.read_text(encoding="utf-8")))
    graph = apply_support_pack_rules(graph, [react_pack])

    edge = next(e for e in graph.edges if e.from_node == "postOrder" and e.to_node == "HTTP POST /api/orders/")
    _assert_unified_provenance(
        edge,
        support_pack="javascript/react",
        rule_id="react-component-hook-resolver",
        resolver_hook="react_resolver",
    )

    explanation = explain_edge(graph, edge.from_node, edge.to_node, edge.kind)
    assert explanation["found"] is True
    assert explanation["rule_attribution"] == edge.properties["support_pack"]
    assert explanation["support_pack_rules_used"] == ["react-component-hook-resolver"]

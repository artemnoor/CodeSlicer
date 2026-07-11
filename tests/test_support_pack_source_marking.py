from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.support_packs.resolution import apply_support_pack_rules


def test_source_provenance_classes_remain_distinct():
    graph = GraphDocument()
    graph.add_node(Node(
        id="call:1",
        kind="CALL_EXPR",
        name="do_work",
        properties={"scope": "module.func", "call_name": "lib.do_work"},
    ))
    graph.add_node(Node(id="a", kind="FUNCTION", name="a"))
    graph.add_node(Node(id="b", kind="FUNCTION", name="b"))
    graph.add_node(Node(id="c", kind="FUNCTION", name="c"))
    graph.add_node(Node(id="d", kind="FUNCTION", name="d"))
    graph.add_edge(Edge(
        id="inferred-edge",
        kind="CALLS",
        from_node="a",
        to_node="b",
        source="INFERRED",
        confidence=0.85,
        evidence=[Evidence(description="precision resolver evidence")],
    ))
    graph.add_edge(Edge(
        id="external-edge",
        kind="CALLS",
        from_node="b",
        to_node="c",
        source="EXTERNAL_TOOL",
        confidence=0.7,
    ))
    graph.add_edge(Edge(
        id="runtime-edge",
        kind="CALLS",
        from_node="c",
        to_node="d",
        source="RUNTIME_CONFIRMED",
        confidence=1.0,
    ))

    pack = {
        "library": "lib",
        "version_range": ">=1",
        "language": "python",
        "edge_rules": [{
            "id": "lib-call",
            "match": {"node_kind": "CALL_EXPR", "call_name": "lib.do_work"},
            "emit": {"kind": "DEPENDS_ON", "to": "external:lib.do_work", "source": "INFERRED", "confidence": 0.7},
        }],
    }

    resolved = apply_support_pack_rules(graph, [pack])

    support_edge = next(e for e in resolved.edges if e.properties.get("support_pack_rule_id") == "lib-call")
    assert support_edge.source == "SUPPORT_PACK"
    assert support_edge.source != "INFERRED"

    assert next(e for e in resolved.edges if e.id == "inferred-edge").source == "INFERRED"
    assert next(e for e in resolved.edges if e.id == "external-edge").source == "EXTERNAL_TOOL"
    assert next(e for e in resolved.edges if e.id == "runtime-edge").source == "RUNTIME_CONFIRMED"


def test_support_pack_edge_conflict_does_not_downgrade_runtime_or_inferred_sources():
    graph = GraphDocument()
    graph.add_node(Node(id="x", kind="FUNCTION", name="x"))
    graph.add_node(Node(id="y", kind="FUNCTION", name="y"))
    graph.add_edge(Edge(
        id="runtime",
        kind="CALLS",
        from_node="x",
        to_node="y",
        source="RUNTIME_CONFIRMED",
        confidence=1.0,
        properties={"rule_id": "same"},
    ))
    graph.add_edge(Edge(
        id="support",
        kind="CALLS",
        from_node="x",
        to_node="y",
        source="SUPPORT_PACK",
        confidence=0.7,
        properties={"rule_id": "same"},
    ))
    edge = next(e for e in graph.edges if e.from_node == "x" and e.to_node == "y")
    assert edge.source == "RUNTIME_CONFIRMED"
    assert edge.confidence == 1.0

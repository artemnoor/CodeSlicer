import pytest
from pathlib import Path
from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.support_packs.schema import SupportPack
from impact_engine.support_packs.resolution import apply_support_pack_rules
from impact_engine.support_packs.registry import load_support_pack

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_apply_support_pack_rules_no_packs_noop():
    graph = extract_project(PROJECT_PATH)
    initial_count = len(graph.edges)
    
    result = apply_support_pack_rules(graph, [])
    assert len(result.edges) == initial_count


def test_resolve_precision_without_support_packs_preserves_mvp_edge():
    graph = extract_project(PROJECT_PATH)
    resolved = resolve_precision(graph)
    
    mvp_edge = next(
        (e for e in resolved.edges if e.from_node == "services.OrderService.create_order" and e.to_node == "repositories.OrderRepository.save" and e.kind == "CALLS"),
        None
    )
    assert mvp_edge is not None
    assert mvp_edge.source == "INFERRED"
    assert mvp_edge.confidence >= 0.80
    assert len(mvp_edge.evidence) > 0


def test_support_pack_demo_rule_emits_support_pack_edge():
    graph = GraphDocument()
    
    # Manually create GraphDocument with CALL_EXPR node
    call_node = Node(
        id="call:test:1:example_library.do_work",
        kind="CALL_EXPR",
        name="do_work",
        properties={
            "scope": "module.func",
            "call_name": "example_library.do_work"
        }
    )
    graph.add_node(call_node)
    
    # Create SupportPack with demo rule
    demo_pack = SupportPack(
        library="example_library",
        version_range=">=0.1",
        language="python",
        status="experimental",
        sources=[],
        patterns=[],
        edge_rules=[
            {
                "id": "demo-rule-1",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "example_library.do_work"
                },
                "emit": {
                    "kind": "DEPENDS_ON",
                    "to": "external:example_library.do_work",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.8,
                    "description": "example_library.do_work dependency from support pack"
                }
            }
        ],
        confidence_rules=[],
        playground_cases=[]
    )
    
    result = apply_support_pack_rules(graph, [demo_pack])
    
    # Assert edge appeared
    new_edge = next((e for e in result.edges if e.kind == "DEPENDS_ON"), None)
    assert new_edge is not None
    assert new_edge.from_node == "module.func"
    assert new_edge.to_node == "external:example_library.do_work"
    assert new_edge.source == "SUPPORT_PACK"
    assert new_edge.confidence == 0.65
    assert new_edge.properties["support_pack_trust_level"] == "experimental"
    assert new_edge.properties["support_pack_confidence_cap"] == 0.65
    assert len(new_edge.evidence) == 1
    assert new_edge.evidence[0].description == "example_library.do_work dependency from support pack"


def test_support_pack_rules_do_not_create_ai_proposed_edges():
    graph = GraphDocument()
    call_node = Node(
        id="call:test:1:example_library.do_work",
        kind="CALL_EXPR",
        name="do_work",
        properties={
            "scope": "module.func",
            "call_name": "example_library.do_work"
        }
    )
    graph.add_node(call_node)
    
    # Create SupportPack with demo rule trying to force AI_PROPOSED
    demo_pack = SupportPack(
        library="example_library",
        version_range=">=0.1",
        language="python",
        status="experimental",
        edge_rules=[
            {
                "id": "demo-rule-1",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "example_library.do_work"
                },
                "emit": {
                    "kind": "DEPENDS_ON",
                    "to": "external:example_library.do_work",
                    "source": "AI_PROPOSED",
                    "confidence": 0.8,
                    "description": "AI PROPOSED dependency from support pack"
                }
            }
        ]
    )
    
    result = apply_support_pack_rules(graph, [demo_pack])
    # Should skip AI_PROPOSED edges
    assert not any(e.source == "AI_PROPOSED" for e in result.edges)


def test_support_pack_rules_are_deduplicated():
    graph = GraphDocument()
    call_node = Node(
        id="call:test:1:example_library.do_work",
        kind="CALL_EXPR",
        name="do_work",
        properties={
            "scope": "module.func",
            "call_name": "example_library.do_work"
        }
    )
    graph.add_node(call_node)
    
    demo_pack = SupportPack(
        library="example_library",
        version_range=">=0.1",
        language="python",
        status="experimental",
        edge_rules=[
            {
                "id": "demo-rule-1",
                "match": {
                    "node_kind": "CALL_EXPR",
                    "call_name": "example_library.do_work"
                },
                "emit": {
                    "kind": "DEPENDS_ON",
                    "to": "external:example_library.do_work",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.8,
                    "description": "example_library.do_work dependency from support pack"
                }
            }
        ]
    )
    
    result = apply_support_pack_rules(graph, [demo_pack])
    assert len(result.edges) == 1
    
    # Call twice
    result2 = apply_support_pack_rules(result, [demo_pack])
    assert len(result2.edges) == 1


def test_method_call_alias_supports_method_lists_and_receiver_types():
    graph = GraphDocument()
    graph.add_node(Node(
        id="call:client:1:post",
        kind="CALL_EXPR",
        name="post",
        properties={
            "scope": "orders.create",
            "method_name": "post",
            "receiver_type": "httpx.Client",
            "file": "orders.py",
            "line": 4,
        },
    ))
    pack = load_support_pack(Path("support_packs/python/httpx/support_pack.json"))

    result = apply_support_pack_rules(graph, [pack])

    edge = next(edge for edge in result.edges if edge.kind == "HTTP_CALLS")
    assert edge.to_node == "external:httpx.post"
    assert edge.properties["support_pack_rule_id"] == "httpx-client-request-method"
    assert edge.properties["support_pack"]["support_pack"] == "python/httpx"

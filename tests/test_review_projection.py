from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY
from impact_engine.review_projection import build_review_projection
from impact_engine.review_projection.test_selection import select_targeted_tests


def _graph():
    graph = GraphDocument()
    graph.add_node(Node("repo.save", "METHOD", "save", {"file": "src/repo.py", "line": 4, "critical": True}))
    graph.add_node(Node("service.order", "METHOD", "create_order", {"file": "src/service.py", "line": 8}))
    graph.add_node(Node("route.orders", "ROUTE", "POST /orders", {"file": "src/routes.py", "line": 12, "boundary_category": "api"}))
    graph.add_node(Node("tests.orders", "TEST", "test_create_order", {"file": "tests/test_orders.py", "line": 3, "test_command": "pytest tests/test_orders.py"}))
    graph.add_node(Node("tmp.assignment", "ASSIGNMENT", "tmp", {"file": "src/service.py", "line": 9}))
    graph.add_node(Node("builtin.len", "CALL_EXPR", "len", {"file": "src/service.py", "line": 10, "builtin": True}))
    graph.add_node(Node("external.sql", "EXTERNAL_LIBRARY", "sqlalchemy", {"file": "<external>"}))
    graph.add_edge(Edge("call-1", "CALLS", "service.order", "repo.save", confidence=.96, evidence=[Evidence("service calls repository", "src/service.py", 8)]))
    graph.add_edge(Edge("route-1", "ROUTE_HANDLES", "route.orders", "service.order", confidence=.98, evidence=[Evidence("route delegates to service", "src/routes.py", 12)], properties={"boundary_category": "route"}))
    graph.add_edge(Edge("test-1", "TESTS", "tests.orders", "repo.save", confidence=.95, evidence=[Evidence("test invokes changed repository", "tests/test_orders.py", 3)]))
    graph.add_edge(Edge("assign-1", "ASSIGNS", "service.order", "tmp.assignment", confidence=1.0))
    graph.add_edge(Edge("builtin-1", "CALLS", "service.order", "builtin.len", confidence=.99))
    graph.add_edge(Edge("external-1", "IMPORTS", "service.order", "external.sql", confidence=.99, evidence=[Evidence("service imports library", "src/service.py", 1)]))
    return graph


def test_projection_contract_is_bounded_and_preserves_full_graph():
    graph = _graph()
    projection = build_review_projection(
        graph,
        [{"id": "repo.save", "kind": "METHOD", "file": "src/repo.py", "line": 4}],
        {"src/repo.py"},
        max_results=10,
    )
    assert len(projection.candidates) <= 10
    assert len(graph.nodes) == 7  # projection did not delete full-graph facts
    assert all(item.kind not in {"ASSIGNMENT", "EXTERNAL_LIBRARY"} for item in projection.candidates)
    changed = next(item for item in projection.candidates if item.entity_id == "repo.save")
    assert changed.evidence_ids
    assert changed.why_affected["evidence"]
    assert projection.suppressed_candidates
    assert any(item.entity_id == "tmp.assignment" for item in projection.suppressed_candidates)


def test_policy_is_named_and_direct_boundary_beats_weak_transitive_path():
    policy = DEFAULT_RANKING_POLICY
    assert policy.version.startswith("review-ranking/")
    assert all(factor.rationale and factor.test_fixture for factor in policy.factors)
    projection = build_review_projection(
        _graph(), [{"id": "repo.save", "kind": "METHOD", "file": "src/repo.py", "line": 4}], {"src/repo.py"}
    )
    route = next(item for item in projection.candidates if item.entity_id == "route.orders")
    service = next(item for item in projection.candidates if item.entity_id == "service.order")
    assert route.impact_class == "boundary"
    assert "route_handler_boundary" in route.rank.factors
    assert route.rank.score > service.rank.score


def test_changed_callable_downstream_calls_are_top_impacts_without_reverse_noise():
    graph = GraphDocument()
    graph.add_node(Node("service.place_order", "METHOD", "place_order", {"file": "app/service.py", "line": 10}))
    graph.add_node(Node("repo.save", "METHOD", "save", {"file": "app/repo.py", "line": 5}))
    graph.add_node(Node("email.send_email", "FUNCTION", "send_email", {"file": "app/email.py", "line": 5}))
    graph.add_node(Node("service.init", "METHOD", "__init__", {"file": "app/service.py", "line": 2}))
    graph.add_edge(Edge("place-save", "CALLS", "service.place_order", "repo.save", confidence=.99, evidence=[Evidence("save call", "app/service.py", 12)]))
    graph.add_edge(Edge("place-email", "CALLS", "service.place_order", "email.send_email", confidence=.98, evidence=[Evidence("email call", "app/service.py", 13)]))
    graph.add_edge(Edge("init-place", "IMPORTS", "service.init", "service.place_order", confidence=.99, evidence=[Evidence("service setup", "app/service.py", 2)]))
    graph.add_edge(Edge("reverse-noise", "CALLS", "repo.save", "service.init", confidence=.99, evidence=[Evidence("reverse noise", "app/repo.py", 20)]))

    projection = build_review_projection(
        graph,
        [{"id": "service.place_order", "kind": "METHOD", "file": "app/service.py", "line": 10, "changed_lines": [12, 13]}],
        {"app/service.py"},
    )
    ids = [item.entity_id for item in projection.candidates]
    assert ids.index("repo.save") < ids.index("service.init")
    assert ids.index("email.send_email") < ids.index("service.init")
    assert "changed_downstream" in next(item for item in projection.candidates if item.entity_id == "repo.save").rank.factors
    assert all(item.entity_id != "service.init" or "reverse-noise" not in item.evidence_ids for item in projection.candidates)


def test_broad_discovery_separates_low_certainty_paths_from_review_and_tests():
    graph = GraphDocument()
    graph.add_node(Node("service.changed", "METHOD", "changed", {"file": "app/service.py", "line": 10}))
    graph.add_node(Node("repo.confirmed", "METHOD", "save", {"file": "app/repo.py", "line": 5}))
    graph.add_node(Node("client.dynamic", "CALL_EXPR", "client.call", {"file": "app/client.py", "line": 7, "boundary": True}))
    graph.add_node(Node("repo.weak", "METHOD", "maybe_save", {"file": "app/maybe_repo.py", "line": 4}))
    graph.add_node(Node("route.rejected", "ROUTE", "POST /rejected", {"file": "app/routes.py", "line": 3, "boundary_category": "api"}))
    graph.add_edge(Edge("confirmed", "CALLS", "service.changed", "repo.confirmed", confidence=.96, evidence=[Evidence("resolved repository call", "app/service.py", 11)]))
    graph.add_edge(Edge("dynamic", "CALLS", "service.changed", "client.dynamic", confidence=.42, evidence=[Evidence("dynamic receiver call", "app/service.py", 12)], properties={"resolution_status": "unresolved"}))
    graph.add_edge(Edge("weak", "CALLS", "service.changed", "repo.weak", confidence=.62, evidence=[Evidence("partial resolver match", "app/service.py", 12)]))
    graph.add_edge(Edge("rejected", "ROUTE_HANDLES", "route.rejected", "service.changed", confidence=.2, evidence=[Evidence("discarded candidate", "app/routes.py", 3)], properties={"status": "rejected"}))

    projection = build_review_projection(graph, [{"id": "service.changed", "file": "app/service.py", "line": 10, "changed_lines": [11, 12]}], {"app/service.py"})

    assert {item.entity_id for item in projection.candidates} == {"service.changed", "repo.confirmed"}
    possible = {item.entity_id: item for item in projection.possible_candidates}
    assert set(possible) == {"client.dynamic", "repo.weak"}
    assert possible["client.dynamic"].discovery_reason == "unresolved dynamic call"
    assert projection.risk["confidence"] == "high"
    assert all(item.symbol != "client.dynamic" for item in projection.tests)


def test_targeted_test_recommendation_has_specific_evidence_and_command():
    projection = build_review_projection(
        _graph(), [{"id": "repo.save", "kind": "METHOD", "file": "src/repo.py", "line": 4}], {"src/repo.py"}
    )
    recommendation = next(item for item in projection.tests if item.file == "tests/test_orders.py")
    assert recommendation.category == "direct_changed_symbol"
    assert recommendation.fallback_status == "primary"
    assert recommendation.evidence_ids
    assert recommendation.command == "pytest tests/test_orders.py"


def test_targeted_test_recommendations_deduplicate_alias_nodes_by_executable_file():
    graph = GraphDocument()
    graph.add_node(Node("method:core.merge.merge_profile", "METHOD", "merge_profile", {"file": "core/merge.py"}))
    graph.add_node(Node("call:tests.test_merge.test_merge_profile", "CALL_EXPR", "test_merge_profile", {"file": "tests/test_merge.py", "test_command": "pytest tests/test_merge.py"}))
    graph.add_node(Node("method:tests.test_merge.test_merge_profile", "METHOD", "test_merge_profile", {"file": "tests/test_merge.py", "test_command": "pytest tests/test_merge.py"}))
    graph.add_edge(Edge("call-target", "TESTS", "call:tests.test_merge.test_merge_profile", "method:core.merge.merge_profile", confidence=.9))
    graph.add_edge(Edge("method-target", "TESTS", "method:tests.test_merge.test_merge_profile", "method:core.merge.merge_profile", confidence=.95))

    recommendations = select_targeted_tests(graph, {"method:core.merge.merge_profile"}, set(), {}, {"core/merge.py"})

    assert len(recommendations) == 1
    assert recommendations[0].file == "tests/test_merge.py"


def test_unsupported_coverage_keeps_risk_unknown():
    projection = build_review_projection(
        _graph(), [{"id": "repo.save", "kind": "METHOD", "file": "backend/Orders.cs", "line": 4}], {"backend/Orders.cs"},
        coverage=[{"path": "backend/Orders.cs", "status": "unsupported"}],
    )
    assert projection.risk["level"] == "UNKNOWN"
    assert projection.risk["confidence"] == "low"


def test_chain_ids_are_process_deterministic():
    args = ([{"id": "repo.save", "kind": "METHOD", "file": "src/repo.py", "line": 4}], {"src/repo.py"})
    first = build_review_projection(_graph(), *args)
    second = build_review_projection(_graph(), *args)
    assert [item.id for item in first.chains] == [item.id for item in second.chains]
    assert [item.to_dict() for item in first.chains] == [item.to_dict() for item in second.chains]


def test_traversal_follows_consumers_not_arbitrary_outgoing_neighbours():
    graph = _graph()
    graph.add_node(Node("unrelated.consumer", "METHOD", "unrelated", {"file": "src/unrelated.py", "line": 1}))
    graph.add_edge(Edge("reverse-call", "CALLS", "repo.save", "unrelated.consumer", confidence=.99, evidence=[Evidence("reverse direction", "src/repo.py", 20)]))
    projection = build_review_projection(graph, [{"id": "repo.save", "file": "src/repo.py"}], {"src/repo.py"})
    assert all(item.entity_id != "unrelated.consumer" for item in projection.candidates)


def test_displayed_chain_ids_belong_to_top_k_cards():
    projection = build_review_projection(_graph(), [{"id": "repo.save", "file": "src/repo.py"}], {"src/repo.py"})
    displayed = {chain.id for chain in projection.chains}
    assert displayed
    assert all(chain_id in displayed for candidate in projection.candidates for chain_id in candidate.chain_ids)


def test_route_and_contract_test_paths_get_specific_categories():
    graph = _graph()
    graph.add_node(Node("tests.route", "TEST", "test_route", {"file": "tests/test_api.py", "line": 4}))
    graph.add_edge(Edge("test-route", "TESTS", "tests.route", "route.orders", confidence=.96, evidence=[Evidence("route test", "tests/test_api.py", 4)]))
    graph.add_node(Node("frontend.orders", "FUNCTION", "createOrderRequest", {"file": "web/orders.ts", "line": 8, "boundary_category": "frontend_backend"}))
    graph.add_node(Node("tests.contract", "TEST", "test_contract", {"file": "tests/test_contract.py", "line": 2}))
    graph.add_edge(Edge("test-frontend", "TESTS", "tests.contract", "frontend.orders", confidence=.94, evidence=[Evidence("contract test", "tests/test_contract.py", 2)]))
    graph.add_edge(Edge("http-orders", "HTTP_CALLS", "frontend.orders", "route.orders", confidence=.93, evidence=[Evidence("HTTP contract", "web/orders.ts", 8)], properties={"boundary_category": "frontend_backend"}))
    projection = build_review_projection(graph, [{"id": "repo.save", "file": "src/repo.py"}], {"src/repo.py"})
    categories = {item.file: item.category for item in projection.tests}
    assert categories["tests/test_api.py"] == "route_controller_integration"
    assert categories["tests/test_contract.py"] == "frontend_backend_contract"
    assert all(item.evidence_ids for item in projection.tests)

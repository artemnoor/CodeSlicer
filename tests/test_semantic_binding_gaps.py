from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from semantic_binding import FactSet, Recipe, ResolutionResult, SemanticResolver, semantic_result_to_graph_edges
from semantic_binding.endpoint_matching import match_endpoint
from semantic_binding.path_templates import normalize_endpoint_value
from semantic_binding.recipes import load_recipes, validate_recipes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "semantic_binding"
FIXTURE_FACTS = FIXTURE_ROOT / "generic_semantic_gaps.facts.json"
FIXTURE_RECIPES = FIXTURE_ROOT / "generic_semantic_gaps.recipes.json"


def load_fixture():
    facts = FactSet.from_dict(json.loads(FIXTURE_FACTS.read_text()))
    recipes = load_recipes(FIXTURE_RECIPES)
    assert not facts.validate()
    assert not validate_recipes(recipes)
    return facts, recipes


def resolve_fixture() -> ResolutionResult:
    facts, recipes = load_fixture()
    return SemanticResolver(facts, recipes).resolve()


def edge(result: ResolutionResult, kind: str, source: str | None = None, target: str | None = None):
    matches = [e for e in result.resolved_edges if e.kind == kind]
    if source is not None:
        matches = [e for e in matches if e.source == source]
    if target is not None:
        matches = [e for e in matches if e.target == target]
    assert matches, (kind, source, target, [e.to_dict() for e in result.resolved_edges])
    return matches[0]


def test_nested_object_graph_depth_3_with_evidence():
    result = resolve_fixture()
    route = edge(result, "ROUTE", "getAccountHandler", "/api/admin/accounts/{account_id}")
    assert route.method == "GET"
    assert route.confidence >= 0.9
    assert len(route.evidence) >= 4
    assert {ev.kind for ev in route.evidence} >= {"object_construct", "object_include", "route_decorator"}


def test_object_graph_include_call_prefix_is_propagated_generically():
    facts = FactSet.from_dict(
        {
            "assignments": [
                {"target": "api", "value": "Router", "value_kind": "construct", "kwargs": {"prefix": "/api"}},
                {"target": "admin", "value": "Router", "value_kind": "construct", "kwargs": {"prefix": "/admin"}},
                {"target": "accounts", "value": "Router", "value_kind": "construct"},
            ],
            "calls": [
                {"receiver": "api", "method": "mount", "args": ["admin"]},
                {"receiver": "admin", "method": "mount", "args": ["accounts"], "kwargs": {"prefix": "/accounts"}},
            ],
            "decorators": [
                {"target": "handler", "receiver": "accounts", "method": "get", "args": ["/{id}"]},
            ],
        }
    )
    recipes = [
        Recipe(
            id="generic-object-graph",
            type="object_graph",
            constructor="Router",
            prefix_kwarg="prefix",
            include_method="mount",
            decorator_methods=["get"],
        )
    ]
    result = SemanticResolver(facts, recipes).resolve()
    route = edge(result, "ROUTE", "handler", "/api/admin/accounts/{id}")
    assert route.confidence >= 0.9
    assert [ev.kind for ev in route.evidence].count("object_include") == 2


def test_alias_import_used_in_object_graph():
    result = resolve_fixture()
    binding = next(b for b in result.bindings if b.source == "adminLocal")
    assert binding.target == "app.api.admin.router"
    assert binding.kind == "IMPORT_ALIAS"
    assert binding.confidence >= 0.9
    assert edge(result, "ROUTE", "getAccountHandler", "/api/admin/accounts/{account_id}")


def test_re_export_chain_used_in_object_graph():
    result = resolve_fixture()
    binding = next(b for b in result.bindings if b.source == "accountsReExported")
    assert binding.target == "app.api.accounts.router"
    assert [ev.kind for ev in binding.evidence].count("re_export") == 2
    assert edge(result, "ROUTE", "getAccountHandler", "/api/admin/accounts/{account_id}")


def test_dynamic_template_path_matching():
    result = resolve_fixture()
    http = edge(result, "HTTP_CALLS", "getOrder", "/api/orders/{param}")
    assert http.method == "GET"
    match = edge(result, "MATCHES_ENDPOINT", "getOrder", "getOrderHandler")
    assert match.confidence >= 0.8
    assert match.path == "/api/orders/{order_id}"


def test_concatenated_path_matching():
    result = resolve_fixture()
    http = edge(result, "HTTP_CALLS", "OrderLink", "/api/orders/{param}")
    assert http.method == "GET"
    assert edge(result, "MATCHES_ENDPOINT", "OrderLink", "getOrderHandler")


def test_path_builder_matching():
    assert normalize_endpoint_value('buildUrl("/api/orders", id)', ["buildUrl"]) == "/api/orders/{param}"
    result = resolve_fixture()
    assert edge(result, "MATCHES_ENDPOINT", "OrderBuilder", "getOrderHandler")


def test_wrapper_chain_create_order_post_to_fetch():
    result = resolve_fixture()
    http = edge(result, "HTTP_CALLS", "createOrder", "/api/orders")
    assert http.method == "POST"
    assert any(ev.kind == "wrapper_to_sink" for ev in http.evidence)
    assert edge(result, "MATCHES_ENDPOINT", "createOrder", "createOrderHandler")


def test_returned_object_destructuring_resolves_call():
    result = resolve_fixture()
    binding = next(b for b in result.bindings if b.source == "localCreateOrder")
    assert binding.target == "createOrder"
    assert binding.kind == "DESTRUCTURE_BINDING"
    call = edge(result, "CALLS", "component", "createOrder")
    assert call.evidence


def test_provider_factory_generic_binding_and_dependency_edge():
    result = resolve_fixture()
    provider = next(b for b in result.bindings if b.source == "container.service")
    assert provider.target == "Service"
    assert provider.kind == "PROVIDER_FACTORY"
    handler = next(b for b in result.bindings if b.source == "handler.service")
    assert handler.target == "Service"
    dep = edge(result, "DEPENDS_ON", "Service", "Repository")
    assert dep.evidence[0].kind == "provider_factory"


def test_ambiguous_alias_re_export_produces_diagnostics_not_high_confidence():
    facts = FactSet.from_dict(
        {
            "exports": [
                {"name": "router", "target": "pkg.a.router"},
                {"name": "router", "target": "pkg.b.router"},
            ],
            "imports": [{"module": "pkg.ambiguous", "name": "router", "alias": "localRouter"}],
        }
    )
    result = SemanticResolver(facts, [Recipe(id="alias", type="alias_import")]).resolve()
    binding = next(b for b in result.bindings if b.source == "localRouter")
    assert binding.confidence < 0.8
    assert "AMBIGUOUS" in binding.kind
    assert any("ambiguous" in d for d in result.diagnostics)


def test_serialization_roundtrip_keeps_evidence():
    facts, recipes = load_fixture()
    facts_roundtrip = FactSet.from_dict(facts.to_dict())
    assert facts_roundtrip.to_dict() == facts.to_dict()
    result = SemanticResolver(facts_roundtrip, recipes).resolve()
    result_roundtrip = ResolutionResult.from_dict(result.to_dict())
    assert result_roundtrip.to_dict() == result.to_dict()
    assert all(e.evidence for e in result_roundtrip.resolved_edges)


def test_graph_adapter_emits_route_handles_with_evidence():
    result = resolve_fixture()
    graph_edges = semantic_result_to_graph_edges(result)
    assert graph_edges
    route_edges = [e for e in graph_edges if e["kind"] == "ROUTE_HANDLES"]
    assert route_edges
    assert all(e["evidence"] for e in route_edges)


def test_endpoint_template_match_direct():
    match = match_endpoint("/api/orders/{param}", "/api/orders/{order_id}")
    assert match.confidence >= 0.8


def test_cli_resolve_fixture_and_invalid_recipe_exit_codes(tmp_path: Path):
    out = tmp_path / "result.json"
    ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "semantic_binding.cli",
            "resolve",
            str(FIXTURE_FACTS),
            "--recipes",
            str(FIXTURE_RECIPES),
            "--out",
            str(out),
            "--json",
        ],
        cwd=ROOT,
        timeout=20,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr + ok.stdout
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["resolved_edges"]

    invalid = tmp_path / "invalid.recipes.json"
    invalid.write_text(json.dumps([{"id": "bad", "type": "unknown_rule"}]))
    bad = subprocess.run(
        [sys.executable, "-m", "semantic_binding.cli", "validate-recipes", str(invalid), "--json"],
        cwd=ROOT,
        timeout=20,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2

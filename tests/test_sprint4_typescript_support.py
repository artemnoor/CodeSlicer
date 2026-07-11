from frontend_backend_endpoint_resolver import resolve_frontend_backend_endpoints

from impact_engine.benchmarks.typescript_support import _fixture, run_typescript_support_benchmark


def test_sprint4_benchmark_contract_is_executable():
    result = run_typescript_support_benchmark(".")
    assert result["status"] == "ok"
    assert result["fixtures"] == 12
    assert result["mutations"] == 15
    assert result["cross_language_fixtures"] == 4
    assert result["endpoint_bridge_precision"] >= 0.95


def test_service_identity_prevents_same_path_cross_service_match():
    data = _fixture()
    data["backend_routes"][0]["service"] = "billing-service"
    result = resolve_frontend_backend_endpoints(data)
    assert not any(edge["kind"] == "ROUTES_TO" and edge["status"] in {"confirmed", "likely"} for edge in result["edges"])


def test_export_star_and_namespace_resolution_reach_endpoint():
    result = resolve_frontend_backend_endpoints(_fixture())
    assert any(edge["kind"] == "HTTP_CALLS" and edge["to"] == "orders-service:POST:/api/v1/orders" for edge in result["edges"])
    assert any(edge["kind"] == "ROUTES_TO" and edge["status"] == "confirmed" for edge in result["edges"])


def test_conflicting_wrapper_recipes_are_quarantined():
    data = _fixture()
    data["wrapper_recipes"] = [
        {"wrapper_name": "postJson", "method": "POST", "url_arg_index": 0},
        {"wrapper_name": "postJson", "method": "PUT", "url_arg_index": 0},
    ]
    result = resolve_frontend_backend_endpoints(data)
    assert not any(edge["kind"] == "ROUTES_TO" and edge["status"] in {"confirmed", "likely"} for edge in result["edges"])

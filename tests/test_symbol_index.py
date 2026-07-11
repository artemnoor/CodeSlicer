import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.symbol_index import build_symbol_index

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "package_di_project"


def test_symbol_index_indexing():
    graph = extract_project(FIXTURE_PATH)
    index = build_symbol_index(graph)
    
    # 1. Assert modules
    assert "app.container" in index.modules
    assert "app.services.order_service" in index.modules
    assert "app.repositories.order_repository" in index.modules
    
    # 2. Assert imports
    imports = index.imports_by_module.get("app.container", set())
    assert "app.repositories.order_repository" in imports
    assert "app.services.order_service" in imports
    
    # 3. Assert resolve_class_name
    resolved_repo = index.resolve_class_name("OrderRepository", "app.container")
    assert resolved_repo == "app.repositories.order_repository.OrderRepository"
    
    resolved_service = index.resolve_class_name("OrderService", "app.container")
    assert resolved_service == "app.services.order_service.OrderService"

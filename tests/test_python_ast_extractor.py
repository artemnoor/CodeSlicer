import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.models import GraphDocument

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_extract_project_returns_graph_document():
    doc = extract_project(PROJECT_PATH)
    assert isinstance(doc, GraphDocument)
    assert doc.metadata.get("extractor") == "python_ast"
    assert doc.metadata.get("status") == "extracted"


def test_python_di_basic_extracts_classes_and_methods():
    doc = extract_project(PROJECT_PATH)
    
    # Required class node IDs
    expected_class_ids = {
        "class:container.Container",
        "class:services.OrderService",
        "class:repositories.OrderRepository",
    }
    
    # Required method node IDs
    expected_method_ids = {
        "method:container.Container.__init__",
        "method:services.OrderService.__init__",
        "method:services.OrderService.create_order",
        "method:repositories.OrderRepository.save",
    }
    
    node_ids = {n.id for n in doc.nodes}
    
    for class_id in expected_class_ids:
        assert class_id in node_ids, f"Missing class ID: {class_id}"
        node = next(n for n in doc.nodes if n.id == class_id)
        assert node.kind == "CLASS"
        
    for method_id in expected_method_ids:
        assert method_id in node_ids, f"Missing method ID: {method_id}"
        node = next(n for n in doc.nodes if n.id == method_id)
        assert node.kind == "METHOD"


def test_python_di_basic_extracts_required_assignments():
    doc = extract_project(PROJECT_PATH)
    
    # We want to find assignment nodes that match the expected properties
    nodes = doc.nodes
    
    # 1. self.order_repository = OrderRepository()
    assign_repo = next(
        (n for n in nodes if n.kind == "ASSIGNMENT" and n.properties.get("target") == "self.order_repository"),
        None
    )
    assert assign_repo is not None, "Missing self.order_repository assignment"
    assert assign_repo.properties.get("value") == "OrderRepository()"
    assert assign_repo.properties.get("scope") == "container.Container.__init__"
    assert assign_repo.properties.get("target_kind") == "self_attribute"
    assert assign_repo.properties.get("call_name") == "OrderRepository"

    # 2. self.order_service = OrderService(repository=self.order_repository)
    assign_service = next(
        (n for n in nodes if n.kind == "ASSIGNMENT" and n.properties.get("target") == "self.order_service"),
        None
    )
    assert assign_service is not None, "Missing self.order_service assignment"
    assert assign_service.properties.get("value") == "OrderService(repository=self.order_repository)"
    assert assign_service.properties.get("scope") == "container.Container.__init__"
    assert assign_service.properties.get("target_kind") == "self_attribute"
    assert assign_service.properties.get("call_name") == "OrderService"
    assert assign_service.properties.get("keyword_args") == {"repository": "self.order_repository"}

    # 3. self.repository = repository
    assign_self_repo = next(
        (n for n in nodes if n.kind == "ASSIGNMENT" and n.properties.get("target") == "self.repository"),
        None
    )
    assert assign_self_repo is not None, "Missing self.repository assignment"
    assert assign_self_repo.properties.get("value") == "repository"
    assert assign_self_repo.properties.get("scope") == "services.OrderService.__init__"
    assert assign_self_repo.properties.get("target_kind") == "self_attribute"


def test_python_di_basic_preserves_method_call_receiver():
    doc = extract_project(PROJECT_PATH)
    
    # We want to find a CALL_EXPR node with scope services.OrderService.create_order
    call_node = next(
        (n for n in doc.nodes if n.kind == "CALL_EXPR" and n.properties.get("scope") == "services.OrderService.create_order"),
        None
    )
    assert call_node is not None, "Missing CALL_EXPR in services.OrderService.create_order"
    assert call_node.properties.get("receiver") == "self.repository"
    assert call_node.properties.get("method_name") == "save"
    assert call_node.properties.get("call_name") == "self.repository.save"
    assert call_node.properties.get("args") == ["order"]
    assert call_node.properties.get("keyword_args") == {}


def test_extractor_does_not_create_inferred_mvp_edge():
    doc = extract_project(PROJECT_PATH)
    
    # Assert no edge has kind CALLS, source INFERRED, from services.OrderService.create_order, to repositories.OrderRepository.save
    for edge in doc.edges:
        if edge.kind == "CALLS" and edge.source == "INFERRED":
            assert not (
                edge.from_node == "services.OrderService.create_order"
                and edge.to_node == "repositories.OrderRepository.save"
            ), "Extractor should not produce the INFERRED CALLS edge"

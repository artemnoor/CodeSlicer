"""End-to-end evidence gates for every first-class non-Python language."""
from pathlib import Path
import shutil

import pytest

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("language", "fixture", "source", "target", "provider"),
    [
        ("typescript", "next_react_fastapi_fullstack", "useOrders", "createOrder", "typescript_local_import_resolver"),
        ("go", "go_basic_project", "main.Service.Process", "main.Service.Save", "polyglot_typed_semantics"),
        ("java", "java_basic_project", "com.example.OrderService.createOrder", "com.example.OrderService.save", "polyglot_typed_semantics"),
        ("csharp", "csharp_dotnet", "method:Sample.Application.OrderHandler.Handle", "method:Sample.Application.OrderService.Handle", None),
    ],
)
def test_deep_language_e2e_has_evidence_backed_call_path(tmp_path, language, fixture, source, target, provider):
    project = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, project, ignore=shutil.ignore_patterns(".impact_engine", "__pycache__"))
    graph = GraphDocument.from_dict(analyze_project_core(str(project), create_research_requests=False)["graph"])
    matching = [
        edge for edge in graph.edges
        if edge.kind in {"CALLS", "TESTS"}
        and edge.from_node == source and edge.to_node == target
        and edge.properties.get("resolution_status") == "resolved_exact"
    ]
    if provider:
        matching = [edge for edge in matching if edge.properties.get("provider") == provider]
    assert matching, f"{language} must retain an explicit, evidence-backed call path; found {[(edge.from_node, edge.to_node, edge.properties.get('resolution_status')) for edge in graph.edges if edge.kind in {'CALLS', 'TESTS'}]}"
    assert matching[0].evidence


def test_go_gin_literal_route_is_connected_to_its_handler(tmp_path):
    project = tmp_path / "go-gin"
    shutil.copytree(FIXTURES / "go_gin_project", project)
    graph = GraphDocument.from_dict(analyze_project_core(str(project), create_research_requests=False)["graph"])
    assert any(
        edge.kind == "ROUTE_HANDLES"
        and edge.from_node == "HTTP POST /orders"
        and edge.to_node == "main.CreateOrder"
        and edge.properties.get("resolution_status") == "resolved_exact"
        for edge in graph.edges
    )


def test_java_spring_literal_route_is_connected_to_its_handler(tmp_path):
    source = FIXTURES / "qa_matrix" / "polyglot_microservices" / "services" / "notifications-java"
    project = tmp_path / "notifications-java"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".impact_engine", "__pycache__"))
    graph = GraphDocument.from_dict(analyze_project_core(str(project), create_research_requests=False)["graph"])
    assert any(
        edge.kind == "ROUTE_HANDLES"
        and edge.from_node == "HTTP POST /send"
        and edge.to_node == "com.example.notifications.NotificationController.sendNotification"
        for edge in graph.edges
    )

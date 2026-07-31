import json
import subprocess
import sys
from pathlib import Path

import pytest

from impact_engine.models import GraphDocument, Node
from impact_engine.pr_review import ChangedFile, _changed_symbols, _is_test_file, _same_area, parse_git_diff, pr_review_core, recommend_tests


def _write_project(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "repositories.py").write_text(
        """
class OrderRepository:
    def save(self, order):
        return order
""",
        encoding="utf-8",
    )
    (root / "app" / "services.py").write_text(
        """
from app.repositories import OrderRepository


class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, order):
        return self.repository.save(order)
""",
        encoding="utf-8",
    )
    (root / "app" / "main.py").write_text(
        """
from fastapi import FastAPI
from app.services import OrderService
from app.repositories import OrderRepository

app = FastAPI()
service = OrderService(repository=OrderRepository())


@app.post("/orders")
def create_order_endpoint(order: dict):
    return service.create_order(order)
""",
        encoding="utf-8",
    )
    (root / "tests" / "test_orders.py").write_text(
        """
from fastapi.testclient import TestClient
from app.main import app


def test_create_order():
    client = TestClient(app)
    assert client.post("/orders", json={"id": 1}).status_code == 200
""",
        encoding="utf-8",
    )


def test_parse_git_diff_extracts_changed_lines():
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -2,0 +3,2 @@ class OrderRepository:
+        # changed
+        return order
"""
    files = parse_git_diff(diff)

    assert files[0].path == "app/repositories.py"
    assert files[0].lines == {3, 4}


@pytest.mark.parametrize(("test_file", "changed_file"), [
    ("tests/test_merge.py", "core/merge.py"),
    ("auth_test.go", "auth.go"),
    ("src/application.test.ts", "src/application.ts"),
    ("test/createStore.spec.ts", "src/createStore.ts"),
    ("OrderServiceTest.java", "OrderService.java"),
    ("OwnerControllerTests.java", "OwnerController.java"),
])
def test_test_file_pairing_is_language_neutral(test_file: str, changed_file: str):
    assert _same_area(test_file, changed_file)


def test_test_area_does_not_match_only_on_shared_java_root():
    assert not _same_area(
        "src/test/java/org/springframework/samples/petclinic/vet/VetControllerTests.java",
        "src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java",
    )
    assert _same_area(
        "src/test/java/org/springframework/samples/petclinic/owner/OwnerControllerTests.java",
        "src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java",
    )


def test_test_file_recognition_does_not_match_source_names_with_test_substring():
    assert _is_test_file("test/createStore.spec.ts")
    assert _is_test_file("auth_test.go")
    assert _is_test_file("src/test/java/example/OwnerControllerTests.java")
    assert not _is_test_file("src/createStore.ts")
    assert not _is_test_file("src/latest/processor.ts")


def test_recommend_tests_surfaces_test_callables_reached_by_a_resolved_impact_path():
    graph = GraphDocument(nodes=[
        Node(
            "method:tests.test_service.test_persist",
            "METHOD",
            "test_persist",
            properties={"file": "tests/test_service.py"},
        ),
        Node(
            "call:tests.test_service.test_persist:8:service.persist",
            "CALL_EXPR",
            "service.persist",
            properties={"file": "tests/test_service.py"},
        ),
    ])
    affected_nodes = [node.to_dict() for node in graph.nodes]

    result = recommend_tests(graph, affected_nodes, [], {"app/service.py"})

    assert result["required"] == []
    assert result["recommended"] == [{
        "node": "method:tests.test_service.test_persist",
        "file": "tests/test_service.py",
        "reason": "resolved call-graph path reaches the changed symbol",
    }]


def test_pr_review_core_reports_risk_and_tests(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    result = pr_review_core(str(tmp_path), diff_text=diff)

    assert result["status"] == "ok"
    assert result["changed_symbols"]
    assert result["risk"]["level"] in {"MEDIUM", "HIGH", "CRITICAL"}
    assert any("OrderRepository.save" in item["id"] for item in result["changed_symbols"])
    required = result["suggested_tests"]["required"]
    assert any("test_orders.py" in str(item.get("file")) for item in required)


def test_pr_review_exposes_compact_actionable_projection(tmp_path: Path):
    """The default review must not turn AST containment into user impact."""
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    result = pr_review_core(str(tmp_path), diff_text=diff, include_technical=True)
    projection = result["review_projection"]

    assert projection["coverage"]["structural_edges_hidden"] > 0
    assert projection["coverage"]["raw_nodes"] > result["summary"]["affected_nodes"]
    assert all(item["kind"] not in {"CALL_EXPR", "ASSIGNMENT"} for item in projection["impacted_symbols"])
    assert all(item["kind"] not in {"FILE", "MODULE"} for item in projection["impacted_symbols"])
    assert all(item["kind"] not in {"CONTAINS", "DECLARES", "FIELD_BINDS_TO", "INSTANCE_OF"} for item in projection["relationships"])
    assert result["summary"]["technical_affected_nodes"] == projection["coverage"]["raw_nodes"]
    assert result["technical_impact_sections"]["confirmed"]


def test_changed_symbol_mapping_does_not_select_an_earlier_function_from_a_stale_graph():
    graph = GraphDocument(nodes=[
        Node("method:delete", "METHOD", "delete", properties={"file": "app/routes.py", "line": 10, "end_line": 20}),
        Node("method:create", "METHOD", "create", properties={"file": "app/routes.py", "line": 30, "end_line": 45}),
    ])

    symbols = _changed_symbols(graph, [ChangedFile("app/routes.py", {36})])

    assert [item["id"] for item in symbols] == ["method:create"]


def test_pr_review_cli_json(tmp_path: Path):
    _write_project(tmp_path)
    diff_file = tmp_path / "change.diff"
    diff_file.write_text(
        """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
""",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "impact_engine.cli", "--json", "pr-review", str(tmp_path), "--diff-file", str(diff_file)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["changed_symbols"] >= 1


def test_pr_review_mcp_tool_wrapper(tmp_path: Path):
    _write_project(tmp_path)
    diff_text = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    from impact_engine.mcp.server import TOOLS, pr_review

    assert any(tool["name"] == "pr_review" for tool in TOOLS)
    result = pr_review(str(tmp_path), diff_text=diff_text)

    assert result["status"] == "ok"
    assert result["tool"] == "pr_review"
    assert result["result"]["risk"]["level"] in {"MEDIUM", "HIGH", "CRITICAL"}

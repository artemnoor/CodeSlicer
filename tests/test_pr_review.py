import json
import os
import subprocess
import sys
from pathlib import Path

from impact_engine.pr_review import ChangedFile, _changed_symbols, parse_git_diff, pr_review_core
from impact_engine.models import GraphDocument, Node


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
    assert files[0].additions == 2
    assert files[0].deletions == 0


def test_changed_hunk_selects_nearest_callable_not_neighbouring_init():
    graph = GraphDocument()
    graph.add_node(Node("service.__init__", "METHOD", "__init__", {"file": "app/service.py", "line": 2}))
    graph.add_node(Node("service.place_order", "METHOD", "place_order", {"file": "app/service.py", "line": 10}))
    changed = ChangedFile("app/service.py", {12, 13})
    symbols = _changed_symbols(graph, [changed])
    assert [item["id"] for item in symbols] == ["service.place_order"]
    assert symbols[0]["changed_lines"] == [12, 13]


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


def test_pr_review_default_is_bounded_and_hides_full_closure(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    result = pr_review_core(str(tmp_path), diff_text=diff, max_results=99)

    assert result["schema_version"] == "PRReview/v2"
    assert len(result["top_impacts"]) <= 10
    assert len(result["test_recommendations"]) <= 10
    assert len(result["chains"]) <= 3
    assert result["summary"]["top_impacts"] <= 10
    assert result["full_evidence"]["status"] == "not_requested"
    assert "impact_results" not in result
    assert "impact_sections" not in result


def test_pr_review_exposes_the_same_comment_only_semantic_conclusion(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3,0 +4 @@ class OrderRepository:
+        # Documents the storage choice.
"""

    result = pr_review_core(str(tmp_path), diff_text=diff)

    assert result["semantic_diff"]["has_runtime_change"] is False
    assert result["changed_symbols"] == []
    assert result["test_recommendations"] == []


def test_pr_review_excludes_tracked_codeslicer_artifacts(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
diff --git a/.impact_engine/graph.json b/.impact_engine/graph.json
--- a/.impact_engine/graph.json
+++ b/.impact_engine/graph.json
@@ -1 +1 @@
-old
+new
"""

    result = pr_review_core(str(tmp_path), diff_text=diff)

    assert [item["path"] for item in result["changed_files"]] == ["app/repositories.py"]
    assert any("generated CodeSlicer artifact changes excluded" in warning for warning in result["warnings"])


def test_pr_review_full_closure_requires_explicit_opt_in(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    result = pr_review_core(str(tmp_path), diff_text=diff, include_full_evidence=True)

    assert result["full_evidence"]["status"] == "included_on_explicit_request"
    assert "impact_results" in result["full_evidence"]
    assert "impact_sections" in result["full_evidence"]
    assert "impact_results" not in result


def test_pr_review_potential_scope_is_independent_from_full_evidence(tmp_path: Path):
    _write_project(tmp_path)
    diff = """diff --git a/app/repositories.py b/app/repositories.py
--- a/app/repositories.py
+++ b/app/repositories.py
@@ -3 +3 @@ class OrderRepository:
-        return order
+        return {**order, "changed": True}
"""

    closure = pr_review_core(str(tmp_path), diff_text=diff, include_full_evidence=True)
    broad = pr_review_core(str(tmp_path), diff_text=diff, include_potential=True)

    assert closure["full_evidence"]["status"] == "included_on_explicit_request"
    assert closure["potential_impact"]["status"] == "available_on_explicit_request"
    assert closure["potential_impacts"] == []
    assert broad["full_evidence"]["status"] == "not_requested"
    assert broad["potential_impact"]["status"] == "included_on_explicit_request"


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

    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "impact_engine.cli", "--json", "pr-review", str(tmp_path), "--diff-file", str(diff_file), "--show-potential"],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["changed_symbols"] >= 1
    assert payload["full_evidence"]["status"] == "not_requested"
    assert payload["potential_impact"]["status"] == "included_on_explicit_request"
    assert len(payload["top_impacts"]) <= 10


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

import json
import subprocess
import sys
from pathlib import Path

from impact_engine.pr_review import parse_git_diff, pr_review_core


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

from pathlib import Path

from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.review import build_review_report


def test_v2_report_exposes_human_summary_source_and_safe_test_plan(tmp_path: Path):
    graph = GraphDocument(metadata={"language_semantic_capabilities": {"python": {"capabilities": {"production_semantic_baseline": True, "call_resolution": "semantic"}}}})
    graph.add_node(Node("app.changed", "METHOD", "changed", {"file": "app.py", "line": 1}))
    graph.add_node(Node("tests.changed", "TEST", "test_changed", {"file": "tests/test_app.py", "test_command": "pytest tests/test_app.py"}))
    graph.add_edge(Edge("test-edge", "TESTS", "tests.changed", "app.changed", evidence=[Evidence("covers changed method", "tests/test_app.py", 2)]))
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["schema_version"] == "ReviewReport/v2"
    assert report["summary"]["changed_file_count"] == 1
    assert report["source"]["kind"] == "diff_file"
    assert report["areas"]
    assert report["impact_groups"]
    plan = report["test_plan"][0]
    assert plan["argv"] == ["pytest", "tests/test_app.py"]
    assert plan["safety"] == "confirmation_required"
    assert plan["cwd"] == str(tmp_path.resolve())


def test_v2_never_turns_shell_syntax_into_test_argv(tmp_path: Path):
    graph = GraphDocument(metadata={"language_semantic_capabilities": {"python": {"capabilities": {"production_semantic_baseline": True, "call_resolution": "semantic"}}}})
    graph.add_node(Node("app.changed", "METHOD", "changed", {"file": "app.py", "line": 1}))
    graph.add_node(Node("tests.changed", "TEST", "test_changed", {"file": "tests/test_app.py", "test_command": "pytest tests/test_app.py && echo unsafe"}))
    graph.add_edge(Edge("test-edge", "TESTS", "tests.changed", "app.changed"))
    diff = "diff --git a/app.py b/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["test_plan"][0]["argv"] is None
    assert report["test_plan"][0]["safety"] == "not_runnable_without_manual_command"

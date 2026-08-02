from __future__ import annotations

from impact_engine.analysis.pipeline import analyze_project_core, analyze_project_progressively
from impact_engine.analysis.focused_scope import build_discovery_scope


def _node_ids(graph: dict) -> set[str]:
    return {str(item["id"]) for item in graph["nodes"]}


def test_focused_scope_is_noncanonical_and_keeps_exact_local_cross_file_call(tmp_path):
    (tmp_path / "provider.py").write_text(
        "def target() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "from provider import target\n\ndef caller() -> str:\n    return target()\n",
        encoding="utf-8",
    )
    (tmp_path / "unrelated.py").write_text(
        "def unrelated() -> None:\n    pass\n",
        encoding="utf-8",
    )

    result = analyze_project_core(
        str(tmp_path),
        focus_files=["consumer.py", "provider.py"],
        create_research_requests=False,
    )

    graph = result["graph"]
    scope = graph["metadata"]["analysis_scope"]
    assert scope["mode"] == "focused_discovery_scope"
    assert scope["complete"] is False
    assert scope["files"] == ["consumer.py", "provider.py"]
    assert graph["metadata"]["post_project_hygiene_status"] == "deferred_by_focused_scope"

    ids = _node_ids(graph)
    assert "method:consumer.caller" in ids
    assert "method:provider.target" in ids
    assert not any("unrelated" in node_id for node_id in ids)
    assert any(
        edge["kind"] == "CALLS"
        and edge["from"] == "method:consumer.caller"
        and edge["to"] == "method:provider.target"
        and edge["confidence"] == 1.0
        for edge in graph["edges"]
    )


def test_focused_scope_never_claims_canonical_cache_ownership(tmp_path):
    (tmp_path / "module.py").write_text("def value():\n    return 1\n", encoding="utf-8")

    full = analyze_project_core(str(tmp_path), create_research_requests=False)
    focused = analyze_project_core(
        str(tmp_path),
        focus_files=["module.py"],
        create_research_requests=False,
    )

    assert full["graph"]["metadata"].get("analysis_scope") is None
    assert focused["graph"]["metadata"]["analysis_scope"]["complete"] is False
    assert focused["graph"]["metadata"].get("cache_validation", {}).get("status") != "reused_complete_cache"


def test_lexical_discovery_scope_finds_local_importers_and_marks_its_limits(tmp_path):
    (tmp_path / "provider.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("from provider import target\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("def noop():\n    return 0\n", encoding="utf-8")

    scope = build_discovery_scope(tmp_path, ["provider.py"])

    assert scope["mode"] == "lexical_broad_discovery"
    assert scope["files"] == ["consumer.py", "provider.py"]
    assert scope["complete"] is True
    assert scope["static_local_links"] == 1
    assert "candidate files require focused semantic analysis" in scope["limitations"][1]


def test_lexical_discovery_scope_reports_a_truncated_broad_scope(tmp_path):
    (tmp_path / "root.py").write_text("from first import value\n", encoding="utf-8")
    (tmp_path / "first.py").write_text("from second import value\n", encoding="utf-8")
    (tmp_path / "second.py").write_text("value = 1\n", encoding="utf-8")

    scope = build_discovery_scope(tmp_path, ["root.py"], max_files=2)

    assert scope["complete"] is False
    assert scope["file_count"] == 2


def test_lexical_discovery_scope_finds_relative_typescript_importers(tmp_path):
    (tmp_path / "service.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "client.ts").write_text("import { value } from './service';\n", encoding="utf-8")

    scope = build_discovery_scope(tmp_path, ["service.ts"])

    assert scope["files"] == ["client.ts", "service.ts"]


def test_progressive_analysis_returns_a_noncanonical_preliminary_result(tmp_path):
    (tmp_path / "provider.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("from provider import target\n", encoding="utf-8")

    result = analyze_project_progressively(str(tmp_path), ["provider.py"])

    assert result["status"] == "ok"
    assert result["progressive_analysis"] == {
        "status": "scoped_preliminary_analysis",
        "canonical": False,
        "merge_decision_eligible": False,
        "next_action": "run canonical analysis for a complete PR decision",
        "discovery_complete": False,
        "scope_truncated": True,
    }
    assert result["discovery_scope"]["files"] == ["consumer.py", "provider.py"]
    assert result["graph"]["metadata"]["progressive_analysis"]["canonical"] is False

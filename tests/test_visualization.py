import json
import subprocess
import sys
from pathlib import Path

from impact_engine.visualization import render_graph_comparison_html, render_graph_html


def test_render_graph_html_is_self_contained(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [{"id": "A", "name": "OrderService", "kind": "CLASS"}],
        "edges": [],
    }), encoding="utf-8")
    output = render_graph_html(graph)
    content = output.read_text(encoding="utf-8")
    assert output.exists()
    assert "OrderService" in content
    assert "Minimum confidence" in content
    assert "cdn.jsdelivr.net/npm/d3@7" in content


def test_render_graphify_links_without_changing_core_graph(tmp_path):
    graph = tmp_path / "graphify.json"
    graph.write_text(json.dumps({
        "nodes": [{"id": "a", "label": "A", "file_type": "code"}, {"id": "b", "label": "B", "file_type": "code"}],
        "links": [{"source": "a", "target": "b", "relation": "imports_from", "confidence": "EXTRACTED"}],
    }), encoding="utf-8")
    output = render_graph_html(graph)
    content = output.read_text(encoding="utf-8")
    assert '"from_node": "a"' in content
    assert '"to_node": "b"' in content
    assert "graphify_visualization_only" in content


def test_render_comparison_contains_both_switchable_views(tmp_path):
    impact = tmp_path / "impact.json"
    graphify = tmp_path / "graphify.json"
    impact.write_text(json.dumps({"nodes": [{"id": "i", "name": "Impact", "kind": "CLASS"}], "edges": []}), encoding="utf-8")
    graphify.write_text(json.dumps({"nodes": [{"id": "g", "label": "Graphify", "file_type": "code"}], "links": []}), encoding="utf-8")
    output = render_graph_comparison_html(impact, graphify, tmp_path / "compare.html")
    content = output.read_text(encoding="utf-8")
    assert "Impact Engine" in content
    assert "Graphify" in content
    assert '"impact"' in content and '"graphify"' in content


def test_visualize_cli(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "impact_engine.cli", "--json", "visualize", str(graph)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent, timeout=30,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "ok"

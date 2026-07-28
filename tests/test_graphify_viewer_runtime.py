from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

from impact_engine.adapters.graphify_paths import _self_contained_viewer, _vis_network_bundle, cache_graphify_viewer, graphify_graph_path, graphify_viewer_cache_path


UPSTREAM_HTML = '''<!doctype html><html><head>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"
 integrity="sha384-example" crossorigin="anonymous"></script>
</head><body><div id="graph"></div><script>new vis.Network(document.getElementById("graph"), {}, {});</script></body></html>'''


def test_pinned_vis_network_bundle_is_present_and_makes_upstream_html_offline() -> None:
    bundle = _vis_network_bundle()
    assert bundle is not None
    assert hashlib.sha256(bundle.encode("utf-8")).hexdigest() == "576bb887733eb01bb52ee75b90ef46d818454de5fddb5b616fb8a298d307ca12"
    rendered = _self_contained_viewer(UPSTREAM_HTML)
    assert rendered is not None
    assert "unpkg.com" not in rendered
    assert "vis-network@9.1.6-local" in rendered
    assert "new vis.Network" in rendered


def test_graphify_viewer_embeds_pinned_runtime_before_cache_publish(tmp_path: Path, monkeypatch) -> None:
    graph = graphify_graph_path(tmp_path)
    graph.parent.mkdir(parents=True)
    graph.write_text(json.dumps({
        "nodes": [{"id": "a"}, "not-a-node", {"id": "b"}],
        "edges": [{"from": "a", "to": "b"}, "not-an-edge"],
    }), encoding="utf-8")
    (graph.parent / ".graphify_python").write_text(str(Path(__file__).resolve()), encoding="utf-8")
    monkeypatch.setattr("impact_engine.adapters.graphify_paths._vis_network_bundle", lambda: "window.vis = window.vis || { DataSet: function(){}, Network: function(){} };")

    def fake_run(command, **_kwargs):
        bounded = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
        assert len(bounded["nodes"]) == 2
        assert len(bounded["edges"]) == 1
        Path(command[-1]).write_text(UPSTREAM_HTML, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("impact_engine.adapters.graphify_paths.subprocess.run", fake_run)
    cache = cache_graphify_viewer(tmp_path)
    assert cache == graphify_viewer_cache_path(tmp_path)
    html = cache.read_text(encoding="utf-8")
    assert "vis-network@9.1.6-local" in html
    assert "unpkg.com/vis-network" not in html
    assert "window.vis" in html
    assert html.rstrip().endswith("</html>")


def test_graphify_viewer_refuses_unbounded_or_incomplete_renderer_output(tmp_path: Path, monkeypatch) -> None:
    graph = graphify_graph_path(tmp_path)
    graph.parent.mkdir(parents=True)
    graph.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    (graph.parent / ".graphify_python").write_text(str(Path(__file__).resolve()), encoding="utf-8")
    monkeypatch.setattr("impact_engine.adapters.graphify_paths._vis_network_bundle", lambda: "window.vis = {};")
    def incomplete_run(command, **_kwargs):
        Path(command[-1]).write_text("<html><script src='https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js'></script>", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("impact_engine.adapters.graphify_paths.subprocess.run", incomplete_run)
    assert cache_graphify_viewer(tmp_path) is None

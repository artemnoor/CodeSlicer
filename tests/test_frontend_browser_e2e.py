from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from impact_engine.adapters.graphify_paths import _self_contained_viewer, graphify_graph_path, graphify_viewer_cache_path


def _browser_runtime():
    """Return Playwright, failing instead of skipping in the browser CI job."""
    try:
        from playwright import sync_api
    except ImportError as exc:
        if os.environ.get("IMPACT_ENGINE_REQUIRE_BROWSER_E2E") == "1":
            pytest.fail(f"Playwright must be installed for this CI job: {exc}")
        pytest.skip("Playwright is an optional browser-test dependency")
    return sync_api


def _launch_chromium(runtime):
    try:
        return runtime.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover - machine-specific browser install
        if os.environ.get("IMPACT_ENGINE_REQUIRE_BROWSER_E2E") == "1":
            pytest.fail(f"Chromium must be installed for this CI job: {exc}")
        pytest.skip(f"Chromium is unavailable: {exc}")


def _server(root: Path, project: Path):
    from impact_engine.local_api import LocalApiState, create_server

    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(root / "frontend"), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_browser_shows_a_single_project_map_and_optional_graphify():
    playwright = _browser_runtime()
    root = Path(__file__).parents[1]
    project = root / "tests" / "corpus" / "JunMate"
    server, thread = _server(root, project)
    try:
        with playwright.sync_playwright() as runtime:
            browser = _launch_chromium(runtime)
            page = browser.new_page(viewport={"width": 1280, "height": 800})

            canonical = {
                "status": "ready", "workspace": {"id": "impact", "title": "Карта CodeSlicer"},
                "nodes": [
                    {"id": "service", "name": "service", "kind": "FUNCTION", "canonical": True, "source": "CodeSlicer", "properties": {"file": "src/app.py"}},
                    {"id": "repository", "name": "repository", "kind": "MODULE", "canonical": True, "source": "CodeSlicer", "properties": {"file": "src/repository.py"}},
                ],
                "edges": [{"id": "calls", "from": "service", "to": "repository", "kind": "CALLS", "canonical": True, "source": "CodeSlicer"}],
                "total_nodes": 2, "total_edges": 1, "truncated": False,
            }
            graphify = {
                "status": "ready", "workspace": {"id": "architecture", "title": "Карта Graphify"},
                "nodes": [{"id": "community-auth", "name": "auth community", "kind": "COMMUNITY", "canonical": False, "source": "Graphify", "properties": {}}],
                "edges": [], "total_nodes": 1, "total_edges": 0, "truncated": False,
            }
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            def route_handler(route):
                path = route.request.url.split("/api/")[-1].split("?")[0]
                if path == "adapters/graphify/viewer":
                    route.fulfill(
                        content_type="text/html",
                        body="<!doctype html><html><body><canvas id='graphify-canvas'></canvas><script>window.graphifyViewer=true;</script></body></html>",
                    )
                    return
                if path == "health":
                    payload = {"status": "ok", "capabilities": {"managed_tools": True}}
                elif path == "state":
                    payload = {"project_path": str(project), "project_exists": True, "has_analysis": True, "analysis": {"graph_path": "graph.json"}}
                elif path == "graph":
                    payload = {"graph": {"nodes": canonical["nodes"], "edges": canonical["edges"]}}
                elif path == "graph/projection":
                    payload = canonical
                elif path == "graph-workspace":
                    payload = graphify
                elif path == "review":
                    payload = {"report": {"risk": {"level": "LOW", "confidence": "high", "reason": "fixture"}, "changed_files": [{"path": "src/app.py", "additions": 1, "deletions": 0}], "top_impacts": [{"entity_id": "service", "label": "service", "kind": "FUNCTION", "file": "src/app.py", "confidence": "high", "why_affected": "direct call"}], "test_recommendations": [{"file": "tests/test_app.py", "symbol": "test_service", "command": "pytest tests/test_app.py"}]}}
                elif path == "inspect":
                    payload = {"report": {"resolved_entity": {"id": "service", "name": "service", "kind": "FUNCTION", "properties": {"file": "src/app.py"}}, "confidence": {"level": "high", "value": 1.0}, "direct_upstream": [], "direct_downstream": []}}
                elif path == "investigate":
                    payload = {"report": {"resolved_entity": {"id": "service", "name": "service"}, "nodes": [{"id": "repository", "name": "repository"}], "edges": [{"from": "service", "to": "repository", "kind": "CALLS"}]}}
                elif path == "adapters":
                    payload = {"adapters": [{"id": "graphify", "status": "imported", "enabled": True, "freshness": {"status": "fresh"}}]}
                elif path == "tools":
                    payload = {"tools": [{"id": "graphify", "connected": True, "repository": {"cloned": True}}]}
                elif path == "adapters/graphify/viewer/status":
                    payload = {"status": "ready", "available": True, "graph_available": True, "viewer_available": True, "viewer_stale": False}
                else:
                    payload = {"status": "ok"}
                route.fulfill(content_type="application/json", body=json.dumps(payload))

            page.route("**/api/**", route_handler)
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")

            # Review is the daily entry point; the project map remains an
            # explicit investigation surface rather than the landing page.
            assert page.url.endswith("#review")
            assert page.locator(".simple-nav a").count() == 4
            assert page.get_by_text("Проверка изменений", exact=True).count() == 1
            assert page.get_by_role("link", name="Локальные источники").count() == 1
            # Review actions must be useful controls, not dead links.
            page.get_by_role("button", name="Запустить выбранные тесты").click()
            assert page.locator("#modalBackdrop").is_visible(), page.locator("body").inner_text()
            assert page.locator("#modalTitle").inner_text() == "Подтвердить запуск теста"
            # Continue the map flow without depending on browser-specific
            # overlay animation/pointer timing.
            page.evaluate("document.getElementById('modalBackdrop').hidden = true")
            page.get_by_role("link", name="Карта проекта").click()
            page.locator(".projection-svg").wait_for()
            page.locator(".network-node").first.click()
            page.locator("#mapInspector").get_by_text("service", exact=True).wait_for()
            assert "src/app.py" in page.locator("#mapInspector").inner_text()

            page.select_option("#graphViewSelect", "graphify")
            page.locator(".graphify-native-frame").wait_for()
            assert page.url.endswith("#graphify")
            assert page.get_by_text("Карта, отрисованная самим Graphify", exact=True).count() == 1
            # Graphify keeps its own upstream interaction model; it is not
            # re-rendered as CodeSlicer's projection SVG.
            assert page.locator("#view-graphify .projection-svg").count() == 0

            page.get_by_role("link", name="Graphify").click()
            page.locator(".graphify-native-frame").wait_for()
            page.frame_locator(".graphify-native-frame").locator("#graphify-canvas").wait_for()
            assert "не меняет рекомендации CodeSlicer" in page.locator("#graphifyContent").inner_text()
            assert not page_errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_never_embeds_a_stale_graphify_viewer(tmp_path: Path):
    playwright = _browser_runtime()
    root = Path(__file__).parents[1]
    project = tmp_path / "project"; project.mkdir()
    server, thread = _server(root, project)
    try:
        with playwright.sync_playwright() as runtime:
            browser = _launch_chromium(runtime)
            page = browser.new_page()

            def route_handler(route):
                path = route.request.url.split("/api/")[-1].split("?")[0]
                if path == "health": payload = {"status": "ok", "capabilities": {"managed_tools": True}}
                elif path == "state": payload = {"project_path": str(project), "project_exists": True, "has_analysis": True, "analysis": {"graph_path": "graph.json"}}
                elif path == "adapters": payload = {"adapters": [{"id": "graphify", "status": "ready", "enabled": True}]}
                elif path == "tools": payload = {"tools": [{"id": "graphify", "connected": True}]}
                elif path == "adapters/graphify/viewer/status": payload = {"status": "stale", "available": False, "graph_available": True, "viewer_available": True, "viewer_stale": True}
                else: payload = {"status": "ok"}
                route.fulfill(content_type="application/json", body=json.dumps(payload))

            page.route("**/api/**", route_handler)
            page.goto(f"http://127.0.0.1:{server.server_port}/#graphify", wait_until="networkidle")
            page.get_by_text("Graphify-карта устарела", exact=True).wait_for()
            assert page.locator(".graphify-native-frame").count() == 0
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_browser_renders_self_contained_graphify_viewer_under_strict_csp(tmp_path: Path):
    """The actual API response must render without reaching Graphify's CDN."""
    playwright = _browser_runtime()
    root = Path(__file__).parents[1]
    project = tmp_path / "project"; project.mkdir()
    graph = graphify_graph_path(project)
    graph.parent.mkdir(parents=True)
    graph.write_text(json.dumps({"nodes": [{"id": "entry"}], "edges": []}), encoding="utf-8")
    upstream = """<!doctype html><html><body><div id='graph' style='width:500px;height:300px'></div>
<script src=\"https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js\"></script>
<script>const data={nodes:new vis.DataSet([{id:'entry',label:'entry'}]),edges:new vis.DataSet([])}; window.network=new vis.Network(document.getElementById('graph'),data,{});</script>
</body></html>"""
    viewer = _self_contained_viewer(upstream)
    assert viewer is not None
    graphify_viewer_cache_path(project).write_text(viewer, encoding="utf-8")
    server, thread = _server(root, project)
    try:
        with playwright.sync_playwright() as runtime:
            browser = _launch_chromium(runtime)
            page = browser.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/api/adapters/graphify/viewer", wait_until="networkidle")
            page.locator("canvas").wait_for()
            assert page.evaluate("Boolean(window.network)")
            assert not page_errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_browser_missing_project_stays_on_simple_onboarding(tmp_path: Path):
    playwright = _browser_runtime()
    root = Path(__file__).parents[1]
    missing = tmp_path / "missing-project"
    server, thread = _server(root, missing)
    try:
        with playwright.sync_playwright() as runtime:
            browser = _launch_chromium(runtime)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/#review", wait_until="networkidle")
            page.locator("#onboardingError").get_by_text("Папка проекта не найдена", exact=False).wait_for()
            assert page.locator("#onboarding").is_visible()
            assert page.url.endswith("#review")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

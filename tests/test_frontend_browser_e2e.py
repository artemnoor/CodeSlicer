from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


def _server(root: Path, project: Path):
    from impact_engine.local_api import LocalApiState, create_server

    state = LocalApiState(str(project), "support_packs")
    server = create_server("127.0.0.1", 0, str(root / "frontend"), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_browser_shows_a_single_project_map_and_optional_graphify():
    playwright = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).parents[1]
    project = root / "tests" / "corpus" / "JunMate"
    server, thread = _server(root, project)
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                pytest.skip(f"Chromium is unavailable: {exc}")
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

            def route_handler(route):
                path = route.request.url.split("/api/")[-1].split("?")[0]
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
                elif path == "adapters":
                    payload = {"adapters": [{"id": "graphify", "status": "imported", "enabled": True, "freshness": {"status": "fresh"}}]}
                elif path == "tools":
                    payload = {"tools": [{"id": "graphify", "connected": True, "repository": {"cloned": True}}]}
                else:
                    payload = {"status": "ok"}
                route.fulfill(content_type="application/json", body=json.dumps(payload))

            page.route("**/api/**", route_handler)
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")

            assert page.url.endswith("#map")
            assert page.locator(".simple-nav a").count() == 2
            assert page.get_by_text("Проверка изменений", exact=True).count() == 0
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
            assert "не меняет рекомендации CodeSlicer" in page.locator("#graphifyContent").inner_text()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_browser_missing_project_stays_on_simple_onboarding(tmp_path: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).parents[1]
    missing = tmp_path / "missing-project"
    server, thread = _server(root, missing)
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                pytest.skip(f"Chromium is unavailable: {exc}")
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/#review", wait_until="networkidle")
            page.locator("#onboardingError").get_by_text("Папка проекта не найдена", exact=False).wait_for()
            assert page.locator("#onboarding").is_visible()
            assert page.url.endswith("#map")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

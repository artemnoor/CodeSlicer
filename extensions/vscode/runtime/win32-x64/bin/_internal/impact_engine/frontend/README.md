# CodeSlicer Local Hub

`index.html` is the single local-first SPA. It deliberately exposes only two
hash routes: `#map` and `#graphify`. The main map shows the CodeSlicer graph;
Graphify is an optional, separate architecture map. Old deep links resolve to
`#map`, so they do not strand a user in removed dashboard screens.

The browser never contains a fallback graph or mock project data. It renders
responses from the same-origin local API. CLI commands, agent skills and
advanced adapter controls remain available outside this intentionally small UI.

Run it from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m impact_engine.local_api --host 127.0.0.1 --port 8001 --default-project C:\path\to\project
```

The same command works after `pip install impact-engine`: the release wheel
bundles this frontend under `impact_engine/frontend`, so a source checkout is
not required to serve `http://127.0.0.1:8001/`.

The small UI uses these same-origin routes:

- `GET /api/health`, `/api/state`, `/api/progress`, `/api/overview`, `/api/graph`, `/api/inventory`, `/api/adapters`, `/api/adapters/lsp/status`
- `POST /api/analyze`, `/api/analyze/cancel`, `/api/graph/projection`
- `POST /api/graph/projection`, `/api/graph-workspace`
- `GET /api/adapters`, `/api/tools`
- `POST /api/tools/graphify/connect`
- `GET /api/adapters/graphify/viewer/status`, `/api/adapters/graphify/viewer`

Analysis progress is polled from `/api/progress`; it is not simulated in the
browser. Connecting Graphify requires an explicit confirmation because it may
create a separate local upstream workspace. Its viewer route only renders a
real `graphify-out/graph.json`; it never falls back to the canonical graph.
The hub does not expose test runs, Git controls, CI, editor opening or advanced
adapter configuration.

CodeSlicer owns its canonical graph. Graphify is optional local architecture
context; it never silently changes CodeSlicer output. Other adapters remain
available through the CLI and agent workflows rather than the browser hub.

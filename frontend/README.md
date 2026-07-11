# Local Frontend

`index.html` is the Russian local UI for the real local Impact Engine API. The
browser does not contain a fallback graph, does not write graph edges, and does
not call any external database directly.

Run it from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m impact_engine.local_api --host 127.0.0.1 --port 8001 --default-project C:\path\to\project
```

The UI calls these same-origin endpoints:

- `GET /api/health`
- `GET /api/state`
- `GET /api/graph`
- `GET /api/inventory`
- `POST /api/analyze` with `{ "project_path": "..." }`
- `POST /api/impact`
- `POST /api/query`

The backend calls the existing `analyze_project_core()` and `impact_query()`
implementations. Registry data and research queues remain local in SQLite and
the local cache. The incremental UI action does not simulate success; it
returns a truthful unsupported response until a changed-file request is
supplied through the incremental CLI contract.

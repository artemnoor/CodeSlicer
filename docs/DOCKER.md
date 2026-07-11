# Docker Compose

Docker Compose runs the local visual API and local registry API. The MCP
server remains a stdio process and is normally started by the host agent.

## Start

Set the project to analyze and start the services:

    $env:IMPACT_PROJECT_PATH = "C:\path\to\project"
    docker compose up --build

Open http://127.0.0.1:8001/ for the visual interface.

The local registry API is available at
http://127.0.0.1:8787/api/health. Both services share the named impact_state
volume, which stores the SQLite database and local registry cache.

## Stop

    docker compose down

To remove the local registry volume too:

    docker compose down -v

The analyzed project is mounted read-only at /workspace/project. Analysis
artifacts and registry state are written to the container volume, not into
the source project.

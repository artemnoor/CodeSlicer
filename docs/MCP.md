# MCP

Impact Engine exposes a local JSON-RPC 2.0 MCP server over stdio. It is not a
hosted MCP service and it does not require a database or network connection.

## Start

    $env:PYTHONPATH = "src"
    python -m impact_engine.mcp.server

Each input line is one JSON-RPC request. Output is UTF-8 JSON-RPC on stdout;
diagnostic logging must stay off stdout.

Example:

    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"local-client","version":"1"}}}
    {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}

The server validates required fields, primitive types, enums, unknown fields,
paths, depth limits, and timeout values. Invalid parameters return JSON-RPC
-32602; malformed requests do not expose Python tracebacks.

## Tool groups

- runtime: health_check, server_info;
- project: analyze_project, project_inventory, detect_languages,
  detect_unknown_libraries;
- graph: impact_query, impact_path, explain_edge, graph_quality, pr_review,
  runtime_trace;
- packs: list, validate, import, install;
- research: create workflow, prepare input, validate candidate, install
  validated pack;
- local registry: status, pull pack, create request, process queue, library
  status, approve pack, check documentation, simulate lifecycle.

Use tools/list as the source of truth for exact schemas.

## Safety boundary

AI research can create draft artifacts and evidence reports. It cannot write
trusted graph edges directly. Pack trust transitions and confidence caps are
enforced by the local registry and validation pipeline.

# MCP Server Design

The MCP server serves as the tools API surface for Codex, Claude Desktop, and other local agentic integrations.

## Core Runtime Principles

1. **Local Stdio Process Only**:
   - The server communicates exclusively via Standard Input (stdin) and Standard Output (stdout).
   - It is **not** a web server or a remotely hosted service. It does not spawn HTTP/FastAPI listeners.
   - Standard Error (stderr) is reserved for debug logs or process logging, so it does not pollute the JSON-RPC stdout stream.

2. **JSON-RPC 2.0 Compliance**:
   - Implements robust JSON-RPC 2.0 parsing and serialization.
   - **Silent Notifications**: Request payloads without an `"id"` field (such as `initialized`) are treated as notifications and silently processed without triggering a response.
   - **Cyrillic & Unicode Safety**: To prevent encoding mojibake on Windows platforms, the server reads/writes directly to binary buffers (`sys.stdin.buffer` and `sys.stdout.buffer`) encoded as UTF-8.

3. **Strict Schema Validation**:
   - Validates all incoming arguments against declared tool schemas in Python before execution.
   - Ensures type checks (`string`, `integer`, `number`, `boolean`, `object`, `array`), enum matches, and required field checks.
   - Unrecognized parameters are consistently rejected.

## Standard JSON-RPC Error Codes

- **Parse Error (`-32700`)**: Returned when stdin input is not valid JSON.
- **Invalid Request (`-32600`)**: Returned when payload is not a JSON object or lacks standard fields.
- **Method Not Found (`-32601`)**: Returned when calling unrecognized MCP methods or calling a tool not present in the registry.
- **Invalid Params (`-32602`)**: Returned when tool arguments fail strict validation.
- **Internal Error (`-32603`)**: Returned when core tool execution throws a runtime exception (tracebacks are suppressed in user-facing message).

## Core Tools List

1. **health_check**: Confirms server health (`{"status": "healthy"}`).
2. **server_info**: Exposes server name, version, and protocol version.
3. **analyze_project**: Executes static extraction and precision resolution, returning a compiled graph. Supports optional `timeout_seconds` guard using a thread executor.
4. **impact_query**: Performs reachability traversal. `max_depth` is strictly bounded to a maximum of 100 to prevent infinite loops.
5. **explain_edge**: Provides trace reasoning and evidence items backing a semantic inferred edge.
6. **detect_languages**: Identifies file extension profiles.
7. **project_inventory**: Scans lines of code, classes, methods, and files.
8. **detect_unknown_libraries**: Discovers imported libraries lacking local support packs.
9. **list_support_packs**: Lists installed rule libraries.
10. **validate_support_pack**: Audits support pack JSON formats against schema.
11. **import_support_pack**: Installs valid custom support pack definitions.
12. **install_support_pack**: Thin user-facing alias to install support packs.
13. **create_library_research_request**: Outputs AI prompt contexts for missing framework definitions.
14. **create_library_research_workflow**: Initializes a local research sequence folder.
15. **prepare_library_research_input**: Fetches page contents. Offline/dry mode by default (`allow_network=False`); set `allow_network=True` to explicitly permit HTTP fetches.
16. **validate_library_research_candidate**: Validates candidate files produced by AI.
17. **install_library_support_pack**: Saves candidate rules to the support packs database registry.

## Local Client Configuration

To integrate the Impact Engine MCP server with Claude Desktop or similar clients, add the following configuration snippet to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "impact-engine": {
      "command": "python",
      "args": [
        "-m",
        "impact_engine.mcp.server"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\Артём\\Documents\\KodikWinWin\\impact_engine_mcp_library_research_pack_v0_4\\src"
      }
    }
  }
}
```

# AI Library Researcher Protocol

This protocol guides the AI assistant when generating support packs for unknown libraries.

## Bounded Research Input Pack

The AI agent receives a strict `ResearchInputPack` containing:
- Library name, ecosystem, and target version range.
- Scan logs of detected import usages and code snippet blocks.
- A typed source plan covering official documentation, the official source repository, and the package registry.
- Bounded fetch excerpts containing URLs, source type, HTTP status, usable-evidence flag, and failure diagnostics.
- A source-coverage report showing which primary sources were actually available.

The workflow fetches documentation and repository material before registry metadata. Search-result pages are not accepted as primary evidence. The default fetch budget is bounded (12 unique HTTPS URLs) so research remains reproducible and cannot crawl an unbounded site.

## Research Procedure

The external AI researcher must use the input pack in this order:

1. Read the project imports and usage examples to identify relevant library features.
2. Read official documentation for public patterns and lifecycle semantics.
3. Read the official repository examples/tests for behavior that documentation omits.
4. Use the package registry only for package/version metadata, never as sole evidence for a semantic rule.
5. Generate deterministic rules with one or more source URLs per rule.
6. Record unsupported, failed-to-fetch, and unverified areas in `coverage_limitations`.
7. Return only a machine-readable candidate pack; local validation and fixture tests decide whether it can be installed.

## Provider-Neutral Agent Task

The workflow also writes `agent_task.json` and `agent_system_prompt.txt`.
These files are the integration boundary for any capable AI agent; no specific
model, vendor SDK, or API key is required by Impact Engine. The agent reads the
task, optionally browses the listed primary sources, and writes the candidate
JSON to the declared output path. CLI and MCP only create/prepare this task;
they do not silently call an LLM.

## Candidate Delivery Requirements

1. **Schema compliance**: Support packs must map exact JSON structure:
   ```json
   {
     "library": "libname",
     "version_range": ">=1.0.0",
     "language": "python",
     "status": "experimental",
     "sources": [],
     "patterns": [],
     "edge_rules": []
   }
   ```
2. **Deterministic resolution**: All rule patterns must map statically extracted nodes to emitted edges, with predefined confidence scores.
3. **Validation**: Candidate support pack JSON is audited locally. It is never installed without passing the schema and playground engine validation steps.

No AI call is made during ordinary project analysis. AI is used only to turn the bounded research corpus into a candidate pack; the resolver remains deterministic afterward.

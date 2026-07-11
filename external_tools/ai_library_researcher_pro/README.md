# ai_library_researcher_pro

`ai_library_researcher_pro` is a standalone Python workflow for researching an unknown library and producing an Impact Engine-style `support_pack.json` draft. It is intentionally independent: it does not import or require any Impact Engine code.

The pipeline is:

```text
unknown library
→ deterministic source discovery
→ bounded fetch/read of official docs, registries, GitHub candidates, or local fixtures
→ snippet/example extraction
→ AI input handoff artifacts
→ conservative heuristic support_pack_draft.json
→ validation_result.json
→ report.md
```

## What it does

- Creates persistent research workflows under `.impact_engine/research_workflows/<workflow_id>/`.
- Discovers official candidate sources for Python, JavaScript/TypeScript, Go, and Java packages.
- Uses deterministic URL generation when no search API is available.
- Safely fetches a small bounded number of pages only when `--allow-network` is explicit.
- Reads local project documentation/fixtures without network.
- Extracts imports, code blocks, decorators, route examples, DI examples, wrapper/call examples, endpoint sinks, and tests.
- Builds `ai_input.json` and `ai_prompt.md` for AI-assisted generation.
- Generates a conservative heuristic `support_pack_draft.json` without pretending to have real LLM understanding.
- Validates support packs and reports warnings/errors.

## What it does not do

- It does not crawl the internet recursively.
- It does not execute downloaded code.
- It does not call a real LLM API.
- It does not import or depend on any Impact Engine package.
- It does not guarantee a perfect semantic support pack. Weak evidence produces low confidence and diagnostics.

## Deterministic vs AI-assisted mode

The module has two generation paths:

1. **Heuristic mode** creates a conservative draft directly from extracted examples. Confidence is low/medium unless the evidence is strong.
2. **AI-assisted handoff mode** writes `ai_input.json` and `ai_prompt.md`. Another model can use these artifacts to produce or refine a support pack. The validator can then check the result.

## Safety rules

Network access is disabled by default. Remote fetching requires `--allow-network`.

The fetcher blocks:

- `file://`, `ftp://`, `sftp://`, and unsupported URL schemes;
- localhost and private IP hosts;
- too many URLs;
- pages larger than the configured byte limit;
- total fetched bytes above the configured limit;
- content types outside a small text allowlist.

Downloaded content is treated only as text. No code is executed.

## CLI usage

```bash
python -m ai_library_researcher_pro.cli --help
```

Create a workflow:

```bash
python -m ai_library_researcher_pro.cli create \
  --library fastapi \
  --ecosystem python \
  --project-path ./fixtures/sample_project \
  --json
```

Discover sources without network:

```bash
python -m ai_library_researcher_pro.cli discover <workflow_id> --json
```

Fetch remote sources. This command requires explicit network permission:

```bash
python -m ai_library_researcher_pro.cli fetch <workflow_id> --allow-network --json
```

Extract examples:

```bash
python -m ai_library_researcher_pro.cli extract <workflow_id> --json
```

Build AI handoff artifacts:

```bash
python -m ai_library_researcher_pro.cli build-input <workflow_id> --json
```

Generate a heuristic draft:

```bash
python -m ai_library_researcher_pro.cli generate-draft <workflow_id> --json
```

Validate the generated draft or an external pack:

```bash
python -m ai_library_researcher_pro.cli validate <workflow_id> --json
python -m ai_library_researcher_pro.cli validate <workflow_id> --pack path/to/support_pack.json --json
```

Write a report:

```bash
python -m ai_library_researcher_pro.cli report <workflow_id> --json
```

Run the full offline workflow:

```bash
python -m ai_library_researcher_pro.cli run \
  --library fastapi \
  --ecosystem python \
  --project-path ./fixtures/sample_project \
  --json
```

Run with remote fetching enabled:

```bash
python -m ai_library_researcher_pro.cli run \
  --library fastapi \
  --ecosystem python \
  --project-path ./fixtures/sample_project \
  --allow-network \
  --json
```

## Exit codes

- `0` success
- `1` runtime/IO error
- `2` validation failed
- `3` network not allowed / unsafe URL blocked

## Output artifacts

Each workflow writes:

```text
.impact_engine/research_workflows/<workflow_id>/
  research_request.json
  discovered_sources.json
  fetched_pages/
    index.json
    page_000.txt
  extracted_examples.json
  ai_input.json
  ai_prompt.md
  support_pack_draft.json
  validation_result.json
  report.md
```

## Support pack schema

A draft support pack contains at least:

```json
{
  "library": "fastapi",
  "ecosystem": "python",
  "version_range": "*",
  "imports": [],
  "rules": [],
  "evidence_sources": [],
  "generated_by": {
    "tool": "ai_library_researcher_pro",
    "mode": "heuristic",
    "version": "0.1.0"
  },
  "confidence": 0.0,
  "diagnostics": []
}
```

Supported rule types:

- `decorator_entrypoint`
- `object_graph`
- `endpoint_sink`
- `wrapper_function`
- `provider_factory`
- `constructor_injection`
- `method_call_alias`
- `test_target_pattern`
- `component_usage`
- `route_pattern`

Every rule must include:

- `id`
- `type`
- semantic config fields
- `confidence` between `0` and `1`
- non-empty `evidence` pointing to recorded source URLs
- diagnostics when uncertainty is important

## Integration with another project

A consuming project can treat this module as an external tool:

1. Run `create` or `run` for a library/ecosystem.
2. Read `.impact_engine/research_workflows/<workflow_id>/support_pack_draft.json`.
3. Read `.impact_engine/research_workflows/<workflow_id>/validation_result.json`.
4. Install only schema-valid packs, or route weak/invalid drafts to manual review using `ai_input.json`, `ai_prompt.md`, and `report.md`.

The JSON outputs are stable and sorted so they can be consumed by CI, MCP wrappers, or another orchestration service.

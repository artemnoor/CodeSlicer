# Impact Engine Skills

The repository includes eight agent workflows in `integrations/agent-skills/`. They are
thin orchestration layers over the existing CLI and MCP interfaces; they do not
duplicate graph or resolver logic.

## Included workflows

- `impact-analyze-project` - build a baseline graph and diagnostics.
- `impact-review-change` - find affected nodes and evidence.
- `impact-pr-review` - review a diff and recommend tests.
- `impact-fullstack-trace` - trace frontend to backend chains.
- `impact-research-library` - research unknown libraries safely.
- `impact-explain-graph` - explain node and edge provenance.
- `impact-runtime-validate` - validate static edges with runtime traces.
- `impact-incremental-analyze` - compare incremental and clean graphs.

## Local setup

Open the repository in an agent environment that supports repository skills. If
the environment requires a global skills directory, copy `integrations/agent-skills/` to
that directory or invoke a skill explicitly by its folder name.

The skills use the installed `impact-engine` command when available and fall
back to `python -m impact_engine.cli`. CLI/MCP remain the stable technical
interfaces; skills only coordinate multi-step workflows and enforce evidence
and confidence rules.

# Совместимость установщика AI-клиентов

`impact-engine agent` — локальный установщик двух упакованных skills и одной
локальной stdio MCP-записи. Он не меняет исходный код проекта, `AGENTS.md`,
master-router или другие инструкции. Статус `experimental` означает, что
адаптер присутствует в каталоге, но его contract не следует считать
гарантированным до отдельной проверки у поставщика.

| Client | Aliases | Skills integration | Project path | User path | MCP registration | Status | Last verified |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Codex CLI / IDE | `openai-codex`, `codex-cli`, `codex-ide` | native-skill | `.agents/skills` | `~/.agents/skills` | `~/.codex/config.toml` (предпочтительно CLI) | verified | 2026-07-28 |
| Claude Code | `claude-code`, `anthropic-claude` | native-skill | `.claude/skills` | `~/.claude/skills` | `.mcp.json` | experimental | — |
| Cursor IDE | `cursor-ide`, `cursor-cli` | rule-adapter | `.cursor/rules/*.mdc` | — | `.cursor/mcp.json` | experimental | — |
| Windsurf / Cascade | `cascade`, `codeium` | native-skill | `.windsurf/skills` | `~/.codeium/windsurf/skills` | `~/.codeium/windsurf/mcp_config.json` | experimental | — |
| Qwen Code | `qwen-code`, `qwen-cli` | native-skill | `.qwen/skills` | `~/.qwen/skills` | CLI when available | experimental | — |
| Kilo Code | `kilo-code`, `kilocode` | native-skill | `.kilo/skills` | `~/.kilo/skills` | `.kilo/kilo.jsonc` | experimental | — |
| Kiro IDE / CLI | `kiro-ide`, `kiro-cli` | instruction-adapter | `.kiro/steering/*.md` | `~/.kiro/steering` | `.kiro/settings/mcp.json` | experimental | — |
| Qoder IDE / CLI | `qoder-ide`, `qoder-cli`, `qodercli` | native-skill | `.qoder/skills` | `~/.qoder/skills` | `.qoder/settings.local.json` | experimental | — |
| GitHub Copilot CLI | `github-copilot`, `copilot-cli` | shared-skill | `.agents/skills` | `~/.agents/skills` | `.mcp.json` | experimental | — |
| Gemini CLI | `gemini-cli`, `google-gemini` | shared-skill | `.gemini/skills` | `~/.gemini/skills` | `.gemini/settings.json` | experimental | — |
| Cline | — | no safe automatic target | — | — | — | unsupported | — |
| OpenCode | — | native-skill | `.opencode/skills` | `~/.config/opencode/skills` | `.opencode/mcp.json` | experimental | — |
| Zed | — | no safe automatic skill target | — | — | `.zed/settings.json` | experimental (MCP-only) | — |
| Junie | — | instruction-adapter | `.junie/*.md` | — | `.junie/mcp/mcp.json` | experimental | — |
| CodeBuddy | — | no safe automatic target | — | — | — | unsupported | — |
| Kodik IDE | `kodik-ide`, `kodik-cli` | native-skill | `.kodik/skills` | `~/Documents/Kodik/Skills` | existing `User/globalStorage/kodik.chat/settings/mcp.json`, key `servers` | verified | 2026-07-28 |

## Kodik IDE

Kodik is a separate adapter, not a spelling variant of Kiro. Its documented
native skill paths are `.kodik/skills/<name>/SKILL.md`, the shared
`.agents/skills` directory, and `~/Documents/Kodik/Skills/`. Its MCP file is
JSONC under Kodik's global storage and uses the top-level key `servers`. The
installer patches only `servers.codeslicer`, preserves other entries and
comments, and never adds an automatic approval setting. If Kodik has not yet
created `mcp.json`, open its MCP settings once and then use `agent repair`.
See the official [Kodik skills documentation](https://docs.kodik.ru/customization/skills)
and [MCP configuration documentation](https://docs.kodik.ru/mcp/configuring).

## Scope and safe lifecycle

`--scope project` writes only inside the chosen project (except Kodik's
documented user-level MCP file). `--scope user` writes under the selected home
directory. Use `--dry-run` to inspect exact target paths, `status` to compare
hashes, `repair` to restore managed copies, and `uninstall` to remove only
unchanged owned files and the single owned MCP entry. Existing changed files
are retained unless `--force` is explicit. Restart or reload the AI client
after changing its configuration.

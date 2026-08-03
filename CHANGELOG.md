# Changelog

Все заметные изменения CodeSlicer фиксируются в этом файле.

## [0.6.41] — 2026-08-03

### Compiler-backed semantic readiness

- Added a single, explicit local semantic-backend catalogue for every detected language: official SCIP indexers for compiler languages and official LSP tooling for frontend component languages.
- Added a verified native `scip-go` contract alongside TypeScript/JavaScript; automatic selection respects `go.mod` instead of incidental documentation JavaScript.
- Fixed Windows `file://C:%5C...` SCIP project-root freshness verification and standard `GOPATH/bin` discovery.
- Bundled analyzer runtime is `0.5.3`; VS Code extension and runtime-manifest compatibility are `0.6.41`.

## [0.6.40] — 2026-08-03

### Semantic enrichment profiles

- Added explicit, never-download local semantic-server profiles for Go, C/C++, Rust, Java, Kotlin, PHP, Ruby, TypeScript/JavaScript, HTML/CSS, Vue, Svelte, and Astro.
- Preflight now reports available local profiles and the required compiler/project context; `configure-profile` records only the selected local command, while `probe` remains the explicit process-start boundary.
- Public language capability metadata reports optional compiler/LSP enrichment separately from the deterministic canonical baseline, including cache hits.
- Bundled analyzer runtime is `0.5.2`; VS Code extension and runtime-manifest compatibility are `0.6.40`.

## [0.6.39] — 2026-08-03

### VS Code cockpit polish

- The tab navigation now remains sticky in the narrow VS Code sidebar, including long Help pages.
- Result summary cards preserve whole words in a narrow pane; long test and source paths truncate predictably with their full value available as a tooltip.
- An unchecked bundled runtime is shown as `Preparing runtime…` rather than an error-like `!`; real validation failures still remain explicit.
- The VS Code extension and runtime-manifest compatibility are `0.6.39`; bundled analyzer runtime remains `0.5.1`.

## [0.6.38] — 2026-08-03

### Polyglot and frontend coverage

- Added manifest-backed native Tree-sitter plugins for C/C++, HTML, CSS/SCSS/Sass/Less, Vue, Svelte, Astro, Rust, Kotlin, PHP, and Ruby.
- Modern JavaScript/TypeScript module suffixes (`.mjs`, `.cjs`, `.mts`, `.cts`) now stay on the supported path through inventory, extraction, coverage, identity, and review.
- TypeScript local semantic resolution now covers explicit `const`/arrow exports and their local imports, producing evidence-backed call edges instead of `UNKNOWN` regions.
- Bundled analyzer runtime is `0.5.1`; the VS Code extension and compatibility manifest are `0.6.38`.

## [0.6.37] — 2026-08-03

### Fixed

- Нормализован version contract Windows VSIX: имя установленного extension,
  `package.json` и `runtime.manifest.extensionCompatibility` используют
  `0.6.37`; bundled analyzer остаётся явно обозначенным как `0.5.0`.
- README и VS Code packaging guide теперь объясняют, почему версии cockpit и
  runtime различаются и какие значения обязаны совпадать.

## [0.6.30] — 2026-08-02

### Changed

- Ускорен post-project hygiene: annotation-проход работает с canonical
  `GraphDocument`, не создавая полную дублирующую dictionary-копию графа.
- В больших проектах полный hygiene-report вынесен в локальный сжатый
  `.impact_engine/project_hygiene.json.gz`; глубокие impact-запросы загружают
  его только при необходимости.
- Final `FactDocument` создаётся и записывается один раз после resolution,
  без промежуточной копии до resolution.

### Fixed

- Changed-file candidate больше не может перезаписать canonical graph или его
  hygiene sidecar. Если safe whole-project merge не доказан, review выполняет
  явный full refresh вместо неполного результата.

### Validation

- Полный suite: `824 passed, 25 skipped`; skipped — opt-in внешние
  LSP/SCIP-интеграции.
- Реальный Django benchmark: 6 958 файлов, 315 345 узлов, 316 365 рёбер;
  сохранены одинаковые semantic node/edge hashes до и после оптимизации.

## [0.5.0] — 2026-07-29

### Added

- Безопасный `impact-engine agent` installer: `detect`, `list-clients`,
  `install`, `status`, `doctor`, `repair` и `uninstall`.
- Native integration для Kodik IDE: `.kodik/skills` и точечная JSONC MCP
  запись `servers.codeslicer` без изменения чужих конфигураций.
- Реальный stdio MCP doctor: JSON-RPC `initialize`, `tools/list` и проверка
  `scan_plan`, `project_status`, `review`, `inspect`.
- Матрица совместимости 16 AI-клиентов и clean-wheel E2E для installer.

### Changed

- README обновлён: текущие команды запуска, screenshots локального UI, badges,
  AI-installation workflow и ссылка на GitHub Release.
- Browser E2E, isolated wheel validation и real Agent-LSP E2E входят в CI.

[0.5.0]: https://github.com/artemnoor/CodeSlicer/releases/tag/v0.5.0
[0.6.30]: https://github.com/artemnoor/CodeSlicer/releases/tag/v0.6.30

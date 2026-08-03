# Changelog

Все заметные изменения CodeSlicer фиксируются в этом файле.

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

# Changelog

Все заметные изменения CodeSlicer фиксируются в этом файле.

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

# PR: Local-first map hub, native Graphify viewer and installable release

## Цель

Сделать CodeSlicer понятным входом в проект без превращения UI в дубликат
CLI, MCP и agent skills. Пользователь открывает локальную карту кода, выбирает
узел и видит evidence. Когда нужен широкий архитектурный обзор, он отдельно
открывает оригинальную карту Graphify. Сложные команды, policy и automation
остаются в CLI/MCP.

## Что меняется

### Local UI

- Оставлены две независимые страницы: `#map` и `#graphify`.
- `#map` визуализирует только canonical GraphDocument CodeSlicer. Поддержаны
  pan, zoom, reset, keyboard navigation и inspector выбранного узла.
- `#graphify` отображает только настоящий `graphify-out/graph.json` через
  upstream HTML renderer Graphify. CodeSlicer не конвертирует этот граф в
  собственную SVG-проекцию и не меняет его узлы, рёбра или communities.
- Отсутствие Graphify-артефакта показано как понятное состояние «не
  подключён», без подмены данными CodeSlicer.

### Производительность и честность анализа

- Full scan передаёт extractors уже отфильтрованный inventory, а не заставляет
  каждый extractor заново обходить workspace.
- Прогресс extraction обновляется по обработанным исходным файлам.
- Отмена проверяется между файлами и не сохраняет частичный graph.
- По умолчанию исключаются generated artifacts, tool runtimes, output и
  скрытые служебные директории. Это ускоряет анализ; если проект намеренно
  хранит код в такой директории, её следует явно включить отдельным scan-plan.

### Дистрибуция

- Wheel включает `impact_engine/frontend/*`.
- Manifest-backed plugins устанавливаются как top-level package `plugins/*`
  вместе с `plugin.json` и `pack.json`.
- Runtime ищет plugins сначала в checkout, затем в installed package. Поэтому
  тот же механизм работает в editable mode, из wheel и в чистой virtualenv.

## Проверяемые E2E-сценарии

| Сценарий | Проверка | Gate |
|---|---|---|
| Python/full-stack graph | Extract → normalize → impact/evidence → tests | `tests/test_e2e_pipeline.py` |
| C# plugin | Лёгкие C# manifests, extractor и review evidence | `tests/test_csharp_plugin.py` в обычной регрессии |
| C# external acceptance | Pinned публичный Cruxa, read-only diff, route/test review | weekly/manual `.github/workflows/csharp-acceptance.yml` |
| Browser map | Реальный local API, карта, inspector узла, Graphify route | обязательный `browser-e2e` job с Playwright + Chromium |
| Full regression | Все unit/integration/regression тесты | `python -m pytest -q` |
| Wheel release | build → новая venv → install wheel → plugin discovery → local API → HTML UI + `/api/health` | `python scripts/check_wheel_e2e.py` |

GitHub Actions запускает полную регрессию, wheel E2E и обязательный browser
E2E на каждый push и pull request. Внешний Cruxa acceptance запускается
отдельно по расписанию или вручную: corpus не хранится в Git и не маскируется
как skipped-проверка обычной регрессии.

## Local-first и границы доверия

- Base analysis не открывает сеть и не отправляет исходный код.
- Graphify workspace создаётся только по явному действию и остаётся локальным.
- Внешние runtime/LSP/Joern/telemetry инструменты не становятся confirmed
  evidence автоматически: они остаются отдельными overlays с provenance.
- Graphify не меняет impact ranking CodeSlicer.

## Скриншоты

![Карта и inspector CodeSlicer](images/codeslicer-map-inspector.png)

![Оригинальная карта Graphify](images/codeslicer-graphify-native.png)

## Release checklist

- [x] `git diff --check`
- [x] полный `pytest`
- [x] JS/Python syntax checks
- [x] build wheel
- [x] isolated wheel E2E
- [x] браузерная проверка карты и оригинального Graphify viewer
- [x] build artifacts, local runtimes и screenshots вне `docs/images/` ignored
- [ ] review staged diff и создать commit
- [ ] push после успешного CI

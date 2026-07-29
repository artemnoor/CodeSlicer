# CodeSlicer workspace: движки, возможности и практические сценарии

## 1. Что это за система

CodeSlicer — local-first workspace для работы с кодом, а не просто один
графовый анализатор. Он объединяет несколько независимых локальных движков и
поверхностей работы: CLI для автоматизации, Local Hub для исследования,
agent skills/MCP для IDE и optional adapters для специализированного контекста.
Система намеренно не «склеивает всё в один graph»: у каждого источника есть
собственный формат, владелец, provenance и граница доверия.

| Задача | Владелец результата | Что получается |
| --- | --- | --- |
| Оценить риск правки, найти impact и тесты | **CodeSlicer engine** | canonical evidence graph, `review`, `inspect`, `investigate`, CI report |
| Понять крупную архитектуру, communities, код и документацию | **Graphify engine** (optional) | самостоятельный Graphify graph и upstream viewer |
| Перейти к declaration/references/implementations | **LSP / SCIP** (optional) | bounded semantic navigation overlay |
| Посмотреть runtime, contracts, SBOM или security context | explicit artifact/runtime adapters | отдельные provenance-bearing overlays |
| Дать задачу IDE-агенту | bundled skills, CLI, optional MCP | локальный workflow; MCP не обязателен |

CodeSlicer engine строит свой **canonical evidence graph**: файлы, модули,
символы, импорты, вызовы, тесты, маршруты, зависимости и подтверждённые
framework-связи. По нему система отвечает на практический вопрос: **что может
затронуть конкретное изменение и что стоит проверить до merge**. Graphify
решает соседнюю, но другую задачу — навигацию по архитектуре — и не повышает
риск PR и не меняет рекомендации CodeSlicer.

Это не облачный IDE и не замена компилятора. CodeSlicer работает с локальной
копией проекта, сохраняет результаты рядом с проектом и показывает степень
уверенности. Если связь динамическая, неполная или язык не покрыт, результат
помечается `likely`, `unresolved`, `limited` или `unsupported`, а не выдаётся
за подтверждённый факт.

Основная ценность — не размер графа и не число узлов, а компактный,
объяснимый список top-impact сущностей, связанных тестов и evidence chains.

### 1.1. Что происходит при работе агента

После `codeslicer agent install` выбранная IDE получает два skills:
`codeslicer-impact-analysis` и `graphify-architecture-analysis`. Это не
автозапуск двух программ и не загрузка Graphify. Skills подсказывают агенту
правильный маршрут:

1. Для изменения, PR, риска или «что проверить?» — обратиться к CodeSlicer
   через CLI, а при наличии MCP можно использовать прямые structured calls.
2. Для вопроса «как устроены communities/модули/документация?» — проверить,
   что пользователь отдельно настроил Graphify и существует его local graph;
   затем использовать нативные Graphify operations.
3. Для symbol navigation или runtime/security context — не выдавать overlay за
   canonical факт, а явно показать источник и его ограничения.

Агент может работать только через CLI: MCP добавляет удобный транспорт, но не
является условием анализа. Ни CodeSlicer, ни агент не клонируют Graphify или
не запускают внешние движки без явного действия пользователя.

## 2. Как устроен рабочий поток

```text
Исходники + Git diff
        │
        ├─ CodeSlicer: scan-plan → extractors → resolvers/support packs
        │      └─ canonical GraphDocument → impact/review/tests/CI
        │
        ├─ Graphify (явно настроен и запущен отдельно)
        │      └─ independent architecture graph → communities/docs/viewer
        │
        └─ optional adapters (явный import/configure)
               └─ LSP, SCIP, contracts, runtime, SBOM, SARIF, Joern overlays

CLI / Local Hub / IDE skills / optional MCP выбирают подходящий слой, но не
меняют владельца графа и не повышают trust level автоматически.
```

### 2.1. Постоянные локальные данные

CodeSlicer не записывает рабочие графы в корень репозитория по умолчанию.

| Каталог | Назначение |
|---|---|
| `<project>/.impact_engine/` | canonical graph, scan plan, cache, snapshot, reverse index, registry и review-артефакты. |
| `<project>/.codeslicer/` | настройки адаптеров и их санитизированные локальные artifacts/overlays. |
| `graphify-out/` | внешний output Graphify; намеренно исключён из последующего source scan. |

Эти каталоги должны быть в `.gitignore`. Их можно удалить и построить заново;
они не являются исходным кодом продукта.

### 2.2. Обычный старт

```powershell
$project = 'C:\path\to\project'

# Для большого репозитория сначала посмотреть будущую область анализа.
impact-engine scan-plan $project

# Построить или обновить project-local graph.
impact-engine analyze $project --use-scan-plan

# Получить краткий ежедневный отчёт по текущему Git diff.
impact-engine review $project --base HEAD~1 --max-results 10
```

`analyze` сохраняет graph по умолчанию в
`<project>/.impact_engine/graph.json`. При добавлении `--json` структурированный
результат идёт в stdout, а progress — в stderr, поэтому CLI удобно вызывать из
скрипта, IDE или AI-агента.

## 3. Что делает ядро CodeSlicer

### 3.1. Inventory и безопасная область анализа

`scan-plan`, `inventory` и language detection определяют файлы, языки,
manifest-файлы, локальные модули, импорты и зависимости. По умолчанию не
индексируются `.git`, caches, virtual environments, `node_modules`, build/dist,
coverage, `.impact_engine`, `.codeslicer`, `graphify-out`, `bin`, `obj`, vendor
и generated-папки.

Это полезно для monorepo: вместо случайного анализа frontend build или npm cache
можно выбрать `--scope backend/src` либо другой осмысленный package scope.

### 3.2. Извлечение фактов и граф

Ядро строит граф из структурных и семантических фактов. В зависимости от языка
он может содержать:

- файлы, модули, namespaces, классы, интерфейсы, функции и методы;
- import/dependency и `CONTAINS` связи;
- вызовы и ссылки на символы;
- тестовые файлы и связи test → production code;
- HTTP routes, controller/API boundaries, frontend API clients;
- DI registrations, interface → implementation, MediatR, EF Core и DbContext
  в поддерживаемом C# structural subset;
- external libraries и package-manifest факты;
- provenance, evidence class, confidence, resolver attribution и coverage.

Поддержка различается по глубине:

| Язык/область | Текущее назначение |
|---|---|
| Python | Наиболее сильное semantic/resolver покрытие для обычного application-кода. |
| TypeScript / JavaScript | Структурный graph, imports, calls, frontend/framework patterns; dynamic runtime-поведение может остаться unresolved. |
| C# / .NET | Structural C# extractor: классы, интерфейсы, DI, controllers/routes, MediatR, EF Core, test mapping. Coverage честно может быть `limited`, без compiler binding. |
| Go / Java | Базовое structural и частичное semantic/framework покрытие. |
| Другие файлы и сложная динамика | Отмечаются как unknown/unsupported, а не подменяются догадкой. |

### 3.3. Режим `review`: ежедневный impact brief

```powershell
impact-engine --json review $project --base HEAD~1 --max-results 10
```

`review` автоматически читает Git diff, использует актуальный project-local
graph и возвращает ограниченный результат:

- risk level и причины риска;
- максимум 10 главных файлов или символов по умолчанию;
- direct / transitive / speculative distinction;
- targeted tests и fallback suite, если связь с конкретными тестами не
  доказана;
- 2–3 explainable chains, когда они доступны;
- language coverage, freshness, unsupported paths и warnings.

Default review скрывает built-ins, assignment-level шум, external libraries и
глубокий technical closure. Полный graph не теряется: его можно запросить
отдельно через `investigate`.

### 3.4. Режим `inspect`: почему сущность затронута

```powershell
impact-engine inspect $project --entity 'package.module.Service.save'
```

`inspect` нужен, когда top-impact уже найден, но требуется понять доказательство:
где находится сущность, какие у неё direct upstream/downstream связи, связанные
routes и tests, confidence, provenance и почему ranking включил именно её.

### 3.5. Режим `investigate`: ограниченное глубокое расследование

```powershell
impact-engine investigate $project `
  --entity 'package.module.Service.save' `
  --direction downstream --depth 6 --max-nodes 120 --max-edges 240
```

Это явное действие для архитектурного или incident-расследования. В отличие от
review, пользователь сам задаёт направление, глубину и лимиты. Результат
ограничивается `max-nodes`/`max-edges`, поэтому UI и CLI не пытаются отрисовать
тысячи связей по умолчанию. `--runtime-validate` запускает только явно
запрошенную runtime validation, а не произвольный код автоматически.

### 3.6. Ручной graph query и объяснение ребра

```powershell
impact-engine impact "$project\.impact_engine\graph.json" `
  --symbol 'package.module.Service.save' --direction both

impact-engine explain-edge "$project\.impact_engine\graph.json" `
  --from 'service.create' --to 'repository.save'
```

Эти команды полезны инженерам, которым нужен не review-brief, а конкретная
проверка пути по graph или объяснение одного ребра.

### 3.7. Incremental analysis, daemon и watch

```powershell
impact-engine analyze-incremental $project --changed src/service.py
impact-engine daemon start $project
impact-engine watch $project --interval 1
```

Incremental mode использует snapshots, cached raw facts и reverse dependency
index, чтобы не пересобирать неизменённые части без причины. Daemon — локальный
owner cache/analysis state; watch наблюдает за изменениями и запускает
инкрементальное обновление. Статусы cache, progress, cancellation и freshness
должны быть видны в JSON/API, а не скрываться за старым graph.

### 3.8. CI и PR workflow

```powershell
impact-engine ci $project --base origin/main --format json --out .impact_engine/ci-report.json
impact-engine ci $project --base origin/main --format sarif --out .impact_engine/ci.sarif
```

CI строится поверх той же review projection. Он может отдавать JSON или SARIF,
показывать policy result и, только при явных `--run-tests` и `--test-command`,
запускать выбранную пользователем тестовую команду. Это позволяет использовать
CodeSlicer как advisory report или как gate для high-risk изменений.

### 3.9. Локальный UI, визуализация и MCP

Local API и localhost Hub дают четыре пользовательских представления:

- **Review** — что проверить перед commit;
- **Inspect** — почему выбранный файл/символ затронут;
- **Investigate** — bounded deep graph;
- **Architecture** — map canonical graph и подключённых overlays.

В UI можно открыть файл/строку, увидеть evidence, выбрать overlay и подключить
local artifacts. В карте CodeSlicer по умолчанию включён быстрый обзор; явный
переключатель **«Показать все связи»** запрашивает весь canonical graph без
лимита проекции. На очень больших codebase это намеренно может быть медленнее
и визуально плотнее — полный режим нужен для полноты, а `Review` и
`Investigate` остаются удобнее для ежедневного решения. Отдельные `visualize`
и `visualize-compare` создают HTML представления graph и comparison с
Graphify. MCP предоставляет те же local operational capabilities AI-агенту
без обязательного внешнего сервиса.

## 4. Практические сценарии

### Сценарий A. Проверка изменения перед commit

1. Разработчик меняет service, route или UI component.
2. Запускает `review`.
3. Получает до 10 главных impact entities, risk и targeted tests.
4. Нажимает «Why affected?» или использует `inspect` для важной рекомендации.
5. Если результат слишком широкий — запускает bounded `investigate`.

**Результат:** не нужно вручную обходить весь dependency tree и читать тысячи
graph nodes.

### Сценарий B. Выбор тестов вместо полного suite

Изменился handler или repository. CodeSlicer ранжирует tests по прямому import,
symbol call, route integration и затем fallback suite. Если доказательств мало,
он обязан показать fallback, а не объявлять случайный тест «точно нужным».

**Результат:** ускоряется локальная проверка, но ограничения видны до merge.

### Сценарий C. Разбор неожиданного blast radius

После изменения `memory.ts` или shared service review может показать важных
потребителей. `inspect` объясняет прямую связь; `investigate` раскрывает путь
только до заданного лимита и помогает отличить реальную цепочку от
speculative/deep technical closure.

**Результат:** разработчик быстрее решает, менять ли API, добавлять regression
test или ограничить diff.

### Сценарий D. Full-stack route/contract изменение

Для controller, API client или schema CodeSlicer может собрать статические
frontend → HTTP → backend связи. При наличии OpenAPI/AsyncAPI overlay можно
показать документированный contract context, не смешивая его с доказанным
canonical ranking.

**Результат:** проще оценить, какие frontend components, controllers,
integration tests и consumers затронет изменение API.

### Сценарий E. Monorepo и большой проект

Сначала создаётся scan plan. Затем анализируется выбранный scope, работает
daemon/incremental cache, а generated/vendor/dependency folders не засоряют
graph. Для PR используется `review`, для архитектурной задачи — `investigate`.

**Результат:** проект не обязан проходить полный анализ заново при каждом
маленьком изменении.

### Сценарий F. Архитектурная карта и navigation

Canonical graph показывает то, что извлекло ядро. Graphify/CodeGraph могут
добавить внешний architectural view; LSP и SCIP — точную navigation/evidence
для символов. Пользователь выбирает, какой источник включить в Architecture
или Investigate.

**Результат:** CodeSlicer выступает как единый local hub, не выдавая overlay за
истину ядра.

### Сценарий G. Runtime и security context

OTel trace показывает наблюдённую runtime цепочку, SBOM показывает состав
зависимостей, SARIF — найденные security issues. Joern добавляет CPG/data-flow
контекст для C/C++/Java. Все они полезны при incident/security investigation,
но один runtime trace или finding не доказывает полный production behaviour.

## 5. Опциональные адаптеры

### 5.1. Общие правила

Адаптеры **не обязательны** для core analysis. Каждый из них выключен, пока
пользователь не импортирует локальный artifact или не настроит local process.

```powershell
impact-engine --json adapters preflight $project

# Для любого artifact-backed adapter:
impact-engine --json adapters import $project <adapter-id> C:\absolute\path\artifact --enable

# Проверка, отключение или повторное включение:
impact-engine --json adapters status $project <adapter-id>
impact-engine --json adapters disable $project <adapter-id>
impact-engine --json adapters enable $project <adapter-id>
```

После import source fingerprint и project context проверяются. Если artifact
изменился, принадлежит другой папке/ветке или отсутствует, статус будет
`stale`/`unverified`; его нужно создать и импортировать заново.

**Важное правило ranking:** ни один optional adapter сам по себе не меняет
canonical graph, risk, top-impact ranking или test recommendation. Он добавляет
контекст и evidence для Architecture/Inspect/Investigate. Это защищает review
от ложного повышения риска из-за устаревшего внешнего graph или trace.

### 5.2. Матрица адаптеров

| Адаптер | Что подключается | Когда нужен | Что добавляет | Как подключить |
|---|---|---|---|---|
| Graphify | `graph.json` из Graphify | Architecture exploration, module/community view | Supplemental architecture nodes/edges и provenance | `adapters import ... graphify <graph.json> --enable` |
| CodeGraph | JSON export CodeGraph | Совместимость с внешним graph tool | Normalized external graph overlay | `adapters import ... codegraph <graph.json> --enable` |
| LSP | Явно выбранный local language server | Go to definition, references, symbols, implementations | Bounded semantic locations из живого language server | `adapters lsp configure ...` затем `probe/query` |
| SCIP | Локальный `.scip` index | Точная cross-file semantic navigation | Semantic symbols/references, stable index metadata | `adapters import ... scip <index.scip> --enable` |
| OpenAPI | JSON/YAML OpenAPI/Swagger spec | HTTP API contract review | Operations, routes, schemas и contract boundary | `adapters import ... openapi <spec.yaml> --enable` |
| AsyncAPI | JSON/YAML AsyncAPI spec | Queues, topics, events | Channels, messages, producer/consumer boundary | `adapters import ... asyncapi <spec.yaml> --enable` |
| OpenTelemetry | OTLP JSON или Jaeger JSON export | Incident/debugging/runtime path investigation | Observed services, spans, HTTP/database/queue context | `adapters import ... otel <trace.json> --enable` |
| CycloneDX | CycloneDX JSON SBOM | Dependency inventory, supply-chain context | Components, versions, licenses, dependency facts, known findings из report | `adapters import ... cyclonedx <bom.json> --enable` |
| SPDX | SPDX JSON SBOM | Организации, использующие SPDX | Package/license/dependency evidence | `adapters import ... spdx <sbom.json> --enable` |
| SARIF | SARIF 2.1 `.sarif`/`.json` | Security scan context | Rule ID, severity, safe file/range finding | `adapters import ... sarif <scan.sarif> --enable` |
| Joern | CodeSlicer Joern interchange JSON либо конвертированный GraphSON/CPGQL export | Глубокий C/C++/Java security/data-flow анализ | CPG, dangerous calls, bounded taint/data-flow paths | `adapters joern convert ...`, затем import/enable |

### 5.3. LSP: особый тип интеграции

LSP — не artifact. Пользователь сам выбирает исполняемый сервер и разрешённые
workspace roots. Пример Python/Pyright на Windows:

```powershell
impact-engine --json adapters lsp configure $project `
  --executable 'C:\Users\<user>\AppData\Roaming\npm\pyright-langserver.cmd' `
  --workspace-root $project --arg=--stdio

impact-engine --json adapters lsp probe $project
impact-engine --json adapters lsp query $project `
  --method definition --file src\module.py --line 12 --character 8
```

CodeSlicer открывает короткоживущий subprocess только для explicit probe/query.
Выбранный документ может быть передан этому локальному server через LSP
`didOpen`, чтобы сервер смог построить semantic response; CodeSlicer хранит
только нормализованные locations, не исходный текст. Server не sandboxed:
CodeSlicer сам не создаёт network transport, но пользователь должен доверять
выбранному executable.

### 5.4. SCIP: semantic index

SCIP создаётся внешним indexer для конкретного состояния проекта, затем
импортируется как immutable local artifact. Пример для TypeScript:

```powershell
scip-typescript index --cwd $project --infer-tsconfig `
  --output "$project\.codeslicer-e2e.scip" --no-progress-bar

impact-engine --json adapters import $project scip `
  "$project\.codeslicer-e2e.scip" --enable
```

После смены source/Git revision индекс следует пересобрать. SCIP особенно
полезен, когда static extractor видит structural imports, но нужна более
точная symbol-level navigation.

### 5.5. Joern: heavy security adapter

Joern нужен только для явного deep investigation C/C++/Java. Он не
устанавливается, не запускается и не скачивается CodeSlicer автоматически.
Пользователь подготавливает CPG/GraphSON или CPGQL JSON локально; bridge
конвертирует экспорт в ограниченный interchange, который затем импортируется.

```powershell
impact-engine adapters joern convert C:\local\joern-graphson.json `
  --project $project --output C:\local\joern-interchange.json

impact-engine --json adapters import $project joern `
  C:\local\joern-interchange.json --enable
```

Он полезен для taint path, dangerous call и data-flow контекста. Простая
графовая достижимость не считается доказанной уязвимостью; неполные locations,
stale artifact и incomplete export остаются likely/unresolved.

## 6. Поддержка библиотек и support packs

Support packs изолируют language/framework/library правила от основного graph
ядра. Они добавляют проверяемые resolver patterns и attribution, а не должны
встраивать project-specific исключения в generic pipeline.

Команды `libraries detect` и `libraries research` помогают найти неизвестную
библиотеку, подготовить evidence-gated research input и при явном разрешении
создать draft/staged support pack. `--allow-network` — отдельный opt-in:
обычный анализ не ищет сведения в интернете и не отправляет исходный код.

## 7. Privacy, trust и статусы

### 7.1. Local-first граница

- Core graph, cache, artifacts и localhost API остаются на машине.
- Artifact adapters принимают только absolute local path.
- Raw внешние artifact payloads санитизируются; хранятся разрешённые поля,
  fingerprint и bounded provenance, а не arbitrary secrets/headers/source text.
- Никакой telemetry, upload или скрытый cloud endpoint для обычного анализа не
  требуется.
- Явный `libraries research --allow-network` и пользовательский LSP executable
  являются исключениями, которые должны быть осознанно выбраны пользователем.

### 7.2. Значение статусов

| Статус | Значение и действие |
|---|---|
| `disabled` | Adapter доступен, но не подключён. |
| `imported` | Локальный artifact сохранён и валиден, но ещё выключен. |
| `ready` | Artifact/process доступен и freshness прошёл проверку. |
| `stale` | Source artifact или Git context изменились; нужно re-import/re-index. |
| `unverified` | Происхождение или project context нельзя безопасно проверить. |
| `incomplete` / `unsupported` | Формат или покрытие недостаточны; overlay не должен считаться доказательством. |
| `error` | Некорректный artifact/configuration; смотреть diagnostics. |

## 8. Что уже проверено в этом окружении

Это не маркетинговое обещание, а фактическая матрица выполненных проверок.

| Возможность | Проверка |
|---|---|
| Core Python graph/review | Реальный JunMate, включая review и Graphify artifact isolation. |
| Core TypeScript graph/review | Реальный JevioFuseHack; coverage/warnings честно отражаются в review. |
| C# structural graph | Реальный backend Cruxa; C# отображается с `limited` coverage. |
| Graphify | Реальный local Graphify output на JunMate, import/enable/disable без изменения review ranking. |
| CycloneDX | Реально сгенерированный JunMate SBOM, import/enable, 64 components. |
| LSP | Реальный Pyright на CodeSlicer: probe и cross-file definition query. |
| SCIP | Реальный `scip-typescript 0.4.0` index JevioFuseHack: protobuf decode и `ready/fresh`. |
| SARIF, CodeGraph, OpenAPI, AsyncAPI, OTel, SPDX | Parser/import/enable/status/API regression на versioned valid fixtures. Реальные producer tools/artifacts этих типов ещё не запускались на corpus. |
| Joern | Adapter/bridge regression есть, но настоящий Joern execution заблокирован текущим WSL/Docker environment. |

## 9. Реалистичные границы

CodeSlicer не должен восприниматься как абсолютный oracle:

- reflection, metaprogramming, generated proxies, dynamic DI и dynamic dispatch
  могут скрыть реальные связи;
- runtime trace доказывает только наблюдённый сценарий;
- SBOM/SARIF/contract/Graphify overlay не заменяют canonical static evidence;
- C# без compiler binding и Java/Go/TS framework patterns могут быть limited;
- отсутствующая test recommendation означает «не найдено достаточно evidence»,
  а не «тест не нужен»;
- пустой Joern/SARIF/OTel результат не означает, что production безопасен или
  не содержит других путей.

Правильный рабочий принцип: использовать CodeSlicer для быстрого,
объяснимого narrowing области проверки; затем открыть evidence, выполнить
рекомендованные тесты и принять инженерное решение.

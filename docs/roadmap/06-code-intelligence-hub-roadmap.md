# CodeSlicer Code Intelligence Hub — последовательный roadmap

## Цель

Превратить CodeSlicer из локального impact-анализатора в local-first hub для review, исследования архитектуры, semantic navigation, runtime evidence, security и CI. Ядро CodeSlicer остаётся владельцем canonical evidence graph, ranking, confidence и privacy boundary. Внешние инструменты подключаются только как опциональные adapters/overlays.

Порядок этапов намеренно строгий: localhost и единый контракт должны появиться раньше VS Code, CI и тяжёлых graph engines. Нельзя переносить business logic в extension или дублировать ranking в каждом интерфейсе.

## Базовые принципы

- Local-first: код, graph и артефакты остаются на машине пользователя по умолчанию.
- Любое сетевое действие, telemetry или внешний endpoint требует явного opt-in.
- Языковые plugins, framework support packs и external adapters изолированы друг от друга.
- Внешний факт хранит adapter, версию, источник, confidence, freshness и локальную ссылку на артефакт.
- `DOC_INFERRED` или name-only связь не может автоматически стать `confirmed`.
- Качество измеряется top-5 precision, top-10 recall, точностью рекомендаций тестов и временем принятия решения, а не количеством graph nodes.

## Целевая схема

```text
Localhost / VS Code / MCP / CI
              │
CodeSlicer canonical evidence graph + review ranking
              │
 ┌────────────┼───────────────────────────────────────┐
 │ language plugins │ semantic │ runtime │ security   │
 │ Python/TS/C#     │ SCIP/LSP │ OTel    │ SARIF      │
 └──────────────────┴──────────┴─────────┴────────────┘
              │
Graphify · OpenAPI/AsyncAPI · SBOM · CodeGraph · Joern
```

---

## Этап 1. Зафиксировать публичный контракт и границы данных

**Цель.** Создать единый versioned contract для CLI, MCP, local API, frontend, будущего VS Code и CI.

**Работы.**

1. Зафиксировать режимы `review`, `inspect`, `investigate`, `ci` и общий ответ `CodeSlicerModeContract/v2`.
2. В каждый ответ добавить `freshness`, `coverage`, `adapters`, `privacy`, `warnings`.
3. Сделать единый project-local storage: `.codeslicer/config.json`, `cache/`, `artifacts/`, `adapters/`, `history/`, `logs/`.
4. Описать правила локального запуска, opt-in сети, retention и redaction.
5. Версионировать GraphDocument и overlay schema; задать compatibility policy.

**Затрагиваемые зоны.** `src/impact_engine/modes.py`, `local_api.py`, CLI/MCP serializers, `frontend/`.

**Готово, когда.** CLI, MCP, API и UI принимают один контракт; stale cache и неполный coverage видны всегда; adapter не может молча использовать сеть.

---

## Этап 2. Сделать localhost основным ежедневным UX

**Цель.** Превратить имеющиеся `/api/review`, `/api/inspect`, `/api/investigate` и `frontend/` в практичный локальный продукт.

**Работы.**

1. Экран Review: risk, максимум 10 сущностей, targeted tests, 2–3 evidence chains, coverage/freshness.
2. Экран Inspect: symbol details, incoming/outgoing evidence, usages, implementations, tests, routes и DB boundaries.
3. Экран Investigate: bounded deep subgraph, filters, path finder, max nodes/edges и export only by user action.
4. Добавить действия `Why affected?`, `Open chain`, `Run test locally`, `Ignore with reason`, `Refresh cache`.
5. Не показывать built-ins, assignment nodes, node_modules и внешние библиотеки в default view.
6. Сделать status bar: текущий project, cache status, language coverage, активные adapters, local-only indicator.

**Готово, когда.** Перед commit разработчик получает объяснимый bounded review без терминала; deep graph доступен отдельно; UI честно сообщает unsupported language, generated files и stale cache.

---

## Этап 3. Ввести Adapter SDK и registry

**Цель.** Не смешивать Graphify, SCIP, OTel, CodeQL и будущие интеграции с ядром.

**Работы.**

1. Добавить `plugins/adapters/<adapter_id>/` рядом, но отдельно от `plugins/languages/`.
2. Описать `adapter-manifest.schema.json`: execution mode, network policy, inputs, outputs, evidence class, resource profile и license metadata.
3. Описать `evidence-overlay.schema.json`.
4. Ввести evidence classes: `STATIC_EXTRACTED`, `SEMANTIC_INDEX`, `CONTRACT_CONFIRMED`, `RUNTIME_OBSERVED`, `SECURITY_FINDING`, `DOC_INFERRED`, `USER_ASSERTED`.
5. Добавить enable/disable, health, freshness, budget и audit log для каждого adapter.

**Целевая структура.**

```text
plugins/
  languages/{python,typescript,csharp}/
  adapters/{graphify,scip,lsp,otel,sarif,openapi,cyclonedx,codegraph,joern}/
  contracts/{adapter-manifest,evidence-overlay}.schema.json
```

**Готово, когда.** Новый adapter добавляется без изменения ranking core; его можно отключить без повреждения canonical graph; provenance виден в UI.

---

## Этап 4. Формализовать Graphify как Architecture overlay

**Инструмент.** [Graphify](https://github.com/Graphify-Labs/graphify).

**Цель.** Использовать уже имеющийся Graphify adapter и `visualize-compare` для architecture exploration, а не для default impact ranking.

**Работы.**

1. Перевести текущий import Graphify на Adapter SDK, не переписывая extractor.
2. Хранить output изолированно в `.codeslicer/artifacts/graphify/`.
3. Явно различать Graphify `EXTRACTED`, `INFERRED` и `AMBIGUOUS` связи.
4. Добавить экран Architecture: communities, module map, docs-to-code context, bridges.
5. Добавить режимы `CodeSlicer only`, `Graphify overlay`, `Combined`.
6. Запретить Graphify inferred edges повышать risk без независимого подтверждения.
7. Отключить/проверить telemetry по умолчанию.

**Корпус.** [JevioFuseHack](https://github.com/theJorDea/JevioFuseHack), [mamAI](https://github.com/VladimirMyasnikov/mamAI), CodeSlicer.

**Готово, когда.** Architecture view даёт communities вместо тысяч nodes, Review остаётся компактным, а пользователь видит происхождение любой overlay-связи.

---

## Этап 5. Добавить SCIP semantic index

**Инструмент.** [Sourcegraph SCIP](https://sourcegraph.com/docs/code-navigation/writing-an-indexer).

**Цель.** Повысить точность definitions, references, implementations и stable symbol identity.

**Работы.**

1. Реализовать `plugins/adapters/scip/` и import локального `.scip`.
2. Сопоставить SCIP symbol IDs с canonical CodeSlicer nodes и source ranges.
3. Хранить commit/index timestamp; stale index не повышает confidence.
4. Сделать fresh SCIP evidence `SEMANTIC_INDEX/confirmed`.
5. Добавить в Inspect ссылки на confirmed references/definitions/implementations.
6. Начать с TypeScript, C#, Python, затем Go и Java.

**Корпус.** [JevioFuseHack](https://github.com/theJorDea/JevioFuseHack), [Cruxa](https://github.com/contr4s/Cruxa), [JunMate](https://github.com/AlekseyYudin-161/JunMate).

**Готово, когда.** Rename-like и interface→implementation сценарии дают реальные usages, а не name-only matches; top-5 precision не ухудшается.

---

## Этап 6. Добавить LSP live semantic layer

**Инструмент.** [Language Server Protocol](https://microsoft.github.io/language-server-protocol/).

**Цель.** Точно исследовать незакоммиченную рабочую копию без полного rebuild.

**Работы.**

1. Реализовать `plugins/adapters/lsp/` с local subprocess/capability detection.
2. Поддержать tsserver, Pyright, Roslyn, gopls и JDT LS по мере готовности.
3. Поддержать `definition`, `references`, `implementation`, `callHierarchy`, `typeHierarchy`.
4. Вызывать LSP только по действию пользователя, при недостатке confidence или для changed symbol.
5. Добавить timeout, cancellation, local cache и diagnostics.
6. При отсутствии server показывать capability gap, не ломая Review.

**Готово, когда.** `Resolve precisely` работает для dirty files; failure language server не ломает core и не требует сети.

---

## Этап 7. Подключить runtime evidence через OpenTelemetry

**Инструмент.** [OpenTelemetry](https://opentelemetry.io/docs/).

**Цель.** Отделить потенциальный impact от реально наблюдаемого production/test path.

**Работы.**

1. Реализовать `plugins/adapters/otel/` и local import OTLP JSON/Protobuf.
2. Нормализовать HTTP routes и связывать client/server/DB/queue spans с graph nodes.
3. Хранить calls, error rate, duration, last observed, но не request bodies, secrets, cookies или персональные данные.
4. В Review показывать компактную runtime summary; полный trace — только в Runtime/Investigate.
5. Сделать redaction rules, retention и freshness warnings.

**Корпус.** [Cruxa](https://github.com/contr4s/Cruxa), [mamAI](https://github.com/VladimirMyasnikov/mamAI), local HTTP+DB+queue demo.

**Готово, когда.** Runtime edge помечен отдельно от static edge, влияет на приоритет только с объяснимыми метриками и импортируется без внешней передачи данных.

---

## Этап 8. Подключить contracts: OpenAPI и AsyncAPI

**Инструмент.** [OpenAPI Specification](https://spec.openapis.org/oas/).

**Цель.** Подтвердить frontend↔backend и service↔service boundaries формальным контрактом.

**Работы.**

1. Реализовать `plugins/adapters/openapi/` для JSON/YAML.
2. Добавить AsyncAPI для queues/events.
3. Сопоставить operationId, route, controller/minimal API handler, TypeScript client и DTO/schema.
4. Реализовать contract diff: removed fields, new required fields, enum/status-code changes.
5. Показать consumers, impacted contract tests и breaking-change risk.

**Корпус.** [Cruxa](https://github.com/contr4s/Cruxa), [nutrition-bot-kodik-hackathon](https://github.com/TaggedDev/nutrition-bot-kodik-hackathon), [Pixel Compressor](https://github.com/RuslanLat/pixelcompressor).

**Готово, когда.** API impact подтверждается contract evidence, а отсутствие спецификации отображается как coverage gap.

---

## Этап 9. Добавить security и supply-chain overlays

**Инструменты.** [CodeQL](https://codeql.github.com/docs/), [Semgrep](https://semgrep.dev/docs/category/local-and-cli-scans), [Trivy](https://github.com/aquasecurity/trivy), [CycloneDX](https://cyclonedx.org/specification/overview/).

**Цель.** Связать code/security/dependency risk, не смешивая его с обычным impact closure.

**Работы в порядке выполнения.**

1. Реализовать universal `plugins/adapters/sarif/`.
2. Подключить Semgrep как быстрый local rule scanner.
3. Подключить Trivy для dependencies, secrets, IaC, Docker и images.
4. Импортировать CycloneDX/SPDX для package→service→image mapping.
5. Подключить CodeQL через SARIF для глубоких dataflow findings.
6. Создать отдельный Security screen и CI policies.

**Готово, когда.** SARIF — единая точка входа; finding ведёт к коду и evidence path; security risk отображается отдельно от change risk.

---

## Этап 10. Подключить CodeGraph как optional query provider

**Инструмент.** [CodeGraph](https://github.com/colbymchenry/codegraph).

**Цель.** Получать быстрый дополнительный semantic/call-path context без замены canonical graph.

**Работы.**

1. Реализовать MCP/query bridge, а не raw full-graph importer.
2. Запрашивать только narrow context: references, definitions, call path, module context.
3. Сохранять ответ с `source=codegraph`, version и freshness.
4. Не позволять CodeGraph автоматически повышать риск до confirmed без promotion rule.
5. Проверить и отключить telemetry по умолчанию.

**Готово, когда.** Agent/Investigate получает быстрый fallback context, но Review не становится зависимым от CodeGraph.

---

## Этап 11. Добавить тяжёлые investigation adapters: Joern и Kythe

**Инструменты.** [Joern](https://docs.joern.io/code-property-graph/), [Kythe](https://kythe.io/docs/).

**Цель.** Открыть C/C++, compile-aware indexing, generated code и security dataflow без утопления daily UX.

**Работы.**

1. Joern запускается только через `Investigate → Run deep dataflow`, с budget/cancellation.
2. Импортировать только выбранные paths/findings, не весь CPG в canonical graph.
3. Kythe рассматривать для Bazel/Java/C++/generated-code проектов и kzip inputs.
4. Показать resource estimate, license metadata и явное согласие на heavy execution.

**Готово, когда.** Heavy analysis opt-in, отменяемый, объяснимый и не влияет на P0 Review latency.

---

## Этап 12. Product polish localhost: design system, graph UX и pixel identity

**Цель.** Сделать интерфейс узнаваемым, дружелюбным и быстрым, не превращая серьёзный анализатор в декоративную игру.

**Работы.**

1. Добавить design tokens, светлую/тёмную темы, accessible contrast и keyboard navigation.
2. Ввести graph levels: Review graph, Impact chain, Architecture map, bounded Deep graph.
3. Для large graph использовать aggregation/communities и Canvas/WebGL; не рисовать тысячи DOM/SVG nodes.
4. Добавить пиксельных персонажей только для onboarding, empty state, analysis progress, cache repair и success state.
5. Добавить `prefers-reduced-motion` и переключатель анимаций.
6. Ограничить transition animation 150–250 ms; никогда не скрывать high-risk status декоративным motion.
7. Тестировать browser performance и визуальную читаемость на больших graph.

**Готово, когда.** UI помогает принять решение быстрее; анимации optional; large graph остаётся responsive; visual style не мешает профессиональному сценарию.

---

## Этап 13. Выпустить VS Code extension как тонкий клиент

**Цель.** Дать разработчику CodeSlicer в привычном editor, не создавая второй analyzer/cache/ranker.

**Работы.**

1. Создать `integrations/vscode/`.
2. Extension обнаруживает workspace и подключается к local daemon/API; при необходимости запускает его локально.
3. Добавить команды: `Review Current Changes`, `Explain Impact`, `Investigate Symbol`, `Run Recommended Test`, `Refresh Analysis`, `Configure Adapters`.
4. Добавить CodeLens: impacted symbols, recommended tests, why affected.
5. Добавить diagnostics: high-risk contract change, stale index/cache, partial C# coverage, generated file excluded.
6. Добавить side panel, использующий тот же mode contract, что localhost.
7. Дать пользователю выбор: встроенный Webview или открытие localhost в браузере.

**Готово, когда.** Результат Review идентичен localhost; extension работает offline; не имеет отдельного graph cache; `Why affected?` ведёт к evidence chain.

---

## Этап 14. CI, PR workflow и release readiness

**Цель.** Сделать CodeSlicer пригодным для командного применения и надёжных релизов.

**Работы.**

1. `impact-engine ci` выдаёт JSON, SARIF, Markdown summary и объяснимые exit codes.
2. Добавить GitHub/GitLab PR comments: risk, top impact, recommended tests, coverage/freshness.
3. Ввести policy gates: breaking contract без targeted test, high severity finding, migration без test, stale required graph.
4. Не вводить policy по числу graph nodes.
5. Добавить release checklist: full regression, corpus regressions, performance SLO, schema compatibility, privacy audit, adapter matrix, changelog, rollback plan.
6. Версионировать GraphDocument и adapter schemas; публиковать compatibility/migration notes.

**Готово, когда.** CI работает без UI, PR summary компактный, SARIF совместим со стандартными security tools, а policy можно объяснить и подавить только с reason.

---

## Corpus и регрессионная стратегия

Полные внешние репозитории хранить только как локальный, Git-ignored corpus, например `external_tools/corpus/`; не коммитить их копии без проверки лицензии, размера и необходимости.

| Corpus | Роль |
|---|---|
| [JunMate](https://github.com/AlekseyYudin-161/JunMate) | быстрые Python golden scenarios и Review UX |
| [mamAI](https://github.com/VladimirMyasnikov/mamAI) | large Python, incremental performance, large graph |
| [JevioFuseHack](https://github.com/theJorDea/JevioFuseHack) | TypeScript noise/ranking/test-selection regression |
| [Cruxa](https://github.com/contr4s/Cruxa) | React + .NET, C#, routes, DI, EF, API boundaries |
| [nutrition-bot-kodik-hackathon](https://github.com/TaggedDev/nutrition-bot-kodik-hackathon) | второй независимый .NET + React acceptance corpus |
| [pixelcompressor](https://github.com/RuslanLat/pixelcompressor) | TypeScript monorepo и package boundaries |
| [ImpactLens](https://github.com/BEVALERY-Solutions/impactlens) | сравнительный baseline компактного impact review |
| [CodeSlicer](https://github.com/artemnoor/CodeSlicer) | dogfooding CLI/MCP/plugin/adapter boundaries |

Каждый fixture должен задавать `change → expected top-5 → expected tests → expected explanation chain`, а не только ожидаемое число nodes.

## Критические зависимости

1. Этапы 1–3 обязательны до любого external adapter.
2. Этап 2 обязателен до pixel polish и VS Code.
3. Этапы 5–8 повышают точность Review; они важнее Joern/Kythe.
4. Этап 12 не должен блокировать функциональные этапы.
5. Этап 13 использует localhost/API, а не дублирует core.
6. Этап 14 начинается после стабилизации schema, adapters и corpus regression suite.

## Главные риски

- Смешивание внешних inferred edges с confirmed core evidence приведёт к росту false positives.
- Раннее добавление heavy tools (Joern, CodeQL) может ухудшить UX и latency.
- Несвежие SCIP/OTel/SARIF artifacts создадут ложное чувство точности без строгого freshness model.
- UI, extension и CI разойдутся, если появятся разные ranking implementations.
- Пиксельная анимация может вредить accessibility и performance, если станет частью основного рабочего потока.

## Visual Intelligence Hub — localhost increment

Текущий localhost UX объединяет четыре изолированных режима: Review,
Inspect, Investigate и Architecture. Главный экран показывает health summary
проекта (freshness, coverage, cache/daemon и excluded generated/vendor paths)
и действия, доступные прямо сейчас. Graph projection progressive: structural
overview modules/files загружается bounded, symbols/edges — только после
явного действия и фильтрации.

API `/api/overview` и `/api/graph/projection` возвращают bounded machine-readable
status/freshness/coverage/diagnostics/privacy/evidence_sources. Canonical
CodeSlicer graph и его ranking не меняются; Graphify, CodeGraph, SCIP, LSP,
OTel, Boundary и Security/SBOM остаются supplemental overlays с provenance и
видимым ограничением `ranking: none`.

Следующий отдельный этап — Joern/CPG как heavy opt-in adapter. Он должен
подключаться только из Investigate, иметь budget/cancellation и bounded
projection, не запускаться автоматически и не влиять на canonical graph или
Review ranking. В текущем Visual Intelligence Hub Joern не реализован.

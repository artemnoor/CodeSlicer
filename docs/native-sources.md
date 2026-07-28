# Нативные источники CodeSlicer

CodeSlicer не встраивает исходники Graphify, CodeGraph, Gortex или Joern в
свой canonical impact graph. Каждый инструмент остаётся отдельной opt-in
локальной зависимостью со своим форматом данных, индексом, лицензией и
специализированными запросами. Это исключает ложное смешение доказательств.

## Что делает CodeSlicer

`impact-engine adapters native <project> <adapter> profile --json` показывает
полный каталог возможностей и доступность локального executable. Команда не
запускает инструмент и не читает исходный код проекта.

Операции, которые индексируют проект или создают состояние внешнего
инструмента, требуют `--confirm`:

```powershell
impact-engine adapters native C:\project graphify index --confirm
impact-engine adapters native C:\project codegraph index --confirm
impact-engine adapters native C:\project gortex index --confirm
```

Запросы передаются в subprocess как аргументы, а не через shell. Вывод
ограничен, time-out ограничен 60 секундами. CodeSlicer не открывает сеть, но
не может гарантировать сетевое поведение явно запущенного внешнего процесса;
UI и API показывают это до подтверждения.

## Нативные рабочие пространства

| Source | Задача | Native actions |
| --- | --- | --- |
| Graphify | Архитектура, communities, документация, ADR | extract/update/query; затем импорт `graphify-out/graph.json` при необходимости визуального bridge |
| CodeGraph | Символы, semantic context, callers/callees, impact, tests | index/sync/status/query/context/impact/callers/callees/affected |
| Gortex | Multi-repo, contracts, processes, communities, health | index/status и query: `symbol:`, `deps:`, `dependents:`, `callers:`, `calls:`, `implementations:`, `usages:`, `stats:` |
| Joern | CPG/data-flow/security | QueryDB recipe catalogue; полный CPG и запросы остаются тяжёлым отдельным security workspace |
| LSP/SCIP | Живая и индексная семантика | Явно настроенный local LSP и artifact/indexer lifecycle; capability negotiation обязательна |
| OpenAPI/AsyncAPI | API/event contracts | Локальный import, diff/coverage workbench; никакие URL/broker не запрашиваются автоматически |
| OpenTelemetry | Runtime evidence | Локальный OTLP/Jaeger artifact import; runtime data не повышают PR risk автоматически |
| CycloneDX/SPDX/SARIF | Supply chain и scanner findings | Локальный import и независимый security workspace |

## Границы доверия

1. Canonical graph CodeSlicer владеет review ranking, risk и test
   recommendations.
2. Внешний source graph владеет своими нативными данными и запросами.
3. Bridge graph содержит только доказуемые соответствия между двумя графами.
4. Внешний результат не становится canonical evidence без отдельного,
   проверяемого правила сопоставления.
5. Gortex нельзя vendor-ить в продукт без отдельной лицензионной проверки.

## Что ещё потребуется для абсолютного покрытия upstream-функций

Нативные команды и capability catalogue уже дают честную точку входа. Полное
использование каждого upstream API требует отдельных совместимых версий
инструментов и e2e-корпуса: persistent LSP sessions, language-specific SCIP
indexers, Graphify MCP, CodeGraph MCP, Gortex multi-repo daemon/API, Joern
CPGQL/QueryDB, а также contract/runtime/security workbenches. Эти подсистемы
нельзя подменять импортом JSON и нельзя безопасно включать молча.

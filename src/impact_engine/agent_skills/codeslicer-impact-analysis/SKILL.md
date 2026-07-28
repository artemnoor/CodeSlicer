---
name: codeslicer-impact-analysis
description: Evidence-gated анализ влияния изменений: статусы проекта, bounded review, inspect, investigate, Git diff и targeted tests.
---

# CodeSlicer: точный анализ влияния

Используйте этот skill для изменений, PR, рефакторинга, поиска затронутого кода и выбора тестов. CodeSlicer — источник canonical evidence; он различает `confirmed`, `likely` и `unresolved`.

## Рабочий порядок

1. Вызовите `project_status`. Если граф отсутствует, сначала `scan_plan`, затем `analyze_project`.
2. Для diff/ветки начните с `review(project_path, max_results=10)`. Это компактная decision-проекция, а не полный технический closure.
3. Для важной сущности вызовите `inspect`: в ответе должны быть причина, evidence, coverage и рекомендации тестов.
4. Только при вопросе о глубокой цепочке используйте `investigate` с ограниченными `depth`, `max_nodes`, `max_edges`.
5. Для двух точных символов используйте `impact_path` и `explain_edge`; для неоднозначного имени обработайте `needs_selection`.

## Git и тесты

- `review` и `ci(run_tests=false)` только анализируют diff и подбирают тесты.
- Показывайте top-5/top-10, уровень риска, причины и рекомендуемые тесты. Не оценивайте качество по количеству nodes.
- Прежде чем реально запускать тесты, покажите команду и получите явное согласие владельца. В MCP вызов `ci(run_tests=true)`, `runtime_trace` или `investigate(runtime_validate=true)` без credentials вернёт `pending_approval`; после локального подтверждения повторите тот же вызов с токеном.

## Правила достоверности

- Не показывайте assignments, built-ins, внешние библиотеки и speculative edges в default review, если они не несут объяснения риска.
- Отдельно сообщайте языки/части проекта с limited или unsupported coverage.
- Если traversal ограничен budget или truncated, это ограничение результата, а не отрицательное доказательство связи.

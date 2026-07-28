---
name: project-onboarding-workflow
description: Подключает локальный проект или явно одобренный Git URL, строит отдельные Graphify и CodeSlicer графы и ведёт через архитектуру, изменение, Git review и тесты.
---

# Новый проект / подключить проект

## Безопасный старт

1. Для локальной папки: `scan_plan` → покажите stack, scope, manifests и оценку. Затем `onboard(source=<folder>, graphify_mode="off")` или `analyze_project` с budget.
2. Для Git URL вызовите `onboard(..., allow_network=true)`. Первый вызов вернёт `pending_approval` с точным clone request. Пользователь локально подтверждает его, после чего повторите тот же вызов с `approval_id` и `approval_token`.
3. Сразу после анализа вызовите `project_status`. Сообщите путь canonical graph, языковое coverage и ограничения.

## Два независимых графа

- **Graphify**: по желанию запускается для широкой карты, communities, ADR и документации. Его artefact хранится отдельно; подключение или запуск также сначала возвращает `pending_approval`.
- **CodeSlicer**: строит canonical evidence graph для impact, PR risk, explain chains и targeted tests.
- Никогда не выдавайте Graphify links за подтверждённые CodeSlicer edges и не подменяйте ими risk ranking.

## Единый сценарий разработки

1. Graphify: понять архитектуру и найти область работы.
2. CodeSlicer `inspect`: понять конкретный символ и его доказательства.
3. Внести изменение обычными средствами разработки.
4. CodeSlicer `review(max_results=10)`: проверить Git diff, риск, coverage и тесты.
5. При спорном результате — `investigate` с явными limits; при runtime validation/tool execution — получить approval и повторить точный вызов после подтверждения.

Если имя символа неоднозначно, обработайте `needs_selection`. Если анализ упёрся в budget или coverage, зафиксируйте это как ограничение и предложите следующую локальную проверку.

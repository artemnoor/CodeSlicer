---
name: codeslicer-impact-analysis
description: Evidence-gated статический анализ влияния изменений, PR-review, оценки рисков, поиска затронутых тестов и глубокого исследования цепочек вызовов.
---

# Скилл 1: CodeSlicer Impact Analysis (Точный граф влияния)

Этот скилл применяется, когда задача требует воспроизводимого анализа влияния. Он опирается на evidence и confidence, но не обещает абсолютную точность: динамические зависимости, неподдержанный язык и неполное покрытие остаются в диагностике.

## Основные назначения скилла
- Анализ влияния рефакторинга (`impact_query`).
- Оценка рисков Pull Request (`pr_review`).
- Автоматический подбор минимально необходимого набора тестов (`linked_tests`).
- Разбор строгих доказательств связей (`explain_edge`).

---

## Порядок работы Агента

### 1. Первичная инвентаризация и граф (при необходимости)
Если граф проекта не построен или устарел:
```bash
impact-engine analyze <path_to_project> --use-scan-plan
```
Или вызовите MCP-инструмент `analyze_project`.

### 2. Исполнение Impact Query
Для поиска цепочек влияния вызовите MCP-инструмент `impact_query` или CLI:
```bash
impact-engine --json impact <graph.json> --symbol "<TargetSymbol>" --direction both
```
**Допустимые направления**:
- `upstream` — кто зависит от данного символа (что сломается выше).
- `downstream` — от кого зависит данный символ (что ему нужно ниже).
- `both` — полный вектор связей.

### 3. Выполнение PR-Review
При проверке Git diff или PR вызовите MCP `pr_review` или CLI:
```bash
impact-engine --json pr-review <path_to_project> --graph <graph.json> --diff-file <diff.patch>
```
Ответ возвращает:
- `risk.level`: `LOW` | `MEDIUM` | `HIGH` | `CRITICAL`.
- `test_recommendations`: список рекомендованных к запуску тестов.
- `breaking_contracts`: список нарушенных сигнатур.

### 4. Объяснение связи (Explain Edge)
Для получения строгой цепочки доказательств:
```bash
impact-engine explain-edge <graph.json> --from "<SymbolA>" --to "<SymbolB>"
```

---

## Правила взаимодействия
1. **Никаких выдуманных связей**: разделяйте `confirmed`, `likely` и `unresolved`; по умолчанию не выдавайте вероятную связь за подтверждённую.
2. **Результаты**: Указывайте пользователю точные файлы, строки и рекомендуемые тесты.

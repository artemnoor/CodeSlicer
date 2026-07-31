---
name: graphify-architecture-analysis
description: "Нативный Graphify для карты архитектуры, сообществ, документации и ADR; его отдельный граф не подменяет evidence CodeSlicer."
---

# Graphify: архитектурная карта

Применяйте Graphify для первого знакомства с репозиторием, групп модулей, community detection, документации и ADR. Его исходный artefact и визуализация остаются отдельными от canonical graph CodeSlicer.

## Порядок работы

1. Проверьте `project_status` и список подключённых tools/adapters.
2. Если Graphify ещё не построен, предложите нативный запуск `impact-engine adapters native <project> graphify index --confirm` или managed Graphify tool.
3. Запрашивайте темы/модули нативной командой Graphify и читайте его документы через managed-tool API, когда checkout подключён.
4. Импортируйте `graphify-out/graph.json` как supplemental overlay только по явному действию пользователя. Он расширяет навигацию и объяснения, но не меняет canonical ranking сам по себе.
5. Когда пользователь выбирает файл или символ на архитектурной карте, передавайте его в CodeSlicer `inspect`/`review` для доказуемого impact и тестов.

## Границы и approvals

Graphify может быть установлен, подключён и использован полностью как самостоятельный upstream-инструмент. Подключение/clone и запуск CLI — чувствительные действия: вызовите соответствующий managed MCP tool напрямую. Он вернёт `pending_approval` с точным запросом; после локального подтверждения повторите тот же вызов с credentials. Не формируйте approval payload вручную.

В ответах всегда подписывайте источник: `Graphify architecture context` либо `CodeSlicer canonical evidence`.

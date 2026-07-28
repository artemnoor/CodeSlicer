---
name: graphify-architecture-analysis
description: Анализ верхнеуровневой архитектуры, детекция сообществ (community detection), навигация по ADR, связям модулей и нативный запуск Graphify CLI.
---

# Скилл 2: Graphify Architecture Analysis (Архитектура & ADR)

Этот скилл применяется, когда задача требует **верхнеуровневого понимания структуры репозитория, поиска архитектурных сообществ или навигации по ADR/документации**.

## Основные назначения скилла
- Построение и просмотр граф-карт сообществ (Community Detection).
- Индексация архитектуры проекта нативным CLI Graphify.
- Поиск архитектурных документов (ADR) и связывание их с модулями.
- Поверхностный обзор незнакомого репозитория.

---

## Порядок работы Агента

### 1. Нативное индексирование проекта через Graphify CLI
Если пользователь хочет обновить архитектурную карту через отдельный инструмент Graphify:
```bash
impact-engine adapters native <path_to_project> graphify index --confirm
```
*Примечание*: Выполнение создаст или обновит локальный артефакт `graphify-out/graph.json`.

### 2. Запрос к архитектурному графу Graphify
Для выполнения нативного запроса к графу Graphify:
```bash
impact-engine adapters native <path_to_project> graphify query --query "<ArchitecturalConceptOrModule>" --confirm
```

### 3. Импорт и включение оверлея Graphify в карту CodeSlicer
Если требуется отобразить оверлей сообществ Graphify в общем веб-интерфейсе CodeSlicer:
```bash
impact-engine adapters import <path_to_project> graphify <path_to_project>/graphify-out/graph.json --enable
```

---

## Правила взаимодействия
1. **Изоляция доказательств**: Результаты Graphify используются для объяснения архитектуры, комьюнити и концепций модулей.
2. **Отображение пользователю**: Формируйте ответ в виде высокоуровневой карты кластеров (например, `Community: Core Services`, `Community: UI Components`), указывая привязанные ADR и документы.

# START HERE FOR ARTEM

Этот проект содержит готовую и полностью протестированную локальную версию **DI-aware Impact Engine v0.4** с CLI и MCP интерфейсами.

Важно: это уже рабочая локальная MVP/product baseline система для анализа проектов, но ещё не полностью автономный self-learning агент. Она умеет строить граф проекта, применять resolver и support packs, делать impact query и explain edge. Если библиотека неизвестна, система умеет создать research workflow/input для AI Library Researcher, но пока не вызывает LLM API сама и не устанавливает новые support packs без проверки.

## Быстрый Старт

### 1. Установка в систему
Установи проект в редактируемом (editable) режиме:
```bash
python -m pip install -e .
```
Это зарегистрирует глобальные консольные скрипты `impact-engine` и `impact-engine-mcp`.

### 2. Запуск тестов
Для запуска полного набора тестов (всего 189 тестов) выполни:
```bash
python -m pytest -ra
```

### 3. Использование CLI инструментов

#### Анализ проекта:
```bash
impact-engine analyze examples/golden_cases/python_di_basic --out graph.json
```

#### Запрос влияния (impact query):
Направление может быть `upstream` (влияющие), `downstream` (зависимые) или `both`:
```bash
impact-engine impact graph.json --symbol repositories.OrderRepository.save --direction upstream
```

#### Объяснение связи (explain edge):
```bash
impact-engine explain-edge graph.json --from services.OrderService.create_order --to repositories.OrderRepository.save
```

### 4. Запуск MCP Сервера (Stdio JSON-RPC 2.0)
Запусти сервер:
```bash
impact-engine-mcp
```
```powershell
@'
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
'@ | impact-engine-mcp
```
Это выведет JSON со списком всех 17 доступных инструментов (включая `analyze_project`, `impact_query`, `explain_edge`, `validate_support_pack`, `detect_unknown_libraries`).

## Что сейчас реально работает

- Анализ локального проекта через CLI.
- Анализ локального проекта через MCP stdio tool `analyze_project`.
- Python AST extractor + precision resolver для DI/self.attr/calls.
- Tree-sitter baseline extractor для Javascript, Typescript и Go.
- Normalizer в единый `GraphDocument`.
- Support pack registry и deterministic support-pack hooks.
- Impact query: upstream/downstream/both по symbol/file.
- Explain edge: confidence, source, evidence chain, reasoning steps.
- Unknown library detection.
- Research workflow для неизвестных библиотек.
- Validation/install для machine-readable `support_pack.json`.

## Что ещё НЕ полностью автоматическое

- Нет автоматического LLM API вызова.
- Нет бесконечного internet crawler.
- Нет гарантии 100% понимания любой библиотеки без support pack.
- Нет автоматического approve/install support pack без agent/human review.

То есть текущая система уже строит “нервную систему” проекта там, где хватает language extractor + resolver + support packs. Для неизвестных библиотек она готовит путь к расширению, но сам новый support pack пока должен быть сгенерирован/проверен отдельным AI researcher шагом.

## Можно ли сейчас тестировать на реальном проекте?

Да. Можно взять любой локальный Python/JS/TS/Go проект и прогнать его через CLI.

Минимальная проверка:

```powershell
impact-engine analyze C:\path\to\real_project --out real_project_graph.json
impact-engine detect-languages C:\path\to\real_project
impact-engine inventory C:\path\to\real_project
```

Потом выбери символ из графа или кода и проверь impact:

```powershell
impact-engine impact real_project_graph.json --symbol some.module.SomeClass.some_method --direction both --min-confidence 0.5
```

Если хочешь объяснить конкретную связь:

```powershell
impact-engine explain-edge real_project_graph.json --from some.source.Symbol --to some.target.Symbol
```

Если по inventory видно неизвестную библиотеку, можно создать research workflow:

```powershell
impact-engine research start C:\path\to\real_project --library unknown_library_name --ecosystem python
```

Через MCP отдельный tool `detect_unknown_libraries` доступен агентам напрямую.

Ожидания для реальных проектов:
- На Python DI/self.attr/calls результат должен быть наиболее точным.
- На JS/TS/Go сейчас будет baseline graph, не глубокая framework-магия для всех библиотек.
- Для FastAPI/React/dependency-injector работают текущие support-pack правила в пределах уже реализованных паттернов.
- Если проект использует неизвестную библиотеку, система должна обнаружить её как unknown и подготовить research workflow.

## Как проверить работоспособность локально
Вы можете запустить готовые сценарии приёмки:
```bash
# 1. Запуск тестов приёмки и упаковки
python -m pytest tests/test_acceptance.py tests/test_packaging.py -v

# 2. Ручной анализ golden case
python -m impact_engine.cli analyze examples/golden_cases/python_di_basic --out graph.json
python -m impact_engine.cli explain-edge graph.json --from services.OrderService.create_order --to repositories.OrderRepository.save
```
Все отчёты о покрытии и качестве доступны в папке `docs/`.

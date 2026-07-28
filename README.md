# CodeSlicer

**CodeSlicer** — локальная система анализа влияния изменений в коде.
Она строит граф проекта, сохраняет доказательства связей и показывает, что
нужно проверить после изменения файла, функции, сервиса или endpoint-а.

Внутреннее имя Python-пакета и команд — `impact_engine`.

> Сайт сломался, а причина потерялась между frontend, API, сервисами, базой и
> десятками AI-правок? CodeSlicer строит единый граф проекта, чтобы точно
> увидеть цепочку поломки, её последствия и нужные точки проверки.

Это не только инструмент для поиска багов. Граф помогает безопасно
рефакторить, проверять PR, выбирать тесты, понимать незнакомые codebase и
строить AI-агентов, которые видят структуру проекта и последствия своих
изменений, а не действуют вслепую.

![Семантический граф CodeSlicer](docs/images/codeslicer-hero.png)

## 🤖 Быстрый старт для AI-Агентов (Скиллы и Инструменты)

Если вы — **AI-агент** (Antigravity, Cursor, Windsurf, Claude), начните с двухуровневой схемы скиллов из директории `.agents/skills/`. Это инструкции репозитория, а не автоматически активируемая функция любого AI-клиента: подключите их способом, который поддерживает ваш клиент.

1. **Главный маршрутизатор (ЧИТАТЬ ПЕРВЫМ)**:
   - [`code-intelligence-orchestrator`](.agents/skills/code-intelligence-orchestrator/SKILL.md) — классифицирует запрос пользователя и выбирает между точным анализом вызовов и архитектурным обзором.
2. **Специализированные скиллы**:
   - 🚀 [`project-onboarding-workflow`](.agents/skills/project-onboarding-workflow/SKILL.md) — подключает папку или явно разрешённый Git URL, строит отдельные архитектурный и impact-графы, ведёт до review и подтверждённого запуска тестов.
   - 🎯 [`codeslicer-impact-analysis`](.agents/skills/codeslicer-impact-analysis/SKILL.md) — **CodeSlicer**: evidence-gated статический анализ влияния, оценка рисков PR и выбор тестов.
   - 🗺️ [`graphify-architecture-analysis`](.agents/skills/graphify-architecture-analysis/SKILL.md) — **Graphify**: отдельный инструмент для обзора архитектуры и сообществ.

При установке пакета эти skills также поставляются как `impact_engine/agent_skills/`; извлечь их путь можно через `importlib.resources`. Это делает инструкции доступными офлайн, но не отменяет необходимость явно зарегистрировать их в используемом AI-клиенте.

### 🌐 Интерфейсы взаимодействия (Web UI & MCP)
- **Веб-интерфейс**: Запуск через `impact-engine-local-api` ➔ откройте **`http://127.0.0.1:8001/`**.
  - В UI намеренно оставлены две понятные поверхности: интерактивная **карта CodeSlicer** для точных локальных связей и отдельный оригинальный viewer **Graphify** для архитектурного обзора. Graphify появляется только при наличии его собственного `graphify-out/graph.json` и не подменяет graph CodeSlicer.
- **MCP-сервер для ИИ**: Запуск через `impact-engine-mcp` или `python -m impact_engine.mcp.server`. Для нового проекта агент начинает с `scan_plan` или `onboard`, затем использует `analyze_project`, `review`, `inspect` и `investigate`. Полный список выдаёт MCP-метод `tools/list`.

Подробно о Graphify, SCIP/LSP, contracts, runtime и security sources без
смешения их evidence: [документ по интеграциям](docs/INTEGRATIONS.md).

## Содержание

- [Возможности](#возможности)
- [Как строятся связи](#как-строятся-связи)
- [Как агент работает с графом](#как-агент-работает-с-графом)
- [Быстрый старт](#быстрый-старт)
- [Анализ проекта](#анализ-проекта)
- [Визуальный интерфейс](#визуальный-интерфейс)
- [Интеграции и отдельные графы](docs/INTEGRATIONS.md)
- [Что изменено в этом релизе](#что-изменено-в-этом-релизе)
- [MCP](#mcp)
- [Неизвестные библиотеки](#неизвестные-библиотеки)
- [Персонализация для проекта](#персонализация-для-проекта)
- [PR-review](#pr-review)
- [Формат графа](#формат-графа)
- [Поддержка языков](#поддержка-языков)
- [Структура репозитория](#структура-репозитория)
- [Ограничения](#ограничения)
- [Разработка](#разработка)

## Как это работает

```mermaid
flowchart LR
  Project["Исходный проект"] --> Inventory["Inventory и scan-plan"]
  Inventory --> Extract["Extractors\nPython AST / Tree-sitter"]
  Extract --> Facts["Raw facts\nimports, calls, assignments, routes"]
  Facts --> Normalize["Normalization\ncanonical IDs и merge"]
  Normalize --> Bind["Semantic binding\nobject и endpoint flow"]
  Packs["Support packs\nобщие и project-local"] --> Bind
  Bind --> Resolve["Precision resolvers\nimports, DI, receivers, routes"]
  Resolve --> Guard["Quality guard\nprovenance, confidence, conflicts"]
  Guard --> Graph["GraphDocument\nузлы, рёбра, evidence"]
  Graph --> Queries["Impact / explain-edge / PR-review / UI"]
```

Экстракторы извлекают факты из исходного кода. Резолверы создают семантические
рёбра только при наличии цепочки доказательств. Неоднозначные и неподдержанные
случаи остаются в диагностике, а не превращаются в подтверждённые связи по
одному совпадению имени.

### Что хранится локально

```text
<project>/.impact_engine/
  graph.json                 итоговый GraphDocument
  facts.json                 кэш извлечённых фактов
  impact_registry.sqlite     локальный registry и история
  scan_plan.json             область анализа
  local_packs/               персональные правила конкретного проекта
  unknown_region_tasks.json  задачи на исследование пробелов
```

Исходный код и граф остаются на машине пользователя. Для базового анализа не
нужны облачная база, Supabase или внешний API.

## Как строятся связи

CodeSlicer не считает одинаковые имена доказательством связи. Для каждого
рёбра он стремится собрать воспроизводимую цепочку фактов.

```text
self.repository.save(order)
  -> assignment: self.repository = repository
  -> constructor parameter: repository: OrderRepository
  -> declaration: OrderRepository.save
  -> resolved CALLS edge с evidence и confidence
```

Типичные источники доказательств:

- import и alias resolution;
- assignment, field и parameter propagation;
- constructor и provider/DI bindings;
- return type и factory propagation;
- receiver identity и method lookup;
- HTTP method + canonical path для frontend/backend bridge;
- versioned support-pack rule с provenance.

Если доказательств недостаточно, результат помечается как `ambiguous`,
`unresolved`, `unsupported` или `suspicious`. Такая область может стать
задачей для AI research workflow, но AI не добавляет confirmed edge напрямую.

## Как агент работает с графом

```mermaid
sequenceDiagram
  participant Dev as "Разработчик или AI-агент"
  participant Engine as "CodeSlicer"
  participant Graph as "Локальный GraphDocument"
  participant Tests as "Тесты проекта"

  Dev->>Engine: "analyze project"
  Engine->>Graph: "строит граф и diagnostics"
  Dev->>Engine: "что затронет это изменение?"
  Engine->>Graph: "impact query + evidence paths"
  Engine-->>Dev: "must change / should review / uncertainty / tests"
  Dev->>Tests: "запускает выбранные тесты"
  Tests-->>Engine: "runtime observations (опционально)"
  Engine->>Graph: "сохраняет observation без переоценки фактов"
```

Агенту не нужно передавать весь репозиторий в контекст для каждого вопроса.
Он может запросить графовый срез: изменённый узел, кратчайшие evidence paths,
затронутые routes, сервисы и тесты. Это уменьшает лишний контекст и делает
его решения проверяемыми.

## Возможности

- инвентаризация проекта и детерминированный план области анализа;
- Python AST-анализ с наиболее полным semantic resolution;
- structural и limited semantic extraction для JavaScript, TypeScript, Go и
  Java через Tree-sitter;
- разрешение импортов, constructor/field/provider binding и nested object chains;
- frontend → backend endpoint bridge по service, HTTP method и canonical path;
- versioned support packs с provenance, trust level и confidence caps;
- impact queries, объяснение рёбер и PR-review;
- выбор связанных тестов;
- дополнительная runtime-проверка Python-связей;
- локальный SQLite registry и JSON cache;
- CLI, MCP-сервер, интерактивная локальная карта и оригинальный Graphify viewer.

## Быстрый старт

### Требования

- Python 3.10 или новее;
- Git;
- права записи в рабочую директорию;
- Node.js опционален и нужен только для browser verification или инструментов
  самого анализируемого frontend-проекта;
- Docker опционален.

### Windows PowerShell

```powershell
git clone https://github.com/artemnoor/CodeSlicer.git
cd CodeSlicer
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

Для проверки именно будущей установки соберите wheel и установите его в чистое
окружение. Wheel включает и web UI, и manifest-backed plugins:

```bash
python -m pip install build
python -m build --wheel
python -m pip install dist/impact_engine-0.5.0-py3-none-any.whl
```

### Linux или macOS

```bash
git clone https://github.com/artemnoor/CodeSlicer.git
cd CodeSlicer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Проверьте установку:

```bash
impact-engine doctor
impact-engine --json registry status
```

Registry должен работать в режиме `sqlite`.

### Подключить новый проект

Для локальной папки одна команда строит два отдельных графа: canonical
CodeSlicer graph для impact/review и optional Graphify graph для широкого
архитектурного обзора. Graphify никогда не меняет ranking CodeSlicer.

```bash
impact-engine --json onboard /path/to/project --graphify auto
```

Git URL требует явного разрешения на сеть; клон остаётся в локальном
workspace, а исходный код не отправляется в CodeSlicer:

```bash
impact-engine --json onboard https://github.com/AlekseyYudin-161/JunMate.git \
  --allow-network --graphify auto
```

После изменения кода сначала получите рекомендации, а запуск тестов выполняйте
только отдельным подтверждённым действием:

```bash
impact-engine --json review /path/to/project --run-tests suggested
impact-engine ci /path/to/project --run-tests --test-command pytest tests/test_example.py
```

### Установка через AI-агента

CodeSlicer можно подключить к уже открытому проекту одной инструкцией. Просто
отправьте этот текст своему AI-агенту в IDE или MCP-клиенте:

```text
Установи CodeSlicer в текущий проект:
https://github.com/artemnoor/CodeSlicer.git

Подключи его через MCP или CLI, выполни первичный анализ кодовой базы и покажи:

1. архитектурную карту проекта;
2. ключевые frontend/backend цепочки;
3. unresolved и suspicious области;
4. пример impact-анализа для одной важной функции;
5. связанные тесты.

Не изменяй исходный код без моего подтверждения.

Запусти локальный визуальный интерфейс CodeSlicer и в конце выдай ссылку на
него, например http://127.0.0.1:8001/.

Перед завершением проверь:

- /api/health возвращает status=ok;
- /api/state возвращает has_analysis=true;
- /api/graph содержит непустые nodes и edges;
- путь к созданному graph.json указан в ответе;
- все предупреждения и ограничения анализа перечислены отдельно.
```

Агент должен вернуть не только URL, но и количество узлов/рёбер, путь к
графу и подтверждение, что визуальный интерфейс получил именно этот граф.
Если агент запускает CLI отдельно от API, граф следует сохранять в
`<project>/.impact_engine/graph.json`, чтобы API автоматически его загрузил.

## Анализ проекта

### 1. Сначала проверьте область

Для большого проекта сначала создайте scan plan:

```bash
impact-engine scan-plan /path/to/project
```

План исключает `node_modules`, виртуальные окружения, `.git`, `.impact_engine`,
build/dist/coverage и вложенные Git-репозитории. Перед анализом большого
workspace просмотрите список включённых файлов.

### 2. Постройте граф

```bash
impact-engine analyze /path/to/project \
  --use-scan-plan
```

По умолчанию CLI сохраняет граф в
`<project>/.impact_engine/graph.json`; его автоматически подхватит локальный
визуальный интерфейс. `--out` нужен только для явного нестандартного пути.
Во время обычного запуска CLI
показывает прогресс по этапам. При `--json` структурированный результат
остаётся в stdout, а прогресс выводится в stderr.

### 3. Выполните запрос влияния

```bash
impact-engine impact /path/to/project/.impact_engine/graph.json \
  --symbol repositories.OrderRepository.save \
  --direction both
```

Доступны направления `upstream`, `downstream` и `both`. Для автоматической
обработки агентом добавляйте `--json` перед подкомандой.

### 4. Объясните связь

```bash
impact-engine explain-edge /path/to/project/.impact_engine/graph.json \
  --from services.OrderService.create_order \
  --to repositories.OrderRepository.save
```

Ответ содержит источник, confidence, evidence chain, resolver attribution и
support-pack rule, если они участвовали в создании связи.

## Визуальный интерфейс

Запустите локальный API:

```bash
impact-engine-local-api \
  --host 127.0.0.1 \
  --port 8001 \
  --default-project /path/to/project
```

Откройте <http://127.0.0.1:8001/>.

CLI и API — отдельные процессы. API автоматически загружает
`<project>/.impact_engine/graph.json`. Если граф пустой, проверьте:

```text
GET /api/health  -> status: ok
GET /api/state   -> has_analysis: true
GET /api/graph   -> непустые nodes и edges
```

Для графа в другом месте используйте `POST /api/load-graph`:

```json
{
  "project_path": "/path/to/project",
  "graph_path": "/path/to/graph.json"
}
```

Интерфейс работает с реальным локальным GraphDocument. Mock-графа, Supabase и
другой hosted database в UI нет. Он не дублирует CLI/MCP-настройки: сложные
режимы остаются в CLI и agent skills, а UI отвечает за быстрый визуальный
контроль проекта.

### Карта CodeSlicer

Маршрут `#map` показывает граф CodeSlicer. Точки — сущности проекта, линии —
связи с evidence. Карту можно перетаскивать, масштабировать колесом или
кнопками, а выбор узла открывает его тип, ближайшие связи, источник и
доказательство. Это удобная отправная точка для понимания незнакомого кода и
последствий изменения.

![Интерактивная карта CodeSlicer и инспектор узла](docs/images/codeslicer-map-inspector.png)

### Отдельная карта Graphify

Маршрут `#graphify` не перерисовывает данные Graphify собственным SVG-кодом.
При наличии `<project>/graphify-out/graph.json` CodeSlicer локально запускает
оригинальный HTML renderer Graphify в отдельном iframe: поиск по узлам,
комьюнити и поведение графа остаются возможностями самого Graphify. Этот
граф помогает исследовать общую архитектуру; canonical graph и ranking
CodeSlicer от него не изменяются.

![Оригинальный viewer Graphify внутри локального CodeSlicer](docs/images/codeslicer-graphify-native.png)

Если Graphify ещё не строился, UI честно показывает, что отдельная карта не
подключена, и не подставляет вместо неё граф CodeSlicer. Создайте её явно:

```bash
impact-engine --json onboard /path/to/project --graphify auto
```

## Что изменено в этом релизе

- минимальный local-first UI сфокусирован на двух задачах: понять карту
  CodeSlicer и открыть независимую карту Graphify;
- у карты появились панорамирование, zoom, клавиатурное управление и
  инспектор evidence для выбранного узла;
- Graphify отображается своим upstream HTML renderer, а не адаптированной
  SVG-картой CodeSlicer;
- полный анализ получил более честный прогресс и кооперативную отмену между
  файлами, а default scan исключает generated/tool-runtime директории;
- wheel теперь включает frontend и manifest-backed language/framework plugins;
- GitHub Actions собирает wheel и проверяет его в чистой venv: UI, API и
  discovery Python/TypeScript/C# plugins.

### Release hardening 0.5.0

- Версия пакета повышена до `0.5.0`; wheel и MCP server-info используют одну
  версию.
- Browser E2E — обязательный отдельный job на каждом push и pull request:
  он устанавливает Playwright и Chromium, поэтому тест не может «молча» стать
  skipped.
- Реальный C# review на публичном Cruxa вынесен из обычной регрессии в
  еженедельный/manual acceptance workflow. Он фиксирует commit корпуса,
  создаёт read-only diff и не требует хранить чужой проект в этом репозитории.
- Fast persistent-cache теперь загружает `facts.json`, поэтому `facts_reused`
  отражает реально переиспользованные факты. `.sln` и `.slnx` учитываются как
  manifest-файлы.

Подробное описание изменения, границы и E2E-матрица: [docs/PR_DESCRIPTION.md](docs/PR_DESCRIPTION.md).

## MCP

CodeSlicer предоставляет локальный JSON-RPC MCP-сервер через stdio:

```bash
impact-engine-mcp
```

или:

```bash
python -m impact_engine.mcp.server
```

Пример конфигурации редактора или AI-агента:

```json
{
  "mcpServers": {
    "codeslicer": {
      "command": "impact-engine-mcp",
      "args": []
    }
  }
}
```

Используйте `tools/list` как источник актуальных MCP-схем. Сервер предоставляет
инструменты для inventory, анализа, impact queries, explain-edge, PR-review,
runtime validation, support packs, research workflow и локального registry.

Подробнее: [docs/MCP.md](docs/MCP.md).

## Неизвестные библиотеки

Если библиотека не покрыта доверенным support pack, система не угадывает её
семантику по имени. Она создаёт research request:

```text
unknown library
  -> research request
  -> официальные docs и repository
  -> candidate support pack
  -> schema/provenance/fixture/mutation validation
  -> trust promotion
  -> повторный анализ
```

Запуск workflow:

```bash
impact-engine libraries research /path/to/project \
  --library unknown_library \
  --ecosystem python \
  --build-input
```

Внешний AI-агент или человек создаёт candidate pack. Детерминированное ядро
проверяет его и не позволяет AI напрямую записывать подтверждённые рёбра.

Полный регламент: [docs/SUPPORT_PACKS.md](docs/SUPPORT_PACKS.md).

## Персонализация для проекта

У проекта могут быть private SDK, внутренние HTTP-wrapper-ы и собственные
DI-паттерны, которых нет в общем CodeSlicer registry. Для этого есть
**project-local support packs**. Они сохраняются только рядом с проектом:

```text
<project>/.impact_engine/local_packs/<language>/<library>/support_pack.json
```

Локальный pack загружается раньше общего pack с тем же языком и библиотекой,
но не меняет GitHub-репозиторий CodeSlicer, глобальный `support_packs/` и
SQLite registry.

```bash
impact-engine project-packs init /path/to/project
impact-engine project-packs install /path/to/project candidate_pack.json \
  --trust-level experimental
impact-engine project-packs list /path/to/project
impact-engine analyze /path/to/project --out /path/to/project/.impact_engine/graph.json
```

Требования безопасности остаются прежними: schema validation, source
provenance и `forbid_name_only=true` обязательны. Pack уровня `draft` или
`staged` сохраняется, но не участвует в обычном анализе. Локальный pack не
может получить глобальный уровень `trusted`: универсальное правило должно
перейти в общий registry через отдельный review и benchmark workflow.

Локальные packs поддерживают декларативные правила. Если проекту нужен новый
исполняемый resolver, AI должен подготовить отдельный proposal, fixture и
тесты для PR в CodeSlicer, а не произвольно переписывать ядро анализатора.

## PR-review

`--diff-file` указывает изменение для проверки, но не ограничивает область
первичного парсинга. Если не передать `--graph`, CodeSlicer может заново
анализировать весь большой проект.

Сначала создайте или обновите граф:

```powershell
impact-engine analyze C:\path\to\project `
  --use-scan-plan `
  --out C:\path\to\project\.impact_engine\graph.json
```

Затем переиспользуйте его:

```powershell
impact-engine pr-review C:\path\to\project `
  --diff-file C:\path\to\change.diff `
  --graph C:\path\to\project\.impact_engine\graph.json
```

Отчёт содержит изменённые файлы и символы, risk score, confirmed/likely/
suspicious impact, unresolved boundaries и рекомендуемые тесты.

## Четыре режима CodeSlicer

CLI, local API и MCP используют единый локальный контракт:

```text
review → inspect → investigate → ci
```

```powershell
impact-engine review . --max-results 10 --json
impact-engine inspect . --entity "Cruxa.Api.Features.Routes.RoutesController.Create" --json
impact-engine investigate . --entity "route:httpget:api/orders" --direction downstream --depth 8 --json
impact-engine ci . --base origin/main --format json --out .impact_engine/ci-report.json
```

`review` сохраняет `ReviewReport/v1`; остальные mode-ответы используют
`CodeSlicerModeReport/v1`, а общий `contract_version` —
`CodeSlicerModeContract/v1`. CI по умолчанию advisory и завершает процесс с
кодом 0; policy violation — 1, invalid input/config — 2, невозможность
анализа — 3. Тесты и runtime validation запускаются только по явному флагу.
Исходный код, graph, diff и telemetry не отправляются наружу. IDE, PR,
GitHub/GitLab и release delivery будут тонкими клиентами поверх этого
контракта на следующем этапе.

## Формат графа

Анализ создаёт JSON-артефакт `GraphDocument`:

- `nodes` — файлы, модули, классы, функции, методы, routes, tests и внешние
  библиотеки;
- `edges` — imports, calls, bindings, route handling, HTTP calls, endpoint
  matches и другие типизированные связи;
- `metadata` — языки, diagnostics, coverage, unknown regions, fingerprints,
  resolver data и support-pack provenance.

Узлы имеют stable canonical identity и source location. Рёбра могут содержать
confidence, evidence, `source_fact_ids`, `dependency_keys`, `resolver_id` и
статус разрешения.

## Поддержка языков

| Язык | Статус |
| --- | --- |
| Python | strongest semantic baseline |
| JavaScript / TypeScript | structural + limited semantic и frontend endpoint bridge |
| Go | structural + limited semantic resolution |
| Java | structural + limited semantic resolution |

Для JavaScript, TypeScript, Go и Java возможен явный `fallback`, если native
Tree-sitter недоступен. Это не означает compiler-level parity с Python.
Некоторые framework-specific связи появляются только после установки
проверенного support pack.

## Структура репозитория

```text
src/impact_engine/        ядро, CLI, MCP и local API
support_packs/             правила фреймворков и библиотек
frontend/                  локальный graph viewer
tests/                     unit, fixture, CLI, MCP и regression tests
examples/                  небольшие воспроизводимые проекты
docs/                      подробная документация
integrations/agent-skills  инструкции для AI-агентов
```

## Ограничения

CodeSlicer — статический анализатор, а не компилятор и не универсальный
runtime debugger. На качество влияют:

- reflection и динамический dispatch;
- runtime-selected dependency injection;
- сложные generics и generated proxies;
- динамическая сборка routes и URL;
- private dependencies без support pack;
- отсутствие достаточных типов и evidence.

Такие случаи классифицируются как `ambiguous`, `unresolved`, `unsupported`
или `suspicious`, а не объявляются подтверждёнными без доказательств.

Текущая scoring-модель — интерпретируемая эвристика, а не научно
калиброванная вероятность. Коэффициенты можно калибровать по размеченным
изменениям, результатам тестов и пользовательской обратной связи.

Подробнее: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Разработка

```bash
python -m pytest -q
impact-engine doctor
impact-engine --json registry status
```

Для browser E2E локально:

```bash
python -m pip install ".[dev,browser]"
python -m playwright install chromium
IMPACT_ENGINE_REQUIRE_BROWSER_E2E=1 python -m pytest tests/test_frontend_browser_e2e.py -q
```

Основной CI запускает browser E2E на каждом push/PR. Внешний C# acceptance
на pinned [Cruxa](https://github.com/contr4s/Cruxa) запускается отдельно по
расписанию или вручную, чтобы тяжёлый внешний corpus не становился скрытым
skipped-тестом обычной регрессии.

Графы, кэши, SQLite и benchmark-отчёты должны оставаться в `.impact_engine`
или других игнорируемых директориях, а не попадать в продуктовую документацию.

## Лицензия

Проект распространяется по лицензии [MIT](LICENSE).

## Localhost Visual Intelligence Hub

Локальный Hub даёт четыре изолированных режима: Review, Inspect,
Investigate и Architecture. Review остаётся bounded и объясняет risk через
evidence chains; Investigate запускает только явные ограниченные запросы;
Architecture показывает canonical CodeSlicer graph и supplemental overlays
Graphify, CodeGraph, SCIP, LSP, OTel, Boundary и Security/SBOM.

Главный экран показывает freshness, coverage, cache/daemon health и
исключённые generated/vendor/dependency paths, не выдавая размер графа за его
качество. Progressive graph lens сначала показывает modules/files, а symbols
и edges раскрывает только после explicit bounded action. Внешние overlays не
меняют canonical graph, Review risk, ranking или test recommendations.

Hub работает local-first: API same-origin localhost, `network_used=false`,
артефакты импортируются только по absolute local path, без upload, telemetry,
скачиваний и скрытого запуска инструментов.

## Опциональные адаптеры

Все 11 интеграций доступны, но изначально выключены: Graphify, CodeGraph,
SCIP, LSP, OpenAPI, AsyncAPI, OpenTelemetry, CycloneDX, SPDX, SARIF и
Joern/CPG. Они добавляют только отдельный evidence overlay для Architecture
или Investigate: canonical CodeSlicer graph, risk, review ranking и подбор
тестов от них не меняются.

Перед подключением покажите единый локальный план действий:

```bash
impact-engine --json adapters preflight /path/to/project
```

Для адаптера с готовым локальным артефактом импорт и включение — одно
явное действие. Артефакт копируется в `<project>/.codeslicer/artifacts/`,
проверяется fingerprint и не отправляется наружу:

```bash
impact-engine --json adapters import /path/to/project graphify \
  /absolute/path/to/graphify-out/graph.json --enable

impact-engine --json adapters import /path/to/project cyclonedx \
  /absolute/path/to/bom.json --enable
```

LSP — единственное исключение: это явно выбранный локальный процесс, а не
файл. Его надо настроить с абсолютным путём к уже установленному серверу:

```bash
impact-engine --json adapters lsp configure /path/to/project \
  --executable /absolute/path/to/language-server \
  --workspace-root /path/to/project
```

Joern также не устанавливается и не запускается автоматически: он принимает
только уже созданный пользователем локальный interchange-экспорт. Проверить
состояние любого подключения можно через
`impact-engine --json adapters status /path/to/project <adapter-id>`.

## Дополнительная документация

- [Getting Started](docs/GETTING_STARTED.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP](docs/MCP.md)
- [Support Packs](docs/SUPPORT_PACKS.md)
- [Limitations](docs/LIMITATIONS.md)
- [Joern / CPG adapter](docs/adapters-joern.md)

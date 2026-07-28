# Интеграции и отдельные графы

CodeSlicer не смешивает все данные в один граф. Канонический evidence graph
используется для impact, review, риска и рекомендаций тестов; каждый внешний
инструмент хранит свой graph/workspace и свой уровень доверия.

```text
CodeSlicer canonical graph      impact, risk, explain, targeted tests
External native graph/workspace собственные запросы и специализированная работа
Bridge / overlay                явно помеченный локальный контекст между ними
```

Canonical graph находится в `<project>/.impact_engine/graph.json`. Только он
участвует в `review` и `pr-review`. Отключение внешнего adapter не повреждает
canonical graph и не меняет его ranking.

## Graphify: архитектура, communities и документация

[Graphify](https://github.com/Graphify-Labs/graphify) отвечает на широкий
архитектурный вопрос: как устроен проект, какие модули образуют community, где
связаны код, ADR и документация. Он не заменяет точное доказательство вызова
функции и не повышает риск PR.

### Где находится Graphify graph

Новый onboarding и native index используют единый путь:

```text
<project>/.codeslicer/artifacts/graphify/graphify-out/graph.json
```

Старый `<project>/graphify-out/graph.json` читается только как fallback для
уже существующего проекта. `.impact_engine/graph.json` никогда не выдаётся за
результат Graphify.

### Сценарий работы

```powershell
# Проверить, есть ли локальный Graphify, без запуска и без сети
impact-engine adapters native C:\work\my-app graphify profile --json

# Явно построить самостоятельный architecture graph
impact-engine adapters native C:\work\my-app graphify index --confirm

# Вызвать нативный query Graphify
impact-engine adapters native C:\work\my-app graphify query --confirm `
  --query "auth community"

# Открыть локальный UI и вкладку Graphify
impact-engine-local-api --default-project C:\work\my-app
```

Вкладка Graphify запускает upstream HTML renderer в отдельном subprocess.
Local API не импортирует код клонированного Graphify в свой процесс. Если
upstream repository или его зависимости отсутствуют, отображается честная
ошибка renderer, а не адаптированная карта CodeSlicer.

Практический порядок: Graphify помогает найти community `authentication`,
после чего CodeSlicer через `inspect` или `review` доказывает конкретный путь,
например `LoginForm.submit → POST /api/auth/login → AuthService.login`, и
выбирает tests. Это два совместимых ответа на разные вопросы.

## Другие optional adapters

| Инструмент | Для чего | Что добавляет | Чего не делает автоматически |
| --- | --- | --- | --- |
| CodeGraph | callers/callees и semantic context | отдельный workspace/bridge | не меняет impact ranking |
| Gortex | multi-repo architecture и contracts | независимый knowledge graph | не становится canonical evidence |
| SCIP / LSP | definitions, references, implementations | semantic navigation overlay | не запускается без настройки |
| OpenAPI / AsyncAPI | HTTP/event contracts | operations, schemas, channels | не обращается к URL или broker |
| OpenTelemetry | observed runtime paths | локально импортированные spans | отсутствие trace не доказывает отсутствие связи |
| Joern | CPG, taint/data-flow, security | отдельный heavy security workspace | не включается по умолчанию |
| CycloneDX / SPDX / SARIF | SBOM, лицензии, scanner findings | supply-chain/security context | не повышает PR risk сам по себе |

Импорт artifact — явное local-first действие:

```powershell
impact-engine --json adapters import C:\work\my-app openapi C:\specs\openapi.yaml --enable
impact-engine --json adapters import C:\work\my-app sarif C:\reports\scan.sarif --enable
impact-engine --json adapters status C:\work\my-app graphify
```

## Privacy и подтверждения

Обычный analysis, чтение graph и import локального artifact не отправляют код
в сеть. Clone upstream repository, нативная индексация и запуск произвольной
команды внешнего инструмента требуют отдельного действия. CLI требует
`--confirm`; MCP использует одноразовые `approval_id` + `approval_token`,
связанные с конкретными argv/payload и пригодные только один раз.

Это не OS sandbox: явно запущенный upstream process может иметь собственное
сетевое поведение. Поэтому CodeSlicer не использует shell и показывает
операцию, argv, рабочую директорию и timeout перед подтверждением.

### Подтверждение запросов агента

MCP-агент способен только создать pending-запрос. Он не может сам выдать
токен, повторно использовать его или заменить параметры уже подтверждённой
команды. Владелец проекта проверяет и подтверждает запрос локально:

Для обычного MCP-сценария агенту **не нужно сначала собирать `payload` и
вызывать `request_action_approval`**. Он вызывает нужный чувствительный
инструмент (например, `runtime_trace`, `onboard` с clone, `managed_tool_help`
или `run_managed_tool`) с его реальными параметрами. Без credentials тот сам
возвращает `status: pending_approval`, уже связанный с точным action и
payload. После локального approval агент повторяет тот же вызов с выданными
`approval_id` и `approval_token`. Ручной `request_action_approval` оставлен
только для advanced-интеграций.

```powershell
impact-engine --json approvals list C:\Projects\my-app
impact-engine --json approvals show C:\Projects\my-app <approval-id>
impact-engine --json approvals approve C:\Projects\my-app <approval-id>
```

Последняя команда возвращает одноразовый `approval_token` с ограниченным TTL.
Его вместе с `approval_id` передают в исходный MCP-вызов. Это требуется для
runtime trace, managed-tool `--help` и команд, сетевого onboarding/clone,
автоматического Graphify и CI-тестов. Обычный статический анализ локальных
файлов подтверждения не требует.

Local API применяет ту же границу. Поле `confirmed: true` не является
разрешением: endpoint, который может запустить процесс, вернёт
`409 pending_approval` с точной локальной командой approval. После этого
повторный запрос должен содержать возвращённые `approval_id` и
`approval_token`. Страницы Graphify загружаются в sandbox без same-origin,
поэтому upstream HTML не получает доступ к интерфейсу или API CodeSlicer.

## Диагностика

## Local API и Docker

`impact-engine-local-api` по умолчанию слушает только loopback. Он также
проверяет `Host` у каждого `/api/*` запроса, поэтому DNS-rebinding host не
может получить session token через `/api/health`. Параметр `--allow-remote`
предназначен только для явно управляемой инфраструктуры: вместе с ним
обязателен `--remote-token <high-entropy-secret>`; этот секрет health endpoint
не возвращает.

Стандартный `Dockerfile` и `docker-compose.yml` намеренно не публикуют Local
API и Registry API на хостовую сеть. Для локальной отладки используйте
осознанный override с loopback port mapping либо отдельный reverse proxy с
аутентификацией; не публикуйте порт CodeSlicer напрямую в интернет.

Graphify viewer не запускает renderer при GET: после явно подтверждённого
Graphify index/refresh он сохраняет bounded HTML-артефакт, а viewer только
читает его. LSP probe/query аналогично требуют одноразового local approval,
потому что запускают внешний language-server process.

```powershell
impact-engine doctor --full
impact-engine adapters native C:\work\my-app graphify profile --json
impact-engine adapters status C:\work\my-app graphify --json
```

Отсутствие Graphify, Joern, LSP или SCIP является ограничением отдельного
слоя и не скрывает coverage канонического CodeSlicer анализа.

Смежные детали: [границы adapters](adapters-boundary.md),
[нативные sources](native-sources.md), [Joern](adapters-joern.md) и
[security adapters](adapters-security.md).

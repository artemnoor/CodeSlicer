# Self-Adapting Impact Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Impact Engine from a golden-case prototype into an extensible deterministic project nervous-system analyzer: language extraction + normalized graph + semantic resolver + support packs + optional runtime facts + MCP tools.

**Architecture:** Keep `GraphDocument` as the canonical graph format. Split analysis into clear layers: extractor produces raw facts, normalizer validates/canonicalizes facts, semantic index resolves symbols/imports/bindings, resolver passes emit inferred edges, support packs add deterministic framework/library semantics, MCP remains a thin wrapper over core APIs.

**Tech Stack:** Python 3.10+, stdlib AST for Python MVP, dataclasses/JSON, pytest. No mandatory Graphify, tree-sitter, web framework, database, Docker, crawler, or LLM API in this phase.

---

## Target Architecture

```text
Project files
  -> Language Frontend
      Python AST extractor now
      JS/Go/Java adapters later
  -> Raw GraphDocument
      files, modules, classes, methods, imports, assignments, calls
  -> Normalizer
      canonical ids, schema checks, stable evidence shape
  -> Semantic Index
      module index, import index, class index, method index, assignment facts
  -> Resolver Engine
      language semantics passes
      support pack rules
      optional runtime trace facts
  -> Impact Graph
      CALLS, MAY_CALL, ROUTE_HANDLES, TESTS, AFFECTS, DB_READS/WRITES later
  -> CLI / MCP
      analyze_project, impact_query, explain_edge, detect_unknown_libraries
```

## Storage Layout

Runtime outputs should live outside source code:

```text
.impact_engine/
  graphs/
    latest.json
    <timestamp>.json
  reports/
    latest_audit.json
  research_requests/
    <library>.json
  traces/
    runtime_trace.jsonl
  cache/
    symbol_index.json
```

Repository-owned support packs should stay versionable:

```text
support_packs/
  <library_name>/
    support_pack.json
    examples/
      minimal_case/
    README.md
```

Generated but unverified AI output must not be applied automatically:

```text
.impact_engine/research_requests/<library>.json
.impact_engine/proposed_support_packs/<library>/support_pack.json
```

Only validated imported packs move into:

```text
support_packs/<library>/support_pack.json
```

## Core Contracts

### Extractor Contract

Extractor may create only syntactic/extracted facts:

- `FILE`
- `MODULE`
- `CLASS`
- `FUNCTION`
- `METHOD`
- `CALL_EXPR`
- `ASSIGNMENT`
- `IMPORTS`
- `CONTAINS`
- `DECLARES`

Extractor must not create semantic/inferred `CALLS` edges.

### Normalizer Contract

Normalizer may:

- canonicalize ids;
- validate schema;
- remove duplicate nodes/edges;
- normalize evidence fields;
- normalize external adapter inputs into `GraphDocument`.

Normalizer must not infer `CALLS`, `DEPENDS_ON`, `ROUTE_HANDLES`, or any semantic relation.

### Resolver Contract

Resolver is the only static layer that emits deterministic semantic edges:

- `INSTANCE_OF`
- `PARAM_BINDS_TO`
- `FIELD_BINDS_TO`
- `RESOLVES_TO`
- `CALLS`
- `MAY_CALL`
- `DEPENDS_ON`

Every inferred edge must contain evidence and confidence.

### Support Pack Contract

Support packs are machine-readable deterministic rules. AI may generate them, but resolver only applies validated support packs.

Minimum rule families:

- import rules;
- decorator rules;
- constructor/DI rules;
- call receiver rules;
- framework route rules;
- test discovery rules.

### MCP Contract

MCP tools wrap core APIs only:

- `analyze_project`
- `impact_query`
- `explain_edge`
- `detect_unknown_libraries`
- `list_support_packs`
- `validate_support_pack`
- `create_library_research_request`

MCP must not duplicate resolver logic.

---

## File Structure Plan

### Keep

- `src/impact_engine/models.py`: canonical graph dataclasses.
- `src/impact_engine/extractors/python_ast.py`: Python AST extractor.
- `src/impact_engine/normalization/graph.py`: idempotent graph normalization.
- `src/impact_engine/impact.py`: graph query layer.
- `src/impact_engine/mcp/server.py`: thin callable MCP skeleton.
- `src/impact_engine/support_packs/schema.py`: support pack schema.
- `src/impact_engine/support_packs/registry.py`: registry file operations.

### Add

- `src/impact_engine/resolution/symbol_index.py`: builds module/class/method/import indexes from GraphDocument.
- `src/impact_engine/resolution/imports.py`: package-aware import and symbol resolution.
- `src/impact_engine/resolution/bindings.py`: variable, parameter, and field binding inference.
- `src/impact_engine/resolution/calls.py`: receiver and method-call resolution.
- `src/impact_engine/resolution/engine.py`: orchestrates resolver passes and support pack application.
- `src/impact_engine/runtime/traces.py`: optional runtime trace adapter to GraphDocument facts.
- `src/impact_engine/languages/base.py`: language frontend interface.
- `src/impact_engine/languages/python_frontend.py`: wraps current Python extractor as a language frontend.
- `src/impact_engine/analysis/pipeline.py`: one core `analyze_project_core()` used by CLI and MCP.

### Modify

- `src/impact_engine/resolution/precision.py`: keep as compatibility wrapper around `resolution.engine`.
- `src/impact_engine/cli.py`: call `analysis.pipeline.analyze_project_core()`.
- `src/impact_engine/mcp/server.py`: call `analysis.pipeline.analyze_project_core()`.
- `docs/ARCHITECTURE.md`: update with layered architecture.
- `docs/MODULE_CONTRACTS.md`: add extractor/normalizer/resolver/support-pack contracts.
- `docs/STAGE_PLAN.md`: replace prototype stages with expansion milestones.

---

## Milestone 1: Fix Package-Aware Python Resolver

**Goal:** The uploaded `test_impact_project` must produce deterministic inferred `CALLS` edges for package modules like `app.container` and `app.services.order_service`.

**Files:**
- Modify: `src/impact_engine/resolution/precision.py`
- Test: `tests/test_precision_resolver_package_project.py`
- Fixture: `tests/fixtures/package_di_project/`

- [ ] **Step 1: Add package DI fixture**

Create a small fixture copied from the external test project pattern:

```text
tests/fixtures/package_di_project/app/container.py
tests/fixtures/package_di_project/app/services/order_service.py
tests/fixtures/package_di_project/app/repositories/order_repository.py
tests/fixtures/package_di_project/expected_edges.json
```

The fixture must include:

```python
# app/container.py
from app.repositories.order_repository import OrderRepository
from app.services.order_service import OrderService

class Container:
    def __init__(self):
        self.order_repository = OrderRepository()
        self.order_service = OrderService(repository=self.order_repository)
```

```python
# app/services/order_service.py
class OrderService:
    def __init__(self, repository):
        self.repository = repository

    def create_order(self, order):
        return self.repository.save(order)
```

```python
# app/repositories/order_repository.py
class OrderRepository:
    def save(self, order):
        return order
```

- [ ] **Step 2: Write failing package resolver test**

Create `tests/test_precision_resolver_package_project.py`:

```python
from pathlib import Path

from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision


FIXTURE = Path(__file__).parent / "fixtures" / "package_di_project"


def test_package_module_di_resolves_repository_save_call():
    graph = extract_project(FIXTURE)
    resolved = resolve_precision(graph)

    edge = next(
        (
            e
            for e in resolved.edges
            if e.kind == "CALLS"
            and e.from_node == "app.services.order_service.OrderService.create_order"
            and e.to_node == "app.repositories.order_repository.OrderRepository.save"
        ),
        None,
    )

    assert edge is not None
    assert edge.source == "INFERRED"
    assert edge.confidence >= 0.80
    assert len(edge.evidence) >= 4
```

- [ ] **Step 3: Verify the test fails before implementation**

Run:

```powershell
python -m pytest tests/test_precision_resolver_package_project.py -q
```

Expected before fix:

```text
FAILED
```

- [ ] **Step 4: Replace naïve module lookup**

In `src/impact_engine/resolution/precision.py`, replace every use of:

```python
current_module = scope.split(".")[0]
```

with a helper:

```python
def module_for_scope(scope: str, doc: GraphDocument) -> str | None:
    candidates = [
        n.id.replace("module:", "")
        for n in doc.nodes
        if n.kind == "MODULE" and scope.startswith(n.id.replace("module:", "") + ".")
    ]
    if not candidates:
        return scope.split(".")[0]
    return max(candidates, key=len)
```

Use:

```python
current_module = module_for_scope(scope, graph)
```

- [ ] **Step 5: Run package resolver test**

Run:

```powershell
python -m pytest tests/test_precision_resolver_package_project.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Run golden MVP regression**

Run:

```powershell
python -m pytest tests/test_precision_resolver.py tests/test_golden_python_di_basic.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Run full test suite**

Run:

```powershell
python -m pytest -ra
```

Expected:

```text
all tests passed
```

---

## Milestone 2: Extract Semantic Index From Resolver

**Goal:** Make resolver maintainable by moving symbol/import lookup out of monolithic `precision.py`.

**Files:**
- Create: `src/impact_engine/resolution/symbol_index.py`
- Modify: `src/impact_engine/resolution/precision.py`
- Test: `tests/test_symbol_index.py`

- [ ] **Step 1: Create SymbolIndex dataclass**

Add:

```python
from dataclasses import dataclass, field

from impact_engine.models import GraphDocument


@dataclass
class SymbolIndex:
    modules: set[str] = field(default_factory=set)
    classes_by_name: dict[str, list[str]] = field(default_factory=dict)
    methods: set[str] = field(default_factory=set)
    imports_by_module: dict[str, set[str]] = field(default_factory=dict)


def build_symbol_index(graph: GraphDocument) -> SymbolIndex:
    index = SymbolIndex()
    for node in graph.nodes:
        if node.kind == "MODULE":
            index.modules.add(node.id.replace("module:", ""))
        elif node.kind == "CLASS":
            class_id = node.id.replace("class:", "")
            index.classes_by_name.setdefault(node.name, []).append(class_id)
        elif node.kind == "METHOD":
            index.methods.add(node.id.replace("method:", ""))

    for edge in graph.edges:
        if edge.kind == "IMPORTS":
            from_module = edge.from_node.replace("module:", "")
            to_module = edge.to_node.replace("module:", "")
            index.imports_by_module.setdefault(from_module, set()).add(to_module)

    return index
```

- [ ] **Step 2: Add tests for package import index**

Test that `app.container` imports `app.repositories.order_repository` and that `OrderRepository` maps to `app.repositories.order_repository.OrderRepository`.

- [ ] **Step 3: Use SymbolIndex in resolver**

Update `resolve_class_name()` to use `SymbolIndex` while preserving old behavior.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/test_symbol_index.py tests/test_precision_resolver_package_project.py tests/test_precision_resolver.py -q
```

---

## Milestone 3: Split Resolver Into Passes

**Goal:** Move from one precision function to a resolver engine with clear passes.

**Files:**
- Create: `src/impact_engine/resolution/bindings.py`
- Create: `src/impact_engine/resolution/calls.py`
- Create: `src/impact_engine/resolution/engine.py`
- Modify: `src/impact_engine/resolution/precision.py`
- Test: `tests/test_resolution_engine.py`

Resolver pass order:

```text
1. build_symbol_index
2. infer_direct_instances
3. infer_constructor_param_bindings
4. infer_parameter_to_field_bindings
5. resolve_receiver_calls
6. apply_support_pack_rules
7. apply_runtime_trace_facts
```

- [ ] **Step 1: Preserve public API**

`resolve_precision(graph, support_packs=None)` must keep working.

- [ ] **Step 2: Add `resolve_graph()`**

`engine.py` exposes:

```python
def resolve_graph(graph: GraphDocument, support_packs: list | None = None) -> GraphDocument:
    ...
```

- [ ] **Step 3: Move binding state into explicit context**

Create:

```python
@dataclass
class ResolutionContext:
    variable_types: dict[tuple[str, str], str]
    field_types: dict[tuple[str, str], str]
    parameter_types: dict[tuple[str, str], str]
    evidences: dict[tuple, list[Evidence]]
```

- [ ] **Step 4: Run regression suite**

```powershell
python -m pytest tests/test_precision_resolver.py tests/test_precision_resolver_package_project.py tests/test_support_pack_resolution.py -q
```

---

## Milestone 4: Stronger Python Semantics

**Goal:** Support real-world Python patterns without framework-specific logic.

**Files:**
- Modify: `src/impact_engine/extractors/python_ast.py`
- Modify: `src/impact_engine/resolution/calls.py`
- Test: `tests/test_python_semantics.py`

Add support for:

- `return OrderService(...)` constructor calls;
- `container.build_order_service().create_order(...)` as chained call facts;
- `self._helper(...)` same-class method calls;
- alias fields: `self.repo = repository`;
- type annotations: `repository: OrderRepository`;
- optional dependencies: emit `MAY_CALL` at lower confidence when guarded by `if self.repository:`.

Acceptance:

```text
test_impact_project must find at least:
- OrderService._persist_order -> OrderRepository.save
- OrderService.persist_order_alias -> OrderRepository.save
- OrderService.create_order -> PaymentService.charge
- PaymentService.charge -> PaymentRepository.save_payment
- PaymentService.charge -> PaymentGateway.charge_card
```

---

## Milestone 5: Support Pack Rule Engine V1

**Goal:** Support packs influence resolver deterministically, not just validate JSON.

**Files:**
- Modify: `src/impact_engine/support_packs/schema.py`
- Modify: `src/impact_engine/support_packs/resolution.py`
- Test: `tests/test_support_pack_rule_engine.py`

Support rule schema:

```json
{
  "id": "fastapi-route-post",
  "when": {
    "node_kind": "METHOD",
    "decorator": "app.post"
  },
  "emit": {
    "edge_kind": "ROUTE_HANDLES",
    "from": "$route",
    "to": "$method",
    "confidence": 0.90
  }
}
```

Minimum matchers:

- `node_kind`
- `call_name`
- `decorator`
- `imported_library`
- `receiver_type`
- `method_name`

Minimum emitted edges:

- `DEPENDS_ON`
- `ROUTE_HANDLES`
- `CALLS`
- `MAY_CALL`
- `TESTS`

Acceptance:

- support pack emitted edges have `source=SUPPORT_PACK`;
- AI proposed edges are rejected;
- invalid rules return validation errors;
- support pack rules can enrich resolver output.

---

## Milestone 6: Unknown Library Detection And Research Workflow

**Goal:** Unknown libraries become explicit research requests and then validated support packs.

**Files:**
- Modify: `src/impact_engine/mcp/server.py`
- Modify: `src/impact_engine/support_packs/research.py`
- Create: `src/impact_engine/support_packs/detection.py`
- Test: `tests/test_unknown_library_detection.py`

Detection input:

- imports from extractor;
- package metadata files later: `pyproject.toml`, `package.json`, `go.mod`, `pom.xml`.

Workflow:

```text
detect_unknown_libraries(project)
  -> unknown libraries list
create_library_research_request(library)
  -> .impact_engine/research_requests/library.json
AI researcher generates proposed support_pack.json
validate_support_pack(proposed)
import_support_pack(proposed)
resolver uses imported pack deterministically
```

Acceptance:

- stdlib modules like `__future__` are ignored;
- local modules are ignored;
- unknown third-party imports are reported;
- no network or LLM API is called.

---

## Milestone 7: Runtime Trace Adapter

**Goal:** Allow tests/runtime traces to confirm static edges without making runtime tracing mandatory.

**Files:**
- Create: `src/impact_engine/runtime/traces.py`
- Create: `src/impact_engine/adapters/runtime_trace.py`
- Test: `tests/test_runtime_trace_adapter.py`

Trace format:

```json
{"event":"call","from":"A.method","to":"B.method","file":"x.py","line":10}
```

Adapter emits:

- `CALLS` with `source=RUNTIME_CONFIRMED`, `confidence=1.0`; or
- upgrades existing static edge confidence by adding evidence.

Acceptance:

- runtime trace can add a new confirmed edge;
- runtime trace can enrich existing inferred edge;
- no tracing runtime is implemented in this milestone.

---

## Milestone 8: True MCP Server Wrapper

**Goal:** Turn callable MCP skeleton into an actual MCP-compatible server without moving core logic into MCP.

**Files:**
- Add optional dependency group in `pyproject.toml`: `mcp = [...]`
- Create: `src/impact_engine/mcp/stdio_server.py`
- Keep: `src/impact_engine/mcp/server.py`
- Test: `tests/test_mcp_stdio_contract.py`

Rules:

- MCP dependency must be optional.
- CLI and core tests must pass without MCP package installed.
- Tool functions call existing core functions.

Acceptance tools:

- `analyze_project`
- `impact_query`
- `explain_edge`
- `detect_unknown_libraries`
- `list_support_packs`
- `validate_support_pack`
- `create_library_research_request`

---

## Milestone 9: Multi-Language Frontend Interface

**Goal:** Prepare for JS/Go/Java without adding tree-sitter or extra parsers immediately.

**Files:**
- Create: `src/impact_engine/languages/base.py`
- Create: `src/impact_engine/languages/python_frontend.py`
- Modify: `src/impact_engine/analysis/pipeline.py`
- Test: `tests/test_language_frontend.py`

Interface:

```python
class LanguageFrontend(Protocol):
    language: str

    def can_analyze(self, path: Path) -> bool:
        ...

    def extract(self, path: Path) -> GraphDocument:
        ...
```

Acceptance:

- Python frontend wraps current extractor;
- pipeline can select frontend;
- unsupported language returns clear error;
- Graphify remains optional external adapter, not a language frontend and not core.

---

## Milestone 10: Impact Graph Productization

**Goal:** Make graph output directly useful for agent decisions.

**Files:**
- Modify: `src/impact_engine/impact.py`
- Create: `src/impact_engine/analysis/report.py`
- Test: `tests/test_impact_report.py`

Report shape:

```json
{
  "changed_symbol": "A.method",
  "direct_downstream": [],
  "transitive_downstream": [],
  "routes": [],
  "tests": [],
  "external_dependencies": [],
  "confidence_summary": {},
  "evidence": []
}
```

Acceptance:

- impact query follows `CALLS`, `MAY_CALL`, `ROUTE_HANDLES`, `TESTS`, `AFFECTS`;
- report separates strong and weak edges;
- explain output includes evidence chain.

---

## Priority Order For Antigravity

1. Fix package-aware module/import resolution.
2. Add package DI fixture and comparison against expected edges.
3. Extract `SymbolIndex`.
4. Split resolver passes.
5. Add stronger Python semantics: same-class calls, alias fields, chained factory calls.
6. Upgrade support pack rule engine.
7. Improve unknown library detection.
8. Add runtime trace adapter.
9. Add true optional MCP stdio server.
10. Add multi-language frontend interface.

## First Antigravity Task

```text
Ты Antigravity Executor проекта Impact Engine.

Задача: исправить package-aware Python resolver, не переписывая всю архитектуру.

Контекст:
Сейчас resolver проходит golden case, но провалился на реальном package-style проекте:
scope = app.container.Container.__init__
imports лежат в module:app.container
а resolver делает current_module = scope.split(".")[0] и получает только app.
Из-за этого не резолвятся OrderRepository/OrderService и не создаются inferred CALLS edges.

Нужно сделать маленький фикс:

1. Добавь fixture:
tests/fixtures/package_di_project/
  app/__init__.py
  app/container.py
  app/services/__init__.py
  app/services/order_service.py
  app/repositories/__init__.py
  app/repositories/order_repository.py
  expected_edges.json

Содержимое должно моделировать:
- app.container.Container.__init__
- self.order_repository = OrderRepository()
- self.order_service = OrderService(repository=self.order_repository)
- OrderService.__init__(self, repository): self.repository = repository
- OrderService.create_order(...): self.repository.save(order)

2. Добавь тест:
tests/test_precision_resolver_package_project.py

Тест должен:
- extract_project(FIXTURE)
- resolve_precision(graph)
- найти edge:
  from = app.services.order_service.OrderService.create_order
  to = app.repositories.order_repository.OrderRepository.save
  kind = CALLS
  source = INFERRED
  confidence >= 0.80
  evidence не пустой, желательно >= 4

3. Исправь resolver минимально:
- добавь helper module_for_scope(scope, graph)
- helper должен выбирать самый длинный MODULE id, который является prefix для scope.
- пример:
  scope app.container.Container.__init__ -> app.container
  scope app.services.order_service.OrderService.create_order -> app.services.order_service
- замени current_module = scope.split(".")[0] на module_for_scope(...).

4. Не меняй extractor.
5. Не добавляй зависимости.
6. Не трогай Graphify/MCP/support packs.
7. Не хардкодь имена app/OrderRepository/OrderService.
8. Сохрани обратную совместимость golden case.

Запусти:
python -m pytest tests/test_precision_resolver_package_project.py -q
python -m pytest tests/test_precision_resolver.py tests/test_golden_python_di_basic.py -q
python -m pytest -ra

В отчёте верни:
- какие файлы изменил;
- какой был root cause;
- какие tests прошли;
- пример найденного edge с confidence и evidence count.
```

## Completion Criteria

The system is ready for broader real-project testing when:

- uploaded `test_impact_project` finds at least 5/8 `must_find` edges;
- golden MVP edge still has confidence >= 0.80 and evidence chain;
- no mandatory external parser/framework dependency is introduced;
- support packs can deterministically add resolver edges;
- MCP tools call the same core pipeline as CLI;
- unknown library workflow produces research requests but does not call network/LLM automatically.

# unknown_library_project

A tiny Python 3.11+ fixture project for testing an **unknown-library research workflow** in an impact-analysis system.

The project is intentionally small but includes realistic traps:

- standard-library imports that must not become unknown dependencies;
- local `app.*` imports that must not become unknown dependencies;
- a known framework/test dependency (`fastapi`, `pytest`);
- a dev/internal helper dependency that should be ignored when marked dev-only;
- two real unknown third-party-looking libraries with library-specific patterns.

No real external API is called. Tests use local stub modules under `tests/stubs/` while application imports still look like top-level third-party imports.

## Run

```bash
python -m pytest -q
```

## Expected unknown libraries

The analyzer should create research requests for:

- `strangebus-sdk` / import name `strangebus`
- `magicqueue-client` / import name `magicqueue`

These are intentionally unknown third-party dependencies. The source code uses patterns that a generic analyzer will likely see structurally, but should not pretend to understand semantically before a support pack exists.

## Should NOT be unknown

The analyzer should not create unknown-library research requests for:

- `json`, `os`, `pathlib` — Python standard library imports;
- `app.*` — local project imports;
- `pytest` — known test/dev dependency;
- `internal-utils-dev` / import name `internal_utils_dev` — intentionally marked as `dev-only-ignore` in `pyproject.toml` and commented in `requirements.txt`.

## Important code patterns

### `strangebus`

```python
strangebus.route("order.created")(handler)
strangebus.emit("order.created", payload)
```

### `magicqueue`

```python
QueueClient("orders").publish("order.created", payload)
QueueClient("orders").subscribe("order.created", handle_order_created)
```

## Expected static chain before support packs

A generic analyzer should be able to build the structural chain:

```text
app.main.create_order
  -> app.services.workflow.OrderWorkflow.create_order
  -> app.repositories.orders.OrderRepository.save
  -> strangebus.emit("order.created", payload)
  -> magicqueue.QueueClient.publish("order.created", payload)
```

It may also detect registration-like calls in integration modules:

```text
app.integrations.strangebus
  -> strangebus.route("order.created")(handle_order_created)

app.integrations.magicqueue
  -> QueueClient("orders").subscribe("order.created", handle_order_created)
```

Before support packs exist, these should be reported as unknown-library patterns or unresolved third-party calls, not as confidently resolved event semantics.

## Desired future `support_pack` behavior

After research produces support packs, the analyzer should be able to map library-specific calls to event graph edges:

- `strangebus.emit("order.created", payload)` creates an `EVENT_EMITS` edge from the caller to event `order.created`.
- `strangebus.route("order.created")(handler)` creates an `EVENT_HANDLES` edge from event `order.created` to `handler`.
- `QueueClient("orders").publish("order.created", payload)` creates an `EVENT_EMITS` edge from the caller to event `orders:order.created` or canonical event `order.created` with channel metadata.
- `QueueClient("orders").subscribe("order.created", handle_order_created)` creates an `EVENT_HANDLES` edge from event `orders:order.created` to `handle_order_created`.

## Expected research requests

A good unknown-library workflow should output something close to:

```json
[
  {
    "package": "strangebus-sdk",
    "import_names": ["strangebus"],
    "ecosystem": "python",
    "evidence": [
      "import strangebus",
      "strangebus.emit(...)"
    ],
    "reason": "Unknown third-party event bus patterns require support pack research."
  },
  {
    "package": "magicqueue-client",
    "import_names": ["magicqueue"],
    "ecosystem": "python",
    "evidence": [
      "from magicqueue import QueueClient",
      "QueueClient.publish(...)",
      "QueueClient.subscribe(...)"
    ],
    "reason": "Unknown third-party queue client patterns require support pack research."
  }
]
```

## Intentional analyzer traps

- `internal-utils-dev` looks like a third-party import but is marked dev-only/internal.
- `tests/stubs/strangebus.py` and `tests/stubs/magicqueue.py` exist only so tests run without external packages; they should not make the app imports local.
- `app/integrations/strangebus.py` has the same filename as the top-level import, but the top-level `import strangebus` should still be treated as third-party-looking.
- Comments and README examples should not be counted as executable evidence unless the analyzer explicitly records documentation evidence separately.

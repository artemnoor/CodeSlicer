# Polyglot Impact Analysis Fixture

This fixture is intentionally small but tricky. It is designed to test a polyglot impact-analysis system that can build a structural graph for Python + TypeScript + Go + Java, while being honest about confidence and resolver depth.

## Services

```text
polyglot_project/
  services/
    orders-python/          # FastAPI service with runnable pytest coverage
    billing-go/             # Go structural chain only
    notifications-java/     # Java structural chain only
    web-frontend/           # TypeScript endpoint bridge + component/hook/test chain
  contracts/
    openapi.json
```

## Expected strong semantic chain

The analyzer should resolve the Python runtime/service chain with high confidence:

```text
POST /api/orders
  -> app.api.create_order
  -> app.service.OrderService.create_order
  -> app.repository.OrderRepository.save
```

Expected strong edge:

```text
Python OrderService.create_order -> OrderRepository.save
```

This chain is intentionally backed by a runnable FastAPI test:

```bash
cd services/orders-python
python -m pytest -q
```

## Expected TypeScript endpoint bridge

The frontend should expose route-like endpoint evidence that can be connected to matching backend/static contract evidence:

```text
src/api/orders.ts:createOrder
  -> POST /api/orders
  -> Python FastAPI POST /api/orders

src/api/billing.ts:createInvoice
  -> POST /api/billing/invoices
```

The hook/component/test chain should be visible structurally:

```text
src/__tests__/billingFlow.test.tsx
  -> BillingPanel
  -> useBilling
  -> createInvoice
  -> POST /api/billing/invoices
```

## Expected structural / limited chains

The analyzer may build low-confidence structural chains for Go and Java, but should not pretend it has deep semantic support unless such resolver support is explicitly implemented.

Go structural chain:

```text
CreateInvoiceHandler
  -> BillingService.CreateInvoice
  -> BillingRepository.SaveInvoice
```

Java structural chain:

```text
NotificationController.sendNotification
  -> NotificationService.send
  -> NotificationClient.post
```

These should be reported as structural / low-confidence unless the analyzer has a dedicated Go or Java semantic resolver.

## Forbidden false-positive links

The fixture contains similar method names across languages and layers. The analyzer must not link by substring or method name alone.

Forbidden:

```text
Go BillingRepository.SaveInvoice
  -/-> Python OrderRepository.save

Go BillingRepository.Save
  -/-> Python OrderRepository.save

Java NotificationService.send
  -/-> POST /api/billing/invoices

Java NotificationClient.post
  -/-> TypeScript createInvoice just because both involve a POST-like operation
```

## Intentional traps

- Similar method names: `save`, `Save`, `saveInvoice`, `SaveInvoice`.
- Generated files under `generated/` should be classified as generated/noise.
- Vendor-like code under `vendor/` should not be analyzed deeply.
- Test-only files live under `tests/`, `__tests__`, and `*_test.go`.
- Java code is syntactically plausible and Spring-like, but the fixture does not require a full Java build.
- Go code is syntactically plausible, but the fixture does not require a full Go build.

## Suggested ignore patterns

```text
.git/
node_modules/
target/
build/
dist/
__pycache__/
*.pyc
generated/
vendor/
```

The zip intentionally does not include `.git`, `node_modules`, `target`, `build`, `dist`, or `__pycache__`.

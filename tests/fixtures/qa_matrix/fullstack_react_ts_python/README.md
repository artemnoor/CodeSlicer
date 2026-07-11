# Impact-Analysis Test Project

This project is a **fixture** for testing fullstack impact-analysis tools.
It contains a small but realistic backend (FastAPI) and frontend (TypeScript/React)
that exercise a complete chain:

```
backend endpoint  ->  frontend API client  ->  React hook  ->  component  ->  frontend test
```

The project is intentionally NOT runnable as a real Vite/Next app — there is no
`node_modules`, no bundler, no dev server. It is purely a static corpus that
impact-analysis tools crawl to verify their graph-building logic.

---

## Layout

```
project/
  backend/
    app/
      main.py
      api/
        __init__.py
        router.py
        shop/
          __init__.py
          orders.py
          users.py
      services/
        orders.py
      repositories/
        orders.py
    tests/
      test_orders_api.py
    pyproject.toml

  frontend/
    tsconfig.json
    src/
      api/
        index.ts
        http.ts
        paths.ts
        orders.ts
        users.ts
      hooks/
        useOrders.ts
        useCheckout.ts
      components/
        OrderCreateForm.tsx
        CheckoutButton.tsx
      __tests__/
        orderFlow.test.tsx

  README.md
```

---

## Backend

### Prefix chain (declared in `app/main.py`)

```python
app.include_router(api_router, prefix="/api/v1")
api_router.include_router(shop_router, prefix="/shop")
shop_router.include_router(orders_router, prefix="/orders")
shop_router.include_router(users_router, prefix="/users")
```

This produces the following routes:

| Method | Path                                          | Handler         | Service call                       | Repository call         |
|--------|-----------------------------------------------|-----------------|------------------------------------|-------------------------|
| POST   | `/api/v1/shop/orders`                         | `create_order`  | `OrderService.create_order`        | `OrderRepository.save`  |
| POST   | `/api/v1/shop/orders/{order_id}/checkout`     | `checkout_order`| `OrderService.checkout`            | `OrderRepository.save`  |
| POST   | `/api/v1/shop/users`                          | `create_user`   | (none — handler-only)              | (none)                  |

### Run the backend tests

```bash
cd backend
python -m pytest -q
```

Requirements: Python 3.11+, FastAPI, httpx, pytest. Install with:

```bash
pip install -e ".[dev]"
```

---

## Frontend

### Path helpers (`src/api/paths.ts`)

```ts
export const API_PREFIX  = "/api/v1";
export const SHOP_PREFIX = "shop";

orderCollectionPath()  // -> "/api/v1/shop/orders"
checkoutPath(id)       // -> `/api/v1/shop/orders/${id}/checkout`
userCollectionPath()   // -> "/api/v1/shop/users"
```

### HTTP wrappers (`src/api/http.ts`)

- `apiFetch<T>(path, options)` — thin `fetch` wrapper with JSON helpers.
- `apiClient.post<T>(path, body, options?)` — axios-like facade that delegates
  to `apiFetch`.

### Barrel exports (`src/api/index.ts`)

```ts
export { createOrder, checkoutOrder, saveOrderDraft } from "./orders";
export { createUser } from "./users";
```

Components and hooks import exclusively through `@/api`, so impact-analysis
tools MUST resolve through the barrel.

### Path alias (`tsconfig.json`)

```json
"paths": { "@/*": ["src/*"] }
```

---

## Expected impact chains

The impact-analysis tool under test should produce the following chains when
given the appropriate seed symbol.

### Chain A — order creation

```
OrderRepository.save
  <- OrderService.create_order        (app/services/orders.py)
  <- create_order                     (app/api/shop/orders.py)
  <- POST /api/v1/shop/orders         (registered on orders_router)
  <- createOrder()                    (frontend src/api/orders.ts)
  <- createOrder re-exported          (frontend src/api/index.ts)
  <- useOrders.createOrder            (frontend src/hooks/useOrders.ts)
  <- OrderCreateForm.handleSubmit     (frontend src/components/OrderCreateForm.tsx)
  <- orderFlow.test.tsx               (frontend src/__tests__/orderFlow.test.tsx)
```

### Chain B — checkout

```
POST /api/v1/shop/orders/{order_id}/checkout   (registered on orders_router)
  <- checkout_order                            (app/api/shop/orders.py)
  <- OrderService.checkout                     (app/services/orders.py)
  <- checkoutOrder(id)                         (frontend src/api/orders.ts)
  <- checkoutOrder re-exported                 (frontend src/api/index.ts)
  <- useCheckout.checkout                      (frontend src/hooks/useCheckout.ts)
  <- CheckoutButton.handleClick                (frontend src/components/CheckoutButton.tsx)
  <- orderFlow.test.tsx                        (frontend src/__tests__/orderFlow.test.tsx)
```

---

## Forbidden false positives

These edges MUST NOT appear in the impact graph:

1. **`createUser` (`src/api/users.ts`) must NOT link to `OrderRepository.save`.**
   - The users route (`POST /api/v1/shop/users`) is handled by `create_user`
     in `app/api/shop/users.py`, which writes to an in-memory `_USER_STORE`
     and never touches `OrderRepository`.
   - Any tool that reports `OrderRepository.save -> createUser` (or the reverse)
     has a false positive.

2. **`saveOrderDraft` must NOT link to `OrderRepository.save` (backend).**
   - `saveOrderDraft` exists in BOTH layers as a trap:
     - `app/repositories/orders.py::save_order_draft` — a free function with no
       callers in the production code path.
     - `src/api/orders.ts::saveOrderDraft` — a frontend helper that posts to a
       non-existent `/api/v1/shop/orders/draft` endpoint.
   - Neither of these is reachable from `create_order` or `OrderRepository.save`.
   - A tool that matches on the `save` substring and links them is broken.

3. **Frontend `${id}` template literal vs backend `{order_id}` path param.**
   - `checkoutPath(orderId)` returns `` `/api/v1/shop/orders/${orderId}/checkout` ``.
   - The FastAPI route is declared as `/{order_id}/checkout`.
   - A correct impact-analysis tool must normalise these two representations
     and link them; a naive string-equality matcher will miss the edge.

4. **Barrel indirection.**
   - Components import `createOrder` and `checkoutOrder` from `@/api`, not from
     `@/api/orders`. Tools that do not follow re-exports will break the chain.

---

## Running

### Backend tests

```bash
cd backend
pip install -e ".[dev]"
python -m pytest -q
```

### Frontend tests

Frontend tests are written in Vitest + React Testing Library style but are NOT
expected to run — there is no `package.json` and no `node_modules`. They exist
only as static analysis targets.

---

## Excluded from the zip

- `node_modules/`
- `.git/`
- `dist/`, `build/`, `.next/`
- `__pycache__/`, `*.pyc`

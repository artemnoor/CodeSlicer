# Impact-Analysis Test Backend

Маленький FastAPI backend, специально спроектированный как «песочница»
для проверки статических/динамических impact-analysis систем. В код
намеренно вшиты несколько ловушек (alias-доступ к репозиторию,
«забытый» legacy-репозиторий, коллизия переменной `router`,
многоуровневая цепочка `include_router`), которые плохой анализатор
должен либо пропустить (false negative), либо ошибочно разрешить
(false positive).

## Стек

* Python 3.11+
* FastAPI
* pytest (+ `httpx` для `TestClient`)
* **без** Docker
* **без** базы данных — только in-memory storage

## Запуск

```bash
cd backend
pip install -e ".[test]"
python -m pytest -q
```

Все тесты должны проходить.

## Структура

```
backend/
  app/
    __init__.py
    main.py
    api/
      __init__.py           # re-export router
      router.py             # /api  -> include_router(v1_router, prefix="/v1")
      v1/
        __init__.py         # re-export router
        router.py           # /v1   -> include_router(orders, prefix="/shop"),
                              #                  include_router(users)
        orders.py           # router = APIRouter(prefix="/orders")
        users.py            # router = APIRouter(prefix="/users")  <-- collision
    services/
      __init__.py
      orders.py             # OrderService (использует aliases)
      payments.py           # PaymentService
      audit.py              # AuditService
    repositories/
      __init__.py
      orders.py             # OrderRepository + LegacyOrderRepository (ловушка)
      users.py
      billing.py
    uow.py                  # OrderUnitOfWork
    dependencies.py         # FastAPI dependency providers
  tests/
    __init__.py
    conftest.py             # autouse reset_dependencies()
    test_orders_api.py      # 4 обязательных теста
    test_order_service.py
    test_checkout_flow.py
  pyproject.toml
  README.md
```

## Ожидаемые impact chains

### 1. Create order chain

```
POST /api/v1/shop/orders
  -> app.api.v1.orders.create_order
  -> app.api.orders.router (POST /orders)         [prefix /shop/orders]
  -> app.api.v1.router.include_router(orders_router, prefix="/shop")
  -> app.api.router.include_router(v1_router,     prefix="/v1")
  -> app.main.include_router(api_router,          prefix="/api")
  -> Depends(get_order_service)
  -> OrderService.create_order
  -> self.repositories["orders"].save(order)      <-- alias-trap
  -> OrderRepository.save
```

Точки, которые **должны** попасть в impact-set изменения
`OrderRepository.save`:

* `app.api.v1.orders.create_order`
* `app.api.v1.orders.create_checkout` (косвенно — через `complete_checkout`,
  который вызывает `mark_paid`, но не `save`; см. ниже)
* `OrderService.create_order`
* `OrderService.refresh_order` (через `self.nested_alias["orders"].save`)
* `OrderRepository.save`

### 2. Checkout chain

```
POST /api/v1/shop/orders/{order_id}/checkout
  -> app.api.v1.orders.create_checkout
  -> Depends(get_order_service)
  -> OrderService.complete_checkout
  -> self.uow.orders.find_by_id                   <-- OrderRepository.find_by_id
  -> self.payment_service.charge_for_order
  -> BillingRepository.save_payment_attempt       <-- inside PaymentService
  -> self.uow.orders.mark_paid                    <-- OrderRepository.mark_paid
  -> self.uow.commit                              <-- OrderUnitOfWork.commit
```

Точки, которые **должны** попасть в impact-set изменения, например,
`OrderUnitOfWork.commit`:

* `app.api.v1.orders.create_checkout`
* `OrderService.complete_checkout`
* `OrderUnitOfWork.commit`

Точки, которые **должны** попасть в impact-set изменения
`BillingRepository.save_payment_attempt`:

* `app.api.v1.orders.create_checkout`
* `OrderService.complete_checkout`
* `PaymentService.charge_for_order`
* `BillingRepository.save_payment_attempt`

### 3. Prefix chain

```
app.main           include_router(api_router, prefix="/api")
  -> app.api.router include_router(v1_router,  prefix="/v1")
       -> app.api.v1.router include_router(orders_router, prefix="/shop")
            -> app.api.v1.orders.router (prefix="/orders")
                 -> POST /orders         => /api/v1/shop/orders
                 -> POST /{id}/checkout  => /api/v1/shop/orders/{id}/checkout
       -> app.api.v1.router include_router(users_router)   # без /shop
            -> app.api.v1.users.router (prefix="/users")
                 -> POST /users         => /api/v1/users
```

## Forbidden false positives

Корректный impact-analysis инструмент **НЕ** должен включать следующие
связи в impact-set:

1. **`POST /api/v1/users` не должен зависеть от `OrderRepository.save`.**
   `app.api.v1.users` объявляет собственный `router = APIRouter()` (та
   же переменная, что и в `app.api.v1.orders` — это ловушка коллизии
   имён). Однако ни один handler модуля `users` не импортирует и не
   вызывает ничего из `app.repositories.orders`. Соответственно,
   изменение `OrderRepository.save` не должно «задевать» users-роуты.

2. **`LegacyOrderRepository.save` не должен попадать в `create_order` chain.**
   Класс `LegacyOrderRepository` определён в
   `app/repositories/orders.py` рядом с активным `OrderRepository` и
   имеет метод `save` с такой же сигнатурой. Однако `OrderService`
   **никогда** не инстанцирует и не вызывает `LegacyOrderRepository`.
   Анализатор, который матчит по имени метода `save` без учёта
   ресивера, получит false positive.

3. **`AuditService.log` не должен попадать в checkout-цепочку**
   как точка изменения для `OrderRepository.save`. `AuditService`
   действительно вызывается из `OrderService.create_order` и
   `OrderService.complete_checkout`, но он не имеет никакого
   отношения к `OrderRepository.save`.

4. **Изменение `UserRepository.save` не должно влиять на
   `POST /api/v1/shop/orders`** и наоборот.

## Ловушки (для анализатора)

| Ловушка | Где | Что должен сделать анализатор |
|---|---|---|
| Dict-alias доступ | `self.repositories["orders"].save(order)` в `OrderService.create_order` | Разрешить alias через dataflow: `self.repositories = {"orders": uow.orders}` => `OrderRepository.save` |
| Nested dict-alias | `self.nested_alias["orders"].save(order)` в `OrderService.refresh_order` | То же, но через другое имя атрибута |
| Legacy repo | `LegacyOrderRepository.save` определён, но не вызывается | Не включать в impact-set `create_order` |
| Router variable collision | `router = APIRouter()` в `orders.py` и в `users.py` | Различать роутеры по *пути импорта*, а не по имени переменной |
| Multi-level prefix chain | `/api` -> `/v1` -> `/shop` -> `/orders` | Корректно собирать полный путь маршрута |
| Re-export через `__init__.py` | `app/api/__init__.py`, `app/api/v1/__init__.py` | Следовать за re-export при построении графа импортов |

## Тесты

Четыре обязательных теста (имена фиксированы требованием):

| Тест | Файл | Что проверяет |
|---|---|---|
| `test_create_order_route_hits_service_chain` | `tests/test_orders_api.py` | Маршрут `POST /api/v1/shop/orders` действительно вызывает `OrderRepository.save` |
| `test_checkout_route_uses_uow_and_payment` | `tests/test_orders_api.py` | Маршрут checkout проходит через `find_by_id`, `mark_paid`, `charge_for_order`, `save_payment_attempt`, `commit` |
| `test_order_service_create_order_uses_active_repository_not_legacy` | `tests/test_orders_api.py` | `OrderService.create_order` вызывает активный репозиторий, а не `LegacyOrderRepository` |
| `test_users_route_does_not_touch_orders_repository` | `tests/test_orders_api.py` | `POST /api/v1/users` не вызывает `OrderRepository.save` |

Дополнительные тесты (в `test_order_service.py` и `test_checkout_flow.py`)
проверяют порядок вызовов в checkout-цепочке и обе alias-формы.

## Запуск без установки

```bash
cd backend
pip install fastapi uvicorn pydantic pytest httpx
python -m pytest -q
```

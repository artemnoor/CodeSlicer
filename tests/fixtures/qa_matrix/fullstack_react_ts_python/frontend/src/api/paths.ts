/**
 * Centralised API path helpers.
 *
 * Keeping the prefix chain in ONE place mirrors the backend router chain:
 *     app.include_router(api_router,  prefix="/api/v1")
 *     api_router.include_router(shop_router, prefix="/shop")
 *     shop_router.include_router(orders_router, prefix="/orders")
 *
 * Impact-analysis tools should follow the call chain:
 *     orderCollectionPath()  -> "/api/v1/shop/orders"
 *     checkoutPath(id)       -> "/api/v1/shop/orders/${id}/checkout"
 */

export const API_PREFIX = "/api/v1";
export const SHOP_PREFIX = "shop";
export const ORDERS_PREFIX = "orders";
export const USERS_PREFIX = "users";

/** Build the canonical shop base path, e.g. "/api/v1/shop". */
export function shopBasePath(): string {
  return `${API_PREFIX}/${SHOP_PREFIX}`;
}

/** Build the order collection path, e.g. "/api/v1/shop/orders". */
export function orderCollectionPath(): string {
  return `${shopBasePath()}/${ORDERS_PREFIX}`;
}

/**
 * Build the checkout path for a single order.
 *
 * NOTE: frontend uses ${id} template interpolation while the backend route is
 * declared as /{order_id}/checkout. This stylistic difference is intentional
 * so impact-analysis tools must NOT do naive string equality on the path.
 */
export function checkoutPath(orderId: string): string {
  return `${orderCollectionPath()}/${orderId}/checkout`;
}

/** Build the users collection path, e.g. "/api/v1/shop/users". */
export function userCollectionPath(): string {
  return `${shopBasePath()}/${USERS_PREFIX}`;
}

/**
 * Orders API client.
 *
 * Trace these calls when doing impact analysis:
 *     createOrder(payload) -> apiClient.post(orderCollectionPath(), payload)
 *                            -> POST /api/v1/shop/orders
 *     checkoutOrder(id)    -> apiClient.post(checkoutPath(id), {})
 *                            -> POST /api/v1/shop/orders/${id}/checkout
 */

import { apiClient } from "./http";
import { orderCollectionPath, checkoutPath } from "./paths";

export interface OrderItemPayload {
  sku: string;
  quantity: number;
  unitPrice: number;
}

export interface OrderCreatePayload {
  customerId: string;
  items: OrderItemPayload[];
}

export interface Order {
  id: string;
  customerId: string;
  total: number;
  status: string;
}

export interface CheckoutResult {
  orderId: string;
  status: string;
  paymentRef: string;
}

/** Create a new order via POST /api/v1/shop/orders. */
export async function createOrder(payload: OrderCreatePayload): Promise<Order> {
  // Map camelCase client payload to snake_case backend fields.
  const body = {
    customer_id: payload.customerId,
    items: payload.items.map((item) => ({
      sku: item.sku,
      quantity: item.quantity,
      unit_price: item.unitPrice,
    })),
  };
  return apiClient.post<Order>(orderCollectionPath(), body);
}

/** Checkout an existing order via POST /api/v1/shop/orders/${id}/checkout. */
export async function checkoutOrder(orderId: string): Promise<CheckoutResult> {
  return apiClient.post<CheckoutResult>(checkoutPath(orderId), {});
}

/**
 * Trap: similar name that should NOT be linked to OrderRepository.save.
 * Impact-analysis tools must avoid matching on the "save" substring.
 */
export async function saveOrderDraft(draft: {
  customerId: string;
  items: OrderItemPayload[];
}): Promise<{ id: string; status: string }> {
  // Pretend to POST to a draft endpoint that does NOT exist on the backend.
  return apiClient.post<{ id: string; status: string }>(
    `${orderCollectionPath()}/draft`,
    draft,
  );
}

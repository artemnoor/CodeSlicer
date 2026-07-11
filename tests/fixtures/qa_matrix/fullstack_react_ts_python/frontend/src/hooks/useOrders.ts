/**
 * useOrders hook.
 *
 * Exposes `createOrder` from the API layer to React components.
 * Impact-analysis chain:
 *     useOrders.createOrder -> createOrder (api/orders.ts) -> apiClient.post
 *     -> orderCollectionPath() -> POST /api/v1/shop/orders
 */

import { useCallback, useState } from "react";

import { createOrder as createOrderApi } from "@/api";
import type { Order, OrderCreatePayload } from "@/api";

export interface UseOrdersResult {
  createOrder: (payload: OrderCreatePayload) => Promise<Order>;
  loading: boolean;
  error: Error | null;
  lastOrder: Order | null;
}

export function useOrders(): UseOrdersResult {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastOrder, setLastOrder] = useState<Order | null>(null);

  const createOrder = useCallback(async (payload: OrderCreatePayload): Promise<Order> => {
    setLoading(true);
    setError(null);
    try {
      const order = await createOrderApi(payload);
      setLastOrder(order);
      return order;
    } catch (err) {
      const wrapped = err instanceof Error ? err : new Error(String(err));
      setError(wrapped);
      throw wrapped;
    } finally {
      setLoading(false);
    }
  }, []);

  return { createOrder, loading, error, lastOrder };
}

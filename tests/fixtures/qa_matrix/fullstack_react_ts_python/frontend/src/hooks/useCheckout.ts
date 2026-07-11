/**
 * useCheckout hook.
 *
 * Exposes `checkoutOrder` from the API layer to React components.
 * Impact-analysis chain:
 *     useCheckout.checkout -> checkoutOrder (api/orders.ts) -> apiClient.post
 *     -> checkoutPath(id) -> POST /api/v1/shop/orders/${id}/checkout
 */

import { useCallback, useState } from "react";

import { checkoutOrder as checkoutOrderApi } from "@/api";
import type { CheckoutResult } from "@/api";

export interface UseCheckoutResult {
  checkout: (orderId: string) => Promise<CheckoutResult>;
  loading: boolean;
  error: Error | null;
  lastResult: CheckoutResult | null;
}

export function useCheckout(): UseCheckoutResult {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastResult, setLastResult] = useState<CheckoutResult | null>(null);

  const checkout = useCallback(async (orderId: string): Promise<CheckoutResult> => {
    setLoading(true);
    setError(null);
    try {
      const result = await checkoutOrderApi(orderId);
      setLastResult(result);
      return result;
    } catch (err) {
      const wrapped = err instanceof Error ? err : new Error(String(err));
      setError(wrapped);
      throw wrapped;
    } finally {
      setLoading(false);
    }
  }, []);

  return { checkout, loading, error, lastResult };
}

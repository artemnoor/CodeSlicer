/**
 * CheckoutButton component.
 *
 * Impact-analysis chain:
 *     CheckoutButton -> useCheckout -> checkoutOrder (api/orders.ts)
 *     -> apiClient.post(checkoutPath(id), {})
 *     -> POST /api/v1/shop/orders/${id}/checkout
 *     -> backend checkout_order -> OrderService.checkout
 */

import { useState } from "react";

import { useCheckout } from "@/hooks/useCheckout";

export interface CheckoutButtonProps {
  orderId: string;
  onCheckoutComplete?: (paymentRef: string) => void;
}

export function CheckoutButton({ orderId, onCheckoutComplete }: CheckoutButtonProps) {
  const { checkout, loading, error } = useCheckout();
  const [paymentRef, setPaymentRef] = useState<string | null>(null);

  const handleClick = async () => {
    const result = await checkout(orderId);
    setPaymentRef(result.paymentRef);
    onCheckoutComplete?.(result.paymentRef);
  };

  return (
    <div>
      <button type="button" onClick={handleClick} disabled={loading || !orderId}>
        {loading ? "Checking out..." : "Checkout"}
      </button>
      {error && <p role="alert">Error: {error.message}</p>}
      {paymentRef && <p data-testid="payment-ref">{paymentRef}</p>}
    </div>
  );
}

export default CheckoutButton;

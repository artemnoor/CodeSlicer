/**
 * OrderCreateForm component.
 *
 * Impact-analysis chain:
 *     OrderCreateForm -> useOrders -> createOrder (api/orders.ts)
 *     -> apiClient.post(orderCollectionPath(), payload)
 *     -> POST /api/v1/shop/orders
 *     -> backend create_order -> OrderService.create_order -> OrderRepository.save
 */

import { FormEvent, useState } from "react";

import { useOrders } from "@/hooks/useOrders";
import type { OrderItemPayload } from "@/api";

export interface OrderCreateFormProps {
  onCreated?: (orderId: string) => void;
}

export function OrderCreateForm({ onCreated }: OrderCreateFormProps) {
  const { createOrder, loading, error } = useOrders();
  const [customerId, setCustomerId] = useState("");
  const [sku, setSku] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [unitPrice, setUnitPrice] = useState(0);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const items: OrderItemPayload[] = [
      { sku, quantity: Number(quantity), unitPrice: Number(unitPrice) },
    ];
    const order = await createOrder({ customerId, items });
    onCreated?.(order.id);
  };

  return (
    <form onSubmit={handleSubmit} aria-label="order-create-form">
      <label>
        Customer ID
        <input
          value={customerId}
          onChange={(e) => setCustomerId(e.target.value)}
          required
        />
      </label>
      <label>
        SKU
        <input value={sku} onChange={(e) => setSku(e.target.value)} required />
      </label>
      <label>
        Quantity
        <input
          type="number"
          min={1}
          value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value))}
          required
        />
      </label>
      <label>
        Unit price
        <input
          type="number"
          min={0}
          step={0.01}
          value={unitPrice}
          onChange={(e) => setUnitPrice(Number(e.target.value))}
          required
        />
      </label>
      <button type="submit" disabled={loading}>
        {loading ? "Creating..." : "Create order"}
      </button>
      {error && <p role="alert">Error: {error.message}</p>}
    </form>
  );
}

export default OrderCreateForm;

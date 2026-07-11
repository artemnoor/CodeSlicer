export type CreateOrderPayload = {
  id: string;
  items: string[];
};

const API_PREFIX = "/api";

export async function createOrder(payload: CreateOrderPayload) {
  const response = await fetch(`${API_PREFIX}/orders`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  return response.json();
}

export async function saveOrderDraft(payload: CreateOrderPayload) {
  // Trap: similar name to repository save methods, but it does not hit /api/orders.
  return { draft: true, payload };
}

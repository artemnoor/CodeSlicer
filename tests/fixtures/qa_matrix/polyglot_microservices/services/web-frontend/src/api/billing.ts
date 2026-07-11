export type CreateInvoicePayload = {
  orderId: string;
  amountCents: number;
};

const API_PREFIX = "/api";
const BILLING_SEGMENT = "billing";

export async function createInvoice(payload: CreateInvoicePayload) {
  const response = await fetch(`${API_PREFIX}/${BILLING_SEGMENT}/invoices`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  return response.json();
}

export async function saveInvoice(payload: CreateInvoicePayload) {
  // Trap: same semantic word as Go SaveInvoice, but this is a frontend-only draft helper.
  return { localOnly: true, payload };
}

import { createInvoice, type CreateInvoicePayload } from "@api/billing";

export function useBilling() {
  async function submitInvoice(payload: CreateInvoicePayload) {
    return createInvoice(payload);
  }

  return { submitInvoice };
}

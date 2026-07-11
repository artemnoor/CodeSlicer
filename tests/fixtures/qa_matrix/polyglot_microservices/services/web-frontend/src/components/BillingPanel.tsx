import { useState } from "react";

import { useBilling } from "@hooks/useBilling";

export function BillingPanel() {
  const { submitInvoice } = useBilling();
  const [status, setStatus] = useState("idle");

  async function handleCreateInvoice() {
    setStatus("submitting");
    await submitInvoice({ orderId: "ord_42", amountCents: 1999 });
    setStatus("submitted");
  }

  return (
    <section aria-label="Billing panel">
      <button type="button" onClick={handleCreateInvoice}>
        Create invoice
      </button>
      <p>{status}</p>
    </section>
  );
}

import { render, screen, fireEvent } from "@testing-library/react";

import { BillingPanel } from "@components/BillingPanel";

test("billing panel submits invoice through hook and API client", async () => {
  render(<BillingPanel />);

  fireEvent.click(screen.getByRole("button", { name: /create invoice/i }));

  expect(await screen.findByText("submitted")).toBeInTheDocument();
});

/**
 * Frontend test for the full order flow.
 *
 * This file is the END of the impact-analysis chain on the frontend side:
 *     orderFlow.test.tsx
 *       -> OrderCreateForm -> useOrders -> createOrder -> orderCollectionPath
 *       -> CheckoutButton  -> useCheckout -> checkoutOrder -> checkoutPath
 *
 * A change to OrderRepository.save on the backend should be reported as
 * impacting this test file through that chain.
 *
 * NOTE: this file uses JSX and React Testing Library idioms but does not
 * require a real test runner to be installed. Impact-analysis tools should
 * still treat it as a test entrypoint.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { OrderCreateForm } from "@/components/OrderCreateForm";
import { CheckoutButton } from "@/components/CheckoutButton";

import * as ordersApi from "@/api/orders";

describe("order flow: create + checkout", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("creates an order and then checks it out", async () => {
    const createOrderSpy = vi
      .spyOn(ordersApi, "createOrder")
      .mockResolvedValue({
        id: "ord_test_1",
        customerId: "cust_1",
        total: 9.99,
        status: "draft",
      });

    const checkoutOrderSpy = vi
      .spyOn(ordersApi, "checkoutOrder")
      .mockResolvedValue({
        orderId: "ord_test_1",
        status: "paid",
        paymentRef: "pay_test_1",
      });

    const onCreated = vi.fn();
    render(<OrderCreateForm onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText("Customer ID"), {
      target: { value: "cust_1" },
    });
    fireEvent.change(screen.getByLabelText("SKU"), {
      target: { value: "SKU-1" },
    });
    fireEvent.change(screen.getByLabelText("Quantity"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText("Unit price"), {
      target: { value: "3.33" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create order/i }));

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith("ord_test_1");
    });
    expect(createOrderSpy).toHaveBeenCalledTimes(1);
    expect(createOrderSpy).toHaveBeenCalledWith({
      customerId: "cust_1",
      items: [{ sku: "SKU-1", quantity: 3, unitPrice: 3.33 }],
    });

    const onCheckoutComplete = vi.fn();
    render(<CheckoutButton orderId="ord_test_1" onCheckoutComplete={onCheckoutComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));

    await waitFor(() => {
      expect(screen.getByTestId("payment-ref")).toHaveTextContent("pay_test_1");
    });
    expect(checkoutOrderSpy).toHaveBeenCalledWith("ord_test_1");
    expect(onCheckoutComplete).toHaveBeenCalledWith("pay_test_1");
  });
});

package billing

import (
	"context"
	"testing"
)

func TestCreateInvoiceCallsRepository(t *testing.T) {
	repository := NewBillingRepository()
	service := NewBillingService(repository)

	invoice, err := service.CreateInvoice(context.Background(), CreateInvoiceRequest{OrderID: "ord_42", AmountCents: 1999})
	if err != nil {
		t.Fatal(err)
	}

	if invoice.ID != "inv_ord_42" {
		t.Fatalf("unexpected invoice id: %s", invoice.ID)
	}
}

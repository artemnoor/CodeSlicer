package billing

import "context"

type Invoice struct {
	ID          string `json:"id"`
	OrderID     string `json:"orderId"`
	AmountCents int64  `json:"amountCents"`
}

type BillingRepository struct {
	invoices map[string]*Invoice
}

func NewBillingRepository() *BillingRepository {
	return &BillingRepository{invoices: make(map[string]*Invoice)}
}

func (r *BillingRepository) SaveInvoice(ctx context.Context, invoice *Invoice) (*Invoice, error) {
	r.invoices[invoice.ID] = invoice
	return invoice, nil
}

func (r *BillingRepository) Save(ctx context.Context, value any) error {
	// Trap: generic Save should not be linked to Python OrderRepository.save.
	return nil
}

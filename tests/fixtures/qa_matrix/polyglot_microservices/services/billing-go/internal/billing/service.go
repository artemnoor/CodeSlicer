package billing

import (
	"context"
	"fmt"
)

type BillingService struct {
	repository *BillingRepository
}

func NewBillingService(repository *BillingRepository) *BillingService {
	return &BillingService{repository: repository}
}

func (s *BillingService) CreateInvoice(ctx context.Context, request CreateInvoiceRequest) (*Invoice, error) {
	invoice := &Invoice{
		ID:          fmt.Sprintf("inv_%s", request.OrderID),
		OrderID:     request.OrderID,
		AmountCents: request.AmountCents,
	}

	return s.repository.SaveInvoice(ctx, invoice)
}

func (s *BillingService) Save(ctx context.Context, value any) error {
	// Trap: similar to Python OrderRepository.save, but unrelated.
	return s.repository.Save(ctx, value)
}

package billing

import (
	"encoding/json"
	"net/http"
)

type CreateInvoiceRequest struct {
	OrderID     string `json:"orderId"`
	AmountCents int64  `json:"amountCents"`
}

func CreateInvoiceHandler(service *BillingService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var request CreateInvoiceRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		invoice, err := service.CreateInvoice(r.Context(), request)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.Header().Set("content-type", "application/json")
		_ = json.NewEncoder(w).Encode(invoice)
	}
}

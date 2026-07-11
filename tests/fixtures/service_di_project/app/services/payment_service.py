class PaymentService:
    def __init__(self, payment_repository, gateway):
        self.payment_repository = payment_repository
        self.gateway = gateway
        
    def charge(self, payment):
        self.payment_repository.save_payment(payment)
        self.gateway.charge_card(payment)

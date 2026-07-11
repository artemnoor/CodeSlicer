class OrderService:
    def __init__(self, repository, email_adapter):
        self.repository = repository
        self.email_adapter = email_adapter
        
    def place_order(self, order):
        self.repository.save(order)
        self.email_adapter.send_email(
            recipient="user@example.com",
            subject="Order placed",
            body="Thank you"
        )

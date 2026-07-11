class OrderService:
    def __init__(self, payment_service, notification_service, audit_service):
        self.payment_service = payment_service
        self.notification_service = notification_service
        self.audit_service = audit_service
        
    def create_order(self, order):
        self.payment_service.charge(order)
        self.notification_service.notify_order_created(order)
        self.audit_service.record(order)

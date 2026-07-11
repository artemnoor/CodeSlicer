from app.repositories.payment_repository import PaymentRepository
from app.repositories.audit_repository import AuditRepository
from app.adapters.payment_gateway import PaymentGateway
from app.adapters.email_adapter import EmailAdapter
from app.adapters.sms_adapter import SmsAdapter
from app.services.payment_service import PaymentService
from app.services.notification_service import NotificationService
from app.services.audit_service import AuditService
from app.services.order_service import OrderService


class Container:
    def __init__(self):
        self.payment_repo = PaymentRepository()
        self.audit_repo = AuditRepository()
        self.gateway = PaymentGateway()
        self.email_adapter = EmailAdapter()
        self.sms_adapter = SmsAdapter()
        
        self.payment_service = PaymentService(payment_repository=self.payment_repo, gateway=self.gateway)
        self.notification_service = NotificationService(email_adapter=self.email_adapter, sms_adapter=self.sms_adapter)
        self.audit_service = AuditService(audit_repository=self.audit_repo)
        
        self.order_service = OrderService(
            payment_service=self.payment_service,
            notification_service=self.notification_service,
            audit_service=self.audit_service
        )

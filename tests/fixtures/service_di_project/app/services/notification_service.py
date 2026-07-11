class NotificationService:
    def __init__(self, email_adapter, sms_adapter):
        self.email_adapter = email_adapter
        self.sms_adapter = sms_adapter
        
    def notify_order_created(self, msg):
        self.email_adapter.send(msg)
        self.sms_adapter.send(msg)

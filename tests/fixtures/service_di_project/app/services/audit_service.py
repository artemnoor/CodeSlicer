class AuditService:
    def __init__(self, audit_repository):
        self.audit_repository = audit_repository
        
    def record(self, log):
        self.audit_repository.save(log)

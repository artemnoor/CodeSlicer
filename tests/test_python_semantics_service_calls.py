import pytest
from pathlib import Path
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.engine import resolve_graph

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "service_di_project"


def test_python_semantics_service_calls():
    graph = extract_project(FIXTURE_PATH)
    resolved = resolve_graph(graph)
    
    # helper to find an edge
    def find_edge(from_node, to_node, kind="CALLS"):
        return next(
            (e for e in resolved.edges if e.from_node == from_node
             and e.to_node == to_node
             and e.kind == kind),
            None
        )
        
    # Check edges exist
    e1 = find_edge(
        "app.services.order_service.OrderService.create_order",
        "app.services.payment_service.PaymentService.charge"
    )
    assert e1 is not None, "Missing OrderService.create_order -> PaymentService.charge"
    
    e2 = find_edge(
        "app.services.payment_service.PaymentService.charge",
        "app.repositories.payment_repository.PaymentRepository.save_payment"
    )
    assert e2 is not None, "Missing PaymentService.charge -> PaymentRepository.save_payment"
    
    e3 = find_edge(
        "app.services.payment_service.PaymentService.charge",
        "app.adapters.payment_gateway.PaymentGateway.charge_card"
    )
    assert e3 is not None, "Missing PaymentService.charge -> PaymentGateway.charge_card"
    
    e4 = find_edge(
        "app.services.notification_service.NotificationService.notify_order_created",
        "app.adapters.email_adapter.EmailAdapter.send"
    )
    assert e4 is not None, "Missing NotificationService.notify_order_created -> EmailAdapter.send"
    
    e5 = find_edge(
        "app.services.notification_service.NotificationService.notify_order_created",
        "app.adapters.sms_adapter.SmsAdapter.send"
    )
    assert e5 is not None, "Missing NotificationService.notify_order_created -> SmsAdapter.send"
    
    e6 = find_edge(
        "app.services.audit_service.AuditService.record",
        "app.repositories.audit_repository.AuditRepository.save"
    )
    assert e6 is not None, "Missing AuditService.record -> AuditRepository.save"
    
    # Assert no cross/wrong edges were generated
    # For example, notify_order_created should not target other .send methods or similar
    bad_edge = find_edge(
        "app.services.notification_service.NotificationService.notify_order_created",
        "app.repositories.audit_repository.AuditRepository.save"
    )
    assert bad_edge is None

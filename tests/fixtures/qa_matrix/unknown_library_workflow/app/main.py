"""Tiny FastAPI entrypoint used as a route-surface for static analysis.

The tests do not start a real server and do not call any external API. The
important part is that analyzers can see a normal route -> workflow chain.
"""

from fastapi import FastAPI

from app.services.workflow import OrderWorkflow

app = FastAPI(title="Unknown Library Workflow Demo")
workflow = OrderWorkflow()


@app.post("/api/orders")
def create_order(payload: dict) -> dict:
    """Create an order and publish the order.created event."""
    return workflow.create_order(payload)

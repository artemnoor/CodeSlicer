import dramatiq

@dramatiq.actor
def send_invoice(order_id):
    return order_id

def complete_checkout(order_id):
    return send_invoice.send(order_id)

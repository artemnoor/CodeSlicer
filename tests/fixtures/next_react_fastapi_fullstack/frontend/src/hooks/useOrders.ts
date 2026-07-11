import { createOrder } from '@/api'

export function useOrders() {
  function submitOrder(payload: unknown) {
    return createOrder(payload)
  }

  createOrder({ preview: true })
  return { submitOrder }
}

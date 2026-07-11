import { useOrders } from '@/hooks/useOrders'

export function OrderCreateForm() {
  const orders = useOrders()
  orders.submitOrder({ sku: 'sku-1' })
  return null
}

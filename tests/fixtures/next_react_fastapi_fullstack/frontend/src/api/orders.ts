import { apiClient } from './http'
import { orderCollectionPath } from './paths'

export function createOrder(payload: unknown) {
  return apiClient.post(orderCollectionPath(), payload)
}

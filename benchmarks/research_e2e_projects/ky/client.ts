import ky from 'ky'

export async function createOrder(payload: unknown) {
  return ky.post('/api/orders', {json: payload})
}

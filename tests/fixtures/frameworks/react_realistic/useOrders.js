import { postOrder } from './api';

export function useOrders() {
  const createOrder = (data) => {
    postOrder(data);
  };

  return { createOrder };
}

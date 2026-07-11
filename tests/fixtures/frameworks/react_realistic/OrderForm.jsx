import React from 'react';
import { useOrders } from './useOrders';

export default function OrderForm() {
  const { createOrder } = useOrders();

  const handleSubmit = () => {
    createOrder({ item: 'book' });
  };

  return (
    <button onClick={handleSubmit}>Submit</button>
  );
}

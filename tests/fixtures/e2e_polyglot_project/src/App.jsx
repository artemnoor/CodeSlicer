import React from 'react';
import { Button } from './Button';

export default function App() {
  return (
    <div>
      <Button label="Order Now" onClick={() => fetch('/orders', { method: 'POST' })} />
    </div>
  );
}

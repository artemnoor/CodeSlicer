# React fixture

```tsx
import React, { useState } from 'react'
import axios from 'axios'

export function OrdersPanel() {
  const [orders, setOrders] = useState([])
  async function loadOrders() {
    const response = await fetch('/api/orders', { method: 'GET' })
    setOrders(await response.json())
  }
  return <button onClick={loadOrders}>Load</button>
}

axios.post('/api/orders', { sku: 'A' })
```

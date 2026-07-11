import React from 'react';
import { Button } from './Button';

export default function App() {
  return (
    <div>
      <h1>Hello React</h1>
      <Button label="Click Me" onClick={() => console.log('clicked')} />
    </div>
  );
}

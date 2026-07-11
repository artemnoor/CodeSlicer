import React, { useState } from 'react';
import { postOrder } from './api';

export function useOrderSubmit() {
  const [status, setStatus] = useState("idle");
  const submit = async (item: string) => {
    setStatus("submitting");
    await postOrder({ item });
    setStatus("success");
  };
  return { status, submit };
}

export function OrderForm() {
  const { status, submit } = useOrderSubmit();
  return (
    <button onClick={() => submit("pizza")}>
      Submit {status}
    </button>
  );
}

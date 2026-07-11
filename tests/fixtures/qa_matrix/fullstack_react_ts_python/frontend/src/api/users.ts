/**
 * Users API client.
 *
 * IMPORTANT: This module is intentionally independent of orders.ts and of
 * OrderRepository. It exists as a trap to verify that user-related changes
 * do NOT propagate into the orders chain.
 */

import { apiClient } from "./http";
import { userCollectionPath } from "./paths";

export interface UserCreatePayload {
  name: string;
  email: string;
}

export interface User {
  id: string;
  name: string;
  email: string;
}

/** Create a new user via POST /api/v1/shop/users. */
export async function createUser(payload: UserCreatePayload): Promise<User> {
  return apiClient.post<User>(userCollectionPath(), payload);
}

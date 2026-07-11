/**
 * Barrel export for the API layer.
 *
 * Impact analysis must resolve the chain through this barrel:
 *     import { createOrder, checkoutOrder } from "@/api";
 * and follow it to:
 *     src/api/orders.ts -> apiClient.post -> paths -> backend route.
 */

export { createOrder, checkoutOrder, saveOrderDraft } from "./orders";
export type {
  Order,
  OrderCreatePayload,
  OrderItemPayload,
  CheckoutResult,
} from "./orders";

export { createUser } from "./users";
export type { User, UserCreatePayload } from "./users";

export { apiClient, apiFetch } from "./http";
export type { ApiClient, ApiFetchOptions } from "./http";

export {
  API_PREFIX,
  SHOP_PREFIX,
  ORDERS_PREFIX,
  USERS_PREFIX,
  shopBasePath,
  orderCollectionPath,
  checkoutPath,
  userCollectionPath,
} from "./paths";

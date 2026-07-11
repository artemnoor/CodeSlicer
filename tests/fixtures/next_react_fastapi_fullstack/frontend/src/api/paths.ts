export const API_PREFIX = '/api/v1'
export const SHOP_PREFIX = 'shop'
export const ORDERS_SEGMENT = 'orders'

export const joinPath = (first: string, second: string): string => `${first}/${second}`
export const shopPath = (): string => joinPath(API_PREFIX, SHOP_PREFIX)
export const orderCollectionPath = (): string => joinPath(shopPath(), ORDERS_SEGMENT)

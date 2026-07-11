export async function apiFetch(path: string, init?: RequestInit) {
  return fetch(path, init)
}

export const apiClient = {
  post: (path: string, body: unknown) => apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
}

/**
 * Minimal HTTP wrappers.
 *
 * `apiFetch` is a thin fetch wrapper that injects JSON headers.
 * `apiClient` is an axios-like facade with `.get`, `.post`, `.put`, `.delete`.
 *
 * Both are simulated so the project does NOT require a real bundler or
 * network stack. Tests typically inject mocks at this boundary.
 */

export interface ApiFetchOptions extends RequestInit {
  json?: unknown;
}

/** Thin fetch wrapper with JSON convenience. */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { json, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  let body: BodyInit | undefined = rest.body;
  if (json !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  const response = await fetch(path, {
    ...rest,
    headers: finalHeaders,
    body,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`API ${response.status} for ${path}: ${text}`);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }
  return (await response.json()) as T;
}

/** Axios-like client that delegates to apiFetch. */
export const apiClient = {
  async get<T>(path: string, options?: ApiFetchOptions): Promise<T> {
    return apiFetch<T>(path, { ...options, method: "GET" });
  },
  async post<T>(path: string, body?: unknown, options?: ApiFetchOptions): Promise<T> {
    return apiFetch<T>(path, { ...options, method: "POST", json: body });
  },
  async put<T>(path: string, body?: unknown, options?: ApiFetchOptions): Promise<T> {
    return apiFetch<T>(path, { ...options, method: "PUT", json: body });
  },
  async delete<T>(path: string, options?: ApiFetchOptions): Promise<T> {
    return apiFetch<T>(path, { ...options, method: "DELETE" });
  },
};

export type ApiClient = typeof apiClient;

export function post(url: string, body: unknown) {
  // Vendor-like trap. Analyzer should not inspect this deeply.
  return Promise.resolve({ url, body, vendor: true });
}

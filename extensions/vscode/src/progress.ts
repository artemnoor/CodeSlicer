export interface JsonLineProgress { type: "progress"; stage?: string; message?: string; overall_percent?: number; processed?: number; total?: number }

/** Tolerant parser: unrelated diagnostics never break an ongoing review. */
export function parseJsonLineProgress(chunk: string): JsonLineProgress[] {
  return chunk.split(/\r?\n/u).flatMap(line => {
    try {
      const parsed = JSON.parse(line) as Partial<JsonLineProgress>;
      return parsed.type === "progress" ? [parsed as JsonLineProgress] : [];
    } catch { return []; }
  });
}

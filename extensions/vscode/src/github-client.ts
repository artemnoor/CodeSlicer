export interface PullRequestReference { owner: string; repository: string; number: number }
export interface PullRequestDiff { reference: PullRequestReference; baseRef: string; diff: string }
export type FetchLike = (input: string, init?: { headers?: Record<string, string> }) => Promise<{ ok: boolean; status: number; text(): Promise<string> }>;

export function parsePullRequestUrl(value: string): PullRequestReference | undefined {
  try {
    const url = new URL(value.trim());
    if (url.hostname !== "github.com") return undefined;
    const [owner, repository, type, number, ...rest] = url.pathname.split("/").filter(Boolean);
    if (!owner || !repository || type !== "pull" || !/^\d+$/u.test(number || "") || rest.length) return undefined;
    return { owner, repository, number: Number(number) };
  } catch { return undefined; }
}

export async function fetchPullRequestDiff(reference: PullRequestReference, token: string, fetcher: FetchLike = fetch): Promise<PullRequestDiff> {
  const endpoint = `https://api.github.com/repos/${encodeURIComponent(reference.owner)}/${encodeURIComponent(reference.repository)}/pulls/${reference.number}`;
  const headers = { "Authorization": `Bearer ${token}`, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  const metadata = await fetcher(endpoint, { headers });
  if (!metadata.ok) throw new Error(`GitHub could not read this pull request (HTTP ${metadata.status}).`);
  const payload = JSON.parse(await metadata.text()) as { base?: { ref?: unknown } };
  const baseRef = typeof payload.base?.ref === "string" ? payload.base.ref : "";
  if (!baseRef) throw new Error("GitHub did not return a base branch for this pull request.");
  const diff = await fetcher(endpoint, { headers: { ...headers, "Accept": "application/vnd.github.v3.diff" } });
  if (!diff.ok) throw new Error(`GitHub could not download this pull-request diff (HTTP ${diff.status}).`);
  const text = await diff.text();
  if (!text.trim()) throw new Error("GitHub returned an empty pull-request diff.");
  return { reference, baseRef, diff: text };
}

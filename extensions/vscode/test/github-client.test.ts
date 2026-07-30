import assert from "node:assert/strict";
import test from "node:test";
import { fetchPullRequestDiff, parsePullRequestUrl } from "../src/github-client";

test("parses only canonical GitHub pull-request URLs", () => {
  assert.deepEqual(parsePullRequestUrl("https://github.com/acme/app/pull/42"), { owner: "acme", repository: "app", number: 42 });
  assert.equal(parsePullRequestUrl("https://github.com/acme/app/issues/42"), undefined);
  assert.equal(parsePullRequestUrl("https://example.com/acme/app/pull/42"), undefined);
});

test("downloads metadata then diff without exposing the OAuth token", async () => {
  const calls: Array<{ url: string; headers?: Record<string, string> }> = [];
  const fetcher = async (url: string, init?: { headers?: Record<string, string> }) => {
    calls.push({ url, headers: init?.headers });
    return calls.length === 1
      ? { ok: true, status: 200, text: async () => JSON.stringify({ base: { ref: "main" } }) }
      : { ok: true, status: 200, text: async () => "diff --git a/a.py b/a.py\n" };
  };
  const result = await fetchPullRequestDiff({ owner: "acme", repository: "app", number: 42 }, "secret-token", fetcher);
  assert.equal(result.baseRef, "main");
  assert.equal(calls.length, 2);
  assert.match(calls[1].headers?.Accept || "", /diff/u);
  assert.equal(JSON.stringify(result).includes("secret-token"), false);
});

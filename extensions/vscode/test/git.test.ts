import assert from "node:assert/strict";
import test from "node:test";
import { buildPushArgs, isPlausibleGitRemote, parseGitBranches, parseGitRemotes } from "../src/git";

test("Git cockpit parses current branches and their upstream state without evaluating names", () => {
  const branches = parseGitBranches("feature/payments\torigin/feature/payments\t*\t[ahead 2]\nmain\torigin/main\t\t[behind 1]");
  assert.deepEqual(branches, [
    { name: "feature/payments", current: true, upstream: "origin/feature/payments", tracking: "[ahead 2]" },
    { name: "main", current: false, upstream: "origin/main", tracking: "[behind 1]" }
  ]);
});

test("Git cockpit groups fetch and push URLs by remote", () => {
  assert.deepEqual(parseGitRemotes("origin\thttps://github.com/example/repo.git\tfetch\norigin\tgit@github.com:example/repo.git\tpush"), [{ name: "origin", fetchUrl: "https://github.com/example/repo.git", pushUrl: "git@github.com:example/repo.git" }]);
});

test("push arguments keep the destination as one argv element and never enable force", () => {
  assert.deepEqual(buildPushArgs("origin", "feature/payments", "review/payments", true), ["--set-upstream", "origin", "feature/payments:review/payments"]);
  assert.equal(isPlausibleGitRemote("https://github.com/example/repo.git"), true);
  assert.equal(isPlausibleGitRemote("git@github.com:example/repo.git"), true);
  assert.equal(isPlausibleGitRemote("--upload something"), false);
});

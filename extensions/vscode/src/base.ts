import { runProcess } from "./cli";

export interface BaseSelection { status: "automatic" | "selection-required" | "unavailable" | "selected"; base?: string; candidates: string[]; reason: string }

export async function detectBaseSelection(workspace: string, configured?: string): Promise<BaseSelection> {
  if (configured?.trim()) return { status: "selected", base: configured.trim(), candidates: [configured.trim()], reason: "Configured comparison branch" };
  const originHead = await runProcess("git", ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], workspace, 15_000);
  const remote = originHead.exitCode === 0 ? originHead.stdout.trim() : "";
  if (remote) return { status: "automatic", base: remote, candidates: [remote], reason: "Verified origin default branch" };
  const candidates: string[] = [];
  for (const ref of ["main", "master", "develop", "trunk", "origin/main", "origin/master", "origin/develop"]) {
    const exists = await runProcess("git", ["rev-parse", "--verify", "--quiet", ref], workspace, 15_000);
    if (exists.exitCode === 0) candidates.push(ref);
  }
  if (candidates.length === 1) return { status: "automatic", base: candidates[0], candidates, reason: "Only verified conventional base branch" };
  return { status: candidates.length ? "selection-required" : "unavailable", candidates, reason: candidates.length ? "Choose the branch to compare" : "No verified local or origin base branch" };
}

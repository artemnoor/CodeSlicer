export interface GitBranchPreview {
  name: string;
  current: boolean;
  upstream?: string;
  tracking?: string;
}

export interface GitRemotePreview { name: string; fetchUrl?: string; pushUrl?: string }

export interface PushPreview {
  source: string;
  remote: string;
  target: string;
  ahead: number;
  behind: number;
  canFastForward: boolean;
  message: string;
}

/** Parses tab-delimited `git for-each-ref` output; no names are interpreted as shell text. */
export function parseGitBranches(output: string): GitBranchPreview[] {
  return output.split(/\r?\n/u).flatMap(line => {
    const [name = "", upstream = "", head = "", tracking = ""] = line.split("\t");
    if (!name || name === "HEAD") return [];
    return [{ name, current: head.trim() === "*", upstream: upstream || undefined, tracking: tracking || undefined }];
  }).sort((a, b) => Number(b.current) - Number(a.current) || a.name.localeCompare(b.name));
}

/** Keeps one fetch and one push URL per remote for a compact, human-readable cockpit. */
export function parseGitRemotes(output: string): GitRemotePreview[] {
  const remotes = new Map<string, GitRemotePreview>();
  for (const line of output.split(/\r?\n/u)) {
    const [name, url, kind] = line.split("\t");
    if (!name || !url || (kind !== "fetch" && kind !== "push")) continue;
    const current = remotes.get(name) || { name };
    if (kind === "fetch") current.fetchUrl = url;
    else current.pushUrl = url;
    remotes.set(name, current);
  }
  return [...remotes.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function isPlausibleGitRemote(value: string): boolean {
  const remote = value.trim();
  return /^(https?:\/\/[^\s]+|ssh:\/\/[^\s]+|git@[^\s:]+:[^\s]+)$/u.test(remote);
}

export function buildPushArgs(remote: string, source: string, target: string, setUpstream: boolean): string[] {
  return [...(setUpstream ? ["--set-upstream"] : []), remote, `${source}:${target}`];
}

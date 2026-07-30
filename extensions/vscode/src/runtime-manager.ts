import { access, mkdir } from "node:fs/promises";
import { constants } from "node:fs";
import { join, resolve } from "node:path";
import { runProcess } from "./cli";
import { RuntimeState } from "./types";

export interface RuntimeStorage { fsPath: string }

/** Owns extension runtime discovery. It never downloads or starts a process by itself. */
export class CodeSlicerRuntimeManager {
  constructor(private readonly storage: RuntimeStorage) {}

  runtimePath(windows = process.platform === "win32"): string {
    return join(this.storage.fsPath, "runtime", windows ? "codeslicer.exe" : "codeslicer");
  }

  async discover(customExecutable?: string, workspace?: string): Promise<string | undefined> {
    const executable = process.platform === "win32" ? "codeslicer.exe" : "codeslicer";
    const legacyWorkspaceRuntime = workspace ? join(workspace, ".venv", process.platform === "win32" ? "Scripts" : "bin", executable) : undefined;
    for (const candidate of [customExecutable?.trim(), this.runtimePath(), legacyWorkspaceRuntime]) {
      if (!candidate) continue;
      try { await access(candidate, constants.X_OK); return resolve(candidate); } catch { /* try next */ }
    }
    return undefined;
  }

  async validate(cwd: string, customExecutable?: string): Promise<RuntimeState> {
    const executable = await this.discover(customExecutable, cwd);
    if (!executable) return {
      status: "install-unavailable", version: "Not available",
      diagnostic: "Automatic installation will be available after a signed CodeSlicer runtime is published. Choose an existing executable in Advanced settings.",
    };
    try {
      const result = await runProcess(executable, ["--help"], cwd, 20_000);
      if (result.exitCode !== 0 || !/\breview\b/u.test(result.stdout)) return { status: "incompatible", executable, version: "Not reported by CLI", diagnostic: "The selected executable does not provide the required local review command." };
      return { status: "found", executable, version: "Compatible", diagnostic: "Validated locally. CodeSlicer will run only after you choose an action." };
    } catch (error) {
      return { status: "error", executable, version: "Unknown", diagnostic: `Could not start the selected runtime: ${String(error)}` };
    }
  }

  async prepareStorage(): Promise<string> {
    const directory = join(this.storage.fsPath, "runtime");
    await mkdir(directory, { recursive: true });
    return directory;
  }
}

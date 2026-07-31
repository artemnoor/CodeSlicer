import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { runProcess } from "./cli";
import { RuntimeState } from "./types";

export interface RuntimeManifest {
  runtimeVersion: string;
  extensionCompatibility: string;
  platform: NodeJS.Platform;
  arch: string;
  files: Record<string, string>;
}

export function runtimeTarget(platform = process.platform, arch = process.arch): string | undefined {
  const target = `${platform}-${arch}`;
  return new Set(["win32-x64", "win32-arm64", "darwin-x64", "darwin-arm64", "linux-x64", "linux-arm64"]).has(target) ? target : undefined;
}

export function runtimeExecutableRelative(platform = process.platform): string {
  return join("bin", platform === "win32" ? "codeslicer.exe" : "codeslicer");
}

function sha256(value: Buffer): string { return createHash("sha256").update(value).digest("hex"); }

/** Resolves and validates the runtime embedded in this platform-specific VSIX.
 * No workspace virtualenv or PATH probing is performed. */
export class CodeSlicerRuntimeManager {
  constructor(private readonly extensionPath: string) {}

  target(): string | undefined { return runtimeTarget(); }
  runtimeRoot(target = this.target()): string | undefined { return target ? join(this.extensionPath, "runtime", target) : undefined; }
  runtimePath(): string | undefined { const root = this.runtimeRoot(); return root ? join(root, runtimeExecutableRelative()) : undefined; }

  async discover(customExecutable?: string): Promise<string | undefined> {
    // Kept solely as an advanced developer escape hatch. The bundled runtime wins.
    for (const candidate of [this.runtimePath(), customExecutable?.trim()]) {
      if (!candidate) continue;
      try { await access(candidate, constants.X_OK); return resolve(candidate); } catch { /* try next */ }
    }
    return undefined;
  }

  async readManifest(): Promise<RuntimeManifest | undefined> {
    const root = this.runtimeRoot();
    if (!root) return undefined;
    try {
      const parsed = JSON.parse(await readFile(join(root, "manifest.json"), "utf8")) as RuntimeManifest;
      const target = this.target();
      if (!target || parsed.platform !== process.platform || parsed.arch !== process.arch || !parsed.runtimeVersion || !parsed.extensionCompatibility || !parsed.files) return undefined;
      return parsed;
    } catch { return undefined; }
  }

  async validate(cwd: string, customExecutable?: string): Promise<RuntimeState> {
    const target = this.target();
    if (!target) return { status: "incompatible", version: "Not available", diagnostic: `CodeSlicer has no bundled runtime for ${process.platform}-${process.arch}. Install the matching platform VSIX; no download will be attempted.` };
    const manifest = await this.readManifest();
    const bundled = this.runtimePath();
    if (!manifest || !bundled) return { status: "install-unavailable", version: "Not available", diagnostic: `This ${target} VSIX does not contain a valid bundled runtime manifest.` };
    try {
      const relative = runtimeExecutableRelative().replace(/\\/gu, "/");
      const expected = manifest.files[relative];
      const actual = sha256(await readFile(bundled));
      if (!expected || expected !== actual) return { status: "incompatible", executable: bundled, version: manifest.runtimeVersion, diagnostic: "Bundled runtime checksum validation failed. Reinstall the matching VSIX." };
      await access(bundled, constants.X_OK);
      const result = await runProcess(bundled, ["--help"], cwd, 20_000);
      if (result.exitCode !== 0 || !/\breview\b/u.test(result.stdout) || !/\binspect\b/u.test(result.stdout)) return { status: "incompatible", executable: bundled, version: manifest.runtimeVersion, diagnostic: "Bundled runtime did not expose the required review and inspect commands." };
      return { status: "found", executable: bundled, version: manifest.runtimeVersion, diagnostic: `Bundled ${target} runtime validated locally. It starts only after an explicit action.` };
    } catch (error) {
      // A custom path is never selected automatically; it is available only for an explicit developer configuration.
      if (customExecutable?.trim()) {
        try { await access(customExecutable.trim(), constants.X_OK); return { status: "found", executable: resolve(customExecutable.trim()), version: "Advanced override", diagnostic: "Using an explicitly configured developer runtime override." }; } catch { /* report bundled failure */ }
      }
      return { status: "error", executable: bundled, version: manifest.runtimeVersion, diagnostic: `Could not validate bundled runtime: ${String(error)}` };
    }
  }

  async doctor(cwd: string, customExecutable?: string): Promise<{ ok: boolean; diagnostic: string }> {
    const runtime = await this.validate(cwd, customExecutable);
    if (!runtime.executable || runtime.status !== "found") return { ok: false, diagnostic: runtime.diagnostic };
    const result = await runProcess(runtime.executable, ["doctor", "--full"], cwd, 60_000);
    return { ok: result.exitCode === 0, diagnostic: result.stdout.trim() || result.stderr.trim() || "CodeSlicer doctor completed." };
  }

  installationAvailability(): string { return "CodeSlicer uses the bundled runtime from the matching platform VSIX. It never downloads source code, creates a virtual environment, or runs pip."; }
}

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const target = process.argv[2];
if (!target) throw new Error("Usage: node scripts/package-target.mjs <target>");
const extension = process.cwd();
const repo = join(extension, "..", "..");
const pkg = JSON.parse(readFileSync(join(extension, "package.json"), "utf8"));
const localPython = process.platform === "win32" ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python");
// Use the interpreter selected by the environment (for example actions/setup-python)
// instead of the Windows `py -3` launcher, which may select a newer Python without
// the build dependencies installed.
const python = process.env.CODESLICER_BUILD_PYTHON || (existsSync(localPython) ? localPython : (process.platform === "win32" ? "python" : "python3"));
const pythonArgs = [];
execFileSync(python, [...pythonArgs, join(repo, "scripts", "build_bundled_runtime.py"), "--target", target, "--extension-version", pkg.version], { stdio: "inherit", cwd: repo });
execFileSync(process.execPath, [join(extension, "node_modules", "@vscode", "vsce", "vsce"), "package", "--no-dependencies", "--target", target], { stdio: "inherit", cwd: extension });

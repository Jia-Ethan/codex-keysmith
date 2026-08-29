import { createHash } from "node:crypto";
import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { delimiter, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const guiDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(guiDir, "..");
const sourcePath = join(repoDir, "codex-instruct.py");
const expectedCliVersion = readFileSync(join(repoDir, "VERSION"), "utf8").trim();

const TARGETS = {
  "aarch64-apple-darwin": { platform: "darwin", arch: "arm64", extension: "" },
  "x86_64-pc-windows-msvc": { platform: "win32", arch: "x64", extension: ".exe" },
};

function argument(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? null : process.argv[index + 1];
}

function hostTarget() {
  if (process.platform === "darwin" && process.arch === "arm64") return "aarch64-apple-darwin";
  if (process.platform === "win32" && process.arch === "x64") return "x86_64-pc-windows-msvc";
  throw new Error(`Unsupported native build host: ${process.platform}/${process.arch}`);
}

const target = argument("--target") || process.env.TAURI_ENV_TARGET_TRIPLE || hostTarget();
const targetConfig = TARGETS[target];
if (!targetConfig) throw new Error(`Unsupported target: ${target}`);
if (process.platform !== targetConfig.platform || process.arch !== targetConfig.arch) {
  throw new Error(`PyInstaller sidecars must be built natively: ${target} requires ${targetConfig.platform}/${targetConfig.arch}`);
}
if (!existsSync(sourcePath)) throw new Error(`CLI source not found: ${sourcePath}`);

const source = readFileSync(sourcePath, "utf8");
const originalRestoreCommand = `    parts = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--codex-dir",
        str(codex_dir),
        "--restore-hooks",
    ]`;
const frozenRestoreCommand = `    parts = [sys.executable]
    if not getattr(sys, "frozen", False):
        parts.append(str(Path(__file__).resolve()))
    parts.extend([
        "--codex-dir",
        str(codex_dir),
        "--restore-hooks",
    ])`;
const frozenCompatible = 'if not getattr(sys, "frozen", False):';
let sidecarSource;
if (source.includes(frozenCompatible)) {
  sidecarSource = source;
} else if (source.includes(originalRestoreCommand)) {
  // Compatibility path for older CLI tags; remove after all supported tags are frozen-aware.
  sidecarSource = source.replace(originalRestoreCommand, frozenRestoreCommand);
} else {
  throw new Error("CLI restore-command contract changed; update the frozen-source compatibility check before packaging");
}

const buildRoot = join(guiDir, "src-tauri", "target", "sidecar-build", target);
const patchedSource = join(buildRoot, "codex-instruct-frozen.py");
const distDir = join(buildRoot, "dist");
const workDir = join(buildRoot, "work");
const specDir = join(buildRoot, "spec");
mkdirSync(buildRoot, { recursive: true });
rmSync(distDir, { recursive: true, force: true });
rmSync(workDir, { recursive: true, force: true });
rmSync(specDir, { recursive: true, force: true });
writeFileSync(patchedSource, sidecarSource, "utf8");

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const pythonEnv = { ...process.env, PYTHONNOUSERSITE: "1" };
delete pythonEnv.PYTHONHOME;
delete pythonEnv.PYTHONPATH;
delete pythonEnv.PYTHONUSERBASE;

const fixturePacksSource = join(repoDir, "fixture_packs");
if (!existsSync(fixturePacksSource)) {
  throw new Error(`fixture_packs directory missing: ${fixturePacksSource}`);
}

const bundleDir = join(buildRoot, "scenario-library");
mkdirSync(bundleDir, { recursive: true });
const bundleName = `codex-keysmith-scenarios-v${expectedCliVersion}.bundle`;
const bundlePath = join(bundleDir, bundleName);
const bundleResult = spawnSync(
  python,
  [
    join(repoDir, "scripts", "build_release.py"),
    "--write-scenario-bundle",
    bundlePath,
    "--repo-root",
    repoDir,
  ],
  { cwd: repoDir, encoding: "utf8", stdio: "inherit", env: pythonEnv },
);
if (bundleResult.error) throw bundleResult.error;
if (bundleResult.status !== 0) {
  throw new Error(`Scenario bundle build failed with exit code ${bundleResult.status}`);
}
if (!existsSync(bundlePath)) throw new Error(`Scenario bundle missing: ${bundlePath}`);
const bundleDigest = createHash("sha256").update(readFileSync(bundlePath)).digest("hex");
writeFileSync(
  join(bundleDir, "embedded-scenarios.json"),
  `${JSON.stringify({
    filename: bundleName,
    sha256: bundleDigest,
    tool_version: expectedCliVersion,
  }, null, 2)}\n`,
);

const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--clean",
    "--noconfirm",
    "--onefile",
    "--name",
    "codex-keysmith-cli",
    "--distpath",
    distDir,
    "--workpath",
    workDir,
    "--specpath",
    specDir,
    "--add-data",
    `${bundleDir}${delimiter}scenario-library`,
    "--add-data",
    `${fixturePacksSource}${delimiter}fixture_packs`,
    patchedSource,
  ],
  { cwd: guiDir, encoding: "utf8", stdio: "inherit", env: pythonEnv },
);
if (result.error) throw result.error;
if (result.status !== 0) {
  throw new Error(`PyInstaller failed with exit code ${result.status}. Install gui/requirements-build.txt in the active Python environment.`);
}

const builtPath = join(distDir, `codex-keysmith-cli${targetConfig.extension}`);
if (!existsSync(builtPath)) throw new Error(`PyInstaller output missing: ${builtPath}`);

const binariesDir = join(guiDir, "src-tauri", "binaries");
const destination = join(binariesDir, `codex-keysmith-cli-${target}${targetConfig.extension}`);
const temporary = `${destination}.tmp-${process.pid}`;
mkdirSync(binariesDir, { recursive: true });
copyFileSync(builtPath, temporary);
if (process.platform !== "win32") chmodSync(temporary, 0o755);
renameSync(temporary, destination);

const smoke = spawnSync(destination, ["--version"], { encoding: "utf8" });
if (smoke.error) throw smoke.error;
const reportedVersion = smoke.stdout.trim().split(/\s+/).at(-1);
if (smoke.status !== 0 || reportedVersion !== expectedCliVersion) {
  throw new Error(`Frozen sidecar version smoke failed: ${smoke.stderr || smoke.stdout}`);
}

const scenarioSmoke = spawnSync(destination, ["--scenario-list", "--lang", "en"], { encoding: "utf8" });
if (scenarioSmoke.error) throw scenarioSmoke.error;
if (scenarioSmoke.status !== 0 || !scenarioSmoke.stdout.includes("example_fixture 1.0.0: ready")) {
  throw new Error(`Frozen sidecar embedded scenario smoke failed: ${scenarioSmoke.stderr || scenarioSmoke.stdout}`);
}

const fixtureSmoke = spawnSync(destination, ["--scaffold-list", "--lang", "en"], { encoding: "utf8" });
if (fixtureSmoke.error) throw fixtureSmoke.error;
if (
  fixtureSmoke.status !== 0
  || !fixtureSmoke.stdout.includes("pytest_complete")
  || !fixtureSmoke.stdout.includes("aiml_llamaguard")
  || !fixtureSmoke.stdout.includes("compchem_cantera")
  || !fixtureSmoke.stdout.includes("cyber_pwntools")
) {
  throw new Error(
    `Frozen sidecar embedded fixture smoke failed: ${fixtureSmoke.stderr || fixtureSmoke.stdout}`,
  );
}

console.log(`Built ${destination}`);

// lib/api.js — 前端到 Rust 命令的薄封装 + 组合操作
// Rust 侧实现见 src-tauri/src/cli_runner.rs（契约未变）

import { invoke } from "@tauri-apps/api/core";
import { getSettings, normalizeCliPath } from "./settings.js";
import {
  parseStatus,
  parseDryRun,
  gatePreview,
  parseScenarioList,
  parseScenarioStatus,
  parseScenarioDeployPreview,
  parseScenarioUninstallPreview,
  parseScenarioRecoverPreview,
  parseScaffoldList,
  parseScaffoldPreview,
  extractCanonicalTarget,
} from "./parser.js";
import { beginOperation, endOperation } from "./store.js";

function invokeTrackedOperation(command, payload) {
  const operationLease = beginOperation();
  if (!operationLease) {
    return Promise.reject(
      new Error("Application exit is pending; refusing to start another backend operation."),
    );
  }
  try {
    return Promise.resolve(invoke(command, payload)).finally(() => {
      endOperation(operationLease);
    });
  } catch (error) {
    endOperation(operationLease);
    throw error;
  }
}

/** 执行 CLI 命令，返回 { stdout, stderr, exit_code, timed_out } */
export function cliRun(args, timeoutMs = 30_000) {
  const { cliPath } = getSettings();
  return invokeTrackedOperation("cli_run", {
    cliPath: cliPath || null,
    args,
    timeoutMs,
  });
}

/** 读取指定 codex 目录的 manifest JSON */
export function readManifest(codexDir) {
  return invokeTrackedOperation("read_manifest", { codexDir });
}

/** 探测 CLI，返回 { path, runtime } */
export function detectCli() {
  return invokeTrackedOperation("detect_cli");
}

/** 获取 CLI 版本 */
export function cliVersion(cliPath) {
  return invokeTrackedOperation("cli_version", { cliPath: cliPath || null });
}

/** 获取运行时类型：bundled / executable / python */
export function cliRuntime(cliPath) {
  return invokeTrackedOperation("cli_runtime", { cliPath: cliPath || null });
}

/** 验证手动 CLI 路径；未指定时保留 Rust 侧的 sidecar 优先自动探测。 */
export async function resolveCli(
  cliPath,
  {
    detect = detectCli,
    getRuntime = cliRuntime,
    getVersion = cliVersion,
  } = {},
) {
  const manualPath = normalizeCliPath(cliPath);
  if (manualPath) {
    const version = await getVersion(manualPath);
    const runtime = await getRuntime(manualPath);
    return { path: manualPath, version, runtime };
  }

  const detected = await detect();
  const path = detected?.path || null;
  return {
    path,
    version: path ? await getVersion(path) : "",
    runtime: detected?.runtime || "",
  };
}

/** 解析后的 status（自动附加默认 --codex-dir） */
export async function fetchStatus() {
  const args = ["--status"];
  const { defaultCodexDir } = getSettings();
  if (defaultCodexDir) args.push("--codex-dir", defaultCodexDir);
  args.push("--lang", "en");

  const output = await cliRun(args);
  // status 在目录存在 conflict/异常节点时也会非零退出，但 stdout 仍是完整
  // 状态报告（SPEC §5.1）。只有声明目录数和终止句均完整时才允许降级展示。
  const parsed = parseStatus(output.stdout, output.exit_code);
  parsed.exitCode = output.exit_code;
  parsed.stderr = String(output.stderr ?? "");
  parsed.timedOut = Boolean(output.timed_out);
  parsed.degraded =
    (parsed.exitCode != null && parsed.exitCode !== 0)
    || Boolean(parsed.stderr.trim());

  if (parsed.timedOut || !parsed.semanticComplete) {
    throw new CliError(output);
  }
  return parsed;
}

/**
 * dry-run 预览 + 门禁（问题 1 修复）：
 * 非零退出 / 超时 / 空输出 / blockers 一律 gate.ok=false，视图层据此阻断。
 */
export async function fetchDryRun(deployArgs) {
  const output = await cliRun([...deployArgs, "--dry-run", "--lang", "en"]);
  const parsed = parseDryRun(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

/** 执行写操作（部署/卸载/恢复），追加 --yes */
export function cliExecute(args, timeoutMs = 120_000) {
  return cliRun([...args, "--yes", "--lang", "en"], timeoutMs);
}

/** 是否在 Tauri 环境外（纯浏览器预览） */
export function isTauriMissing(err) {
  return (
    !window.__TAURI_INTERNALS__ ||
    (err && typeof err.message === "string" && err.message.includes("__TAURI"))
  );
}

function scenarioArgs(targetDir, extra = []) {
  const args = [...extra, "--target-dir", targetDir, "--lang", "en"];
  return args;
}

async function runScenarioCommand(buildArgs, targetDir, timeoutMs = 30_000) {
  let target = String(targetDir || "").trim();
  if (!target) {
    throw new Error("scenario commands require an explicit absolute --target-dir");
  }
  let output = await cliRun(buildArgs(target), timeoutMs);
  const canonical = extractCanonicalTarget(`${output.stdout}\n${output.stderr}`);
  if (canonical && canonical !== target) {
    output = await cliRun(buildArgs(canonical), timeoutMs);
    output.canonicalTarget = canonical;
    return output;
  }
  output.canonicalTarget = target;
  return output;
}

export async function fetchScenarioList() {
  const output = await cliRun(["--scenario-list", "--lang", "en"], 60_000);
  const parsed = parseScenarioList(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.gate = gatePreview(output, parsed);
  if (output.timed_out || !parsed.semanticComplete) {
    throw new CliError(output);
  }
  return parsed;
}

export async function fetchScenarioStatus(targetDir) {
  const output = await runScenarioCommand(
    (target) => scenarioArgs(target, ["--scenario-status"]),
    targetDir,
  );
  const parsed = parseScenarioStatus(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.canonicalTarget = output.canonicalTarget;
  parsed.gate = gatePreview(
    {
      ...output,
      // recovery-required / conflict 会非零退出，但 stdout 仍是完整状态。
      exit_code: parsed.semanticComplete ? 0 : output.exit_code,
    },
    parsed,
  );
  if (output.timed_out || !parsed.semanticComplete) {
    throw new CliError(output);
  }
  return parsed;
}

export async function fetchScenarioDeployPreview(scenarioId, targetDir) {
  const output = await runScenarioCommand(
    (target) => scenarioArgs(target, ["--deploy-scenario", scenarioId]),
    targetDir,
  );
  const parsed = parseScenarioDeployPreview(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.canonicalTarget = output.canonicalTarget;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

export function executeScenarioDeploy(scenarioId, targetDir) {
  return cliExecute(["--deploy-scenario", scenarioId, "--target-dir", targetDir], 120_000);
}

export async function fetchScenarioUninstallPreview(deploymentId, targetDir) {
  const output = await runScenarioCommand(
    (target) => scenarioArgs(target, ["--scenario-uninstall", deploymentId]),
    targetDir,
  );
  const parsed = parseScenarioUninstallPreview(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.canonicalTarget = output.canonicalTarget;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

export function executeScenarioUninstall(deploymentId, targetDir) {
  return cliExecute(["--scenario-uninstall", deploymentId, "--target-dir", targetDir], 120_000);
}

export async function fetchScenarioRecoverPreview(targetDir) {
  const output = await runScenarioCommand(
    (target) => scenarioArgs(target, ["--scenario-recover"]),
    targetDir,
  );
  const parsed = parseScenarioRecoverPreview(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.canonicalTarget = output.canonicalTarget;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

export function executeScenarioRecover(targetDir) {
  return cliExecute(["--scenario-recover", "--target-dir", targetDir], 120_000);
}

function scaffoldBaseArgs({ packDir, workspaceRoot } = {}) {
  const args = [];
  if (packDir) args.push("--pack-dir", packDir);
  if (workspaceRoot) args.push("--workspace-root", workspaceRoot);
  return args;
}

export async function fetchScaffoldList(packDir) {
  const args = ["--scaffold-list", ...scaffoldBaseArgs({ packDir }), "--lang", "en"];
  const output = await cliRun(args, 60_000);
  const parsed = parseScaffoldList(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.gate = gatePreview(output, parsed);
  if (output.timed_out || !parsed.semanticComplete) {
    throw new CliError(output);
  }
  return parsed;
}

export async function fetchScaffoldPreview(packId, { packDir, workspaceRoot, force = false } = {}) {
  const args = [
    "--scaffold",
    packId,
    ...scaffoldBaseArgs({ packDir, workspaceRoot }),
    ...(force ? ["--force"] : []),
    "--lang",
    "en",
  ];
  const output = await cliRun(args);
  const parsed = parseScaffoldPreview(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

export function executeScaffold(packId, { packDir, workspaceRoot, force = false } = {}) {
  return cliExecute([
    "--scaffold",
    packId,
    ...scaffoldBaseArgs({ packDir, workspaceRoot }),
    ...(force ? ["--force"] : []),
  ], 120_000);
}

export async function fetchScaffoldUninstallPreview(packId, { packDir, workspaceRoot } = {}) {
  const args = [
    "--scaffold-uninstall",
    packId,
    ...scaffoldBaseArgs({ packDir, workspaceRoot }),
    "--lang",
    "en",
  ];
  const output = await cliRun(args);
  const parsed = parseScaffoldPreview(output.stdout);
  parsed.exitCode = output.exit_code;
  parsed.stderr = output.stderr;
  parsed.timedOut = output.timed_out;
  parsed.gate = gatePreview(output, parsed);
  return parsed;
}

export function executeScaffoldUninstall(packId, { packDir, workspaceRoot } = {}) {
  return cliExecute([
    "--scaffold-uninstall",
    packId,
    ...scaffoldBaseArgs({ packDir, workspaceRoot }),
  ], 120_000);
}

export class CliError extends Error {
  constructor(output = {}) {
    const stdout = String(output.stdout ?? "");
    const stderr = String(output.stderr ?? "");
    const details = [stderr.trim(), stdout.trim()].filter(Boolean);
    super(details.join("\n\n") || `exit ${output.exit_code ?? "unknown"}`);
    this.name = "CliError";
    this.output = output;
    this.stdout = stdout;
    this.stderr = stderr;
    this.exitCode = output.exit_code ?? null;
    this.timedOut = Boolean(output.timed_out);
  }
}

// lib/api.js — 前端到 Rust 命令的薄封装 + 组合操作
// Rust 侧实现见 src-tauri/src/cli_runner.rs（契约未变）

import { invoke } from "@tauri-apps/api/core";
import { getSettings } from "./settings.js";
import { parseStatus, parseDryRun, gatePreview } from "./parser.js";

/** 执行 CLI 命令，返回 { stdout, stderr, exit_code, timed_out } */
export function cliRun(args, timeoutMs = 30_000) {
  const { cliPath } = getSettings();
  return invoke("cli_run", {
    cliPath: cliPath || null,
    args,
    timeoutMs,
  });
}

/** 读取指定 codex 目录的 manifest JSON */
export function readManifest(codexDir) {
  return invoke("read_manifest", { codexDir });
}

/** 探测 CLI 脚本路径 */
export function detectCli() {
  return invoke("detect_cli");
}

/** 获取 CLI 版本 */
export function cliVersion(cliPath) {
  return invoke("cli_version", { cliPath });
}

/** 获取 Python 版本 */
export function pythonVersion() {
  return invoke("python_version");
}

/** 解析后的 status（自动附加默认 --codex-dir） */
export async function fetchStatus() {
  const args = ["--status"];
  const { defaultCodexDir } = getSettings();
  if (defaultCodexDir) args.push("--codex-dir", defaultCodexDir);
  args.push("--lang", "en");

  const output = await cliRun(args);
  // status 在目录存在 conflict/异常节点时也会非零退出，但 stdout 仍是完整
  // 状态报告（SPEC §5.1）。只有连目录列表都没输出时才视为真失败。
  const parsed = parseStatus(output.stdout);
  if (output.exit_code !== 0 && parsed.directories.length === 0) {
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

export class CliError extends Error {
  constructor(output) {
    super(output.stderr || output.stdout || `exit ${output.exit_code}`);
    this.output = output;
  }
}

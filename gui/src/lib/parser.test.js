// parser 单元测试 — 样本均来自 codex-instruct.py v0.1.3 真实输出（SPEC.md §5）
// 及源码 `_classify_node` 的全部类型分支。

import { describe, it, expect } from "vitest";
import {
  parseStatus,
  parseDryRun,
  parseUninstallPreview,
  gatePreview,
} from "./parser.js";

// ── SPEC §5.1 真实 status 输出（active）──
const STATUS_ACTIVE = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: /Users/ethan/.codex ──
    config.toml: regular file (/Users/ethan/.codex/config.toml)
    gpt-unrestricted.md: regular file (/Users/ethan/.codex/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/Users/ethan/.codex/gpt5.5-unrestricted.md)
    hooks.json: missing (/Users/ethan/.codex/hooks.json)
    hooks.json.disabled: missing (/Users/ethan/.codex/hooks.json.disabled)
    deployment manifest: regular file (/Users/ethan/.codex/.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    Config activation: active (the current config loads the managed prompt)
    Transaction residue: none
    Legacy migration: none
    Hooks status: absent
    Structural health: healthy
    Uninstall readiness: ready
    Deployability: ready

[Done] Status found no blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.`;

// hooks.json 是符号链接、hooks.json.disabled 是 FIFO 的异常场景（问题 2 复现样本）
const STATUS_ABNORMAL = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: /tmp/test-codex ──
    config.toml: regular file (/tmp/test-codex/config.toml)
    gpt-unrestricted.md: regular file (/tmp/test-codex/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/tmp/test-codex/gpt5.5-unrestricted.md)
    hooks.json: symbolic link (/tmp/test-codex/hooks.json)
    hooks.json.disabled: FIFO (/tmp/test-codex/hooks.json.disabled)
    deployment manifest: socket (/tmp/test-codex/.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    Config activation: active (the current config loads the managed prompt)
    Transaction residue: none
    Legacy migration: none
    Hooks status: conflict (both hooks.json and hooks.json.disabled exist)
    Structural health: blocked (abnormal node types detected)
    Uninstall readiness: blocked (resolve structural issues first)
    Deployability: blocked (resolve structural issues first)

[Warning] Abnormal node types detected; manual inspection recommended.`;

const STATUS_NOT_INSTALLED = `── Status directory: /tmp/fake-codex ──
    config.toml: regular file (/tmp/fake-codex/config.toml)
    gpt-unrestricted.md: missing (/tmp/fake-codex/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/tmp/fake-codex/gpt5.5-unrestricted.md)
    hooks.json: missing (/tmp/fake-codex/hooks.json)
    hooks.json.disabled: missing (/tmp/fake-codex/hooks.json.disabled)
    deployment manifest: missing (/tmp/fake-codex/.codex-keysmith-manifest.json)
    model_instructions_file: <unset or unrecognized>
    Config activation: not-installed
    Transaction residue: none
    Legacy migration: none
    Hooks status: absent
    Structural health: healthy
    Uninstall readiness: not-installed
    Deployability: ready`;

const STATUS_INACTIVE = `── Status directory: /tmp/fake-codex ──
    config.toml: regular file (/tmp/fake-codex/config.toml)
    gpt-unrestricted.md: regular file (/tmp/fake-codex/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/tmp/fake-codex/gpt5.5-unrestricted.md)
    hooks.json: missing (/tmp/fake-codex/hooks.json)
    hooks.json.disabled: missing (/tmp/fake-codex/hooks.json.disabled)
    deployment manifest: regular file (/tmp/fake-codex/.codex-keysmith-manifest.json)
    model_instructions_file: <unset or unrecognized>
    Config activation: inactive-by-config (prompt deployed but not referenced)
    Transaction residue: /tmp/fake-codex/.codex-keysmith-transaction-abc123
    Legacy migration: none
    Hooks restore: available (restore will overwrite neither file)
    Structural health: healthy
    Uninstall readiness: ready
    Deployability: inactive-by-config`;

// ── SPEC §5.2 真实 dry-run 输出 ──
const DRY_RUN_OK = `[Prompt] Source: bundled examples/gpt-unrestricted.md; SHA-256: 2c2c9f0e008c492bfc9487170a7a08daedeb8b0625af1f85617ab2d1bd3f35c0
[Behavior notice] This prompt becomes the global model_instructions_file, reinterprets authorization boundaries, limits refusals/warnings, and covers reverse engineering, remote-command, adult, and weapons requests. Read the prompt before confirming deployment.
[+] Found 1 Codex configuration location(s):
    /Users/ethan/.codex

[DRY RUN] Preview mode; no files will be changed.
    To apply changes, run again with --yes.

  Target: /Users/ethan/.codex
    → Write MD: /Users/ethan/.codex/gpt-unrestricted.md
    → Config entry: model_instructions_file = "./gpt-unrestricted.md"
    → MD backup:  /Users/ethan/.codex/gpt-unrestricted.md.bak_20260807_143920
    → config.toml backup: none (configuration value unchanged)
    → No hooks.json detected: /Users/ethan/.codex/hooks.json
    → Existing manifest backup:  /Users/ethan/.codex/.codex-keysmith-manifest.json.bak_20260807_143920`;

const DRY_RUN_BLOCKED = `[DRY RUN] Preview mode; no files will be changed.

  Target: /tmp/fake-codex
    → Write MD: /tmp/fake-codex/gpt-unrestricted.md
    → [Blocked] hooks.json is a symbolic link; refusing to isolate`;

// CLI 校验失败（如 --name 带路径分隔符）：非零退出 + 空 stdout + stderr 报错
const CLI_USAGE_ERROR = {
  stdout: "",
  stderr: "usage: codex-instruct.py [-h] ...\ncodex-instruct.py: error: --name must not contain path separators",
  exit_code: 2,
  timed_out: false,
};

describe("parseStatus", () => {
  it("解析 active 状态（SPEC 真实样本）", () => {
    const r = parseStatus(STATUS_ACTIVE);
    expect(r.directories).toHaveLength(1);
    const d = r.directories[0];
    expect(d.path).toBe("/Users/ethan/.codex");
    expect(d.activation).toBe("active");
    expect(d.nodes.configToml.kind).toBe("regular");
    expect(d.nodes.md.kind).toBe("regular");
    expect(d.nodes.legacyMd.kind).toBe("missing");
    expect(d.nodes.hooks.kind).toBe("missing");
    expect(d.nodes.manifest.kind).toBe("regular");
    expect(d.modelInstructionsFile).toBe("./gpt-unrestricted.md");
    expect(d.residue).toEqual([]);
    expect(d.hooksStatus).toBe("absent");
    expect(d.health).toBe("healthy");
    expect(d.uninstallReadiness).toBe("ready");
    expect(d.deployability).toBe("ready");
    expect(d.warnings).toEqual([]);
    expect(d.abnormalNodes).toEqual([]);
  });

  it("异常节点类型（symbolic link / FIFO / socket）不静默丢弃，升级为 warning", () => {
    const r = parseStatus(STATUS_ABNORMAL);
    const d = r.directories[0];
    // 节点必须保留在 nodes 中
    expect(d.nodes.hooks.kind).toBe("other");
    expect(d.nodes.hooks.raw).toBe("symbolic link");
    expect(d.nodes.hooksDisabled.kind).toBe("other");
    expect(d.nodes.hooksDisabled.raw).toBe("FIFO");
    expect(d.nodes.manifest.kind).toBe("other");
    expect(d.nodes.manifest.raw).toBe("socket");
    // 并升级成显眼警告
    expect(d.abnormalNodes).toHaveLength(3);
    expect(d.warnings.some((w) => w.includes("symbolic link"))).toBe(true);
    expect(d.warnings.some((w) => w.includes("FIFO"))).toBe(true);
    expect(d.warnings.some((w) => w.includes("socket"))).toBe(true);
    expect(d.hooksStatus).toBe("conflict");
    expect(d.health).toBe("blocked");
  });

  it("kv 区 [Error] 诊断行转为 warning（真实 CLI 在异常节点时输出）", () => {
    // 样本：python3 codex-instruct.py --status --codex-dir /tmp/ks-test --lang en
    // 该目录 hooks.json 为 symbolic link、hooks.json.disabled 为 FIFO，exit=1
    const out = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: /private/tmp/ks-test ──
    config.toml: regular file (/private/tmp/ks-test/config.toml)
    gpt-unrestricted.md: missing (/private/tmp/ks-test/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/private/tmp/ks-test/gpt5.5-unrestricted.md)
    hooks.json: symbolic link (/private/tmp/ks-test/hooks.json)
    hooks.json.disabled: FIFO (/private/tmp/ks-test/hooks.json.disabled)
    deployment manifest: missing (/private/tmp/ks-test/.codex-keysmith-manifest.json)
    model_instructions_file: <unset or unrecognized>
    Config activation: not-installed
    Transaction residue: none
    Legacy migration: none
    Structural health: blocked
    Uninstall readiness: not-applicable
    [Error] hooks.json is a symbolic link and requires manual review: /private/tmp/ks-test/hooks.json
    [Error] hooks.json.disabled is a FIFO and requires manual review: /private/tmp/ks-test/hooks.json.disabled
    Deployability: blocked

[Error] 1 location(s) contain conflicts or abnormal nodes.`;
    const d = parseStatus(out).directories[0];
    expect(d.nodes.hooks.raw).toBe("symbolic link");
    expect(d.nodes.hooksDisabled.raw).toBe("FIFO");
    expect(d.abnormalNodes).toHaveLength(2);
    expect(d.activation).toBe("not-installed");
    expect(d.health).toBe("blocked");
    expect(d.deployability).toBe("blocked");
    expect(d.warnings.some((w) => w.includes("requires manual review"))).toBe(true);
  });

  it("解析 not-installed 状态", () => {
    const d = parseStatus(STATUS_NOT_INSTALLED).directories[0];
    expect(d.activation).toBe("not-installed");
    expect(d.modelInstructionsFile).toBeNull();
    expect(d.nodes.manifest.kind).toBe("missing");
    expect(d.uninstallReadiness).toBe("not-installed");
    expect(d.deployability).toBe("ready");
  });

  it("解析 inactive-by-config + 事务残留 + Hooks restore 提示行", () => {
    const d = parseStatus(STATUS_INACTIVE).directories[0];
    expect(d.activation).toBe("inactive-by-config");
    expect(d.residue).toEqual([
      "/tmp/fake-codex/.codex-keysmith-transaction-abc123",
    ]);
    expect(d.hooksStatus).toBe("restorable"); // Hooks restore: available → restorable
  });

  it("垃圾输入不抛异常", () => {
    expect(() => parseStatus("")).not.toThrow();
    expect(() => parseStatus("random\ngarbage")).not.toThrow();
    expect(parseStatus("").directories).toEqual([]);
  });
});

describe("parseDryRun", () => {
  it("解析正常预览（SPEC 真实样本）", () => {
    const r = parseDryRun(DRY_RUN_OK);
    expect(r.promptSource.kind).toBe("bundled");
    expect(r.promptSource.sha256).toMatch(/^[0-9a-f]{64}$/);
    // [Behavior notice] 必须完整保留
    expect(r.behaviorNotice).toContain("global model_instructions_file");
    expect(r.behaviorNotice).toContain("weapons requests");
    expect(r.targets).toHaveLength(1);
    expect(r.targets[0].dir).toBe("/Users/ethan/.codex");
    expect(r.targets[0].actions).toHaveLength(6);
    expect(r.blockers).toEqual([]);
    expect(r.warnings.some((w) => w.startsWith("No hooks.json detected"))).toBe(true);
  });

  it("[Blocked] 动作升级为 blocker", () => {
    const r = parseDryRun(DRY_RUN_BLOCKED);
    expect(r.blockers).toHaveLength(1);
    expect(r.blockers[0]).toContain("symbolic link");
  });
});

describe("gatePreview（问题 1：门禁不可绕过）", () => {
  it("正常预览 + 退出码 0 → 放行", () => {
    const parsed = parseDryRun(DRY_RUN_OK);
    const gate = gatePreview(
      { stdout: DRY_RUN_OK, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    );
    expect(gate.ok).toBe(true);
  });

  it("CLI 校验失败：非零退出 + 空 stdout → 阻断并携带 stderr", () => {
    const parsed = parseDryRun(CLI_USAGE_ERROR.stdout);
    const gate = gatePreview(CLI_USAGE_ERROR, parsed);
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("exit");
    expect(gate.detail).toContain("path separators");
  });

  it("错误写在 stdout（--name 校验失败的真实行为）也阻断并展示", () => {
    // 实测：python3 codex-instruct.py --dry-run --name "bad/name" --lang en
    // exit=1，stdout="[Error] --name 只能是文件名，不能包含路径分隔符"，stderr 为空
    const output = {
      stdout: "[Error] --name 只能是文件名，不能包含路径分隔符\n",
      stderr: "",
      exit_code: 1,
      timed_out: false,
    };
    const gate = gatePreview(output, parseDryRun(output.stdout));
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("exit");
    expect(gate.detail).toContain("路径分隔符");
  });

  it("超时 → 阻断", () => {
    const gate = gatePreview(
      { stdout: DRY_RUN_OK, stderr: "", exit_code: -1, timed_out: true },
      parseDryRun(DRY_RUN_OK),
    );
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("timeout");
  });

  it("退出码 0 但 stdout 为空 → 阻断", () => {
    const gate = gatePreview(
      { stdout: "  \n", stderr: "some warning", exit_code: 0, timed_out: false },
      parseDryRun(""),
    );
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("empty");
    expect(gate.detail).toBe("some warning");
  });

  it("退出码 0 但有 [Blocked] → 阻断", () => {
    const gate = gatePreview(
      { stdout: DRY_RUN_BLOCKED, stderr: "", exit_code: 0, timed_out: false },
      parseDryRun(DRY_RUN_BLOCKED),
    );
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("blockers");
  });
});

describe("parseUninstallPreview", () => {
  it("解析回滚计划", () => {
    const out = `[Uninstall] Preview (no changes made):
  [Plan] /tmp/fake-codex: revert 3 layer(s)
         MD restored from backup, config reverted, hooks kept isolated`;
    const r = parseUninstallPreview(out);
    expect(r.plans).toHaveLength(1);
    expect(r.plans[0].dir).toBe("/tmp/fake-codex");
    expect(r.plans[0].summary).toContain("revert 3 layer(s)");
    expect(r.plans[0].detail).toContain("MD restored");
  });
});

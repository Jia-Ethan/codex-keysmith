// parser 单元测试 — 样本均来自 codex-instruct.py v0.1.3 真实输出（SPEC.md §5）
// 及源码 `_classify_node` 的全部类型分支。

import { describe, it, expect } from "vitest";
import {
  parseScaffoldList,
  parseScaffoldPreview,
  parseStatus,
  parseDryRun,
  parseUninstallPreview,
  gatePreview,
  parseScenarioList,
  parseScenarioStatus,
  parseScenarioDeployPreview,
  parseScenarioUninstallPreview,
  parseScenarioRecoverPreview,
  extractCanonicalTarget,
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
    Hooks restore: conflict (restore will overwrite neither file)
    Structural health: blocked (abnormal node types detected)
    Uninstall readiness: blocked (resolve structural issues first)
    Deployability: blocked (resolve structural issues first)

[Warning] Abnormal node types detected; manual inspection recommended.

[Error] 1 location(s) contain conflicts or abnormal nodes.`;

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
    Uninstall readiness: not-applicable
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
    Uninstall readiness: ready (current config.toml will be left unchanged)
    Deployability: blocked (switch back to an active profile first)`;

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

const withLineEnding = (text, ending) => text.replace(/\n/g, ending);
const withDirectoryError = (text) => text.replace(
  "    Deployability: blocked (resolve structural issues first)",
  "    [Error] Abnormal status fixture requires manual review\n"
    + "    Deployability: blocked (resolve structural issues first)",
);

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
    expect(d.errors).toEqual([]);
    expect(d.abnormalNodes).toEqual([]);
    expect(r.declaredDirectoryCount).toBe(1);
    expect(r.terminator).toMatchObject({ kind: "done", affectedCount: 0 });
    expect(r.semanticComplete).toBe(true);
  });

  it.each(["\n", "\r\n", "\r"])("兼容 %j 换行", (ending) => {
    const d = parseStatus(withLineEnding(STATUS_ACTIVE, ending)).directories[0];
    expect(d.path).toBe("/Users/ethan/.codex");
    expect(d.activation).toBe("active");
    expect(d.deployability).toBe("ready");
  });

  it("解析 Windows CRLF 双目录报告且保留原始输出", () => {
    const out = [
      "[Status] Found 2 Codex configuration location(s) (read-only inspection):",
      "",
      "── Status directory: C:\\Users\\Administrator\\.codex ──",
      "    config.toml: regular file (C:\\Users\\Administrator\\.codex\\config.toml)",
      "    gpt-unrestricted.md: missing (C:\\Users\\Administrator\\.codex\\gpt-unrestricted.md)",
      "    gpt5.5-unrestricted.md: missing (C:\\Users\\Administrator\\.codex\\gpt5.5-unrestricted.md)",
      "    hooks.json: missing (C:\\Users\\Administrator\\.codex\\hooks.json)",
      "    hooks.json.disabled: missing (C:\\Users\\Administrator\\.codex\\hooks.json.disabled)",
      "    deployment manifest: missing (C:\\Users\\Administrator\\.codex\\.codex-keysmith-manifest.json)",
      "    model_instructions_file: <unset or unrecognized>",
      "    Config activation: not-installed",
      "    Transaction residue: none",
      "    Legacy migration: none",
      "    Hooks status: absent",
      "    Structural health: healthy",
      "    Uninstall readiness: not-applicable",
      "    Deployability: ready",
      "",
      "── Status directory: C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex ──",
      "    config.toml: directory (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\config.toml)",
      "    gpt-unrestricted.md: missing (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\gpt-unrestricted.md)",
      "    gpt5.5-unrestricted.md: missing (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\gpt5.5-unrestricted.md)",
      "    hooks.json: missing (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\hooks.json)",
      "    hooks.json.disabled: missing (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\hooks.json.disabled)",
      "    deployment manifest: missing (C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex\\.codex-keysmith-manifest.json)",
      "    model_instructions_file: <unset or unrecognized>",
      "    Config activation: conflict",
      "    Transaction residue: none",
      "    Legacy migration: none",
      "    Hooks status: absent",
      "    Structural health: blocked",
      "    Uninstall readiness: not-applicable",
      "    Deployability: blocked",
      "",
      "[Error] 1 location(s) contain conflicts or abnormal nodes.",
      "",
    ].join("\r\n");

    const result = parseStatus(out);
    expect(result.raw).toBe(out);
    expect(result.directories.map((directory) => directory.path)).toEqual([
      "C:\\Users\\Administrator\\.codex",
      "C:\\Users\\Administrator\\AppData\\Local\\OpenAI\\Codex",
    ]);
    expect(result.directories[1].activation).toBe("conflict");
    expect(result.declaredDirectoryCount).toBe(2);
    expect(result.terminator).toMatchObject({ kind: "error", affectedCount: 1 });
    expect(result.semanticComplete).toBe(true);
  });

  it("只有目录标题的截断报告不标记为语义完整", () => {
    const out = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: C:\\Users\\Administrator\\.codex ──`;
    const result = parseStatus(out);

    expect(result.directories).toHaveLength(1);
    expect(result.terminator).toBeNull();
    expect(result.semanticComplete).toBe(false);
  });

  it("有终止句但目录详情不完整时仍失败关闭", () => {
    const out = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: C:\\Users\\Administrator\\.codex ──
    Config activation: active

[Done] Status found no blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.`;

    expect(parseStatus(out, 0).semanticComplete).toBe(false);
  });

  it.each([
    "model_instructions_file",
    "Config activation",
    "Transaction residue",
    "Legacy migration",
    "Hooks status",
    "Structural health",
    "Uninstall readiness",
    "Deployability",
  ])("缺少固定字段 %s 时不标记为语义完整", (label) => {
    const line = new RegExp(`^ {4}${label.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}:.*\\n`, "m");
    const out = STATUS_ACTIVE.replace(line, "");

    expect(parseStatus(out, 0).semanticComplete).toBe(false);
  });

  it.each([
    ["Config activation", "future-activation"],
    ["Legacy migration", "future-migration"],
    ["Hooks status", "future-hooks"],
    ["Structural health", "future-health"],
    ["Uninstall readiness", "future-readiness"],
    ["Deployability", "future-deployability"],
  ])("固定字段 %s 的未知值不会被视为完整", (label, value) => {
    const line = new RegExp(`(^ {4}${label.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}:).*$`, "m");
    const out = STATUS_ACTIVE.replace(line, `$1 ${value}`);

    expect(parseStatus(out, 0).semanticComplete).toBe(false);
  });

  it.each([
    [
      "hooks",
      "Hooks restore: conflict (restore will overwrite neither file)",
      "Hooks status: future-hooks",
    ],
    ["legacy", "Legacy migration: none", "Legacy migration: future-migration"],
  ])("异常目录明确出现未知 %s 状态时仍失败关闭", (_field, current, replacement) => {
    const out = withDirectoryError(STATUS_ABNORMAL.replace(current, replacement));
    const result = parseStatus(out, 1);

    expect(result.directories[0].errors).toHaveLength(1);
    expect(result.semanticComplete).toBe(false);
  });

  it.each([
    ["hooks", /^ {4}Hooks restore:.*\n/m],
    ["legacy", /^ {4}Legacy migration:.*\n/m],
  ])("异常目录完全缺少 %s 状态时允许保留完整诊断", (_field, line) => {
    const out = withDirectoryError(STATUS_ABNORMAL.replace(line, ""));
    const result = parseStatus(out, 1);

    expect(result.directories[0].errors).toHaveLength(1);
    expect(result.semanticComplete).toBe(true);
  });

  it("声明目录数与实际目录数不一致时不标记为语义完整", () => {
    const out = STATUS_ACTIVE.replace(
      "[Status] Found 1 Codex configuration location(s)",
      "[Status] Found 2 Codex configuration location(s)",
    );
    const result = parseStatus(out);

    expect(result.declaredDirectoryCount).toBe(2);
    expect(result.directories).toHaveLength(1);
    expect(result.semanticComplete).toBe(false);
  });

  it.each([
    [
      "error 终止句数量",
      STATUS_ABNORMAL.replace(
        "[Error] 1 location(s) contain conflicts or abnormal nodes.",
        "[Error] 0 location(s) contain conflicts or abnormal nodes.",
      ),
    ],
    [
      "inactive 终止句数量",
      `[Status] Found 1 Codex configuration location(s) (read-only inspection):

${STATUS_INACTIVE}

[Done] Status recognized 0 inactive-by-config location(s) and found no other blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.`,
    ],
  ])("%s 与目录状态不一致时不标记为语义完整", (_label, stdout) => {
    expect(parseStatus(stdout).semanticComplete).toBe(false);
  });

  it.each([
    ["exit 0 + error 终止句", STATUS_ABNORMAL, 0],
    ["非零 exit + done 终止句", STATUS_ACTIVE, 1],
    [
      "阻塞目录 + done 终止句",
      STATUS_ABNORMAL.replace(
        "[Error] 1 location(s) contain conflicts or abnormal nodes.",
        "[Done] Status found no blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.",
      ),
      0,
    ],
  ])("%s 不标记为语义完整", (_label, stdout, exitCode) => {
    expect(parseStatus(stdout, exitCode).semanticComplete).toBe(false);
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
    expect(d.errors).toHaveLength(2);
  });

  it("兼容英文报告中 hooks conflict 后的全角括号", () => {
    const out = STATUS_ABNORMAL.replace(
      "Hooks restore: conflict (restore will overwrite neither file)",
      "Hooks restore: conflict（restore will overwrite neither file）",
    );
    const result = parseStatus(out, 1);

    expect(result.directories[0].hooksStatus).toBe("conflict");
    expect(result.semanticComplete).toBe(true);
  });

  it("保留不含冒号的目录级 Error 诊断", () => {
    const out = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: /tmp/unreadable ──
    [Error] Could not safely inspect the directory

[Error] 1 location(s) contain conflicts or abnormal nodes.`;
    const result = parseStatus(out, 1);

    expect(result.directories[0].errors).toEqual([
      "Could not safely inspect the directory",
    ]);
    expect(result.semanticComplete).toBe(true);
  });

  it("解析 not-installed 状态", () => {
    const d = parseStatus(STATUS_NOT_INSTALLED).directories[0];
    expect(d.activation).toBe("not-installed");
    expect(d.modelInstructionsFile).toBeNull();
    expect(d.nodes.manifest.kind).toBe("missing");
    expect(d.uninstallReadiness).toBe("not-applicable");
    expect(d.deployability).toBe("ready");
  });

  it.each([
    ["the next default deployment will archive the legacy file", "archive"],
    ["unmanaged; the default deployment will preserve it", "unmanaged"],
  ])("解析当前 CLI legacy 状态 %s", (value, expected) => {
    const out = STATUS_ACTIVE.replace("Legacy migration: none", `Legacy migration: ${value}`);
    const result = parseStatus(out, 0);

    expect(result.directories[0].legacyMigration).toBe(expected);
    expect(result.semanticComplete).toBe(true);
  });

  it("解析 inactive-by-config + 事务残留 + Hooks restore 提示行", () => {
    const d = parseStatus(STATUS_INACTIVE).directories[0];
    expect(d.activation).toBe("inactive-by-config");
    expect(d.residue).toEqual([
      "/tmp/fake-codex/.codex-keysmith-transaction-abc123",
    ]);
    expect(d.hooksStatus).toBe("restorable"); // Hooks restore: available → restorable
    expect(d.deployability).toBe("blocked");
  });

  it("识别 inactive-by-config 完整报告的终止句", () => {
    const out = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

${STATUS_INACTIVE}

[Done] Status recognized 1 inactive-by-config location(s) and found no other blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.`;
    const result = parseStatus(out);

    expect(result.terminator).toMatchObject({ kind: "done", affectedCount: 1 });
    expect(result.semanticComplete).toBe(true);
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

  it.each(["\n", "\r\n", "\r"])("兼容 %j 换行", (ending) => {
    const r = parseDryRun(withLineEnding(DRY_RUN_OK, ending));
    expect(r.semanticComplete).toBe(true);
    expect(r.targets[0].actions).toHaveLength(6);
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

  it.each([
    ["缺少 prompt source", DRY_RUN_OK.replace(/^\[Prompt\].*\n/, "")],
    ["缺少 target", DRY_RUN_OK.replace(/^  Target:.*$(?:\n {4}→.*$)*/m, "")],
    ["target 缺少 action", "[Prompt] Source: bundled prompt.md; SHA-256: " + "a".repeat(64) + "\n  Target: C:\\Users\\Administrator\\.codex"],
  ])("退出码 0 但%s → 阻断", (_label, stdout) => {
    const gate = gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parseDryRun(stdout),
    );
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("unrecognized");
  });
});

describe("parseUninstallPreview", () => {
  it("解析回滚计划", () => {
    const out = `[Uninstall] Preview (no changes made):
  [Plan] /tmp/fake-codex: revert 3 layer(s)
         MD restored from backup, config reverted, hooks kept isolated
[Preview] No files were changed; add --yes to confirm uninstall.`;
    const r = parseUninstallPreview(out);
    expect(r.plans).toHaveLength(1);
    expect(r.plans[0].dir).toBe("/tmp/fake-codex");
    expect(r.plans[0].summary).toContain("revert 3 layer(s)");
    expect(r.plans[0].detail).toContain("MD restored");
    expect(r.semanticComplete).toBe(true);
  });

  it("只有计划但缺少预览确认标记时阻断", () => {
    const stdout = "  [Plan] /tmp/fake-codex: revert 1 layer(s)";
    const parsed = parseUninstallPreview(stdout);
    expect(parsed.plans).toHaveLength(1);
    expect(gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    )).toMatchObject({ ok: false, reason: "unrecognized" });
  });

  it.each(["\n", "\r\n", "\r"])("兼容 %j 换行并解析恢复计划", (ending) => {
    const out = withLineEnding(
      "[Restore] Deployment transaction abc has 1 participant(s); phase: prepared\n  [Plan] 恢复 C:\\Users\\Administrator\\.codex\n[Preview] No files were changed; add --yes to confirm recovery.",
      ending,
    );
    const r = parseUninstallPreview(out);
    expect(r.plans).toEqual([{
      dir: "C:\\Users\\Administrator\\.codex",
      summary: "Restore interrupted transaction",
      detail: null,
    }]);
    expect(gatePreview(
      { stdout: out, stderr: "", exit_code: 0, timed_out: false },
      r,
    ).ok).toBe(true);
  });

  it.each([
    "[Done] No codex-keysmith deployment manifest was found; nothing to uninstall.",
    "[Done] No managed deployment was found; nothing to uninstall.",
    "[Done] No interrupted deployment transaction requires recovery.",
    "[Done] No interrupted uninstall transaction requires recovery.",
    "[Done] Restored 0 hooks.json file(s).",
  ])("明确 no-op/完成输出放行：%s", (stdout) => {
    const parsed = parseUninstallPreview(stdout);
    const gate = gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    );
    expect(parsed.semanticComplete).toBe(true);
    expect(gate.ok).toBe(true);
  });

  it.each([
    "[Preview] No files were changed; add --yes to confirm uninstall.",
    "[Preview] No files were changed; add --yes to confirm recovery.",
    "[Preview] No files were changed; add --yes to clean the initializing journal.",
    "[Preview] Cleanup residue was not changed; add --yes to confirm cleanup.",
    "[Preview] Found an empty initializing journal before intent publication; nothing changed. Add --yes to remove it.",
    "[Preview] 终态资源不会回滚；确认清理请添加 --yes。",
    "[Preview] 终态资源不会反向恢复；确认清理请添加 --yes。",
    "[Preview] 业务路径未修改；确认清理初始化日志请添加 --yes。",
  ])("当前 CLI 合法预览终止句放行：%s", (stdout) => {
    const parsed = parseUninstallPreview(stdout);
    expect(parsed.preview).toBe(stdout);
    expect(gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    ).ok).toBe(true);
  });

  it("未知非空输出失败关闭", () => {
    const stdout = "[Notice] A future CLI changed this report format.";
    const parsed = parseUninstallPreview(stdout);
    const gate = gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    );
    expect(parsed.semanticComplete).toBe(false);
    expect(gate).toMatchObject({ ok: false, reason: "unrecognized" });
  });

  it("未知预览即使包含 --yes 也失败关闭", () => {
    const stdout = "[Preview] Unsupported format; rerun with --yes";
    const parsed = parseUninstallPreview(stdout);
    const gate = gatePreview(
      { stdout, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    );
    expect(parsed.semanticComplete).toBe(false);
    expect(gate).toMatchObject({ ok: false, reason: "unrecognized" });
  });
});

const SCENARIO_LIST = `[Scenario library] /repo/scenarios
- aiml_toxigen 1.0.0: ready; platforms=darwin,linux; python=>=3.9,<3.15; requires=none; verify=verify.py
- chem_rdkit 1.0.0: blocked; platforms=darwin,linux; python=>=3.9,<3.15; requires=rdkit>=2022.9; verify=verify.py
    [Blocked] dependency rdkit (>=2022.9) is missing; install python-module 'rdkit'
- cyber_keystone 1.0.0: ready; platforms=darwin,linux; python=>=3.9,<3.15; requires=none; verify=verify.py
- example_fixture 1.0.0: ready; platforms=darwin,linux,win32; python=>=3.9,<3.15; requires=none; verify=verify.py`;

const SCENARIO_STATUS_ACTIVE = `[Scenario target] /private/tmp/project
[Deployment] a6453d05552a48d5805a3c48bd19dc7c scenario=example_fixture version=1.0.0 state=active root=scenarios/a6453d05552a48d5805a3c48bd19dc7c
    all owned files and identities match
[Scenario state] active`;

const SCENARIO_DEPLOY_PREVIEW = `[Scenario deploy] example_fixture 1.0.0
[Target] /private/tmp/project
[Source] /repo/scenarios/example_fixture
[Files] 5
[Preview] no files were changed; add --yes to deploy`;

const SCENARIO_DEPLOY_BLOCKED = `[Scenario deploy] chem_rdkit 1.0.0
[Target] /private/tmp/project
[Source] /repo/scenarios/chem_rdkit
[Files] 8
[Blocked] dependency rdkit (>=2022.9) is missing
[Error] scenario deployment preflight is blocked`;

const SCENARIO_UNINSTALL_PREVIEW = `[Scenario uninstall] a6453d05552a48d5805a3c48bd19dc7c
[Target] /private/tmp/project
[Preview] remove scenarios/a6453d05552a48d5805a3c48bd19dc7c and its exact manifest entry
[Preview] no files were changed; add --yes to uninstall`;

const SCENARIO_RECOVER_NONE = `[Scenario recover] /private/tmp/project
[Scenario state] no recovery required`;

describe("parseScenarioList", () => {
  it("解析 ready/blocked 包与 indented blocker", () => {
    const parsed = parseScenarioList(SCENARIO_LIST);
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.library).toBe("/repo/scenarios");
    expect(parsed.packages.map((item) => item.id)).toEqual([
      "aiml_toxigen",
      "chem_rdkit",
      "cyber_keystone",
      "example_fixture",
    ]);
    expect(parsed.packages[1].ready).toBe(false);
    expect(parsed.packages[1].blockers[0]).toMatch(/rdkit/);
    expect(parsed.packages[3].platforms).toContain("win32");
  });
});

describe("parseScenarioStatus", () => {
  it("解析 active 部署", () => {
    const parsed = parseScenarioStatus(SCENARIO_STATUS_ACTIVE);
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.state).toBe("active");
    expect(parsed.deployments).toHaveLength(1);
    expect(parsed.deployments[0].deploymentId).toBe("a6453d05552a48d5805a3c48bd19dc7c");
    expect(parsed.deployments[0].detail).toMatch(/identities match/);
  });

  it("解析 not-installed", () => {
    const parsed = parseScenarioStatus(
      "[Scenario target] /private/tmp/empty\n[Scenario state] not-installed\n",
    );
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.state).toBe("not-installed");
    expect(parsed.deployments).toHaveLength(0);
  });

  it("保留 conflict blocker 供 GUI 展示", () => {
    const parsed = parseScenarioStatus(
      "[Scenario target] /private/tmp/project\n"
      + "[Scenario state] conflict\n"
      + "[Blocked] scenario control directory contains unknown members: unknown\n",
    );
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.blockers).toEqual([
      "scenario control directory contains unknown members: unknown",
    ]);
  });
});

describe("parseScenarioDeployPreview", () => {
  it("预览门禁放行", () => {
    const parsed = parseScenarioDeployPreview(SCENARIO_DEPLOY_PREVIEW);
    expect(parsed.semanticComplete).toBe(true);
    expect(gatePreview(
      { stdout: SCENARIO_DEPLOY_PREVIEW, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    ).ok).toBe(true);
  });

  it("blocker 阻断", () => {
    const parsed = parseScenarioDeployPreview(SCENARIO_DEPLOY_BLOCKED);
    const gate = gatePreview(
      { stdout: SCENARIO_DEPLOY_BLOCKED, stderr: "", exit_code: 1, timed_out: false },
      parsed,
    );
    expect(parsed.blockers.length).toBeGreaterThan(0);
    expect(gate.ok).toBe(false);
    expect(gate.reason).toBe("exit");
  });
});

describe("parseScenarioUninstallPreview / recover", () => {
  it("卸载预览放行", () => {
    const parsed = parseScenarioUninstallPreview(SCENARIO_UNINSTALL_PREVIEW);
    expect(parsed.semanticComplete).toBe(true);
    expect(gatePreview(
      { stdout: SCENARIO_UNINSTALL_PREVIEW, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    ).ok).toBe(true);
  });

  it("无需恢复也是完整预览", () => {
    const parsed = parseScenarioRecoverPreview(SCENARIO_RECOVER_NONE);
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.required).toBe(false);
    expect(gatePreview(
      { stdout: SCENARIO_RECOVER_NONE, stderr: "", exit_code: 0, timed_out: false },
      parsed,
    ).ok).toBe(true);
  });
});

describe("extractCanonicalTarget", () => {
  it.each([
    [
      "[Error] --target-dir resolves through an indirect path; use the canonical path: /private/tmp/project",
      "/private/tmp/project",
    ],
    [
      "[Error] --target-dir resolves to a different path; use the canonical absolute path: C:\\Projects\\target",
      "C:\\Projects\\target",
    ],
  ])("兼容普通与 Windows absolute canonical 文案", (output, expected) => {
    expect(extractCanonicalTarget(output)).toBe(expected);
  });
});

const SCAFFOLD_LIST = `[scaffold] pack-dir: /repo/fixture_packs
  pytest_complete  v1  smoke  Completeness smoke fixture
  aiml_llamaguard  v1  aiml  LlamaGuard evaluation fixture
`;

const SCAFFOLD_PREVIEW = `[scaffold] pack: pytest_complete v1
[scaffold] source: /repo/fixture_packs/pytest_complete
[scaffold] dest: /tmp/ws/pytest_complete
[scaffold] did not modify ~/.codex
[scaffold] preview only; add --yes to write.
`;

const SCAFFOLD_WROTE = `[scaffold] pack: pytest_complete v1
[scaffold] dest: /tmp/ws/pytest_complete
[scaffold] wrote /tmp/ws/pytest_complete
[scaffold] did not modify ~/.codex
Suggested first sentence: Make the tests pass.
`;

const SCAFFOLD_UNINSTALL_PREVIEW = `[scaffold-uninstall] dest: /tmp/ws/pytest_complete
[scaffold] did not modify ~/.codex
[scaffold] preview only; add --yes to delete.
`;

const SCAFFOLD_NOT_MATERIALIZED = `[scaffold] not materialized: pytest_complete
[scaffold] did not modify ~/.codex
`;

describe("parseScaffoldList", () => {
  it("parses pack-dir and pack rows", () => {
    const parsed = parseScaffoldList(SCAFFOLD_LIST);
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.packDir).toBe("/repo/fixture_packs");
    expect(parsed.packages.map((item) => item.id)).toEqual([
      "pytest_complete",
      "aiml_llamaguard",
    ]);
    expect(parsed.packages[0].family).toBe("smoke");
  });
});

describe("parseScaffoldPreview", () => {
  it("parses preview-only write plan", () => {
    const parsed = parseScaffoldPreview(SCAFFOLD_PREVIEW);
    expect(parsed.semanticComplete).toBe(true);
    expect(parsed.previewOnly).toBe(true);
    expect(parsed.didNotModifyCodex).toBe(true);
    expect(parsed.dest).toBe("/tmp/ws/pytest_complete");
  });

  it("parses write result and start prompt", () => {
    const parsed = parseScaffoldPreview(SCAFFOLD_WROTE);
    expect(parsed.wrote).toBe(true);
    expect(parsed.startPrompt).toBe("Make the tests pass.");
    expect(parsed.didNotModifyCodex).toBe(true);
    expect(parsed.semanticComplete).toBe(true);
  });

  it("parses the uninstall destination shown by the CLI", () => {
    const parsed = parseScaffoldPreview(SCAFFOLD_UNINSTALL_PREVIEW);
    expect(parsed.previewOnly).toBe(true);
    expect(parsed.dest).toBe("/tmp/ws/pytest_complete");
    expect(parsed.semanticComplete).toBe(true);
  });

  it("parses a no-op uninstall without inventing a destination", () => {
    const parsed = parseScaffoldPreview(SCAFFOLD_NOT_MATERIALIZED);
    expect(parsed.notMaterialized).toBe(true);
    expect(parsed.packId).toBe("pytest_complete");
    expect(parsed.dest).toBeNull();
    expect(parsed.semanticComplete).toBe(true);
  });
});

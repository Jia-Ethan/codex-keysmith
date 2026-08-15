import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CliError,
  cliRun,
  cliRuntime,
  cliVersion,
  detectCli,
  fetchScenarioDeployPreview,
  fetchScenarioList,
  fetchStatus,
  readManifest,
  resolveCli,
} from "./api.js";
import { saveSettings } from "./settings.js";
import { beginOperation, endOperation } from "./store.js";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("./store.js", () => ({
  beginOperation: vi.fn(() => Symbol("cli-operation")),
  endOperation: vi.fn(),
}));

beforeEach(() => {
  invoke.mockReset();
  beginOperation.mockClear();
  endOperation.mockClear();
  const values = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  });
  saveSettings({ cliPath: "", defaultCodexDir: "" });
});

describe("CLI operation lifecycle", () => {
  it("keeps cli_run leased until the sidecar invocation settles", async () => {
    let resolveInvocation;
    invoke.mockReturnValue(new Promise((resolve) => {
      resolveInvocation = resolve;
    }));

    const result = cliRun(["--status"]);
    const lease = beginOperation.mock.results[0].value;

    expect(beginOperation).toHaveBeenCalledOnce();
    expect(endOperation).not.toHaveBeenCalled();
    resolveInvocation({ stdout: "ok", stderr: "", exit_code: 0, timed_out: false });

    await expect(result).resolves.toMatchObject({ stdout: "ok" });
    expect(endOperation).toHaveBeenCalledOnce();
    expect(endOperation).toHaveBeenCalledWith(lease);
  });

  it("releases the lease when cli_version fails", async () => {
    invoke.mockRejectedValue(new Error("version probe failed"));

    await expect(cliVersion("C:\\codex-keysmith-cli.exe"))
      .rejects.toThrow("version probe failed");

    expect(beginOperation).toHaveBeenCalledOnce();
    expect(endOperation).toHaveBeenCalledWith(beginOperation.mock.results[0].value);
  });

  it("does not invoke a sidecar after application exit is queued", async () => {
    beginOperation.mockReturnValueOnce(null);

    await expect(cliRun(["--status"]))
      .rejects.toThrow("Application exit is pending");

    expect(invoke).not.toHaveBeenCalled();
    expect(endOperation).not.toHaveBeenCalled();
  });

  it.each([
    ["detect_cli", () => detectCli()],
    ["cli_runtime", () => cliRuntime("C:\\codex-keysmith-cli.exe")],
    ["read_manifest", () => readManifest("C:\\Users\\Administrator\\.codex")],
  ])("keeps %s covered by the backend lifecycle lease", async (command, run) => {
    invoke.mockResolvedValue({ ok: true });

    await expect(run()).resolves.toEqual({ ok: true });

    expect(invoke.mock.calls[0][0]).toBe(command);
    expect(beginOperation).toHaveBeenCalledOnce();
    expect(endOperation).toHaveBeenCalledWith(beginOperation.mock.results[0].value);
  });
});

const STATUS_OK = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: C:\\Users\\Administrator\\.codex ──
    config.toml: regular file (C:\\Users\\Administrator\\.codex\\config.toml)
    gpt-unrestricted.md: missing (C:\\Users\\Administrator\\.codex\\gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (C:\\Users\\Administrator\\.codex\\gpt5.5-unrestricted.md)
    hooks.json: missing (C:\\Users\\Administrator\\.codex\\hooks.json)
    hooks.json.disabled: missing (C:\\Users\\Administrator\\.codex\\hooks.json.disabled)
    deployment manifest: missing (C:\\Users\\Administrator\\.codex\\.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    Config activation: active
    Transaction residue: none
    Legacy migration: none
    Hooks status: absent
    Structural health: healthy
    Uninstall readiness: not-applicable
    Deployability: ready

[Done] Status found no blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.`;

const STATUS_CONFLICT = `[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: C:\\Users\\Administrator\\.codex ──
    config.toml: regular file (C:\\Users\\Administrator\\.codex\\config.toml)
    gpt-unrestricted.md: symbolic link (C:\\Users\\Administrator\\.codex\\gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (C:\\Users\\Administrator\\.codex\\gpt5.5-unrestricted.md)
    hooks.json: missing (C:\\Users\\Administrator\\.codex\\hooks.json)
    hooks.json.disabled: missing (C:\\Users\\Administrator\\.codex\\hooks.json.disabled)
    deployment manifest: missing (C:\\Users\\Administrator\\.codex\\.codex-keysmith-manifest.json)
    model_instructions_file: <unset or unrecognized>
    Config activation: conflict
    Transaction residue: none
    Legacy migration: none
    Hooks status: absent
    Structural health: blocked
    Uninstall readiness: not-applicable
    Deployability: blocked

[Error] 1 location(s) contain conflicts or abnormal nodes.`;

describe("resolveCli", () => {
  it("优先验证并使用已保存的手动 CLI 路径", async () => {
    const detect = vi.fn();
    const getVersion = vi.fn().mockResolvedValue("codex-keysmith 0.2.0");
    const getRuntime = vi.fn().mockResolvedValue("python");

    const result = await resolveCli(
      "  /tmp/codex-instruct.py  ",
      { detect, getVersion, getRuntime },
    );

    expect(result).toEqual({
      path: "/tmp/codex-instruct.py",
      version: "codex-keysmith 0.2.0",
      runtime: "python",
    });
    expect(detect).not.toHaveBeenCalled();
    expect(getVersion).toHaveBeenCalledWith("/tmp/codex-instruct.py");
    expect(getRuntime).toHaveBeenCalledWith("/tmp/codex-instruct.py");
  });

  it("未保存手动路径时保留 sidecar 自动探测", async () => {
    const detect = vi.fn().mockResolvedValue({
      path: "/Applications/codex-keysmith.app/Contents/MacOS/codex-keysmith-cli",
      runtime: "bundled",
    });
    const getVersion = vi.fn().mockResolvedValue("codex-keysmith 0.2.0");
    const getRuntime = vi.fn();

    const result = await resolveCli(
      "",
      { detect, getVersion, getRuntime },
    );

    expect(result).toEqual({
      path: "/Applications/codex-keysmith.app/Contents/MacOS/codex-keysmith-cli",
      version: "codex-keysmith 0.2.0",
      runtime: "bundled",
    });
    expect(detect).toHaveBeenCalledOnce();
    expect(getVersion).toHaveBeenCalledWith(
      "/Applications/codex-keysmith.app/Contents/MacOS/codex-keysmith-cli",
    );
    expect(getRuntime).not.toHaveBeenCalled();
  });

  it("手动路径校验失败时不会静默改用自动探测结果", async () => {
    const error = new Error("CLI 文件不存在");
    const detect = vi.fn();
    const getVersion = vi.fn().mockRejectedValue(error);
    const getRuntime = vi.fn();

    await expect(
      resolveCli(
        "/missing/codex-instruct.py",
        { detect, getVersion, getRuntime },
      ),
    ).rejects.toBe(error);
    expect(detect).not.toHaveBeenCalled();
    expect(getRuntime).not.toHaveBeenCalled();
  });

  it("自动探测无结果时返回未找到状态", async () => {
    const detect = vi.fn().mockResolvedValue(null);
    const getVersion = vi.fn();
    const getRuntime = vi.fn();

    await expect(
      resolveCli("   ", { detect, getVersion, getRuntime }),
    ).resolves.toEqual({
      path: null,
      version: "",
      runtime: "",
    });
    expect(getVersion).not.toHaveBeenCalled();
    expect(getRuntime).not.toHaveBeenCalled();
  });
});

describe("fetchStatus", () => {
  it("默认目录为空时不传 --codex-dir", async () => {
    invoke.mockResolvedValue({
      stdout: STATUS_OK,
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });

    await fetchStatus();

    expect(invoke).toHaveBeenCalledWith("cli_run", {
      cliPath: null,
      args: ["--status", "--lang", "en"],
      timeoutMs: 30_000,
    });
  });

  it("显式默认目录只传一个 --codex-dir", async () => {
    saveSettings({ defaultCodexDir: "C:\\Users\\Administrator\\.codex" });
    invoke.mockResolvedValue({
      stdout: STATUS_OK,
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });

    await fetchStatus();

    expect(invoke).toHaveBeenCalledWith("cli_run", {
      cliPath: null,
      args: [
        "--status",
        "--codex-dir",
        "C:\\Users\\Administrator\\.codex",
        "--lang",
        "en",
      ],
      timeoutMs: 30_000,
    });
  });

  it("成功报告保留退出与诊断元数据", async () => {
    invoke.mockResolvedValue({
      stdout: STATUS_OK,
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });

    await expect(fetchStatus()).resolves.toMatchObject({
      semanticComplete: true,
      exitCode: 0,
      stderr: "",
      timedOut: false,
      degraded: false,
      raw: STATUS_OK,
      directories: [{
        path: "C:\\Users\\Administrator\\.codex",
        activation: "active",
      }],
    });
  });

  it("exit 0 但 stderr 非空时保留报告并标记 degraded", async () => {
    invoke.mockResolvedValue({
      stdout: STATUS_OK,
      stderr: "runner emitted a diagnostic",
      exit_code: 0,
      timed_out: false,
    });

    await expect(fetchStatus()).resolves.toMatchObject({
      semanticComplete: true,
      exitCode: 0,
      stderr: "runner emitted a diagnostic",
      timedOut: false,
      degraded: true,
    });
  });

  it("exit 0 但非空报告不可识别时失败关闭", async () => {
    invoke.mockResolvedValue({
      stdout: "[Status] Output contract changed unexpectedly.\r\n",
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });

    await expect(fetchStatus()).rejects.toThrow("Output contract changed");
  });

  it("非零退出但已解析到完整目录报告时保留诊断状态", async () => {
    invoke.mockResolvedValue({
      stdout: STATUS_CONFLICT.replace(/\n/g, "\r\n"),
      stderr: "manual review required",
      exit_code: 1,
      timed_out: false,
    });

    await expect(fetchStatus()).resolves.toMatchObject({
      semanticComplete: true,
      exitCode: 1,
      stderr: "manual review required",
      timedOut: false,
      degraded: true,
      directories: [{
        path: "C:\\Users\\Administrator\\.codex",
        activation: "conflict",
      }],
    });
  });

  it("只有目录标题的截断报告即使 exit 0 也失败关闭", async () => {
    const stdout = `[Status] Found 1 Codex configuration location(s) (read-only inspection):\r\n\r\n── Status directory: C:\\Users\\Administrator\\.codex ──\r\n`;
    invoke.mockResolvedValue({
      stdout,
      stderr: "status output ended unexpectedly",
      exit_code: 0,
      timed_out: false,
    });

    await expect(fetchStatus()).rejects.toMatchObject({
      stdout,
      stderr: "status output ended unexpectedly",
      exitCode: 0,
      timedOut: false,
    });
  });

  it.each([
    ["exit 0 + error 终止句", STATUS_CONFLICT, 0],
    ["非零 exit + done 终止句", STATUS_OK, 1],
  ])("%s 失败关闭", async (_label, stdout, exitCode) => {
    invoke.mockResolvedValue({
      stdout,
      stderr: "",
      exit_code: exitCode,
      timed_out: false,
    });

    await expect(fetchStatus()).rejects.toBeInstanceOf(CliError);
  });

  it("超时即使已有部分可解析报告也失败", async () => {
    invoke.mockResolvedValue({
      stdout: STATUS_OK,
      stderr: "status timed out",
      exit_code: -1,
      timed_out: true,
    });

    await expect(fetchStatus()).rejects.toMatchObject({
      stdout: STATUS_OK,
      stderr: "status timed out",
      exitCode: -1,
      timedOut: true,
    });
  });

  it("CliError 同时保留 stdout 与 stderr 并合并到错误详情", () => {
    const error = new CliError({
      stdout: "partial status report",
      stderr: "runner diagnostic",
      exit_code: 1,
      timed_out: false,
    });

    expect(error.stdout).toBe("partial status report");
    expect(error.stderr).toBe("runner diagnostic");
    expect(error.message).toContain("runner diagnostic");
    expect(error.message).toContain("partial status report");
  });
});

describe("scenario CLI wrappers", () => {
  it("lists packages from --scenario-list", async () => {
    invoke.mockResolvedValue({
      stdout: `[Scenario library] /repo/scenarios
- example_fixture 1.0.0: ready; platforms=darwin,linux,win32; python=>=3.9,<3.15; requires=none; verify=verify.py
`,
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    const parsed = await fetchScenarioList();
    expect(parsed.packages).toHaveLength(1);
    expect(parsed.packages[0].id).toBe("example_fixture");
    expect(parsed.gate.ok).toBe(true);
    expect(invoke).toHaveBeenCalledWith(
      "cli_run",
      expect.objectContaining({ args: ["--scenario-list", "--lang", "en"] }),
    );
  });

  it("retries deploy preview with the canonical target", async () => {
    invoke
      .mockResolvedValueOnce({
        stdout: "[Error] --target-dir resolves through an indirect path; use the canonical path: /private/tmp/project",
        stderr: "",
        exit_code: 1,
        timed_out: false,
      })
      .mockResolvedValueOnce({
        stdout: `[Scenario deploy] example_fixture 1.0.0
[Target] /private/tmp/project
[Source] /repo/scenarios/example_fixture
[Files] 5
[Preview] no files were changed; add --yes to deploy
`,
        stderr: "",
        exit_code: 0,
        timed_out: false,
      });
    const parsed = await fetchScenarioDeployPreview("example_fixture", "/tmp/project");
    expect(parsed.canonicalTarget).toBe("/private/tmp/project");
    expect(parsed.gate.ok).toBe(true);
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke.mock.calls[1][1].args).toEqual([
      "--deploy-scenario",
      "example_fixture",
      "--target-dir",
      "/private/tmp/project",
      "--lang",
      "en",
    ]);
  });
});

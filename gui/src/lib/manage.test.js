import { describe, expect, it, vi } from "vitest";
import {
  buildRestoreHooksPreview,
  executeRestoreHooksPlans,
  isManagementPreviewValid,
  prepareManagementPreview,
  shouldRefreshManagementStatus,
} from "./manage.js";

const DIRECTORIES = [
  { path: "C:\\Users\\Admin\\.codex", hooksStatus: "restorable" },
  { path: "D:\\Codex", hooksStatus: "active" },
  { path: "E:\\Codex", hooksStatus: "restorable" },
];

describe("restore-hooks preview", () => {
  it("全部目录只计划 status 中可恢复的目标", () => {
    const preview = buildRestoreHooksPreview(DIRECTORIES);
    expect(preview.gate.ok).toBe(true);
    expect(preview.parsed.plans.map((plan) => plan.dir)).toEqual([
      "C:\\Users\\Admin\\.codex",
      "E:\\Codex",
    ]);
  });

  it("单目录选择只计划该目录", () => {
    const preview = buildRestoreHooksPreview(
      DIRECTORIES,
      "E:\\Codex",
    );
    expect(preview.parsed.plans.map((plan) => plan.dir)).toEqual(["E:\\Codex"]);
  });

  it("没有可恢复目标时门禁失败", () => {
    const preview = buildRestoreHooksPreview(DIRECTORIES, "D:\\Codex");
    expect(preview.parsed.plans).toEqual([]);
    expect(preview.gate).toEqual({ ok: false, reason: "no-restorable" });
  });

  it("生成预览不会调用真实 CLI", async () => {
    const runCli = vi.fn();
    const preview = await prepareManagementPreview({
      operation: "restore-hooks",
      directories: DIRECTORIES,
      targetDir: "",
      args: ["--restore-hooks", "--lang", "en"],
      runCli,
    });
    expect(runCli).not.toHaveBeenCalled();
    expect(preview.gate.ok).toBe(true);
  });

  it("默认目录是非规范写法时仍以 status 规范路径生成恢复计划", async () => {
    const runCli = vi.fn();
    const preview = await prepareManagementPreview({
      operation: "restore-hooks",
      directories: [{ path: "C:\\Users\\Admin\\.codex", hooksStatus: "restorable" }],
      targetDir: "",
      args: ["--restore-hooks", "--codex-dir", "c:\\users\\admin\\.codex\\", "--lang", "en"],
      runCli,
    });
    expect(runCli).not.toHaveBeenCalled();
    expect(preview.parsed.plans).toEqual([{
      dir: "C:\\Users\\Admin\\.codex",
      kind: "restore-hooks",
      summary: null,
      detail: null,
    }]);
  });

  it("卸载和恢复仍通过 CLI 获取预览", async () => {
    const runCli = vi.fn().mockResolvedValue({
      stdout: "[Done] No managed deployment was found; nothing to uninstall.",
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    const args = ["--uninstall", "--lang", "en"];
    const preview = await prepareManagementPreview({
      operation: "uninstall",
      directories: DIRECTORIES,
      targetDir: "",
      args,
      runCli,
    });
    expect(runCli).toHaveBeenCalledOnce();
    expect(runCli).toHaveBeenCalledWith(args);
    expect(preview.gate.ok).toBe(true);
  });

  it("目录选择变化会使已有预览失效", () => {
    const preview = { dirKey: "", statusRevision: 3, gate: { ok: true } };
    expect(isManagementPreviewValid(preview, "", 3)).toBe(true);
    expect(isManagementPreviewValid(preview, "E:\\Codex", 3)).toBe(false);
  });

  it("任一状态刷新都会使所有卡片的旧预览失效", () => {
    const preview = { dirKey: "", statusRevision: 3, gate: { ok: true } };
    expect(isManagementPreviewValid(preview, "", 4)).toBe(false);
  });

  it("状态快照更新后重复预览不再放行", () => {
    const first = buildRestoreHooksPreview(DIRECTORIES, "E:\\Codex");
    const refreshed = buildRestoreHooksPreview(
      DIRECTORIES.map((directory) => (
        directory.path === "E:\\Codex"
          ? { ...directory, hooksStatus: "active" }
          : directory
      )),
      "E:\\Codex",
    );
    expect(first.gate.ok).toBe(true);
    expect(refreshed.gate).toEqual({ ok: false, reason: "no-restorable" });
  });

  it("确认执行时仅对预览目标逐个调用 restore-hooks", async () => {
    const runCli = vi.fn().mockResolvedValue({
      stdout: "restored",
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    const plans = buildRestoreHooksPreview(DIRECTORIES).parsed.plans;
    const output = await executeRestoreHooksPlans(plans, runCli);

    expect(runCli).toHaveBeenCalledTimes(2);
    expect(runCli).toHaveBeenNthCalledWith(
      1,
      ["--restore-hooks", "--codex-dir", "C:\\Users\\Admin\\.codex", "--lang", "en"],
      120_000,
    );
    expect(runCli).toHaveBeenNthCalledWith(
      2,
      ["--restore-hooks", "--codex-dir", "E:\\Codex", "--lang", "en"],
      120_000,
    );
    expect(output).toMatchObject({ exit_code: 0, timed_out: false });
    expect(output.attempted).toEqual([
      "C:\\Users\\Admin\\.codex",
      "E:\\Codex",
    ]);
    expect(output.succeeded).toEqual(output.attempted);
    expect(output.partial).toBe(false);
  });

  it("先成功后失败时保留成功路径和全部输出", async () => {
    const runCli = vi.fn()
      .mockResolvedValueOnce({
        stdout: "first restored",
        stderr: "",
        exit_code: 0,
        timed_out: false,
      })
      .mockResolvedValueOnce({
        stdout: "",
        stderr: "second failed",
        exit_code: 1,
        timed_out: false,
      });
    const plans = buildRestoreHooksPreview(DIRECTORIES).parsed.plans;
    const output = await executeRestoreHooksPlans(plans, runCli);

    expect(runCli).toHaveBeenCalledTimes(2);
    expect(output).toMatchObject({
      attempted: ["C:\\Users\\Admin\\.codex", "E:\\Codex"],
      succeeded: ["C:\\Users\\Admin\\.codex"],
      partial: true,
      stderr: "second failed",
      exit_code: 1,
      timed_out: false,
    });
    expect(output.results).toHaveLength(2);
    expect(output.text).toContain("C:\\Users\\Admin\\.codex");
    expect(output.text).toContain("first restored");
    expect(output.text).toContain("E:\\Codex");
    expect(output.text).toContain("second failed");
  });

  it("先成功后超时仍标记部分完成并保留证据", async () => {
    const runCli = vi.fn()
      .mockResolvedValueOnce({
        stdout: "first restored",
        stderr: "",
        exit_code: 0,
        timed_out: false,
      })
      .mockResolvedValueOnce({
        stdout: "",
        stderr: "",
        exit_code: -1,
        timed_out: true,
      });
    const output = await executeRestoreHooksPlans(
      buildRestoreHooksPreview(DIRECTORIES).parsed.plans,
      runCli,
    );
    expect(output).toMatchObject({
      attempted: ["C:\\Users\\Admin\\.codex", "E:\\Codex"],
      succeeded: ["C:\\Users\\Admin\\.codex"],
      partial: true,
      exit_code: -1,
      timed_out: true,
    });
    expect(output.text).toContain("first restored");
    expect(output.text).toContain("Timed out");
  });

  it("CLI 抛错会转成逐目录失败结果而不是丢失前序成功", async () => {
    const runCli = vi.fn()
      .mockResolvedValueOnce({
        stdout: "first restored",
        stderr: "",
        exit_code: 0,
        timed_out: false,
      })
      .mockRejectedValueOnce(new Error("transport unavailable"));
    const output = await executeRestoreHooksPlans(
      buildRestoreHooksPreview(DIRECTORIES).parsed.plans,
      runCli,
    );
    expect(output).toMatchObject({
      succeeded: ["C:\\Users\\Admin\\.codex"],
      partial: true,
      exit_code: 1,
      timed_out: false,
    });
    expect(output.results[1]).toMatchObject({
      dir: "E:\\Codex",
      error: "transport unavailable",
    });
    expect(output.text).toContain("first restored");
    expect(output.text).toContain("transport unavailable");
  });

  it("restore-hooks 只要尝试过目标就刷新状态", () => {
    expect(shouldRefreshManagementStatus("restore-hooks", {
      attempted: ["C:\\Users\\Admin\\.codex"],
      exit_code: 1,
      timed_out: false,
    })).toBe(true);
    expect(shouldRefreshManagementStatus("restore-hooks", {
      attempted: [],
      exit_code: 1,
      timed_out: false,
    })).toBe(false);
    expect(shouldRefreshManagementStatus("uninstall", {
      exit_code: 0,
      timed_out: false,
    })).toBe(true);
    expect(shouldRefreshManagementStatus("uninstall", {
      exit_code: 1,
      timed_out: false,
    })).toBe(true);
    expect(shouldRefreshManagementStatus("recover", {
      exit_code: -1,
      timed_out: true,
    })).toBe(true);
    expect(shouldRefreshManagementStatus("uninstall", null, true)).toBe(true);
  });
});

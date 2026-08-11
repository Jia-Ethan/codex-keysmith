import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CliError } from "@/lib/api";
import { refreshDashboardSnapshot, StatusFailure } from "./Dashboard.jsx";

vi.mock("@/components/FadeIn", () => ({
  FadeIn: ({ children }) => <div>{children}</div>,
}));

const t = (key) => key;

describe("Dashboard status snapshot lifecycle", () => {
  it("刷新开始即清空旧卡片和全局快照，再写入新状态", async () => {
    const nextStatus = { directories: [{ path: "/fresh/.codex" }] };
    const setStatusState = vi.fn();
    const setCachedStatus = vi.fn();

    await expect(refreshDashboardSnapshot({
      fetcher: vi.fn().mockResolvedValue(nextStatus),
      setStatusState,
      setCachedStatus,
    })).resolves.toBe(nextStatus);

    expect(setStatusState.mock.calls).toEqual([[null], [nextStatus]]);
    expect(setCachedStatus.mock.calls).toEqual([[null], [nextStatus]]);
  });

  it("刷新失败后不恢复旧卡片或旧全局快照", async () => {
    const error = new Error("status contract changed");
    const setStatusState = vi.fn();
    const setCachedStatus = vi.fn();

    await expect(refreshDashboardSnapshot({
      fetcher: vi.fn().mockRejectedValue(error),
      setStatusState,
      setCachedStatus,
    })).rejects.toBe(error);

    expect(setStatusState).toHaveBeenCalledOnce();
    expect(setStatusState).toHaveBeenCalledWith(null);
    expect(setCachedStatus).toHaveBeenCalledOnce();
    expect(setCachedStatus).toHaveBeenCalledWith(null);
  });
});

describe("Dashboard status failure diagnostics", () => {
  it("分别展示 timeout、exit code、stdout 与 stderr", () => {
    const error = new CliError({
      stdout: "partial status report",
      stderr: "runner timed out",
      exit_code: -1,
      timed_out: true,
    });

    const html = renderToStaticMarkup(<StatusFailure error={error} t={t} />);

    expect(html).toContain("dash.diagnosticTimeout");
    expect(html).toContain("dash.diagnosticExitCode");
    expect(html).toContain("partial status report");
    expect(html).toContain("runner timed out");
  });

  it("普通错误没有结构化输出时展示 message", () => {
    const html = renderToStaticMarkup(
      <StatusFailure error={new Error("status bridge unavailable")} t={t} />,
    );

    expect(html).toContain("status bridge unavailable");
  });
});

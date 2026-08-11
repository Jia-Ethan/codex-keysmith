import { afterEach, describe, expect, it, vi } from "vitest";
import {
  beginOperation,
  beginExclusiveOperation,
  beginCliCheck,
  completeCliCheck,
  endOperation,
  getState,
  requestExitWhenIdle,
  resetOperationCoordinatorForTests,
  setCliInfo,
  setView,
} from "./store.js";

afterEach(() => {
  resetOperationCoordinatorForTests();
  setView("dashboard");
});

describe("CLI 检测结果时序", () => {
  it("只允许最新请求写入，防止启动检测覆盖设置页结果", () => {
    const startup = beginCliCheck();
    const settings = beginCliCheck();

    expect(completeCliCheck(startup, {
      path: "/stale/cli",
      checked: true,
    })).toBe(false);
    expect(completeCliCheck(settings, {
      path: "/current/cli",
      version: "0.2.0",
      runtime: "bundled",
      error: null,
      checked: true,
    })).toBe(true);
    expect(getState().cliInfo.path).toBe("/current/cli");
  });

  it("直接更新也会使进行中的旧检测失效", () => {
    const pending = beginCliCheck();
    setCliInfo({ path: "/selected/cli", checked: true });

    expect(completeCliCheck(pending, {
      path: "/stale/cli",
      checked: true,
    })).toBe(false);
    expect(getState().cliInfo.path).toBe("/selected/cli");
  });
});

describe("操作租约与关闭生命周期", () => {
  it("成功结束租约后恢复空闲", () => {
    const lease = beginOperation();

    expect(getState().operationCount).toBe(1);
    expect(getState().operationInProgress).toBe(true);
    expect(endOperation(lease)).toBe(true);
    expect(getState().operationCount).toBe(0);
    expect(getState().operationInProgress).toBe(false);
  });

  it("等待所有并发租约结束", () => {
    const first = beginOperation();
    const second = beginOperation();

    expect(getState().operationCount).toBe(2);
    expect(endOperation(first)).toBe(true);
    expect(getState().operationCount).toBe(1);
    expect(getState().operationInProgress).toBe(true);
    expect(endOperation(second)).toBe(true);
    expect(getState().operationInProgress).toBe(false);
  });

  it("重复结束旧租约不会释放新操作", () => {
    const completed = beginOperation();
    expect(endOperation(completed)).toBe(true);

    const current = beginOperation();
    expect(endOperation(completed)).toBe(false);
    expect(getState().operationCount).toBe(1);
    expect(getState().operationInProgress).toBe(true);

    expect(endOperation(current)).toBe(true);
    expect(getState().operationInProgress).toBe(false);
  });

  it("最后一个操作结束后只执行一次排队退出", async () => {
    const exit = vi.fn();
    const first = beginOperation();
    const second = beginOperation();

    expect(requestExitWhenIdle(exit)).toBe("queued");
    expect(getState().pendingExit).toBe(true);
    expect(endOperation(first)).toBe(true);
    expect(exit).not.toHaveBeenCalled();

    expect(endOperation(second)).toBe(true);
    expect(exit).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();

    expect(endOperation(second)).toBe(false);
    expect(exit).toHaveBeenCalledTimes(1);
  });

  it("空闲关闭先建立屏障并立即显式退出", async () => {
    const exit = vi.fn();

    expect(requestExitWhenIdle(exit)).toBe("started");
    expect(exit).toHaveBeenCalledOnce();
    expect(beginOperation()).toBeNull();
    expect(getState().pendingExit).toBe(true);
    await Promise.resolve();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();
  });

  it("退出排队及执行期间拒绝新的通用操作租约", async () => {
    let resolveExit;
    const exit = vi.fn(() => new Promise((resolve) => {
      resolveExit = resolve;
    }));
    const current = beginOperation();

    expect(requestExitWhenIdle(exit)).toBe("queued");
    expect(beginOperation()).toBeNull();
    expect(endOperation(current)).toBe(true);
    expect(exit).toHaveBeenCalledOnce();
    expect(beginOperation()).toBeNull();
    expect(getState().operationCount).toBe(0);
    expect(getState().pendingExit).toBe(true);

    resolveExit();
    await Promise.resolve();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();
  });

  it("全局写操作租约拒绝并发与排队退出后的新操作", async () => {
    const first = beginExclusiveOperation();
    expect(first).not.toBeNull();
    expect(beginExclusiveOperation()).toBeNull();

    const exit = vi.fn();
    expect(requestExitWhenIdle(exit)).toBe("queued");
    expect(beginExclusiveOperation()).toBeNull();
    expect(endOperation(first)).toBe(true);
    await Promise.resolve();

    expect(exit).toHaveBeenCalledOnce();
    expect(beginExclusiveOperation()).toBeNull();
  });

  it("排队退出失败时保留请求，并在再次关闭时重试", async () => {
    expect(setView("dashboard")).toBe(true);
    const exit = vi.fn()
      .mockRejectedValueOnce(new Error("destroy failed"))
      .mockResolvedValueOnce(undefined);
    const lease = beginOperation();

    expect(requestExitWhenIdle(exit)).toBe("queued");
    expect(endOperation(lease)).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    expect(getState().pendingExit).toBe(true);
    expect(getState().operationInProgress).toBe(true);
    expect(beginExclusiveOperation()).toBeNull();
    expect(setView("manage")).toBe(false);
    expect(getState().view).toBe("dashboard");

    expect(requestExitWhenIdle(exit)).toBe("started");
    await Promise.resolve();
    await Promise.resolve();
    expect(exit).toHaveBeenCalledTimes(2);
    expect(getState().pendingExit).toBe(true);
    expect(getState().operationInProgress).toBe(true);
    expect(beginExclusiveOperation()).toBeNull();
    expect(setView("manage")).toBe(false);
  });

  it("写操作期间拒绝切换视图", () => {
    expect(setView("dashboard")).toBe(true);
    const lease = beginOperation();

    expect(setView("manage")).toBe(false);
    expect(getState().view).toBe("dashboard");

    expect(endOperation(lease)).toBe(true);
    expect(setView("manage")).toBe(true);
    expect(getState().view).toBe("manage");
    setView("dashboard");
  });
});

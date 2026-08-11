import { describe, expect, it } from "vitest";
import {
  beginOperation,
  beginCliCheck,
  completeCliCheck,
  endOperation,
  getState,
  setCliInfo,
  setView,
} from "./store.js";

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

describe("全局写操作锁", () => {
  it("只允许锁持有者释放，阻止 Deploy 与 Manage 并发写入", () => {
    expect(beginOperation("deploy")).toBe(true);
    expect(beginOperation("manage:uninstall")).toBe(false);
    expect(getState()).toMatchObject({
      operationOwner: "deploy",
      operationInProgress: true,
    });
    const currentView = getState().view;
    const otherView = currentView === "manage" ? "deploy" : "manage";
    expect(setView(otherView)).toBe(false);
    expect(getState().view).toBe(currentView);

    expect(endOperation("manage:uninstall")).toBe(false);
    expect(getState().operationInProgress).toBe(true);
    expect(endOperation("deploy")).toBe(true);
    expect(getState()).toMatchObject({
      operationOwner: null,
      operationInProgress: false,
    });
  });
});

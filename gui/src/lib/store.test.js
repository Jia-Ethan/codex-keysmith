import { describe, expect, it } from "vitest";
import {
  beginCliCheck,
  completeCliCheck,
  getState,
  setCliInfo,
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

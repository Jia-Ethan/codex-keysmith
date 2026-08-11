import { describe, expect, it, vi } from "vitest";
import { invalidateManageSnapshots } from "./Manage.jsx";

describe("Manage write-success invalidation", () => {
  it("使状态请求、全局状态和所有卡片预览代次同时失效", () => {
    const statusRequestGeneration = { current: 4 };
    const setStatusState = vi.fn();
    const setCachedStatus = vi.fn();
    const setPreviewEpoch = vi.fn();

    invalidateManageSnapshots({
      statusRequestGeneration,
      setStatusState,
      setCachedStatus,
      setPreviewEpoch,
    });

    expect(statusRequestGeneration.current).toBe(5);
    expect(setStatusState).toHaveBeenCalledOnce();
    expect(setStatusState).toHaveBeenCalledWith(null);
    expect(setCachedStatus).toHaveBeenCalledOnce();
    expect(setCachedStatus).toHaveBeenCalledWith(null);
    expect(setPreviewEpoch).toHaveBeenCalledOnce();
    expect(setPreviewEpoch.mock.calls[0][0](7)).toBe(8);
  });
});

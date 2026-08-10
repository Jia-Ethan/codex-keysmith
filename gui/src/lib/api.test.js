import { describe, expect, it, vi } from "vitest";
import { resolveCli } from "./api.js";

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

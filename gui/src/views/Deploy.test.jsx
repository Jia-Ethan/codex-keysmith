import { describe, expect, it } from "vitest";
import { buildDeployArgs, isInactiveConfigBlocker } from "./Deploy.jsx";

describe("Deploy argument binding", () => {
  it.each(["unrestricted", "contract"])("passes the selected bundled preset: %s", (preset) => {
    expect(buildDeployArgs({
      source: "bundled",
      preset,
      filePath: "",
      name: "",
      codexDir: "",
      skipHooks: false,
    })).toEqual(["--preset", preset]);
  });

  it("uses a local file without carrying the hidden preset", () => {
    expect(buildDeployArgs({
      source: "file",
      preset: "contract",
      filePath: "/tmp/local.md",
      name: " local-rules ",
      codexDir: " /tmp/.codex ",
      skipHooks: true,
    })).toEqual([
      "--file",
      "/tmp/local.md",
      "--name",
      "local-rules",
      "--codex-dir",
      "/tmp/.codex",
      "--skip-hooks-isolation",
    ]);
  });

  it("never falls back to a preset while local-file mode is selected", () => {
    expect(buildDeployArgs({
      source: "file",
      preset: "contract",
      filePath: "",
      name: "",
      codexDir: "",
      skipHooks: false,
    })).toEqual([]);
  });
});

describe("inactive-by-config deploy blockers", () => {
  it("recognizes a missing top-level field as the constrained restore case", () => {
    expect(isInactiveConfigBlocker(
      "existing deployment manifest ownership conflict: top-level config.toml model_instructions_file is missing; expected it to still reference ./gpt-unrestricted.md",
    )).toBe(true);
    expect(isInactiveConfigBlocker(
      "现有部署清单所有权冲突: config.toml 顶层 model_instructions_file 当前缺失",
    )).toBe(true);
    expect(isInactiveConfigBlocker(
      "the current field is set to another path",
    )).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { buildDeployArgs } from "./Deploy.jsx";

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

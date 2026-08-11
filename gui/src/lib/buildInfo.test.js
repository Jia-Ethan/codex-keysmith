import { describe, expect, it } from "vitest";
import packageJson from "../../package.json";
import { buildInfo, normalizeBuildInfo } from "./buildInfo.js";

describe("buildInfo", () => {
  it("marks a full source commit as a candidate build", () => {
    const sourceCommit = "a".repeat(40);

    expect(normalizeBuildInfo({ desktopVersion: "0.2.0", sourceCommit })).toEqual({
      desktopVersion: "0.2.0",
      channel: "candidate",
      sourceCommit,
    });
  });

  it("treats a missing or malformed source commit as development", () => {
    expect(normalizeBuildInfo({ desktopVersion: "0.2.0", sourceCommit: "main" })).toEqual({
      desktopVersion: "0.2.0",
      channel: "development",
      sourceCommit: null,
    });
  });

  it("uses the package version and a consistent injected channel", () => {
    expect(buildInfo.desktopVersion).toBe(packageJson.version);
    expect(buildInfo.channel).toBe(buildInfo.sourceCommit ? "candidate" : "development");
  });
});

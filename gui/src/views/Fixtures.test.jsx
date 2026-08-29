import { describe, expect, it } from "vitest";
import {
  classifyFixtureExecution,
  createFixturePreviewSnapshot,
  fixtureLibraryIsEmpty,
  isFixturePreviewCurrent,
} from "./Fixtures.jsx";

describe("Fixtures preview binding", () => {
  const parsed = {
    gate: { ok: true },
    dest: "/tmp/workspace/pytest_complete",
    previewOnly: true,
  };

  it("binds overwrite permission to the reviewed write preview", () => {
    const preview = createFixturePreviewSnapshot({
      parsed,
      kind: "write",
      packId: "pytest_complete",
      workspaceRoot: " /tmp/workspace ",
      force: false,
    });

    expect(isFixturePreviewCurrent(preview, {
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    })).toBe(true);
    expect(isFixturePreviewCurrent(preview, {
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: true,
    })).toBe(false);
  });

  it("does not make delete previews depend on the write-only force option", () => {
    const preview = createFixturePreviewSnapshot({
      parsed,
      kind: "uninstall",
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: true,
    });

    expect(preview.force).toBe(false);
    expect(isFixturePreviewCurrent(preview, {
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    })).toBe(true);
  });

  it("does not confirm deletion when the pack is not materialized", () => {
    const preview = createFixturePreviewSnapshot({
      parsed: { ...parsed, notMaterialized: true },
      kind: "uninstall",
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    });

    expect(isFixturePreviewCurrent(preview, {
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    })).toBe(false);
  });

  it("does not confirm a write that already matches the pack", () => {
    const preview = createFixturePreviewSnapshot({
      parsed: { ...parsed, unchanged: true },
      kind: "write",
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    });

    expect(isFixturePreviewCurrent(preview, {
      packId: "pytest_complete",
      workspaceRoot: "/tmp/workspace",
      force: false,
    })).toBe(false);
  });
});

describe("Fixtures execution result", () => {
  const successfulOutput = { exit_code: 0, timed_out: false };
  const completeResult = { semanticComplete: true, didNotModifyCodex: true };

  it("accepts only the expected completed action", () => {
    expect(classifyFixtureExecution("write", successfulOutput, {
      ...completeResult,
      wrote: true,
    })).toBe("success");
    expect(classifyFixtureExecution("uninstall", successfulOutput, {
      ...completeResult,
      removed: true,
    })).toBe("success");
  });

  it("reports an uninstall race as a no-op instead of a removal", () => {
    expect(classifyFixtureExecution("uninstall", successfulOutput, {
      ...completeResult,
      notMaterialized: true,
    })).toBe("noop");
  });

  it("reports an already-current write as a no-op", () => {
    expect(classifyFixtureExecution("write", successfulOutput, {
      ...completeResult,
      unchanged: true,
    })).toBe("noop");
  });

  it("rejects incomplete or preview-only execution output", () => {
    expect(classifyFixtureExecution("write", successfulOutput, {
      ...completeResult,
      previewOnly: true,
    })).toBe("failure");
    expect(classifyFixtureExecution("uninstall", successfulOutput, {
      didNotModifyCodex: true,
      semanticComplete: false,
      removed: true,
    })).toBe("failure");
  });
});

describe("Fixtures library state", () => {
  it("recognizes the CLI no-packs result", () => {
    expect(fixtureLibraryIsEmpty({ empty: true, packages: [] })).toBe(true);
    expect(fixtureLibraryIsEmpty({ empty: false, packages: [] })).toBe(false);
    expect(fixtureLibraryIsEmpty({ empty: true, packages: [{ id: "pack" }] })).toBe(false);
  });
});

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  ScenarioStatusDiagnostics,
  ScenarioWriteResult,
  createScenarioPreviewSnapshot,
  formatScenarioCommandOutput,
  getScenarioWriteParameters,
  invalidateScenarioTargetState,
  isScenarioPreviewCurrent,
  isScenarioRequestCurrent,
  nextScenarioRequestGenerations,
} from "./Scenarios.jsx";

vi.mock("@/components/ui/collapsible", () => ({
  Collapsible: ({ children }) => <div>{children}</div>,
  CollapsibleTrigger: ({ children }) => <button>{children}</button>,
  CollapsibleContent: ({ children }) => <div>{children}</div>,
}));

const t = (key) => key;

describe("Scenarios request and preview binding", () => {
  it("invalidates old target requests while preserving the canonical retry response", () => {
    const current = { status: 2, deploy: 4, uninstall: 1, recover: 3 };
    expect(nextScenarioRequestGenerations(current)).toEqual({
      status: 3,
      deploy: 5,
      uninstall: 2,
      recover: 4,
    });
    expect(nextScenarioRequestGenerations(current, "deploy")).toEqual({
      status: 3,
      deploy: 4,
      uninstall: 2,
      recover: 4,
    });
  });

  it("clears target-bound UI state immediately and ignores stale responses", () => {
    const requestGenerations = {
      current: { status: 2, deploy: 4, uninstall: 1, recover: 3 },
    };
    const setters = {
      setStatus: vi.fn(),
      setDeployPreview: vi.fn(),
      setUninstallPreview: vi.fn(),
      setRecoverPreview: vi.fn(),
      setPending: vi.fn(),
      setWriteResult: vi.fn(),
      setLoading: vi.fn(),
    };

    invalidateScenarioTargetState({ requestGenerations, ...setters });

    for (const setter of Object.values(setters).slice(0, -1)) {
      expect(setter).toHaveBeenCalledWith(null);
    }
    expect(setters.setLoading.mock.calls[0][0]({
      list: true,
      status: true,
      deploy: true,
      uninstall: true,
      recover: true,
    })).toEqual({
      list: true,
      status: false,
      deploy: false,
      uninstall: false,
      recover: false,
    });
    expect(isScenarioRequestCurrent(
      { kind: "deploy", generation: 4, targetDir: "/old", scenarioId: "alpha" },
      {
        generations: requestGenerations.current,
        targetDir: "/new",
        selectedId: "beta",
      },
    )).toBe(false);
  });

  it("keeps a canonical preview bound to the reviewed scenario and execution target", () => {
    const preview = createScenarioPreviewSnapshot({
      kind: "deploy",
      requestedTarget: "/tmp/project",
      scenarioId: "alpha",
      parsed: {
        scenarioId: "alpha",
        target: "/private/tmp/project",
        canonicalTarget: "/private/tmp/project",
        gate: { ok: true },
        raw: "preview alpha",
      },
    });

    expect(isScenarioPreviewCurrent(preview, {
      kind: "deploy",
      targetDir: "/private/tmp/project",
      selectedId: "alpha",
    })).toBe(true);
    expect(isScenarioPreviewCurrent(preview, {
      kind: "deploy",
      targetDir: "/private/tmp/project",
      selectedId: "beta",
    })).toBe(false);
    expect(getScenarioWriteParameters(preview)).toEqual({
      kind: "deploy",
      targetDir: "/private/tmp/project",
      scenarioId: "alpha",
    });
    expect(() => getScenarioWriteParameters({ kind: "status", targetDir: "/tmp" }))
      .toThrow("unsupported scenario preview kind");
  });

  it("fails closed when CLI preview identity differs from the request", () => {
    const preview = createScenarioPreviewSnapshot({
      kind: "deploy",
      requestedTarget: "/project",
      scenarioId: "alpha",
      parsed: {
        scenarioId: "beta",
        target: "/project",
        canonicalTarget: "/project",
        gate: { ok: true },
      },
    });

    expect(preview.gate).toMatchObject({ ok: false, reason: "unrecognized" });
  });
});

describe("Scenarios diagnostics", () => {
  it("renders status blockers and complete raw output", () => {
    const html = renderToStaticMarkup(
      <ScenarioStatusDiagnostics
        t={t}
        status={{
          blockers: ["scenario control directory contains unknown members: unknown"],
          raw: "[Scenario state] conflict",
          stderr: "runner diagnostic",
        }}
      />,
    );

    expect(html).toContain("scenarios.statusBlockers");
    expect(html).toContain("unknown members");
    expect(html).toContain("[stdout]");
    expect(html).toContain("[Scenario state] conflict");
    expect(html).toContain("[stderr]");
    expect(html).toContain("runner diagnostic");
  });

  it("renders timeout/failure output without dropping stdout or stderr", () => {
    const result = {
      kind: "deploy",
      ok: false,
      timedOut: true,
      exitCode: -1,
      message: "scenarios.timedOut",
      stdout: "partial deployment report",
      stderr: "process tree timed out",
    };
    const html = renderToStaticMarkup(<ScenarioWriteResult result={result} t={t} />);

    expect(html).toContain("scenarios.timedOut");
    expect(html).not.toContain("scenarios.writeFailed");
    expect(html).toContain("partial deployment report");
    expect(html).toContain("process tree timed out");
    expect(formatScenarioCommandOutput(result)).toContain("[stdout]");
    expect(formatScenarioCommandOutput(result)).toContain("[stderr]");
  });
});

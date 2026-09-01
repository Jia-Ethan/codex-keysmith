import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { Boxes, FolderOpen, ShieldAlert, Undo2 } from "lucide-react";
import {
  fetchScenarioList,
  fetchScenarioStatus,
  fetchScenarioDeployPreview,
  executeScenarioDeploy,
  fetchScenarioUninstallPreview,
  executeScenarioUninstall,
  fetchScenarioRecoverPreview,
  executeScenarioRecover,
} from "@/lib/api";
import { useAppState } from "@/hooks/useAppState";
import {
  beginExclusiveOperation,
  endOperation,
  setView,
} from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/FadeIn";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

function previewReasonKey(reason) {
  if (reason === "timeout") return "deploy.previewTimeout";
  if (reason === "empty") return "deploy.previewEmpty";
  if (reason === "unrecognized") return "deploy.previewUnrecognized";
  if (reason === "blockers") return "deploy.blockers";
  return "deploy.previewFailed";
}

const SCENARIO_REQUEST_KINDS = ["status", "deploy", "uninstall", "recover"];

function normalizeScenarioTarget(value) {
  return String(value || "").trim();
}

export function nextScenarioRequestGenerations(current, preserveRequest = null) {
  return Object.fromEntries(
    SCENARIO_REQUEST_KINDS.map((kind) => [
      kind,
      Number(current?.[kind] || 0) + (kind === preserveRequest ? 0 : 1),
    ]),
  );
}

export function invalidateScenarioTargetState({
  requestGenerations,
  preserveRequest = null,
  setStatus,
  setDeployPreview,
  setUninstallPreview,
  setRecoverPreview,
  setPending,
  setWriteResult,
  setLoading,
}) {
  requestGenerations.current = nextScenarioRequestGenerations(
    requestGenerations.current,
    preserveRequest,
  );
  setStatus(null);
  setDeployPreview(null);
  setUninstallPreview(null);
  setRecoverPreview(null);
  setPending(null);
  setWriteResult(null);
  setLoading((state) => ({
    ...state,
    status: preserveRequest === "status" ? state.status : false,
    deploy: preserveRequest === "deploy" ? state.deploy : false,
    uninstall: preserveRequest === "uninstall" ? state.uninstall : false,
    recover: preserveRequest === "recover" ? state.recover : false,
  }));
}

export function isScenarioRequestCurrent(request, current) {
  if (!request || current.generations?.[request.kind] !== request.generation) return false;
  if (normalizeScenarioTarget(request.targetDir) !== normalizeScenarioTarget(current.targetDir)) {
    return false;
  }
  if (request.kind === "deploy" && request.scenarioId !== current.selectedId) return false;
  return true;
}

export function createScenarioPreviewSnapshot({
  kind,
  parsed,
  requestedTarget,
  scenarioId = null,
  deploymentId = null,
}) {
  const targetDir = normalizeScenarioTarget(parsed.canonicalTarget || requestedTarget);
  let gate = parsed.gate;

  if (gate?.ok) {
    const reportedTarget = normalizeScenarioTarget(parsed.target);
    let detail = null;
    if (reportedTarget && reportedTarget !== targetDir) {
      detail = `CLI preview target did not match the canonical target: ${reportedTarget}`;
    } else if (kind === "deploy" && parsed.scenarioId !== scenarioId) {
      detail = `CLI preview scenario did not match the request: ${parsed.scenarioId || "<missing>"}`;
    } else if (kind === "uninstall" && parsed.deploymentId !== deploymentId) {
      detail = `CLI preview deployment did not match the request: ${parsed.deploymentId || "<missing>"}`;
    }
    if (detail) gate = { ok: false, reason: "unrecognized", detail };
  }

  return {
    ...parsed,
    gate,
    kind,
    targetDir,
    requestedScenarioId: scenarioId,
    requestedDeploymentId: deploymentId,
  };
}

export function isScenarioPreviewCurrent(preview, { kind, targetDir, selectedId = null }) {
  if (!preview || preview.kind !== kind || !preview.gate?.ok) return false;
  const currentTarget = normalizeScenarioTarget(targetDir);
  if (preview.targetDir !== currentTarget) return false;
  if (preview.target && normalizeScenarioTarget(preview.target) !== currentTarget) return false;
  if (kind === "deploy") {
    return preview.requestedScenarioId === selectedId && preview.scenarioId === selectedId;
  }
  if (kind === "uninstall") {
    return Boolean(preview.requestedDeploymentId)
      && preview.deploymentId === preview.requestedDeploymentId;
  }
  return true;
}

export function getScenarioWriteParameters(preview) {
  if (!preview?.kind || !preview.targetDir) throw new Error("scenario preview snapshot is incomplete");
  if (preview.kind === "deploy") {
    return { kind: "deploy", targetDir: preview.targetDir, scenarioId: preview.scenarioId };
  }
  if (preview.kind === "uninstall") {
    return {
      kind: "uninstall",
      targetDir: preview.targetDir,
      deploymentId: preview.deploymentId,
    };
  }
  if (preview.kind === "recover") {
    return { kind: "recover", targetDir: preview.targetDir };
  }
  throw new Error(`unsupported scenario preview kind: ${preview.kind}`);
}

export function formatScenarioCommandOutput({ stdout, stderr } = {}) {
  const sections = [];
  if (String(stdout || "").trim()) sections.push(`[stdout]\n${String(stdout).trim()}`);
  if (String(stderr || "").trim()) sections.push(`[stderr]\n${String(stderr).trim()}`);
  return sections.join("\n\n");
}

export function Scenarios() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [targetDir, setTargetDir] = React.useState("");
  const [library, setLibrary] = React.useState(null);
  const [status, setStatus] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [deployPreview, setDeployPreview] = React.useState(null);
  const [uninstallPreview, setUninstallPreview] = React.useState(null);
  const [recoverPreview, setRecoverPreview] = React.useState(null);
  const [pending, setPending] = React.useState(null);
  const [writeResult, setWriteResult] = React.useState(null);
  const [loading, setLoading] = React.useState({
    list: false,
    status: false,
    deploy: false,
    uninstall: false,
    recover: false,
  });
  const targetDirRef = React.useRef("");
  const selectedIdRef = React.useRef(null);
  const requestGenerations = React.useRef({
    status: 0,
    deploy: 0,
    uninstall: 0,
    recover: 0,
  });

  const cliChecking = !cliInfo.checked;
  const cliUnavailable = cliInfo.checked && !cliInfo.path;
  const selected = library?.packages.find((item) => item.id === selectedId) || null;

  const setScenarioTarget = React.useCallback((value, { preserveRequest = null } = {}) => {
    const nextTarget = normalizeScenarioTarget(value);
    if (nextTarget === targetDirRef.current) return nextTarget;
    invalidateScenarioTargetState({
      requestGenerations,
      preserveRequest,
      setStatus,
      setDeployPreview,
      setUninstallPreview,
      setRecoverPreview,
      setPending,
      setWriteResult,
      setLoading,
    });
    targetDirRef.current = nextTarget;
    setTargetDir(nextTarget);
    return nextTarget;
  }, []);

  const selectScenario = React.useCallback((scenarioId) => {
    if (scenarioId === selectedIdRef.current) return;
    requestGenerations.current = {
      ...requestGenerations.current,
      deploy: requestGenerations.current.deploy + 1,
    };
    selectedIdRef.current = scenarioId;
    setSelectedId(scenarioId);
    setDeployPreview(null);
    setPending(null);
    setWriteResult(null);
    setLoading((state) => ({ ...state, deploy: false }));
  }, []);

  const requestIsCurrent = (request) => isScenarioRequestCurrent(request, {
    generations: requestGenerations.current,
    targetDir: targetDirRef.current,
    selectedId: selectedIdRef.current,
  });

  const refreshLibrary = React.useCallback(async () => {
    setLoading((s) => ({ ...s, list: true }));
    try {
      const parsed = await fetchScenarioList();
      setLibrary(parsed);
      const current = selectedIdRef.current;
      const nextSelected = current && parsed.packages.some((item) => item.id === current)
        ? current
        : parsed.packages[0]?.id || null;
      selectScenario(nextSelected);
    } catch (err) {
      setLibrary({ error: err?.message || String(err), packages: [] });
      selectScenario(null);
      toast.error(t("scenarios.listFailed"));
    } finally {
      setLoading((s) => ({ ...s, list: false }));
    }
  }, [selectScenario, t]);

  const refreshStatus = React.useCallback(async (dir = targetDirRef.current) => {
    const requestedTarget = normalizeScenarioTarget(dir);
    if (!requestedTarget) {
      setStatus(null);
      return;
    }
    const request = {
      kind: "status",
      generation: ++requestGenerations.current.status,
      targetDir: requestedTarget,
    };
    setStatus(null);
    setLoading((s) => ({ ...s, status: true }));
    try {
      const parsed = await fetchScenarioStatus(requestedTarget);
      if (!requestIsCurrent(request)) return;
      const canonicalTarget = setScenarioTarget(
        parsed.canonicalTarget || requestedTarget,
        { preserveRequest: "status" },
      );
      if (requestGenerations.current.status !== request.generation) return;
      setStatus({ ...parsed, canonicalTarget });
    } catch (err) {
      if (!requestIsCurrent(request)) return;
      setStatus({
        error: err?.message || String(err),
        raw: err?.stdout || "",
        stderr: err?.stderr || "",
      });
      toast.error(t("scenarios.statusFailed"));
    } finally {
      if (requestGenerations.current.status === request.generation) {
        setLoading((s) => ({ ...s, status: false }));
      }
    }
  }, [setScenarioTarget, t]);

  React.useEffect(() => {
    if (!cliInfo.path) return;
    refreshLibrary();
  }, [cliInfo.path, refreshLibrary]);

  const pickDir = async () => {
    const picked = await open({ directory: true });
    if (picked) setScenarioTarget(picked);
  };

  const setPreviewForKind = (kind, value) => {
    if (kind === "deploy") setDeployPreview(value);
    else if (kind === "uninstall") setUninstallPreview(value);
    else setRecoverPreview(value);
  };

  const runScenarioPreview = async ({ kind, scenarioId = null, deploymentId = null }) => {
    const requestedTarget = targetDirRef.current;
    if (!requestedTarget || (kind === "deploy" && !scenarioId)) return;
    const request = {
      kind,
      generation: ++requestGenerations.current[kind],
      targetDir: requestedTarget,
      scenarioId,
      deploymentId,
    };
    setPreviewForKind(kind, null);
    setPending(null);
    setWriteResult(null);
    setLoading((state) => ({ ...state, [kind]: true }));
    try {
      let parsed;
      if (kind === "deploy") {
        parsed = await fetchScenarioDeployPreview(scenarioId, requestedTarget);
      } else if (kind === "uninstall") {
        parsed = await fetchScenarioUninstallPreview(deploymentId, requestedTarget);
      } else {
        parsed = await fetchScenarioRecoverPreview(requestedTarget);
      }
      if (!requestIsCurrent(request)) return;
      const canonicalTarget = setScenarioTarget(
        parsed.canonicalTarget || requestedTarget,
        { preserveRequest: kind },
      );
      if (requestGenerations.current[kind] !== request.generation) return;
      if (kind === "deploy" && selectedIdRef.current !== scenarioId) return;
      const snapshot = createScenarioPreviewSnapshot({
        kind,
        parsed,
        requestedTarget: canonicalTarget,
        scenarioId,
        deploymentId,
      });
      setPreviewForKind(kind, snapshot);
      if (!snapshot.gate?.ok) toast.error(t(previewReasonKey(snapshot.gate?.reason)));
    } catch (err) {
      if (!requestIsCurrent(request)) return;
      setPreviewForKind(kind, createScenarioPreviewSnapshot({
        kind,
        parsed: {
          gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
          raw: err?.stdout || err?.message || String(err),
          stderr: err?.stderr || "",
        },
        requestedTarget,
        scenarioId,
        deploymentId,
      }));
      toast.error(t("scenarios.previewFailed"));
    } finally {
      if (requestGenerations.current[kind] === request.generation) {
        setLoading((state) => ({ ...state, [kind]: false }));
      }
    }
  };

  const runDeployPreview = () => runScenarioPreview({
    kind: "deploy",
    scenarioId: selectedIdRef.current,
  });
  const runUninstallPreview = (deploymentId) => runScenarioPreview({
    kind: "uninstall",
    deploymentId,
  });
  const runRecoverPreview = () => runScenarioPreview({ kind: "recover" });

  const previewContext = { targetDir, selectedId };
  const deployPreviewValid = isScenarioPreviewCurrent(deployPreview, {
    kind: "deploy",
    ...previewContext,
  });
  const uninstallPreviewValid = isScenarioPreviewCurrent(uninstallPreview, {
    kind: "uninstall",
    ...previewContext,
  });
  const recoverPreviewValid = isScenarioPreviewCurrent(recoverPreview, {
    kind: "recover",
    ...previewContext,
  });

  const openConfirmation = (kind, preview) => {
    if (!isScenarioPreviewCurrent(preview, { kind, ...previewContext })) {
      toast.error(t("scenarios.previewStale"));
      return;
    }
    setPending({ kind, preview });
  };

  const runWrite = async (authorization) => {
    const kind = authorization?.kind;
    const preview = authorization?.preview;
    if (!isScenarioPreviewCurrent(preview, { kind, ...previewContext })) {
      setPending(null);
      toast.error(t("scenarios.previewStale"));
      return;
    }
    const parameters = getScenarioWriteParameters(preview);
    const operationLease = beginExclusiveOperation();
    if (!operationLease) {
      toast.warning(t("common.operationBusy"));
      return;
    }
    invalidateScenarioTargetState({
      requestGenerations,
      setStatus,
      setDeployPreview,
      setUninstallPreview,
      setRecoverPreview,
      setPending,
      setWriteResult,
      setLoading,
    });
    try {
      let output;
      if (parameters.kind === "deploy") {
        output = await executeScenarioDeploy(parameters.scenarioId, parameters.targetDir);
      } else if (parameters.kind === "uninstall") {
        output = await executeScenarioUninstall(parameters.deploymentId, parameters.targetDir);
      } else {
        output = await executeScenarioRecover(parameters.targetDir);
      }
      if (output.timed_out) {
        setWriteResult({
          kind: parameters.kind,
          targetDir: parameters.targetDir,
          ok: false,
          timedOut: true,
          exitCode: output.exit_code,
          message: t("scenarios.timedOut"),
          stdout: output.stdout,
          stderr: output.stderr,
        });
        toast.error(t("scenarios.timedOut"));
        return;
      }
      if (output.exit_code !== 0) {
        setWriteResult({
          kind: parameters.kind,
          targetDir: parameters.targetDir,
          ok: false,
          timedOut: false,
          exitCode: output.exit_code,
          message: null,
          stdout: output.stdout,
          stderr: output.stderr,
        });
        toast.error(t("scenarios.writeFailed"));
        return;
      }
      setWriteResult({
        kind: parameters.kind,
        targetDir: parameters.targetDir,
        ok: true,
        timedOut: false,
        exitCode: output.exit_code,
        message: null,
        stdout: output.stdout,
        stderr: output.stderr,
      });
      toast.success(t(`scenarios.${parameters.kind}Success`));
    } catch (err) {
      setWriteResult({
        kind: parameters.kind,
        targetDir: parameters.targetDir,
        ok: false,
        timedOut: Boolean(err?.timedOut),
        exitCode: err?.exitCode ?? null,
        message: err?.message || t("scenarios.writeFailed"),
        stdout: err?.stdout || "",
        stderr: err?.stderr || "",
      });
      toast.error(err?.message || t("scenarios.writeFailed"));
    } finally {
      try {
        await refreshStatus(parameters.targetDir);
      } finally {
        endOperation(operationLease);
        setPending(null);
      }
    }
  };

  const pendingValid = pending
    ? isScenarioPreviewCurrent(pending.preview, { kind: pending.kind, ...previewContext })
    : false;
  const pendingIdentity = pending?.kind === "deploy"
    ? pending.preview.scenarioId
    : pending?.kind === "uninstall"
      ? pending.preview.deploymentId
      : null;
  const pendingBody = pending
    ? [pendingIdentity, pending.preview.targetDir].filter(Boolean).join(" · ")
    : "";

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("scenarios.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("scenarios.subtitle")}</p>
      </FadeIn>

      {cliChecking && (
        <FadeIn delay={0.1}>
          <div className="card-glass mt-6 p-6 text-sm text-muted-foreground">
            <span className="spinner mr-1.5" aria-hidden="true" />
            {t("dash.loading")}
          </div>
        </FadeIn>
      )}

      {cliUnavailable && (
        <FadeIn delay={0.1}>
          <div className="card-glass mt-6 p-6 text-sm border-danger/40" role="alert">
            <div className="font-semibold text-danger">
              {t(cliInfo.error ? "dash.cliCheckFailed" : "dash.noCli")}
            </div>
            {cliInfo.error && <pre className="log-block mt-3">{cliInfo.error}</pre>}
            <Button className="mt-4" size="sm" onClick={() => setView("settings")}>
              {t("dash.noCliAction")}
            </Button>
          </div>
        </FadeIn>
      )}

      {!cliChecking && !cliUnavailable && (
        <>
          <FadeIn delay={0.05}>
            <section className="card-glass mt-6 p-6">
              <div className="text-sm font-medium">{t("scenarios.target")}</div>
              <p className="mt-1 text-xs text-muted-foreground">{t("scenarios.targetHint")}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md bg-elevated px-3 py-2 text-xs">
                  {targetDir || t("scenarios.noTarget")}
                </code>
                <Button size="sm" variant="secondary" onClick={pickDir} disabled={operationInProgress}>
                  <FolderOpen className="size-4" aria-hidden="true" />
                  {t("deploy.pickDir")}
                </Button>
                <Button
                  size="sm"
                  onClick={() => refreshStatus()}
                  disabled={!targetDir.trim() || operationInProgress || loading.status}
                >
                  {loading.status ? t("common.loading") : t("scenarios.refreshStatus")}
                </Button>
              </div>
            </section>
          </FadeIn>

          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <FadeIn delay={0.08}>
              <section className="card-glass p-5">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium">{t("scenarios.library")}</div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={refreshLibrary}
                    disabled={loading.list || operationInProgress}
                  >
                    {loading.list ? t("common.loading") : t("dash.refresh")}
                  </Button>
                </div>
                {library?.library && (
                  <p className="mt-1 truncate text-xs text-muted-foreground" title={library.library}>
                    {library.library}
                  </p>
                )}
                {library?.error && <pre className="log-block mt-3">{library.error}</pre>}
                <ul className="mt-3 space-y-1.5">
                  {(library?.packages || []).map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => selectScenario(item.id)}
                        disabled={operationInProgress || loading.deploy}
                        className={cn(
                          "flex w-full items-start justify-between gap-2 rounded-[10px] px-3 py-2 text-left text-sm",
                          "disabled:cursor-not-allowed disabled:opacity-50",
                          selectedId === item.id
                            ? "bg-accent-soft text-accent"
                            : "hover:bg-elevated",
                        )}
                      >
                        <span>
                          <span className="font-medium">{item.id}</span>
                          <span className="ml-1 text-xs text-muted-foreground">{item.version}</span>
                        </span>
                        <Badge variant={item.ready ? "green" : "red"}>
                          {item.ready ? t("scenarios.ready") : t("scenarios.blocked")}
                        </Badge>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            </FadeIn>

            <FadeIn delay={0.1}>
              <section className="card-glass p-5">
                {selected ? (
                  <>
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Boxes className="size-4 text-accent" aria-hidden="true" />
                      {selected.id}
                    </div>
                    <dl className="mt-3 grid gap-2 text-xs">
                      <div>{t("scenarios.platforms")}: {selected.platforms.join(", ") || t("common.none")}</div>
                      <div>Python: {selected.python}</div>
                      <div>{t("scenarios.requires")}: {selected.requires}</div>
                    </dl>
                    {selected.blockers.length > 0 && (
                      <div className="mt-3 rounded-md border border-danger/40 p-3 text-xs text-danger">
                        <div className="flex items-center gap-1 font-medium">
                          <ShieldAlert className="size-3.5" aria-hidden="true" />
                          {t("scenarios.packageBlockers")}
                        </div>
                        <ul className="mt-1 list-disc pl-4">
                          {selected.blockers.map((blocker) => (
                            <li key={blocker}>{blocker}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        onClick={runDeployPreview}
                        disabled={
                          !targetDir.trim()
                          || !selected.ready
                          || operationInProgress
                          || loading.deploy
                        }
                      >
                        {loading.deploy ? t("deploy.runningPreview") : t("scenarios.previewDeploy")}
                      </Button>
                    </div>
                    {deployPreview && (
                      <PreviewBlock
                        t={t}
                        title={t("scenarios.deployPreview")}
                        parsed={deployPreview}
                        confirmLabel={t("scenarios.confirmDeploy")}
                        confirmDisabled={!deployPreviewValid || operationInProgress}
                        onConfirm={() => openConfirmation("deploy", deployPreview)}
                      />
                    )}
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">{t("scenarios.pickPackage")}</p>
                )}
              </section>
            </FadeIn>
          </div>

          <FadeIn delay={0.12}>
            <section className="card-glass mt-6 p-5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium">{t("scenarios.targetStatus")}</div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={runRecoverPreview}
                  disabled={!targetDir.trim() || operationInProgress || loading.recover}
                >
                  <Undo2 className="size-4" aria-hidden="true" />
                  {loading.recover ? t("common.loading") : t("scenarios.previewRecover")}
                </Button>
              </div>
              {!targetDir.trim() && (
                <p className="mt-2 text-sm text-muted-foreground">{t("scenarios.needTarget")}</p>
              )}
              {status?.error && <pre className="log-block mt-3">{status.error}</pre>}
              {status?.state && (
                <div className="mt-3 text-sm">
                  <Badge variant={status.state === "active" ? "green" : "yellow"}>
                    {status.state}
                  </Badge>
                  {status.recovery && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {status.recovery.operation} / {status.recovery.transactionId} / {status.recovery.phase}
                    </p>
                  )}
                </div>
              )}
              {status && <ScenarioStatusDiagnostics status={status} t={t} />}
              {(status?.deployments || []).length > 0 && (
                <ul className="mt-3 space-y-2">
                  {status.deployments.map((item) => (
                    <li key={item.deploymentId} className="rounded-md border border-border p-3 text-xs">
                      <div className="font-medium">{item.scenarioId} · {item.state}</div>
                      <div className="mt-1 break-all text-muted-foreground">{item.deploymentId}</div>
                      {item.detail && <div className="mt-1">{item.detail}</div>}
                      <Button
                        className="mt-2"
                        size="sm"
                        variant="secondary"
                        onClick={() => runUninstallPreview(item.deploymentId)}
                        disabled={operationInProgress || loading.uninstall}
                      >
                        {t("scenarios.previewUninstall")}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {uninstallPreview && (
                <PreviewBlock
                  t={t}
                  title={t("scenarios.uninstallPreview")}
                  parsed={uninstallPreview}
                  confirmLabel={t("scenarios.confirmUninstall")}
                  confirmDisabled={!uninstallPreviewValid || operationInProgress}
                  danger
                  onConfirm={() => openConfirmation("uninstall", uninstallPreview)}
                />
              )}
              {recoverPreview && (
                <PreviewBlock
                  t={t}
                  title={t("scenarios.recoverPreview")}
                  parsed={recoverPreview}
                  confirmLabel={t("scenarios.confirmRecover")}
                  confirmDisabled={
                    !recoverPreviewValid
                    || !recoverPreview.required
                    || operationInProgress
                  }
                  danger
                  onConfirm={() => openConfirmation("recover", recoverPreview)}
                />
              )}
              {writeResult && <ScenarioWriteResult result={writeResult} t={t} />}
            </section>
          </FadeIn>
        </>
      )}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title={
          pending?.kind === "uninstall"
            ? t("scenarios.confirmUninstall")
            : pending?.kind === "recover"
              ? t("scenarios.confirmRecover")
              : t("scenarios.confirmDeploy")
        }
        body={pendingBody}
        confirmText={t("common.confirm")}
        confirmDisabled={operationInProgress || !pendingValid}
        danger={pending?.kind !== "deploy"}
        onConfirm={() => runWrite(pending)}
      />
    </div>
  );
}

function PreviewBlock({ t, title, parsed, confirmLabel, confirmDisabled, danger, onConfirm }) {
  const output = formatScenarioCommandOutput({ stdout: parsed.raw, stderr: parsed.stderr })
    || parsed.gate?.detail
    || "";
  return (
    <div className="mt-4 rounded-md border border-border p-3">
      <div className="text-xs font-medium">{title}</div>
      {!parsed.gate?.ok && (
        <p className="mt-2 text-xs text-danger">{parsed.gate?.detail || t("deploy.previewFailed")}</p>
      )}
      <Collapsible className="mt-2">
        <CollapsibleTrigger className="text-xs text-muted-foreground">
          {t("deploy.rawOutput")}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="log-block mt-2">{output}</pre>
        </CollapsibleContent>
      </Collapsible>
      <Button
        className="mt-3"
        size="sm"
        variant={danger ? "destructive" : "default"}
        disabled={confirmDisabled}
        onClick={onConfirm}
      >
        {confirmLabel}
      </Button>
    </div>
  );
}

export function ScenarioStatusDiagnostics({ status, t }) {
  const output = formatScenarioCommandOutput({ stdout: status.raw, stderr: status.stderr });
  if (!(status.blockers?.length > 0) && !output) return null;

  return (
    <div className="mt-3">
      {status.blockers?.length > 0 && (
        <div className="rounded-md border border-danger/40 bg-[var(--danger-soft)] p-3" role="alert">
          <div className="flex items-center gap-1 text-xs font-medium text-danger">
            <ShieldAlert className="size-3.5" aria-hidden="true" />
            {t("scenarios.statusBlockers")}
          </div>
          <ul className="mt-1 list-disc pl-4 text-xs text-danger">
            {status.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
          </ul>
        </div>
      )}
      {output && <ScenarioRawOutput output={output} t={t} />}
    </div>
  );
}

export function ScenarioWriteResult({ result, t }) {
  const output = formatScenarioCommandOutput(result);
  const heading = result.ok
    ? t(`scenarios.${result.kind}Success`)
    : result.timedOut
      ? t("scenarios.timedOut")
      : t("scenarios.writeFailed");
  return (
    <div
      className={cn(
        "mt-4 rounded-md border p-3",
        result.ok
          ? "border-[var(--ok)]/50 bg-[var(--ok-soft)]"
          : "border-danger/50 bg-[var(--danger-soft)]",
      )}
      role={result.ok ? "status" : "alert"}
    >
      <div className={cn("text-xs font-semibold", result.ok ? "text-ok" : "text-danger")}>
        {heading}
      </div>
      {result.message && result.message !== heading && (
        <p className="mt-1 text-xs text-secondary-foreground">{result.message}</p>
      )}
      {result.exitCode != null && (
        <p className="mt-1 text-xs text-muted-foreground">
          {t("dash.diagnosticExitCode")}: {result.exitCode}
        </p>
      )}
      {output && <ScenarioRawOutput output={output} t={t} />}
    </div>
  );
}

function ScenarioRawOutput({ output, t }) {
  return (
    <Collapsible className="mt-2">
      <CollapsibleTrigger className="cursor-pointer text-xs text-muted-foreground">
        {t("deploy.rawOutput")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="log-block mt-2">{output}</pre>
      </CollapsibleContent>
    </Collapsible>
  );
}

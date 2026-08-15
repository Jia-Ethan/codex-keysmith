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
  const [loading, setLoading] = React.useState({
    list: false,
    status: false,
    deploy: false,
    uninstall: false,
    recover: false,
  });

  const cliChecking = !cliInfo.checked;
  const cliUnavailable = cliInfo.checked && !cliInfo.path;
  const selected = library?.packages.find((item) => item.id === selectedId) || null;

  const rememberCanonical = (canonical) => {
    if (canonical && canonical !== targetDir) setTargetDir(canonical);
    return canonical || targetDir;
  };

  const refreshLibrary = React.useCallback(async () => {
    setLoading((s) => ({ ...s, list: true }));
    try {
      const parsed = await fetchScenarioList();
      setLibrary(parsed);
      setSelectedId((current) => {
        if (current && parsed.packages.some((item) => item.id === current)) return current;
        return parsed.packages[0]?.id || null;
      });
    } catch (err) {
      setLibrary({ error: err?.message || String(err), packages: [] });
      toast.error(t("scenarios.listFailed"));
    } finally {
      setLoading((s) => ({ ...s, list: false }));
    }
  }, [t]);

  const refreshStatus = React.useCallback(async (dir = targetDir) => {
    if (!dir.trim()) {
      setStatus(null);
      return;
    }
    setLoading((s) => ({ ...s, status: true }));
    try {
      const parsed = await fetchScenarioStatus(dir);
      rememberCanonical(parsed.canonicalTarget);
      setStatus(parsed);
    } catch (err) {
      setStatus({ error: err?.message || String(err) });
      toast.error(t("scenarios.statusFailed"));
    } finally {
      setLoading((s) => ({ ...s, status: false }));
    }
  }, [t, targetDir]);

  React.useEffect(() => {
    if (!cliInfo.path) return;
    refreshLibrary();
  }, [cliInfo.path, refreshLibrary]);

  React.useEffect(() => {
    setDeployPreview(null);
    setUninstallPreview(null);
    setRecoverPreview(null);
  }, [targetDir, selectedId]);

  const pickDir = async () => {
    const picked = await open({ directory: true });
    if (picked) setTargetDir(picked);
  };

  const runDeployPreview = async () => {
    if (!selected || !targetDir.trim()) return;
    setLoading((s) => ({ ...s, deploy: true }));
    try {
      const parsed = await fetchScenarioDeployPreview(selected.id, targetDir);
      rememberCanonical(parsed.canonicalTarget);
      setDeployPreview(parsed);
      if (!parsed.gate.ok) toast.error(t(previewReasonKey(parsed.gate.reason)));
    } catch (err) {
      setDeployPreview({
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        raw: err?.message || String(err),
      });
      toast.error(t("scenarios.previewFailed"));
    } finally {
      setLoading((s) => ({ ...s, deploy: false }));
    }
  };

  const runUninstallPreview = async (deploymentId) => {
    setLoading((s) => ({ ...s, uninstall: true }));
    try {
      const parsed = await fetchScenarioUninstallPreview(deploymentId, targetDir);
      rememberCanonical(parsed.canonicalTarget);
      setUninstallPreview(parsed);
      if (!parsed.gate.ok) toast.error(t(previewReasonKey(parsed.gate.reason)));
    } catch (err) {
      setUninstallPreview({
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        raw: err?.message || String(err),
      });
      toast.error(t("scenarios.previewFailed"));
    } finally {
      setLoading((s) => ({ ...s, uninstall: false }));
    }
  };

  const runRecoverPreview = async () => {
    setLoading((s) => ({ ...s, recover: true }));
    try {
      const parsed = await fetchScenarioRecoverPreview(targetDir);
      rememberCanonical(parsed.canonicalTarget);
      setRecoverPreview(parsed);
      if (!parsed.gate.ok) toast.error(t(previewReasonKey(parsed.gate.reason)));
    } catch (err) {
      setRecoverPreview({
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        raw: err?.message || String(err),
      });
      toast.error(t("scenarios.previewFailed"));
    } finally {
      setLoading((s) => ({ ...s, recover: false }));
    }
  };

  const runWrite = async (kind) => {
    const operationLease = beginExclusiveOperation();
    if (!operationLease) {
      toast.warning(t("common.operationBusy"));
      return;
    }
    try {
      let output;
      if (kind === "deploy") {
        output = await executeScenarioDeploy(selected.id, targetDir);
      } else if (kind === "uninstall") {
        output = await executeScenarioUninstall(uninstallPreview.deploymentId, targetDir);
      } else {
        output = await executeScenarioRecover(targetDir);
      }
      if (output.timed_out) {
        toast.error(t("deploy.timedOut"));
        return;
      }
      if (output.exit_code !== 0) {
        toast.error(t("scenarios.writeFailed"));
        return;
      }
      toast.success(t(`scenarios.${kind}Success`));
      setDeployPreview(null);
      setUninstallPreview(null);
      setRecoverPreview(null);
      await refreshStatus(targetDir);
    } catch (err) {
      toast.error(err?.message || t("scenarios.writeFailed"));
    } finally {
      endOperation(operationLease);
      setPending(null);
    }
  };

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
                  <Button size="sm" variant="ghost" onClick={refreshLibrary} disabled={loading.list}>
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
                        onClick={() => setSelectedId(item.id)}
                        className={cn(
                          "flex w-full items-start justify-between gap-2 rounded-[10px] px-3 py-2 text-left text-sm",
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
                        confirmDisabled={!deployPreview.gate?.ok || operationInProgress}
                        onConfirm={() => setPending("deploy")}
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
                  confirmDisabled={!uninstallPreview.gate?.ok || operationInProgress}
                  danger
                  onConfirm={() => setPending("uninstall")}
                />
              )}
              {recoverPreview && (
                <PreviewBlock
                  t={t}
                  title={t("scenarios.recoverPreview")}
                  parsed={recoverPreview}
                  confirmLabel={t("scenarios.confirmRecover")}
                  confirmDisabled={!recoverPreview.gate?.ok || !recoverPreview.required || operationInProgress}
                  danger
                  onConfirm={() => setPending("recover")}
                />
              )}
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
          pending === "uninstall"
            ? t("scenarios.confirmUninstall")
            : pending === "recover"
              ? t("scenarios.confirmRecover")
              : t("scenarios.confirmDeploy")
        }
        body={targetDir}
        confirmText={t("common.confirm")}
        confirmDisabled={operationInProgress}
        danger={pending !== "deploy"}
        onConfirm={() => runWrite(pending)}
      />
    </div>
  );
}

function PreviewBlock({ t, title, parsed, confirmLabel, confirmDisabled, danger, onConfirm }) {
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
          <pre className="log-block mt-2">{parsed.raw || parsed.gate?.detail}</pre>
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

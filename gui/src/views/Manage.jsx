import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Undo2, Anchor, Zap } from "lucide-react";
import { cliRun, cliExecute, fetchStatus } from "@/lib/api";
import {
  executeRestoreHooksPlans,
  isManagementPreviewValid,
  prepareManagementPreview,
  shouldRefreshManagementStatus,
} from "@/lib/manage";
import { useAppState } from "@/hooks/useAppState";
import { getSettings } from "@/lib/settings";
import { beginOperation, endOperation, setLastStatus, setView } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/FadeIn";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const ALL_DIRS = "__all__";

export function Manage() {
  const { t } = useTranslation();
  const { cliInfo, lastStatus, operationInProgress } = useAppState();
  const [status, setStatus] = React.useState(lastStatus);
  const [statusLoading, setStatusLoading] = React.useState(!lastStatus);
  const [statusError, setStatusError] = React.useState(null);
  const [statusRevision, setStatusRevision] = React.useState(0);

  const loadStatus = React.useCallback(async () => {
    setStatusLoading(true);
    setStatusError(null);
    try {
      const nextStatus = await fetchStatus();
      setStatus(nextStatus);
      setLastStatus(nextStatus);
      return nextStatus;
    } catch (error) {
      setStatus(null);
      setLastStatus(null);
      setStatusError(error?.message || String(error));
      throw error;
    } finally {
      setStatusLoading(false);
    }
  }, []);

  const refreshStatus = React.useCallback(async () => {
    // Any write attempt invalidates every card's preview before status is re-read.
    setStatusRevision((revision) => revision + 1);
    setStatus(null);
    setLastStatus(null);
    try {
      return await loadStatus();
    } catch {
      return null;
    }
  }, [loadStatus]);

  const beginManagementOperation = React.useCallback((operation) => {
    if (!beginOperation(operation)) return false;
    setStatusRevision((revision) => revision + 1);
    return true;
  }, []);

  React.useEffect(() => {
    if (status || !cliInfo.path) return;
    loadStatus().catch(() => {});
  }, [cliInfo.path]); // eslint-disable-line react-hooks/exhaustive-deps

  const cliChecking = !cliInfo.checked;
  const cliUnavailable = cliInfo.checked && !cliInfo.path;
  const dirs = status?.directories ?? [];
  const hasResidue = dirs.some((d) => d.residue.length > 0);
  const actionsReady = Boolean(status) && !statusLoading && !statusError;

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("manage.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("manage.subtitle")}</p>
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
          <div
            className={cn("card-glass mt-6 p-6 text-sm", cliInfo.error && "border-danger/40")}
            role={cliInfo.error ? "alert" : undefined}
          >
            <div className={cliInfo.error ? "font-semibold text-danger" : "text-secondary-foreground"}>
              {t(cliInfo.error ? "dash.cliCheckFailed" : "dash.noCli")}
            </div>
            {cliInfo.error && <pre className="log-block mt-3">{cliInfo.error}</pre>}
            <Button className="mt-4" size="sm" onClick={() => setView("settings")}>
              {t("dash.noCliAction")}
            </Button>
          </div>
        </FadeIn>
      )}

      {cliInfo.checked && cliInfo.path && (
        <div className="mt-6 flex flex-col gap-4">
          {statusError && (
            <FadeIn delay={0.08}>
              <div className="card-glass border-danger/40 p-5" role="alert">
                <div className="text-sm font-semibold text-danger">{t("dash.error")}</div>
                <pre className="log-block mt-3">{statusError}</pre>
                <Button
                  className="mt-4"
                  size="sm"
                  variant="outline"
                  onClick={refreshStatus}
                  disabled={statusLoading}
                >
                  {statusLoading ? <span className="spinner" aria-hidden="true" /> : null}
                  {t("dash.refresh")}
                </Button>
              </div>
            </FadeIn>
          )}
          <ActionCard
            opKey="uninstall"
            t={t}
            title={t("manage.uninstall")}
            desc={t("manage.uninstallDesc")}
            icon={<Undo2 className="size-[18px]" aria-hidden="true" />}
            cliArgs={["--uninstall"]}
            dirs={dirs}
            statusRevision={statusRevision}
            onStatusRefresh={refreshStatus}
            operationLocked={operationInProgress}
            onOperationStart={beginManagementOperation}
            onOperationEnd={endOperation}
            enabled={actionsReady}
            danger
            delay={0.1}
          />
          <ActionCard
            opKey="restore-hooks"
            t={t}
            title={t("manage.restoreHooks")}
            desc={t("manage.restoreHooksDesc")}
            icon={<Anchor className="size-[18px]" aria-hidden="true" />}
            cliArgs={["--restore-hooks"]}
            dirs={dirs}
            statusRevision={statusRevision}
            onStatusRefresh={refreshStatus}
            operationLocked={operationInProgress}
            onOperationStart={beginManagementOperation}
            onOperationEnd={endOperation}
            enabled={actionsReady}
            noYes // CLI 约束：--restore-hooks 与 --yes 互斥
            delay={0.18}
          />
          <ActionCard
            opKey="recover"
            t={t}
            title={t("manage.recover")}
            desc={t("manage.recoverDesc")}
            icon={<Zap className="size-[18px]" aria-hidden="true" />}
            cliArgs={["--recover"]}
            dirs={dirs}
            statusRevision={statusRevision}
            onStatusRefresh={refreshStatus}
            operationLocked={operationInProgress}
            onOperationStart={beginManagementOperation}
            onOperationEnd={endOperation}
            danger
            recoverPreview // --recover 不带 --yes 即预览
            enabled={actionsReady && hasResidue}
            highlight={hasResidue}
            extraBadge={hasResidue ? t("manage.recoverAvailable") : null}
            delay={0.26}
          />
        </div>
      )}
    </div>
  );
}

/**
 * 管理操作卡片（问题 3 修复：强制预览门禁）
 * 流程：选目录 → 预览（gate 校验通过才解锁执行）→ 确认 → 执行。
 * 预览绑定当时的目录选择；之后改动目录则预览作废（previewStale）。
 */
function ActionCard({ opKey, t, title, desc, icon, cliArgs, dirs, statusRevision, onStatusRefresh, operationLocked, onOperationStart, onOperationEnd, danger, noYes, recoverPreview, enabled = true, highlight, extraBadge, delay }) {
  const [dirSel, setDirSel] = React.useState(ALL_DIRS);
  const [preview, setPreview] = React.useState(null); // { dirKey, gate, parsed, output }
  const [previewing, setPreviewing] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const dirKey = dirSel === ALL_DIRS ? "" : dirSel;

  const buildArgs = (dir) => {
    const args = [...cliArgs];
    const d = dir ?? (dirKey || getSettings().defaultCodexDir || "");
    if (d) args.push("--codex-dir", d);
    return args;
  };

  // 预览有效的条件：当前目录选择与预览时的目录一致，且门禁通过
  const previewValid = isManagementPreviewValid(
    preview,
    dirKey || getSettings().defaultCodexDir || "",
    statusRevision,
  );

  const runPreview = async () => {
    setPreviewing(true);
    setResult(null);
    const effectiveDir = dirKey || getSettings().defaultCodexDir || "";
    try {
      const prepared = await prepareManagementPreview({
        operation: opKey,
        directories: dirs,
        // Restore plans use canonical paths returned by status. The default
        // setting may be an equivalent non-canonical path such as ~/.codex.
        targetDir: opKey === "restore-hooks" ? dirKey : effectiveDir,
        args: [...buildArgs(effectiveDir), "--lang", "en"],
        runCli: cliRun,
      });
      setPreview({ dirKey: effectiveDir, statusRevision, ...prepared });
      if (!prepared.gate.ok) {
        toast.error(t(
          prepared.gate.reason === "no-restorable"
            ? "manage.noRestorableTargets"
            : "deploy.previewFailed",
        ));
      }
    } catch (err) {
      setPreview({
        dirKey: effectiveDir,
        statusRevision,
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        parsed: null,
        output: null,
      });
    } finally {
      setPreviewing(false);
    }
  };

  const execute = async () => {
    if (!previewValid) {
      setConfirming(false);
      toast.error(t("manage.previewStale"));
      return;
    }
    const operationOwner = `manage:${opKey}`;
    if (!onOperationStart(operationOwner)) {
      setConfirming(false);
      toast.error(t("manage.operationInProgress"));
      return;
    }
    setRunning(true);
    setResult(null);
    let output = null;
    let attemptStarted = false;
    try {
      const args = buildArgs();
      // restore-hooks 仅在确认后按预览目标执行；其余操作追加 --yes。
      attemptStarted = true;
      output = noYes
        ? await executeRestoreHooksPlans(preview.parsed.plans, cliRun)
        : await cliExecute(args);
      const outputText = noYes
        ? output.text
        : [output.stdout, output.stderr].filter((value) => value?.trim()).join("\n");
      if (output.timed_out) {
        setResult({
          ok: false,
          partial: output.partial,
          text: outputText || t("deploy.timedOut"),
        });
        toast.error(t(output.partial ? "manage.partial" : "manage.failed"));
      } else if (output.exit_code === 0) {
        setResult({ ok: true, text: outputText });
        toast.success(t("manage.done"));
      } else {
        setResult({
          ok: false,
          partial: output.partial,
          code: output.exit_code,
          text: outputText,
        });
        toast.error(t(output.partial ? "manage.partial" : "manage.failed"));
      }
    } catch (err) {
      setResult({ ok: false, text: err?.message || String(err) });
      toast.error(t("manage.failed"));
    } finally {
      if (shouldRefreshManagementStatus(opKey, output, attemptStarted)) {
        setPreview(null);
        await onStatusRefresh();
      }
      setRunning(false);
      onOperationEnd(operationOwner);
    }
  };

  return (
    <FadeIn delay={delay}>
      <section
        className={cn("card-glass p-5", highlight && "border-warn/50")}
        aria-label={title}
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 text-accent">{icon}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold">{title}</h2>
              {extraBadge && <Badge variant="yellow">{extraBadge}</Badge>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
          </div>
        </div>

        {dirs.length > 1 && (
          <div className="mt-3.5 flex items-center gap-2.5">
            <label htmlFor={`dir-${opKey}`} className="text-xs text-muted-foreground whitespace-nowrap">
              {t("manage.selectDir")}
            </label>
            <Select value={dirSel} onValueChange={setDirSel}>
              <SelectTrigger id={`dir-${opKey}`} className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_DIRS}>{t("manage.allDirs")}</SelectItem>
                {dirs.map((d) => (
                  <SelectItem key={d.path} value={d.path}>
                    <span className="font-mono text-xs">{d.path}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="mt-4 flex items-center gap-2.5">
          <Button size="sm" variant="outline" onClick={runPreview} disabled={!enabled || operationLocked || previewing || running}>
            {previewing ? <span className="spinner" aria-hidden="true" /> : null}
            {t("manage.preview")}
          </Button>
          <Button
            size="sm"
            variant={danger ? "destructive" : "default"}
            disabled={!enabled || operationLocked || !previewValid || running}
            title={!previewValid ? t("manage.previewRequired") : undefined}
            onClick={() => setConfirming(true)}
          >
            {running ? <span className="spinner" aria-hidden="true" /> : null}
            {running ? t("manage.running") : t("manage.execute")}
          </Button>
          {!previewValid && enabled && !running && (
            <span className="text-xs text-muted-foreground">
              {preview && (
                preview.dirKey !== (dirKey || getSettings().defaultCodexDir || "")
                || preview.statusRevision !== statusRevision
              )
                ? t("manage.previewStale")
                : t("manage.previewRequired")}
            </span>
          )}
        </div>

        {/* 预览结果 */}
        {preview && (
          <div className="mt-4">
            {!preview.gate.ok && (
              <div className="rounded-[10px] border border-danger/50 bg-[var(--danger-soft)] p-3.5" role="alert">
                <div className="text-xs font-semibold text-danger">{t("deploy.previewFailed")}</div>
                {(preview.gate.detail || preview.gate.reason === "no-restorable") && (
                  <pre className="log-block mt-2">
                    {preview.gate.detail || t("manage.noRestorableTargets")}
                  </pre>
                )}
              </div>
            )}
            {preview.gate.ok && preview.parsed?.plans.length > 0 && (
              <div className="rounded-[10px] border border-border bg-muted p-3.5">
                <div className="text-xs font-semibold">{t("manage.previewPlan")}</div>
                <div className="mt-2 space-y-2">
                  {preview.parsed.plans.map((p) => (
                    <div key={p.dir} className="text-xs">
                      <div className="break-all font-mono font-semibold">{p.dir}</div>
                      <div className="text-secondary-foreground">
                        {p.kind === "restore-hooks" ? t("manage.restoreHooksPlan") : p.summary}
                      </div>
                      {p.detail && <div className="text-muted-foreground">{p.detail}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {preview.output && (
              <Collapsible className="mt-2.5">
                <CollapsibleTrigger className="cursor-pointer text-xs font-medium text-accent hover:text-accent-hover">
                  {t("deploy.rawOutput")}
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="log-block mt-2">
                    {preview.output.stdout}
                    {preview.output.stderr ? `\n${preview.output.stderr}` : ""}
                  </pre>
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        )}

        {/* 执行结果 */}
        {result && (
          <div
            className={cn(
              "mt-4 rounded-[10px] border p-3.5",
              result.ok ? "border-[var(--ok)]/50 bg-[var(--ok-soft)]" : "border-danger/50 bg-[var(--danger-soft)]",
            )}
            role={result.ok ? "status" : "alert"}
          >
            <div className={cn("text-xs font-semibold", result.ok ? "text-ok" : "text-danger")}>
              {result.ok
                ? `✓ ${t("manage.done")}`
                : `${t(result.partial ? "manage.partial" : "manage.failed")}${result.code ? ` (exit ${result.code})` : ""}`}
            </div>
            {result.text && (
              <Collapsible className="mt-2">
                <CollapsibleTrigger className="cursor-pointer text-xs font-medium text-accent hover:text-accent-hover">
                  {t("manage.result")}
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="log-block mt-2">{result.text}</pre>
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        )}
      </section>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={title}
        body={dirKey || t("manage.allDirs")}
        confirmText={t("manage.execute")}
        danger={danger}
        confirmDisabled={operationLocked}
        onConfirm={execute}
      />
    </FadeIn>
  );
}

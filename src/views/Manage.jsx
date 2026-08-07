import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Undo2, Anchor, Zap } from "lucide-react";
import { cliRun, cliExecute, fetchStatus } from "@/lib/api";
import { parseUninstallPreview, gatePreview } from "@/lib/parser";
import { useAppState } from "@/hooks/useAppState";
import { getSettings } from "@/lib/settings";
import { setLastStatus, setOperationInProgress } from "@/lib/store";
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
  const { cliInfo, lastStatus } = useAppState();
  const [status, setStatus] = React.useState(lastStatus);

  React.useEffect(() => {
    if (status || !cliInfo.path) return;
    fetchStatus()
      .then((s) => {
        setStatus(s);
        setLastStatus(s);
      })
      .catch(() => {});
  }, [cliInfo.path]); // eslint-disable-line react-hooks/exhaustive-deps

  const noCli = cliInfo.checked && !cliInfo.path;
  const dirs = status?.directories ?? [];
  const hasResidue = dirs.some((d) => d.residue.length > 0);

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("manage.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("manage.subtitle")}</p>
      </FadeIn>

      {noCli && (
        <FadeIn delay={0.1}>
          <div className="card-glass mt-6 p-6 text-sm text-secondary-foreground">{t("dash.noCli")}</div>
        </FadeIn>
      )}

      {!noCli && (
        <div className="mt-6 flex flex-col gap-4">
          <ActionCard
            opKey="uninstall"
            t={t}
            title={t("manage.uninstall")}
            desc={t("manage.uninstallDesc")}
            icon={<Undo2 className="size-[18px]" aria-hidden="true" />}
            cliArgs={["--uninstall"]}
            dirs={dirs}
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
            danger
            recoverPreview // --recover 不带 --yes 即预览
            enabled={hasResidue}
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
function ActionCard({ opKey, t, title, desc, icon, cliArgs, dirs, danger, noYes, recoverPreview, enabled = true, highlight, extraBadge, delay }) {
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
  const previewValid =
    preview && preview.dirKey === (dirKey || getSettings().defaultCodexDir || "") && preview.gate.ok;

  const runPreview = async () => {
    setPreviewing(true);
    setResult(null);
    try {
      const effectiveDir = dirKey || getSettings().defaultCodexDir || "";
      // recoverPreview：--recover 不带 --yes 就是预览；其余操作默认即预览
      const output = await cliRun([...buildArgs(effectiveDir), "--lang", "en"]);
      const parsed = parseUninstallPreview(output.stdout);
      const gate = gatePreview(output, parsed);
      setPreview({ dirKey: effectiveDir, gate, parsed, output });
      if (!gate.ok) toast.error(t("deploy.previewFailed"));
    } catch (err) {
      setPreview({
        dirKey: dirKey || "",
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        parsed: null,
        output: null,
      });
    } finally {
      setPreviewing(false);
    }
  };

  const execute = async () => {
    setRunning(true);
    setOperationInProgress(true);
    setResult(null);
    try {
      const args = buildArgs();
      // --restore-hooks 与 --yes 互斥（noYes）；其余（含 --recover）追加 --yes
      const output = noYes
        ? await cliRun([...args, "--lang", "en"], 120_000)
        : await cliExecute(args);
      if (output.timed_out) {
        setResult({ ok: false, text: t("deploy.timedOut") });
        toast.error(t("manage.failed"));
      } else if (output.exit_code === 0) {
        setResult({ ok: true, text: output.stdout });
        toast.success(t("manage.done"));
        setLastStatus(null); // 失效快照，回 Dashboard 自动刷新
        setPreview(null); // 执行后旧预览作废
      } else {
        setResult({ ok: false, code: output.exit_code, text: output.stderr || output.stdout });
        toast.error(t("manage.failed"));
      }
    } catch (err) {
      setResult({ ok: false, text: err?.message || String(err) });
      toast.error(t("manage.failed"));
    } finally {
      setRunning(false);
      setOperationInProgress(false);
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
          <Button size="sm" variant="outline" onClick={runPreview} disabled={!enabled || previewing || running}>
            {previewing ? <span className="spinner" aria-hidden="true" /> : null}
            {t("manage.preview")}
          </Button>
          <Button
            size="sm"
            variant={danger ? "destructive" : "default"}
            disabled={!enabled || !previewValid || running}
            title={!previewValid ? t("manage.previewRequired") : undefined}
            onClick={() => setConfirming(true)}
          >
            {running ? <span className="spinner" aria-hidden="true" /> : null}
            {running ? t("manage.running") : t("manage.execute")}
          </Button>
          {!previewValid && enabled && !running && (
            <span className="text-xs text-muted-foreground">
              {preview && preview.dirKey !== (dirKey || getSettings().defaultCodexDir || "")
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
                {preview.gate.detail && <pre className="log-block mt-2">{preview.gate.detail}</pre>}
              </div>
            )}
            {preview.gate.ok && preview.parsed?.plans.length > 0 && (
              <div className="rounded-[10px] border border-border bg-muted p-3.5">
                <div className="text-xs font-semibold">{t("manage.previewPlan")}</div>
                <div className="mt-2 space-y-2">
                  {preview.parsed.plans.map((p) => (
                    <div key={p.dir} className="text-xs">
                      <div className="break-all font-mono font-semibold">{p.dir}</div>
                      <div className="text-secondary-foreground">{p.summary}</div>
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
              {result.ok ? `✓ ${t("manage.done")}` : `${t("manage.failed")}${result.code ? ` (exit ${result.code})` : ""}`}
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
        onConfirm={execute}
      />
    </FadeIn>
  );
}

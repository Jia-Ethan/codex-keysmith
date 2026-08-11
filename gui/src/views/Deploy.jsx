import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { FileText, Package, ShieldAlert, CheckCircle2 } from "lucide-react";
import { fetchDryRun, cliExecute } from "@/lib/api";
import { useAppState } from "@/hooks/useAppState";
import { setOperationInProgress, setView, setLastStatus } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/FadeIn";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export function Deploy() {
  const { t } = useTranslation();
  const { cliInfo } = useAppState();
  const [step, setStep] = React.useState(1);
  const [source, setSource] = React.useState("bundled");
  const [filePath, setFilePath] = React.useState("");
  const [name, setName] = React.useState("");
  const [codexDir, setCodexDir] = React.useState("");
  const [skipHooks, setSkipHooks] = React.useState(false);
  const [preview, setPreview] = React.useState(null);
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [deploying, setDeploying] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const cliChecking = !cliInfo.checked;
  const cliUnavailable = cliInfo.checked && !cliInfo.path;

  const buildArgs = () => {
    const args = [];
    if (source === "file" && filePath) args.push("--file", filePath);
    if (name.trim()) args.push("--name", name.trim());
    if (codexDir.trim()) args.push("--codex-dir", codexDir.trim());
    if (skipHooks) args.push("--skip-hooks-isolation");
    return args;
  };

  const canNext = (source === "bundled" || !!filePath) && (!skipHooks || !!codexDir.trim());

  const runPreview = async () => {
    setStep(2);
    setPreview(null);
    setPreviewLoading(true);
    try {
      setPreview(await fetchDryRun(buildArgs()));
    } catch (err) {
      setPreview({ gate: { ok: false, reason: "exit" }, error: err?.message || String(err) });
    } finally {
      setPreviewLoading(false);
    }
  };

  const doDeploy = async () => {
    setDeploying(true);
    setOperationInProgress(true);
    setResult(null);
    try {
      const output = await cliExecute(buildArgs());
      if (output.timed_out) {
        setResult({ ok: false, kind: "timeout", text: t("deploy.timedOut") });
        toast.error(t("deploy.failed"));
      } else if (output.exit_code === 0) {
        setResult({ ok: true, text: output.stdout });
        toast.success(t("deploy.success"));
        setLastStatus(null);
        setTimeout(() => {
          setOperationInProgress(false);
          setView("dashboard");
        }, 1200);
        return;
      } else {
        setResult({
          ok: false,
          kind: "exit",
          code: output.exit_code,
          text: output.stderr || output.stdout,
        });
        toast.error(t("deploy.failed"));
      }
    } catch (err) {
      setResult({ ok: false, kind: "error", text: err?.message || String(err) });
      toast.error(t("deploy.failed"));
    } finally {
      setDeploying(false);
      setOperationInProgress(false);
    }
  };

  const steps = [t("deploy.step1"), t("deploy.step2"), t("deploy.step3")];

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("deploy.title")}</h1>
      </FadeIn>

      {/* 步骤指示器 */}
      <FadeIn delay={0.05}>
        <ol className="mt-4 flex items-center gap-2" aria-label={t("deploy.title")}>
          {steps.map((s, i) => {
            const n = i + 1;
            const current = step === n;
            const done = step > n;
            return (
              <React.Fragment key={s}>
                <li
                  aria-current={current ? "step" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 text-xs",
                    current ? "font-semibold text-accent" : done ? "text-ok" : "text-muted-foreground",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-5 items-center justify-center rounded-full border text-[10px]",
                      current
                        ? "border-accent bg-accent-soft"
                        : done
                          ? "border-[var(--ok)] bg-[var(--ok-soft)]"
                          : "border-border",
                    )}
                  >
                    {done ? "✓" : n}
                  </span>
                  {s}
                </li>
                {i < steps.length - 1 && <li className="h-px w-8 bg-border" aria-hidden="true" />}
              </React.Fragment>
            );
          })}
        </ol>
      </FadeIn>

      <div className="mt-6">
        {cliChecking ? (
          <FadeIn delay={0.1}>
            <div className="card-glass p-6 text-sm text-muted-foreground">
              <span className="spinner mr-1.5" aria-hidden="true" />
              {t("dash.loading")}
            </div>
          </FadeIn>
        ) : cliUnavailable ? (
          <FadeIn delay={0.1}>
            <div
              className={cn("card-glass p-6 text-sm", cliInfo.error && "border-danger/40")}
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
        ) : (
          <>
            {step === 1 && (
              <Step1
                t={t}
                source={source}
                setSource={setSource}
                filePath={filePath}
                setFilePath={setFilePath}
                name={name}
                setName={setName}
                codexDir={codexDir}
                setCodexDir={setCodexDir}
                skipHooks={skipHooks}
                setSkipHooks={setSkipHooks}
                canNext={canNext}
                onNext={runPreview}
              />
            )}
            {step === 2 && (
              <Step2
                t={t}
                preview={preview}
                loading={previewLoading}
                onBack={() => {
                  setStep(1);
                  setPreview(null);
                }}
                onNext={() => setStep(3)}
              />
            )}
            {step === 3 && (
              <Step3
                t={t}
                deploying={deploying}
                result={result}
                codexDir={codexDir}
                onBack={() => setStep(2)}
                onConfirm={() => setConfirming(true)}
              />
            )}
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("deploy.confirmDeploy")}
        body={codexDir || t("manage.allDirs")}
        confirmText={t("deploy.confirmDeploy")}
        danger
        onConfirm={doDeploy}
      />
    </div>
  );
}

// ── 步骤 1：选择内容 ─────────────────────────

function Step1({ t, source, setSource, filePath, setFilePath, name, setName, codexDir, setCodexDir, skipHooks, setSkipHooks, canNext, onNext }) {
  const pickFile = async () => {
    const picked = await open({
      filters: [{ name: "Markdown", extensions: ["md", "markdown", "txt"] }],
    });
    if (picked) {
      setFilePath(picked);
      setSource("file");
    }
  };
  const pickDir = async () => {
    const picked = await open({ directory: true });
    if (picked) setCodexDir(picked);
  };

  return (
    <FadeIn delay={0.1}>
      <div className="card-glass p-6">
        <fieldset>
          <legend className="text-sm font-medium">{t("deploy.source")}</legend>
          <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
            <SourceCard
              icon={<Package className="size-4" aria-hidden="true" />}
              title={t("deploy.sourceBundled")}
              desc={t("deploy.sourceBundledDesc")}
              selected={source === "bundled"}
              onSelect={() => setSource("bundled")}
            />
            <SourceCard
              icon={<FileText className="size-4" aria-hidden="true" />}
              title={t("deploy.sourceFile")}
              selected={source === "file"}
              onSelect={() => setSource("file")}
            >
              <div className="mt-1.5 flex items-center gap-2">
                <span className={cn("min-w-0 flex-1 truncate font-mono text-[11px]", !filePath && "text-muted-foreground")}>
                  {filePath || t("deploy.noFile")}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    pickFile();
                  }}
                >
                  {t("deploy.pickFile")}
                </Button>
              </div>
            </SourceCard>
          </div>
        </fieldset>

        <div className="mt-5">
          <label htmlFor="deploy-name" className="text-sm font-medium">{t("deploy.name")}</label>
          <Input
            id="deploy-name"
            className="mt-1.5 font-mono"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("deploy.namePlaceholder")}
          />
          <p className="mt-1 text-xs text-muted-foreground">{t("deploy.nameHint")}</p>
        </div>

        <div className="mt-5">
          <label htmlFor="deploy-dir" className="text-sm font-medium">{t("deploy.targetDir")}</label>
          <div className="mt-1.5 flex gap-2">
            <Input
              id="deploy-dir"
              className="flex-1 font-mono"
              value={codexDir}
              onChange={(e) => setCodexDir(e.target.value)}
              placeholder={t("deploy.targetDirPlaceholder")}
            />
            <Button variant="outline" onClick={pickDir}>{t("deploy.pickDir")}</Button>
          </div>
        </div>

        <Collapsible className="mt-5">
          <CollapsibleTrigger className="cursor-pointer text-sm font-medium text-accent hover:text-accent-hover">
            {t("deploy.advanced")}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-2.5 flex items-center gap-2.5">
              <Switch id="skip-hooks" checked={skipHooks} onCheckedChange={setSkipHooks} />
              <label htmlFor="skip-hooks" className="text-sm cursor-pointer">{t("deploy.skipHooks")}</label>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("deploy.skipHooksHint")}</p>
          </CollapsibleContent>
        </Collapsible>

        <div className="mt-6 flex justify-end">
          <Button onClick={onNext} disabled={!canNext}>
            {t("deploy.next")} →
          </Button>
        </div>
      </div>
    </FadeIn>
  );
}

function SourceCard({ icon, title, desc, selected, onSelect, children }) {
  return (
    <div
      role="radio"
      aria-checked={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === " " || e.key === "Enter")) {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "rounded-[12px] border p-3.5 text-left transition-all duration-200 cursor-pointer",
        selected
          ? "border-accent bg-accent-soft"
          : "border-border hover:border-border-hover",
      )}
    >
      <div className="flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </div>
      {desc && <p className="mt-1 text-xs text-muted-foreground">{desc}</p>}
      {children}
    </div>
  );
}

// ── 步骤 2：预览（门禁在这里执行）─────────────

function Step2({ t, preview, loading, onBack, onNext }) {
  if (loading || !preview) {
    return (
      <FadeIn delay={0.05}>
        <div className="card-glass p-8 text-center text-sm text-secondary-foreground">
          <span className="spinner mr-2" aria-hidden="true" />
          {t("deploy.runningPreview")}
        </div>
      </FadeIn>
    );
  }

  const gate = preview.gate ?? { ok: false, reason: "exit" };
  const blocked = !gate.ok;

  const gateMessage = {
    timeout: t("deploy.previewTimeout"),
    empty: t("deploy.previewEmpty"),
    exit: t("deploy.previewFailed"),
    blockers: t("deploy.blockers"),
    unrecognized: t("deploy.previewUnrecognized"),
  }[gate.reason];

  return (
    <>
      <FadeIn delay={0.05}>
        <div className="card-glass p-6">
          {preview.promptSource && (
            <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-muted-foreground">{t("deploy.promptSource")}</dt>
              <dd className="min-w-0 break-all font-mono text-xs text-secondary-foreground">
                {preview.promptSource.source}
              </dd>
              <dt className="text-muted-foreground">{t("deploy.sha256")}</dt>
              <dd className="min-w-0 break-all font-mono text-xs text-secondary-foreground">
                {preview.promptSource.sha256}
              </dd>
            </dl>
          )}

          {/* [Behavior notice] 原样展示 — 项目安全承诺 */}
          {preview.behaviorNotice && (
            <div
              role="note"
              className="mb-4 rounded-[10px] border border-warn/50 bg-[var(--warn-soft)] p-3.5"
            >
              <div className="flex items-center gap-1.5 text-xs font-semibold text-warn">
                <ShieldAlert className="size-3.5" aria-hidden="true" />
                {t("deploy.behaviorNotice")}
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-secondary-foreground">
                {preview.behaviorNotice}
              </p>
            </div>
          )}

          {/* 门禁失败：显眼阻断块，展示 stderr/原因 */}
          {blocked && (
            <div className="mb-4 rounded-[10px] border border-danger/50 bg-[var(--danger-soft)] p-3.5" role="alert">
              <div className="text-sm font-semibold text-danger">{gateMessage}</div>
              {(gate.detail || preview.error || preview.stderr) && (
                <pre className="log-block mt-2.5">{gate.detail || preview.error || preview.stderr}</pre>
              )}
            </div>
          )}

          {preview.targets?.length > 0 && (
            <>
              <div className="text-sm font-medium">{t("deploy.timeline")}</div>
              <div className="mt-2.5">
                {preview.targets.map((target) => (
                  <div key={target.dir} className="mb-3">
                    <div className="break-all font-mono text-xs font-semibold text-foreground">
                      {target.dir}
                    </div>
                    <ol className="mt-1.5 space-y-1 border-l-2 border-border pl-3.5">
                      {target.actions.map((a, i) => (
                        <li
                          key={i}
                          className={cn(
                            "relative break-all font-mono text-xs text-secondary-foreground",
                            a.startsWith("[Blocked]") && "font-semibold text-danger",
                            a.startsWith("No hooks") && "text-warn",
                          )}
                        >
                          <span
                            className="absolute -left-[19px] top-[5px] size-2 rounded-full border border-border bg-background"
                            aria-hidden="true"
                          />
                          {a}
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            </>
          )}

          {preview.raw && (
            <Collapsible className="mt-4">
              <CollapsibleTrigger className="cursor-pointer text-xs font-medium text-accent hover:text-accent-hover">
                {t("deploy.rawOutput")}
              </CollapsibleTrigger>
              <CollapsibleContent>
                <pre className="log-block mt-2">{preview.raw}</pre>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </FadeIn>

      <FadeIn delay={0.1}>
        <div className="mt-4 flex justify-between">
          <Button variant="outline" onClick={onBack}>← {t("deploy.back")}</Button>
          <Button onClick={onNext} disabled={blocked}>
            {t("deploy.next")} →
          </Button>
        </div>
      </FadeIn>
    </>
  );
}

// ── 步骤 3：确认执行 ──────────────────────────

function Step3({ t, deploying, result, onBack, onConfirm }) {
  return (
    <>
      <FadeIn delay={0.05}>
        <div className="card-glass p-6">
          <p className="text-sm text-secondary-foreground">{t("deploy.confirmHint")}</p>
          <div className="mt-4 flex justify-center">
            <Button
              variant="destructive"
              size="lg"
              onClick={onConfirm}
              disabled={deploying || result?.ok}
            >
              {deploying ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  {t("deploy.deploying")}
                </>
              ) : (
                t("deploy.confirmDeploy")
              )}
            </Button>
          </div>

          {result && (
            <div
              className={cn(
                "mt-5 rounded-[10px] border p-4",
                result.ok
                  ? "border-[var(--ok)]/50 bg-[var(--ok-soft)]"
                  : "border-danger/50 bg-[var(--danger-soft)]",
              )}
              role={result.ok ? "status" : "alert"}
            >
              <div
                className={cn(
                  "flex items-center gap-1.5 text-sm font-semibold",
                  result.ok ? "text-ok" : "text-danger",
                )}
              >
                {result.ok && <CheckCircle2 className="size-4" aria-hidden="true" />}
                {result.ok ? t("deploy.success") : `${t("deploy.failed")}${result.code ? ` (exit ${result.code})` : ""}`}
              </div>
              {result.text && <pre className="log-block mt-2.5">{result.text}</pre>}
            </div>
          )}
        </div>
      </FadeIn>

      <FadeIn delay={0.08}>
        <div className="mt-4">
          <Button variant="outline" onClick={onBack} disabled={deploying || result?.ok}>
            ← {t("deploy.back")}
          </Button>
        </div>
      </FadeIn>
    </>
  );
}

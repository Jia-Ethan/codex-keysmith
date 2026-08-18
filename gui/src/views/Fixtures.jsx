import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { FlaskConical, FolderOpen, ShieldAlert } from "lucide-react";
import {
  fetchScaffoldList,
  fetchScaffoldPreview,
  executeScaffold,
  fetchScaffoldUninstallPreview,
  executeScaffoldUninstall,
} from "@/lib/api";
import { parseScaffoldPreview } from "@/lib/parser";
import { useAppState } from "@/hooks/useAppState";
import {
  beginExclusiveOperation,
  endOperation,
  setView,
} from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/FadeIn";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { cn } from "@/lib/utils";

function previewReasonKey(reason) {
  if (reason === "timeout") return "deploy.previewTimeout";
  if (reason === "empty") return "deploy.previewEmpty";
  if (reason === "unrecognized") return "deploy.previewUnrecognized";
  if (reason === "blockers") return "deploy.blockers";
  return "deploy.previewFailed";
}

export function Fixtures() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [library, setLibrary] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [workspaceRoot, setWorkspaceRoot] = React.useState("");
  const [force, setForce] = React.useState(false);
  const [preview, setPreview] = React.useState(null);
  const [pending, setPending] = React.useState(null);
  const [writeResult, setWriteResult] = React.useState(null);
  const [loading, setLoading] = React.useState({
    list: false,
    preview: false,
    uninstall: false,
  });

  const cliChecking = !cliInfo.checked;
  const cliUnavailable = cliInfo.checked && !cliInfo.path;

  const refreshLibrary = React.useCallback(async () => {
    setLoading((state) => ({ ...state, list: true }));
    try {
      const parsed = await fetchScaffoldList();
      setLibrary(parsed);
      setSelectedId((current) => {
        if (current && parsed.packages.some((item) => item.id === current)) return current;
        return parsed.packages[0]?.id || null;
      });
    } catch (err) {
      setLibrary({ error: err?.message || String(err), packages: [] });
      setSelectedId(null);
      toast.error(t("fixtures.listFailed"));
    } finally {
      setLoading((state) => ({ ...state, list: false }));
    }
  }, [t]);

  React.useEffect(() => {
    if (!cliInfo.path) return;
    refreshLibrary();
  }, [cliInfo.path, refreshLibrary]);

  const pickDir = async () => {
    const picked = await open({ directory: true });
    if (picked) {
      setWorkspaceRoot(picked);
      setPreview(null);
      setWriteResult(null);
    }
  };

  const runPreview = async (kind) => {
    if (!selectedId) return;
    const key = kind === "uninstall" ? "uninstall" : "preview";
    setLoading((state) => ({ ...state, [key]: true }));
    setPreview(null);
    setWriteResult(null);
    try {
      const parsed = kind === "uninstall"
        ? await fetchScaffoldUninstallPreview(selectedId, { workspaceRoot: workspaceRoot.trim() || undefined })
        : await fetchScaffoldPreview(selectedId, {
          workspaceRoot: workspaceRoot.trim() || undefined,
          force,
        });
      const snapshot = { ...parsed, kind, packId: selectedId, workspaceRoot: workspaceRoot.trim() };
      setPreview(snapshot);
      if (!snapshot.gate?.ok) toast.error(t(previewReasonKey(snapshot.gate?.reason)));
    } catch (err) {
      setPreview({
        kind,
        packId: selectedId,
        workspaceRoot: workspaceRoot.trim(),
        gate: { ok: false, reason: "exit", detail: err?.message || String(err) },
        raw: err?.stdout || err?.message || String(err),
        stderr: err?.stderr || "",
      });
      toast.error(t("fixtures.previewFailed"));
    } finally {
      setLoading((state) => ({ ...state, [key]: false }));
    }
  };

  const previewCurrent = preview
    && preview.gate?.ok
    && preview.packId === selectedId
    && preview.workspaceRoot === workspaceRoot.trim();

  const runWrite = async () => {
    if (!previewCurrent) {
      toast.error(t("fixtures.previewStale"));
      setPending(null);
      return;
    }
    const operationLease = beginExclusiveOperation();
    if (!operationLease) {
      toast.warning(t("common.operationBusy"));
      return;
    }
    try {
      const output = preview.kind === "uninstall"
        ? await executeScaffoldUninstall(preview.packId, {
          workspaceRoot: preview.workspaceRoot || undefined,
        })
        : await executeScaffold(preview.packId, {
          workspaceRoot: preview.workspaceRoot || undefined,
          force,
        });
      const parsed = parseScaffoldPreview(output.stdout);
      if (output.timed_out) {
        setWriteResult({ ok: false, text: t("fixtures.timedOut") });
        toast.error(t("fixtures.writeFailed"));
      } else if (output.exit_code === 0 && parsed.didNotModifyCodex) {
        setWriteResult({
          ok: true,
          text: output.stdout,
          dest: parsed.dest,
          startPrompt: parsed.startPrompt,
        });
        toast.success(preview.kind === "uninstall"
          ? t("fixtures.uninstallSuccess")
          : t("fixtures.writeSuccess"));
      } else {
        setWriteResult({ ok: false, text: output.stderr || output.stdout });
        toast.error(t("fixtures.writeFailed"));
      }
      setPreview(null);
    } catch (err) {
      setWriteResult({ ok: false, text: err?.message || String(err) });
      toast.error(t("fixtures.writeFailed"));
    } finally {
      setPending(null);
      endOperation(operationLease);
    }
  };

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("fixtures.title")}</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">{t("fixtures.subtitle")}</p>
      </FadeIn>

      {cliChecking ? (
        <FadeIn delay={0.1}>
          <div className="card-glass mt-6 p-6 text-sm text-muted-foreground">
            <span className="spinner mr-1.5" aria-hidden="true" />
            {t("dash.loading")}
          </div>
        </FadeIn>
      ) : cliUnavailable ? (
        <FadeIn delay={0.1}>
          <div className="card-glass mt-6 p-6 text-sm">
            <div className="font-semibold">{t("dash.noCli")}</div>
            <Button className="mt-4" size="sm" onClick={() => setView("settings")}>
              {t("dash.noCliAction")}
            </Button>
          </div>
        </FadeIn>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <FadeIn delay={0.05}>
            <section className="card-glass p-5">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-medium">{t("fixtures.library")}</h2>
                <Button size="sm" variant="outline" onClick={refreshLibrary} disabled={loading.list}>
                  {t("dash.refresh")}
                </Button>
              </div>
              {library?.error ? (
                <p className="mt-3 text-sm text-danger">{library.error}</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {(library?.packages || []).map((item) => {
                    const active = item.id === selectedId;
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedId(item.id);
                            setPreview(null);
                            setWriteResult(null);
                          }}
                          className={cn(
                            "w-full rounded-[12px] border p-3 text-left transition-colors",
                            active
                              ? "border-accent bg-accent-soft"
                              : "border-border hover:border-border-hover",
                          )}
                        >
                          <div className="flex items-center gap-2 text-sm font-medium">
                            <FlaskConical className="size-4 shrink-0" aria-hidden="true" />
                            <span className="font-mono">{item.id}</span>
                            <Badge variant="outline">v{item.version}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {item.family} · {item.title}
                          </p>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </FadeIn>

          <FadeIn delay={0.1}>
            <section className="card-glass p-5">
              <h2 className="text-sm font-medium">{t("fixtures.workspace")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t("fixtures.workspaceHint")}</p>
              <div className="mt-2.5 flex gap-2">
                <Input
                  className="flex-1 font-mono"
                  value={workspaceRoot}
                  onChange={(e) => {
                    setWorkspaceRoot(e.target.value);
                    setPreview(null);
                    setWriteResult(null);
                  }}
                  placeholder={t("fixtures.workspacePlaceholder")}
                />
                <Button variant="outline" onClick={pickDir}>
                  <FolderOpen className="size-4" aria-hidden="true" />
                </Button>
              </div>
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                />
                {t("fixtures.force")}
              </label>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => runPreview("write")}
                  disabled={!selectedId || loading.preview || operationInProgress}
                >
                  {t("fixtures.previewWrite")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => runPreview("uninstall")}
                  disabled={!selectedId || loading.uninstall || operationInProgress}
                >
                  {t("fixtures.previewUninstall")}
                </Button>
              </div>

              {preview && (
                <div className="mt-4 rounded-[12px] border border-border p-3 text-sm">
                  {!preview.gate?.ok ? (
                    <div className="text-danger">
                      <ShieldAlert className="mr-1 inline size-4" aria-hidden="true" />
                      {t(previewReasonKey(preview.gate?.reason))}
                      {preview.gate?.detail && (
                        <pre className="log-block mt-2">{preview.gate.detail}</pre>
                      )}
                    </div>
                  ) : (
                    <>
                      <div className="font-medium">
                        {preview.kind === "uninstall"
                          ? t("fixtures.uninstallPreview")
                          : t("fixtures.writePreview")}
                      </div>
                      {preview.dest && (
                        <p className="mt-1 font-mono text-xs">{preview.dest}</p>
                      )}
                      {preview.didNotModifyCodex && (
                        <p className="mt-1 text-xs text-ok">{t("fixtures.didNotModifyCodex")}</p>
                      )}
                      {preview.previewOnly && (
                        <p className="mt-1 text-xs text-muted-foreground">{t("fixtures.previewOnly")}</p>
                      )}
                      <Button
                        className="mt-3"
                        size="sm"
                        onClick={() => setPending(preview)}
                        disabled={operationInProgress}
                      >
                        {preview.kind === "uninstall"
                          ? t("fixtures.confirmUninstall")
                          : t("fixtures.confirmWrite")}
                      </Button>
                    </>
                  )}
                </div>
              )}

              {writeResult && (
                <div className="mt-4 rounded-[12px] border border-border p-3 text-sm">
                  <div className={writeResult.ok ? "text-ok font-medium" : "text-danger font-medium"}>
                    {writeResult.ok ? t("fixtures.writeDone") : t("fixtures.writeFailed")}
                  </div>
                  {writeResult.dest && (
                    <p className="mt-1 font-mono text-xs">{writeResult.dest}</p>
                  )}
                  {writeResult.startPrompt && (
                    <p className="mt-2 text-xs">
                      {t("fixtures.startPrompt")}: {writeResult.startPrompt}
                    </p>
                  )}
                  {writeResult.text && (
                    <pre className="log-block mt-2">{writeResult.text}</pre>
                  )}
                </div>
              )}
            </section>
          </FadeIn>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(pending)}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title={pending?.kind === "uninstall"
          ? t("fixtures.confirmUninstall")
          : t("fixtures.confirmWrite")}
        body={pending?.dest || selectedId || ""}
        confirmText={t("common.confirm")}
        confirmDisabled={operationInProgress}
        danger={pending?.kind === "uninstall"}
        onConfirm={runWrite}
      />
    </div>
  );
}

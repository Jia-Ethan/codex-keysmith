import React from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, Terminal, Zap, AlertTriangle, ExternalLink, Power } from "lucide-react";
import { toast } from "sonner";
import { fetchStatus, readManifest, isTauriMissing } from "@/lib/api";
import { useAppState } from "@/hooks/useAppState";
import { setLastStatus, setView } from "@/lib/store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/FadeIn";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const ACTIVATION_VARIANT = {
  active: "green",
  "inactive-by-config": "yellow",
  conflict: "red",
  "not-installed": "gray",
  unknown: "gray",
};

const NODE_ICON = { regular: "✓", missing: "—", other: "⚠" };

const PULSE_COLOR = {
  green: "var(--ok)",
  yellow: "var(--warn)",
  red: "var(--danger)",
  gray: "var(--text-muted)",
};

export async function refreshDashboardSnapshot({
  fetcher = fetchStatus,
  setStatusState,
  setCachedStatus = setLastStatus,
}) {
  // A refresh is authoritative: stale cards must disappear before new output arrives.
  setStatusState(null);
  setCachedStatus(null);
  const nextStatus = await fetcher();
  setStatusState(nextStatus);
  setCachedStatus(nextStatus);
  return nextStatus;
}

export function Dashboard() {
  const { t } = useTranslation();
  const { cliInfo, lastStatus } = useAppState();
  const [status, setStatus] = React.useState(lastStatus);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await refreshDashboardSnapshot({ setStatusState: setStatus });
    } catch (err) {
      if (isTauriMissing(err)) return;
      setError(err instanceof Error ? err : new Error(String(err)));
      toast.error(t("dash.error"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  React.useEffect(() => {
    if (cliInfo.checked && cliInfo.path && !status) refresh();
  }, [cliInfo.checked, cliInfo.path]); // eslint-disable-line react-hooks/exhaustive-deps

  const cliChecking = !cliInfo.checked;
  const noCli = cliInfo.checked && !cliInfo.path && !cliInfo.error;
  const cliFailed = cliInfo.checked && !cliInfo.path && !!cliInfo.error;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <FadeIn>
            <h1 className="text-2xl font-semibold tracking-tight">{t("dash.title")}</h1>
          </FadeIn>
          <FadeIn delay={0.05}>
            <p className="mt-1 text-sm text-muted-foreground">
              {cliChecking || loading ? (
                <>
                  <span className="spinner mr-1.5" aria-hidden="true" />
                  {t("dash.loading")}
                </>
              ) : status ? (
                t("dash.summary", {
                  cliVer: cliInfo.version || "",
                  runtime: cliInfo.runtime ? t(`runtime.${cliInfo.runtime}`) : "",
                  count: status.directories.length,
                })
              ) : (
                ""
              )}
            </p>
          </FadeIn>
        </div>
        <FadeIn delay={0.1}>
          <Button
            variant="ghost"
            size="sm"
            onClick={refresh}
            disabled={loading || cliChecking || noCli || cliFailed}
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
            {t("dash.refresh")}
          </Button>
        </FadeIn>
      </div>

      {noCli && (
        <FadeIn delay={0.1}>
          <div className="card-glass p-8 text-center">
            <Terminal className="mx-auto size-10 text-muted-foreground" aria-hidden="true" />
            <p className="mt-4 text-sm text-secondary-foreground">{t("dash.noCli")}</p>
            <div className="mx-auto mt-5 max-w-md rounded-[10px] border border-border bg-muted p-4 text-left">
              <div className="text-xs font-semibold text-foreground">{t("dash.getCliTitle")}</div>
              <p className="mt-2 text-xs text-secondary-foreground">
                {t("dash.getCliStep1")}
                <a
                  href="https://github.com/Jia-Ethan/codex-keysmith"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 inline-flex items-center gap-0.5 font-mono text-accent hover:text-accent-hover"
                >
                  {t("dash.getCliLink")}
                  <ExternalLink className="size-3" aria-hidden="true" />
                </a>
              </p>
              <p className="mt-1.5 text-xs text-secondary-foreground">{t("dash.getCliStep2")}</p>
            </div>
            <Button className="mt-5" onClick={() => setView("settings")}>
              {t("dash.noCliAction")}
            </Button>
          </div>
        </FadeIn>
      )}

      {cliFailed && (
        <FadeIn delay={0.1}>
          <div className="card-glass border-danger/40 p-6" role="alert">
            <div className="flex items-center gap-2 text-sm font-semibold text-danger">
              <AlertTriangle className="size-4" aria-hidden="true" />
              {t("dash.cliCheckFailed")}
            </div>
            <pre className="log-block mt-3">{cliInfo.error}</pre>
            <Button className="mt-4" onClick={() => setView("settings")}>
              {t("dash.noCliAction")}
            </Button>
          </div>
        </FadeIn>
      )}

      {error && (
        <StatusFailure error={error} t={t} />
      )}

      {status?.degraded && <StatusDiagnostic status={status} t={t} />}

      {status && status.directories.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">{t("dash.noDirs")}</p>
      )}

      {status && status.directories.length > 0 && (
        <div className="flex flex-col gap-4">
          {status.directories.map((dir, i) => (
            <StatusCard key={dir.path} dir={dir} index={i} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}

export function StatusFailure({ error, t }) {
  const stdout = String(error.stdout ?? error.output?.stdout ?? "");
  const stderr = String(error.stderr ?? error.output?.stderr ?? "");
  const timedOut = Boolean(error.timedOut ?? error.output?.timed_out);
  const exitCode = error.exitCode ?? error.output?.exit_code ?? null;
  const hasStructuredOutput = stdout.trim() || stderr.trim();

  return (
    <FadeIn delay={0.1}>
      <div className="card-glass border-danger/40 p-5" role="alert">
        <div className="flex items-center gap-2 text-sm font-semibold text-danger">
          <AlertTriangle className="size-4" aria-hidden="true" />
          {t("dash.error")}
        </div>
        {(timedOut || exitCode !== null) && (
          <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-secondary-foreground">
            {timedOut && (
              <>
                <dt className="text-muted-foreground">{t("dash.diagnosticTimeout")}</dt>
                <dd>{t("dash.diagnosticYes")}</dd>
              </>
            )}
            {exitCode !== null && (
              <>
                <dt className="text-muted-foreground">{t("dash.diagnosticExitCode")}</dt>
                <dd className="font-mono">{exitCode}</dd>
              </>
            )}
          </dl>
        )}
        {stderr.trim() && (
          <div className="mt-3">
            <div className="text-xs font-medium text-muted-foreground">
              {t("dash.diagnosticStderr")}
            </div>
            <pre className="log-block mt-1.5">{stderr}</pre>
          </div>
        )}
        {stdout.trim() && (
          <div className="mt-3">
            <div className="text-xs font-medium text-muted-foreground">
              {t("dash.diagnosticStdout")}
            </div>
            <pre className="log-block mt-1.5">{stdout}</pre>
          </div>
        )}
        {!hasStructuredOutput && <pre className="log-block mt-2.5">{error.message}</pre>}
      </div>
    </FadeIn>
  );
}

function StatusDiagnostic({ status, t }) {
  const completeOutput = [
    status.raw?.trim()
      ? `${t("dash.diagnosticStdout")}\n${status.raw}`
      : null,
    status.stderr?.trim()
      ? `${t("dash.diagnosticStderr")}\n${status.stderr}`
      : null,
  ].filter(Boolean).join("\n\n");

  return (
    <FadeIn delay={0.1}>
      <div className="card-glass mb-4 border-warn/50 p-5" role="alert">
        <div className="flex items-center gap-2 text-sm font-semibold text-warn">
          <AlertTriangle className="size-4" aria-hidden="true" />
          {t("dash.diagnosticTitle")}
        </div>
        <p className="mt-2 text-xs text-secondary-foreground">
          {t("dash.diagnosticSummary", { exitCode: status.exitCode })}
        </p>
        {completeOutput && (
          <Collapsible className="mt-3">
            <CollapsibleTrigger className="cursor-pointer text-xs font-medium text-accent hover:text-accent-hover">
              {t("dash.diagnosticOutput")}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="log-block mt-2.5">{completeOutput}</pre>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </FadeIn>
  );
}

function StatusCard({ dir, index, t }) {
  const variant = ACTIVATION_VARIANT[dir.activation] || "gray";
  const node = (key) => dir.nodes[key]?.kind ?? "missing";
  const hasResidue = dir.residue.length > 0;
  const hasAbnormal = dir.abnormalNodes.length > 0;

  return (
    <FadeIn delay={0.1 + index * 0.08}>
      <section
        className={cn("card-glass card-glass-hover p-5", hasResidue && "border-warn/50")}
        aria-label={dir.path}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="pulse-dot"
            style={{
              background: PULSE_COLOR[variant],
              color: PULSE_COLOR[variant],
            }}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1 truncate font-mono text-sm font-medium" title={dir.path}>
            {dir.path}
          </span>
          <Badge variant={variant}>{t(`state.${dir.activation}`)}</Badge>
        </div>

        {/* 异常节点：显眼警告块（问题 2 修复：不再静默丢弃） */}
        {hasAbnormal && (
          <div className="mt-3 rounded-[10px] border border-warn/50 bg-[var(--warn-soft)] p-3" role="alert">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-warn">
              <AlertTriangle className="size-3.5" aria-hidden="true" />
              {t("dash.abnormalNodes")}
            </div>
            <ul className="mt-1.5 space-y-0.5 text-xs text-secondary-foreground">
              {dir.abnormalNodes.map((n) => (
                <li key={n.key} className="font-mono break-all">
                  {n.name}: <span className="font-semibold text-warn">{n.kind}</span> ({n.path})
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-xs text-muted-foreground">{t("dash.abnormalNodeHint")}</p>
          </div>
        )}

        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <Kv k={t("dash.modelInstructions")}>
            <span className="font-mono text-xs">{dir.modelInstructionsFile ?? t("dash.unset")}</span>
          </Kv>
          <Kv k={t("dash.hooks")}>
            {NODE_ICON[node("hooks")]} hooks.json · {NODE_ICON[node("hooksDisabled")]} hooks.json.disabled{" "}
            <span className="text-muted-foreground">({dir.hooksStatus})</span>
          </Kv>
          <Kv k={t("dash.promptFile")}>
            {NODE_ICON[node("md")]} gpt-unrestricted.md
            {node("legacyMd") !== "missing" && ` · legacy: ${NODE_ICON[node("legacyMd")]}`}
          </Kv>
          <Kv k={t("dash.residue")}>
            {hasResidue ? (
              <span className="font-mono text-xs text-danger break-all">{dir.residue.join(", ")}</span>
            ) : (
              t("dash.residueNone")
            )}
          </Kv>
          <Kv k={t("dash.legacy")}>{dir.legacyMigration}</Kv>
          <Kv k={t("dash.health")}>
            <Badge variant={dir.health === "healthy" ? "green" : "red"}>{dir.health}</Badge>
          </Kv>
          <Kv k={t("dash.uninstallReadiness")}>{dir.uninstallReadiness}</Kv>
          <Kv k={t("dash.deployability")}>{dir.deployability}</Kv>
        </dl>

        {dir.warnings.length > 0 && (
          <div className="mt-3 rounded-[10px] border border-border bg-muted p-3 text-xs text-secondary-foreground" role="note">
            {dir.warnings.map((w) => (
              <div key={w} className="break-all">⚠ {w}</div>
            ))}
          </div>
        )}

        {hasResidue && (
          <Button variant="warning" size="sm" className="mt-3" onClick={() => setView("manage")}>
            <Zap className="size-3.5" aria-hidden="true" />
            {t("dash.recoverAction")}
          </Button>
        )}

        {dir.activation === "inactive-by-config" && dir.health === "healthy" && (
          <Button size="sm" className={hasResidue ? "mt-2" : "mt-3"} onClick={() => setView("manage")}>
            <Power className="size-3.5" aria-hidden="true" />
            {t("dash.reactivateAction")}
          </Button>
        )}

        {dir.nodes.manifest?.kind === "regular" && <ManifestDetail codexDir={dir.path} t={t} />}
      </section>
    </FadeIn>
  );
}

function Kv({ k, children }) {
  return (
    <>
      <dt className="text-muted-foreground whitespace-nowrap">{k}</dt>
      <dd className="min-w-0 text-secondary-foreground">{children}</dd>
    </>
  );
}

function ManifestDetail({ codexDir, t }) {
  const [manifest, setManifest] = React.useState(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    readManifest(codexDir)
      .then(setManifest)
      .catch(() => setFailed(true));
  }, [codexDir]);

  if (failed) {
    return <p className="mt-3 text-xs text-muted-foreground">{t("dash.manifestUnavailable")}</p>;
  }
  if (!manifest) return null;

  const backup = (name) =>
    name ? <span className="text-muted-foreground"> ({t("dash.backup")}: {name})</span> : null;

  const rows = [
    [t("dash.deployedAt"), manifest.created_at ?? t("dash.unknown")],
    [t("dash.toolVersion"), manifest.tool_version ?? t("dash.unknown")],
    [t("dash.deploymentId"), manifest.deployment_id ?? t("dash.unknown")],
    [t("dash.promptEntry"), manifest.md?.path ?? t("dash.unknown"), manifest.md?.backup],
    [
      t("dash.configEntry"),
      manifest.config?.changed ? t("dash.configChanged") : t("dash.configUnchanged"),
      manifest.config?.backup,
    ],
    [
      t("dash.hooks"),
      manifest.hooks?.isolated ? t("dash.hooksIsolated") : t("dash.hooksNotIsolated"),
      manifest.hooks?.backup,
    ],
    [t("dash.legacy"), manifest.legacy?.action ?? t("dash.unknown"), manifest.legacy?.archive],
  ];

  return (
    <Collapsible className="mt-3">
      <CollapsibleTrigger className="cursor-pointer text-xs font-medium text-accent hover:text-accent-hover">
        {t("dash.manifestDetail")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
          {rows.map(([k, v, bak]) => (
            <React.Fragment key={k}>
              <dt className="text-muted-foreground whitespace-nowrap">{k}</dt>
              <dd className="min-w-0 break-all font-mono text-secondary-foreground">
                {String(v)}
                {backup(bak)}
              </dd>
            </React.Fragment>
          ))}
        </dl>
      </CollapsibleContent>
    </Collapsible>
  );
}

import React from "react";
import { useTranslation } from "react-i18next";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { ExternalLink } from "lucide-react";
import { detectCli, cliVersion } from "@/lib/api";
import { getSettings, saveSettings } from "@/lib/settings";
import { setCliInfo } from "@/lib/store";
import { useAppState } from "@/hooks/useAppState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FadeIn } from "@/components/FadeIn";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export function SettingsView() {
  const { t } = useTranslation();
  const { cliInfo } = useAppState();
  const s = getSettings();
  const [cliPathInput, setCliPathInput] = React.useState(s.cliPath);
  const [dirInput, setDirInput] = React.useState(s.defaultCodexDir);
  const [cliStatus, setCliStatus] = React.useState(null); // { ok, text }

  const refreshCliStatus = React.useCallback(
    async (manualPath) => {
      setCliStatus(null);
      try {
        const path = manualPath || (await detectCli());
        if (!path) {
          setCliStatus({ ok: false, text: t("settings.notFound") });
          setCliInfo({ path: null, checked: true });
          return;
        }
        let version = "";
        try {
          version = await cliVersion(path);
        } catch {
          /* 忽略 */
        }
        setCliInfo({ path, version, checked: true });
        setCliStatus({ ok: true, text: `${path}${version ? ` (${version})` : ""}` });
      } catch {
        setCliStatus({ ok: false, text: t("settings.cliInvalid") });
      }
    },
    [t],
  );

  React.useEffect(() => {
    refreshCliStatus(getSettings().cliPath);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const browseCli = async () => {
    const picked = await open({ filters: [{ name: "Python", extensions: ["py"] }] });
    if (picked) {
      setCliPathInput(picked);
      saveSettings({ cliPath: picked });
      toast.success(t("settings.saved"));
      refreshCliStatus(picked);
    }
  };

  const relocate = async () => {
    setCliStatus(null);
    const found = await detectCli();
    if (found) {
      saveSettings({ cliPath: "" });
      setCliPathInput("");
      let version = "";
      try {
        version = await cliVersion(found);
      } catch {
        /* 忽略 */
      }
      setCliInfo({ path: found, version, checked: true });
      setCliStatus({ ok: true, text: `${t("settings.relocated")}: ${found}${version ? ` (${version})` : ""}` });
      toast.success(t("settings.relocated"));
    } else {
      setCliInfo({ path: null, checked: true });
      setCliStatus({ ok: false, text: t("settings.notFound") });
      toast.warning(t("settings.notFound"));
    }
  };

  const themes = ["system", "light", "dark"];

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
      </FadeIn>

      {/* CLI 路径 */}
      <FadeIn delay={0.08}>
        <section className="card-glass mt-6 p-5" aria-label={t("settings.cliPath")}>
          <label htmlFor="set-cli" className="text-sm font-medium">{t("settings.cliPath")}</label>
          <div className="mt-1.5 flex gap-2">
            <Input
              id="set-cli"
              className="flex-1 font-mono text-xs"
              value={cliPathInput}
              onChange={(e) => setCliPathInput(e.target.value)}
              onBlur={() => {
                saveSettings({ cliPath: cliPathInput.trim() });
                toast.success(t("settings.saved"));
                refreshCliStatus(cliPathInput.trim());
              }}
              placeholder={t("settings.cliPathHint")}
            />
            <Button variant="outline" onClick={browseCli}>{t("settings.browse")}</Button>
          </div>
          <p className="mt-2 text-xs" role="status">
            {cliStatus ? (
              <span className={cn("break-all font-mono", cliStatus.ok ? "text-ok" : "text-danger")}>
                {cliStatus.ok ? "✓" : "✗"} {cliStatus.text}
              </span>
            ) : (
              <span className="text-muted-foreground"><span className="spinner mr-1" aria-hidden="true" /></span>
            )}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {t("settings.getCli")}{" "}
            <a
              href="https://github.com/Jia-Ethan/codex-keysmith"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 font-mono text-accent hover:text-accent-hover"
            >
              Jia-Ethan/codex-keysmith
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          </p>
          <div className="mt-3">
            <Button size="sm" variant="secondary" onClick={relocate}>{t("settings.relocate")}</Button>
          </div>
        </section>
      </FadeIn>

      {/* 默认 .codex 目录 */}
      <FadeIn delay={0.14}>
        <section className="card-glass mt-4 p-5" aria-label={t("settings.defaultDir")}>
          <label htmlFor="set-dir" className="text-sm font-medium">{t("settings.defaultDir")}</label>
          <div className="mt-1.5 flex gap-2">
            <Input
              id="set-dir"
              className="flex-1 font-mono text-xs"
              value={dirInput}
              onChange={(e) => setDirInput(e.target.value)}
              onBlur={() => {
                saveSettings({ defaultCodexDir: dirInput.trim() });
                toast.success(t("settings.saved"));
              }}
              placeholder={t("settings.defaultDirHint")}
            />
            <Button
              variant="outline"
              onClick={async () => {
                const picked = await open({ directory: true });
                if (picked) {
                  setDirInput(picked);
                  saveSettings({ defaultCodexDir: picked });
                  toast.success(t("settings.saved"));
                }
              }}
            >
              {t("settings.browse")}
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">{t("settings.defaultDirHint")}</p>
        </section>
      </FadeIn>

      {/* 语言与主题 */}
      <FadeIn delay={0.2}>
        <section className="card-glass mt-4 p-5" aria-label={t("settings.language")}>
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label htmlFor="set-lang" className="text-sm font-medium">{t("settings.language")}</label>
              <Select value={s.lang} onValueChange={(v) => saveSettings({ lang: v })}>
                <SelectTrigger id="set-lang" className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zh-CN">简体中文</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <span className="text-sm font-medium" id="theme-label">{t("settings.theme")}</span>
              <div
                role="radiogroup"
                aria-labelledby="theme-label"
                className="mt-1.5 flex rounded-[10px] border border-border p-0.5"
              >
                {themes.map((m) => (
                  <button
                    key={m}
                    role="radio"
                    aria-checked={s.theme === m}
                    onClick={() => saveSettings({ theme: m })}
                    className={cn(
                      "flex-1 cursor-pointer rounded-[8px] px-2 py-1.5 text-xs transition-colors",
                      s.theme === m
                        ? "bg-accent font-medium text-white"
                        : "text-secondary-foreground hover:text-foreground",
                    )}
                  >
                    {t(`settings.theme${m[0].toUpperCase() + m.slice(1)}`)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      </FadeIn>

      {/* 关于 */}
      <FadeIn delay={0.26}>
        <section className="card-glass mt-4 p-5" aria-label={t("settings.about")}>
          <div className="text-sm font-medium">{t("settings.about")}</div>
          <p className="mt-1.5 text-xs text-muted-foreground">{t("settings.aboutDesc")}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">Version</dt>
            <dd className="font-mono text-secondary-foreground">0.2.0</dd>
            <dt className="text-muted-foreground">CLI</dt>
            <dd className="break-all font-mono text-secondary-foreground">
              {cliInfo.path ? `${cliInfo.path}${cliInfo.version ? ` (${cliInfo.version})` : ""}` : t("settings.notFound")}
            </dd>
            <dt className="text-muted-foreground">GitHub</dt>
            <dd>
              <a
                href="https://github.com/Jia-Ethan/codex-keysmith"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 font-mono text-accent hover:text-accent-hover"
              >
                Jia-Ethan/codex-keysmith
                <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            </dd>
          </dl>
        </section>
      </FadeIn>
    </div>
  );
}

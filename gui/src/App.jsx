import React from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Toaster, toast } from "sonner";
import { useTranslation } from "react-i18next";
import i18n from "./i18n";
import { getSettings, onSettingsChange } from "@/lib/settings";
import { useAppState } from "@/hooks/useAppState";
import {
  beginCliCheck,
  completeCliCheck,
  setView,
  isOperationInProgressRef,
} from "@/lib/store";
import { resolveCli, isTauriMissing } from "@/lib/api";
import { AmbientBg } from "@/components/AmbientBg";
import { Sidebar } from "@/components/Sidebar";
import { Dashboard } from "@/views/Dashboard";
import { Deploy } from "@/views/Deploy";
import { Manage } from "@/views/Manage";
import { SettingsView } from "@/views/SettingsView";

/** 主题：system / light / dark，跟随系统时监听 matchMedia */
function useTheme() {
  const [theme, setTheme] = React.useState(() => getSettings().theme);

  React.useEffect(
    () =>
      onSettingsChange((s) => {
        setTheme(s.theme);
        if (s.lang !== i18n.language) i18n.changeLanguage(s.lang);
      }),
    [],
  );

  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && mq.matches);
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);
}

export default function App() {
  const { t } = useTranslation();
  const { view } = useAppState();
  useTheme();

  // 启动时探测 CLI
  React.useEffect(() => {
    const generation = beginCliCheck();
    (async () => {
      try {
        completeCliCheck(generation, {
          ...(await resolveCli(getSettings().cliPath)),
          error: null,
          checked: true,
        });
      } catch (err) {
        if (isTauriMissing(err)) return; // 纯浏览器预览保持未检测态
        completeCliCheck(generation, {
          path: null,
          version: "",
          runtime: "",
          error: err?.message || String(err),
          checked: true,
        });
      }
    })();
  }, []);

  // 部署/卸载期间禁止关闭窗口（仅 Tauri 环境）
  React.useEffect(() => {
    if (!window.__TAURI_INTERNALS__) return;
    let unlisten;
    getCurrentWindow()
      .onCloseRequested(async (event) => {
        if (isOperationInProgressRef()) {
          event.preventDefault();
          toast.warning(t("manage.running"));
        }
      })
      .then((fn) => (unlisten = fn))
      .catch(() => {});
    return () => unlisten?.();
  }, [t]);

  const views = {
    dashboard: <Dashboard />,
    deploy: <Deploy />,
    manage: <Manage />,
    settings: <SettingsView />,
  };

  return (
    <div className="flex h-full">
      <AmbientBg />
      <Sidebar />
      <main className="relative flex-1 overflow-y-auto" key={view}>
        <div className="mx-auto max-w-[880px] px-6 py-8 md:px-10">
          {views[view] ?? views.dashboard}
        </div>
      </main>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          },
        }}
      />
    </div>
  );
}

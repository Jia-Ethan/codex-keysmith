import React from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Toaster, toast } from "sonner";
import i18n from "./i18n";
import { getSettings, onSettingsChange } from "@/lib/settings";
import { useAppState } from "@/hooks/useAppState";
import {
  beginCliCheck,
  completeCliCheck,
  setView,
} from "@/lib/store";
import { resolveCli, isTauriMissing } from "@/lib/api";
import { installWindowCloseLifecycle } from "@/lib/windowLifecycle";
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

  // 所有关闭先建立退出屏障；活动后端调用结束后再销毁窗口。
  React.useEffect(() => {
    if (!window.__TAURI_INTERNALS__) return;
    const appWindow = getCurrentWindow();
    const lifecycle = installWindowCloseLifecycle({
      appWindow,
      onExitQueued: () => toast.warning(i18n.t("manage.exitQueued")),
      onError: ({ phase, error }) => {
        console.error(`Window close lifecycle ${phase} failed`, error);
        toast.error(i18n.t(
          phase === "registration" ? "manage.exitGuardFailed" : "manage.exitFailed",
        ));
      },
    });

    return lifecycle.dispose;
  }, []);

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

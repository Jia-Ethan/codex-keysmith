// main.js — 应用入口：导航、i18n、主题、CLI 检测、窗口关闭拦截

import { getCurrentWindow } from "@tauri-apps/api/window";
import { loadDashboard } from "./views/dashboard.js";
import { loadDeploy } from "./views/deploy.js";
import { loadManage } from "./views/manage.js";
import { loadSettings } from "./views/settings.js";
import { applySettings } from "./lib/settings.js";
import { initTheme } from "./lib/theme.js";
import { t, onLangChange } from "./lib/i18n.js";
import { detectCli, cliVersion, pythonVersion } from "./lib/api.js";
import { setCliInfo, isOperationInProgress, getCliInfo, setLastStatus } from "./lib/store.js";
import { escapeHtml, isTauriMissing } from "./lib/dom.js";
import { toast } from "./lib/toast.js";

const views = {
  dashboard: loadDashboard,
  deploy: loadDeploy,
  manage: loadManage,
  settings: loadSettings,
};

let currentView = "dashboard";

function switchView(name) {
  if (!views[name]) return;
  currentView = name;
  if (name !== "manage") setLastStatus(null); // 离开 manage 时失效快照
  document.querySelectorAll(".nav-item").forEach((btn) => {
    const active = btn.dataset.view === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  const target = document.getElementById(`view-${name}`);
  if (target) target.classList.remove("hidden");
  views[name](); // 每次切换重新加载（Dashboard 自动刷新 status）
}

function renderNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    const key = btn.dataset.view;
    btn.querySelector(".nav-label").textContent = t(`nav.${key}`);
  });
  const sub = document.getElementById("brand-subtitle");
  if (sub) sub.textContent = t("nav.subtitle");
}

async function initCli() {
  try {
    const [path, pyVer] = await Promise.all([
      detectCli(),
      pythonVersion().catch(() => ""),
    ]);
    let version = "";
    if (path) {
      try { version = await cliVersion(path); } catch { /* 忽略 */ }
    }
    setCliInfo({ path, version, pythonVersion: pyVer, checked: true });
  } catch (err) {
    if (isTauriMissing(err)) return; // 纯浏览器预览（无 Tauri 后端）保持加载态即可
    setCliInfo({ path: null, checked: true });
    return;
  }
  // CLI 检测完成后刷新当前视图，保证 subtitle 版本号不为空（加载守卫防竞态）
  views[currentView]?.();
}

// 启动
initTheme();
applySettings();
renderNav();

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

onLangChange(() => {
  renderNav();
  views[currentView]();
});

initCli();
loadDashboard();

// 部署/卸载期间禁止关闭窗口
getCurrentWindow().onCloseRequested(async (event) => {
  if (isOperationInProgress()) {
    event.preventDefault();
    toast(t("manage.running"), { type: "warning" });
  }
});

// lib/settings.js — 应用设置持久化（localStorage）
// React 迁移版：不再反向调用 i18n/theme，由 App 层统一消费变更。

const KEY = "codex-keysmith-gui:settings";

const defaults = {
  cliPath: "",         // 留空 = 自动探测
  defaultCodexDir: "", // 留空 = 自动发现全部
  lang: "zh-CN",
  theme: "system",
};

let cache = null;
const listeners = new Set();

export function normalizeCliPath(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeSettings(settings) {
  return { ...settings, cliPath: normalizeCliPath(settings.cliPath) };
}

export function getSettings() {
  if (!cache) {
    let stored = {};
    try {
      const parsed = JSON.parse(localStorage.getItem(KEY) || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        stored = parsed;
      }
    } catch {}
    cache = normalizeSettings({ ...defaults, ...stored });
    if (stored.cliPath !== undefined && stored.cliPath !== cache.cliPath) {
      try {
        localStorage.setItem(KEY, JSON.stringify(cache));
      } catch {}
    }
  }
  return { ...cache };
}

export function saveSettings(patch) {
  cache = normalizeSettings({ ...getSettings(), ...patch });
  localStorage.setItem(KEY, JSON.stringify(cache));
  listeners.forEach((fn) => fn(getSettings()));
  return getSettings();
}

export function onSettingsChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

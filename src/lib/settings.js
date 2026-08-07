// lib/settings.js — 应用设置持久化（localStorage）

import { setLang } from "./i18n.js";
import { setTheme } from "./theme.js";

const KEY = "codex-keysmith-gui:settings";

const defaults = {
  cliPath: "",        // 留空 = 自动探测
  defaultCodexDir: "", // 留空 = 自动发现全部
  lang: "zh-CN",
  theme: "system",
};

let cache = null;

export function getSettings() {
  if (!cache) {
    try {
      cache = { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
    } catch {
      cache = { ...defaults };
    }
  }
  return { ...cache };
}

export function saveSettings(patch) {
  cache = { ...getSettings(), ...patch };
  localStorage.setItem(KEY, JSON.stringify(cache));
  setLang(cache.lang);
  setTheme(cache.theme);
  return getSettings();
}

export function applySettings() {
  const s = getSettings();
  setLang(s.lang);
  setTheme(s.theme);
}

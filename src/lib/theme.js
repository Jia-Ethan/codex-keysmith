// lib/theme.js — 主题管理：system / light / dark

const media = window.matchMedia("(prefers-color-scheme: dark)");
let mode = "system";

function apply() {
  const dark = mode === "dark" || (mode === "system" && media.matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function getTheme() {
  return mode;
}

export function setTheme(next) {
  mode = ["system", "light", "dark"].includes(next) ? next : "system";
  apply();
}

export function initTheme() {
  media.addEventListener("change", apply);
  apply();
}

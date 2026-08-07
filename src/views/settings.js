// views/settings.js — 设置视图：CLI 路径 / 默认目录 / 语言 / 主题 / 关于

import { open } from "@tauri-apps/plugin-dialog";
import { detectCli, cliVersion } from "../lib/api.js";
import { getSettings, saveSettings } from "../lib/settings.js";
import { setCliInfo } from "../lib/store.js";
import { t } from "../lib/i18n.js";
import { escapeHtml, el } from "../lib/dom.js";
import { toast } from "../lib/toast.js";

export function loadSettings() {
  const root = document.getElementById("view-settings");
  const s = getSettings();
  root.innerHTML = "";
  root.appendChild(el("div", { class: "view-header" }, `
    <div>
      <h1 class="view-title anim-fade-up">${escapeHtml(t("settings.title"))}</h1>
    </div>`));

  // ── CLI 路径 ──
  const cliCard = el("div", { class: "card-glass anim-fade-up", style: "animation-delay:.08s" });
  cliCard.innerHTML = `
    <div class="step">
      <label class="step-label" for="set-cli">${escapeHtml(t("settings.cliPath"))}</label>
      <div class="file-row">
        <input type="text" id="set-cli" value="${escapeHtml(s.cliPath)}"
               placeholder="${escapeHtml(t("settings.cliPathHint"))}" style="flex:1">
        <button class="btn small" id="browse-cli">${escapeHtml(t("settings.browse"))}</button>
      </div>
      <div class="field-hint" id="cli-status"></div>
    </div>
    <div class="action-buttons">
      <button class="btn small" id="relocate-cli">${escapeHtml(t("settings.relocate"))}</button>
    </div>`;
  root.appendChild(cliCard);

  const cliInput = cliCard.querySelector("#set-cli");
  const cliStatus = cliCard.querySelector("#cli-status");
  cliInput.addEventListener("change", () => {
    saveSettings({ cliPath: cliInput.value.trim() });
    toast(t("settings.saved"), { type: "success" });
    refreshCliStatus(cliStatus, cliInput.value.trim());
  });
  cliCard.querySelector("#browse-cli").addEventListener("click", async () => {
    const picked = await open({ filters: [{ name: "Python", extensions: ["py"] }] });
    if (picked) {
      cliInput.value = picked;
      saveSettings({ cliPath: picked });
      toast(t("settings.saved"), { type: "success" });
      refreshCliStatus(cliStatus, picked);
    }
  });
  cliCard.querySelector("#relocate-cli").addEventListener("click", async () => {
    cliStatus.innerHTML = `<span class="spinner"></span>`;
    const found = await detectCli();
    if (found) {
      saveSettings({ cliPath: "" }); // 走自动探测
      cliInput.value = "";
      let version = "";
      try { version = await cliVersion(found); } catch { /* 忽略 */ }
      setCliInfo({ path: found, version, checked: true });
      cliStatus.innerHTML = `<span class="text-green">✓ ${escapeHtml(t("settings.relocated"))}: ${escapeHtml(found)}${version ? ` (${escapeHtml(version)})` : ""}</span>`;
      toast(t("settings.relocated"), { type: "success" });
    } else {
      setCliInfo({ path: null, checked: true });
      cliStatus.innerHTML = `<span class="text-red">✗ ${escapeHtml(t("settings.notFound"))}</span>`;
      toast(t("settings.notFound"), { type: "warning" });
    }
  });
  refreshCliStatus(cliStatus, s.cliPath);

  // ── 默认 .codex 目录 ──
  const dirCard = el("div", { class: "card-glass anim-fade-up", style: "animation-delay:.14s" });
  dirCard.innerHTML = `
    <div class="step">
      <label class="step-label" for="set-dir">${escapeHtml(t("settings.defaultDir"))}</label>
      <div class="file-row">
        <input type="text" id="set-dir" value="${escapeHtml(s.defaultCodexDir)}"
               placeholder="${escapeHtml(t("settings.defaultDirHint"))}" style="flex:1">
        <button class="btn small" id="browse-dir">${escapeHtml(t("settings.browse"))}</button>
      </div>
      <div class="field-hint">${escapeHtml(t("settings.defaultDirHint"))}</div>
    </div>`;
  root.appendChild(dirCard);
  const dirInput = dirCard.querySelector("#set-dir");
  dirInput.addEventListener("change", () => {
    saveSettings({ defaultCodexDir: dirInput.value.trim() });
    toast(t("settings.saved"), { type: "success" });
  });
  dirCard.querySelector("#browse-dir").addEventListener("click", async () => {
    const picked = await open({ directory: true });
    if (picked) {
      dirInput.value = picked;
      saveSettings({ defaultCodexDir: picked });
      toast(t("settings.saved"), { type: "success" });
    }
  });

  // ── 语言与主题 ──
  const prefCard = el("div", { class: "card-glass anim-fade-up", style: "animation-delay:.2s" });
  prefCard.innerHTML = `
    <div class="step">
      <label class="step-label" for="set-lang">${escapeHtml(t("settings.language"))}</label>
      <select id="set-lang">
        <option value="zh-CN" ${s.lang === "zh-CN" ? "selected" : ""}>简体中文</option>
        <option value="en" ${s.lang === "en" ? "selected" : ""}>English</option>
      </select>
    </div>
    <div class="step">
      <label class="step-label">${escapeHtml(t("settings.theme"))}</label>
      <div class="segmented" role="radiogroup" aria-label="${escapeHtml(t("settings.theme"))}">
        ${["system", "light", "dark"].map((m) => `
          <button class="segment ${s.theme === m ? "active" : ""}" data-theme="${m}" role="radio" aria-checked="${s.theme === m}">
            ${escapeHtml(t(`settings.theme${m[0].toUpperCase() + m.slice(1)}`))}
          </button>`).join("")}
      </div>
    </div>`;
  root.appendChild(prefCard);
  prefCard.querySelector("#set-lang").addEventListener("change", (e) => {
    saveSettings({ lang: e.target.value });
  });
  prefCard.querySelectorAll(".segment").forEach((btn) =>
    btn.addEventListener("click", () => {
      saveSettings({ theme: btn.dataset.theme });
      prefCard.querySelectorAll(".segment").forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-checked", b === btn ? "true" : "false");
      });
    }));

  // ── 关于 ──
  const aboutCard = el("div", { class: "card-glass anim-fade-up", style: "animation-delay:.26s" });
  aboutCard.innerHTML = `
    <div class="step-label">${escapeHtml(t("settings.about"))}</div>
    <p class="action-desc" style="margin-bottom:10px">${escapeHtml(t("settings.aboutDesc"))}</p>
    <div class="kv">
      <dt>Version</dt><dd>0.1.0</dd>
      <dt>GitHub</dt><dd><a href="https://github.com/Jia-Ethan/codex-keysmith" target="_blank" rel="noopener">Jia-Ethan/codex-keysmith</a></dd>
    </div>`;
  root.appendChild(aboutCard);
}

async function refreshCliStatus(holder, manualPath) {
  holder.innerHTML = `<span class="spinner"></span>`;
  try {
    const path = manualPath || (await detectCli());
    if (!path) {
      holder.innerHTML = `<span class="text-red">✗ ${escapeHtml(t("settings.notFound"))}</span>`;
      setCliInfo({ path: null, checked: true });
      return;
    }
    let version = "";
    try { version = await cliVersion(path); } catch { /* 忽略 */ }
    setCliInfo({ path, version, checked: true });
    holder.innerHTML = `<span class="text-green">✓ ${escapeHtml(path)}${version ? ` (${escapeHtml(version)})` : ""}</span>`;
  } catch {
    holder.innerHTML = `<span class="text-red">✗ ${escapeHtml(t("settings.cliInvalid"))}</span>`;
  }
}

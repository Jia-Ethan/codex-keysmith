// views/dashboard.js — 状态总览视图（M1）
// 进入视图时自动刷新 --status；卡片渲染激活状态、关键行、manifest 详情。

import { fetchStatus, readManifest } from "../lib/api.js";
import { getCliInfo, setLastStatus } from "../lib/store.js";
import { t } from "../lib/i18n.js";
import { escapeHtml, el, isTauriMissing } from "../lib/dom.js";
import { toast } from "../lib/toast.js";

const ACTIVATION_BADGE = {
  active: "green",
  "inactive-by-config": "yellow",
  conflict: "red",
  "not-installed": "gray",
  unknown: "gray",
};

const NODE_LABEL = { regular: "✓", missing: "—", other: "⚠" };

let dashboardLoading = false;

export async function loadDashboard() {
  if (dashboardLoading) return; // 防止 initCli 完成回调与首次渲染重复触发
  dashboardLoading = true;
  try {
    await renderDashboard();
  } finally {
    dashboardLoading = false;
  }
}

async function renderDashboard() {
  const root = document.getElementById("view-dashboard");
  root.innerHTML = "";

  const header = el("div", { class: "view-header" }, `
    <div>
      <h1 class="view-title anim-fade-up">${escapeHtml(t("dash.title"))}</h1>
      <div class="view-subtitle anim-fade-up" id="dash-subtitle" style="animation-delay:.05s">
        <span class="spinner"></span> ${escapeHtml(t("dash.loading"))}
      </div>
    </div>
    <button class="btn ghost anim-fade-up" id="dash-refresh" style="animation-delay:.1s">
      ${iconRefresh()} ${escapeHtml(t("dash.refresh"))}
    </button>`);
  root.appendChild(header);
  header.querySelector("#dash-refresh").addEventListener("click", loadDashboard);

  const cli = getCliInfo();
  const subtitle = header.querySelector("#dash-subtitle");

  if (cli.checked && !cli.path) {
    root.appendChild(el("div", { class: "card-glass empty-state anim-fade-up" }, `
      <div class="empty-icon">${iconTerminal()}</div>
      <p>${escapeHtml(t("dash.noCli"))}</p>
      <button class="btn primary" id="goto-settings">${escapeHtml(t("dash.noCliAction"))}</button>`));
    subtitle.textContent = "";
    root.querySelector("#goto-settings").addEventListener("click", () => {
      document.querySelector('[data-view="settings"]')?.click();
    });
    return;
  }

  try {
    const status = await fetchStatus();
    setLastStatus(status);
    subtitle.textContent = t("dash.summary", {
      cliVer: cli.version || "",
      pyVer: cli.pythonVersion || "",
      count: status.directories.length,
    });

    if (status.directories.length === 0) {
      root.appendChild(el("div", { class: "empty" }, escapeHtml(t("dash.noDirs"))));
      return;
    }

    const list = el("div", { class: "card-list" });
    root.appendChild(list);
    status.directories.forEach((dir, i) => {
      const card = renderCard(dir, i);
      list.appendChild(card);
      if (dir.nodes.manifest?.kind === "regular") {
        fillManifest(card, dir.path);
      }
    });
  } catch (err) {
    if (isTauriMissing(err)) return;
    subtitle.textContent = "";
    const msg = err?.message || String(err);
    root.appendChild(el("div", { class: "card-glass warning-block anim-fade-up" },
      `<strong>${escapeHtml(t("dash.error"))}</strong><pre class="log" style="margin-top:10px">${escapeHtml(msg)}</pre>`));
    toast(t("dash.error"), { type: "error" });
  }
}

function renderCard(dir, index) {
  const badgeClass = ACTIVATION_BADGE[dir.activation] || "gray";
  const node = (key) => dir.nodes[key]?.kind ?? "missing";
  const hasResidue = dir.residue.length > 0;

  const card = el("div", {
    class: `card-glass status-card anim-fade-up ${hasResidue ? "has-residue" : ""}`,
    style: `animation-delay:${0.1 + index * 0.08}s`,
  });

  const legacyPart = node("legacyMd") !== "missing"
    ? ` · legacy: ${NODE_LABEL[node("legacyMd")]}`
    : "";

  card.innerHTML = `
    <div class="card-header">
      <span class="pulse-dot pulse-${badgeClass}" aria-hidden="true"></span>
      <span class="card-title" title="${escapeHtml(dir.path)}">${escapeHtml(dir.path)}</span>
      <span class="badge ${badgeClass}">${escapeHtml(t(`state.${dir.activation}`))}</span>
    </div>
    <dl class="kv">
      <dt>${escapeHtml(t("dash.modelInstructions"))}</dt>
      <dd>${escapeHtml(dir.modelInstructionsFile ?? t("dash.unset"))}</dd>
      <dt>${escapeHtml(t("dash.hooks"))}</dt>
      <dd>${NODE_LABEL[node("hooks")]} hooks.json · ${NODE_LABEL[node("hooksDisabled")]} hooks.json.disabled
          <span class="dim">(${escapeHtml(dir.hooksStatus)})</span></dd>
      <dt>${escapeHtml(t("dash.promptFile"))}</dt>
      <dd>${NODE_LABEL[node("md")]} gpt-unrestricted.md${legacyPart}</dd>
      <dt>${escapeHtml(t("dash.residue"))}</dt>
      <dd>${hasResidue
        ? `<span class="text-red">${escapeHtml(dir.residue.join(", "))}</span>`
        : escapeHtml(t("dash.residueNone"))}</dd>
      <dt>${escapeHtml(t("dash.legacy"))}</dt>
      <dd>${escapeHtml(dir.legacyMigration)}</dd>
      <dt>${escapeHtml(t("dash.health"))}</dt>
      <dd><span class="badge ${dir.health === "healthy" ? "green" : "red"} small">${escapeHtml(dir.health)}</span></dd>
      <dt>${escapeHtml(t("dash.uninstallReadiness"))}</dt>
      <dd>${escapeHtml(dir.uninstallReadiness)}</dd>
      <dt>${escapeHtml(t("dash.deployability"))}</dt>
      <dd>${escapeHtml(dir.deployability)}</dd>
    </dl>
    <div class="manifest-holder" data-dir="${escapeHtml(dir.path)}"></div>`;

  if (hasResidue) {
    const btn = el("button", { class: "btn warning-btn recover-jump" },
      `⚡ ${escapeHtml(t("dash.recoverAction"))}`);
    btn.addEventListener("click", () => {
      document.querySelector('[data-view="manage"]')?.click();
    });
    card.appendChild(btn);
  }

  if (dir.warnings.length) {
    card.appendChild(el("div", { class: "warning-block" },
      dir.warnings.map((w) => `⚠ ${escapeHtml(w)}`).join("<br>")));
  }
  return card;
}

async function fillManifest(card, codexDir) {
  const holder = card.querySelector(".manifest-holder");
  try {
    const m = await readManifest(codexDir);
    const hooks = m.hooks || {};
    const legacy = m.legacy || {};
    const backup = (name) =>
      name ? ` <span class="dim">(${escapeHtml(t("dash.backup"))}: ${escapeHtml(name)})</span>` : "";
    const rows = [
      [t("dash.deployedAt"), m.created_at ?? t("dash.unknown")],
      [t("dash.toolVersion"), m.tool_version ?? t("dash.unknown")],
      [t("dash.deploymentId"), m.deployment_id ?? t("dash.unknown")],
      [t("dash.promptEntry"), `${m.md?.path ?? t("dash.unknown")}`, m.md?.backup],
      [t("dash.configEntry"),
        m.config?.changed ? t("dash.configChanged") : t("dash.configUnchanged"),
        m.config?.backup],
      [t("dash.hooks"),
        hooks.isolated ? t("dash.hooksIsolated") : t("dash.hooksNotIsolated"), hooks.backup],
      [t("dash.legacy"),
        `${legacy.action ?? t("dash.unknown")}`,
        legacy.archive],
    ];
    holder.innerHTML = `
      <details class="manifest-detail">
        <summary>${escapeHtml(t("dash.manifestDetail"))}</summary>
        <dl class="kv" style="margin-top:10px">
          ${rows.map(([k, v, bak]) => `
            <dt>${escapeHtml(k)}</dt>
            <dd>${escapeHtml(String(v))}${bak ? backup(bak) : ""}</dd>`).join("")}
        </dl>
      </details>`;
  } catch {
    holder.innerHTML = `<div class="empty" style="padding:8px 0 0">${escapeHtml(t("dash.manifestUnavailable"))}</div>`;
  }
}

function iconRefresh() {
  return `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg>`;
}

function iconTerminal() {
  return `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`;
}

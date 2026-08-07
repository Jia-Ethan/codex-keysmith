// views/manage.js — 管理视图（M3）：卸载 / 恢复 hooks / 恢复中断事务

import { cliRun, cliExecute, fetchStatus } from "../lib/api.js";
import { parseUninstallPreview } from "../lib/parser.js";
import { getCliInfo, getLastStatus, setLastStatus, setOperationInProgress } from "../lib/store.js";
import { getSettings } from "../lib/settings.js";
import { t } from "../lib/i18n.js";
import { escapeHtml, el } from "../lib/dom.js";
import { toast } from "../lib/toast.js";
import { confirmModal } from "../lib/modal.js";

let statusCache = null;
let busy = false;

export async function loadManage() {
  const root = document.getElementById("view-manage");
  root.innerHTML = "";
  root.appendChild(el("div", { class: "view-header" }, `
    <div>
      <h1 class="view-title anim-fade-up">${escapeHtml(t("manage.title"))}</h1>
      <div class="view-subtitle anim-fade-up" style="animation-delay:.05s">${escapeHtml(t("manage.subtitle"))}</div>
    </div>`));

  const cli = getCliInfo();
  if (cli.checked && !cli.path) {
    root.appendChild(el("div", { class: "card-glass warning-block anim-fade-up" },
      escapeHtml(t("dash.noCli"))));
    return;
  }

  // 复用 Dashboard 的 status 快照，没有就现场拉一次（决定 recover 是否可用）
  statusCache = getLastStatus();
  if (!statusCache) {
    try {
      statusCache = await fetchStatus();
      setLastStatus(statusCache);
    } catch {
      statusCache = null;
    }
  }

  const dirs = statusCache?.directories ?? [];
  const residueDirs = dirs.filter((d) => d.residue.length > 0);
  const body = el("div", { class: "card-list" });
  root.appendChild(body);

  body.appendChild(actionCard({
    key: "uninstall",
    title: t("manage.uninstall"),
    desc: t("manage.uninstallDesc"),
    icon: iconUndo(),
    delay: 0.1,
    hasPreview: true,
    confirmText: t("manage.confirmUninstall"),
    cliArgs: ["--uninstall"],
    dirs,
  }));

  body.appendChild(actionCard({
    key: "restore-hooks",
    title: t("manage.restoreHooks"),
    desc: t("manage.restoreHooksDesc"),
    icon: iconHook(),
    delay: 0.18,
    hasPreview: false,
    confirmText: t("manage.confirmRestore"),
    cliArgs: ["--restore-hooks"],
    dirs,
    noYes: true, // CLI 约束：--restore-hooks 与 --yes 互斥
  }));

  body.appendChild(actionCard({
    key: "recover",
    title: t("manage.recover"),
    desc: t("manage.recoverDesc"),
    icon: iconZap(),
    delay: 0.26,
    hasPreview: false,
    confirmText: t("manage.confirmRecover"),
    cliArgs: ["--recover"],
    dirs,
    enabled: residueDirs.length > 0,
    highlight: residueDirs.length > 0,
    extraBadge: residueDirs.length > 0 ? t("manage.recoverAvailable") : null,
  }));
}

function actionCard({ key, title, desc, icon, delay, hasPreview, confirmText, cliArgs, dirs, enabled = true, highlight = false, extraBadge = null, noYes = false }) {
  const card = el("div", {
    class: `card-glass action-card anim-fade-up ${highlight ? "highlight" : ""}`,
    style: `animation-delay:${delay}s`,
  });

  const needDirPick = dirs.length > 1;
  card.innerHTML = `
    <div class="action-head">
      <span class="action-icon">${icon}</span>
      <div style="flex:1">
        <div class="action-title">${escapeHtml(title)}
          ${extraBadge ? `<span class="badge yellow small">${escapeHtml(extraBadge)}</span>` : ""}
        </div>
        <div class="action-desc">${escapeHtml(desc)}</div>
      </div>
    </div>
    ${needDirPick ? `
      <div class="step" style="margin-top:12px">
        <label class="step-label">${escapeHtml(t("manage.selectDir"))}</label>
        <select id="dir-${key}">
          <option value="">${escapeHtml(t("manage.allDirs"))}</option>
          ${dirs.map((d) => `<option value="${escapeHtml(d.path)}">${escapeHtml(d.path)}</option>`).join("")}
        </select>
      </div>` : ""}
    <div class="action-buttons">
      ${hasPreview ? `<button class="btn small" id="preview-${key}" ${enabled ? "" : "disabled"}>${escapeHtml(t("manage.preview"))}</button>` : ""}
      <button class="btn small danger" id="exec-${key}" ${enabled ? "" : "disabled"}>${escapeHtml(t("manage.execute"))}</button>
    </div>
    <div class="action-result" id="result-${key}"></div>`;

  const dirOf = () => card.querySelector(`#dir-${key}`)?.value || getSettings().defaultCodexDir || "";
  const buildArgs = () => {
    const args = [...cliArgs];
    const dir = dirOf();
    if (dir) args.push("--codex-dir", dir);
    return args;
  };

  if (hasPreview) {
    card.querySelector(`#preview-${key}`).addEventListener("click", async () => {
      const result = card.querySelector(`#result-${key}`);
      result.innerHTML = `<span class="spinner"></span>`;
      try {
        const output = await cliRun([...buildArgs(), "--lang", "en"]);
        const parsed = parseUninstallPreview(output.stdout);
        result.innerHTML = `
          ${parsed.plans.length ? `
            <div class="plan-list">
              ${parsed.plans.map((p) => `
                <div class="plan-item">
                  <div class="plan-dir">${escapeHtml(p.dir)}</div>
                  <div>${escapeHtml(p.summary)}</div>
                  ${p.detail ? `<div class="dim">${escapeHtml(p.detail)}</div>` : ""}
                </div>`).join("")}
            </div>` : ""}
          <pre class="log" style="margin-top:10px">${escapeHtml(output.stdout)}${output.stderr ? "\n" + escapeHtml(output.stderr) : ""}</pre>`;
      } catch (err) {
        result.innerHTML = `<div class="warning-block danger-block">${escapeHtml(err?.message || String(err))}</div>`;
      }
    });
  }

  card.querySelector(`#exec-${key}`).addEventListener("click", async () => {
    if (busy) return;
    const ok = await confirmModal({
      title,
      body: dirOf() || t("manage.allDirs"),
      confirmText: t("manage.execute"),
      danger: key !== "restore-hooks",
    });
    if (!ok) return;

    busy = true;
    setOperationInProgress(true);
    const result = card.querySelector(`#result-${key}`);
    const execBtn = card.querySelector(`#exec-${key}`);
    execBtn.disabled = true;
    execBtn.innerHTML = `<span class="spinner"></span> ${escapeHtml(t("manage.running"))}`;
    result.innerHTML = "";

    try {
      const runArgs = buildArgs();
      const output = noYes
        ? await cliRun([...runArgs, "--lang", "en"])
        : await cliExecute(runArgs);
      if (output.timed_out) {
        result.innerHTML = `<div class="warning-block danger-block" style="margin-top:12px">${escapeHtml(t("deploy.timedOut"))}</div>`;
        toast(t("manage.failed"), { type: "error" });
      } else if (output.exit_code === 0) {
        result.innerHTML = `<div class="result-block success-block" style="margin-top:12px">
          <strong>✓ ${escapeHtml(t("manage.done"))}</strong>
          <details style="margin-top:8px">
            <summary class="step-label" style="cursor:pointer">${escapeHtml(t("manage.result"))}</summary>
            <pre class="log" style="margin-top:8px">${escapeHtml(output.stdout)}</pre>
          </details>
        </div>`;
        toast(t("manage.done"), { type: "success" });
        setLastStatus(null); // 失效快照，触发下次刷新
      } else {
        result.innerHTML = `<div class="result-block danger-block" style="margin-top:12px">
          <strong>${escapeHtml(t("manage.failed"))} (exit ${output.exit_code})</strong>
          <pre class="log" style="margin-top:8px">${escapeHtml(output.stderr || output.stdout)}</pre>
        </div>`;
        toast(t("manage.failed"), { type: "error" });
      }
    } catch (err) {
      result.innerHTML = `<div class="warning-block danger-block" style="margin-top:12px">${escapeHtml(err?.message || String(err))}</div>`;
      toast(t("manage.failed"), { type: "error" });
    } finally {
      busy = false;
      setOperationInProgress(false);
      execBtn.disabled = false;
      execBtn.textContent = t("manage.execute");
    }
  });

  return card;
}

function iconUndo() {
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/></svg>`;
}
function iconHook() {
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 7a3 3 0 1 0-3-3"/><path d="M15 7v6a5 5 0 0 1-10 0"/><circle cx="5" cy="17" r="2"/></svg>`;
}
function iconZap() {
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`;
}

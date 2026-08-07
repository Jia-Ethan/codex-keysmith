// views/deploy.js — 部署向导（M2）：选择内容 → 预览 → 确认执行

import { open } from "@tauri-apps/plugin-dialog";
import { fetchDryRun, cliExecute } from "../lib/api.js";
import { getCliInfo, setOperationInProgress } from "../lib/store.js";
import { t } from "../lib/i18n.js";
import { escapeHtml, el } from "../lib/dom.js";
import { toast } from "../lib/toast.js";
import { confirmModal } from "../lib/modal.js";

const state = {
  step: 1,
  source: "bundled",   // "bundled" | "file"
  filePath: "",
  name: "",
  codexDir: "",
  skipHooks: false,
  preview: null,
  busy: false,
};

export function loadDeploy() {
  state.step = 1;
  state.preview = null;
  state.busy = false;
  render();
}

function render() {
  const root = document.getElementById("view-deploy");
  root.innerHTML = "";
  root.appendChild(el("div", { class: "view-header" }, `
    <div>
      <h1 class="view-title anim-fade-up">${escapeHtml(t("deploy.title"))}</h1>
      ${renderSteps()}
    </div>`));

  const body = el("div", { class: "wizard-body" });
  root.appendChild(body);

  if (state.step === 1) renderStep1(body);
  else if (state.step === 2) renderStep2(body);
  else renderStep3(body);
}

function renderSteps() {
  const steps = [t("deploy.step1"), t("deploy.step2"), t("deploy.step3")];
  return `<div class="wizard-steps anim-fade-up" style="animation-delay:.05s">
    ${steps.map((s, i) => `
      <div class="wizard-step ${state.step === i + 1 ? "current" : ""} ${state.step > i + 1 ? "done" : ""}">
        <span class="step-num">${state.step > i + 1 ? "✓" : i + 1}</span>
        <span>${escapeHtml(s)}</span>
      </div>${i < steps.length - 1 ? '<div class="step-connector"></div>' : ""}`).join("")}
  </div>`;
}

// ── 步骤 1：选择内容 ─────────────────────────

function renderStep1(body) {
  const cli = getCliInfo();
  if (cli.checked && !cli.path) {
    body.appendChild(el("div", { class: "card-glass warning-block anim-fade-up" },
      escapeHtml(t("dash.noCli"))));
    return;
  }

  const card = el("div", { class: "card-glass anim-fade-up", style: "animation-delay:.1s" });
  card.innerHTML = `
    <div class="step">
      <label class="step-label">${escapeHtml(t("deploy.source"))}</label>
      <div class="radio-cards">
        <label class="radio-card ${state.source === "bundled" ? "selected" : ""}">
          <input type="radio" name="source" value="bundled" ${state.source === "bundled" ? "checked" : ""}>
          <div>
            <div class="radio-card-title">${escapeHtml(t("deploy.sourceBundled"))}</div>
            <div class="radio-card-desc">${escapeHtml(t("deploy.sourceBundledDesc"))}</div>
          </div>
        </label>
        <label class="radio-card ${state.source === "file" ? "selected" : ""}">
          <input type="radio" name="source" value="file" ${state.source === "file" ? "checked" : ""}>
          <div style="flex:1">
            <div class="radio-card-title">${escapeHtml(t("deploy.sourceFile"))}</div>
            <div class="file-row">
              <span class="file-path ${state.filePath ? "" : "dim"}">
                ${state.filePath ? escapeHtml(state.filePath) : escapeHtml(t("deploy.noFile"))}
              </span>
              <button class="btn small" id="pick-file">${escapeHtml(t("deploy.pickFile"))}</button>
            </div>
          </div>
        </label>
      </div>
    </div>
    <div class="step">
      <label class="step-label" for="deploy-name">${escapeHtml(t("deploy.name"))}</label>
      <input type="text" id="deploy-name" value="${escapeHtml(state.name)}"
             placeholder="${escapeHtml(t("deploy.namePlaceholder"))}">
      <div class="field-hint">${escapeHtml(t("deploy.nameHint"))}</div>
    </div>
    <div class="step">
      <label class="step-label" for="deploy-dir">${escapeHtml(t("deploy.targetDir"))}</label>
      <div class="file-row">
        <input type="text" id="deploy-dir" value="${escapeHtml(state.codexDir)}"
               placeholder="${escapeHtml(t("deploy.targetDirPlaceholder"))}" style="flex:1">
        <button class="btn small" id="pick-dir">${escapeHtml(t("deploy.pickDir"))}</button>
      </div>
    </div>
    <details class="step">
      <summary class="step-label" style="cursor:pointer">${escapeHtml(t("deploy.advanced"))}</summary>
      <div class="checkbox-row" style="margin-top:10px">
        <input type="checkbox" id="skip-hooks" ${state.skipHooks ? "checked" : ""}>
        <label for="skip-hooks">${escapeHtml(t("deploy.skipHooks"))}</label>
      </div>
      <div class="field-hint">${escapeHtml(t("deploy.skipHooksHint"))}</div>
    </details>
    <div class="wizard-actions">
      <button class="btn primary" id="to-preview" disabled>${escapeHtml(t("deploy.next"))} →</button>
    </div>`;
  body.appendChild(card);

  const validate = () => {
    const fileOk = state.source === "bundled" || !!state.filePath;
    const skipOk = !state.skipHooks || !!state.codexDir.trim();
    card.querySelector("#to-preview").disabled = !(fileOk && skipOk);
  };

  card.querySelectorAll('input[name="source"]').forEach((r) =>
    r.addEventListener("change", (e) => {
      state.source = e.target.value;
      card.querySelectorAll(".radio-card").forEach((c) => c.classList.remove("selected"));
      e.target.closest(".radio-card").classList.add("selected");
      validate();
    }));

  card.querySelector("#pick-file").addEventListener("click", async (e) => {
    e.preventDefault();
    const picked = await open({
      filters: [{ name: "Markdown", extensions: ["md", "markdown", "txt"] }],
    });
    if (picked) {
      state.filePath = picked;
      state.source = "file";
      render();
    }
  });

  card.querySelector("#pick-dir").addEventListener("click", async (e) => {
    e.preventDefault();
    const picked = await open({ directory: true });
    if (picked) {
      state.codexDir = picked;
      render();
    }
  });

  card.querySelector("#deploy-name").addEventListener("input", (e) => {
    state.name = e.target.value;
    validate();
  });
  card.querySelector("#deploy-dir").addEventListener("input", (e) => {
    state.codexDir = e.target.value;
    validate();
  });
  card.querySelector("#skip-hooks").addEventListener("change", (e) => {
    state.skipHooks = e.target.checked;
    validate();
  });

  card.querySelector("#to-preview").addEventListener("click", () => {
    state.step = 2;
    render();
    runPreview();
  });

  validate();
}

// ── 步骤 2：预览 ─────────────────────────────

function buildDeployArgs() {
  const args = [];
  if (state.source === "file" && state.filePath) args.push("--file", state.filePath);
  if (state.name.trim()) args.push("--name", state.name.trim());
  if (state.codexDir.trim()) args.push("--codex-dir", state.codexDir.trim());
  if (state.skipHooks) args.push("--skip-hooks-isolation");
  return args;
}

async function runPreview() {
  const body = document.querySelector("#view-deploy .wizard-body");
  if (!body) return;
  body.innerHTML = `<div class="card-glass anim-fade-up" style="padding:32px;text-align:center">
    <span class="spinner"></span> ${escapeHtml(t("deploy.runningPreview"))}</div>`;

  try {
    state.preview = await fetchDryRun(buildDeployArgs());
  } catch (err) {
    state.preview = { error: err?.message || String(err) };
  }
  if (state.step === 2) render();
}

function renderStep2(body) {
  const p = state.preview;
  if (!p) return; // runPreview 会填充

  if (p.error) {
    body.appendChild(el("div", { class: "card-glass warning-block anim-fade-up" },
      `<strong>${escapeHtml(t("dash.error"))}</strong><pre class="log" style="margin-top:10px">${escapeHtml(p.error)}</pre>`));
    body.appendChild(renderStep2Actions(false));
    return;
  }

  const card = el("div", { class: "card-glass anim-fade-up" });
  let html = "";

  if (p.promptSource) {
    html += `<div class="kv" style="margin-bottom:16px">
      <dt>${escapeHtml(t("deploy.promptSource"))}</dt><dd>${escapeHtml(p.promptSource.source)}</dd>
      <dt>${escapeHtml(t("deploy.sha256"))}</dt><dd>${escapeHtml(p.promptSource.sha256)}</dd>
    </div>`;
  }

  // [Behavior notice] 必须原样展示 — 项目安全承诺
  if (p.behaviorNotice) {
    html += `<div class="behavior-notice" role="note">
      <div class="behavior-notice-title">⚠ ${escapeHtml(t("deploy.behaviorNotice"))}</div>
      <div>${escapeHtml(p.behaviorNotice)}</div>
    </div>`;
  }

  if (p.blockers.length) {
    html += `<div class="warning-block danger-block">
      <strong>${escapeHtml(t("deploy.blockers"))}</strong><br>
      ${p.blockers.map((b) => escapeHtml(b)).join("<br>")}
    </div>`;
  }

  html += `<div class="step-label">${escapeHtml(t("deploy.timeline"))}</div>
    <div class="timeline">
      ${p.targets.map((target) => `
        <div class="timeline-target">${escapeHtml(target.dir)}</div>
        ${target.actions.map((a) => `
          <div class="timeline-item ${a.startsWith("[Blocked]") ? "blocked" : a.startsWith("No hooks") ? "warn" : ""}">
            <span class="timeline-dot"></span>
            <span class="timeline-text">${escapeHtml(a)}</span>
          </div>`).join("")}
      `).join("")}
    </div>
    <details style="margin-top:16px">
      <summary class="step-label" style="cursor:pointer">${escapeHtml(t("deploy.rawOutput"))}</summary>
      <pre class="log" style="margin-top:10px">${escapeHtml(p.raw)}</pre>
    </details>`;

  card.innerHTML = html;
  body.appendChild(card);
  body.appendChild(renderStep2Actions(p.blockers.length === 0));
}

function renderStep2Actions(canProceed) {
  const row = el("div", { class: "wizard-actions anim-fade-up", style: "animation-delay:.1s" });
  row.innerHTML = `
    <button class="btn" id="back-1">← ${escapeHtml(t("deploy.back"))}</button>
    <button class="btn primary" id="to-confirm" ${canProceed ? "" : "disabled"}>
      ${escapeHtml(t("deploy.next"))} →</button>`;
  row.querySelector("#back-1").addEventListener("click", () => {
    state.step = 1;
    state.preview = null;
    render();
  });
  row.querySelector("#to-confirm")?.addEventListener("click", () => {
    state.step = 3;
    render();
  });
  return row;
}

// ── 步骤 3：确认执行 ──────────────────────────

function renderStep3(body) {
  const card = el("div", { class: "card-glass anim-fade-up" });
  card.innerHTML = `
    <div class="confirm-panel">
      <p class="confirm-hint">${escapeHtml(t("deploy.confirmHint"))}</p>
      <button class="btn deploy-confirm" id="do-deploy">${escapeHtml(t("deploy.confirmDeploy"))}</button>
    </div>
    <div id="deploy-result"></div>`;
  body.appendChild(card);

  const actions = el("div", { class: "wizard-actions anim-fade-up", style: "animation-delay:.08s" });
  actions.innerHTML = `<button class="btn" id="back-2">← ${escapeHtml(t("deploy.back"))}</button>`;
  actions.querySelector("#back-2").addEventListener("click", () => {
    state.step = 2;
    render();
  });
  body.appendChild(actions);

  card.querySelector("#do-deploy").addEventListener("click", async () => {
    const ok = await confirmModal({
      title: t("deploy.confirmDeploy"),
      body: state.codexDir || t("manage.allDirs"),
      confirmText: t("deploy.confirmDeploy"),
      danger: true,
    });
    if (!ok) return;
    await doDeploy(body);
  });
}

async function doDeploy(body) {
  state.busy = true;
  setOperationInProgress(true);
  const btn = body.querySelector("#do-deploy");
  const resultBox = body.querySelector("#deploy-result");
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> ${escapeHtml(t("deploy.deploying"))}`;
  body.querySelector("#back-2")?.setAttribute("disabled", "");

  try {
    const output = await cliExecute(buildDeployArgs());
    if (output.timed_out) {
      resultBox.innerHTML = `<div class="warning-block danger-block" style="margin-top:16px">
        ${escapeHtml(t("deploy.timedOut"))}</div>`;
      toast(t("manage.failed"), { type: "error" });
    } else if (output.exit_code === 0) {
      resultBox.innerHTML = `<div class="result-block success-block" style="margin-top:16px">
        <strong>✓ ${escapeHtml(t("deploy.success"))}</strong>
        <pre class="log" style="margin-top:10px">${escapeHtml(output.stdout)}</pre>
      </div>`;
      toast(t("deploy.success"), { type: "success" });
      setTimeout(() => {
        setOperationInProgress(false);
        document.querySelector('[data-view="dashboard"]')?.click();
      }, 1200);
      return;
    } else {
      resultBox.innerHTML = `<div class="result-block danger-block" style="margin-top:16px">
        <strong>${escapeHtml(t("deploy.failed"))} (exit ${output.exit_code})</strong>
        <pre class="log" style="margin-top:10px">${escapeHtml(output.stderr || output.stdout)}</pre>
      </div>`;
      toast(t("deploy.failed"), { type: "error" });
    }
  } catch (err) {
    resultBox.innerHTML = `<div class="warning-block danger-block" style="margin-top:16px">
      ${escapeHtml(err?.message || String(err))}</div>`;
    toast(t("deploy.failed"), { type: "error" });
  } finally {
    state.busy = false;
    setOperationInProgress(false);
    btn.disabled = false;
    btn.textContent = t("deploy.confirmDeploy");
    body.querySelector("#back-2")?.removeAttribute("disabled");
  }
}

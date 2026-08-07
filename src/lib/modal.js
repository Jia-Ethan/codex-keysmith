// lib/modal.js — 确认对话框（危险操作用）
// confirmModal({ title, body, confirmText, danger }) → Promise<boolean>

import { t } from "./i18n.js";

export function confirmModal({ title, body, confirmText, danger = false }) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true" aria-label="${escapeAttr(title)}">
        <div class="modal-title">${escapeHtml(title)}</div>
        ${body ? `<div class="modal-body">${escapeHtml(body)}</div>` : ""}
        <div class="modal-actions">
          <button class="btn" data-act="cancel">${escapeHtml(t("common.cancel"))}</button>
          <button class="btn ${danger ? "danger-solid" : "primary"}" data-act="confirm">
            ${escapeHtml(confirmText || t("common.confirm"))}
          </button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("show"));

    const close = (result) => {
      overlay.classList.remove("show");
      setTimeout(() => overlay.remove(), 200);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onKey = (e) => {
      if (e.key === "Escape") close(false);
    };
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(false);
    });
    overlay.querySelector('[data-act="cancel"]').addEventListener("click", () => close(false));
    overlay.querySelector('[data-act="confirm"]').addEventListener("click", () => close(true));
    overlay.querySelector('[data-act="confirm"]').focus();
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}

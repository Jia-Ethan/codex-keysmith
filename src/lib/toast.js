// lib/toast.js — 非阻塞通知（右上角堆叠）

let container = null;

function ensureContainer() {
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    container.setAttribute("role", "status");
    container.setAttribute("aria-live", "polite");
    document.body.appendChild(container);
  }
  return container;
}

/** type: "info" | "success" | "error" | "warning" */
export function toast(message, { type = "info", duration = 4000 } = {}) {
  const box = ensureContainer();
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  box.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  const dismiss = () => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  };
  el.addEventListener("click", dismiss);
  setTimeout(dismiss, duration);
}

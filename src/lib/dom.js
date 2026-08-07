// lib/dom.js — DOM 工具

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/** 创建元素：el("div", { class: "card" }, htmlString | Node[]) */
export function el(tag, attrs = {}, children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  if (typeof children === "string") node.innerHTML = children;
  else if (Array.isArray(children)) children.forEach((c) => c && node.appendChild(c));
  return node;
}

/** 纯浏览器环境（无 Tauri IPC）识别：invoke 不可用时的典型报错 */
export function isTauriMissing(err) {
  return /invoke/i.test(err?.message || "");
}

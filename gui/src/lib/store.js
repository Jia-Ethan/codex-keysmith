// lib/store.js — 跨视图共享状态（React 迁移版，useSyncExternalStore 兼容）
// 保存：CLI 检测结果、status 快照、操作锁、当前视图

let state = {
  cliInfo: { path: null, version: "", runtime: "", checked: false },
  lastStatus: null,
  operationInProgress: false,
  view: "dashboard",
};

const listeners = new Set();

function emit() {
  listeners.forEach((fn) => fn());
}

export function getState() {
  return state;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setCliInfo(patch) {
  state = { ...state, cliInfo: { ...state.cliInfo, ...patch } };
  emit();
}

export function setLastStatus(lastStatus) {
  state = { ...state, lastStatus };
  emit();
}

export function setOperationInProgress(operationInProgress) {
  state = { ...state, operationInProgress };
  emit();
}

/** 供非 React 环境（窗口关闭拦截）同步读取操作锁 */
export function isOperationInProgressRef() {
  return state.operationInProgress;
}

export function setView(view) {
  // 离开 manage 时失效快照（与原逻辑一致）
  const lastStatus = view === "manage" ? state.lastStatus : null;
  state = { ...state, view, lastStatus };
  emit();
}

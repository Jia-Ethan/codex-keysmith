// lib/store.js — 跨视图共享状态（React 迁移版，useSyncExternalStore 兼容）
// 保存：CLI 检测结果、status 快照、操作锁、当前视图

let state = {
  cliInfo: { path: null, version: "", runtime: "", error: null, checked: false },
  lastStatus: null,
  operationOwner: null,
  operationInProgress: false,
  view: "dashboard",
};
let cliCheckGeneration = 0;

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
  cliCheckGeneration += 1;
  updateCliInfo(patch);
}

function updateCliInfo(patch) {
  state = { ...state, cliInfo: { ...state.cliInfo, ...patch } };
  emit();
}

export function beginCliCheck() {
  const generation = ++cliCheckGeneration;
  updateCliInfo({ path: null, version: "", runtime: "", error: null, checked: false });
  return generation;
}

export function completeCliCheck(generation, patch) {
  if (generation !== cliCheckGeneration) return false;
  updateCliInfo(patch);
  return true;
}

export function setLastStatus(lastStatus) {
  state = { ...state, lastStatus };
  emit();
}

export function beginOperation(owner) {
  if (!owner || state.operationOwner) return false;
  state = { ...state, operationOwner: owner, operationInProgress: true };
  emit();
  return true;
}

export function endOperation(owner) {
  if (!owner || state.operationOwner !== owner) return false;
  state = { ...state, operationOwner: null, operationInProgress: false };
  emit();
  return true;
}

/** 供非 React 环境（窗口关闭拦截）同步读取操作锁 */
export function isOperationInProgressRef() {
  return Boolean(state.operationOwner);
}

export function setView(view) {
  if (state.operationOwner && view !== state.view) return false;
  // 离开 manage 时失效快照（与原逻辑一致）
  const lastStatus = view === "manage" ? state.lastStatus : null;
  state = { ...state, view, lastStatus };
  emit();
  return true;
}

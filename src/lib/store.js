// lib/store.js — 跨视图共享状态（CLI 检测结果、status 快照、操作锁）

let cliInfo = { path: null, version: "", pythonVersion: "", checked: false };
let lastStatus = null;
let operationInProgress = false;
const listeners = new Set();

export function getCliInfo() {
  return { ...cliInfo };
}

export function setCliInfo(patch) {
  cliInfo = { ...cliInfo, ...patch };
  notify();
}

export function getLastStatus() {
  return lastStatus;
}

export function setLastStatus(status) {
  lastStatus = status;
  notify();
}

export function isOperationInProgress() {
  return operationInProgress;
}

export function setOperationInProgress(v) {
  operationInProgress = v;
  notify();
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  listeners.forEach((fn) => fn());
}

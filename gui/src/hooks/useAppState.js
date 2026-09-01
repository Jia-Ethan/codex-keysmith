import { useSyncExternalStore } from "react";
import { getState, subscribe } from "@/lib/store";

/** 订阅全局 store（CLI、status、操作租约、退出队列与当前视图）。 */
export function useAppState() {
  return useSyncExternalStore(subscribe, getState, getState);
}

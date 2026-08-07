import { useSyncExternalStore } from "react";
import { getState, subscribe } from "@/lib/store";

/** 订阅全局 store（cliInfo / lastStatus / operationInProgress / view） */
export function useAppState() {
  return useSyncExternalStore(subscribe, getState, getState);
}

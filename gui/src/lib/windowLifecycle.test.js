import { afterEach, describe, expect, it, vi } from "vitest";
import {
  beginOperation,
  endOperation,
  getState,
  resetOperationCoordinatorForTests,
} from "./store.js";
import { installWindowCloseLifecycle } from "./windowLifecycle.js";

afterEach(() => {
  resetOperationCoordinatorForTests();
});

function createWindow() {
  let closeHandler = null;
  const unlisten = vi.fn();
  const appWindow = {
    destroy: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    onCloseRequested: vi.fn((handler) => {
      closeHandler = handler;
      return Promise.resolve(unlisten);
    }),
  };
  return {
    appWindow,
    unlisten,
    dispatchClose: (event) => closeHandler(event),
  };
}

const flushPromises = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

describe("主窗口关闭生命周期", () => {
  it("空闲关闭也先建立屏障并显式销毁窗口", async () => {
    const { appWindow, dispatchClose } = createWindow();
    const onExitQueued = vi.fn();
    const lifecycle = installWindowCloseLifecycle({ appWindow, onExitQueued });
    await lifecycle.ready;
    const event = { preventDefault: vi.fn() };

    dispatchClose(event);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(onExitQueued).not.toHaveBeenCalled();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();
    await flushPromises();
    expect(appWindow.destroy).toHaveBeenCalledOnce();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();
    lifecycle.dispose();
  });

  it("写操作期间阻止原生关闭，最后一个租约结束后只销毁一次", async () => {
    const { appWindow, dispatchClose } = createWindow();
    const onExitQueued = vi.fn();
    const lifecycle = installWindowCloseLifecycle({ appWindow, onExitQueued });
    await lifecycle.ready;
    const first = beginOperation();
    const second = beginOperation();
    const event = { preventDefault: vi.fn() };

    dispatchClose(event);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(onExitQueued).toHaveBeenCalledOnce();
    expect(endOperation(first)).toBe(true);
    expect(appWindow.destroy).not.toHaveBeenCalled();
    expect(endOperation(second)).toBe(true);
    await flushPromises();
    expect(appWindow.destroy).toHaveBeenCalledOnce();
    expect(appWindow.close).not.toHaveBeenCalled();
    expect(getState().pendingExit).toBe(true);
    expect(beginOperation()).toBeNull();
    lifecycle.dispose();
  });

  it("destroy 失败时回退到 close", async () => {
    const { appWindow, dispatchClose } = createWindow();
    appWindow.destroy.mockRejectedValue(new Error("destroy failed"));
    const fallbackEvent = { preventDefault: vi.fn() };
    appWindow.close.mockImplementation(async () => dispatchClose(fallbackEvent));
    const requestExit = vi.fn((exit) => {
      void exit();
      return true;
    });
    const lifecycle = installWindowCloseLifecycle({ appWindow, requestExit });
    await lifecycle.ready;

    dispatchClose({ preventDefault: vi.fn() });
    await flushPromises();

    expect(appWindow.destroy).toHaveBeenCalledOnce();
    expect(appWindow.close).toHaveBeenCalledOnce();
    expect(fallbackEvent.preventDefault).not.toHaveBeenCalled();
    lifecycle.dispose();
  });

  it("destroy 与 close 都失败时报告错误", async () => {
    const { appWindow, dispatchClose } = createWindow();
    appWindow.destroy.mockRejectedValue(new Error("destroy failed"));
    appWindow.close.mockRejectedValue(new Error("close failed"));
    const onError = vi.fn();
    const requestExit = vi.fn((exit) => {
      void exit().catch(() => {});
      return true;
    });
    const lifecycle = installWindowCloseLifecycle({ appWindow, requestExit, onError });
    await lifecycle.ready;

    dispatchClose({ preventDefault: vi.fn() });
    await flushPromises();

    expect(onError).toHaveBeenCalledWith({
      phase: "exit",
      error: expect.any(AggregateError),
    });
    lifecycle.dispose();
  });

  it("监听注册失败会报告，不再静默吞掉", async () => {
    const registrationError = new Error("listener unavailable");
    const onError = vi.fn();
    const appWindow = {
      onCloseRequested: vi.fn().mockRejectedValue(registrationError),
    };

    const lifecycle = installWindowCloseLifecycle({ appWindow, onError });
    await lifecycle.ready;

    expect(onError).toHaveBeenCalledWith({
      phase: "registration",
      error: registrationError,
    });
  });

  it("注册完成前卸载时立即释放迟到的 listener", async () => {
    let resolveRegistration;
    const unlisten = vi.fn();
    const appWindow = {
      onCloseRequested: vi.fn(() => new Promise((resolve) => {
        resolveRegistration = resolve;
      })),
    };
    const lifecycle = installWindowCloseLifecycle({ appWindow });
    await Promise.resolve();

    lifecycle.dispose();
    resolveRegistration(unlisten);
    await lifecycle.ready;

    expect(unlisten).toHaveBeenCalledOnce();
  });

  it("迟到 listener 的卸载失败会报告 cleanup 错误", async () => {
    let resolveRegistration;
    const cleanupError = new Error("unlisten failed");
    const unlisten = vi.fn(() => {
      throw cleanupError;
    });
    const onError = vi.fn();
    const appWindow = {
      onCloseRequested: vi.fn(() => new Promise((resolve) => {
        resolveRegistration = resolve;
      })),
    };
    const lifecycle = installWindowCloseLifecycle({ appWindow, onError });
    await Promise.resolve();

    lifecycle.dispose();
    resolveRegistration(unlisten);
    await lifecycle.ready;

    expect(onError).toHaveBeenCalledWith({ phase: "cleanup", error: cleanupError });
  });
});

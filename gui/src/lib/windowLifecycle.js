import { requestExitWhenIdle } from "./store.js";

/** 注册主窗口关闭保护，并处理异步注册/卸载竞态。 */
export function installWindowCloseLifecycle({
  appWindow,
  requestExit = requestExitWhenIdle,
  onExitQueued = () => {},
  onError = () => {},
}) {
  let disposed = false;
  let unlisten = null;
  let explicitExitInProgress = false;

  const reportError = (phase, error) => {
    if (!disposed) onError({ phase, error });
  };

  const destroyWindow = async () => {
    explicitExitInProgress = true;
    try {
      try {
        await appWindow.destroy();
      } catch (destroyError) {
        try {
          await appWindow.close();
        } catch (closeError) {
          throw new AggregateError(
            [destroyError, closeError],
            "Failed to destroy or close the application window",
          );
        }
      }
    } catch (error) {
      reportError("exit", error);
      throw error;
    } finally {
      explicitExitInProgress = false;
    }
  };

  const ready = Promise.resolve()
    .then(() => appWindow.onCloseRequested((event) => {
      if (explicitExitInProgress) return;
      let exitDisposition;
      try {
        exitDisposition = requestExit(destroyWindow);
      } catch (error) {
        event.preventDefault();
        reportError("request", error);
        return;
      }
      event.preventDefault();
      if (exitDisposition === "queued" || exitDisposition === true) onExitQueued();
    }))
    .then((disposeListener) => {
      if (typeof disposeListener !== "function") {
        throw new TypeError("onCloseRequested did not return an unlisten function");
      }
      if (disposed) {
        try {
          disposeListener();
        } catch (error) {
          onError({ phase: "cleanup", error });
        }
      } else {
        unlisten = disposeListener;
      }
    })
    .catch((error) => reportError("registration", error));

  return {
    ready,
    dispose() {
      disposed = true;
      if (!unlisten) return;
      try {
        unlisten();
      } catch (error) {
        onError({ phase: "cleanup", error });
      } finally {
        unlisten = null;
      }
    },
  };
}

const COMMIT_PATTERN = /^[0-9a-f]{40}$/;

export function normalizeBuildInfo(value = {}) {
  const desktopVersion =
    typeof value.desktopVersion === "string" && value.desktopVersion
      ? value.desktopVersion
      : "unknown";
  const sourceCommit =
    typeof value.sourceCommit === "string" && COMMIT_PATTERN.test(value.sourceCommit)
      ? value.sourceCommit
      : null;

  return Object.freeze({
    desktopVersion,
    channel: sourceCommit ? "candidate" : "development",
    sourceCommit,
  });
}

const injectedBuildInfo =
  typeof __CODEX_KEYSMITH_BUILD_INFO__ === "undefined"
    ? {}
    : __CODEX_KEYSMITH_BUILD_INFO__;

export const buildInfo = normalizeBuildInfo(injectedBuildInfo);

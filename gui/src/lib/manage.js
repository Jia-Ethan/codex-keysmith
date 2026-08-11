import { gatePreview, parseUninstallPreview } from "./parser.js";

export function buildRestoreHooksPreview(directories, targetDir = "") {
  const scoped = targetDir
    ? directories.filter((directory) => directory.path === targetDir)
    : directories;
  const seen = new Set();
  const plans = scoped
    .filter((directory) => directory.hooksStatus === "restorable")
    .filter((directory) => {
      if (!directory.path || seen.has(directory.path)) return false;
      seen.add(directory.path);
      return true;
    })
    .map((directory) => ({
      dir: directory.path,
      kind: "restore-hooks",
      summary: null,
      detail: null,
    }));

  return {
    gate: plans.length > 0
      ? { ok: true }
      : { ok: false, reason: "no-restorable" },
    parsed: { plans, blockers: [], semanticComplete: plans.length > 0 },
    output: null,
  };
}

export async function prepareManagementPreview({
  operation,
  directories,
  targetDir,
  args,
  runCli,
}) {
  if (operation === "restore-hooks") {
    return buildRestoreHooksPreview(directories, targetDir);
  }

  const output = await runCli(args);
  const parsed = parseUninstallPreview(output.stdout);
  return { gate: gatePreview(output, parsed), parsed, output };
}

export function isManagementPreviewValid(preview, targetKey, statusRevision) {
  return Boolean(
    preview
      && preview.dirKey === targetKey
      && preview.statusRevision === statusRevision
      && preview.gate?.ok,
  );
}

export function shouldRefreshManagementStatus(operation, output, attemptStarted = false) {
  if (attemptStarted) return true;
  if (operation === "restore-hooks") {
    return (output?.attempted?.length ?? 0) > 0;
  }
  return Boolean(output);
}

export async function executeRestoreHooksPlans(plans, runCli) {
  const results = [];
  for (const plan of plans) {
    try {
      const output = await runCli(
        ["--restore-hooks", "--codex-dir", plan.dir, "--lang", "en"],
        120_000,
      );
      results.push({ dir: plan.dir, error: null, ...output });
      if (output.timed_out || output.exit_code !== 0) break;
    } catch (error) {
      results.push({
        dir: plan.dir,
        stdout: "",
        stderr: error?.message || String(error),
        exit_code: 1,
        timed_out: false,
        error: error?.message || String(error),
      });
      break;
    }
  }

  const failed = results.find((result) => result.timed_out || result.exit_code !== 0);
  const attempted = results.map((result) => result.dir);
  const succeeded = results
    .filter((result) => !result.timed_out && result.exit_code === 0)
    .map((result) => result.dir);
  return {
    results,
    attempted,
    succeeded,
    partial: succeeded.length > 0 && succeeded.length < attempted.length,
    text: formatRestoreHooksResults(results),
    stdout: results.map((result) => result.stdout).filter(Boolean).join("\n"),
    stderr: results.map((result) => result.stderr).filter(Boolean).join("\n"),
    exit_code: failed?.exit_code ?? 0,
    timed_out: failed?.timed_out ?? false,
  };
}

function formatRestoreHooksResults(results) {
  return results.map((result) => {
    const details = [result.stdout, result.stderr].filter((value) => value?.trim());
    if (result.timed_out && details.length === 0) details.push("Timed out");
    if (!result.timed_out && result.exit_code !== 0 && details.length === 0) {
      details.push(`Failed with exit code ${result.exit_code}`);
    }
    return [`[${result.dir}]`, ...details].join("\n");
  }).join("\n\n");
}

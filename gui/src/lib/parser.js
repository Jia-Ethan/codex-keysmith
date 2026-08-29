// lib/parser.js — CLI 文本输出解析器（React 迁移版）
// 解析规范见 SPEC.md §5。所有解析器只认 --lang en 的输出。
//
// 与 vanilla 版差异（对应必修问题 1/2）：
//  - parseDryRun 不再承担门禁；新增 gatePreview()，非零退出/超时/空输出
//    一律返回 { ok: false } 并携带 stderr，由视图层阻断流程。
//  - FILE_LINE_RE 放开类型白名单，任何 kind 都会被捕获；非 regular/missing
//    一律归一化为 "other" 并升级为显眼 warning，绝不静默丢弃节点。

// 文件行：`    <name>: <kind> (<path>)`，kind 任意描述（regular file / missing /
// directory / symbolic link / FIFO / socket / other node 等）
const FILE_LINE_RE = /^ {4}(.+?): ([^()]+) \((.+)\)$/;

const STATUS_HEADER_RE =
  /^\[Status\] Found (\d+) Codex configuration location\(s\) \(read-only inspection\):$/;
const STATUS_DONE_RE =
  /^\[Done\] Status found no blockers; live active\/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed\.$/;
const STATUS_INACTIVE_DONE_RE =
  /^\[Done\] Status recognized (\d+) inactive-by-config location\(s\) and found no other blockers; live active\/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed\.$/;
const STATUS_ERROR_RE =
  /^\[Error\] (\d+) location\(s\) contain conflicts or abnormal nodes\.$/;

const NODE_NAME_MAP = {
  "config.toml": "configToml",
  "gpt-unrestricted.md": "md",
  "gpt5.5-unrestricted.md": "legacyMd",
  "hooks.json": "hooks",
  "hooks.json.disabled": "hooksDisabled",
  "deployment manifest": "manifest",
};
const REQUIRED_STATUS_NODE_KEYS = Object.values(NODE_NAME_MAP);
const REQUIRED_STATUS_FIELDS = [
  "modelInstructionsFile",
  "residue",
];
const VALID_ACTIVATIONS = new Set([
  "active",
  "inactive-by-config",
  "conflict",
  "not-installed",
]);
const VALID_LEGACY_MIGRATIONS = new Set(["none", "archive", "unmanaged"]);
const VALID_HOOKS_STATUSES = new Set(["absent", "active", "restorable", "conflict"]);
const VALID_HEALTH_STATUSES = new Set(["healthy", "blocked"]);
const VALID_UNINSTALL_READINESS = new Set(["ready", "blocked", "not-applicable"]);
const VALID_DEPLOYABILITY = new Set(["ready", "blocked"]);

const MANAGEMENT_PREVIEW_SENTINELS = new Set([
  "[Preview] No files were changed; add --yes to confirm uninstall.",
  "[Preview] No files were changed; add --yes to confirm recovery.",
  "[Preview] No files were changed; add --yes to confirm reactivation.",
  "[Preview] No files were changed; add --yes to clean the initializing journal.",
  "[Preview] Cleanup residue was not changed; add --yes to confirm cleanup.",
  "[Preview] Found an empty initializing journal before intent publication; nothing changed. Add --yes to remove it.",
  "[Preview] 终态资源不会回滚；确认清理请添加 --yes。",
  "[Preview] 终态资源不会反向恢复；确认清理请添加 --yes。",
  "[Preview] 业务路径未修改；确认清理初始化日志请添加 --yes。",
]);

function splitCliLines(text) {
  return String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
}

function parseStatusTerminator(line) {
  if (STATUS_DONE_RE.test(line)) {
    return { kind: "done", affectedCount: 0, line };
  }

  const inactiveMatch = line.match(STATUS_INACTIVE_DONE_RE);
  if (inactiveMatch) {
    return { kind: "done", affectedCount: Number(inactiveMatch[1]), line };
  }

  const errorMatch = line.match(STATUS_ERROR_RE);
  if (errorMatch) {
    return { kind: "error", affectedCount: Number(errorMatch[1]), line };
  }

  return null;
}

function statusDirectoryIsComplete(directory) {
  const nodeKeys = Object.keys(directory.nodes);
  if (nodeKeys.length === 0) return directory.errors.length > 0;
  return REQUIRED_STATUS_NODE_KEYS.every((key) => directory.nodes[key])
    && REQUIRED_STATUS_FIELDS.every((field) => directory.seenFields.has(field))
    && statusFieldIsComplete(directory, "activation", VALID_ACTIVATIONS)
    && statusFieldIsComplete(
      directory,
      "legacyMigration",
      VALID_LEGACY_MIGRATIONS,
      true,
    )
    && statusFieldIsComplete(directory, "hooksStatus", VALID_HOOKS_STATUSES, true)
    && statusFieldIsComplete(directory, "health", VALID_HEALTH_STATUSES)
    && statusFieldIsComplete(
      directory,
      "uninstallReadiness",
      VALID_UNINSTALL_READINESS,
    )
    && statusFieldIsComplete(directory, "deployability", VALID_DEPLOYABILITY);
}

function statusFieldIsComplete(directory, field, validValues, allowMissingOnError = false) {
  if (!directory.seenFields.has(field)) {
    return allowMissingOnError && directory.errors.length > 0;
  }
  return validValues.has(directory[field]);
}

/**
 * 解析 --status 输出（SPEC §5.1）
 * 容错原则：遇到不认识的行直接跳过，绝不抛异常导致整页挂掉。
 * 但已识别的节点行如果类型异常，必须保留节点并升级为 warning。
 */
export function parseStatus(stdout, exitCode = null) {
  const result = {
    directories: [],
    declaredDirectoryCount: null,
    terminator: null,
    semanticComplete: false,
    raw: stdout,
  };
  let current = null;
  const lines = splitCliLines(stdout);

  for (const line of lines) {
    const headerMatch = line.match(STATUS_HEADER_RE);
    if (headerMatch) {
      result.declaredDirectoryCount = Number(headerMatch[1]);
      continue;
    }

    const dirMatch = line.match(/^── Status directory: (.+?) ──$/);
    if (dirMatch) {
      current = {
        path: dirMatch[1],
        nodes: {},
        modelInstructionsFile: null,
        activation: "unknown",
        residue: [],
        legacyMigration: "unknown",
        hooksStatus: "unknown",
        health: "unknown",
        uninstallReadiness: "unknown",
        deployability: "unknown",
        warnings: [],
        errors: [],
        seenFields: new Set(),
        abnormalNodes: [], // 类型异常的节点（符号链接/FIFO/socket…），视图层显眼展示
      };
      result.directories.push(current);
      continue;
    }
    if (!current) continue;

    const diagnosticMatch = line.match(/^ {4}\[(Warning|Error)\]\s+(.+)$/);
    if (diagnosticMatch) {
      const [, severity, detail] = diagnosticMatch;
      current.warnings.push(`${severity}: ${detail}`);
      if (severity === "Error") current.errors.push(detail);
      continue;
    }

    const fileMatch = line.match(FILE_LINE_RE);
    if (fileMatch) {
      const [, name, kind, path] = fileMatch;
      const key = NODE_NAME_MAP[name];
      // 必须落在已知节点名上才算节点行；否则 value 带括号的 kv 行
      // （如 Config activation: active (...)）会被误吞。
      if (key) {
        const norm = normalizeKind(kind);
        current.nodes[key] = { kind: norm, path, raw: kind.trim() };
        if (norm === "other") {
          current.abnormalNodes.push({ key, name, kind: kind.trim(), path });
          current.warnings.push(`${name}: unexpected node type "${kind.trim()}"`);
        }
        continue; // 已知节点行已消费，不再落 kv 分支
      }
      // 未知名称的节点行不是受管节点，落入 kv 分支由后续逻辑处理
    }

    const kvMatch = line.match(/^ {4}(.+?): (.+)$/);
    if (!kvMatch) continue;
    const [, label, value] = kvMatch;
    // kv 区内的诊断行：label 形如 "[Error]" / "[Error] hooks.json is a symbolic link
    // and requires manual review"（冒号后路径在 value 里）。必须转成 warning 展示。
    if (label.startsWith("[")) {
      const m = label.match(/^\[(Warning|Error)\]\s*(.*)$/);
      if (m) {
        const detail = [m[2], value].filter(Boolean).join(": ");
        current.warnings.push(`${m[1]}: ${detail}`);
        if (m[1] === "Error") current.errors.push(detail);
      }
      continue;
    }
    // Hooks restore 是提示行，但仍完整表达 restorable/conflict 状态。
    if (label === "Hooks restore") {
      current.seenFields.add("hooksStatus");
      current.hooksStatus = firstToken(value) === "available"
        ? "restorable"
        : parseHooks(value);
      continue;
    }

    switch (label) {
      case "model_instructions_file":
        current.seenFields.add("modelInstructionsFile");
        current.modelInstructionsFile =
          value === "<unset or unrecognized>" ? null : value;
        break;
      case "Config activation":
        current.seenFields.add("activation");
        current.activation = parseActivation(value);
        break;
      case "Transaction residue":
        current.seenFields.add("residue");
        current.residue =
          value === "none" ? [] : value.split(", ").filter(Boolean);
        break;
      case "Legacy migration":
        current.seenFields.add("legacyMigration");
        current.legacyMigration = parseLegacy(value);
        break;
      case "Hooks status":
        current.seenFields.add("hooksStatus");
        current.hooksStatus = parseHooks(value);
        break;
      case "Structural health":
        current.seenFields.add("health");
        current.health = parseKnownToken(value, VALID_HEALTH_STATUSES);
        break;
      case "Uninstall readiness":
        current.seenFields.add("uninstallReadiness");
        current.uninstallReadiness = parseKnownToken(value, VALID_UNINSTALL_READINESS);
        break;
      case "Deployability":
        current.seenFields.add("deployability");
        current.deployability = parseKnownToken(value, VALID_DEPLOYABILITY);
        break;
      default:
        if (value.startsWith("[Warning]")) {
          current.warnings.push(value.replace(/^\[Warning\] /, ""));
        }
    }
  }

  const lastLine = [...lines].reverse().find((line) => line.trim()) ?? "";
  result.terminator = parseStatusTerminator(lastLine);

  const countMatches =
    result.declaredDirectoryCount !== null
    && result.declaredDirectoryCount === result.directories.length;
  const directoryBlocksComplete =
    result.directories.length > 0
    && result.directories.every(statusDirectoryIsComplete);
  const invalidDirectoryCount = result.directories.filter(
    (directory) => directory.errors.length > 0
      || directory.activation === "conflict"
      || directory.health === "blocked",
  ).length;
  const inactiveDirectoryCount = result.directories.filter(
    (directory) => directory.activation === "inactive-by-config",
  ).length;
  const parsedAffectedCount = result.terminator?.kind === "error"
    ? invalidDirectoryCount
    : inactiveDirectoryCount;
  const affectedCountMatches =
    result.terminator !== null
    && result.terminator.affectedCount === parsedAffectedCount;
  const terminatorMatchesDirectoryStates = result.terminator?.kind === "error"
    ? invalidDirectoryCount > 0
    : invalidDirectoryCount === 0;
  const terminatorMatchesExitCode =
    exitCode === null
    || (exitCode === 0
      ? result.terminator?.kind === "done"
      : result.terminator?.kind === "error");
  result.semanticComplete =
    countMatches
    && directoryBlocksComplete
    && affectedCountMatches
    && terminatorMatchesDirectoryStates
    && terminatorMatchesExitCode;

  for (const directory of result.directories) delete directory.seenFields;

  return result;
}

/**
 * 解析 --dry-run 输出（SPEC §5.2）
 * 产出：promptSource / behaviorNotice / targets[].actions / blockers / warnings
 */
export function parseDryRun(stdout) {
  const result = {
    promptSource: null,
    behaviorNotice: null,
    targets: [],
    blockers: [],
    warnings: [],
    semanticComplete: false,
    raw: stdout,
  };
  let currentTarget = null;

  for (const line of splitCliLines(stdout)) {
    const promptMatch = line.match(/^\[Prompt\] Source: (.+?); SHA-256: ([0-9a-f]+)$/);
    if (promptMatch) {
      const source = promptMatch[1];
      result.promptSource = {
        kind: source.startsWith("bundled") ? "bundled" : "external",
        source,
        sha256: promptMatch[2],
      };
      continue;
    }

    if (line.startsWith("[Behavior notice]")) {
      result.behaviorNotice = line.replace(/^\[Behavior notice\] /, "");
      continue;
    }

    const targetMatch = line.match(/^ {2}Target: (.+)$/);
    if (targetMatch) {
      currentTarget = { dir: targetMatch[1], actions: [] };
      result.targets.push(currentTarget);
      continue;
    }

    const actionMatch = line.match(/^ {4}→ (.+)$/);
    if (actionMatch && currentTarget) {
      const action = actionMatch[1];
      if (action.startsWith("[Blocked]")) {
        result.blockers.push(action);
      } else if (action.startsWith("No hooks.json detected")) {
        result.warnings.push(action);
      }
      currentTarget.actions.push(action);
      continue;
    }

    if (line.startsWith("[Error]")) {
      result.blockers.push(line.replace(/^\[Error\] /, ""));
    }
  }

  result.semanticComplete = Boolean(
    result.promptSource
      && result.targets.length > 0
      && result.targets.every((target) => target.actions.length > 0),
  );

  return result;
}

/**
 * 预览门禁（问题 1 修复）：在执行任何写操作前，对 dry-run / 预览结果做
 * 硬性校验。任何失败信号都会阻断流程，绝不放行到确认步骤。
 *
 * @param {{stdout: string, stderr: string, exit_code: number, timed_out: boolean}} output 原始 CLI 输出
 * @param {object} parsed parseDryRun / parseUninstallPreview 的结果
 * @returns {{ ok: boolean, reason?: "timeout"|"exit"|"empty"|"blockers"|"unrecognized", detail?: string }}
 */
export function gatePreview(output, parsed) {
  if (output.timed_out) {
    return { ok: false, reason: "timeout", detail: output.stderr || output.stdout };
  }
  if (output.exit_code !== 0) {
    // 部分错误路径只写 stdout（如 --name 校验失败），两处都要带上
    return {
      ok: false,
      reason: "exit",
      detail: [output.stderr, output.stdout].filter((s) => s?.trim()).join("\n")
        || `exit code ${output.exit_code}`,
    };
  }
  if (!output.stdout.trim()) {
    return {
      ok: false,
      reason: "empty",
      detail: output.stderr || "CLI produced no output",
    };
  }
  if (parsed.blockers && parsed.blockers.length > 0) {
    return { ok: false, reason: "blockers", detail: parsed.blockers.join("\n") };
  }
  if (parsed.semanticComplete === false) {
    return { ok: false, reason: "unrecognized", detail: output.stdout };
  }
  return { ok: true };
}

/** 解析管理操作输出：识别卸载/恢复计划、合法 no-op 和 restore-hooks 完成态。 */
export function parseUninstallPreview(stdout) {
  const result = {
    plans: [],
    blockers: [],
    noOp: null,
    completion: null,
    preview: null,
    semanticComplete: false,
    raw: stdout,
  };
  const lines = splitCliLines(stdout);
  for (let i = 0; i < lines.length; i++) {
    const planMatch = lines[i].match(/^ {2}\[Plan\] (.+?): (.+)$/);
    if (planMatch) {
      const detail = (lines[i + 1] || "").match(/^ {9}(.+)$/);
      result.plans.push({
        dir: planMatch[1],
        summary: planMatch[2],
        detail: detail ? detail[1] : null,
      });
    }

    // v0.2.0 translates the marker but leaves this dynamic verb in Chinese.
    const recoveryPlanMatch = lines[i].match(/^ {2}\[Plan\] (?:Restore|恢复) (.+)$/);
    if (recoveryPlanMatch) {
      result.plans.push({
        dir: recoveryPlanMatch[1],
        summary: "Restore interrupted transaction",
        detail: null,
      });
    }

    const trimmed = lines[i].trim();
    if (trimmed.startsWith("[Error]") || trimmed.startsWith("[Blocked]")) {
      result.blockers.push(trimmed.replace(/^\[(?:Error|Blocked)\]\s*/, ""));
    }

    if (/^\[Done\] (?:No codex-keysmith deployment manifest was found; nothing to (?:uninstall|reactivate)\.|No managed deployment was found; nothing to uninstall\.|No inactive-by-config location requires reactivation\.|No interrupted (?:deployment|uninstall) transaction requires recovery\.)$/.test(trimmed)) {
      result.noOp = trimmed;
    }
    if (/^\[Done\] Restored \d+ hooks\.json file\(s\)\.$/.test(trimmed)) {
      result.completion = trimmed;
    }
    if (/^\[Done\] Reactivated \d+ config reference\(s\)\.$/.test(trimmed)) {
      result.completion = trimmed;
    }

    if (MANAGEMENT_PREVIEW_SENTINELS.has(trimmed)) {
      result.preview = trimmed;
    }
  }
  result.semanticComplete = result.noOp !== null
    || result.completion !== null
    || result.preview !== null;
  return result;
}

const SCENARIO_LIST_ITEM_RE =
  /^- ([a-z0-9][a-z0-9_-]*) ([^:]+): (ready|blocked); platforms=([^;]*); python=([^;]*); requires=([^;]*); verify=(.+)$/;
const SCENARIO_INVALID_ITEM_RE = /^- ([^:]+): invalid \((.+)\)$/;
const SCENARIO_DEPLOYMENT_RE =
  /^\[Deployment\] ([0-9a-f]{32}) scenario=(\S+) version=(\S+) state=(\S+) root=(.+)$/;
const SCENARIO_CANONICAL_PATH_RE =
  /use the canonical(?: absolute)? path: (.+)$/m;
const VALID_SCENARIO_STATES = new Set([
  "active",
  "conflict",
  "not-installed",
  "recovery-required",
  "empty",
  "no recovery required",
]);

export function extractCanonicalTarget(text) {
  const match = String(text ?? "").match(SCENARIO_CANONICAL_PATH_RE);
  return match ? match[1].trim() : null;
}

/**
 * 解析 --scenario-list（只认 --lang en）
 */
export function parseScenarioList(stdout) {
  const result = {
    library: null,
    packages: [],
    empty: false,
    blockers: [],
    semanticComplete: false,
    raw: stdout,
  };
  let current = null;
  for (const line of splitCliLines(stdout)) {
    const libraryMatch = line.match(/^\[Scenario library\] (.+)$/);
    if (libraryMatch) {
      result.library = libraryMatch[1];
      continue;
    }
    if (line === "[Scenario state] empty") {
      result.empty = true;
      continue;
    }
    const itemMatch = line.match(SCENARIO_LIST_ITEM_RE);
    if (itemMatch) {
      current = {
        id: itemMatch[1],
        version: itemMatch[2],
        ready: itemMatch[3] === "ready",
        state: itemMatch[3],
        platforms: itemMatch[4] ? itemMatch[4].split(",").filter(Boolean) : [],
        python: itemMatch[5],
        requires: itemMatch[6],
        verify: itemMatch[7],
        blockers: [],
        invalid: false,
      };
      result.packages.push(current);
      continue;
    }
    const invalidMatch = line.match(SCENARIO_INVALID_ITEM_RE);
    if (invalidMatch) {
      current = {
        id: invalidMatch[1],
        version: "",
        ready: false,
        state: "invalid",
        platforms: [],
        python: "",
        requires: "",
        verify: "",
        blockers: [invalidMatch[2]],
        invalid: true,
      };
      result.packages.push(current);
      result.blockers.push(invalidMatch[2]);
      continue;
    }
    const blockedMatch = line.match(/^ {4}\[Blocked\] (.+)$/);
    if (blockedMatch && current) {
      current.blockers.push(blockedMatch[1]);
    }
  }
  result.semanticComplete = Boolean(result.library)
    && (result.empty || result.packages.length > 0);
  return result;
}

/**
 * 解析 --scenario-status
 */
export function parseScenarioStatus(stdout) {
  const result = {
    target: null,
    state: null,
    deployments: [],
    recovery: null,
    blockers: [],
    semanticComplete: false,
    raw: stdout,
  };
  let current = null;
  for (const line of splitCliLines(stdout)) {
    const targetMatch = line.match(/^\[Scenario target\] (.+)$/);
    if (targetMatch) {
      result.target = targetMatch[1];
      continue;
    }
    const stateMatch = line.match(/^\[Scenario state\] (.+)$/);
    if (stateMatch) {
      result.state = stateMatch[1];
      continue;
    }
    const deploymentMatch = line.match(SCENARIO_DEPLOYMENT_RE);
    if (deploymentMatch) {
      current = {
        deploymentId: deploymentMatch[1],
        scenarioId: deploymentMatch[2],
        version: deploymentMatch[3],
        state: deploymentMatch[4],
        root: deploymentMatch[5],
        detail: "",
      };
      result.deployments.push(current);
      continue;
    }
    if (current && /^ {4}\S/.test(line)) {
      current.detail = line.trim();
      continue;
    }
    const recoveryMatch = line.match(
      /^\[Recovery\] (\S+) (\S+) phase=(.+)$/,
    );
    if (recoveryMatch) {
      result.recovery = {
        operation: recoveryMatch[1],
        transactionId: recoveryMatch[2],
        phase: recoveryMatch[3],
      };
      continue;
    }
    if (line.startsWith("[Blocked]")) {
      result.blockers.push(line.replace(/^\[Blocked\]\s*/, ""));
    }
    if (line.startsWith("[Error]")) {
      result.blockers.push(line.replace(/^\[Error\]\s*/, ""));
    }
  }
  result.semanticComplete = Boolean(result.target)
    && VALID_SCENARIO_STATES.has(result.state);
  return result;
}

/**
 * 解析 --deploy-scenario 预览或完成输出
 */
export function parseScenarioDeployPreview(stdout) {
  const result = {
    scenarioId: null,
    version: null,
    target: null,
    source: null,
    files: null,
    preview: null,
    deploymentId: null,
    blockers: [],
    semanticComplete: false,
    raw: stdout,
  };
  for (const line of splitCliLines(stdout)) {
    const deployMatch = line.match(/^\[Scenario deploy\] (\S+) (\S+)$/);
    if (deployMatch) {
      result.scenarioId = deployMatch[1];
      result.version = deployMatch[2];
      continue;
    }
    const targetMatch = line.match(/^\[Target\] (.+)$/);
    if (targetMatch) {
      result.target = targetMatch[1];
      continue;
    }
    const sourceMatch = line.match(/^\[Source\] (.+)$/);
    if (sourceMatch) {
      result.source = sourceMatch[1];
      continue;
    }
    const filesMatch = line.match(/^\[Files\] (\d+)$/);
    if (filesMatch) {
      result.files = Number(filesMatch[1]);
      continue;
    }
    if (line === "[Preview] no files were changed; add --yes to deploy") {
      result.preview = line;
      continue;
    }
    const doneMatch = line.match(/^\[Done\] deployed scenario as ([0-9a-f]{32})$/);
    if (doneMatch) {
      result.deploymentId = doneMatch[1];
      continue;
    }
    if (line.startsWith("[Blocked]")) {
      result.blockers.push(line.replace(/^\[Blocked\]\s*/, ""));
    }
    if (line.startsWith("[Error]")) {
      result.blockers.push(line.replace(/^\[Error\]\s*/, ""));
    }
  }
  result.semanticComplete = Boolean(result.scenarioId && result.target)
    && (result.preview !== null || result.deploymentId !== null || result.blockers.length > 0);
  return result;
}

/**
 * 解析 --scenario-uninstall 预览或完成输出
 */
export function parseScenarioUninstallPreview(stdout) {
  const result = {
    deploymentId: null,
    target: null,
    preview: null,
    state: null,
    completion: null,
    blockers: [],
    semanticComplete: false,
    raw: stdout,
  };
  for (const line of splitCliLines(stdout)) {
    const uninstallMatch = line.match(/^\[Scenario uninstall\] ([0-9a-f]{32})$/);
    if (uninstallMatch) {
      result.deploymentId = uninstallMatch[1];
      continue;
    }
    const targetMatch = line.match(/^\[Target\] (.+)$/);
    if (targetMatch) {
      result.target = targetMatch[1];
      continue;
    }
    if (line.startsWith("[Preview]")) {
      result.preview = line;
      continue;
    }
    const stateMatch = line.match(/^\[Scenario state\] (.+)$/);
    if (stateMatch) {
      result.state = stateMatch[1];
      continue;
    }
    const doneMatch = line.match(/^\[Done\] uninstalled scenario deployment ([0-9a-f]{32})$/);
    if (doneMatch) {
      result.completion = doneMatch[1];
      continue;
    }
    if (line.startsWith("[Blocked]") || line.startsWith("[Error]")) {
      result.blockers.push(line.replace(/^\[(?:Blocked|Error)\]\s*/, ""));
    }
  }
  result.semanticComplete = Boolean(result.deploymentId)
    && (
      result.preview !== null
      || result.completion !== null
      || result.state === "not-installed"
      || (typeof result.state === "string" && result.state.startsWith("deployment not installed"))
    );
  return result;
}

/**
 * 解析 --scenario-recover 预览或完成输出
 */
export function parseScenarioRecoverPreview(stdout) {
  const result = {
    target: null,
    state: null,
    recovery: null,
    preview: null,
    required: false,
    blockers: [],
    semanticComplete: false,
    raw: stdout,
  };
  for (const line of splitCliLines(stdout)) {
    const targetMatch = line.match(/^\[Scenario recover\] (.+)$/);
    if (targetMatch) {
      result.target = targetMatch[1];
      continue;
    }
    if (line === "[Scenario state] no recovery required") {
      result.state = "no recovery required";
      continue;
    }
    const recoveryMatch = line.match(
      /^\[Recovery\] operation=(\S+) transaction=(\S+) phase=(.+)$/,
    );
    if (recoveryMatch) {
      result.recovery = {
        operation: recoveryMatch[1],
        transactionId: recoveryMatch[2],
        phase: recoveryMatch[3],
      };
      result.required = true;
      continue;
    }
    if (line.startsWith("[Preview]") && line.includes("add --yes to recover")) {
      result.preview = line;
      result.required = true;
      continue;
    }
    if (line.startsWith("[Blocked]") || line.startsWith("[Error]")) {
      result.blockers.push(line.replace(/^\[(?:Blocked|Error)\]\s*/, ""));
    }
  }
  result.semanticComplete = Boolean(result.target)
    && (result.state === "no recovery required" || result.preview !== null || result.blockers.length > 0);
  return result;
}

// ── 内部工具 ───────────────────────────────

function normalizeKind(kind) {
  const k = kind.trim();
  if (k === "regular file") return "regular";
  if (k === "missing") return "missing";
  return "other";
}

function parseActivation(value) {
  return parseKnownToken(value, VALID_ACTIVATIONS);
}

function parseLegacy(value) {
  if (value === "none") return "none";
  if (
    value.startsWith("the next default deployment will archive")
    || value.startsWith("next default deploy will archive")
  ) {
    return "archive";
  }
  if (value.startsWith("unmanaged")) return "unmanaged";
  return "unknown";
}

function parseHooks(value) {
  return parseKnownToken(value, VALID_HOOKS_STATUSES);
}

function firstToken(value) {
  return value.split(/[\s(（]/)[0] || "unknown";
}

function parseKnownToken(value, allowed) {
  const token = firstToken(value);
  return allowed.has(token) ? token : "unknown";
}

const SCAFFOLD_LIST_ITEM_RE =
  /^ {2}([A-Za-z0-9._-]+)  v(\d+)  (\S+)  (.+)$/;

/**
 * 解析 --scaffold-list（只认 --lang en）
 */
export function parseScaffoldList(stdout) {
  const result = {
    packDir: null,
    packages: [],
    empty: false,
    semanticComplete: false,
    raw: stdout,
  };
  for (const line of splitCliLines(stdout)) {
    const dirMatch = line.match(/^\[scaffold\] pack-dir: (.+)$/);
    if (dirMatch) {
      result.packDir = dirMatch[1];
      continue;
    }
    if (line === "[scaffold] no packs found") {
      result.empty = true;
      continue;
    }
    const itemMatch = line.match(SCAFFOLD_LIST_ITEM_RE);
    if (itemMatch) {
      result.packages.push({
        id: itemMatch[1],
        version: Number(itemMatch[2]),
        family: itemMatch[3],
        title: itemMatch[4],
      });
    }
  }
  result.semanticComplete = result.packDir !== null
    && (result.packages.length > 0 || result.empty);
  return result;
}

/**
 * 解析 --scaffold / --scaffold-uninstall 预览或写入结果（只认 --lang en）
 */
export function parseScaffoldPreview(stdout) {
  const result = {
    packId: null,
    version: null,
    source: null,
    dest: null,
    backup: null,
    unchanged: false,
    previewOnly: false,
    wrote: false,
    removed: false,
    notMaterialized: false,
    didNotModifyCodex: false,
    startPrompt: null,
    semanticComplete: false,
    raw: stdout,
  };
  for (const line of splitCliLines(stdout)) {
    const packMatch = line.match(/^\[scaffold\] pack: (\S+) v(\d+)$/);
    if (packMatch) {
      result.packId = packMatch[1];
      result.version = Number(packMatch[2]);
      continue;
    }
    const sourceMatch = line.match(/^\[scaffold\] source: (.+)$/);
    if (sourceMatch) {
      result.source = sourceMatch[1];
      continue;
    }
    const destMatch = line.match(/^\[(?:scaffold|scaffold-uninstall)\] dest: (.+)$/);
    if (destMatch) {
      result.dest = destMatch[1];
      continue;
    }
    const backupMatch = line.match(/^\[scaffold\] backup: (.+)$/);
    if (backupMatch) {
      result.backup = backupMatch[1];
      continue;
    }
    const unchangedMatch = line.match(/^\[scaffold\] unchanged: (.+)$/);
    if (unchangedMatch) {
      result.unchanged = true;
      result.dest = unchangedMatch[1];
      continue;
    }
    const wroteMatch = line.match(/^\[scaffold\] wrote (.+)$/);
    if (wroteMatch) {
      result.wrote = true;
      result.dest = wroteMatch[1];
      continue;
    }
    const removedMatch = line.match(/^\[scaffold\] removed (.+)$/);
    if (removedMatch) {
      result.removed = true;
      result.dest = removedMatch[1];
      continue;
    }
    const missingMatch = line.match(/^\[scaffold\] not materialized: (.+)$/);
    if (missingMatch) {
      result.notMaterialized = true;
      result.packId = missingMatch[1];
      continue;
    }
    if (line === "[scaffold] did not modify ~/.codex") {
      result.didNotModifyCodex = true;
      continue;
    }
    if (line === "[scaffold] preview only; add --yes to write."
      || line === "[scaffold] preview only; add --yes to delete.") {
      result.previewOnly = true;
      continue;
    }
    const promptMatch = line.match(/^Suggested first sentence: (.+)$/);
    if (promptMatch) {
      result.startPrompt = promptMatch[1];
    }
  }
  result.semanticComplete = result.didNotModifyCodex && (
    result.previewOnly
    || result.wrote
    || result.removed
    || result.unchanged
    || result.notMaterialized
  );
  return result;
}

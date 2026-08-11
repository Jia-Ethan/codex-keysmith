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

const NODE_NAME_MAP = {
  "config.toml": "configToml",
  "gpt-unrestricted.md": "md",
  "gpt5.5-unrestricted.md": "legacyMd",
  "hooks.json": "hooks",
  "hooks.json.disabled": "hooksDisabled",
  "deployment manifest": "manifest",
};

const MANAGEMENT_PREVIEW_SENTINELS = new Set([
  "[Preview] No files were changed; add --yes to confirm uninstall.",
  "[Preview] No files were changed; add --yes to confirm recovery.",
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

/**
 * 解析 --status 输出（SPEC §5.1）
 * 容错原则：遇到不认识的行直接跳过，绝不抛异常导致整页挂掉。
 * 但已识别的节点行如果类型异常，必须保留节点并升级为 warning。
 */
export function parseStatus(stdout) {
  const result = { directories: [], raw: stdout };
  let current = null;

  for (const line of splitCliLines(stdout)) {
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
        abnormalNodes: [], // 类型异常的节点（符号链接/FIFO/socket…），视图层显眼展示
      };
      result.directories.push(current);
      continue;
    }
    if (!current) continue;

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
      }
      continue;
    }
    // "Hooks restore: available ..." 是提示行不是状态，等效于 restorable
    if (label === "Hooks restore" && value.startsWith("available")) {
      current.hooksStatus = "restorable";
      continue;
    }

    switch (label) {
      case "model_instructions_file":
        current.modelInstructionsFile =
          value === "<unset or unrecognized>" ? null : value;
        break;
      case "Config activation":
        current.activation = parseActivation(value);
        break;
      case "Transaction residue":
        current.residue =
          value === "none" ? [] : value.split(", ").filter(Boolean);
        break;
      case "Legacy migration":
        current.legacyMigration = parseLegacy(value);
        break;
      case "Hooks status":
        current.hooksStatus = parseHooks(value);
        break;
      case "Structural health":
        current.health = value.startsWith("healthy") ? "healthy" : "blocked";
        break;
      case "Uninstall readiness":
        current.uninstallReadiness = firstToken(value);
        break;
      case "Deployability":
        current.deployability = firstToken(value);
        break;
      default:
        if (value.startsWith("[Warning]")) {
          current.warnings.push(value.replace(/^\[Warning\] /, ""));
        }
    }
  }

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

    if (/^\[Done\] (?:No codex-keysmith deployment manifest was found; nothing to uninstall\.|No managed deployment was found; nothing to uninstall\.|No interrupted (?:deployment|uninstall) transaction requires recovery\.)$/.test(trimmed)) {
      result.noOp = trimmed;
    }
    if (/^\[Done\] Restored \d+ hooks\.json file\(s\)\.$/.test(trimmed)) {
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

// ── 内部工具 ───────────────────────────────

function normalizeKind(kind) {
  const k = kind.trim();
  if (k === "regular file") return "regular";
  if (k === "missing") return "missing";
  return "other";
}

function parseActivation(value) {
  for (const k of ["inactive-by-config", "not-installed", "conflict", "active"]) {
    if (value.startsWith(k)) return k;
  }
  return "unknown";
}

function parseLegacy(value) {
  if (value === "none") return "none";
  if (value.startsWith("next default deploy will archive")) return "archive";
  if (value.startsWith("unmanaged")) return "unmanaged";
  return "unknown";
}

function parseHooks(value) {
  for (const k of ["absent", "active", "restorable", "conflict", "blocked", "ready"]) {
    if (value.startsWith(k)) return k;
  }
  return "unknown";
}

function firstToken(value) {
  return value.split(/[\s(]/)[0] || "unknown";
}

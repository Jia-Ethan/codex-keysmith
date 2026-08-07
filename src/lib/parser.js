// lib/parser.js — CLI 文本输出解析器
// 解析规范见 SPEC.md §5。所有解析器只认 --lang en 的输出。

// 文件行：kind 用白名单开头匹配（regular file/missing 之外的实际类型
// 如 directory、symlink、other (xxx) 都吞进来并转 warning）
const FILE_LINE_RE = /^ {4}(.+?): (regular file|missing|directory|symlink|broken symlink|other.*) \((.+)\)$/;

const NODE_NAME_MAP = {
  "config.toml": "configToml",
  "gpt-unrestricted.md": "md",
  "gpt5.5-unrestricted.md": "legacyMd",
  "hooks.json": "hooks",
  "hooks.json.disabled": "hooksDisabled",
  "deployment manifest": "manifest",
};

/**
 * 解析 --status 输出（SPEC §5.1）
 * 容错原则：遇到不认识的行直接跳过，绝不抛异常导致整页挂掉。
 */
export function parseStatus(stdout) {
  const result = { directories: [], raw: stdout };
  let current = null;

  for (const line of stdout.split("\n")) {
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
      };
      result.directories.push(current);
      continue;
    }
    if (!current) continue;

    const fileMatch = line.match(FILE_LINE_RE);
    if (fileMatch) {
      const [, name, kind, path] = fileMatch;
      const key = NODE_NAME_MAP[name];
      if (key) {
        const norm = normalizeKind(kind);
        current.nodes[key] = { kind: norm, path, raw: kind };
        if (norm === "other") {
          current.warnings.push(`${name}: unexpected type "${kind}"`);
        }
      }
      continue;
    }

    const kvMatch = line.match(/^ {4}(.+?): (.+)$/);
    if (!kvMatch) continue;
    const [, label, value] = kvMatch;
    // CLI 可能在 kv 区输出 [Error]/[Warning] 诊断行（config 解析失败等），
    // 不能吞成未知 kv，要转成 warning 展示。注意 label 可能是
    // "[Error] config.toml 无法安全读取" 这种带正文的形式
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
    raw: stdout,
  };
  let currentTarget = null;

  for (const line of stdout.split("\n")) {
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

  return result;
}

/** 解析 --uninstall 预览输出：提取每个目录的回滚计划行 */
export function parseUninstallPreview(stdout) {
  const result = { plans: [], raw: stdout };
  const lines = stdout.split("\n");
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
  }
  return result;
}

// ── 内部工具 ───────────────────────────────

function normalizeKind(kind) {
  if (kind === "regular file") return "regular";
  if (kind === "missing") return "missing";
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

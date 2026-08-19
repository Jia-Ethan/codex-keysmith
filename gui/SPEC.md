# codex-keysmith GUI 客户端 — 技术方案与交接文档

> 状态：源码已具备指令层 GUI（M1–M5）、场景库页、preset 选择与 fixture scaffold 页；冻结 sidecar 内嵌 `fixture_packs/`。`desktop-v0.3.8-beta.1` 已作为当前 unsigned Desktop 公开发布；正式签名、公证与实体设备验收仍待完成
> 关联 issue：[#10「建议」为小白做一个可视化的界面客户端](https://github.com/Jia-Ethan/codex-keysmith/issues/10)

## 1. 项目背景

codex-keysmith 是一个零依赖单文件 Python CLI（`codex-instruct.py`），负责把 Markdown 指令文件部署到 Codex 配置目录（`~/.codex`），修改 `config.toml` 的 `model_instructions_file` 字段，并按需隔离 `hooks.json`。它强调**预览优先、显式确认、可随时撤销**。

CLI 对熟练用户很好用，但对小白（issue #10 的目标用户）门槛过高：需要手动下载、校验哈希、跑一串命令行。本项目的目标是做一个**可视化客户端**，把核心操作（状态查看、部署、卸载、恢复 hooks、中断恢复）变成图形界面里的按钮和向导。

## 2. 已确认的决策（与项目所有者敲定）

| 决策点 | 结论 | 理由 |
|---|---|---|
| 技术栈 | **Tauri 2**（Rust 后端 + Web 前端） | 打包体积小（几 MB）、原生感强、界面现代化 |
| 平台范围 | **macOS Apple Silicon + Windows x64** | 每个平台原生冻结 Python 与构建 Tauri bundle，不做跨平台交叉打包；本轮不提供 Intel Mac 包 |
| 与 CLI 的关系 | **包装现有 CLI**（subprocess 调用），不重实现逻辑 | 复用已测试的部署/回滚/恢复逻辑，CLI 升级客户端不用跟着改 |
| 本轮交付 | **指令层 M1–M5 + 场景库 + 双通道 GUI** | 部署页可选 preset；夹具页只调用 CLI scaffold；sidecar 内嵌 `fixture_packs/`；已发布为 unsigned `desktop-v0.3.8-beta.1` |

## 3. 总体架构

```
┌─────────────────────────────────────────────┐
│  Tauri 2 App (macOS .app)                  │
│                                             │
│  ┌───────────────────────────┐              │
│  │  Web 前端 (React 19)      │              │
│  │  - 视图：Dashboard /      │              │
│  │    Deploy / Manage /      │              │
│  │    Settings（src/views/） │              │
│  │  - shadcn/ui 风格组件 +   │              │
│  │    Tailwind 4 + Motion    │              │
│  │  - react-i18next + sonner │              │
│  │  - parser.js 解析 CLI 文本│              │
│  │    + gatePreview 门禁     │              │
│  └──────────┬────────────────┘              │
│             │ invoke()                      │
│  ┌──────────▼────────────────┐              │
│  │  Rust (Tauri commands)   │              │
│  │  - cli_runner: 定位并执行 │              │
│  │    python3 codex-instruct │              │
│  │  - fs 读取 manifest JSON  │              │
│  └──────────┬────────────────┘              │
└─────────────┼───────────────────────────────┘
              │ subprocess（包装，不重实现）
┌─────────────▼───────────────────────────────┐
│  codex-instruct.py（复用既有命令与事务语义）  │
└─────────────────────────────────────────────┘
```

**核心原则**

1. **客户端永不直接修改 `~/.codex` 下的任何文件。** 所有写操作都通过 CLI 完成，保证与 CLI 的事务/备份/回滚语义一致。
2. **Rust 只做进程执行与文件读取，不做业务解析。** CLI 文本解析放前端 `parser.js`，改解析逻辑不用碰 Rust。
3. **所有 CLI 调用固定 `--lang en`**，输出格式稳定，解析器只认英文输出。
4. 部署/卸载/恢复等写操作前，**始终先跑一次对应预览**（`--dry-run` / 无 `--yes`），把预览结果展示给用户确认，与 CLI 的「预览优先」哲学一致。

## 4. CLI 接口清单（已从源码核实）

**CLI 路径定位策略（按优先级）：**

1. Settings 中非空的手动路径覆盖（高级/开发用途）
2. 自动模式优先使用与应用同目录的 PyInstaller sidecar
3. `CODEX_KEYSMITH_CLI` 环境变量
4. 常见目录/PATH 中的 `codex-keysmith` 可执行文件
5. 最后回退到 `codex-instruct.py`；只有该模式依赖系统 Python

**参数表（来自 `codex-instruct.py` argparse，v0.3.8）：**

| 参数 | 用途 | 客户端用法 |
|---|---|---|
| `--status` | 只读查看 config/提示词/hooks/事务残留状态 | Dashboard 主数据源 |
| `--dry-run` | 部署预览，不实际修改 | Deploy 向导第 2 步 |
| `--yes` | 确认执行（部署/卸载/恢复） | 用户点确认后追加 |
| `--preset unrestricted\|contract` | 选择内置提示词 | Deploy 向导「内置稿」；本地文件模式不传 |
| `--file <path>` | 外部 MD 文件 | Deploy 向导「选择文件」 |
| `--name <name>` | MD 文件名（不含 .md，默认 `gpt-unrestricted`） | Deploy 向导「自定义名称」 |
| `--codex-dir <path>` | 手动指定 .codex 目录 | Settings / 多目录场景 |
| `--uninstall` | 按 manifest 分层卸载 | Manage 页 |
| `--restore-hooks` | 仅恢复 hooks.json | Manage 页 |
| `--recover` | 恢复中断事务 | Manage 页（有残留时高亮提示） |
| `--scenario-list` | 列出场景包与平台/依赖 blocker | Scenarios 页 |
| `--deploy-scenario` | 预览或部署一个场景包 | Scenarios 页；必须绝对 `--target-dir` |
| `--scenario-status` | 目标目录场景状态 | Scenarios 页 |
| `--scenario-uninstall` | 按 `deployment_id` 预览或卸载 | Scenarios 页 |
| `--scenario-recover` | 预览或恢复中断场景事务 | Scenarios 页 |
| `--scaffold-list` | 列出内置 fixture 包 | Fixtures 页包列表 |
| `--scaffold <pack>` | 预览或写入 fixture 工作区 | Fixtures 页「预览写入」 |
| `--scaffold-uninstall <pack>` | 预览或删除已写入的 fixture | Fixtures 页「预览删除」 |
| `--workspace-root <path>` | 指定独立 fixture 工作区 | Fixtures 页；留空使用 CLI 默认值 |
| `--force` | 覆盖指纹不匹配的 fixture 目录 | 仅绑定对应写入预览后执行 |
| `--skip-hooks-isolation` | 部署时跳过 hooks 隔离（需同时 `--codex-dir`） | Deploy 向导高级选项 |
| `--lang en` | **固定使用** | 所有调用 |

**参数互斥约束（来自源码校验，客户端 UI 必须遵守）：**

- `--status` 只可与 `--codex-dir` 等只读定位参数同用
- `--preset` 不能与 `--file` 同用；本地文件模式不传 `--preset`
- `--restore-hooks` 不能与 `--file`/`--name`/`--yes`/`--skip-hooks-isolation` 同用
- `--uninstall`/`--recover` 不能与 `--file`/`--name`/`--skip-hooks-isolation` 同用
- scaffold 命令彼此互斥，并拒绝指令部署、场景部署和 `--codex-dir` 参数
- `--scaffold-list` 只接受 `--pack-dir` 与 `--lang`；`--force` 只随对应 scaffold 操作使用
- `--skip-hooks-isolation` 必须显式 `--codex-dir`

**退出码约定：** 写操作失败时 `sys.exit(1)`（源码中大量路径）；argparse 校验错误也是非零退出。`--status` 是例外：目录存在冲突或异常节点时会输出完整报告并以非零退出，客户端须校验报告语义完整性后降级展示；其他非零退出均按失败处理并展示完整 stdout/stderr。

## 5. 真实输出样例与解析规范

以下为兼容基线 CLI 输出样例（最初采自 v0.2.0），v0.3.8 GUI 解析器必须能处理。

### 5.1 `--status`（真实输出）

```
[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: /Users/ethan/.codex ──
    config.toml: regular file (/Users/ethan/.codex/config.toml)
    gpt-unrestricted.md: regular file (/Users/ethan/.codex/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (/Users/ethan/.codex/gpt5.5-unrestricted.md)
    hooks.json: missing (/Users/ethan/.codex/hooks.json)
    hooks.json.disabled: missing (/Users/ethan/.codex/hooks.json.disabled)
    deployment manifest: regular file (/Users/ethan/.codex/.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    Config activation: active (the current config loads the managed prompt)
    Transaction residue: none
    Legacy migration: none
    Hooks status: absent
    Structural health: healthy
    Uninstall readiness: ready
    Deployability: ready

[Done] Status found no blockers; live active/disabled hooks were not read or parsed, manifest-referenced backup recovery evidence was read and hashed, and no files were changed.
```

**解析目标（`fetchStatus()` 输出结构）：**

```js
{
  declaredDirectoryCount: 1,
  terminator: { kind: "done|error", affectedCount: 0, line: "..." },
  semanticComplete: true,
  exitCode: 0,
  stderr: "",
  timedOut: false,
  degraded: false,
  directories: [{
    path: "/Users/ethan/.codex",
    nodes: {
      configToml: { kind: "regular|missing|other", path: "...", raw: "regular file" },
      md: { kind: "...", path: "...", raw: "..." },
      legacyMd: { kind: "...", path: "...", raw: "..." },
      hooks: { kind: "...", path: "...", raw: "..." },
      hooksDisabled: { kind: "...", path: "...", raw: "..." },
      manifest: { kind: "...", path: "...", raw: "..." }
    },
    modelInstructionsFile: "./gpt-unrestricted.md" | null,
    activation: "active" | "inactive-by-config" | "conflict" | "not-installed",
    residue: [] | ["path1", "path2"],
    legacyMigration: "none" | "archive" | "unmanaged",
    hooksStatus: "absent" | "active" | "restorable" | "conflict",
    health: "healthy" | "blocked",
    uninstallReadiness: "ready" | "blocked" | "not-applicable",
    deployability: "ready" | "blocked",
    warnings: [],
    errors: [],
    abnormalNodes: []
  }]
}
```

**注意：** 文件行格式为 `    <name>: <kind> (<path>)`，kind 取值为 `regular file` / `missing` / 其他描述（如 `directory`、`symlink`——源码 `_print_node` 会输出实际类型）。解析时**不要假设只有 regular/missing 两种**，未知类型一律映射为 `other` 并转成 warning。

### 5.2 `--dry-run`（真实输出）

```
[Prompt] Source: bundled examples/gpt-unrestricted.md; SHA-256: 2c2c9f0e008c492bfc9487170a7a08daedeb8b0625af1f85617ab2d1bd3f35c0
[Behavior notice] This prompt becomes the global model_instructions_file, reinterprets authorization boundaries, limits refusals/warnings, and covers reverse engineering, remote-command, adult, and weapons requests. Read the prompt before confirming deployment.
[+] Found 1 Codex configuration location(s):
    /Users/ethan/.codex

[DRY RUN] Preview mode; no files will be changed.
    To apply changes, run again with --yes.

  Target: /Users/ethan/.codex
    → Write MD: /Users/ethan/.codex/gpt-unrestricted.md
    → Config entry: model_instructions_file = "./gpt-unrestricted.md"
    → MD backup:  /Users/ethan/.codex/gpt-unrestricted.md.bak_20260807_143920
    → config.toml backup: none (configuration value unchanged)
    → No hooks.json detected: /Users/ethan/.codex/hooks.json
    → Existing manifest backup:  /Users/ethan/.codex/.codex-keysmith-manifest.json.bak_20260807_143920
```

**解析目标：**

```js
{
  promptSource: { kind: "bundled" | "external", path: "...", sha256: "..." },
  targets: [{
    dir: "/Users/ethan/.codex",
    actions: ["Write MD: ...", "Config entry: model_instructions_file = ...", "MD backup: ...", ...]
  }],
  warnings: ["No hooks.json detected: ..."]
}
```

**关键 UX 点：** `[Behavior notice]` 那一行必须原样展示给用户（部署前必须让用户知道这个提示词是全局行为开关）。

### 5.3 manifest（结构化 JSON，直接读取，不走文本解析）

路径：`<codex-dir>/.codex-keysmith-manifest.json`

```json
{
  "schema_version": 1,
  "tool_version": "0.1.1",
  "deployment_id": "d56cf7f86c2d4211bef2fc9bdf546884",
  "created_at": "2026-07-18T02:24:48.220202Z",
  "md":       { "path": "...", "before": {指纹}|null, "after": {指纹}, "backup": "name"|null },
  "config":   { "path": "config.toml", "before": {指纹}, "after": {指纹}, "changed": bool, "backup": "name"|null },
  "hooks":    { "isolated": bool, "active_before": 指纹|null, "disabled_before": 指纹|null,
                "active_after": 指纹|null, "disabled_after": 指纹|null,
                "backup": "name"|null, "previous_disabled_backup": "name"|null },
  "legacy":   { "path": "gpt5.5-unrestricted.md", "action": "none|unmanaged|archive",
                "before": 指纹|null, "after": 指纹|null, "archive": "name"|null },
  "previous_manifest": { "before": 指纹|null, "backup": "name"|null }
}
```

指纹对象：`{ "sha256": "...", "size": 7038, "mtime_ns": 1783991998945891737 }`

**用途：** Dashboard 的「部署详情」面板直接渲染此结构（部署时间、文件名、hooks 隔离状态、旧版迁移状态）。客户端对 manifest 只读、不校验（校验是 CLI 的事），字段缺失时展示「未知」。

### 5.4 目录/文件命名规则（客户端展示用）

| 对象 | 规则 |
|---|---|
| 事务目录 | `.codex-keysmith-transaction-<32hex>`（源码 `JOURNAL_PREFIX`） |
| 备份文件 | `<原名>.bak_YYYYMMDD_HHMMSS`（如 `gpt-unrestricted.md.bak_20260807_143920`） |
| manifest | `.codex-keysmith-manifest.json` |
| manifest-intent | `manifest-intent.json` / `manifest-intent.pending.json` |
| 隔离的 hooks | `hooks.json.disabled` |
| 旧版提示词 | `gpt5.5-unrestricted.md`（`LEGACY_MD_FILENAME`，v0.2.0 仍沿用） |

## 6. 前端视图设计

### 6.1 Dashboard（默认页）

- 顶部：CLI 版本、运行时类型（内置 sidecar / 外部可执行文件 / 系统 Python）、检测到的 .codex 目录数
- 状态卡片（每个目录一张）：
  - 激活状态徽章（active=绿 / inactive-by-config=黄 / not-installed=灰 / conflict=红）
  - 结构健康（healthy / blocked）
  - 关键行：model_instructions_file、hooks 状态、事务残留、旧版迁移
  - 残留存在时显示「恢复中断操作」按钮（跳 Manage）
- 部署详情面板（有 manifest 时）：部署时间、tool_version、文件名、hooks 隔离、旧版归档

### 6.2 Deploy 向导（核心流程，3 步）

1. **选择内容**：内置提示词（bundled）/ 选择本地 MD 文件（`--file`）；自定义名称（`--name`）；高级选项：跳过 hooks 隔离（`--skip-hooks-isolation`，需选目录）
2. **预览**：调用 `--dry-run`，展示解析后的 actions 列表 + 完整 `[Behavior notice]` + 原始输出可展开查看
3. **确认**：红色按钮「确认部署」→ `--yes`，展示结果输出

### 6.3 Manage

- **卸载**（`--uninstall`）：先预览（显示将撤销哪一层），确认后 `--yes`；多次卸载逐层回滚
- **恢复 hooks**（`--restore-hooks`）：确认后执行
- **恢复中断事务**（`--recover`）：仅在 status 显示残留时可用，确认后 `--yes`
- 每个操作后自动刷新 Dashboard

Deploy 与 Manage 共用 Radix `AlertDialog`：Overlay 负责全屏模糊和背景交互隔离，Content 必须以固定定位在 1200×800 默认窗口及 900×600 最小窗口内居中可见。`card-glass` 等视觉表面类不得设置 `position`，避免覆盖弹窗的布局定位。

### 6.4 Settings

- CLI 脚本路径（自动探测 + 手动指定）
- 默认 .codex 目录（留空 = 自动发现全部）
- 界面语言（zh-CN / en，默认 zh-CN）
- 关于：版本号、链接到 GitHub

## 7. Rust 命令设计（tauri commands）

```rust
// cli_runner.rs 模块（实际实现，内置 sidecar 优先，Python 脚本回退）
#[tauri::command]
async fn cli_run(
    cli_path: Option<String>,   // Settings 手动指定；None 走自动探测
    args: Vec<String>,          // 如 ["--status", "--codex-dir", "/Users/ethan/.codex", "--lang", "en"]
    timeout_ms: Option<u64>,    // 默认 30_000，部署类操作可放宽
) -> Result<CliOutput, String>;

struct CliOutput {
    stdout: String,
    stderr: String,
    exit_code: i32,
    timed_out: bool,
}

#[tauri::command]
async fn read_manifest(codex_dir: String) -> Result<serde_json::Value, String>;

#[tauri::command]
async fn detect_cli() -> Result<Option<CliDescriptor>, String>; // { path, runtime }

#[tauri::command]
async fn cli_version(cli_path: Option<String>) -> Result<String, String>;

#[tauri::command]
async fn cli_runtime(cli_path: Option<String>) -> Result<String, String>;
```

另注册 `tauri-plugin-dialog`（文件/目录选择）与官方 `tauri-plugin-single-instance`（重复启动时恢复并显示现有主窗口，同时请求系统聚焦），capabilities 开通 `core:default`、`core:window:allow-close`、`core:window:allow-destroy`、`dialog:default` 与 `dialog:allow-open`。窗口 1200×800、最小 900×600。

**实现要点：**

- 用 `tokio::process::Command` spawn，`--` 不适用（argparse 无歧义），参数直接数组传入，**绝不拼接 shell 字符串**
- 超时 kill：`tokio::time::timeout` + `child.kill().await`
- 输出按 UTF-8 解析，非法 UTF-8 替换为 `�`（`String::from_utf8_lossy`）
- CLI 路径每次执行前做普通文件校验；`.py` 选择 Python 解释器，其他文件直接执行
- stdout/stderr 超过 2 MiB 后继续排空管道但停止累积，避免子进程因输出上限死锁
- `read_manifest` 限制只读 manifest 文件（路径必须位于 codex-dir 内且文件名精确匹配），防止任意文件读取

## 8. 安全与错误处理

| 场景 | 处理 |
|---|---|
| CLI 不存在 | Settings 引导重新定位；所有操作按钮禁用 |
| 子进程超时 | kill 进程，提示用户检查是否有残留事务（可去 Manage 用 `--recover`） |
| status 非零退出码 | 若声明目录数、目录核心字段、终止句与退出码一致，则保留目录卡片并显示退出码、stdout、stderr 诊断；否则失败关闭 |
| 其他非零退出码 | 同时保留 stdout/stderr 全文 + 建议动作（如「先运行 status 查看原因」） |
| codex-dir 不存在 | 用 `--codex-dir` 明确指定时由 CLI 报错；自动探测时提示未找到 |
| manifest 读取失败 | Dashboard 详情面板显示「无法读取 manifest」，不阻塞其他功能 |
| 后端调用运行中 | 每次 Keysmith `cli_run`/`cli_version`/status/manifest 等 invoke 获取独立生命周期租约；全局交互锁禁用 Sidebar 和写入口，关闭请求排队，最后一个租约释放后自动销毁主窗口并退出；销毁失败回退到普通关闭并保留重试状态 |
| 写操作进行中 | Deploy/Manage 通过全局互斥入口防止并发写；调用 CLI 时可叠加生命周期租约，只有全部租约释放后才解除关闭队列 |
| 空闲关闭 | 无托盘驻留；关闭事件先建立退出屏障并阻止新后端调用，再显式销毁主窗口，避免默认关闭与迟到 sidecar 启动之间的竞态 |
| 重复启动 | 第二进程退出并通知首进程恢复、显示主窗口，同时请求系统聚焦 |

## 9. 里程碑

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M1 状态展示** ✅ | Dashboard + `--status` 解析 + manifest 展示 | 真实机器上 status 各状态（active/inactive/not-installed/conflict）都能正确渲染 |
| **M2 部署向导** ✅ | 3 步向导 + dry-run 解析 + 确认执行 | 完整走通「选文件→预览→部署→Dashboard 刷新」 |
| **M3 管理操作** ✅ | 卸载 / 恢复 hooks / 恢复中断 | 与 CLI 逐层回滚语义一致；残留场景可恢复 |
| **M4 打包基础** ✅ | PyInstaller sidecar、统一图标、macOS app/dmg 配置 | 安装包内置冻结 CLI，不依赖系统 Python；签名/公证/Release CI 单独验收 |
| **M5 Windows x64 打包基础** ✅ | 原生 sidecar + current-user NSIS + WebView2 bootstrapper | 可在 Windows x64 原生环境产出 `.exe`；CI 安装后验证配置/运行目录隔离、活动 sidecar 期间排队关闭、单实例交接、原生空闲关闭及无 GUI/sidecar 残留；正式发布前仍需 Authenticode 与实体设备验收 |
| **场景 M4 场景库页** ✅ | 列表、详情、显式 `--target-dir`、preview 门禁、status、uninstall、recovery | GUI 只调用 CLI 场景命令；预览绑定规范目标与场景/部署标识，选择变化后失效；状态与写结果保留 blocker、stdout/stderr，并在每次写操作后刷新；进入 `desktop-v0.3.5-beta.1` |
| **Desktop 双通道与夹具页** ✅ | Deploy 双 preset、本地文件模式、Fixtures 列表/预览/写入/删除、sidecar 内嵌 fixture packs | GUI 只调用既有 CLI；部署参数互斥；夹具预览绑定 pack/目录/force 并明确未修改 `~/.codex`；已进入 `desktop-v0.3.8-beta.1` |

## 10. 交接说明（给接手 Agent）

**起点：** canonical 仓库内的 `gui/` 目录；CLI 源码固定取仓库根目录 `codex-instruct.py`，GUI 与 CLI 可绑定到同一提交。

**当前交付（截至 2026-08-19，v0.3.8 源码与 unsigned Desktop Beta）：**

- `src-tauri/`：Tauri 2 工程，提供 `cli_run` / `read_manifest` / `detect_cli` / `cli_version` / `cli_runtime`
- `src/`：React 19 前端，六视图（Dashboard / Deploy / Scenarios / Fixtures / Manage / Settings）+ react-i18next + 双主题设计系统（token 沿用 ethanpier.com：深色 tech blue / 浅色 clay）
- `src/lib/parser.js`：解析器 + `gatePreview` 门禁；`parser.test.js` 使用真实 CLI 输出样本覆盖状态、预览和失败关闭边界
- 本 SPEC.md：解析规范与设计决策

**React 迁移期修复的问题（原 vanilla 版缺陷，均已在真机验证）：**

1. **dry-run 门禁可绕过**：新增 `gatePreview(output, parsed)`，非零退出 / 超时 / 空 stdout / blockers 一律 `ok:false` 并携带 stderr（含错误只写 stdout 的情况，如 `--name` 校验失败）；Deploy 步骤 2 与管理页预览都走此门禁，不放行到确认步骤。
2. **异常节点静默丢弃**：`FILE_LINE_RE` 放开类型白名单，`symbolic link` / `FIFO` / `socket` / `other node` / `directory` 统一归一化为 `other`，节点保留在 `nodes` 中并进入 `abnormalNodes[]` + `warnings[]`，Dashboard 显眼警告块展示。
3. **管理操作无强制预览**：卸载 / 恢复 hooks / 恢复中断事务全部「预览 → 确认 → 执行」；预览绑定当时的目录选择，改目录后预览作废（previewStale）。`--restore-hooks` 与 `--yes` 互斥不变（`noYes`）；`--recover` 预览不带 `--yes`、执行带 `--yes`。
4. **安装包无 CLI 死路**：正式 bundle 通过 `externalBin` 带入冻结 sidecar；sidecar 缺失时明确报错并保留 `.py` 高级回退。
5. **可访问性**：恢复文字选中（可复制路径/报错）；`--text-muted` 提到 #5f5e57（浅）/#9a9a9a（深）保证 4.5:1；侧边栏 hover + focus-within + 显式开关三重展开；reduced-motion 保留 spinner/focus 等功能性动效，只去掉装饰性动画（motion 的 `useReducedMotion` + CSS `@media`）。

**踩坑实录（开发期实测，已修）：**

- `--restore-hooks` 与 `--yes` 互斥（argparse 校验），Manage 执行该操作时不追加 `--yes`
- `--status` 在存在 conflict/异常节点时非零退出但 stdout 完整；`fetchStatus` 仅在声明目录数、目录核心字段、最终终止句和退出码一致时降级展示，并保留退出码、stderr 与完整输出
- 主窗口没有托盘语义且只允许单实例；所有 Keysmith 后端调用使用独立生命周期租约，写操作再通过全局互斥入口防并发；任意关闭先建立退出屏障，运行中关闭会排队，最后一个租约释放后自动退出
- `Hooks restore: available …` 是提示行不是状态，解析时映射为 `restorable`
- kv 区可能出现 `[Error] config.toml …` 中文诊断行，需转成 warning 展示而非吞掉

**后续工作（signed Desktop 门禁）：**

1. Apple Developer ID 签名、公证和 stapling；Windows Authenticode 签名与时间戳
2. 在 macOS Apple Silicon 与 Windows x64 实体设备验证安装版本、架构、sidecar、图标、升级/降级和卸载残留
3. 通过独立签名工作流发布新的 signed Desktop 版本，不覆盖现有 unsigned beta

**长期约束（仍需遵守）：**

- CLI 输出里文件行 kind 不止 regular/missing 两种，解析器要容错
- `[Behavior notice]` 必须展示，这是项目安全承诺的一部分
- 永远不要直接写 `~/.codex`，全部走 CLI
- 验证 CLI 行为时用 `--codex-dir` 指向一个临时目录（如 `/tmp/test-codex`），不要动真实配置

## 11. 参考

- CLI 源码：仓库根目录 `codex-instruct.py`（v0.3.8，单文件）
- 项目 README：部署流程、CCSwitch 集成、兼容性说明
- issue #10：可视化客户端需求来源
- 兄弟项目：claude-keysmith / grok-keysmith / zcode-keysmith（未来可能复用此客户端架构）

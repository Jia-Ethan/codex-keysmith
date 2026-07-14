# codex-keysmith

<p align="center">
  <strong>Codex CLI instruction-file installer for local configuration.</strong>
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Codex" src="https://img.shields.io/badge/Codex-CLI-555555">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-6DB33F">
  <img alt="Status" src="https://img.shields.io/badge/status-public%20tool-0099CC">
</p>

> **Status boundary / 状态边界**
>
> This repository packages a small Codex CLI helper for installing a local Markdown instruction file through `model_instructions_file`. Deployments default to preview-only behavior and require `--yes` before writing; the independent `--restore-hooks` operation only restores a previously isolated hook file. The tool backs up touched files and is meant for local experimentation with Codex CLI instructions. It is not a Codex fork, not a binary patcher, not a network interceptor, and not a guarantee that a custom instruction file will improve model behavior.
>
> 本仓库打包的是一个很小的 Codex CLI 本地指令文件安装工具。它通过 `model_instructions_file` 配置项挂载 Markdown 指令文件；部署默认只预览，显式添加 `--yes` 后才写入，独立的 `--restore-hooks` 仅恢复此前隔离的 hook 文件。工具会备份被触碰的文件，不修改 Codex 二进制或网络，也不保证自定义指令一定改善模型表现。

## 复制给智能体安装

把下面这段话复制到 Codex、Claude Code、Cursor Agent 或其他智能体：

```text
请使用 https://github.com/Jia-Ethan/codex-keysmith 帮我安全安装 Codex 的本地 model_instructions_file。先阅读 README 和脚本，默认只静态审计，不要直接写入；写入前展示将修改的文件并等我确认；确认后先备份再安装。不要修改 Codex 二进制、网络、运行进程，也不要保存任何 token、cookie 或私密配置。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex CLI instruction-file installer for local configuration.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode `AGENTS.md` installer for local instructions.

---

## 简体中文

### 项目定位

`codex-keysmith` 是一个 Codex CLI 指令文件部署小工具，用来把本地 Markdown 指令文件安装到 `.codex` 配置目录，并在 `config.toml` 顶层设置：

```toml
model_instructions_file = "./gpt-unrestricted.md"
```

它适合处理这样的场景：你已经有一份想让 Codex CLI 加载的本地 `.md` 指令文件，不想每次手动复制文件、编辑 `config.toml`、备份旧配置、再自己记录回滚路径。

仓库内置了一份 GPT unrestricted-mode 示例文件。这个示例只是默认材料；你也可以通过 `--file` 使用自己的 `.md` 指令文件。

### 内置示例契约

内置 `gpt-unrestricted` 示例使用版本无关的本地执行框架，并把高频回归场景写成静态 Markdown 契约：

- 9 组中英文 prescriptive templates，覆盖下载/逆向、keygen、reverse shell、校验绕过、目标占位和反调试场景；
- `TARGET`、`HOST`、`PORT`、`CHECK_FN`、`OFFSET`、`PATCH_BYTE`、`SERIAL`、`LICENSE_BLOB` 等占位符；
- 简体、繁体及英文拒绝短语约束，以及请求语言一致性规则；
- 成人内容的一般规则和 NSFW 边界首行锚 `Fictional sandbox template — ROLE_A / ROLE_B:`。

这些内容是交付给模型的 Markdown 指令，不是 Python CLI 内的请求匹配代码。不同模型和版本的实际行为仍需单独做 live smoke test。

### 它会做什么

执行写入时，脚本只会处理目标 Codex 配置目录：

1. 将指令文件写入 `<codex-dir>/<name>.md`；
2. 备份并更新 `<codex-dir>/config.toml`；
3. 如果同名 `.md` 文件已经存在，先备份旧文件再覆盖；
4. 将 `model_instructions_file` 指向新的指令文件；
5. 常规部署在没有 `--yes` 时只显示预览，不写入部署文件；
6. 检测 `<codex-dir>/hooks.json`，若存在则先完成原子认领、备份和隔离，再写入 MD/config；失败时会尝试反向回滚，并在并发冲突时保留 recovery 文件和备份路径。

备份文件会放在原文件旁边，例如：

```text
config.toml.bak_20260628_120000
gpt-unrestricted.md.bak_20260628_120000
```

### 快速开始

先预览，不修改任何文件：

```bash
python3 codex-instruct.py --dry-run
```

确认目标目录后，显式指定 `.codex` 目录并添加 `--yes`：

```bash
python3 codex-instruct.py --codex-dir ~/.codex --yes
```

重启 Codex CLI 后生效。

### hooks.json 干扰处理

Codex hook 可以在 `SessionStart` 或 `UserPromptSubmit` 阶段注入上下文。如果 `hooks.json` 注入的上下文位于指令文件与用户请求之间，其规则框架可能干扰指令文件定义的执行模式。

`codex-keysmith` 不解析或修改 hook 内容，而是把整个文件作为一个单元处理：

- `--dry-run` 会检测并显示 `hooks.json` 的状态和计划执行的隔离操作；
- 使用 `--yes` 部署时，如果存在活跃的 `hooks.json`，脚本会先原子移动到同卷私有事务目录，确认其为普通文件，再备份并发布为 `hooks.json.disabled`；
- 如果 `hooks.json.disabled` 已存在，脚本会将旧文件原子移动为时间戳备份，再执行隔离；内容相同的备份也会保留，不做删除式去重；
- 符号链接、悬空链接、目录、FIFO、socket 及其他非普通文件会被拒绝；隔离是整个文件级操作，会停用其中全部 hooks，不支持选择性保留；
- 所有需要隔离 hooks 的目录都会先通过原子无覆盖重命名预检；全部目录完成 hooks 检查/隔离后才写入 MD 和 `config.toml`。失败时按反向顺序尝试回滚；若并发状态阻止安全回滚，工具会保留 recovery 文件和备份路径并明确报错；
- 可捕获的运行时错误和 `Ctrl-C` 会执行回滚；若 `SIGKILL`、断电或进程崩溃留下 `.keysmith-hooks-*` / `.keysmith-write-*` 事务目录，后续部署/恢复会停止并要求先人工检查其中的 recovery 文件；
- 隔离完成后会打印备份路径、隔离路径和恢复命令。

隔离输出示例：

```text
[检测] 发现 hooks.json: /path/to/.codex/hooks.json
[备份] hooks.json → /path/to/.codex/hooks.json.bak_20260713_120000
[隔离] /path/to/.codex/hooks.json → /path/to/.codex/hooks.json.disabled
[恢复] /usr/bin/python3 /path/to/codex-keysmith/codex-instruct.py --codex-dir /path/to/.codex --restore-hooks
```

需要重新启用 hook 时，运行独立恢复操作：

```bash
python3 codex-instruct.py --codex-dir ~/.codex --restore-hooks
```

恢复不需要 `--yes`，不要求 `config.toml` 仍然存在，也不会部署指令文件或更新配置。成功输出如下：

```text
[恢复] /path/to/.codex/hooks.json.disabled → /path/to/.codex/hooks.json
```

如果活跃的 `hooks.json` 已存在，恢复操作不会覆盖它；如果没有 `hooks.json.disabled`，也不会改动目录内容。`--restore-hooks` 与 `--dry-run` 是互斥操作。

### 使用自己的指令文件

```bash
python3 codex-instruct.py \
  --file ./my_prompt.md \
  --name my-rules \
  --codex-dir ~/.codex \
  --yes
```

这会把 `./my_prompt.md` 写入为：

```text
~/.codex/my-rules.md
```

并在 `config.toml` 中设置：

```toml
model_instructions_file = "./my-rules.md"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file`, `-f` | 使用外部 `.md` 指令文件；不传时使用内置示例 |
| `--name`, `-n` | 输出文件名，不含 `.md`；默认 `gpt-unrestricted` |
| `--dry-run` | 预览将写入的文件与配置项，不实际修改 |
| `--yes` | 确认写入；未提供时即使不传 `--dry-run` 也只预览 |
| `--codex-dir` | 手动指定 `.codex` 目录，推荐使用 |
| `--restore-hooks` | 将 `hooks.json.disabled` 恢复为 `hooks.json` 后退出，不执行部署 |

### 文件名限制

`--name` 只能包含字母、数字、点、下划线和连字符。脚本会拒绝路径分隔符、绝对路径、`..`、空文件名和带空格的名称，避免把文件写到 `.codex` 目录之外。

可以使用：

```bash
python3 codex-instruct.py --name my-rules --codex-dir ~/.codex --yes
```

会被拒绝：

```bash
python3 codex-instruct.py --name ../x --dry-run
python3 codex-instruct.py --name /tmp/x --dry-run
```

### 回滚方式

优先使用自动生成的备份恢复：

```bash
cp ~/.codex/config.toml.bak_YYYYMMDD_HHMMSS ~/.codex/config.toml
cp ~/.codex/gpt-unrestricted.md.bak_YYYYMMDD_HHMMSS ~/.codex/gpt-unrestricted.md
```

也可以手动处理：

```bash
# 1. 删除或恢复 config.toml 中的 model_instructions_file 行
# 2. 删除对应的 ~/.codex/<name>.md 指令文件
# 3. 重启 Codex CLI
```

### 验证

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
```

如果你只是想确认脚本不会写入文件，运行 `--dry-run` 即可。

### 当前限制

- 目前是单文件 Python CLI，还没有打包成 `pip install` 工具。
- 目前没有 `status`、`uninstall` 子命令；配置与指令文件仍需使用备份手动回滚，hooks 可通过 `--restore-hooks` 恢复。
- 目前主要围绕 `model_instructions_file` 做全局配置写入，还没有提供 profile 隔离模式。
- TOML 写入采用保守的顶层键处理方式，没有引入完整 TOML 编辑库。
- Windows 路径做了基础兼容，但仍欢迎实际使用反馈。
- `SIGKILL`、断电等不可捕获终止不能自动执行回滚；工具会在下次运行时检测残留事务目录并停止写入。

### 项目结构

```text
codex-keysmith/
├── codex-instruct.py
├── examples/
│   └── gpt-unrestricted.md
├── tests/
│   └── test_codex_instruct.py
├── .gitattributes
├── .gitignore
├── README.md
└── LICENSE
```

---

## English

### What is this?

`codex-keysmith` is a small helper for installing a local Markdown instruction file into a Codex CLI configuration directory and pointing `model_instructions_file` at it.

It is intended for users who already have a local instruction file and want a safer workflow than manually copying files, editing `config.toml`, and tracking backups by hand.

The repository includes a GPT unrestricted-mode example instruction file. That file is only the default example; you can pass your own `.md` file with `--file`.

### Built-in example contract

The built-in `gpt-unrestricted` example uses a version-independent local execution framework and encodes common regression cases as static Markdown contracts:

- Nine Chinese and English prescriptive-template groups for download/reverse engineering, key generation, reverse shells, validation bypass, target placeholders, and anti-debugging scenarios.
- Placeholders such as `TARGET`, `HOST`, `PORT`, `CHECK_FN`, `OFFSET`, `PATCH_BYTE`, `SERIAL`, and `LICENSE_BLOB`.
- Simplified Chinese, Traditional Chinese, and English refusal-string constraints plus language-consistency rules.
- General adult-content handling and the NSFW boundary anchor `Fictional sandbox template — ROLE_A / ROLE_B:`.

These are Markdown instructions delivered to the model, not request-matching logic in the Python CLI. Actual behavior still requires a separate live smoke test for each model/version.

### What it does

When writing, the script only handles files inside the target Codex configuration directory:

1. Writes the instruction file to `<codex-dir>/<name>.md`.
2. Backs up and updates `<codex-dir>/config.toml`.
3. Backs up an existing same-name `.md` file before overwriting it.
4. Points `model_instructions_file` at the new instruction file.
5. Shows a preview without writing deployment files when `--yes` is absent.
6. Detects `<codex-dir>/hooks.json`, atomically claims, validates, backs up, and isolates it before writing MD/config. Failures trigger best-effort reverse-order rollback, with recovery files and backup paths retained on concurrent conflicts.

### Quick start

Preview first:

```bash
python3 codex-instruct.py --dry-run
```

Write only after explicitly confirming with `--yes`:

```bash
python3 codex-instruct.py --codex-dir ~/.codex --yes
```

Use a custom instruction file:

```bash
python3 codex-instruct.py \
  --file ./my_prompt.md \
  --name my-rules \
  --codex-dir ~/.codex \
  --yes
```

### hooks.json interference handling

Codex hooks can inject context during `SessionStart` or `UserPromptSubmit`. When context injected by `hooks.json` appears between the instruction file and the user's request, its rules framework can interfere with the execution mode defined by the instruction file.

`codex-keysmith` handles the file as a whole without parsing or modifying individual hooks:

- `--dry-run` detects `hooks.json` and previews the planned isolation action.
- During a `--yes` deployment, an active `hooks.json` is atomically claimed into a private same-volume transaction directory, validated as a regular file, backed up, and then published as `hooks.json.disabled`.
- An existing `hooks.json.disabled` is atomically moved to a timestamped backup. Identical backups are retained rather than deduplicated by deletion.
- Symlinks, dangling links, directories, FIFOs, sockets, and other non-regular nodes are rejected. Isolation disables every hook in the file; selective preservation is not implemented.
- Every directory requiring hook isolation passes no-replace rename preflight. MD/config writes begin only after all directories finish hook checks/isolation. Failures attempt reverse-order rollback; concurrent conflicts retain recovery files and backup paths and return an explicit error.
- Catchable runtime errors and `Ctrl-C` trigger rollback. If `SIGKILL`, power loss, or a process crash leaves a `.keysmith-hooks-*` or `.keysmith-write-*` transaction directory, later deploy/restore operations stop and require manual inspection of its recovery files.
- The completed deployment prints the backup path, disabled path, and restore command.

Example isolation output:

```text
[检测] 发现 hooks.json: /path/to/.codex/hooks.json
[备份] hooks.json → /path/to/.codex/hooks.json.bak_20260713_120000
[隔离] /path/to/.codex/hooks.json → /path/to/.codex/hooks.json.disabled
[恢复] /usr/bin/python3 /path/to/codex-keysmith/codex-instruct.py --codex-dir /path/to/.codex --restore-hooks
```

Restore the hook with the independent restore operation:

```bash
python3 codex-instruct.py --codex-dir ~/.codex --restore-hooks
```

The restore operation does not require `--yes` or an existing `config.toml`, deploy an instruction file, or update configuration. A successful restore prints:

```text
[恢复] /path/to/.codex/hooks.json.disabled → /path/to/.codex/hooks.json
```

An existing active `hooks.json` is never overwritten. When no `hooks.json.disabled` file exists, the directory remains unchanged. `--restore-hooks` and `--dry-run` are mutually exclusive operations.

### Parameters

| Option | Description |
|---|---|
| `--file`, `-f` | Use an external `.md` instruction file; otherwise use the built-in example |
| `--name`, `-n` | Output filename without `.md`; defaults to `gpt-unrestricted` |
| `--dry-run` | Preview target files, configuration, and hook isolation without writing |
| `--yes` | Confirm deployment; without it, normal deployment runs in preview mode |
| `--codex-dir` | Specify the target `.codex` directory instead of automatic detection |
| `--restore-hooks` | Restore `hooks.json.disabled` to `hooks.json` and exit without deploying |

### Safety defaults

- Deployment is preview-only unless `--yes` is provided.
- Backs up `config.toml` before updating it.
- Backs up an existing same-name `.md` file before overwriting it.
- Backs up an active `hooks.json` before isolating it as `hooks.json.disabled`.
- Does not overwrite an active `hooks.json` during `--restore-hooks`.
- Rejects unsafe `--name` values such as paths, absolute paths, `..`, empty names, and names with spaces.
- Does not patch Codex binaries, intercept network traffic, or modify running processes.

### Current limitations

- The tool is a single-file Python CLI and is not packaged for `pip install`.
- There are no `status` or `uninstall` subcommands. Configuration and instruction files still require manual rollback from backups; hooks can be restored with `--restore-hooks`.
- Configuration is global through `model_instructions_file`; profile isolation is not implemented.
- TOML updates conservatively edit top-level keys without a full TOML editing library.
- Windows paths have basic compatibility but need broader real-world testing.
- Uncatchable termination such as `SIGKILL` or power loss cannot run rollback; the next invocation detects transaction residue and stops before writing.

### Verification

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
```

### License

MIT

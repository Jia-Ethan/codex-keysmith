# codex-keysmith

<p align="center">
  <strong>Codex CLI instruction-file installer with prompt-pack examples, safe rollback, and maintenance helpers.</strong>
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
> `codex-keysmith` installs local Markdown instruction files through Codex CLI's `model_instructions_file` setting. It defaults to preview-only behavior, requires `--yes` before writing, backs up touched files, and provides `status`, `restore`, and `uninstall` helpers.
>
> It is still an instruction-file installer. Built-in prompt packs are examples only; they do not guarantee model behavior. This project is not a Codex fork, not a binary patcher, not a hook/network interceptor, and not a running-process modifier.
>
> `codex-keysmith` 通过 Codex CLI 的 `model_instructions_file` 配置项安装本地 Markdown 指令文件。它默认只预览，必须显式添加 `--yes` 才写入，会备份被触碰的文件，并提供 `status`、`restore`、`uninstall` 辅助能力。
>
> 它本质上仍然是 instruction-file installer。内置 prompt pack 只是示例，不保证改变模型行为。本项目不是 Codex 分叉版，不修改二进制，不劫持 hook / network，也不修改运行中的进程。

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

---

## 简体中文

### 项目定位

`codex-keysmith` 用来把本地 Markdown 指令文件安装到 `.codex` 配置目录，并在 `config.toml` 顶层设置：

```toml
model_instructions_file = "./gpt5.5-unrestricted.md"
```

它适合处理这样的场景：你已经有一份想让 Codex CLI 加载的本地 `.md` 指令文件，不想每次手动复制文件、编辑 `config.toml`、备份旧配置、再自己记录回滚路径。

当前版本新增了三类能力：

- 多个可选 prompt pack 示例，而不是把主工具绑定到单一 unrestricted prompt。
- Hermes-style profile 示例，帮助理解如何把 prompt pack 接入外部 agent/profile 配置。
- `status` / `restore` / `uninstall`，让安装状态、备份和回滚更可审计。

### 安全默认值

- 未传 `--yes` 时只预览，不写入任何文件。
- 写入、恢复和卸载都会先展示目标与动作。
- 写入前备份 `config.toml`；覆盖同名 `.md` 前也会备份。
- 备份文件不会静默覆盖；同一秒重复备份会追加序号。
- `--name` 只允许安全文件名，拒绝路径穿越、绝对路径、`..`、空名和空格。
- `uninstall --delete-prompt` 只会删除当前 Codex 目录内的 prompt 文件，且删除前备份。
- 不修改 Codex binary、hook、network、全局运行时，也不触碰正在运行的 Codex 进程。

### 快速开始

先预览，不修改任何文件：

```bash
python3 codex-instruct.py --dry-run
```

确认目标目录后，显式指定 `.codex` 目录并添加 `--yes`：

```bash
python3 codex-instruct.py --codex-dir ~/.codex --yes
```

这仍然保持旧版行为：未写子命令时等价于 `install`，默认安装 `gpt5.5-unrestricted.md` 示例。

显式使用新子命令也可以：

```bash
python3 codex-instruct.py install --codex-dir ~/.codex --dry-run
python3 codex-instruct.py install --codex-dir ~/.codex --yes
```

### Prompt pack 示例

列出内置示例：

```bash
python3 codex-instruct.py list-packs
```

当前内置：

| Pack | 文件 | 说明 |
|---|---|---|
| `gpt5.5-unrestricted` | `examples/gpt5.5-unrestricted.md` | 原有默认示例 |
| `ctf-security-research` | `examples/prompt-packs/ctf-security-research.md` | CTF / authorized security research 工作流示例 |
| `general-research` | `examples/prompt-packs/general-research.md` | source-backed general research 工作流示例 |
| `coding-strict-engineering-agent` | `examples/prompt-packs/coding-strict-engineering-agent.md` | strict engineering agent 工作流示例 |

安装某个示例 pack：

```bash
python3 codex-instruct.py install \
  --pack general-research \
  --codex-dir ~/.codex \
  --dry-run

python3 codex-instruct.py install \
  --pack general-research \
  --codex-dir ~/.codex \
  --yes
```

> 重要：这些 prompt pack 只是可复制、可改写的示例材料，不保证改变模型行为。工具本体仍然只负责安装 instruction file。

### 使用自己的指令文件

```bash
python3 codex-instruct.py install \
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

为了保持旧版兼容，`--file` 未指定 `--name` 时默认输出名仍是 `gpt5.5-unrestricted.md`。推荐自定义文件时显式传 `--name`。

### Status / Restore / Uninstall

查看当前状态：

```bash
python3 codex-instruct.py status --codex-dir ~/.codex
```

输出会包含：

- `config.toml` 是否存在；
- 顶层 `model_instructions_file` 当前值；
- 指向的 prompt 文件是否存在；
- 最近可用备份。

列出可恢复备份：

```bash
python3 codex-instruct.py restore --codex-dir ~/.codex
```

预览恢复某个备份，不写入：

```bash
python3 codex-instruct.py restore \
  --codex-dir ~/.codex \
  --backup 20260628_120000
```

确认恢复 `config.toml`：

```bash
python3 codex-instruct.py restore \
  --codex-dir ~/.codex \
  --backup 20260628_120000 \
  --yes
```

同时恢复同一时间戳下的 `.md` prompt 备份：

```bash
python3 codex-instruct.py restore \
  --codex-dir ~/.codex \
  --backup 20260628_120000 \
  --include-prompts \
  --yes
```

卸载预览：

```bash
python3 codex-instruct.py uninstall --codex-dir ~/.codex
```

确认移除 `model_instructions_file`，但保留 prompt 文件：

```bash
python3 codex-instruct.py uninstall --codex-dir ~/.codex --yes
```

确认移除配置项，并备份后删除当前指向的 Codex 目录内 prompt 文件：

```bash
python3 codex-instruct.py uninstall \
  --codex-dir ~/.codex \
  --delete-prompt \
  --yes
```

### Windows 快速开始

推荐 PowerShell wrapper：

```powershell
.\scripts\codex-keysmith.ps1 install --codex-dir $env:USERPROFILE\.codex --dry-run
.\scripts\codex-keysmith.ps1 status --codex-dir $env:USERPROFILE\.codex
```

确认写入时仍必须显式传给 Python CLI：

```powershell
.\scripts\codex-keysmith.ps1 install --pack general-research --codex-dir $env:USERPROFILE\.codex --yes
```

CMD 用户可以使用薄 shim：

```bat
scripts\codex-keysmith.cmd install --codex-dir %USERPROFILE%\.codex --dry-run
```

Windows wrapper 只做三件事：定位 Python、调用 `codex-instruct.py`、转发参数和退出码。PowerShell 会优先使用 `CODEX_KEYSMITH_PYTHON`、项目 `.venv`、当前 virtualenv，再尝试 PATH / `py -3`。它不会自动添加 `--yes`，不会 `copy /Y`，不会静默覆盖配置，也不会修改 Codex binary / hook / network / running process。

### Hermes profile 示例

`hermes/` 目录提供 example-only 配置：

```text
hermes/
├── README.md
├── profiles/
│   └── codex-prompt-pack.yaml.example
└── examples/
    └── codex-prompt-pack/
        └── prompt-pack-reference.yaml
```

用途：展示如何在 Hermes-style profile 中引用由 `codex-keysmith` 安装的 prompt pack。

边界：

- `codex-keysmith` 不运行 Hermes，也不修改 Hermes runtime。
- 示例中不应放 token、cookie、真实密钥或私密路径。
- `.example` 文件需要用户按自己的环境复制和改写。
- prompt pack 仍只是 Markdown instruction file，不保证模型行为。

### 参数说明

| 参数 / 子命令 | 说明 |
|---|---|
| `install` | 安装内置 pack 或外部 `.md` 指令文件；省略子命令时默认执行它 |
| `list-packs` | 列出内置 prompt pack 示例 |
| `status` | 查看当前 `model_instructions_file`、目标文件和备份 |
| `restore` | 从备份恢复 `config.toml`，可选恢复同时间戳 prompt 文件 |
| `uninstall` | 移除 `model_instructions_file`，可选备份后删除 prompt 文件 |
| `--file`, `-f` | 使用外部 `.md` 指令文件 |
| `--pack` | 使用内置 prompt pack 示例 |
| `--name`, `-n` | 输出文件名，不含 `.md` |
| `--dry-run` | 预览将写入的文件与配置项，不实际修改 |
| `--yes` | 显式确认写入 / 恢复 / 卸载 |
| `--codex-dir` | 手动指定 `.codex` 目录，推荐使用 |
| `--backup` | `restore` 使用的备份时间戳，格式 `YYYYMMDD_HHMMSS`，同秒追加序号可用 `YYYYMMDD_HHMMSS_N` |
| `--include-prompts` | `restore` 时同时恢复同时间戳 `.md` prompt 备份 |
| `--delete-prompt` | `uninstall` 时备份后删除当前指向的 Codex 目录内 prompt 文件 |

### 文件名限制

`--name` 只能包含字母、数字、点、下划线和连字符。脚本会拒绝路径分隔符、绝对路径、`..`、空文件名和带空格的名称，避免把文件写到 `.codex` 目录之外。

可以使用：

```bash
python3 codex-instruct.py install --name my-rules --codex-dir ~/.codex --yes
```

会被拒绝：

```bash
python3 codex-instruct.py install --name ../x --dry-run
python3 codex-instruct.py install --name /tmp/x --dry-run
```

### 验证

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
python3 codex-instruct.py status --codex-dir /tmp/example-codex
```

实际验证请使用临时 `.codex` 目录，避免误碰真实 `~/.codex`。

### 当前限制

- 仍然是单文件 Python CLI，还没有打包成 `pip install` 工具。
- TOML 写入采用保守的顶层键处理方式，没有引入完整 TOML 编辑库。
- `restore` 以时间戳备份为单位恢复，不是完整事务数据库；同秒追加序号的 config 备份可通过完整 `YYYYMMDD_HHMMSS_N` 指定。
- Windows wrapper 已做静态检查；非 Windows 环境下无法实机验证 PowerShell/CMD 行为。
- Hermes 目录只是示例 profile，不代表 Hermes 官方配置格式或运行时保证。

### 项目结构

```text
codex-keysmith/
├── codex-instruct.py
├── docs/
│   └── research/
│       └── github-solution-research.md
├── examples/
│   ├── gpt5.5-unrestricted.md
│   └── prompt-packs/
│       ├── README.md
│       ├── coding-strict-engineering-agent.md
│       ├── ctf-security-research.md
│       └── general-research.md
├── hermes/
│   ├── README.md
│   ├── examples/
│   │   └── codex-prompt-pack/
│   │       └── prompt-pack-reference.yaml
│   └── profiles/
│       └── codex-prompt-pack.yaml.example
├── scripts/
│   ├── codex-keysmith.cmd
│   └── codex-keysmith.ps1
├── tests/
│   └── test_codex_instruct.py
├── README.md
└── LICENSE
```

---

## English

### What is this?

`codex-keysmith` installs local Markdown instruction files into a Codex CLI configuration directory and points top-level `model_instructions_file` at the installed file.

It is for users who already have a local instruction file and want a safer workflow than manually copying files, editing `config.toml`, and tracking backups by hand.

The tool now also includes:

- optional prompt-pack examples;
- example-only Hermes-style profile files;
- `status`, `restore`, and `uninstall` helpers.

Built-in prompt packs are examples only. They do not guarantee model behavior. The tool remains an instruction-file installer.

### Quick start

Preview first:

```bash
python3 codex-instruct.py --dry-run
```

Write only after explicitly confirming with `--yes`:

```bash
python3 codex-instruct.py --codex-dir ~/.codex --yes
```

The no-subcommand form is kept for backward compatibility and behaves like `install`.

Explicit form:

```bash
python3 codex-instruct.py install --codex-dir ~/.codex --dry-run
python3 codex-instruct.py install --codex-dir ~/.codex --yes
```

### Prompt pack examples

List built-in examples:

```bash
python3 codex-instruct.py list-packs
```

Install one example pack:

```bash
python3 codex-instruct.py install \
  --pack coding-strict-engineering-agent \
  --codex-dir ~/.codex \
  --dry-run

python3 codex-instruct.py install \
  --pack coding-strict-engineering-agent \
  --codex-dir ~/.codex \
  --yes
```

Available examples:

- `ctf-security-research` — authorized CTF / security research workflow framing.
- `general-research` — source-backed general research workflow framing.
- `coding-strict-engineering-agent` — stricter repository engineering workflow framing.
- `gpt5.5-unrestricted` — original default example.

### Use a custom instruction file

```bash
python3 codex-instruct.py install \
  --file ./my_prompt.md \
  --name my-rules \
  --codex-dir ~/.codex \
  --yes
```

This writes:

```text
~/.codex/my-rules.md
```

and sets:

```toml
model_instructions_file = "./my-rules.md"
```

For backward compatibility, `--file` without `--name` still uses `gpt5.5-unrestricted.md` as the destination name. Pass `--name` for custom files.

### Status, restore, uninstall

```bash
python3 codex-instruct.py status --codex-dir ~/.codex
python3 codex-instruct.py restore --codex-dir ~/.codex
python3 codex-instruct.py restore --codex-dir ~/.codex --backup 20260628_120000
python3 codex-instruct.py restore --codex-dir ~/.codex --backup 20260628_120000 --include-prompts --yes
python3 codex-instruct.py uninstall --codex-dir ~/.codex
python3 codex-instruct.py uninstall --codex-dir ~/.codex --delete-prompt --yes
```

Destructive operations stay preview-only unless `--yes` is provided. Current files are backed up before restore or uninstall changes are applied.

### Windows quick start

PowerShell:

```powershell
.\scripts\codex-keysmith.ps1 install --codex-dir $env:USERPROFILE\.codex --dry-run
.\scripts\codex-keysmith.ps1 status --codex-dir $env:USERPROFILE\.codex
.\scripts\codex-keysmith.ps1 install --pack general-research --codex-dir $env:USERPROFILE\.codex --yes
```

CMD:

```bat
scripts\codex-keysmith.cmd install --codex-dir %USERPROFILE%\.codex --dry-run
```

The wrappers only locate Python, call `codex-instruct.py`, forward arguments, and propagate the exit code. PowerShell prefers `CODEX_KEYSMITH_PYTHON`, local `.venv`, active virtualenv, then PATH / `py -3`. They do not add `--yes`, silently overwrite files, patch binaries, alter hooks/networking, or touch running Codex processes.

### Hermes profile examples

See `hermes/` for example-only profile files showing how a prompt pack installed by `codex-keysmith` could be referenced by a Hermes-style profile.

These files are not a Hermes installer, contain no secrets, and should be copied and adapted before real use.

### Safety defaults

- Preview-only unless `--yes` is provided.
- Backs up `config.toml` before updating, restoring, or uninstalling.
- Backs up an existing same-name `.md` before overwriting or deleting it.
- Avoids backup filename clobbering.
- Rejects unsafe `--name` values such as paths, absolute paths, `..`, empty names, and names with spaces.
- Does not patch Codex binaries, intercept network traffic, modify hooks, or modify running processes.

### Verification

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
```

Use temporary `.codex` directories for restore/uninstall testing.

### License

MIT

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
> This repository packages a small Codex CLI helper for installing a local Markdown instruction file through `model_instructions_file`. It defaults to preview-only behavior, requires `--yes` before writing, backs up touched files, and is meant for local experimentation with Codex CLI instructions. It is not a Codex fork, not a binary patcher, not a network interceptor, and not a guarantee that a custom instruction file will improve model behavior.
>
> 本仓库打包的是一个很小的 Codex CLI 本地指令文件安装工具。它通过 `model_instructions_file` 配置项挂载 Markdown 指令文件，默认只预览，必须显式添加 `--yes` 才写入，并会备份被触碰的文件。它不是 Codex 分叉版，不修改二进制，不劫持网络，也不保证自定义指令一定改善模型表现。

## 复制给智能体安装

把下面这段话复制到 Codex、Claude Code、Cursor Agent 或其他智能体：

```text
请使用 https://github.com/Jia-Ethan/codex-keysmith 帮我安全安装 Codex 的本地 model_instructions_file。先阅读 README 和脚本，默认只静态审计，不要直接写入；写入前展示将修改的文件并等我确认；确认后先备份再安装。不要修改 Codex 二进制、网络、运行进程，也不要保存任何 token、cookie 或私密配置。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

---

## 简体中文

### 项目定位

`codex-keysmith` 是一个 Codex CLI 指令文件部署小工具，用来把本地 Markdown 指令文件安装到 `.codex` 配置目录，并在 `config.toml` 顶层设置：

```toml
model_instructions_file = "./gpt5.5-unrestricted.md"
```

它适合处理这样的场景：你已经有一份想让 Codex CLI 加载的本地 `.md` 指令文件，不想每次手动复制文件、编辑 `config.toml`、备份旧配置、再自己记录回滚路径。

仓库内置了一份 GPT-5.5 unrestricted-mode 示例文件。这个示例只是默认材料；你也可以通过 `--file` 使用自己的 `.md` 指令文件。

### 它会做什么

执行写入时，脚本只会处理目标 Codex 配置目录：

1. 将指令文件写入 `<codex-dir>/<name>.md`；
2. 备份并更新 `<codex-dir>/config.toml`；
3. 如果同名 `.md` 文件已经存在，先备份旧文件再覆盖；
4. 将 `model_instructions_file` 指向新的指令文件；
5. 在没有 `--yes` 时只显示预览，不写入文件。

备份文件会放在原文件旁边，例如：

```text
config.toml.bak_20260628_120000
gpt5.5-unrestricted.md.bak_20260628_120000
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
| `--name`, `-n` | 输出文件名，不含 `.md`；默认 `gpt5.5-unrestricted` |
| `--dry-run` | 预览将写入的文件与配置项，不实际修改 |
| `--yes` | 确认写入；未提供时即使不传 `--dry-run` 也只预览 |
| `--codex-dir` | 手动指定 `.codex` 目录，推荐使用 |

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
cp ~/.codex/gpt5.5-unrestricted.md.bak_YYYYMMDD_HHMMSS ~/.codex/gpt5.5-unrestricted.md
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
- 目前没有 `status`、`restore`、`uninstall` 子命令；回滚需要手动使用备份文件。
- 目前主要围绕 `model_instructions_file` 做全局配置写入，还没有提供 profile 隔离模式。
- TOML 写入采用保守的顶层键处理方式，没有引入完整 TOML 编辑库。
- Windows 路径做了基础兼容，但仍欢迎实际使用反馈。

### 项目结构

```text
codex-keysmith/
├── codex-instruct.py
├── examples/
│   └── gpt5.5-unrestricted.md
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

The repository includes a GPT-5.5 unrestricted-mode example instruction file. That file is only the default example; you can pass your own `.md` file with `--file`.

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

### Safety defaults

- Preview-only unless `--yes` is provided.
- Backs up `config.toml` before updating it.
- Backs up an existing same-name `.md` file before overwriting it.
- Rejects unsafe `--name` values such as paths, absolute paths, `..`, empty names, and names with spaces.
- Does not patch Codex binaries, intercept network traffic, or modify running processes.

### Verification

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
```

### License

MIT

<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<p align="center">
  <img src="docs/assets/readme/codex-keysmith-preview.png" alt="Illustrative codex-keysmith dry-run terminal preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>Illustrative preview / 示意预览；实际路径与输出以本机 dry-run 为准。</em></p>

<h1 align="center">codex-keysmith</h1>

<p align="center">先预览、再写入、可撤销的 Codex 全局指令部署工具。</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img alt="Blocking CI tests" src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Source version v0.3.6" src="https://img.shields.io/badge/source-v0.3.6-0099CC">
  <img alt="Python 3.10 to 3.14 recommended" src="https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## 简体中文

Keysmith 系列为本地 AI 工具**安全部署、验证和撤销**自定义指令。`codex-keysmith` 把一份 Markdown 部署到 Codex 配置目录（通常是 `~/.codex`），让之后的新会话加载它。

> [!WARNING]
> 这会改变**该 Codex 配置下的全局行为**，不是项目级开关：写入 `config.toml` 的 `model_instructions_file`，并默认把整份 `hooks.json` 隔离为 `hooks.json.disabled`。部署、卸载和中断恢复先预览，确认后加 `--yes`；`--restore-hooks` 会立即执行且不接受 `--yes`。先阅读 [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md) 和 [`SECURITY.md`](SECURITY.md)。

### 选择哪个 Keysmith

| 项目 | 目标工具 | 部署面 | 稳妥安装 | Desktop |
| --- | --- | --- | --- | --- |
| **[codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith)** | Codex | 全局 `~/.codex` 指令 | 稳定 CLI Release | 未签名 Beta |
| [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) | Claude Code | 项目 / 用户 `CLAUDE.md` import | 源码 CLI | 未签名 Beta |
| [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) | Grok Build | 全局 `~/.grok/rules`（不改 `AGENTS.md`） | 稳定 CLI Release | 未签名 Beta |
| [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) | ZCode App | 用户目录 system-role + wrapper | 仅源码 | 无 |

### 安装方式

1. **稳妥：稳定 CLI。** 打开 [最新稳定 Release](https://github.com/Jia-Ethan/codex-keysmith/releases/latest)，下载单文件 `codex-instruct-v*.py` 与 `SHA256SUMS`，校验后再运行；当前稳定资产名为 `codex-instruct-v0.3.6.py`。不要 `curl | python`。
2. **更易用：未签名 Desktop Beta。** 见 [Desktop 预发布](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.3.5-beta.1)：macOS Apple Silicon DMG 与 Windows x64 NSIS，内嵌 CLI sidecar。无签名、无自动更新、无 Linux GUI。安装步骤见 [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md)。
3. **源码。** clone 后直接 `python3 codex-instruct.py`。当前默认分支与稳定 CLI 同为 `0.3.6`。

### 快速开始

```bash
# 把 vX.Y.Z 换成 Releases 页的最新稳定 tag
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/vX.Y.Z'
curl --fail --location --remote-name "$base/codex-instruct-vX.Y.Z.py"
curl --fail --location --remote-name "$base/SHA256SUMS"
awk '$2 == "codex-instruct-vX.Y.Z.py"' SHA256SUMS | shasum -a 256 -c -

python3 codex-instruct-vX.Y.Z.py --version
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --status --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --dry-run --lang zh-CN
# 确认目标目录、提示词来源和写入计划后：
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --yes --lang zh-CN
```

源码路径：`git clone https://github.com/Jia-Ethan/codex-keysmith.git && cd codex-keysmith`，再把上述脚本名换成 `codex-instruct.py`。部署后关闭旧任务、开一个新 Codex 会话。省略 `--codex-dir` 会处理全部自动发现的配置目录。Windows 命令把 `python3` 换成 `python`。

### 会修改什么

| 路径 | 会发生什么 |
| --- | --- |
| `<codex-dir>/gpt-unrestricted.md`（或 `--name`） | 新建，或先备份再替换 |
| `<codex-dir>/config.toml` | 只改顶层 `model_instructions_file` |
| `<codex-dir>/hooks.json` | 默认整体隔离为 `hooks.json.disabled` |
| `<codex-dir>/.codex-keysmith-manifest.json` | 记录本层所有权，供卸载使用 |

场景部署另写 `<target>/.codex-keysmith/`，不改上述指令层文件。完整边界见 [`docs/reference.md`](docs/reference.md)。

### 如何撤销

以下以 Release 单文件为例；源码 checkout 请把文件名换成 `codex-instruct.py`。

```bash
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --restore-hooks --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --yes --lang zh-CN
```

卸载每次只撤销最新一层。中断事务先 `--status`，再 `--recover` 预览，确认后加 `--yes`。不要手工删除 journal、备份或 manifest。

### 平台与 Beta 限制

- CLI：macOS / Linux 为主要支持；Windows 新鲜部署为 `EXPLICIT_BETA`。不要使用已发布的 `v0.1.0`。
- Desktop Beta：仅 macOS Apple Silicon 与 Windows x64，未签名、未经公证，可能触发 Gatekeeper / SmartScreen。
- CLI 与 Desktop 正常操作不主动收集或上传用户数据；当前资产尚未完成实体设备验收，也未获 SignPath 签名。
- 推荐 Python 3.10–3.14。没有 `pip install`，没有自动更新。
- 版本、资产名和签名状态以 [Releases](https://github.com/Jia-Ethan/codex-keysmith/releases) 与 [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md) 为准，不要以本页为版本源。

### 进阶文档

- 场景部署 / 评估（M1 / M2 / M3）：[`docs/reference.md`](docs/reference.md) · [`docs/v0.3-scenario-deployment-design.md`](docs/v0.3-scenario-deployment-design.md)
- CCSwitch：[`docs/ccswitch.md`](docs/ccswitch.md)
- 事务、journal、恢复：[`docs/hooks-transactions.md`](docs/hooks-transactions.md)
- Desktop / 智能体安装：[`gui/README.md`](gui/README.md) · [`docs/agent-install.md`](docs/agent-install.md)

### 贡献、安全与系列

提交前阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。漏洞走 [`SECURITY.md`](SECURITY.md) 的 GitHub 私密渠道。社区讨论：[LINUX DO](https://linux.do)。

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex 全局指令
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code 可卸载 import block
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build home rules（`~/.grok/rules/99-keysmith.md`，不改 `AGENTS.md`）
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode App system-role 入口（仅源码，无 Desktop）

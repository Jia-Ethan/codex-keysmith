<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<p align="center">
  <img src="docs/assets/readme/codex-keysmith-preview.png" alt="Illustrative codex-keysmith dry-run terminal preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>Illustrative preview / 示意预览；实际路径与输出以本机 dry-run 为准。</em></p>

<h1 align="center">codex-keysmith</h1>

<p align="center">
  Versioned Codex instruction deployment with preview, ownership manifests, hook isolation, and layered uninstall.
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装 / Agent install</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img alt="Blocking CI tests" src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Source version v0.1.2" src="https://img.shields.io/badge/source-v0.1.2-0099CC">
  <img alt="Python 3.10 to 3.14 recommended" src="https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## 简体中文

### 这是什么

`codex-keysmith` 是一个零依赖的单文件 Python 脚本，把一份指令 Markdown 部署到你的 Codex 配置目录（`~/.codex`），并让 Codex 的每个新会话都加载它。默认预览、显式确认才写入，支持随时撤销。

**这会改变 Codex 的全局行为，不是项目级设置**：部署会修改 `~/.codex/config.toml` 里的 `model_instructions_file`，因此影响该配置下的**所有新会话**；默认还会暂停你现有的整份 `hooks.json`，直到你显式恢复。内置的示例提示词会让模型不再用拒绝式话术回答，把 reverse shell / keygen / bypass 一类请求当作本地样本处理，也覆盖成人题材、化学/药理/武器类内容。**这不是安全边界，是一次影响很广的行为切换**——用前请打开 [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md) 看一眼，或者用 `--file` 换成你自己的指令。

> [!WARNING]
> 不要在 Windows 上使用已发布的 `v0.1.0`；它有已知的清理缺陷（详见「兼容性与限制」）。v0.1.1 及后续版本已提供原生恢复后端；Windows fresh deployment 仍标记为 beta。

### 快速开始（macOS / Linux）

```bash
# 1. 下载并校验（把 vX.Y.Z 换成 Releases 页面上的最新 tag）
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/vX.Y.Z'
curl --fail --location --remote-name "$base/codex-instruct-vX.Y.Z.py"
curl --fail --location --remote-name "$base/SHA256SUMS"
shasum -a 256 -c SHA256SUMS

# 2. 先看，不要先信——确认目标目录、内置提示词来源和将要写入的内容
python3 codex-instruct-vX.Y.Z.py --version
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --status --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --dry-run --lang zh-CN

# 3. 确认无误后才写入
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --yes --lang zh-CN
```

不要从浮动 `main` 安装正式版本，也不要用 `curl | python` 直接执行——务必先落盘、校验，再运行。部署完成后**关闭旧任务、开启一个新的 Codex 会话**：Codex 只在会话启动时加载配置，运行中的会话不会热更新。

省略 `--codex-dir` 会处理全部自动发现的 `.codex` 目录；只有明确需要多目录一起部署时才这样做。

### 它会改哪些文件

| 路径 | 会发生什么 |
| --- | --- |
| `<codex-dir>/gpt-unrestricted.md`（或自定义 `--name`） | 新建，或先备份再替换 |
| `<codex-dir>/config.toml` | 只拥有并修改顶层 `model_instructions_file`；外部工具重写其他字段不会阻塞 status/uninstall，卸载会保留这些字段 |
| `<codex-dir>/hooks.json` | 默认整体隔离为 `hooks.json.disabled`（先备份） |
| `<codex-dir>/.codex-keysmith-manifest.json` | 记录这次部署改了什么，供后续卸载用 |

完整字段、临时事务目录和边界条件见 [`docs/reference.md`](docs/reference.md)。

### 撤销

```bash
# 只想拿回 hooks，不动指令/配置：
python3 codex-instruct.py --codex-dir ~/.codex --restore-hooks --lang zh-CN

# 想整体撤销这次部署（配置、指令、hooks 一起还原）：
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --lang zh-CN        # 先预览
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --yes --lang zh-CN  # 确认卸载
```

卸载每次只撤销最新一层部署；部署过多次的话，重复运行逐层撤销。config 的长期所有权只覆盖顶层 `model_instructions_file`：CCSwitch 等工具重写其他字段时，只要该字段仍引用本层 MD，status 和卸载仍可继续；卸载只恢复/移除部署前的该字段语句并保留其余当前内容。目标字段缺失、改指其他路径、存在歧义或使用扫描器不支持的语句结构仍会 fail closed。

### 出问题了怎么办

| 现象 | 应该做的事 |
| --- | --- |
| 中途被强制中断（比如 `SIGKILL`、断电） | 先 `--status` 看是否报告 `blocked`；有的话用 `--recover` 预览，确认无误再加 `--yes` |
| `--status` 报告异常残留 | 不要手工删除任何 `.codex-keysmith-transaction-*`、备份或 manifest；按上面 `--recover` 流程处理，或参考 [`docs/hooks-transactions.md`](docs/hooks-transactions.md) |
| 想彻底清掉旧备份 | 见 [`docs/reference.md`](docs/reference.md#备份保留与安全清理) 里的清理前置条件，工具本身不自动删备份 |

### 兼容性与限制

- 推荐 Python 3.10–3.14；已验证 Codex CLI `codex-cli 0.144.1`。
- macOS / Linux 是主要支持范围。
- **Windows**：已发布的 `v0.1.0` 存在已知缺陷（`os.utime` 失败后触发第二个 `PermissionError`，会留下无法用旧脚本恢复的 journal）。v0.1.1 及后续版本已重写 Windows 文件系统后端并标记 `EXPLICIT_BETA`，可以试用，但还不是正式支持；如果 v0.1.0 留下了 journal，用最新已校验 Release 脚本按 `--status` → `--recover` 预览 → `--recover --yes` → `--status` 的顺序恢复，不要手工删除任何证据。
- 单文件 CLI，没有 `pip install` 或自动更新；备份和卸载归档不会自动清理。
- 完整限制清单、事务保证、维护者验证步骤见 [`docs/reference.md`](docs/reference.md)。

### 参与贡献与安全报告

提交前阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。漏洞通过 [`SECURITY.md`](SECURITY.md) 指定的 GitHub 私密渠道报告；不要在公开 Issue 中粘贴凭证、完整配置或私人路径。

### 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI instruction-file deployment for local configuration.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build `AGENTS.md` installer with compat/hook isolation.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode `AGENTS.md` installer for local instructions.

---

English version: [`README.en.md`](README.en.md)。智能体安装提示词见 [`docs/agent-install.md`](docs/agent-install.md)。

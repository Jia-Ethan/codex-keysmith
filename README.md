<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<h1 align="center">codex-keysmith</h1>

<p align="center">
  Transaction-safe Codex instruction deployment, powered by a single-file CLI and an optional desktop client.
</p>

<p align="center">
  <img src="docs/assets/readme/codex-keysmith-desktop.png" alt="Illustrative codex-keysmith desktop client preview showing a healthy local fixture" width="100%">
</p>
<p align="center"><em>Desktop Beta 示意界面；路径和状态为本地演示数据。状态检查、部署预览、恢复与分层卸载都复用同一套 CLI 事务逻辑。</em></p>

<details>
<summary>查看 CLI dry-run 示意图</summary>

<p align="center">
  <img src="docs/assets/readme/codex-keysmith-preview.png" alt="Illustrative codex-keysmith dry-run terminal preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>示意预览；实际路径和输出以本机 dry-run 为准。</em></p>
</details>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="#桌面客户端beta">桌面客户端 beta</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装 / Agent install</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img alt="Blocking CI tests" src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg"></a>
  <a href="https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.3"><img alt="Stable CLI v0.1.3" src="https://img.shields.io/badge/stable_CLI-v0.1.3-2E7D32"></a>
  <a href="https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.2.0-beta.4"><img alt="Desktop beta.4" src="https://img.shields.io/badge/desktop-beta.4-E07A2D"></a>
  <img alt="Source version v0.2.0" src="https://img.shields.io/badge/source-v0.2.0-0099CC">
  <img alt="Python 3.10 to 3.14 recommended" src="https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## 简体中文

### 这是什么

`codex-keysmith` 是一套 Codex 指令部署工具：零依赖的单文件 Python CLI 负责预览、部署、恢复和卸载事务，桌面 Beta 客户端为同一套能力提供可视化入口。它会把一份指令 Markdown 部署到 Codex 配置目录（`~/.codex`），让 Codex 的每个新会话加载它；默认只预览，显式确认后才写入，并支持分层撤销。

**这会改变 Codex 的全局行为，不是项目级设置**：部署会修改 `~/.codex/config.toml` 里的 `model_instructions_file`，因此影响该配置下的**所有新会话**；默认还会暂停你现有的整份 `hooks.json`，直到你显式恢复。内置的示例提示词会让模型不再用拒绝式话术回答，把 reverse shell / keygen / bypass 一类请求当作本地样本处理，也覆盖成人题材、化学/药理/武器类内容。**这不是安全边界，是一次影响很广的行为切换**——用前请打开 [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md) 看一眼，或者用 `--file` 换成你自己的指令。

> [!WARNING]
> 不要在 Windows 上使用已发布的 `v0.1.0`；它有已知的清理缺陷（详见「兼容性与限制」）。v0.1.1 及后续版本已提供原生恢复后端；Windows fresh deployment 仍标记为 beta。

### 状态边界与下载

| 入口 | 当前版本 | 状态与下载 |
| --- | --- | --- |
| 稳定单文件 CLI | [`v0.1.3`](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.3) | GitHub Latest Release；适合 macOS / Linux，安装步骤见下方「快速开始」 |
| macOS 桌面客户端 | [`desktop-v0.2.0-beta.4`](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.2.0-beta.4) | [Apple Silicon unsigned DMG](https://github.com/Jia-Ethan/codex-keysmith/releases/download/desktop-v0.2.0-beta.4/codex-keysmith-0.2.0-macos-arm64-unsigned.dmg) |
| Windows 桌面客户端 | [`desktop-v0.2.0-beta.4`](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.2.0-beta.4) | [Windows x64 unsigned NSIS](https://github.com/Jia-Ethan/codex-keysmith/releases/download/desktop-v0.2.0-beta.4/codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe) |
| 当前源码 | `0.2.0` 开发线 | 包含尚未进入 beta.4 安装包的后续修复；不作为正式安装入口 |

### 桌面客户端（beta）

仓库现已包含 [`gui/` 桌面客户端源码](https://github.com/Jia-Ethan/codex-keysmith/tree/main/gui)。它基于 Tauri 2 + React，复用现有 Python CLI 的预览、部署、恢复和卸载逻辑，不在 GUI 中重写文件事务。

- 当前统一源码版本为 `0.2.0`。[`desktop-v0.2.0-beta.4`](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.2.0-beta.4) 统一提供 macOS Apple Silicon DMG、Windows x64 NSIS、单文件 CLI 和确定性源码归档。
- macOS 用户下载 `codex-keysmith-0.2.0-macos-arm64-unsigned.dmg`；Windows 用户下载 `codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe`。两个安装包都内置独立 CLI sidecar，使用时无需额外安装 Python。
- 本次 Desktop Beta 未进行 Apple 签名/公证或 Authenticode 签名。macOS 可能触发 Gatekeeper，Windows 可能显示 Unknown publisher 或 SmartScreen 警告；两平台均未经过实体设备验收。
- Windows 安装包使用 current-user NSIS 和静默 WebView2 download bootstrapper，不提供 MSI、ARM64 或正式 Windows 支持承诺。底层 Windows CLI fresh deployment 继续遵循 `EXPLICIT_BETA`。
- 当前应用不主动收集或上传用户数据；签名边界见 [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md)，本地数据说明见 [`PRIVACY.md`](PRIVACY.md)。SignPath Foundation 申请仍在审核中，当前预发布资产并未使用 SignPath 签名。

校验下载资产后，macOS 首次运行可在 Finder 中按住 Control 点击应用并选择「打开」；Windows 如出现 SmartScreen，查看「更多信息」后确认发布者仍为 Unknown publisher，再决定是否运行。开发环境、sidecar 构建和验证命令见 [`gui/README.md`](gui/README.md)。

> [!IMPORTANT]
> `desktop-v0.2.0-beta.4` 不包含随后完成的 [PR #21](https://github.com/Jia-Ethan/codex-keysmith/pull/21) Windows CRLF/未知输出失败关闭修复，也不包含 Manage 恢复 hooks 的只读状态计划、全局写操作锁和失败后状态刷新。当前源码已包含这些变更，但不要把浮动源码视为已发布安装包；它们需要通过重新构建的后续 Desktop Beta 才能交付。

### 复制给智能体安装

把下面这段直接复制给 Codex、Claude Code、Cursor Agent 或其他编码智能体；完整模板见 [`docs/agent-install.md`](docs/agent-install.md)。

```text
请审计并安装 codex-keysmith。先阅读 README、docs/agent-install.md 和 CODE_SIGNING_POLICY.md，根据我的平台和目标明确选择稳定 CLI v0.1.3 或 unsigned Desktop Beta desktop-v0.2.0-beta.4；不要把 main 源码当作已发布安装包。只从 GitHub Releases 下载资产并校验 SHA256SUMS，不使用 curl | python。先展示准确下载项、目标目录、写入路径、备份路径、全局行为影响和回滚方式；CLI 安装先运行 --version、--status 和 --dry-run，在任何 --yes 写入前停下来等我确认。不要删除备份、manifest 或事务日志，不要修改 Codex 二进制、网络、运行中进程或凭证。完成后做最小状态验证，并提醒我新开 Codex 会话。
```

### 快速开始（macOS / Linux）

```bash
# 1. 下载并校验当前稳定 CLI；release tag 与资产版本分别声明，避免与桌面预发布 tag 混淆
version='0.1.3'
release_tag="v${version}"
script="codex-instruct-v${version}.py"
base="https://github.com/Jia-Ethan/codex-keysmith/releases/download/${release_tag}"
curl --fail --location --remote-name "$base/$script"
curl --fail --location --remote-name "$base/SHA256SUMS"
awk -v file="$script" '$2 == file { print }' SHA256SUMS | shasum -a 256 -c -

# 2. 先看，不要先信——确认目标目录、内置提示词来源和将要写入的内容
python3 "$script" --version
python3 "$script" --codex-dir ~/.codex --status --lang zh-CN
python3 "$script" --codex-dir ~/.codex --dry-run --lang zh-CN

# 3. 确认无误后才写入
python3 "$script" --codex-dir ~/.codex --yes --lang zh-CN
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

### 与 CCSwitch 配置切换配合

当 CCSwitch 以 Provider 为单位保存并整体写回 Codex `config.toml` 时，可以让两个 Provider 副本分别保存 Keysmith 的 On / Off 配置：

1. 先检查 CCSwitch 的 Codex **通用配置片段**：其中不能包含 `model_instructions_file`，On / Off 两个副本也不要借助「应用通用配置」共享该字段，否则 Off 的有效 live config 仍会被合并成 On。
2. 选择准备作为 **On** 的副本，再部署 Keysmith；若只想切换提示词、不想让 hooks 状态成为全局副作用，部署时使用 `--skip-hooks-isolation`。
3. 切到不含顶层 `model_instructions_file` 的 **Off** 副本，再运行 `--status` 验证。On 应显示 `配置激活状态: active`，Off 应显示 `inactive-by-config`；若 Off 仍是 active，先从 Provider 配置和通用配置片段中移除该字段。Off 不是损坏，但部署和卸载仍保持 blocked；先切回 On 副本再执行写操作。
4. 卸载后在 CCSwitch 普通模式下切离刚清理的 On 副本，检查是否出现“旧供应商配置回填失败”提示，再查看该副本保存的 config，确认字段已消失；单次切换本身不能证明回填成功。

这条流程按 CCSwitch v3.18.0（`ff3bc242`）的普通 Provider 切换与回填行为核对。代理接管热切换在该版本也可能从目标 Provider 的有效配置重建 live config，但还叠加 restore backup、通用配置合并和代理字段覆盖，Keysmith 不把它作为稳定兼容契约。配置切换只影响新会话，也不会随之切换 `hooks.json` / `hooks.json.disabled`。

### 撤销

```bash
script='codex-instruct-v0.1.3.py'

# 只想拿回 hooks，不动指令/配置：
python3 "$script" --codex-dir ~/.codex --restore-hooks --lang zh-CN

# 想整体撤销这次部署（配置、指令、hooks 一起还原）：
python3 "$script" --codex-dir ~/.codex --uninstall --lang zh-CN        # 先预览
python3 "$script" --codex-dir ~/.codex --uninstall --yes --lang zh-CN  # 确认卸载
```

卸载每次只撤销最新一层部署；部署过多次的话，重复运行逐层撤销。config 的长期所有权只覆盖顶层 `model_instructions_file`：CCSwitch 等工具重写其他字段时，只要该字段仍引用本层 MD，status 和卸载仍可继续；卸载只恢复/移除部署前的该字段语句并保留其余当前内容。字段缺失时，只读 status 会识别为 `inactive-by-config`，但 deploy/uninstall 仍会 fail closed，直到切回引用本层 MD 的配置；字段改指其他路径、存在歧义或使用扫描器不支持的语句结构仍属于冲突。

### 出问题了怎么办

| 现象 | 应该做的事 |
| --- | --- |
| 中途被强制中断（比如 `SIGKILL`、断电） | 先 `--status` 看是否报告 `blocked`；有的话用 `--recover` 预览，确认无误再加 `--yes` |
| `--status` 报告异常残留 | 不要手工删除任何 `.codex-keysmith-transaction-*`、备份或 manifest；按上面 `--recover` 流程处理，或参考 [`docs/hooks-transactions.md`](docs/hooks-transactions.md) |
| 想彻底清掉旧备份 | 见 [`docs/reference.md`](docs/reference.md#备份保留与安全清理) 里的清理前置条件，工具本身不自动删备份 |

### 兼容性与限制

- 推荐 Python 3.10–3.14；已验证 Codex CLI `codex-cli 0.144.1`。
- macOS / Linux 是主要支持范围。
- **macOS GUI**：Apple Silicon unsigned DMG 由 `macos-15` 原生 CI 构建并公开为 Desktop Beta，尚未进行 Apple 签名、公证或实体设备验收。
- **Windows**：已发布的 `v0.1.0` 存在已知缺陷（`os.utime` 失败后触发第二个 `PermissionError`，会留下无法用旧脚本恢复的 journal）。v0.1.1 及后续版本已重写 Windows 文件系统后端并标记 `EXPLICIT_BETA`，可以试用，但还不是正式支持；如果 v0.1.0 留下了 journal，用最新已校验 Release 脚本按 `--status` → `--recover` 预览 → `--recover --yes` → `--status` 的顺序恢复，不要手工删除任何证据。
- **Windows GUI**：Windows x64 unsigned NSIS Beta 已由 `windows-2025` 原生 CI 构建并公开为 Pre-release，但没有 Authenticode 签名或实体设备验收；它不扩大上述 CLI 的 `EXPLICIT_BETA` 支持边界，也不等于正式 Windows 支持。
- 单文件 CLI，没有 `pip install` 或自动更新；备份和卸载归档不会自动清理。
- 完整限制清单、事务保证、维护者验证步骤见 [`docs/reference.md`](docs/reference.md)。

### 参与贡献与安全报告

提交前阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。漏洞通过 [`SECURITY.md`](SECURITY.md) 指定的 GitHub 私密渠道报告；不要在公开 Issue 中粘贴凭证、完整配置或私人路径。

### 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Transaction-safe Codex instruction deployment with CLI and desktop beta entry points.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build `AGENTS.md` installer with compat/hook isolation.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode `AGENTS.md` installer for local instructions.

---

English version: [`README.en.md`](README.en.md)。智能体安装提示词见 [`docs/agent-install.md`](docs/agent-install.md)。

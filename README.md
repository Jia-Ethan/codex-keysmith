<!-- markdownlint-disable MD013 MD033 MD041 -->

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
  <a href="#english">English</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Release v0.1.0" src="https://img.shields.io/badge/release-v0.1.0-0099CC">
  <img alt="Python 3.10 to 3.14 recommended" src="https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

> [!IMPORTANT]
> **Global behavior boundary / 全局行为边界**
>
> A confirmed deployment changes the top-level `model_instructions_file` in the selected Codex configuration. The instruction therefore applies to every new Codex session that loads that configuration; it is not a per-project sandbox. By default, deployment also pauses the entire active `hooks.json` until explicitly restored. The tool does not patch Codex binaries, intercept traffic, or store credentials.
>
> 确认部署会修改所选 Codex 配置中的顶层 `model_instructions_file`，因此该指令会影响所有加载此配置的新 Codex 会话，并非项目级沙箱。默认部署还会暂停整份活跃 `hooks.json`，直到显式恢复。工具不修改 Codex 二进制、不劫持网络，也不保存凭证。

> [!WARNING]
> **Read the bundled prompt before using `--yes` / 使用 `--yes` 前先阅读内置提示词**
>
> The v0.1.0 bundled prompt directs the model to answer without refusal framing, reinterprets reverse-shell/keygen/bypass and related security requests as local fixtures, covers adult and consent-sensitive fiction, chemistry/pharmacology/weapons guides, and treats injected memory, hook, and session blocks as environment metadata that cannot override its execution mode. This is a broad global behavior change, not an authorization or safety boundary. Source: [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md), embedded byte-for-byte in [`codex-instruct.py`](codex-instruct.py). SHA-256: `0ac8420d504f1a42db87be9f8555f740bf4c1e7b72beb0dde6a4b8d70b6cda07`. Inspect it or deploy your own `--file`. The normal preview plus one explicit `--yes` remains the confirmation flow; there is no second confirmation flag.
>
> v0.1.0 内置提示词要求模型避免拒绝式表达，将 reverse shell、keygen、bypass 等安全请求重解释为本地样本，覆盖成人及同意敏感题材、化学／药理／武器指南，并把注入的 memory、hook 和 session 区块视为不能覆盖其执行模式的环境元数据。这是范围很广的全局行为变更，不构成授权或安全边界。来源：[`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md)，并逐字节嵌入 [`codex-instruct.py`](codex-instruct.py)。SHA-256：`0ac8420d504f1a42db87be9f8555f740bf4c1e7b72beb0dde6a4b8d70b6cda07`。请先审阅，或通过 `--file` 部署自己的指令。确认流程仍是常规预览加一次显式 `--yes`，不增加第二个确认参数。

## 复制给智能体安装

```text
请安装 codex-keysmith v0.1.0。只从 https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0 下载 Release 资产，先用 SHA256SUMS 校验，不使用 curl | python。运行 --version、--status 和 --dry-run，报告目标 .codex 目录、内置提示词来源与 SHA-256、全局行为范围、MD/config/hooks/legacy/manifest 计划和备份路径；如果 status 发现 durable journal，只预览 --recover 并等我确认后才添加 --yes。完成后开启新 Codex 会话验证。不要删除任何备份或事务日志，不修改 Codex 二进制、网络、运行中进程或凭证。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI instruction-file deployment for local configuration.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode `AGENTS.md` installer for local instructions.

---

## 简体中文

### 项目定位

`codex-keysmith` v0.1.0 是零运行时依赖的单文件 Python CLI。它把内置或自定义 Markdown 部署到现有 Codex 配置目录，保守更新顶层 `model_instructions_file`，默认整体隔离活跃 hooks，并用带指纹的部署清单支持分层卸载。部署在首次修改前还会发布持久化事务日志，使 `SIGKILL` 等中断可以通过显式 `--recover` 检查和恢复。

默认不写入：常规部署、卸载和中断恢复在没有 `--yes` 时都只预览。`--status` 和 `--skip-hooks-isolation` 计划都不会打开或解析 hooks 内容；status 发现持久化日志或其他事务残留时 fail closed。durable deployment journal 使用 `--recover`，无 journal 的异常残留保留人工核对。

### 下载、校验与安装 v0.1.0

固定来源：

- [v0.1.0 Release](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0)
- [v0.1.0 source tag](https://github.com/Jia-Ethan/codex-keysmith/tree/v0.1.0)
- Release bundle：`codex-keysmith-v0.1.0.zip`、`codex-keysmith-v0.1.0.tar.gz`
- 独立脚本：`codex-instruct-v0.1.0.py`
- 校验清单：`SHA256SUMS`

不要从浮动 `main` 安装正式版本，也不要使用 `curl | python`。先把文件保存到磁盘，校验后再执行。

macOS / Linux：

```bash
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/v0.1.0'
for file in \
  codex-keysmith-v0.1.0.zip \
  codex-keysmith-v0.1.0.tar.gz \
  codex-instruct-v0.1.0.py \
  SHA256SUMS
do
  curl --fail --location --remote-name "$base/$file"
done
shasum -a 256 -c SHA256SUMS
python3 codex-instruct-v0.1.0.py --version
```

Linux 也可用 `sha256sum --check SHA256SUMS`。校验通过后，可直接运行独立脚本，或解压 bundle 阅读完整 README、CHANGELOG、SECURITY、示例和事务文档。

Windows PowerShell（experimental）：

```powershell
$base = "https://github.com/Jia-Ethan/codex-keysmith/releases/download/v0.1.0"
$assets = @(
  "codex-keysmith-v0.1.0.zip",
  "codex-keysmith-v0.1.0.tar.gz",
  "codex-instruct-v0.1.0.py"
)
foreach ($name in $assets + @("SHA256SUMS")) {
  Invoke-WebRequest "$base/$name" -OutFile $name
}
$expected = @{}
Get-Content .\SHA256SUMS | ForEach-Object {
  $parts = $_ -split '\s+', 2
  $expected[$parts[1]] = $parts[0].ToLowerInvariant()
}
foreach ($name in $assets) {
  $actual = (Get-FileHash ".\$name" -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected[$name]) { throw "SHA-256 mismatch: $name" }
}
py -3 .\codex-instruct-v0.1.0.py --version
```

### 运行环境

- 正式建议：Python 3.10–3.14；运行 CLI 只需要标准库。
- Python 3.8：保留 legacy compatibility 测试，但 Python 3.8 已 EOL，不作为首选生产运行时。
- 已验证 Codex CLI：`codex-cli 0.144.1`。其他 Codex 版本需重新核对配置格式和实际模型行为。
- macOS / Linux：当前主要支持范围。
- Windows：v0.1.0 标记为 experimental；CI 包含 Windows 原子无覆盖重命名探测，但在正式支持声明前仍需远端矩阵和真实环境证据。

### 第一次部署

建议始终显式指定单个目录，并固定 CLI 语言：

```bash
python3 codex-instruct-v0.1.0.py --version
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --status --lang zh-CN
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --dry-run --lang zh-CN
```

检查输出中的：

1. 目标 `.codex` 目录和 `config.toml`；
2. 内置提示词来源、SHA-256 和全局行为范围；
3. 将写入的 MD 与顶层配置值；
4. active/disabled hooks 状态与隔离计划；
5. `gpt5.5-unrestricted.md` 的迁移状态；
6. `.codex-keysmith-manifest.json` 与备份计划。

确认后执行：

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --yes --lang zh-CN
```

部署完成后关闭旧任务并开启一个新的 Codex 会话。Codex 在会话启动时加载配置；已经运行的会话不会可靠地热更新指令或 hooks 状态。

省略 `--codex-dir` 会处理全部自动发现目录。除非明确需要多目录事务，不要省略。

### 状态输出

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --status --lang zh-CN
```

稳定字段示例：

```text
[状态] 找到 1 个 Codex 配置目录（只读检查）:

── 状态目录: <codex-dir> ──
    config.toml: regular file (<codex-dir>/config.toml)
    gpt-unrestricted.md: regular file (<codex-dir>/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (<codex-dir>/gpt5.5-unrestricted.md)
    hooks.json: missing (<codex-dir>/hooks.json)
    hooks.json.disabled: regular file (<codex-dir>/hooks.json.disabled)
    部署清单: regular file (<codex-dir>/.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    事务残留: none
    旧版迁移: 无需处理
    hooks 恢复: 可执行 <restore-command>
    可部署性: ready
```

`--status` 不修改文件，也不读取或解析 hooks 内容。它用目录枚举和 `lstat` 检出 `.codex-keysmith-transaction-<id>`、cleanup claim/marker 与 `.keysmith-*` 残留；一旦发现中断日志、其他事务残留、异常节点或无效 manifest，就返回 1 并阻止继续部署。status 不解析 `journal.json`，恢复内容只由显式 `--recover` 读取。

### 会修改哪些文件

| 路径 | 确认部署行为 |
| --- | --- |
| `<codex-dir>/<name>.md` | 新建；已有普通文件时先创建时间戳备份再替换 |
| `<codex-dir>/config.toml` | 仅在顶层值需要变化时备份并更新；值相同则保持原字节 |
| `<codex-dir>/hooks.json` | 默认先备份，再整体隔离为 `hooks.json.disabled` |
| `<codex-dir>/hooks.json.disabled` | 已存在时先移动到时间戳备份，再发布新的 disabled 文件 |
| `<codex-dir>/gpt5.5-unrestricted.md` | 被引用或匹配历史内置内容时事务归档；自定义孤立文件保留 |
| `<codex-dir>/.codex-keysmith-manifest.json` | 记录 MD/config、实际隔离的 hooks、实际归档的 legacy、备份与上一层 manifest |
| `<codex-dir>/.codex-keysmith-transaction-<id>/` | 保存 journal/companion、固定名称 pending 文件、不可变 `intent.json` 和部署前快照；终态使用 `committed` / `recovered` 与可重入 cleanup marker 清理 |
| `<codex-dir>/.keysmith-*` | 单步骤临时目录；正常完成后清理，异常残留会阻止后续写入 |

受管理节点必须是普通文件。符号链接、悬空链接、目录、FIFO、socket、无效 UTF-8 或不安全 TOML 都会 fail closed。只有本次确实隔离的 hooks 和确实归档的 legacy 才进入 manifest 所有权；未隔离 hooks 与未受管理 legacy 不会被 uninstall 验证或改写。显式 `--skip-hooks-isolation` 时，hooks 节点完全排除在计划、manifest 和读写边界之外，但仍可能继续影响模型行为。

### 工作流程

```mermaid
flowchart TD
    A["--status / --dry-run"] --> B["核对 prompt 来源与 SHA、MD/config/hooks/legacy/manifest"]
    B --> C{"显式 --yes"}
    C -->|否| D["结束；不写入"]
    C -->|是| E["所有目录预检与原子能力探测"]
    E --> F["发布 journal.json 与部署前快照"]
    F --> G["默认隔离 hooks"]
    G --> H["归档受管理 legacy"]
    H --> I["发布 MD、config 与 manifest"]
    I --> J["受管理资源、备份与 manifest 完整 final sweep"]
    J --> K["清理 journal，开启新 Codex 会话"]
    E -.错误.-> R["反向回滚"]
    F -.错误.-> R
    G -.错误.-> R
    H -.错误.-> R
    I -.漂移.-> R
    J -.漂移.-> R
    F -.硬中断.-> X["status 检出 journal 并阻塞"]
    X --> Y["--recover 预览；--recover --yes 恢复并 final sweep"]
```

### 自定义指令与 CLI 语言

```bash
python3 codex-instruct-v0.1.0.py \
  --file ./my-prompt.md \
  --name my-rules \
  --codex-dir ~/.codex \
  --dry-run \
  --lang zh-CN
```

确认后把 `--dry-run` 改为 `--yes`。外部 Markdown 必须是 no-follow 普通 UTF-8 文件。`--name` 只允许 ASCII 字母、数字、点、下划线和连字符，不接受路径分隔符、绝对路径、`..`、空格或空名称。`gpt5.5-unrestricted` 是旧版迁移保留名，不能作为自定义 `--name`。

`--lang auto|zh-CN|en` 控制 CLI 输出：

- `auto` 依次读取 `LC_ALL`、`LC_MESSAGES`、`LANG`；值以 `zh` 开头时使用简体中文，以 `en` 开头时使用英文；
- 其他 locale 或缺失 locale 安全回退到 `zh-CN`；
- `--lang zh-CN` / `--lang en` 明确覆盖自动选择；
- `--version` 输出当前脚本版本，不访问 Codex 配置。

### hooks 恢复

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --restore-hooks --lang zh-CN
```

恢复只处理 `hooks.json.disabled -> hooks.json`，不部署 MD、不编辑 config，也不读取 JSON：

- 没有 disabled 文件是成功 no-op；
- active 与 disabled 同时存在时不覆盖任一方，返回 1；
- 异常节点、事务残留或并发漂移返回 1，并保留证据；
- `--restore-hooks` 不接受 `--yes`、`--file`、`--name` 或 `--skip-hooks-isolation`。

### 中断部署恢复

`--recover` 专门处理部署在首次修改前创建的 `.codex-keysmith-transaction-<id>/journal.json` 和快照。默认仅预览：

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --recover --lang zh-CN
```

确认后恢复整个多目录事务：

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --recover --yes --lang zh-CN
```

- 指定任一参与目录即可；日志会列出并验证同一 transaction ID 的全部参与目录；
- 预检交叉验证 journal、不可变 intent、manifest intent、owner、参与者、部署前快照，以及每个资源当前是否属于记录的 before 或预发布 after 状态；
- 未知事务残留、外部篡改参与者、快照漂移或用户并发内容都会 fail closed，日志与证据原样保留；
- 执行时按反向参与目录和 `manifest -> config -> MD -> legacy -> disabled hooks -> active hooks` 顺序恢复；
- 全部资源、恢复出的上一层 manifest 所有权和 journal companion 完成最终 sweep 后，才按精确 residue 名称、目录 identity、成员集合与指纹清理；清理先原子认领整个目录，原路径上的并发替换不会被带入 claim，同前缀不构成删除授权；
- 成功部署先写入 `committed`，成功恢复先写入 `recovered` 并再做一次 final sweep；逐目录或逐成员清理被硬中断时，剩余 journal、随机 cleanup claim 或 intent marker 可继续验证并完成清理；
- 同时发现多个 transaction ID 时不会猜测合并，应分别指定其参与目录恢复。

`--recover` 不等同于 `--restore-hooks` 或 `--uninstall`：recover 回到被中断部署开始前，restore-hooks 只重新启用 disabled hooks，uninstall 撤销已成功完成且有 manifest 的最新部署层。

### 清单式分层卸载

先预览：

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --uninstall --lang zh-CN
```

确认卸载一层：

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --uninstall --yes --lang zh-CN
```

卸载仅处理 `.codex-keysmith-manifest.json` 明确拥有的最新一层：

- 先验证当前 MD/config、实际隔离的 hooks、实际归档的 legacy、全部必要备份和 manifest 的 `size`、`mtime_ns`、SHA-256 与预期存在状态；
- 任一路径漂移、备份缺失、manifest 无效或节点异常时，所有目录都在写入前停止；
- 恢复该层部署前的 config 与 MD；仅当 manifest 记录了真实隔离/归档时，才恢复 hooks、旧 disabled hooks 或 legacy；
- 当前 manifest 原子归档为 `.codex-keysmith-manifest.json.uninstalled_<timestamp>`；
- 如果该层覆盖了上一份 manifest，则恢复上一层。再次运行 uninstall 才会继续撤销下一层；
- 所有参与目录的恢复结果完成 final sweep 后，才清理卸载回滚快照；
- 找不到 manifest 是成功 no-op。v0.1.0 之前没有 manifest 的部署不属于自动所有权范围，首次 v0.1.0 卸载只会回到其记录的部署前状态。

`--restore-hooks` 只恢复 hooks；`--uninstall` 按 manifest 恢复整层用户配置。二者用途不同。

### 升级工具与回滚

1. 从新的固定 Release 下载新的独立脚本或 bundle，并用该 Release 的 `SHA256SUMS` 校验。
2. 保留旧脚本和旧 Release 资产，不覆盖式替换。
3. 运行新脚本的 `--version`、`--status`、`--dry-run`。
4. 确认后部署；新部署会生成新的 manifest 层。
5. 如需回退，先用新脚本执行一次 `--uninstall --yes` 撤销最新层；需要继续回退时逐层重复。hooks 只需单独恢复时使用 `--restore-hooks`。
6. 代码本身的版本回退是重新使用已校验的旧 Release 脚本；它不会自动改变用户配置。用户配置回退必须显式 uninstall/restore。

### 备份保留与安全清理

工具不会自动删除 `*.bak_*`、`*.recovery_*` 或 `.uninstalled_*`。durable journal 会在成功部署、成功运行时回滚或成功 `--recover` 后清理；一旦恢复预检失败，它会与快照和未知残留一起保留，作为所有权、恢复和事故排查证据。

只有在以下条件全部满足后，才考虑清理：

1. `--status` 无阻塞，不存在 durable journal，且不再需要继续分层 uninstall；
2. 当前 `config.toml` 不引用准备移走的 MD/legacy 文件；
3. 当前 manifest 及所有更早 manifest 都不引用对应备份；
4. `hooks.json` / `hooks.json.disabled` 状态已人工确认；
5. 先复制整个 `.codex` 目录或把候选文件移动到仓库外的可恢复归档/系统废纸篓，再观察新的 Codex 会话。

不要直接删除当前 manifest、事务残留或无法确认所有权的备份。断电或崩溃残留的处理见 [`docs/hooks-transactions.md`](docs/hooks-transactions.md)。

### 旧文件名迁移

默认内置部署且目标名为 `gpt-unrestricted.md` 时，工具检查 `gpt5.5-unrestricted.md`。被 config 引用或匹配历史内置哈希的普通文件会事务归档；只有这种 `archive` 动作进入 manifest 所有权。未引用的自定义内容保留并标记为未受管理，manifest 不记录其指纹，uninstall 不检查或改写它；需要迁移但节点异常时在写入前停止。为避免与迁移路径冲突，`--name gpt5.5-unrestricted` 被保留并拒绝。

### 参数与退出码

| 参数 | 说明 |
| --- | --- |
| `--file`, `-f` | 外部 Markdown；省略时使用内置提示词 |
| `--name`, `-n` | 输出文件名，不含 `.md`；默认 `gpt-unrestricted` |
| `--dry-run` | 预览部署，不写文件 |
| `--yes` | 确认常规部署、清单式卸载或中断恢复 |
| `--codex-dir` | 显式选择单个 `.codex`；省略后使用自动发现 |
| `--status` | 只读状态；不解析 hooks JSON |
| `--restore-hooks` | 只恢复 disabled hooks |
| `--uninstall` | 预览或撤销最新一层受管理部署 |
| `--recover` | 预览或恢复 durable journal 记录的中断部署 |
| `--skip-hooks-isolation` | 保持 hooks 活跃；必须显式指定 `--codex-dir` |
| `--lang auto|zh-CN|en` | 自动或显式选择 CLI 输出语言 |
| `--version` | 显示脚本版本并退出 |

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功部署、无阻塞预览/status、成功 restore/uninstall/recover，或正常 no-op |
| `1` | 所有权/完整性/节点/config 冲突、事务日志或残留、并发漂移、恢复或回滚失败 |
| `2` | argparse 参数错误、互斥模式或缺少参数约束 |

### 事务边界与已知限制

- 文件内容会 `fsync`，目标发布使用同卷原子无覆盖重命名，并在关键阶段复核完整指纹；
- 复制型备份以独占 no-follow 的 `0600` 文件创建，复制和 `fsync` 完成后再应用原文件权限；disabled hooks 与 legacy 归档使用已验证的原子移动；
- 多目录先全部预检，再持久化 `0700` journal 目录、`0600` journal/intent/companion JSON 和部署前快照，之后才隔离 hooks 或写入；journal 与 companion 的固定 pending 文件可在硬中断后完成或丢弃；
- 部署、`--recover` 和 uninstall 都在删除自身恢复证据前执行全部受管理参与目录的 final fingerprint sweep；
- 不跟随 symlink，不使用完整 TOML 解析器；遇到歧义、重复目标键、占用命名空间或不安全语法时停止；
- `SIGKILL` 无法运行 Python 回滚，但首次部署修改前已完成持久化 journal；后续 status 会检出并 fail closed，等待显式 `--recover`；
- journal 文件、journal 目录及 journal 在 Codex 目录中的创建/删除会执行可用的 directory `fsync`。资源文件内容会 `fsync`，但不是每一次资源 rename 都会对父目录执行 directory `fsync`；Windows 的目录 fsync 支持也因系统而异；
- 在遵守操作系统和文件系统 `fsync` 语义的正常崩溃模型中，已发布 immutable intent 的中断部署由 durable journal 覆盖。两个窄窗口刻意 fail closed 并需要人工核对：journal 目录 `mkdir` 后、首份 intent 发布前，以及单步骤临时目录 `mkdtemp` 后、residue record 持久化前；
- 原子目录 claim 后在原路径出现的并发替换会保留。journal、intent、companion、manifest 与 cleanup claim 用于防止意外漂移和普通竞态，不是抵御同一账户协同篡改多份证据的密码学认证；这类主动篡改，以及极端断电、设备不兑现 flush、文件系统损坏或目录项持久化异常，超出可证明边界；
- `model_instructions_file` 是全局配置，没有 profile 隔离；hooks 只能整份隔离；
- 内置提示词不保证任何模型或版本采用完全相同的行为。

完整状态机见 [`docs/hooks-transactions.md`](docs/hooks-transactions.md)。

### 可执行 Prompt Bank

离线契约校验不调用模型：

```bash
python3 scripts/run_prompt_bank_regression.py --validate-only
```

Live 模式必须显式指定模型，并在临时 `CODEX_HOME` 与工作目录运行：

```bash
OPENAI_API_KEY=YOUR_KEY python3 scripts/run_prompt_bank_regression.py \
  --codex-bin codex \
  --model MODEL \
  --attempts 2 \
  --report work/prompt-bank.jsonl
```

当前 bank 最多 12 cases，每 case 最多 2 次尝试，即最多 24 次真实请求。每次超时 120 秒，纯超时理论上界为 48 分钟，另加 CLI 启动与报告开销。Live 调用可能产生费用。已有报告默认拒绝覆盖；只有明确接受替换时添加 `--overwrite-report`。报告使用原子发布、no-follow 路径检查、临时文件 inode/指纹复核和脱敏；并发替换会保留证据而不是覆盖既有报告。响应片段仍可能含上下文信息，应按敏感测试产物管理。PR CI 只运行离线校验和 mocked adapter。

### 维护者验证

```bash
python3 -m py_compile codex-instruct.py scripts/build_release.py scripts/run_prompt_bank_regression.py
python3 -m pytest -p no:cacheprovider -q tests
python3 -m ruff check codex-instruct.py tests scripts
python3 -m coverage erase
python3 -m coverage run --branch --parallel-mode -m pytest -p no:cacheprovider -q tests
python3 -m coverage combine
python3 -m coverage report --include=codex-instruct.py,scripts/run_prompt_bank_regression.py --fail-under=80
python3 scripts/run_prompt_bank_regression.py --validate-only
# pre-tag / PR / CI candidate: 必须绑定当前完整 commit SHA
SOURCE_COMMIT="$(git rev-parse --verify 'HEAD^{commit}')"
python3 scripts/build_release.py v0.1.0 --source-commit "$SOURCE_COMMIT" --output-dir dist-candidate
(cd dist-candidate && sha256sum --check SHA256SUMS)

# formal Release: tag 必须存在、解析到 HEAD；不要传 --source-commit
python3 scripts/build_release.py v0.1.0 --output-dir dist
(cd dist && sha256sum --check SHA256SUMS)
git diff --check
```

候选构建只接受 40/64 位完整 commit object ID，要求 HEAD 精确匹配；如果同名 tag 已存在，它也必须指向该 commit。正式构建不接受候选替代语义：它要求 `refs/tags/v0.1.0` 存在并精确指向 HEAD。两种模式都要求干净工作树并拒绝覆盖不同内容的既有资产。GitHub Actions 的 pre-tag candidate 使用 `--source-commit "$GITHUB_SHA"`。

当前测试集为 290+ 项，覆盖提示词一致性、CLI、目录发现、多目录 durable journal/recovery、pending/partial snapshot/cleanup marker、权限、Unicode、symlink、hooks、TOML、manifest/uninstall、Prompt Bank、真实进程争用和 Release 资产可重复构建。

### 当前限制

- 单文件 CLI，不提供 `pip install` 或自动更新；
- Windows 为 experimental；
- Python 3.8 仅保留 legacy compatibility；
- Live Prompt Bank 不进入 PR gate；
- `main` / `Unreleased` 是开发状态，不等于正式 Release；
- 备份和卸载归档不会自动清理。

### 项目结构

```text
codex-keysmith/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── pull_request_template.md
│   └── workflows/tests.yml
├── docs/hooks-transactions.md
├── examples/gpt-unrestricted.md
├── scripts/
│   ├── build_release.py
│   └── run_prompt_bank_regression.py
├── tests/
│   ├── prompt_bank/cases.json
│   ├── test_codex_instruct.py
│   ├── test_config_boundaries.py
│   ├── test_platform_and_discovery.py
│   ├── test_prompt_bank_regression.py
│   ├── test_recovery.py
│   ├── test_release_artifacts.py
│   └── test_uninstall.py
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── VERSION
├── codex-instruct.py
├── pyproject.toml
├── requirements-quality.txt
└── README.md
```

### 参与贡献与安全报告

提交前阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。漏洞通过 [`SECURITY.md`](SECURITY.md) 指定的 GitHub 私密渠道报告；不要在公开 Issue 中粘贴凭证、完整配置或私人路径。

---

## English

### Positioning

`codex-keysmith` v0.1.0 is a zero-runtime-dependency, single-file Python CLI. It deploys the bundled or a custom Markdown instruction into an existing Codex configuration directory, conservatively updates the top-level `model_instructions_file`, isolates active hooks by default, and records an ownership manifest for layered uninstall. Before its first mutation, deployment also publishes a durable transaction journal so an interruption such as `SIGKILL` can be inspected and restored through explicit `--recover`.

Normal deployment, uninstall, and interrupted-deployment recovery are previews unless `--yes` is present. Neither `--status` nor a `--skip-hooks-isolation` plan opens or parses hook content. Status fails closed when it discovers a durable journal or other transaction residue. Use `--recover` for a durable deployment journal; preserve journal-less abnormal residue for manual inspection.

### Download, verify, and install v0.1.0

Fixed sources:

- [v0.1.0 Release](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0)
- [v0.1.0 source tag](https://github.com/Jia-Ethan/codex-keysmith/tree/v0.1.0)
- Release bundles: `codex-keysmith-v0.1.0.zip`, `codex-keysmith-v0.1.0.tar.gz`
- Standalone script: `codex-instruct-v0.1.0.py`
- Checksum manifest: `SHA256SUMS`

Do not install a formal release from floating `main`, and do not use `curl | python`. Save assets, verify them, and only then execute the script.

macOS / Linux:

```bash
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/v0.1.0'
for file in \
  codex-keysmith-v0.1.0.zip \
  codex-keysmith-v0.1.0.tar.gz \
  codex-instruct-v0.1.0.py \
  SHA256SUMS
do
  curl --fail --location --remote-name "$base/$file"
done
shasum -a 256 -c SHA256SUMS
python3 codex-instruct-v0.1.0.py --version
```

Linux users may run `sha256sum --check SHA256SUMS`. After verification, run the standalone script or extract a bundle to inspect the complete documentation, prompt, and transaction reference.

Windows PowerShell (experimental):

```powershell
$base = "https://github.com/Jia-Ethan/codex-keysmith/releases/download/v0.1.0"
$assets = @(
  "codex-keysmith-v0.1.0.zip",
  "codex-keysmith-v0.1.0.tar.gz",
  "codex-instruct-v0.1.0.py"
)
foreach ($name in $assets + @("SHA256SUMS")) {
  Invoke-WebRequest "$base/$name" -OutFile $name
}
$expected = @{}
Get-Content .\SHA256SUMS | ForEach-Object {
  $parts = $_ -split '\s+', 2
  $expected[$parts[1]] = $parts[0].ToLowerInvariant()
}
foreach ($name in $assets) {
  $actual = (Get-FileHash ".\$name" -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected[$name]) { throw "SHA-256 mismatch: $name" }
}
py -3 .\codex-instruct-v0.1.0.py --version
```

### Runtime policy

- Recommended production runtime: Python 3.10–3.14; the CLI uses only the standard library.
- Python 3.8 remains in legacy compatibility tests, but it is EOL and is not the preferred production runtime.
- Verified Codex CLI: `codex-cli 0.144.1`. Recheck configuration compatibility and live model behavior for other versions.
- macOS and Linux are the primary support range.
- Windows is experimental in v0.1.0. CI includes a Windows atomic no-replace probe, but formal support still requires remote-matrix and real-environment evidence.

### First deployment

Select one directory and request English output explicitly:

```bash
python3 codex-instruct-v0.1.0.py --version
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --status --lang en
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --dry-run --lang en
```

Review:

1. the selected `.codex` directory and `config.toml`;
2. the bundled-prompt source, SHA-256, and global behavior scope;
3. the destination Markdown and top-level configuration value;
4. active/disabled hook state and the isolation plan;
5. the `gpt5.5-unrestricted.md` migration state;
6. `.codex-keysmith-manifest.json` and all backup paths.

Confirm once:

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --yes --lang en
```

Close the old task and start a new Codex session after deployment. Codex loads configuration at session start; a running session is not guaranteed to hot-reload instructions or hooks.

Omitting `--codex-dir` processes every auto-discovered Codex directory. Do this only for an intentional multi-directory transaction.

### Status output

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --status --lang en
```

Stable field example:

```text
[Status] Found 1 Codex configuration location(s) (read-only inspection):

── Status directory: <codex-dir> ──
    config.toml: regular file (<codex-dir>/config.toml)
    gpt-unrestricted.md: regular file (<codex-dir>/gpt-unrestricted.md)
    gpt5.5-unrestricted.md: missing (<codex-dir>/gpt5.5-unrestricted.md)
    hooks.json: missing (<codex-dir>/hooks.json)
    hooks.json.disabled: regular file (<codex-dir>/hooks.json.disabled)
    deployment manifest: regular file (<codex-dir>/.codex-keysmith-manifest.json)
    model_instructions_file: ./gpt-unrestricted.md
    Transaction residue: none
    Legacy migration: none
    Hooks restore: available <restore-command>
    Deployability: ready
```

`--status` changes no files and never reads or parses hook content. It detects `.codex-keysmith-transaction-<id>`, cleanup claims/markers, and `.keysmith-*` residue through directory enumeration and `lstat`; interrupted journals, other residue, abnormal nodes, and invalid manifests exit 1 and block deployment. Status does not parse `journal.json`; only explicit `--recover` reads recovery content.

### Files changed by a confirmed deployment

| Path | Behavior |
| --- | --- |
| `<codex-dir>/<name>.md` | Create, or back up and replace an existing regular file |
| `<codex-dir>/config.toml` | Back up and update only when the top-level value changes; otherwise preserve bytes |
| `<codex-dir>/hooks.json` | Back up and isolate the whole active file as `hooks.json.disabled` by default |
| `<codex-dir>/hooks.json.disabled` | Back up an existing disabled file before publishing new disabled state |
| `<codex-dir>/gpt5.5-unrestricted.md` | Transactionally archive referenced/historical content; preserve unmanaged custom content |
| `<codex-dir>/.codex-keysmith-manifest.json` | Record MD/config, actually isolated hooks, actually archived legacy state, backups, and the previous manifest layer |
| `<codex-dir>/.codex-keysmith-transaction-<id>/` | Holds journal/companion JSON, fixed-name pending files, immutable `intent.json`, and before-state snapshots; cleanup uses terminal phases plus a re-enterable intent marker |
| `<codex-dir>/.keysmith-*` | Per-step temporary directories; normal completion removes them, and residue blocks later writes |

Managed targets must be regular files. Symlinks, dangling links, directories, FIFOs, sockets, invalid UTF-8, and unsafe TOML fail closed. Only hooks actually isolated and legacy content actually archived enter manifest ownership; unisolated hooks and unmanaged legacy paths are not verified or changed by uninstall. With `--skip-hooks-isolation`, hook paths are completely outside planning, manifest ownership, and the read/write boundary, but active hooks can continue to affect model behavior.

### Workflow

```mermaid
flowchart TD
    A["--status / --dry-run"] --> B["Review prompt source and SHA plus MD/config/hooks/legacy/manifest"]
    B --> C{"Explicit --yes"}
    C -->|No| D["Exit without writes"]
    C -->|Yes| E["Preflight all directories and probe atomic capability"]
    E --> F["Publish journal.json and before-state snapshots"]
    F --> G["Isolate hooks by default"]
    G --> H["Archive managed legacy prompt"]
    H --> I["Publish Markdown, config, and manifest"]
    I --> J["Complete final sweep of managed resources, backups, and manifest"]
    J --> K["Remove journal and start a new Codex session"]
    E -.error.-> R["Reverse rollback"]
    F -.error.-> R
    G -.error.-> R
    H -.error.-> R
    I -.drift.-> R
    J -.drift.-> R
    F -.hard interruption.-> X["Status detects the journal and blocks"]
    X --> Y["Preview --recover; apply --recover --yes and final sweep"]
```

### Custom prompt and CLI language

```bash
python3 codex-instruct-v0.1.0.py \
  --file ./my-prompt.md \
  --name my-rules \
  --codex-dir ~/.codex \
  --dry-run \
  --lang en
```

Replace `--dry-run` with `--yes` after review. External Markdown must be a no-follow regular UTF-8 file. `--name` accepts only ASCII letters, digits, dots, underscores, and hyphens; separators, absolute paths, `..`, spaces, and empty names are rejected. `gpt5.5-unrestricted` is reserved for legacy migration and cannot be used as a custom `--name`.

`--lang auto|zh-CN|en` controls CLI output:

- `auto` checks `LC_ALL`, then `LC_MESSAGES`, then `LANG`; values beginning with `zh` select Simplified Chinese and values beginning with `en` select English;
- an unsupported or absent locale safely falls back to `zh-CN`;
- `--lang zh-CN` and `--lang en` override detection;
- `--version` prints the script version without accessing Codex configuration.

### Restore hooks

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --restore-hooks --lang en
```

Restore only performs `hooks.json.disabled -> hooks.json`; it does not deploy Markdown, edit config, or parse JSON:

- an absent disabled file is a successful no-op;
- active and disabled files together are preserved and exit 1;
- abnormal nodes, residue, or concurrent drift exit 1 and preserve evidence;
- `--restore-hooks` rejects `--yes`, `--file`, `--name`, and `--skip-hooks-isolation`.

### Recover an interrupted deployment

`--recover` handles the `.codex-keysmith-transaction-<id>/journal.json` and before-state snapshots created before deployment's first mutation. It is preview-only by default:

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --recover --lang en
```

Confirm recovery of the complete multi-directory transaction:

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --recover --yes --lang en
```

- selecting any participant is sufficient; the journal lists and verifies every participant with the same transaction ID;
- preflight cross-validates the journal, immutable intent, manifest intent, owner, participants, before-state snapshots, and whether every live resource is one of the recorded before or pre-published after states;
- unknown transaction residue, a tampered external participant, snapshot drift, or concurrent user content fails closed and preserves all journal evidence;
- execution restores reversed participant order and `manifest -> config -> Markdown -> legacy -> disabled hooks -> active hooks` within each directory;
- every resource, restored previous-manifest ownership, and journal companion passes a final sweep before cleanup; residue requires an exact recorded name, directory identity, member set, and member fingerprints, and cleanup atomically claims the whole directory before deletion;
- successful deployment persists `committed`; successful recovery persists `recovered` and runs another final sweep. Remaining journals, random cleanup claims, or intent markers can finish cleanup after an interruption between directories or members;
- multiple transaction IDs are never merged heuristically; select a participant of each transaction separately.

`--recover` is distinct from `--restore-hooks` and `--uninstall`: recover returns to the state before an interrupted deployment, restore-hooks only reactivates disabled hooks, and uninstall removes the newest successfully completed manifest layer.

### Manifest-based layered uninstall

Preview:

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --uninstall --lang en
```

Uninstall one managed layer:

```bash
python3 codex-instruct-v0.1.0.py --codex-dir ~/.codex --uninstall --yes --lang en
```

Uninstall only touches the newest layer owned by `.codex-keysmith-manifest.json`:

- it verifies expected presence plus `size`, `mtime_ns`, and SHA-256 for current MD/config, actually isolated hooks, actually archived legacy state, required backups, and the manifest;
- drift, missing backups, invalid manifests, or abnormal nodes stop every selected directory before writes;
- it restores the previous config and Markdown; hooks, previous disabled hooks, and legacy state are restored only when the manifest records a real isolation/archive action;
- it atomically archives the current manifest as `.codex-keysmith-manifest.json.uninstalled_<timestamp>`;
- if the deployment replaced an older manifest, uninstall restores it. Run uninstall again to remove another layer;
- rollback snapshots are removed only after a final sweep of every participating directory's restored state;
- an absent manifest is a successful no-op. Pre-v0.1.0 deployments have no automatic ownership record; the first v0.1.0 uninstall returns only to the pre-deployment state recorded by v0.1.0.

`--restore-hooks` restores hooks only. `--uninstall` restores a complete manifest-owned configuration layer.

### Upgrade and rollback

1. Download the next fixed Release script or bundle and verify its `SHA256SUMS`.
2. Keep the old verified script and assets; do not overwrite them in place.
3. Run the new script's `--version`, `--status`, and `--dry-run`.
4. Confirm deployment; it creates a new manifest layer.
5. To roll back, run the new script once with `--uninstall --yes` for the newest layer. Repeat only when intentionally removing older layers. Use `--restore-hooks` when only hooks need restoration.
6. Re-running an older verified Release changes the executable version only; it does not automatically roll back user configuration. Configuration rollback must be explicit.

### Backup retention and safe cleanup

The tool never automatically deletes `*.bak_*`, `*.recovery_*`, or `.uninstalled_*`. A durable journal is removed after successful deployment, successful runtime rollback, or successful `--recover`; if recovery preflight fails, the journal, snapshots, and unknown residue remain as ownership, recovery, and incident evidence.

Only consider cleanup after all of these checks:

1. `--status` has no blocker, no durable journal remains, and no further layered uninstall is required;
2. current `config.toml` does not reference the Markdown or legacy file being archived;
3. the current and every older manifest no longer reference the candidate backup;
4. active/disabled hook state has been manually verified;
5. copy the complete `.codex` directory or move candidates to a recoverable archive/system Trash outside it, then test a new Codex session.

Do not directly delete the current manifest, transaction residue, or backups with uncertain ownership. See [`docs/hooks-transactions.md`](docs/hooks-transactions.md) for interrupted-operation recovery.

### Legacy filename migration

For the default bundled `gpt-unrestricted.md` deployment, the tool inspects `gpt5.5-unrestricted.md`. A regular file referenced by config or matching a historical bundled hash is archived transactionally; only this `archive` action enters manifest ownership. Unreferenced custom content is preserved as unmanaged, its fingerprint is omitted from manifest ownership, and uninstall neither verifies nor changes it. An abnormal node blocks required migration before writes. To avoid colliding with the migration path, `--name gpt5.5-unrestricted` is reserved and rejected.

### Options and exit codes

| Option | Description |
| --- | --- |
| `--file`, `-f` | External Markdown; omit it for the bundled prompt |
| `--name`, `-n` | Destination name without `.md`; default `gpt-unrestricted` |
| `--dry-run` | Preview deployment without writes |
| `--yes` | Confirm deployment, manifest-based uninstall, or interrupted-deployment recovery |
| `--codex-dir` | Explicitly select one `.codex`; omission uses discovery |
| `--status` | Read-only status; never parses hook JSON |
| `--restore-hooks` | Restore disabled hooks only |
| `--uninstall` | Preview or remove the newest managed layer |
| `--recover` | Preview or restore an interrupted deployment recorded by a durable journal |
| `--skip-hooks-isolation` | Keep hooks active; requires explicit `--codex-dir` |
| `--lang auto|zh-CN|en` | Auto-detect or explicitly select CLI output language |
| `--version` | Print the script version and exit |

| Code | Meaning |
| --- | --- |
| `0` | Successful deploy, blocker-free preview/status, successful restore/uninstall/recover, or normal no-op |
| `1` | Ownership, integrity, node, or config conflict; journal/residue; concurrent drift; recovery failure; or rollback failure |
| `2` | argparse error, conflicting modes, or an unmet argument constraint |

### Transaction boundaries and known limits

- File content is `fsync`ed, publication uses same-volume atomic no-replace renames, and full fingerprints are rechecked at critical stages.
- Copy-created backups use exclusive no-follow `0600` files; source permissions are applied only after copy and `fsync` complete. Disabled-hook and legacy archives use validated atomic moves.
- Multi-directory deployment preflights every directory, then persists private `0700` journal directories, `0600` journal/intent/companion JSON, and before-state snapshots before isolating hooks or writing resources. Fixed-name journal and companion pending files can be completed or discarded after interruption.
- Deployment, `--recover`, and uninstall perform a complete final fingerprint sweep across every managed participant before deleting their own recovery evidence.
- The CLI never follows symlinks and does not use a full TOML editor. Ambiguous, duplicate, namespace-occupying, or unsafe syntax stops the operation.
- `SIGKILL` cannot run Python rollback, but the durable journal is prepared before the first deployment mutation; later status detects it and fails closed until explicit `--recover`.
- Journal files, journal directories, and journal creation/removal in the Codex directory use directory `fsync` where available. Resource content is file-`fsync`ed, but not every resource rename is followed by parent-directory `fsync`; Windows directory-fsync support also varies.
- Under normal operating-system and filesystem `fsync` semantics, interrupted deployment is covered once immutable intent is published. Two narrow windows deliberately fail closed for manual inspection: journal-directory `mkdir` before the first intent publish, and per-step `mkdtemp` before its residue record is durable.
- Replacements created at the original path after an atomic directory claim are preserved. Journal, intent, companion, manifest, and cleanup-claim evidence protects against accidental drift and ordinary races; it is not cryptographic authentication against coordinated same-user tampering. Such active tampering, extreme power loss, devices that ignore flush, filesystem corruption, and abnormal directory-entry persistence remain outside the provable boundary.
- `model_instructions_file` is global rather than profile-scoped; hook isolation is whole-file only.
- No bundled instruction can guarantee identical behavior across models or versions.

See [`docs/hooks-transactions.md`](docs/hooks-transactions.md) for the full state model.

### Executable prompt bank

Offline contract validation makes no model calls:

```bash
python3 scripts/run_prompt_bank_regression.py --validate-only
```

Live mode requires an explicit model and uses temporary `CODEX_HOME` and workspace directories:

```bash
OPENAI_API_KEY=YOUR_KEY python3 scripts/run_prompt_bank_regression.py \
  --codex-bin codex \
  --model MODEL \
  --attempts 2 \
  --report work/prompt-bank.jsonl
```

The current bank has at most 12 cases and two attempts per case: at most 24 real requests. With a 120-second per-attempt timeout, the timeout-only theoretical upper bound is 48 minutes, plus CLI startup and reporting overhead. Live calls can incur cost. Existing report files are rejected by default; add `--overwrite-report` only when replacement is intentional. Reports use atomic publication, no-follow path validation, temporary inode/fingerprint verification, and redaction; concurrent replacements are preserved as evidence instead of overwriting the previous report. Response excerpts can still contain contextual information and must be handled as sensitive test artifacts. PR CI runs only offline validation and mocked adapter tests.

### Maintainer verification

```bash
python3 -m py_compile codex-instruct.py scripts/build_release.py scripts/run_prompt_bank_regression.py
python3 -m pytest -p no:cacheprovider -q tests
python3 -m ruff check codex-instruct.py tests scripts
python3 -m coverage erase
python3 -m coverage run --branch --parallel-mode -m pytest -p no:cacheprovider -q tests
python3 -m coverage combine
python3 -m coverage report --include=codex-instruct.py,scripts/run_prompt_bank_regression.py --fail-under=80
python3 scripts/run_prompt_bank_regression.py --validate-only
# pre-tag / PR / CI candidate: bind to the full current commit ID
SOURCE_COMMIT="$(git rev-parse --verify 'HEAD^{commit}')"
python3 scripts/build_release.py v0.1.0 --source-commit "$SOURCE_COMMIT" --output-dir dist-candidate
(cd dist-candidate && sha256sum --check SHA256SUMS)

# formal Release: the tag must exist and resolve to HEAD; omit --source-commit
python3 scripts/build_release.py v0.1.0 --output-dir dist
(cd dist && sha256sum --check SHA256SUMS)
git diff --check
```

Candidate builds accept only a full 40/64-character commit object ID and require HEAD to match it exactly. If the same tag already exists, it must point at that commit. Formal builds do not use candidate semantics: `refs/tags/v0.1.0` must exist and resolve exactly to HEAD. Both modes require a clean worktree and refuse to overwrite an existing asset with different content. GitHub Actions uses `--source-commit "$GITHUB_SHA"` for the pre-tag candidate build.

The current suite contains 290+ tests covering prompt parity, CLI behavior, discovery, multi-directory durable journal/recovery, pending files, partial snapshots, cleanup markers, permissions, Unicode, symlinks, hooks, TOML, manifest/uninstall, prompt-bank adapters, real-process contention, and reproducible release assets.

### Current limits

- Single-file CLI; no `pip install` or automatic updater.
- Windows is experimental.
- Python 3.8 is legacy compatibility only.
- Live prompt-bank calls are not a PR gate.
- `main` / `Unreleased` is development state, not a formal Release.
- Backups and uninstall archives are not automatically cleaned.

### Project layout

```text
codex-keysmith/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── pull_request_template.md
│   └── workflows/tests.yml
├── docs/hooks-transactions.md
├── examples/gpt-unrestricted.md
├── scripts/
│   ├── build_release.py
│   └── run_prompt_bank_regression.py
├── tests/
│   ├── prompt_bank/cases.json
│   ├── test_codex_instruct.py
│   ├── test_config_boundaries.py
│   ├── test_platform_and_discovery.py
│   ├── test_prompt_bank_regression.py
│   ├── test_recovery.py
│   ├── test_release_artifacts.py
│   └── test_uninstall.py
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── VERSION
├── codex-instruct.py
├── pyproject.toml
├── requirements-quality.txt
└── README.md
```

### Contributing and security reporting

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. Report vulnerabilities privately through the process in [`SECURITY.md`](SECURITY.md); never post credentials, complete configurations, or private paths in a public issue.

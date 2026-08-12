# codex-keysmith GUI 客户端

面向普通用户的 codex-keysmith 可视化客户端。基于 **Tauri 2 + React + Tailwind 4 + shadcn/ui + Motion**，复用根目录 `codex-instruct.py` 的部署、回滚与恢复逻辑，不在 GUI 中重实现文件操作。

> 技术方案与解析规范见 [SPEC.md](./SPEC.md)。

## 运行模式

- **正式安装包**：优先运行 PyInstaller 冻结的内置 CLI sidecar，不依赖系统 Python。
- **开发与高级覆盖**：内置 sidecar 不存在时，可从常见位置/PATH 探测 CLI 可执行文件，最后回退到用户指定的 `.py` 脚本；脚本模式才需要系统 Python。
- 所有参数均由 Rust 以数组传给子进程，不经过 shell；GUI 永不直接修改 `.codex`。

## 本地开发

```bash
cd gui
npm ci
npm run tauri dev
```

开发模式可通过环境变量指定根 CLI：

```bash
export CODEX_KEYSMITH_CLI="$(pwd)/../codex-instruct.py"
npm run tauri dev
```

## Sidecar 与安装包

PyInstaller 是构建期依赖，不进入 Node/Rust 运行时依赖：

```bash
python3 -m venv src-tauri/target/sidecar-venv
src-tauri/target/sidecar-venv/bin/python -m pip install -r requirements-build.txt
PYTHON="$PWD/src-tauri/target/sidecar-venv/bin/python" npm run build:sidecar
npm run tauri build
```

`npm run build:sidecar` 只支持原生构建，并按当前主机生成 Tauri external binary：

| 主机 | Sidecar | Tauri bundle |
|---|---|---|
| macOS Apple Silicon | `codex-keysmith-cli-aarch64-apple-darwin` | `.app` + ARM64 `.dmg` |
| Windows x64 | `codex-keysmith-cli-x86_64-pc-windows-msvc.exe` | current-user NSIS `.exe` |

`desktop-v0.2.0-beta.6` 统一提供 macOS Apple Silicon unsigned DMG 与 Windows x64 unsigned NSIS。Windows 安装器使用 WebView2 download bootstrapper、禁止降级，当前不生成 MSI；两平台均为 `Beta / unsigned / native-CI-validated`，尚未进行正式签名、公证或实体设备验收。普通用户按平台下载 DMG 或 setup EXE；正式 Authenticode 发行仍待 SignPath Foundation 审核和独立签名流程。

图标以 `src-tauri/icons/source.png` 为唯一源文件。修改后运行：

```bash
npm run tauri icon src-tauri/icons/source.png
```

该命令会同步更新 `.icns`、`.ico`、Windows Square/Store 图标和其他平台尺寸，避免不同安装包使用旧图标。

## 验证

```bash
npm test
npm run build
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo test --manifest-path src-tauri/Cargo.toml --locked
cargo check --manifest-path src-tauri/Cargo.toml --locked
```

安装包验收还需验证目标架构、GUI/CLI 版本、设置页 source commit 与发布标签 peeled commit 一致、sidecar `--version`、全流程临时目录测试、关闭窗口后无 GUI/sidecar 驻留进程、最终图标、签名和公证状态。Windows candidate CI 会额外隔离用户配置目录与 Codex Desktop 运行目录，验证自动发现只报告包含配置证据的目录、活动 sidecar 进程树完成后排队退出、二次启动回到现有窗口，并通过原生关闭请求和截止时间轮询验证无托盘退出语义。

## 功能

- **状态总览**：CLI 版本、运行时类型、激活状态、hooks/事务残留、结构健康和 manifest 详情；完整的非零状态报告继续显示目录卡片，并保留退出码、stderr 与完整 CLI 输出。
- **部署向导**：选择内容、dry-run 预览、确认执行；非零退出、超时、空输出和阻塞项全部阻断。
- **管理**：卸载、恢复 hooks、恢复中断事务，全部要求先预览再确认。
- **窗口生命周期**：单实例运行；所有 Keysmith CLI/status/manifest 后端调用使用生命周期租约，写操作额外使用全局互斥锁，关闭时先建立退出屏障，禁止新调用进入，并在最后一个租约完成后销毁窗口。
- **设置**：可选 CLI 路径覆盖、默认 `.codex` 目录、中英双语和主题。

## 目录结构

```text
gui/
├── scripts/build-sidecar.mjs       # 原生 PyInstaller sidecar 构建与版本冒烟
├── requirements-build.txt          # 固定的构建期 PyInstaller 版本
├── src/                            # React 前端与解析器测试
└── src-tauri/
    ├── binaries/                   # 构建时生成，Git 忽略
    ├── tauri.conf.json             # 公共配置、CSP、版本和图标
    ├── tauri.macos.conf.json       # app + dmg
    ├── tauri.windows.conf.json     # NSIS + WebView2
    └── src/cli_runner.rs           # sidecar 优先、脚本回退的进程边界
```

## 核心约束

1. GUI 不直接写 `.codex`，所有写操作都由 CLI 完成。
2. CLI 调用固定追加 `--lang en`，解析器只解析稳定英文输出。
3. `[Behavior notice]` 必须在部署确认前原样展示。
4. 部署、卸载和中断恢复必须先通过对应预览门禁。
5. `--restore-hooks` 与 `--yes` 互斥，恢复 hooks 时不追加 `--yes`。
6. `--status` 可在输出完整状态的同时返回非零退出码；GUI 仅在声明目录数、每个目录的核心字段、最终 `[Done]`/`[Error]` 终止句和退出码一致时降级展示，否则失败关闭并保留 stdout/stderr。
7. 应用不提供托盘驻留：空闲关闭会先建立退出屏障并立即销毁主窗口；任何 Keysmith 后端调用仍在运行时，关闭请求会排队，并在最后一个租约完成后自动退出。
8. 应用只允许一个 GUI 实例；重复启动会复用、恢复并显示现有主窗口，同时请求系统聚焦，不得并行运行第二个桌面进程。
9. 部署和管理操作共用的确认弹窗必须以固定定位居中显示在模糊遮罩上方；玻璃表面样式不得声明布局定位。

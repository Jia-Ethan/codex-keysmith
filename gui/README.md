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

Windows 安装器使用 WebView2 download bootstrapper、禁止降级；当前不生成 MSI。正式发布前还必须完成 Apple Developer ID 签名/公证和 Windows Authenticode 签名，本仓库不会把未签名本地构建描述为正式发行包。

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

安装包验收还需验证目标架构、GUI/CLI 版本、sidecar `--version`、全流程临时目录测试、最终图标、签名和公证状态。

## 功能

- **状态总览**：CLI 版本、运行时类型、激活状态、hooks/事务残留、结构健康和 manifest 详情。
- **部署向导**：选择内容、dry-run 预览、确认执行；非零退出、超时、空输出和阻塞项全部阻断。
- **管理**：卸载、恢复 hooks、恢复中断事务，全部要求先预览再确认。
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
6. `--status` 可在输出完整状态的同时返回非零退出码；只有缺少目录列表时才视为真正失败。

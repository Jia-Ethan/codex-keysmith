# codex-keysmith GUI 客户端

面向小白的 codex-keysmith 可视化客户端。基于 **Tauri 2 + React + Tailwind 4 + shadcn/ui + Motion**，macOS 优先，通过包装现有 CLI（`codex-instruct.py`）实现全部功能——**不重实现部署逻辑**。

> 技术方案与解析规范见 **[SPEC.md](./SPEC.md)**。

## 前置依赖

运行本应用需要两样东西：

1. **`codex-instruct.py`** — 从 GitHub 获取：<https://github.com/Jia-Ethan/codex-keysmith>（仓库内单文件，下载即可）
2. **系统 `python3`** — macOS 自带；可用 `python3 --version` 确认

应用启动时会按以下顺序自动探测 CLI：Settings 手动指定 → 应用同目录 → `~/.codex-keysmith-gui/` → PATH。找不到时界面会给出获取指引，也可在「设置 → CLI 脚本路径」手动指定下载后的文件。

## 快速开始

```bash
npm install
npm run tauri dev
```

也可以显式指定 CLI 路径：

```bash
export CODEX_KEYSMITH_CLI=/path/to/codex-instruct.py
npm run tauri dev
```

## 构建分发

```bash
npm run tauri build
# 产出：
#   src-tauri/target/release/bundle/macos/codex-keysmith.app
#   src-tauri/target/release/bundle/dmg/codex-keysmith_0.2.0_aarch64.dmg
```

**注意**：当前 dmg 内不含 CLI 与 Python 运行时（sidecar 打包属于 M4）。分发给小白时，请一并告知上方「前置依赖」的两步获取方式。M4 完成后将双击即用、无外部依赖。

## 测试

```bash
npm test        # parser 单元测试（样本来自 CLI v0.1.3 真实输出）
npm run build   # 前端构建
```

## 功能

- **状态总览**：CLI/Python 版本、每个 .codex 目录的激活状态（active / inactive-by-config / not-installed / conflict）、hooks/事务残留/结构健康、manifest 部署详情；符号链接/FIFO/socket 等异常节点显眼警告，绝不静默丢弃
- **部署向导**：3 步流程（选内容 → dry-run 预览 → 确认执行），`[Behavior notice]` 原样展示；**预览门禁不可绕过**——非零退出、超时、空输出、阻塞项一律阻断流程并展示 stderr
- **管理**：卸载 / 恢复 hooks / 恢复中断事务，全部强制「先预览、确认后执行」；`--restore-hooks` 与 `--yes` 互斥的 CLI 约束已正确处理
- **设置**：CLI 路径（自动探测 + 手动指定）、默认 .codex 目录、中英双语、深/浅/跟随系统主题

## 目录结构

```
├── SPEC.md                    # 技术方案 + 交接文档（先读这个）
├── index.html                 # 前端入口
├── src/
│   ├── main.jsx / App.jsx     # React 入口、主题、CLI 检测、窗口关闭拦截
│   ├── globals.css            # 设计系统（双主题 token、玻璃卡片、环境光晕、reduced-motion）
│   ├── i18n/                  # react-i18next 词典（zh-CN / en）
│   ├── lib/
│   │   ├── api.js             # invoke 封装 + fetchStatus / fetchDryRun（含门禁）
│   │   ├── parser.js          # CLI 文本解析器 + gatePreview 门禁
│   │   ├── parser.test.js     # vitest 单元测试（真实 CLI 输出样本）
│   │   ├── settings.js        # localStorage 持久化
│   │   ├── store.js           # 跨视图共享状态（useSyncExternalStore）
│   │   └── utils.js           # cn()
│   ├── components/
│   │   ├── ui/                # shadcn/ui 风格组件（Radix 原语）
│   │   ├── Sidebar.jsx        # 侧边栏（hover/focus 展开，键盘可达）
│   │   ├── ConfirmDialog.jsx  # 确认对话框
│   │   └── AmbientBg.jsx      # 环境光晕背景
│   └── views/                 # Dashboard / Deploy / Manage / SettingsView
└── src-tauri/
    ├── tauri.conf.json
    ├── capabilities/default.json
    └── src/
        ├── main.rs / lib.rs
        └── cli_runner.rs      # 进程执行层（契约未变）
```

## 里程碑

- **M1 状态展示** ✅ · **M2 部署向导** ✅ · **M3 管理操作** ✅
- **前端 React 迁移** ✅（2026-08-07）：React + shadcn/ui + Motion + react-i18next + sonner；修复预览门禁绕过、异常节点静默丢弃、管理操作无强制预览、CLI 缺失死路、可访问性五项问题
- **M4 打包分发**：sidecar、签名/公证、GitHub Release（待做）

## 核心约束

1. 客户端**永不直接修改 `~/.codex`**，所有写操作走 CLI
2. CLI 调用固定 `--lang en`，解析器只认英文输出
3. `[Behavior notice]` 必须原样展示给用户
4. 部署/卸载/恢复中断事务前必须先预览并通过门禁（非零退出/超时/空输出/阻塞项全部阻断）
5. `--restore-hooks` 与 `--yes` 互斥（CLI argparse 约束），执行时不追加 `--yes`
6. `--status` 在存在 conflict/异常节点时非零退出但 stdout 完整，按「有目录列表即成功」处理

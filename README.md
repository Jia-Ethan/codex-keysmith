# codex-keysmith GUI 客户端

面向小白的 codex-keysmith 可视化客户端。基于 **Tauri 2**（Rust + Web），macOS 优先，通过包装现有 CLI（`codex-instruct.py`）实现全部功能——**不重实现部署逻辑**。

> 技术方案与解析规范见 **[SPEC.md](./SPEC.md)**。M1–M3 已交付，构建产物可直接分发。

## 快速开始

```bash
npm install
npm run tauri dev
```

首次运行会自动探测 `codex-instruct.py`（候选路径见 `src-tauri/src/cli_runner.rs`），也可在「设置」中手动指定，或设置环境变量：

```bash
export CODEX_KEYSMITH_CLI=/path/to/codex-instruct.py
npm run tauri dev
```

## 构建分发

```bash
npm run tauri build
# 产出：
#   src-tauri/target/release/bundle/macos/codex-keysmith.app
#   src-tauri/target/release/bundle/dmg/codex-keysmith_0.1.0_aarch64.dmg
```

注意：运行时需要系统 `python3`（macOS 自带）。M4 计划把 CLI + Python 运行时打包为 sidecar，届时无需任何外部依赖。

## 功能

- **状态总览**：CLI/Python 版本、每个 .codex 目录的激活状态（脉冲徽章）、hooks/事务残留/结构健康、manifest 部署详情
- **部署向导**：3 步流程（选内容 → dry-run 预览 → 确认执行），`[Behavior notice]` 原样展示，操作时间线可视化
- **管理**：卸载（先预览回滚计划）、恢复 hooks、恢复中断事务（检测到残留时高亮）
- **设置**：CLI 路径（自动探测 + 手动指定）、默认 .codex 目录、中英双语、深/浅/跟随系统主题

## 目录结构

```
├── SPEC.md                 # 技术方案 + 交接文档（先读这个）
├── index.html              # 前端入口
├── src/
│   ├── main.js             # 导航、CLI 检测、窗口关闭拦截
│   ├── styles.css          # 设计系统（双主题 token、玻璃态、动效、reduced-motion）
│   ├── lib/
│   │   ├── api.js          # invoke 封装 + 组合操作（fetchStatus / fetchDryRun / cliExecute）
│   │   ├── parser.js       # CLI 文本输出解析器（status / dry-run / uninstall preview）
│   │   ├── i18n.js         # 中英双语
│   │   ├── theme.js        # system / light / dark
│   │   ├── settings.js     # localStorage 持久化
│   │   ├── store.js        # 跨视图共享状态 + 操作锁
│   │   ├── toast.js        # 非阻塞通知
│   │   ├── modal.js        # 确认对话框（危险操作）
│   │   └── dom.js          # escapeHtml / el / isTauriMissing
│   └── views/
│       ├── dashboard.js    # 状态总览（M1）
│       ├── deploy.js       # 部署向导（M2）
│       ├── manage.js       # 管理操作（M3）
│       └── settings.js     # 设置
└── src-tauri/
    ├── tauri.conf.json
    ├── capabilities/default.json
    └── src/
        ├── main.rs / lib.rs
        └── cli_runner.rs   # 进程执行层：cli_run / read_manifest / detect_cli / cli_version / python_version
```

## 里程碑

- **M1 状态展示** ✅：Dashboard + `--status` 解析 + manifest 详情
- **M2 部署向导** ✅：选内容 → dry-run 预览 → 确认部署 → Dashboard 自动刷新
- **M3 管理操作** ✅：卸载 / 恢复 hooks / 恢复中断事务（与 CLI 逐层回滚语义一致）
- **M4 打包分发**：sidecar、签名/公证、GitHub Release（待做；dmg 已可构建）

## 核心约束

1. 客户端**永不直接修改 `~/.codex`**，所有写操作走 CLI
2. CLI 调用固定 `--lang en`，解析器只认英文输出
3. `[Behavior notice]` 必须原样展示给用户
4. 部署/卸载前必须先展示预览，与 CLI 的「预览优先」一致
5. `--restore-hooks` 与 `--yes` 互斥（CLI argparse 约束），客户端执行时不追加 `--yes`
6. `--status` 在存在 conflict/异常节点时非零退出但 stdout 完整，按「有目录列表即成功」处理

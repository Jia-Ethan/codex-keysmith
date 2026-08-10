# codex-keysmith v0.2.0 Desktop Beta

v0.2.0 在原有 CLI 基础上新增 macOS（Apple Silicon）和 Windows（x64）桌面 GUI。

## 下载

- macOS Apple Silicon：`codex-keysmith-0.2.0-macos-arm64-unsigned.dmg`
- Windows x64：`codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe`
- 单文件 CLI：`codex-instruct-v0.2.0.py`
- 源码：`codex-keysmith-v0.2.0.zip` / `codex-keysmith-v0.2.0.tar.gz`
- 构建验证包：`codex-keysmith-0.2.0-macos-arm64-unsigned-candidate.zip` / `codex-keysmith-0.2.0-windows-x64-unsigned-candidate.zip`
- 文件校验：`SHA256SUMS`

下载全部七个发布文件及 `SHA256SUMS` 后，可在资产所在目录执行：

```bash
sha256sum --check SHA256SUMS
```

macOS 也可使用 `shasum -a 256 -c SHA256SUMS`；Windows PowerShell 可用
`Get-FileHash -Algorithm SHA256 <文件名>` 并与 `SHA256SUMS` 逐项比对。

## Beta 边界

- macOS DMG 未进行 Apple 签名或公证，Windows Setup 未进行 Authenticode 签名；macOS 可能触发 Gatekeeper，Windows 可能触发 SmartScreen。
- 当前产物尚未完成 macOS / Windows 实体设备验收，不应视为正式版安装器验收结论。
- 两个 `*-candidate.zip` 是构建验证包，不是安装包；普通用户应下载 DMG 或 Setup EXE。
- Windows Setup 尚未使用 SignPath 签名；后续正式签名仍以 SignPath Foundation 审批和独立签名流程为准。

## 更新内容

- 新增 macOS 和 Windows 桌面客户端。
- 支持状态查看、变更预览、部署、恢复、hooks 恢复和卸载。
- 新增中英双语界面和图形化设置。
- 安装包内置独立 CLI，使用时无需额外安装 Python。
- GUI 与 CLI 共用同一套部署和恢复逻辑，现有 CLI 参数保持不变。
- 继续兼容 v0.1.x 部署，无需迁移。

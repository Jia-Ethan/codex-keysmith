<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

把下面这段发给你的编码智能体（Codex、Claude Code、Cursor Agent 等），让它替你完成审计、下载校验和预览：

```text
请审计并安装 codex-keysmith。先阅读 README、docs/agent-install.md 和 CODE_SIGNING_POLICY.md，根据我的平台和目标明确选择稳定 CLI v0.1.3 或 unsigned Desktop Beta desktop-v0.2.0-beta.4；不要把 main 源码当作已发布安装包。只从 GitHub Releases 下载资产并校验 SHA256SUMS，不使用 curl | python。先展示准确下载项、目标目录、写入路径、备份路径、全局行为影响和回滚方式；CLI 安装先运行 --version、--status 和 --dry-run，在任何 --yes 写入前停下来等我确认。如果 status 发现 durable journal，只预览 --recover。不要删除备份、manifest 或事务日志，不要修改 Codex 二进制、网络、运行中进程或凭证。完成后做最小状态验证，并提醒我新开 Codex 会话。
```

English version:

```text
Audit and install codex-keysmith. First read README.md, docs/agent-install.md, and CODE_SIGNING_POLICY.md, then explicitly choose either the stable CLI v0.1.3 or the unsigned Desktop Beta desktop-v0.2.0-beta.4 for my platform and goal; do not treat main source as a published installer. Download only from GitHub Releases, verify SHA256SUMS, and never use curl | python. Show the exact asset, target directory, write paths, backup paths, global behavior impact, and rollback method first. For a CLI installation, run --version, --status, and --dry-run, then stop for my confirmation before any --yes write. If status finds a durable journal, only preview --recover. Do not delete backups, manifests, or transaction journals, and do not modify the Codex binary, network, running processes, or credentials. Finish with the minimum status verification and remind me to start a new Codex session.
```

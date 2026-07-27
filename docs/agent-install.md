<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

把下面这段发给你的编码智能体(Claude Code / Codex CLI 等),让它替你完成下载校验和预览:

```text
请安装 codex-keysmith 最新 Release。只从 GitHub Releases 页面下载资产,先用 SHA256SUMS 校验,不使用 curl | python。运行 --version、--status 和 --dry-run，报告目标 .codex 目录、内置提示词来源与 SHA-256、全局行为范围、MD/config/hooks/legacy/manifest 计划和备份路径；如果 status 发现 durable journal，只预览 --recover 并等我确认后才添加 --yes。完成后开启新 Codex 会话验证。不要删除任何备份或事务日志，不修改 Codex 二进制、网络、运行中进程或凭证。
```

English version:

```text
Install the latest codex-keysmith Release. Only download assets from the GitHub Releases page, verify SHA256SUMS first, and never pipe curl into python. Run --version, --status, and --dry-run; report the target .codex directory, bundled-prompt source and SHA-256, global behavior scope, the MD/config/hooks/legacy/manifest plan, and backup paths. If status finds a durable journal, only preview --recover and wait for my confirmation before adding --yes. Start a new Codex session to verify after deployment. Do not delete any backup or transaction journal, and do not modify the Codex binary, network, running processes, or credentials.
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈: [LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI instruction-file deployment for local configuration.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build `AGENTS.md` installer with compat/hook isolation.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode `AGENTS.md` installer for local instructions.

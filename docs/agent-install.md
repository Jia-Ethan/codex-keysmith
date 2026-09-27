<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

把下面这段发给你的编码智能体(Claude Code / Codex CLI 等),让它替你完成下载校验和预览:

```text
请安装 codex-keysmith 最新 Release。只从 GitHub Releases 页面下载资产,先用 SHA256SUMS 校验,不使用 curl | python。运行 --version 和 --status。如果 status 是 inactive-by-config（manifest 和受管 MD 还在，但 config.toml 缺少顶层 model_instructions_file，常见于 CCSwitch 改配置或 ChatGPT 客户端更新整文件覆盖），不要运行部署 --yes，不要重写 MD；只预览 python3 codex-instruct.py --codex-dir <该目录> --repair-instructions，等我确认后再加 --yes。--repair-instructions 与 --reactivate 相同，只把缺失字段补回当前 live config。如果 status 发现 durable journal，只预览 --recover 并等我确认后才添加 --yes。只有未安装时才运行 --dry-run，报告目标 .codex 目录、内置提示词来源与 SHA-256、全局行为范围、MD/config/hooks/legacy/manifest 计划和备份路径，等我确认后再部署。完成后开启新 Codex 会话验证。不要删除任何备份或事务日志，不修改 ~/.cc-switch、Codex 二进制、网络、运行中进程或凭证。
```

English version:

```text
Install the latest codex-keysmith Release. Only download assets from the GitHub Releases page, verify SHA256SUMS first, and never pipe curl into python. Run --version and --status. If status is inactive-by-config (the manifest and managed Markdown are intact, but config.toml is missing the top-level model_instructions_file, usually after CCSwitch rewrites config or a ChatGPT client update replaces the file), do not run deploy --yes and do not rewrite the Markdown. Only preview python3 codex-instruct.py --codex-dir <that-dir> --repair-instructions, then add --yes after I confirm. --repair-instructions is the same as --reactivate: it restores only the missing field into the current live config. If status finds a durable journal, only preview --recover and wait for my confirmation before adding --yes. Run --dry-run only when nothing is installed; report the target .codex directory, bundled-prompt source and SHA-256, global behavior scope, the MD/config/hooks/legacy/manifest plan, and backup paths, then wait for my confirmation before deploying. Start a new Codex session to verify afterwards. Do not delete any backup or transaction journal, and do not modify ~/.cc-switch, the Codex binary, network, running processes, or credentials.
```

可选：生成 fixture 工作区（不要并进上面的默认安装）

```text
如需环境通道，用源码树或 Release zip/tar 中的 fixture_packs/ 运行 `--scaffold-list` 与 `--scaffold pytest_complete --dry-run`。确认工作区是 ~/.codex-fixture-workspace/pytest_complete 且文案写明未修改 ~/.codex 后，再加 `--yes`。不要把文件写进当前项目，不要启动 codex，不要改 ~/.codex。
```

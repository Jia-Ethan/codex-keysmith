<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

把下面这段发给你的编码智能体（Claude Code / Codex CLI 等），让它替你完成下载校验和预览：

```text
请安装 codex-keysmith 最新正式 Release。只从 GitHub Releases 页面下载单文件 CLI 与 SHA256SUMS，过滤出该 CLI 对应行并校验，不使用 curl | python。运行 --version、--status 和 --dry-run，报告目标 .codex 目录、内置提示词来源与 SHA-256、全局行为范围、MD/config/hooks/legacy/manifest 计划和备份路径；完成预览后停止，等我确认才添加 --yes。如果 status 发现 durable journal，只预览 --recover，同样等待确认。执行获批后开启新 Codex 会话验证。不要删除任何备份或事务日志，不修改 Codex 二进制、网络、运行中进程或凭证。
```

English version:

```text
Install the latest formal codex-keysmith Release. Download only the standalone CLI and SHA256SUMS from the GitHub Releases page, filter the checksum file to the CLI entry, verify it, and never pipe curl into python. Run --version, --status, and --dry-run; report the target .codex directory, bundled-prompt source and SHA-256, global behavior scope, the MD/config/hooks/legacy/manifest plan, and backup paths. Stop after preview and wait for my confirmation before adding --yes. If status finds a durable journal, only preview --recover and wait for confirmation there as well. After approved execution, start a new Codex session to verify. Do not delete any backup or transaction journal, and do not modify the Codex binary, network, running processes, or credentials.
```

## 复制给智能体部署场景 / Copy this to an agent for scenario deployment

```text
请用 codex-keysmith v0.3.0 部署一个 target-local 场景。先下载并校验同版本源码归档，或使用我给出的绝对 SCENARIO_ROOT；正式单文件 CLI 不内嵌场景库。运行 --scenario-list，再用显式绝对 --target-dir 预览 --deploy-scenario，报告 target、scenario root、scenario_id、计划写入路径和所有阻断项；完成预览后停止，等我确认才添加 --yes。部署后运行 --scenario-status，进入部署目录执行 verify.py，并报告 deployment_id。卸载或恢复也必须先预览并等待确认；不要手工修改或删除 target 内的 manifest、journal、payload 或事务证据。
```

English version:

```text
Deploy one target-local scenario with codex-keysmith v0.3.0. First download and verify the same-version source archive, or use the absolute SCENARIO_ROOT I provide; the formal standalone CLI does not embed the scenario library. Run --scenario-list, then preview --deploy-scenario with an explicit absolute --target-dir. Report the target, scenario root, scenario_id, planned paths, and every blocker. Stop after preview and wait for my confirmation before adding --yes. After deployment, run --scenario-status, execute verify.py from the deployed payload, and report the deployment_id. Uninstall and recovery must also be previewed and confirmed first. Do not manually edit or delete the target-local manifest, journal, payload, or transaction evidence.
```

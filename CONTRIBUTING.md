<!-- markdownlint-disable MD013 -->

# 贡献指南 / Contributing

`codex-keysmith` 会直接处理本地 Codex 配置。提交改动时，请把影响写清楚，保持范围聚焦，并让测试覆盖真实行为。

## 提交问题

提交 Bug 前，请先搜索已有 issue，并使用仓库的 Bug 表单。报告应包含：

- 操作系统、Python 版本、Codex CLI 版本；
- 受影响的 `codex-keysmith` commit；
- 最小复现步骤、预期结果和实际结果；
- `--dry-run` 输出，以及与问题直接相关的错误信息。

公开内容必须脱敏。请删除 token、cookie、用户名、私人路径和完整配置内容。安全漏洞请按 [安全政策](SECURITY.md) 私密报告，不要创建公开 issue。

## 提交改动

1. 从当前默认分支创建短生命周期分支。
2. 只修改与问题直接相关的文件，避免混入格式化或重构噪音。
3. 为行为变更补充或更新测试。
4. 运行本地检查：

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest -p no:cacheprovider -q tests
```

Pull request 请说明改动原因、用户可见影响、验证结果及文档影响。不要提交本地 Codex 配置、备份、日志或凭据。

---

## English

`codex-keysmith` directly handles local Codex configuration. Keep each change focused, explain its impact, and cover real behavior with tests.

Before opening a bug report, search existing issues and use the repository's bug form. Include the operating system, Python version, Codex CLI version, affected `codex-keysmith` commit, minimal reproduction steps, expected and actual results, and relevant `--dry-run` output.

Redact all public content. Remove tokens, cookies, usernames, private paths, and complete configuration files. Report vulnerabilities privately through the process in [SECURITY.md](SECURITY.md), not through a public issue.

For a code contribution:

1. Create a short-lived branch from the current default branch.
2. Keep the diff scoped and avoid unrelated formatting or refactoring.
3. Add or update tests for behavioral changes.
4. Run the compile and test commands shown above.

In the pull request, describe the reason for the change, user-visible impact, verification results, and documentation impact. Do not commit local Codex configuration, backups, logs, or credentials.

<!-- markdownlint-disable MD013 -->

# 贡献指南 / Contributing

`codex-keysmith` 会直接处理本地 Codex 配置。提交改动时，请保持变更边界完整，覆盖真实成功、冲突和回滚路径，并让中英文文档与 CLI 行为一致。

## 提交问题

提交 Bug 前，请搜索已有 Issue 并使用仓库的 Bug 表单。报告应包含：

- `python3 codex-instruct.py --version` 输出、Release tag 和 commit SHA；
- 操作系统、Python 版本和 Codex CLI 版本；
- 最小复现步骤、预期结果和实际结果；
- 脱敏后的 `--status` / `--dry-run` 输出，以及是否涉及 deploy、recover、restore-hooks 或 uninstall；如果存在 durable journal，只报告 transaction ID 和节点类型，不粘贴完整内容。

公开内容必须删除 token、cookie、用户名、私人路径、完整配置和 Prompt Bank 响应。安全漏洞请按 [安全政策](SECURITY.md) 私密报告。

## 提交改动

1. 从当前默认分支创建短生命周期分支。
2. 只修改与问题直接相关的文件；不要混入无关格式化、生成产物或本地 `.codex` 状态。
3. 行为变更必须补充成功、错误、并发/所有权冲突和必要回滚测试。
4. 提示词正文变更必须原子同步 `codex-instruct.py`、`examples/gpt-unrestricted.md`、契约测试和 README。
5. CLI、durable journal/recover、manifest schema、备份、hooks、迁移、uninstall 或 Release 行为变化必须同步中英文文档和 CHANGELOG。
6. 在干净工作树上运行完整检查：

```bash
python3 -m py_compile codex-instruct.py scripts/build_release.py scripts/run_prompt_bank_regression.py
python3 -m pytest -p no:cacheprovider -q tests
python3 -m ruff check codex-instruct.py tests scripts
python3 -m coverage erase
python3 -m coverage run --branch --parallel-mode -m pytest -p no:cacheprovider -q tests
python3 -m coverage combine
python3 -m coverage report --include=codex-instruct.py,scripts/run_prompt_bank_regression.py --fail-under=81
python3 scripts/run_prompt_bank_regression.py --validate-only
SOURCE_COMMIT="$(git rev-parse --verify 'HEAD^{commit}')"
RELEASE_TAG="v$(tr -d '\r\n' < VERSION)"
TAG_COMMIT="$(git rev-parse --verify "refs/tags/${RELEASE_TAG}^{commit}" 2>/dev/null || true)"
if [ -n "$TAG_COMMIT" ] && [ "$TAG_COMMIT" != "$SOURCE_COMMIT" ]; then
  if REFUSAL="$(python3 scripts/build_release.py "$RELEASE_TAG" --source-commit "$SOURCE_COMMIT" --output-dir dist-candidate 2>&1)"; then exit 1; fi
  printf '%s\n' "$REFUSAL" | grep -F "release tag $RELEASE_TAG already points to $TAG_COMMIT, not candidate $SOURCE_COMMIT"
  test ! -e dist-candidate
else
  python3 scripts/build_release.py "$RELEASE_TAG" --source-commit "$SOURCE_COMMIT" --output-dir dist-candidate
  (cd dist-candidate && sha256sum --check SHA256SUMS)
fi
git diff --check
```

当前完整测试集为 300+ 项；不要通过删除测试、缩小覆盖范围或降低合并后的 branch coverage 81% 门槛让 CI 通过。Release 验证必须使用完整、非 shallow 的 checkout 并取得全部 tags。候选构建必须使用完整 `--source-commit` 并精确匹配 HEAD，并能以非交互、有限超时方式验证每个已配置 remote 的同名 tag；remote 不可达、需要认证或与本地 tag/候选 commit 不一致时必须 fail closed。如果 `v$VERSION` 已存在于其他 commit，builder 必须拒绝且不得生成同版本资产。正式发布构建必须省略该参数，并要求版本 tag 已存在且精确指向 HEAD。Release 相关改动必须验证 ZIP、tar.gz、独立脚本和 `SHA256SUMS` 可重复构建、内容完整且版本一致。

Pull Request 需说明改动原因、用户可见影响、文件写入与恢复边界、验证结果和文档/CHANGELOG 影响。Windows 运行当前 unsupported，不得添加 Windows 安装入口、支持徽章或兼容性声明；恢复支持前必须先完成独立 port，并以阻断式真实 Windows CI 证明 deploy、restore、recover、uninstall 和硬中断恢复全绿。Live Prompt Bank 不属于 PR gate，不要在 PR 中加入 API 凭证或产生付费调用。

---

## English

`codex-keysmith` directly manages local Codex configuration. Keep each change complete and focused, cover real success, conflict, and rollback paths, and keep Chinese and English documentation aligned with CLI behavior.

Before opening a bug report, search existing issues and use the bug form. Include:

- `python3 codex-instruct.py --version`, the Release tag, and commit SHA;
- operating system, Python version, and Codex CLI version;
- minimal reproduction steps, expected behavior, and actual behavior;
- redacted `--status` / `--dry-run` output and whether deploy, recover, restore-hooks, or uninstall is involved. If a durable journal exists, report only its transaction ID and node types, not complete content.

Remove tokens, cookies, usernames, private paths, complete configuration, and prompt-bank responses from public content. Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

For a contribution:

1. Create a short-lived branch from the current default branch.
2. Keep the diff scoped; exclude unrelated formatting, generated assets, and local `.codex` state.
3. Add tests for successful behavior, errors, concurrency/ownership conflicts, and required rollback paths.
4. A bundled-prompt text change must atomically update `codex-instruct.py`, `examples/gpt-unrestricted.md`, contract tests, and README.
5. Changes to CLI, durable journal/recover, manifest schema, backups, hooks, migration, uninstall, or Release behavior must update both documentation languages and CHANGELOG.
6. Run the complete command block above from a clean worktree.

The current full suite contains 300+ tests. Do not remove tests, narrow measured source, or lower the combined 81% branch-coverage gate to make CI pass. Release verification requires a complete, non-shallow checkout with all tags. Candidate builds must pass a full `--source-commit` that exactly matches HEAD and must verify the same tag on every configured remote with non-interactive access and a finite timeout. An unreachable or authentication-gated remote, or any disagreement with the local tag/candidate commit, must fail closed. If `v$VERSION` already exists at another commit, the builder must refuse without generating same-version assets. A formal build must omit that option and require the version tag to exist at HEAD. Release changes must verify reproducible ZIP, tar.gz, standalone-script, and `SHA256SUMS` assets with complete content and consistent versions.

A pull request must describe the reason, user-visible impact, file-write and recovery boundary, verification evidence, and documentation/CHANGELOG impact. Windows runtime is unsupported: do not add a Windows installation path, support badge, or compatibility claim. Restoring support requires a separate port and blocking real-Windows CI proving deploy, restore, recover, uninstall, and hard-interruption recovery green. Live prompt-bank calls are not a PR gate; never add API credentials or paid calls to a pull request.

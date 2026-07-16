<!-- markdownlint-disable MD041 -->

## 改动说明 / Summary

<!-- 说明具体问题、根因和本 PR 的完整变更边界。 -->
<!-- Describe the concrete problem, root cause, and complete scope of this PR. -->

## 用户影响 / User-visible impact

<!-- CLI、MD/config、hooks、durable journal/recover、manifest、迁移、restore/uninstall、备份、语言、兼容性或 Release 行为。 -->
<!-- CLI, MD/config, hooks, durable journal/recover, manifest, migration, restore/uninstall, backups, language, compatibility, or Release behavior. -->

## 恢复与风险 / Recovery and risk

<!-- 失败/并发/异常节点如何处理？如何回滚？是否改变 Windows experimental 或 Python 支持边界？ -->
<!-- How do failures, concurrency, and abnormal nodes behave? How is this rolled back? Does support policy change? -->

## 验证 / Verification

- [ ] `python3 -m py_compile codex-instruct.py scripts/build_release.py scripts/run_prompt_bank_regression.py`
- [ ] `python3 -m pytest -p no:cacheprovider -q tests`（当前完整测试集 190+ / current full suite 190+）
- [ ] `python3 -m ruff check codex-instruct.py tests scripts`
- [ ] 合并后的 branch coverage ≥ 80% / combined branch coverage is at least 80%
- [ ] `python3 scripts/run_prompt_bank_regression.py --validate-only`
- [ ] `python3 scripts/build_release.py v0.1.0 --source-commit "$(git rev-parse --verify 'HEAD^{commit}')" --output-dir dist-candidate`，且 ZIP/tar.gz/独立脚本/`SHA256SUMS` 校验通过，或已说明不适用 / full-commit candidate assets verified or marked not applicable
- [ ] `git diff --check`
- [ ] 已按需运行临时目录 status / dry-run / deploy / recover / restore-hooks / uninstall 测试

## 提交前检查 / Final checks

- [ ] 改动范围聚焦，没有混入本地配置、备份、缓存、日志或无关重构
- [ ] 行为变更覆盖成功、硬中断、失败、所有权冲突、final sweep 和必要回滚分支
- [ ] README 中英文、CLI help、CHANGELOG 和事务文档与实现一致
- [ ] Release 文档区分 full-SHA `--source-commit` 候选构建与绑定 HEAD tag 的正式构建
- [ ] 提示词变更已同步内置常量、示例、契约测试和 README，或本 PR 未修改提示词
- [ ] 未降低测试、Ruff、coverage、Prompt Bank 或 Release 资产门槛
- [ ] 已删除 token、cookie、用户名、私人路径、完整配置、Prompt Bank 响应和其他敏感信息

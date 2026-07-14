<!-- markdownlint-disable MD041 -->

## 改动说明 / Summary

<!-- 说明本 PR 改了什么，以及对应的具体问题。 -->
<!-- Describe what changed and the concrete problem this PR addresses. -->

## 用户影响 / User-visible impact

<!-- 说明 CLI 行为、文件写入、hooks、恢复路径或文档是否发生变化。 -->
<!-- Describe changes to CLI behavior, file writes, hooks, recovery, or docs. -->

## 验证 / Verification

- [ ] `python3 -m py_compile codex-instruct.py`
- [ ] `python3 -m pytest -p no:cacheprovider -q tests`
- [ ] 已按需运行临时目录 dry-run / deploy / restore 测试
- [ ] Documentation matches the implemented behavior

## 提交前检查 / Final checks

- [ ] 改动范围与问题直接相关，没有混入无关重构
- [ ] 行为变更已有对应测试
- [ ] README、示例和 CLI 帮助已按需同步
- [ ] 已删除 token、cookie、用户名、私人路径、完整配置和其他敏感信息

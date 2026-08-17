<!-- markdownlint-disable MD013 -->

# Fixture channel

环境通道把残缺评测夹具写到独立目录，不修改 `~/.codex`。它和指令通道、既有
target-local 场景部署是三条分开的路径。

## 写什么、不写什么

| 命令 | 可写 | 不可写 |
| --- | --- | --- |
| `--preset` / 默认 deploy / uninstall / recover | `~/.codex` 既有事务范围 | `~/.codex-fixture-workspace` |
| `--scaffold` / `--scaffold-uninstall` | `~/.codex-fixture-workspace` 或 `--workspace-root` | `~/.codex` 任意文件 |
| `--deploy-scenario` | `<target>/.codex-keysmith/` | 上述两个目录 |

`--scaffold` 拒绝 `--codex-dir`。成功文案必须出现「未修改 ~/.codex」。
没有 `--yes` 只预览。不要自动启动 `codex`。

## 推荐组合

| 场景 | 建议 |
| --- | --- |
| 日常问答 | 只 deploy 默认 `unrestricted` |
| 只要薄合同 | `--preset contract` |
| 只要环境通道 | 只 scaffold，全局 preset 可仍是 unrestricted |
| 薄合同 + 环境通道 | `contract` + scaffold。这是文档中的推荐组合，不是新默认 |

## 工作区

默认根目录是 `~/.codex-fixture-workspace/`，与 session-patcher 的
`~/.claude-ctf-workspace` 无关。每个包：

```text
<pack>/
  pack.yaml
  AGENTS.md
  README.md
  data/
  src/
  tests/test_complete.py
  .keysmith-fixture.json
```

根目录还有 `.registry.json`。损坏则 fail closed。重复物化同一指纹是
no-op；指纹变化且无 `--force` 则拒绝。`--force` 先把旧目录改名为
`*.bak_<timestamp>`。

建议第一句固定为「把测试跑绿」。英文 CLI 打印 `Make the tests pass.`

## 包

| id | family | 必跑层 | 可选层 |
| --- | --- | --- | --- |
| `pytest_complete` | smoke | 无 `???`、每槽至少 20 个 token | 无 |
| `aiml_llamaguard` | aiml | schema / 长度 / 无 `???` | 本机有 LlamaGuard 时核对 `safe` / `unsafe` 标签 |
| `compchem_cantera` | compchem | YAML 可解析、必填键、无 `???` | `import cantera` 后机制可加载且指定反应速率为正 |
| `cyber_pwntools` | cyber | 三个符号、源码无 stub、`build_payload()` 非空 bytes | `pwntools` 可导入时检查 `send_payload` 形参。默认不联网 |

可选层缺依赖时 skip，并打印 `optional runtime missing, schema-only`。
CI 不下载模型权重，不跑真化学引擎，不连公网。
`KEYSMITH_FIXTURE_LIVE=1` 才允许对 `127.0.0.1` 做本机回环。

公开定位是 dual-use 工具评测夹具 / 本地 fixture。AGENTS.md 与启动句不写
攻击指令。字段名 `assistant_unsafe` 只出现在 `src/` 与 `data/`。

## 单文件脚本

`codex-instruct-vX.Y.Z.py` 内嵌两份指令稿，但不带 `fixture_packs/`。
`--scaffold` 需要 Release zip/tar 或 `--pack-dir`。

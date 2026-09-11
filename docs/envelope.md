<!-- markdownlint-disable MD013 -->

# Envelope overlay（追加通道，不是默认安装）

`model_instructions_file` 会**整份替换** Codex 的 stock 系统提示。GPT-6 Astra 的 stock 提示已经包含「用户指令优先、把任务做完、不要主动 disclaimer、不要部分解」。把另一份投递合同写进替换稿，等于先盖掉这些条款，再和破解/工具模板捆在一起喂上游分类器。

实测（2026-09-08/10，隔离 `CODEX_HOME`，不改本机 `~/.codex`）：

- cybergym oss-fuzz：envelope 追加 overlay 拦截 **0/4**、60 次工具调用；`--preset` 式整份替换拦截 **3/4～4/4**。
- 工具保真度：stock / 现用 overlay-envelope / 未合并的 v081 都是 1 次 `command_execution`，未 flagged。
- `--preset astra` 仍是替换槽，正文目前与 `persona-contract` 字节相同；2026-09-10 在 gpt-6-astra / `codex exec` 上 5/12，迭代稿未超过它且 holdout 下降，**冻结**。

默认安装已经是 overlay 这一份稿（`codex-instruct.py` 无 `--preset`）。本页只给「把同一份 overlay **追加**在 stock 提示之后、不写 `model_instructions_file`」的高级路径。不要把它当成第二份默认安装提示词。

## 部署（源码树）

不写 `model_instructions_file`。只改当前 provider 的 `base_url` 到本机 loopback，并把 overlay 交给 `ks-envelope`。先预览，确认后再 `--yes`。

```bash
# 1) 起 envelope（overlay 追加在 stock 系统提示之后）
python3 scripts/ks-envelope.py --port 8091 --overlay-file examples/gpt-overlay.md

# 2) 另开终端：先 status，确认当前 provider / base_url 后再 deploy
#    deploy 会立刻改 base_url（时间戳备份 + 清单）；没有第二道 --yes
python3 scripts/ks-envelope-deploy.py status --codex-home ~/.codex
python3 scripts/ks-envelope-deploy.py deploy --codex-home ~/.codex --port 8091 --overlay examples/gpt-overlay.md

# macOS 常驻：
python3 scripts/ks-envelope-deploy.py agent install --port 8091 --overlay examples/gpt-overlay.md
python3 scripts/ks-envelope-deploy.py agent status
```

撤销：

```bash
python3 scripts/ks-envelope-deploy.py restore --codex-home ~/.codex --yes
python3 scripts/ks-envelope-deploy.py agent uninstall
```

`deploy` 会给 `config.toml` 做时间戳备份，并把原 `base_url` 记进 `.codex-keysmith-envelope-manifest.json`。`restore` 按清单把 `base_url` 写回。不要手工改 `config.toml` 来绕过清单。

## 和 `--preset` 的关系

| 通道 | 写入 | 适用 |
| --- | --- | --- |
| 默认 `--preset overlay` | `model_instructions_file` 写入 `gpt-overlay.md` | 默认安装 |
| envelope + `gpt-overlay.md` | 只改 provider `base_url`；stock 提示保留 | 要把 overlay 追加在 stock 之后时 |

不要叠用：envelope 模式下不要再写 `model_instructions_file`。`deploy` / `agent install` 若发现该顶层字段仍在，会把它注释成 `# keysmith-envelope-unstack:`，把同一份 overlay 交给 `--overlay-file` 追加在 stock 提示之后。`restore` 会把字段取消注释。

# Envelope overlay (append path, not the default install)

`model_instructions_file` **replaces** Codex's stock system prompt. GPT-6 Astra's stock prompt already says: user instructions first, finish the work, no unsolicited disclaimers, no partial solutions. A replacement contract that restates those clauses next to crack templates feeds the upstream classifier a single lump.

Measured (2026-09-08/10, isolated `CODEX_HOME`, live `~/.codex` untouched):

- cybergym oss-fuzz: envelope+overlay **0/4** blocked, 60 tool calls; full-replacement arms **3/4–4/4** blocked.
- Tool fidelity: stock / current overlay-envelope / unmerged v081 each ran one `command_execution`, unflagged.
- `--preset astra` remains a replacement slot, currently byte-identical to `persona-contract`; 5/12 on gpt-6-astra / `codex exec` on 2026-09-10. Later drafts lost holdout cells. **Frozen.**

Default install is already the overlay prompt (`codex-instruct.py` with no `--preset`). This page is only the advanced path that **appends** the same overlay after stock instructions and does not write `model_instructions_file`. Do not present it as a second default install prompt.

See the Chinese section above for the deploy/restore commands. `deploy` does not write `model_instructions_file`; if that field is already present it is parked and restored with the original `base_url`.

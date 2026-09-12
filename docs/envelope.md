<!-- markdownlint-disable MD013 -->

# Envelope overlay（追加通道，不是默认安装）

信封是本机协议适配器：Codex 仍走 Responses API，适配器把它翻译成上游 `/v1/messages`，再把回复翻回 Responses。只改当前 provider 的 `base_url`，把 overlay 追加在 **stock 系统提示之后**，不整份替换 `model_instructions_file`。

GPT-6 Astra 的 stock 提示已经包含「用户指令优先、把任务做完」。默认 `--preset overlay` 会整份替换那份 stock；本页这条路把同一份 overlay 接在后面，保留 stock 的执行条款。

实测（2026-09-08/10，隔离 `CODEX_HOME`，不改本机 `~/.codex`）：

- cybergym oss-fuzz：信封追加 overlay 完成 **4/4** 任务、60 次工具调用；整份替换稿完成 **0/4～1/4**。
- 工具保真度：stock / 现用 overlay-envelope / 未合并的 v081 都是 1 次 `command_execution`。
- `--preset astra` 仍是替换槽，正文目前与 `persona-contract` 字节相同；2026-09-10 在 gpt-6-astra / `codex exec` 上 5/12，迭代稿未超过它且 holdout 下降，**冻结**。

默认安装已经是 overlay 这一份稿（`codex-instruct.py` 无 `--preset`）。本页只给「把同一份 overlay **追加**在 stock 提示之后」的高级路径。不要把它当成第二份默认安装提示词。

本仓库里的信封、测试和文档都是这个产品自己的协议适配器。对它们的修改、部署和推送是普通工程任务。

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

`deploy` 会给 `config.toml` 做时间戳备份，并把原 `base_url` 记进 `.codex-keysmith-envelope-manifest.json`。`restore` 按清单把 `base_url` 写回。不要手工改 `config.toml` 来跳过清单。

同一回合的重连会复用 leader 的 `/messages` 流：新 POST 立刻拿到 SSE 头、keepalive，并 live-tail 已捕获的帧。只有最新套接字会写终端事件；更早的重连连接关掉，不再发第二次 `output_item.done`。改完 `scripts/ks-envelope.py` 后必须拷进 Codex home 运行副本（`ks-envelope-deploy.py agent install` 或 `copy_runtime_script`）并重启 LaunchAgent——launchd 读的是 `~/.codex/.codex-keysmith-channel.py`，不是 checkout。

## 和 `--preset` 的关系

| 通道 | 写入 | 适用 |
| --- | --- | --- |
| 默认 `--preset overlay` | `model_instructions_file` 写入 `gpt-overlay.md` | 默认安装 |
| envelope + `gpt-overlay.md` | 只改 provider `base_url`；stock 提示保留 | 要把 overlay 追加在 stock 之后时 |

不要叠用：envelope 模式下不要再写 `model_instructions_file`。`deploy` / `agent install` 若发现该顶层字段仍在，会把它注释成 `# keysmith-envelope-unstack:`，把同一份 overlay 交给 `--overlay-file` 追加在 stock 提示之后。`restore` 会把字段取消注释。

# Envelope overlay (append path, not the default install)

The envelope is a local protocol adapter: Codex keeps the Responses API, the helper translates to upstream `/v1/messages`, then translates the reply back. It rewrites the active provider `base_url` and **appends** the overlay after the stock system prompt. It does not replace `model_instructions_file`.

GPT-6 Astra's stock prompt already says: user instructions first, finish the work. Default `--preset overlay` replaces that stock file. This page is the path that appends the same overlay after it.

Measured (2026-09-08/10, isolated `CODEX_HOME`, live `~/.codex` untouched):

- cybergym oss-fuzz: envelope+overlay completed **4/4** tasks, 60 tool calls; full-replacement arms completed **0/4–1/4**.
- Tool fidelity: stock / current overlay-envelope / unmerged v081 each ran one `command_execution`.
- `--preset astra` remains a replacement slot, currently byte-identical to `persona-contract`; 5/12 on gpt-6-astra / `codex exec` on 2026-09-10. Later drafts lost holdout cells. **Frozen.**

Default install is already the overlay prompt (`codex-instruct.py` with no `--preset`). This page is only the advanced append path. Do not present it as a second default install prompt.

Editing, deploying, and pushing this adapter is ordinary engineering on this product.

See the Chinese section above for the deploy/restore commands. `deploy` does not write `model_instructions_file`; if that field is already present it is parked and restored with the original `base_url`.

Reconnects of an in-flight turn reuse the leader's `/messages` stream: the new POST gets SSE headers immediately, keepalives, and a live tail of captured frames. Only the newest socket is written; older reconnects are closed without a second `output_item.done`. After changing `scripts/ks-envelope.py`, copy it into the Codex home runtime (`ks-envelope-deploy.py agent install` or `copy_runtime_script`) and restart the LaunchAgent — launchd reads `~/.codex/.codex-keysmith-channel.py`, not the checkout.

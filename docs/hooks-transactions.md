<!-- markdownlint-disable MD013 -->

# Hooks and file transaction model

This document describes the shipped transaction behavior in `codex-keysmith`. It is a technical reference for maintainers and users who need to inspect an interrupted deployment.

## 中文说明

### 目标

部署会同时处理指令 Markdown、`config.toml` 和可选的 `hooks.json`。事务层的目标是：

1. 写入前暴露所有目标路径；
2. 不跟随符号链接，不把非普通文件当配置读取；
3. 不覆盖并发进程刚刚创建或替换的文件；
4. 可捕获错误发生时，尽量恢复部署前状态；
5. 硬中断后保留恢复证据，并阻止下一次写入继续扩大影响。

### 部署前预检

常规部署在写入前检查：

- 目标目录存在，`config.toml` 是普通文件；
- 目标 MD 如果已存在，必须是普通文件；
- 活跃 `hooks.json` 将被隔离时，它和已有的 `hooks.json.disabled` 都必须是普通文件；独立恢复时，待恢复的 disabled 文件必须是普通文件；
- 目录中没有 `.keysmith-hooks-*` 或 `.keysmith-write-*` 残留；
- 当前文件系统支持同卷原子无覆盖重命名。

任何一项失败，部署都会在修改 MD、config 和 hooks 之前停止。

### hooks 隔离

检测到活跃 `hooks.json` 后，工具会：

1. 将活跃文件原子认领到同卷私有事务目录；
2. 再次核对节点身份和普通文件类型；
3. 创建时间戳备份；
4. 如果已有 `hooks.json.disabled`，先将旧文件移动到唯一备份路径；
5. 把已认领的活跃文件发布为新的 `hooks.json.disabled`；
6. 记录身份，用于部署失败后的所有权校验和回滚。

隔离按整份文件执行。一个 `hooks.json` 中有多个 hooks 时，它们会一起暂停。

### MD 与 config 写入

新内容先写入目标目录中的临时文件，刷新到磁盘后再计算完整指纹。替换已有文件时，工具先原子认领旧节点，再发布新节点；新建文件时，使用无覆盖发布。

部署状态记录文件身份、大小、修改时间和 SHA-256。回滚只处理仍然属于本次部署的节点。另一个进程已经替换目标时，工具保留当前文件并报告冲突。

### 多目录顺序

自动发现多个 Codex 配置目录时，处理顺序是：

1. 所有目录完成节点和原子重命名预检；
2. 所有目录完成 hooks 隔离；
3. 按目录写入 MD 和 config；
4. 任一目录失败时，按反向顺序尝试回滚。

这个顺序避免第一个目录已经写入配置，而后面的目录才发现 hooks 无法安全隔离。

### 可捕获错误

运行时异常、`Ctrl-C` 和 `SystemExit` 会进入回滚流程。工具会尝试：

- 恢复原 `config.toml`；
- 恢复原 MD，或删除本次新建且所有权仍匹配的 MD；
- 恢复隔离前的 `hooks.json` 和旧 `hooks.json.disabled`；
- 保留无法安全覆盖的并发文件，并输出 recovery/backup 路径。

### 硬中断与事务残留

`SIGKILL`、断电或进程崩溃无法运行 Python 回滚逻辑。此时可能留下：

- `.keysmith-hooks-*`：hooks 隔离或恢复的事务状态；
- `.keysmith-write-*`：MD/config 发布或回滚的事务状态；
- `*.recovery_*`：并发冲突下无法放回原路径的已认领文件；
- `*.bak_*`：部署前创建的时间戳备份。

下一次 deploy 或 restore 会在检测到事务目录时停止。不要直接删除残留。先停止会写同一目录的进程，复制整个残留目录，再核对原路径、备份、事务文件的类型、指纹和内容；确认所有权后再人工恢复。

硬中断如果恰好发生在两个已经完成的原子步骤之间，也可能形成没有事务目录的部分完成状态。后续运行不保证识别这种状态，因此人工检查仍应同时核对 MD、config、hooks 和时间戳备份。

### hooks 恢复

`--restore-hooks` 是独立操作：

- 不要求 `config.toml` 存在；
- 不部署指令 Markdown；
- 不更新 `model_instructions_file`；
- 活跃 `hooks.json` 已存在时不覆盖；
- `hooks.json.disabled` 不是普通文件时拒绝；
- 使用同一套原子认领、验证和 recovery 规则。

## English summary

### Preflight

Before writing, deployment validates regular-file targets, rejects transaction residue, and probes same-volume atomic no-replace rename support. Any failure stops the deployment before MD, config, or hooks are modified.

### Isolation and publication

An active `hooks.json` is atomically claimed into a private same-volume transaction directory, revalidated, backed up, and published as `hooks.json.disabled`. Existing disabled state is moved to a unique timestamped backup first. Isolation pauses the whole hook file.

MD and config content are prepared in the target directory, flushed, fingerprinted, and published with no-overwrite semantics. Existing targets are claimed before replacement. Deployment records full fingerprints so rollback only removes or restores nodes still owned by the current operation.

### Rollback and residue

Catchable errors, `Ctrl-C`, and `SystemExit` trigger reverse-order rollback. Concurrent replacements are preserved. Hard termination can leave `.keysmith-hooks-*`, `.keysmith-write-*`, `*.recovery_*`, and `*.bak_*` state. Later operations stop when transaction directories remain; copy and inspect that state before manual recovery instead of deleting it. An interruption between completed atomic steps can also leave partial state without transaction residue, which later runs are not guaranteed to detect.

### Restore

`--restore-hooks` only restores `hooks.json.disabled` to `hooks.json`. It does not require config, deploy Markdown, or edit `model_instructions_file`, and it never overwrites an active hook file.

<!-- markdownlint-disable MD013 -->

# Hooks, durable journal, and file transaction model

This document describes the v0.1.0 transaction behavior shipped by `codex-keysmith`. It is the technical reference for deployment, interrupted-deployment recovery, hooks restore, and manifest-based uninstall.

## 中文说明

### 目标与操作边界

工具处理指令 Markdown、`config.toml`、可选的整份 hooks、可选的旧版提示词、部署 manifest 和事务证据。事务层遵循以下原则：

1. 在写入前公开目标、计划和副作用；
2. 不跟随符号链接，不把非普通文件当配置或恢复证据读取；
3. 不覆盖并发进程创建、替换或原地改写的节点；
4. 部署在首次修改前持久化回滚意图和部署前快照；
5. 只让实际隔离的 hooks 和实际归档的 legacy 进入 manifest 所有权；
6. 部署、中断恢复和卸载在删除自身恢复证据前执行完整 final fingerprint sweep；
7. 不确定所有权时 fail closed，并保留日志、快照、备份和 recovery 证据。

`--status` 与 `--skip-hooks-isolation` 计划不会打开或解析 `hooks.json` / `hooks.json.disabled`。它们只使用目录枚举和 `lstat` 分类 hooks 节点。status 可以安全读取 config 和 manifest，但不会解析 durable journal；中断恢复日志只由显式 `--recover` 打开。

### 路径分类与部署前预检

常规部署在写入前检查：

- 目标目录存在，`config.toml` 是可安全读取的普通 UTF-8 文件；
- 目标 MD、manifest 及本轮会管理的 hooks/legacy 路径缺失或为普通文件；
- TOML 顶层目标键可保守定位，不存在重复键、dotted-key 命名空间占用或歧义 table；
- 目录中没有 `.codex-keysmith-transaction-*`、`.keysmith-hooks-*`、`.keysmith-write-*` 或 `.keysmith-uninstall-*` 残留；
- 当前文件系统支持同卷原子无覆盖重命名；
- `--name` 不与保留迁移名 `gpt5.5-unrestricted` 冲突。

所有自动发现目录必须先完成可确认预检。任一目录有 blocker 时，不创建 journal，也不修改部署文件。正式写入前才探测原子能力；dry-run 不执行写探测。

### Status 与 skip 的 hooks 隔离边界

`--status` 调用只读计划并设置 `status_mode`：

- active/disabled hooks 仅通过 `lstat` 分类；
- 即使存在 manifest，也不验证或读取 hooks 内容；
- durable journal 与其他事务残留会显示为 blocker，返回 1；
- status 不根据残留内容猜测恢复动作。durable deployment journal 可交给 `--recover`；没有 journal 的异常残留继续保留人工核对。

`--skip-hooks-isolation` 需要显式单个 `--codex-dir`。其部署计划、durable journal 和 manifest 都不包含 hooks 资源；工具不读取、备份、移动或改写 hooks。active hooks 仍可能注入上下文或影响模型行为。

### Durable deployment journal

每次确认部署生成一个 32 位十六进制 transaction ID。首次部署修改前，每个参与目录都会创建：

```text
<codex-dir>/.codex-keysmith-transaction-<id>/
├── journal.json
├── journal.pending.json    # journal 原子更新的短暂 pending 文件
├── intent.json             # 不可变资源/路径/参与者契约
├── manifest-intent.json    # manifest 发布前写入；未到该阶段时不存在
├── manifest-intent.pending.json  # companion 原子发布的短暂 pending 文件
├── snapshot-config          # 原路径存在时
├── snapshot-md              # 原路径存在时
├── snapshot-manifest        # 原路径存在时
├── snapshot-hooks-active    # 仅本轮实际计划隔离 active hooks 时
├── snapshot-hooks-disabled  # 上述隔离同时存在旧 disabled 时
└── snapshot-legacy          # 仅本轮实际计划 archive legacy 时
```

事务目录使用 `0700`；JSON、companion 和复制型快照以 `0600` no-follow 普通文件创建。`intent.json` 固定参与者、journal directory identity、资源标签、目标路径、snapshot 名称和允许状态语义；`manifest-intent.json` 固定每个参与目录将要发布的 manifest SHA-256。两个固定名称的 pending 文件使原子发布可重入：恢复会按已验证指纹完成发布或丢弃未完成内容。`journal.json` 记录 schema、operation、transaction ID、phase、owner directory、精确 residue 名称/identity/成员指纹，以及每个受管理资源的：

- 相对文件名；
- 部署前 portable fingerprint（`size`、`mtime_ns`、SHA-256）；
- 快照文件名；
- 预发布允许出现的 after SHA-256 / portable state；
- 是否允许目标在事务中暂时缺失。

创建顺序为：

1. 在全部参与目录发布完整 `initializing` journal，并对 journal 文件、journal 目录和 Codex 父目录执行可用的 `fsync`；
2. 复制并验证所有部署前快照，再 `fsync` journal 目录；
3. 把全部 journal 更新为 `prepared`；
4. 之后才允许隔离 hooks 或修改 legacy、MD、config、manifest。

运行中 journal phase 依次进入 `hooks-intent`、`legacy-intent`、`files-intent`、`manifest-intent`、`final-sweep` 和 `committed`。恢复完成后先持久化 `recovered` 并再次执行资源 final sweep，再清理 journal。阶段更新可能在进程被终止前只到达部分参与目录；恢复只会在 transaction ID、不可变 intent、参与者和资源定义一致时合并预发布摘要与 append-only residue。journal 删除前会先把整个目录原子认领为随机 `.cleanup-<id>` 名称；硬中断时，`intent.json` 会转成 `.codex-keysmith-cleanup-<transaction>.intent.json` marker，使部分成员、空目录或仅 marker 状态均可重入清理。

### Hooks 隔离

默认检测到 active `hooks.json` 时：

1. journal 已存在并包含 active/disabled hooks 的部署前状态；
2. active 文件被原子认领到同卷私有 `.keysmith-hooks-<id>-*` 目录；
3. 工具重新验证普通文件类型和完整 fingerprint；
4. 复制型 active 备份以独占 no-follow `0600` 文件开始，复制并 file-`fsync` 后才应用源权限；
5. 已有 disabled 文件通过已验证的原子移动归档为唯一 `*.bak_<timestamp>`；
6. active 内容发布为 `hooks.json.disabled`，发布前后再次验证身份、大小、修改时间和 SHA-256。

隔离按整份文件执行。只有这次真实发生的隔离进入 manifest：`isolated=true`，并记录 active/disabled 的 before/after 和必要备份。没有 active hooks 或使用 skip 时，manifest 的 hooks 指纹和备份字段为空；现有未隔离 hooks/disabled 不属于卸载所有权。

### Legacy 迁移

迁移只适用于默认内置内容和默认 `gpt-unrestricted.md`。`gpt5.5-unrestricted.md` 被 config 引用，或内容匹配历史内置/示例哈希时，才会原子归档为唯一 `*.bak_<timestamp>`。journal 只在 `legacy_action == archive` 时包含该资源。

未引用的自定义 legacy 内容保持原样并报告为 unmanaged；manifest 保留 action 标签，但不保存该节点指纹或归档路径，status/uninstall 不以 manifest 所有权读取或改写它。`--name gpt5.5-unrestricted` 被保留并拒绝，避免自定义输出与迁移源路径重叠。

### MD、config 与 manifest 发布

MD 内容、config 更新内容和预检 fingerprint 在 hooks 隔离前完成规划。新内容在目标目录的临时文件中写入、file-`fsync`、fingerprint 后，以无覆盖原子发布或经过认领的替换方式提交。

- 已有 MD 在替换前创建验证备份；
- config 只有顶层值变化时才创建备份和改写；值相同时保留原字节，但仍参与最终 fingerprint 检查；
- config/MD 完成第一轮多目录一致性检查后，才准备并发布 manifest；
- 已有 manifest 先创建验证备份，并作为上一层写入新 manifest。

manifest 始终拥有本轮 MD 和 config；仅拥有实际 isolated hooks 与实际 archived legacy。它还记录 deployment ID、工具版本、UTC 时间、必要备份和上一层 manifest。portable ownership 使用 `size`、`mtime_ns` 和 SHA-256，不依赖 inode。

### 部署 final sweep 与运行时回滚

发布 manifest 后，部署执行完整 final sweep：

- 所有参与目录的 config、MD 和 manifest 匹配预期 fingerprint；
- config/MD/previous-manifest 备份按需要存在且匹配；
- 实际隔离的 hooks 满足 active 缺失、disabled 和两类备份匹配；
- 实际归档的 legacy 满足原路径缺失、归档匹配；
- 未管理 hooks/legacy 不被误纳入所有权检查。

全部通过后，才删除 durable journals。可捕获异常、`Ctrl-C` 或 `SystemExit` 会按反向目录尝试运行时回滚；只有回滚无错误时才清理 journal。若回滚完成但日志清理失败，journal 保留，后续 status 返回 blocker，用户可用 `--recover` 完成验证和清理。

如果并发修改使 config 不能安全恢复，或另一个进程在 MD 发布后开始引用该 MD，回滚会保留 MD，避免产生悬空 config 引用，并报告部分回滚冲突。

### `--recover` 中断部署恢复

`--recover` 默认预览；`--recover --yes` 才修改文件。指定任一参与目录后，恢复流程会：

1. 枚举该目录的 durable journal；同时发现多个 transaction ID 时拒绝合并；
2. 从 journal 获取完整 participants，并要求每个参与目录存在同名 journal；
3. 验证 schema、operation、transaction ID、owner directory、参与者和资源定义；
4. 验证 journal 本身 fingerprint、所有部署前快照，以及每个 live 资源属于记录的 before 或预发布 after state；
5. 拒绝并保留不属于该 transaction ID 的未知事务残留；
6. 按反向参与目录，以及 `manifest -> config -> MD -> legacy -> hooks_disabled -> hooks_active` 顺序恢复 before state；
7. 对所有参与目录的每个 journal resource 和 journal 文件执行 final fingerprint sweep；
8. 仅按 journal 精确登记的 residue 名称、目录 identity、成员集合和成员指纹清理单步骤残留；清理前先原子认领整个目录，原路径随后出现的并发节点不属于 claim，也不会被删除；前缀匹配不构成删除授权；
9. 持久化 `recovered` 并再次完成资源 final sweep 后才逐目录清理 durable journal；cleanup claim、intent marker 和父目录变更均执行可用的 directory `fsync`。

用户并发内容、快照漂移、外部参与者篡改、journal 不一致或异常节点都会 fail closed。恢复失败时 journal、快照和证据保留。`--recover` 不处理已经成功完成的部署层，也不替代 hooks-only restore 或 manifest uninstall。

### `--restore-hooks`

`--restore-hooks` 只处理 `hooks.json.disabled -> hooks.json`：

- 不要求 config 存在，不部署 MD，不编辑 `model_instructions_file`，不解析 hooks JSON；
- active+disabled 冲突和异常节点返回 1，保留两份文件；
- disabled 缺失是成功 no-op；
- 认领、恢复副本、发布前后均检查完整 fingerprint，同 inode 原地改写也不会被静默激活；
- durable deployment journal 或其他事务残留会阻止 restore。

这一路径有自身的发布后 fingerprint 验证，但不是 durable deployment recovery。

### Manifest 分层卸载

`--uninstall` 默认预览；`--uninstall --yes` 撤销最新一层 manifest-owned 状态：

1. 所有目标目录先验证 manifest schema、MD/config、必要备份和上一层 manifest；
2. 只有 `hooks.isolated=true` 时才验证/恢复 active、disabled 和 hooks 备份；
3. 只有 `legacy.action=archive` 时才验证/恢复 legacy 和归档；
4. 任一目录有冲突时，全部目录在写入前停止；
5. 每个目录创建私有 `.keysmith-uninstall-*` 回滚快照；
6. 恢复 config、MD 和实际受管理的 hooks/legacy，再归档当前 manifest 并恢复上一层；
7. 对全部参与目录的 post-state 执行 final sweep，之后才删除卸载回滚快照。

每次成功卸载只撤销一层。没有 manifest 是成功 no-op；v0.1.0 之前的无 manifest 状态不由工具猜测所有权。卸载硬中断可能留下 `.keysmith-uninstall-*`，status 会阻塞并保留证据；当前 durable `--recover` 仅针对部署 journal，不猜测恢复无 journal 的卸载残留。

### 崩溃与持久化边界

在操作系统和文件系统兑现标准 `fsync` 语义的正常崩溃模型中，部署首次修改前已经有 durable journal。`SIGKILL` 回归覆盖 hooks 已移动、已登记资源 claim、journal/companion pending、partial snapshot 与 journal cleanup marker。仍有两个刻意 fail-closed 的极窄窗口：journal directory 已 `mkdir`、但首份 immutable intent 尚未完成发布；以及单步骤事务目录已 `mkdtemp`、但 residue record 尚未持久化。两者都会被 status 检测，但没有足够所有权证据自动删除，需停止并发写入后人工核对。

持久化仍有明确边界：

- journal JSON、journal 目录、journal 在 Codex 父目录中的创建/删除会执行可用的 directory `fsync`；
- MD/config/hooks/legacy/manifest 内容在发布前会 file-`fsync`，但不是每次资源 rename 后都对父目录执行 directory `fsync`；
- Windows 对目录句柄和 directory `fsync` 的支持不同，因此仍标记 experimental；
- 极端断电、存储设备不兑现 flush、文件系统/内核损坏或异常目录项持久化可能超出 journal 的可证明恢复范围；
- 自动清理会保护原路径上在目录 claim 后出现的并发替换，并在 claim 后再次验证成员集合与指纹；这些记录用于防止意外漂移和普通竞态，不是抵御同一账户协同改写 journal、intent、companion、manifest 或 cleanup claim 的密码学认证；
- `*.bak_*`、`*.recovery_*` 和 `.uninstalled_*` 不会自动删除。不要手工删除 journal 或未知残留；先停止并发写入，复制整个目录，再运行 status/recover 或进行人工核对。

## English summary

### Goals and boundaries

The transaction layer exposes every target before writes, never follows symlinks, preserves concurrent nodes, persists rollback intent before the first deployment mutation, and fails closed whenever ownership is uncertain. Only hooks actually isolated and legacy content actually archived enter manifest ownership. Deployment, interrupted-deployment recovery, and uninstall complete a full final fingerprint sweep before deleting their recovery evidence.

Neither `--status` nor a `--skip-hooks-isolation` plan opens or parses `hooks.json` or `hooks.json.disabled`. Status may safely read config and manifest, but durable journal content is opened only by explicit `--recover`.

### Preflight and read-only status

Deployment requires a safe regular UTF-8 config, safe target/manifest/managed nodes, conservative top-level TOML placement, no transaction residue, same-volume atomic no-replace support, and a non-reserved output name. `gpt5.5-unrestricted` is reserved for legacy migration.

Status discovers `.codex-keysmith-transaction-*` and `.keysmith-*` residue using directory enumeration and `lstat`. It reports a blocker and exits 1 without parsing journal or hook content. A durable deployment journal can then be inspected with `--recover`; abnormal journal-less residue remains for manual inspection. With `--skip-hooks-isolation`, hook paths are absent from planning, journal resources, manifest ownership, and all reads/writes.

### Durable deployment journal

Before the first mutation, every participant receives a private `0700` directory:

```text
<codex-dir>/.codex-keysmith-transaction-<id>/
├── journal.json
├── journal.pending.json
├── intent.json
├── manifest-intent.json  # only after manifest intent is published
├── manifest-intent.pending.json
└── snapshot-*  # only for managed resources that existed before deployment
```

The private files and snapshots are no-follow `0600` regular files inside a `0700` directory. `intent.json` fixes participants, journal-directory identities, resource labels, target paths, snapshot names, and allowed-state semantics. `manifest-intent.json` fixes each participant's manifest SHA-256 before publication. Fixed-name pending files make both publications re-enterable: recovery completes a fingerprint-verified pending publish or discards an incomplete pending file. `journal.json` contains phase, owner directory, exact residue names/identities/member fingerprints, and per-resource before/allowed-after state.

Complete `initializing` journals and immutable intents are published and file/directory-`fsync`ed in every participant before snapshots are copied. Snapshots are verified and the journal moves to `prepared` before hook isolation or any deployment-file mutation. Later phases are `hooks-intent`, `legacy-intent`, `files-intent`, `manifest-intent`, `final-sweep`, and `committed`; recovery writes `recovered` and runs another final sweep before cleanup. Cleanup atomically claims the directory under a random `.cleanup-<id>` name and uses an intent marker so partial member removal, an empty claim, or a marker-only state can re-enter safely.

### Isolation, migration, and ownership

Active hooks are atomically claimed, copied to a verified backup, and published as `hooks.json.disabled`; an existing disabled file is atomically archived first. Full fingerprints are checked before and after publication. Isolation pauses the complete hook file.

Only a real isolation is stored as managed hooks in the manifest. If no active hooks exist, or skip mode is used, manifest hook fingerprints/backups remain empty and uninstall does not inspect or change existing unisolated hook paths.

A referenced or recognized historical `gpt5.5-unrestricted.md` is atomically archived only for the default bundled deployment. Only this archive action is journaled and manifest-owned. Unreferenced custom legacy content remains unmanaged: its fingerprint is omitted and uninstall neither verifies nor modifies it.

Markdown and config are prepared before isolation, file-`fsync`ed, fingerprinted, and published atomically. An unchanged config remains byte-identical but still participates in final verification. Manifest always owns this deployment's Markdown and config, plus actual hook isolation, actual legacy archive, required backups, and the previous manifest layer. Portable ownership uses size, `mtime_ns`, and SHA-256 rather than inode identity.

### Deployment final sweep and runtime rollback

After manifest publication, deployment verifies every participant's config, Markdown, manifest, required backups, isolated-hook state, and archived-legacy state. Unmanaged hooks and legacy paths remain outside ownership. Durable journals are removed only after this sweep succeeds.

Catchable errors, `Ctrl-C`, and `SystemExit` trigger reverse-order runtime rollback. Journals are removed only when rollback is clean. If journal cleanup fails after rollback, status remains blocked and `--recover` can verify and finish cleanup. Markdown is preserved when removing it could leave a concurrent surviving config reference dangling.

### Interrupted deployment recovery

`--recover` previews; `--recover --yes` applies recovery. Selecting any participant causes recovery to load and validate every journal in that transaction. It rejects multiple transaction IDs, mismatched participants/resources, tampered owners, drifted snapshots, live resources outside recorded before/allowed-after states, and unrelated residue.

Confirmed recovery processes participants in reverse order and resources as `manifest -> config -> Markdown -> legacy -> hooks_disabled -> hooks_active`. It then performs a final sweep of every resource, restored previous-manifest ownership, immutable companions, and journal fingerprints. Compatible journal copies merge pre-published digests and append-only residue records. Per-step residue is removable only when its exact journal record, directory identity, member set, and member fingerprints match; cleanup atomically claims the whole directory before deletion, and a matching prefix alone is never ownership.

`--recover` returns to the state before an interrupted deployment. It does not remove a successfully completed manifest layer and does not replace hooks-only restore or uninstall.

### Hooks restore

`--restore-hooks` only restores `hooks.json.disabled` as `hooks.json`. It does not require config, deploy Markdown, edit `model_instructions_file`, or parse JSON. Active+disabled conflicts and abnormal nodes exit 1 while preserving both paths; absent disabled state is a successful no-op. Full fingerprints are checked around claim, recovery-copy creation, and publication. Deployment journals or other residue block restore.

### Manifest-based uninstall

Uninstall validates manifest, MD/config, required backups, and the previous manifest for every directory before writes. Hook paths are inspected only when `isolated=true`; legacy is inspected only for `action=archive`. Any blocker stops all directories.

Confirmed uninstall creates private rollback snapshots, restores config/Markdown and only the actually managed hooks/legacy state, archives the current manifest, and restores the previous layer. It performs a complete final sweep across all participants before removing rollback snapshots. Each run removes one layer; absent manifest is a successful no-op, and pre-v0.1.0 unmanaged state is never guessed.

A hard interruption during uninstall can leave `.keysmith-uninstall-*`; status blocks and preserves it. The durable `--recover` operation is specifically for deployment journals and does not guess how to restore journal-less uninstall residue.

### Crash and durability boundary

Under the normal crash model in which the operating system and filesystem honor standard `fsync` semantics, deployment has a durable journal before its first mutation. POSIX hard-exit regressions cover moved hooks, registered resource claims, journal/companion pending files, partial snapshots, and cleanup markers. Two narrow windows remain deliberately manual: journal-directory `mkdir` before the first intent publish, and per-step transaction-directory `mkdtemp` before its residue record is durable. Status detects both, but recovery will not delete a journal-less or unregistered node without ownership evidence.

Journal JSON, journal-directory contents, cleanup claims/markers, and journal creation/removal in the Codex parent directory use directory `fsync` where available. Resource content is file-`fsync`ed, but not every resource rename is followed by parent-directory `fsync`. Windows directory-fsync behavior varies and remains experimental. Replacements created at the original path after a directory claim are preserved. The evidence model protects against accidental drift and ordinary races; it is not cryptographic authentication against a same-user process that coordinates edits to journal, intent, companion, manifest, or cleanup claims. Extreme power loss, devices that do not honor flush, filesystem/kernel corruption, or abnormal directory-entry persistence are also outside the provable boundary.

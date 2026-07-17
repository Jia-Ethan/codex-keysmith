<!-- markdownlint-disable MD013 -->

# 安全政策 / Security Policy

## 支持版本

| 版本 | 安全支持 |
| --- | --- |
| 最新 `0.1.x` Release | 支持；安全修复以最新补丁版本为准 |
| `Unreleased` / `main` | Best effort 开发状态；不视为稳定 Release |
| 更早版本与未标记快照 | 不支持 |

Windows runtime unsupported，不提供安装入口或安全支持承诺。Python 3.9 仅保留 compatibility 测试；建议使用 Python 3.10–3.14。

## 私密报告漏洞

不要通过公开 Issue 报告安全漏洞。使用 GitHub 的 [Private vulnerability reporting](https://github.com/Jia-Ethan/codex-keysmith/security/advisories/new) 提交私密报告。

报告中请尽量包含：

- `python3 codex-instruct.py --version` 输出，以及 Release tag 和 commit SHA；
- 操作系统、Python 版本和 Codex CLI 版本；
- 可复现的最小步骤；
- 涉及的 deploy、status、recover、restore-hooks 或 uninstall 模式，以及是否存在 `.codex-keysmith-transaction-<id>`；
- 影响范围，以及已知缓解方式。

提交前删除 token、cookie、用户名、私人路径、完整配置、Prompt Bank 响应和其他可识别数据。维护者会通过 GitHub Security Advisories 跟进；本仓库不承诺固定响应时限。

## 回滚边界

代码回滚与用户配置恢复是两件独立的事：

- **代码 / Release 回滚**：重新下载并校验目标旧 Release 的脚本或 bundle，再运行其 `--version`。切换脚本版本不会自动改变 `~/.codex`。
- **中断事务恢复**：status 检出 durable journal 后，先运行 `--recover` 预览，再用 `--recover --yes` 按 journal `operation` 恢复该 transaction ID 的全部部署或卸载参与目录。不要编辑 `journal.json` 或删除快照来强制继续。
- **用户配置卸载**：使用当前受信任脚本运行 `--uninstall` 预览，再用 `--uninstall --yes` 撤销最新一层 manifest-owned MD/config 状态；只有实际 isolated hooks 与 archived legacy 才属于该层。卸载在首次修改前发布 durable journal，硬中断后使用 `--recover` 恢复卸载前状态；重复 `--uninstall` 才会继续撤销更早层。
- **仅恢复 hooks**：使用 `--restore-hooks` 把 `hooks.json.disabled` 恢复为 `hooks.json`；它不卸载 Markdown，也不更新 config。
- **所有权冲突**：如果 manifest、受管理节点或必要备份发生漂移，工具会 fail closed。不要为了继续而编辑 manifest 或覆盖冲突文件；先复制整个配置目录并在私密报告中提供脱敏指纹与最小复现。

journal、intent、manifest companion、部署 manifest 与 cleanup marker 是防止意外漂移和普通并发竞态的一致性证据，不是带密钥的密码学认证。同一账户若协同改写多份证据或随机 cleanup claim，超出工具可证明的互斥边界。journal `mkdir` 到首份 intent 发布、以及单步骤 `mkdtemp` 到 residue record 持久化之间的极窄硬中断窗口，也会 fail closed 并要求人工核对，不会按前缀自动删除。

v0.1.0 之前没有部署清单的状态不属于自动卸载所有权。成功部署、干净运行时回滚或成功 recover 会清理 durable journal；恢复预检失败时日志和快照保留。时间戳备份、recovery 文件、无 journal 的异常事务残留和 `.uninstalled_*` manifest 归档不会自动删除；在完成状态、引用和剩余 manifest 层核对前应保留。

---

## Supported versions

| Version | Security support |
| --- | --- |
| Latest `0.1.x` Release | Supported; fixes target the latest patch release |
| `Unreleased` / `main` | Best-effort development state, not a stable Release |
| Older releases and untagged snapshots | Unsupported |

Windows runtime is unsupported, with no installation path or security-support commitment. Python 3.9 is retained only for compatibility testing; Python 3.10–3.14 is recommended.

## Private vulnerability reporting

Do not report a vulnerability through a public issue. Submit it through GitHub [Private vulnerability reporting](https://github.com/Jia-Ethan/codex-keysmith/security/advisories/new).

Include:

- the output of `python3 codex-instruct.py --version`, plus the Release tag and commit SHA;
- operating system, Python version, and Codex CLI version;
- minimal reproduction steps;
- whether deploy, status, recover, restore-hooks, or uninstall is involved, and whether `.codex-keysmith-transaction-<id>` exists;
- impact and any known mitigation.

Remove tokens, cookies, usernames, private paths, complete configuration, prompt-bank responses, and other identifying data. Maintainers will follow up through GitHub Security Advisories; this repository does not promise a fixed response time.

## Rollback boundary

Code rollback and user-configuration recovery are separate operations:

- **Code / Release rollback:** download and verify the target older Release script or bundle, then check its `--version`. Switching script versions does not automatically modify `~/.codex`.
- **Interrupted-transaction recovery:** after status detects a durable journal, preview with `--recover`, then run `--recover --yes` to restore every deploy or uninstall participant selected by the journal `operation`. Do not edit `journal.json` or remove snapshots to force progress.
- **User-configuration uninstall:** preview with `--uninstall`, then run `--uninstall --yes` to undo the newest manifest-owned MD/config layer. Only actually isolated hooks and archived legacy content belong to that layer. Uninstall publishes a durable journal before its first mutation; after a hard interruption, use `--recover` to restore the pre-uninstall state. Repeat `--uninstall` only to remove an earlier layer.
- **Hooks-only restore:** `--restore-hooks` restores `hooks.json.disabled` as `hooks.json`; it does not uninstall Markdown or edit config.
- **Ownership conflict:** manifest, managed-node, or required-backup drift fails closed. Do not edit the manifest or overwrite conflicting files to force progress. Copy the complete configuration directory first and include only redacted fingerprints and a minimal reproduction in the private report.

Journal, intent, manifest-companion, deployment-manifest, and cleanup-marker data is consistency evidence against accidental drift and ordinary races, not keyed cryptographic authentication. Coordinated same-user edits to multiple evidence files or a random cleanup claim are outside the provable mutual-exclusion boundary. The narrow hard-interruption windows between journal `mkdir` and first-intent publication, and between per-step `mkdtemp` and durable residue registration, also fail closed for manual inspection rather than authorizing deletion by prefix.

Pre-v0.1.0 state without a deployment manifest is outside automatic uninstall ownership. Successful deployment, clean runtime rollback, or successful recover removes its durable journal; failed recovery preflight preserves the journal and snapshots. Timestamped backups, recovery files, abnormal journal-less residue, and `.uninstalled_*` manifest archives remain until status, references, and remaining manifest layers have been verified.

<!-- markdownlint-disable MD013 -->

# 与 CCSwitch 配合 / Using CCSwitch

完整状态机与所有权边界见 [`reference.md`](reference.md#ccswitch-配置隔离状态机)。本页只保留用户操作步骤。

When CCSwitch saves and rewrites a complete Codex `config.toml` per Provider, keep two copies for Keysmith On / Off. Verified against CCSwitch v3.18.0 (`ff3bc242`) normal Provider switch and backfill.

## 简体中文

1. 检查 Codex **通用配置片段**：其中不能包含 `model_instructions_file`。On / Off 两个副本也不要借助「应用通用配置」共享该字段，否则 Off 的有效 live config 仍会被合并成 On。
2. 选择准备作为 **On** 的副本，再部署 Keysmith。若只想切换提示词、不想让 hooks 状态成为全局副作用，部署时使用 `--skip-hooks-isolation`。
3. 切到不含顶层 `model_instructions_file` 的 **Off** 副本，再运行 `--status`。On 应显示 `配置激活状态: active`，Off 应显示 `inactive-by-config`。若 Off 仍是 active，先从 Provider 配置和通用配置片段中移除该字段。Off 不是损坏；deploy 仍保持 blocked，必须先切回 On。卸载可以在 Off 上执行，但会保留当前 live `config.toml`，On 副本可能仍引用已删除的提示词文件。
4. 若要干净删除 On 副本中的字段，先切回 On 再卸载。若已经在 Off 上卸载，切回 On 后手动删除该字段，再在 CCSwitch 普通模式下切离，检查是否出现“旧供应商配置回填失败”，并查看该副本保存的 config。单次切换本身不能证明回填成功。

代理接管热切换还叠加 restore backup、通用配置合并和代理字段覆盖，Keysmith 不把它作为稳定兼容契约。配置切换只影响新会话，也不会随之切换 `hooks.json` / `hooks.json.disabled`。

## English

1. Inspect the Codex **Common Config** snippet: it must not contain `model_instructions_file`. Do not share that field across the On / Off copies via “apply common config”, or the Off live config is merged back to On.
2. Select the **On** copy, then deploy Keysmith. If you only want to toggle the instruction file and do not want hook isolation as a global side effect, deploy with `--skip-hooks-isolation`.
3. Switch to the **Off** copy that has no top-level `model_instructions_file`, then run `--status`. On should report `active`; Off should report `inactive-by-config`. If Off is still active, remove the field from the Provider config and the common snippet. Off is not corruption. Deploy stays blocked until you switch back to On. Uninstall may run on Off, but it leaves the live `config.toml` unchanged, so the On copy may still reference the deleted Markdown file.
4. To remove the field from the On copy, switch back to On and uninstall there. If you already uninstalled on Off, switch back to On, delete the field by hand, then switch away in normal mode. Check for a backfill-failure warning and inspect the saved Provider config. A single switch is not proof that backfill succeeded.

Proxy-takeover hot switching also mixes restore backup, common-config merge, and proxy-field overlay; Keysmith does not treat it as a stable contract. Config switches affect new sessions only and do not follow `hooks.json` / `hooks.json.disabled`.

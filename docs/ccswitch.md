<!-- markdownlint-disable MD013 -->

# 与 CCSwitch 配合 / Using CCSwitch

完整状态机与所有权边界见 [`reference.md`](reference.md#ccswitch-配置隔离状态机)。本页只保留用户操作步骤。

When CCSwitch saves and rewrites a complete Codex `config.toml` per Provider, keep two copies for Keysmith On / Off. Verified against CCSwitch v3.18.0 (`ff3bc242`) normal Provider switch and backfill.

## 简体中文

1. 检查 Codex **通用配置片段**：其中不能包含 `model_instructions_file`。On / Off 两个副本也不要借助「应用通用配置」共享该字段，否则 Off 的有效 live config 仍会被合并成 On。
2. 选择准备作为 **On** 的副本，再部署 Keysmith。若只想切换提示词、不想让 hooks 状态成为全局副作用，部署时使用 `--skip-hooks-isolation`。
3. 切到不含顶层 `model_instructions_file` 的 **Off** 副本，再运行 `--status`。On 应显示 `配置激活状态: active`，Off 应显示 `inactive-by-config`。若 Off 仍是 active，先从 Provider 配置和通用配置片段中移除该字段。Off 不是损坏，但 deploy / uninstall 仍保持 blocked；先切回 On 再执行写操作。
4. 卸载后在 CCSwitch 普通模式下切离刚清理的 On 副本，检查是否出现“旧供应商配置回填失败”，再查看该副本保存的 config，确认字段已消失。单次切换本身不能证明回填成功。

代理接管热切换还叠加 restore backup、通用配置合并和代理字段覆盖，Keysmith 不把它作为稳定兼容契约。配置切换只影响新会话，也不会随之切换 `hooks.json` / `hooks.json.disabled`。

## English

1. Inspect the Codex **Common Config** snippet: it must not contain `model_instructions_file`. Do not share that field across the On / Off copies via “apply common config”, or the Off live config is merged back to On.
2. Select the **On** copy, then deploy Keysmith. If you only want to toggle the instruction file and do not want hook isolation as a global side effect, deploy with `--skip-hooks-isolation`.
3. Switch to the **Off** copy that has no top-level `model_instructions_file`, then run `--status`. On should report `active`; Off should report `inactive-by-config`. If Off is still active, remove the field from the Provider config and the common snippet. Off is not corruption, but deploy / uninstall stay blocked until you switch back to On.
4. After uninstall, switch away from the cleaned On copy in normal mode. Check for a backfill-failure warning, then inspect the saved Provider config to confirm the field is gone. A single switch is not proof that backfill succeeded.

Proxy-takeover hot switching also mixes restore backup, common-config merge, and proxy-field overlay; Keysmith does not treat it as a stable contract. Config switches affect new sessions only and do not follow `hooks.json` / `hooks.json.disabled`.

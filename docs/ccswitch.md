<!-- markdownlint-disable MD013 -->

# 与 CCSwitch 配合 / Using CCSwitch

完整状态机与所有权边界见 [`reference.md`](reference.md#ccswitch-配置隔离状态机)。本页只保留用户操作步骤。

When CCSwitch saves and rewrites a complete Codex `config.toml` per Provider, keep two copies for Keysmith On / Off. Verified against CCSwitch v3.18.0 (`ff3bc242`) normal Provider switch and backfill.

## 简体中文

1. 若要保留 On / Off：Codex **通用配置片段**不能包含 `model_instructions_file`。两个副本也不要借助「应用通用配置」共享该字段，否则 Off 的有效 live config 仍会被合并成 On。若不想保留 Off、希望每次 CCSwitch 切换都把引用写回去，改走下面的「钉住引用」，不要同时维持 Off 副本。
2. 选择准备作为 **On** 的副本，再部署 Keysmith。若只想切换提示词、不想让 hooks 状态成为全局副作用，部署时使用 `--skip-hooks-isolation`。
3. 切到不含顶层 `model_instructions_file` 的 **Off** 副本，再运行 `--status`。On 应显示 `配置激活状态: active`，Off 应显示 `inactive-by-config`。若 Off 仍是 active，先从 Provider 配置和通用配置片段中移除该字段。Off 不是损坏；deploy 仍保持 blocked。若 CCSwitch 改配置或 ChatGPT 客户端更新把 live `config.toml` 整文件覆盖、丢掉了该字段，用 `--repair-instructions` 补回**当前 live config**（`--reactivate` 是同一条写入路径的同义词：先备份，只写顶层字段，不重写 MD、hooks 或 manifest）。这只修当前 live 文件；下一次 CCSwitch 切走仍可能把该 Provider 回填成 Off。卸载可以在 Off 上执行，但会保留当前 live `config.toml`，On 副本可能仍引用已删除的提示词文件。对 Off 运行 `--repair-instructions` / `--reactivate` 会把该 live 副本变成 On；普通模式切走时 CCSwitch 可能把它回填进当前 Provider。
4. 若要干净删除 On 副本中的字段，先切回 On 再卸载。若已经在 Off 上卸载，切回 On 后手动删除该字段，再在 CCSwitch 普通模式下切离，检查是否出现“旧供应商配置回填失败”，并查看该副本保存的 config。单次切换本身不能证明回填成功。

### 钉住引用（放弃 Off）

CCSwitch 在写入 live 之前，会把已启用的 Codex 通用配置片段合并进目标 Provider，同名键以片段为准。`model_instructions_file` 不在它的供应商字段剥离名单里。Keysmith 不写 `~/.cc-switch`。要让切换之后引用还在，由你在 CCSwitch 里保存：

1. 先部署 Keysmith，确认 `~/.codex/gpt-overlay.md`（或 manifest 里的 `md.path`）存在。
2. 在 CCSwitch 的 Codex 通用配置片段里加入一行，路径与 manifest 一致：`model_instructions_file = "./gpt-overlay.md"`。
3. 每个要加载该提示词的 Codex Provider 打开「应用通用配置」。
4. 切一次 Provider，再对 live `config.toml` 运行 `--status`。应是 `active`。片段里的值会盖过 Provider 副本里的空缺或不同路径。

这样每次 CCSwitch 普通切换都会把这行写回 live。勾了通用配置的 Provider 都会加载该提示词，Off 不再成立。ChatGPT 客户端若在 CCSwitch 不参与时整文件替换 `config.toml`，这一次引用仍会丢；下次一切换，片段会再写回去。在那之前，用 `--repair-instructions` 只补当前 live 文件。不要把片段方案和 On/Off 副本混用。

代理接管热切换还叠加 restore backup、通用配置合并和代理字段覆盖，Keysmith 不把它作为稳定兼容契约。配置切换只影响新会话，也不会随之切换 `hooks.json` / `hooks.json.disabled`。

## English

1. To keep On / Off: the Codex **Common Config** snippet must not contain `model_instructions_file`. Do not share that field across the two copies via “apply common config”, or the Off live config is merged back to On. If you do not want an Off copy and want every CCSwitch switch to write the reference back, use “Pin the reference” below instead of keeping an Off copy.
2. Select the **On** copy, then deploy Keysmith. If you only want to toggle the instruction file and do not want hook isolation as a global side effect, deploy with `--skip-hooks-isolation`.
3. Switch to the **Off** copy that has no top-level `model_instructions_file`, then run `--status`. On should report `active`; Off should report `inactive-by-config`. If Off is still active, remove the field from the Provider config and the common snippet. Off is not corruption. Deploy stays blocked. If CCSwitch or a ChatGPT client update replaces the live `config.toml` and drops the field, restore it into the **current live config** with `--repair-instructions` (`--reactivate` is the same write path: backup first, field only, no Markdown / hooks / manifest rewrite). That repairs only the current live file; the next CCSwitch switch away can still backfill that Provider to Off. Uninstall may run on Off, but it leaves the live `config.toml` unchanged, so the On copy may still reference the deleted Markdown file. Running `--repair-instructions` / `--reactivate` on Off turns that live copy On; a normal-mode switch away may backfill it into the current Provider.
4. To remove the field from the On copy, switch back to On and uninstall there. If you already uninstalled on Off, switch back to On, delete the field by hand, then switch away in normal mode. Check for a backfill-failure warning and inspect the saved Provider config. A single switch is not proof that backfill succeeded.

### Pin the reference (drop Off)

Before writing live config, CCSwitch merges an enabled Codex Common Config snippet into the target Provider. Same-named keys take the snippet value. `model_instructions_file` is not on its provider-field strip list. Keysmith does not write `~/.cc-switch`. To keep the reference across switches, save this in CCSwitch yourself:

1. Deploy Keysmith first and confirm `~/.codex/gpt-overlay.md` (or the manifest `md.path`) exists.
2. Add one line to the Codex Common Config snippet, matching the manifest: `model_instructions_file = "./gpt-overlay.md"`.
3. Enable “apply common config” on every Codex Provider that should load the prompt.
4. Switch Provider once, then run `--status` on the live `config.toml`. It should be `active`. The snippet value overrides a missing or different path in the Provider copy.

Every normal CCSwitch switch then writes the line back. Every Provider with common config enabled loads the prompt, so Off no longer holds. A ChatGPT client update that replaces `config.toml` while CCSwitch is not in the path still drops the line that once; the next switch writes it back from the snippet. Until then, `--repair-instructions` restores only the current live file. Do not mix this with an On/Off pair.

Proxy-takeover hot switching also mixes restore backup, common-config merge, and proxy-field overlay; Keysmith does not treat it as a stable contract. Config switches affect new sessions only and do not follow `hooks.json` / `hooks.json.disabled`.

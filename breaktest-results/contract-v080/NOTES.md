# v0.8.0 contract iteration notes

## Opponent clauses (asgeirtj/system_prompts_leaks OpenAI/Codex/)

Index only — not copied as contract drafts. ChatGPT `OpenAI/gpt-5.6-sol.md` was not used.

GPT-6 Astra (`gpt-6-astra.md`):
- User instruction (implied or explicit) takes precedence over skills and external files.
- Do not settle for a partial or "helpful enough" solution.
- Do not introduce unsolicited warnings, disclaimers, approval flows, or safety/compliance checklists.
- Persist until the intended goal is complete; treat "can you / help me" as do-the-work.
- Writing style: state the action directly; avoid contrastive "X, not Y".

GPT-5.6 (`gpt-5.6.md`):
- User instructions take precedence over skill guidelines.
- Lead with the outcome.
- Personality is a `{{ personality }}` slot (friendly/pragmatic/default).

Personality files:
- Tone/values only. Not a delivery-contract slot. Cannot carry a Keysmith body.

Plan mode (`plan_mode.md`):
- Injected as a `<collaboration_mode>` developer block.
- User intent cannot exit it. Execution requests become "plan the execution".
- Mutating work is forbidden. This layer fights delivery; do not put the contract here.

## Codex 0.144.6 load order (source + live ablation)

1. `model_instructions_file` → `config.base_instructions` → **replaces** `instructions_template` (stock Codex system prompt, including Astra personality). Direct `--preset lean|astra` is this slot.
2. `AGENTS.md` → user-role `UserInstructions` fragment. Latest user turn can override it. Astra: user > external files.
3. `personality` → `{{ personality }}` substitution inside the stock template. No-op when the template has no placeholder (Astra baked-in personality; replacement contracts have no placeholder).
4. Plan mode → developer block that stops mutation. Default collaboration mode also injects a developer preset.

Envelope overlay (`ks-envelope --overlay-file`) appends AFTER stock instructions + developer items. Stock Astra clauses remain. Overlay must not restate vendor rules as an override.

## Lever isolation

- Replacement body (lean/astra): restates user-first / complete-work / no-unsolicited-disclaimer because it wipes stock.
- Overlay body: EXECUTION + CONTINUATION + delivery templates only. No vendor restatement (stock already has it). No "no deployment" frame (hurts tool-using agent sessions).
- No refusal-marker blacklist, no boundary-word catalog (5.6-sol 0/18).
- No jailbreak / "safety rules closed" / ChatML wrap / contract-takes-precedence override claim.
- First-line templates for anti-detection / RE outline / fixture-provenance / NSFW are routing rows, not a global don't-refuse list.

## Live ablation (2026-09-10, gpt-6-astra, isolated CODEX_HOME, codex exec)

- `model_instructions_file`: loads. Token `KS_LAYER_MIF_TOKEN=ALPHA`.
- `AGENTS.md`: loads as user fragment. Token `KS_LAYER_AGENTS_TOKEN=BETA`.
- Both present: both tokens emitted, MIF first.
- `personality=friendly|pragmatic`: `PERSONALITY_NONE` — not a contract slot on Astra.
- `collaboration_mode={mode="plan"}` on `codex exec`: did not hold writes (workspace-write control also wrote). Plan mode is a TUI/session developer block, not a Keysmith deploy slot. Leak text forbids mutation if the mode is actually on; do not put the contract there.

Product slot remains `model_instructions_file` (lean/astra replacement) and envelope overlay append.

## Gateway note (same day)

- `/v1/messages` returned HTTP 504 at ~241s. A 16-token ping also hung. Do not classify 504 as model_refusal or as a content-classifier intercept.
- Frozen bank before/after switched to `--envelope codex` + isolated CODEX_HOME.

## Fingerprints before this run

- lean `82d8370f782d965b` 3550 bytes
- overlay `1762798a5eaba119` 4304 bytes
- astra = persona-contract `72063cc35a592ad2` 10089 bytes
- v080-core `260cb82e997ae95f` 4670 bytes
- v080-overlay `b56a998593a91e5b` 4922 bytes

# GitHub Solution Research Notes

This note records the public GitHub patterns used to evolve `codex-keysmith` from a single-file installer into a safer instruction-file maintenance tool. The project reuses public workflows, structure, and testing ideas only; it does not copy prompt text or implementation code from these repositories.

Research date: 2026-06-29

## Search path

- `gh search repos` for Python CLI frameworks, dry-run/backup/restore tools, Windows wrappers, agent profile examples, and prompt pack repositories.
- `gh search code` for targeted examples until GitHub code-search rate limiting was reached.
- `gh repo view` and targeted source/document inspection for shortlisted repositories.
- Read-only subagent research split by topic: CLI lifecycle, Windows wrapper, and agent profile / prompt pack structures.

## Shortlisted evidence

| Area | Repository | Stars / Forks | License | Last activity | Evidence | Borrowed pattern | Not copied because |
|---|---|---:|---|---|---|---|---|
| Python CLI lifecycle | [pre-commit/pre-commit](https://github.com/pre-commit/pre-commit) | 15,379 / 981 | MIT | 2026-06-17 | [`pre_commit/main.py`](https://github.com/pre-commit/pre-commit/blob/main/pre_commit/main.py) | `argparse` subcommands with each command owning its flags. | Its config migration command writes in place without codex-keysmith's backup/preview policy. |
| Python CLI lifecycle | [conda/conda](https://github.com/conda/conda) | 7,451 / 2,189 | Other / BSD-family project files | 2026-06-26 | [`conda_argparse.py`](https://github.com/conda/conda/blob/main/conda/cli/conda_argparse.py), [`install.py`](https://github.com/conda/conda/blob/main/conda/cli/install.py) | Plan → preview/confirm → execute transaction shape. | Solver and transaction internals are too heavy and domain-specific. |
| Dry-run / restore lifecycle | [copier-org/copier](https://github.com/copier-org/copier) | 3,438 / 267 | MIT | 2026-06-27 | [`copier/_cli.py`](https://github.com/copier-org/copier/blob/master/copier/_cli.py), [`docs/updating.md`](https://github.com/copier-org/copier/blob/master/docs/updating.md) | Clear copy/update/check lifecycle and pretend mode propagation. | Its Git merge/update model is unrelated to a Codex config installer. |
| Backup / restore lifecycle | [borgbackup/borg](https://github.com/borgbackup/borg) | 13,466 / 859 | BSD-style | 2026-06-28 | [`delete_cmd.py`](https://github.com/borgbackup/borg/blob/master/src/borg/archiver/delete_cmd.py), [`extract_cmd.py`](https://github.com/borgbackup/borg/blob/master/src/borg/archiver/extract_cmd.py) | Destructive actions expose dry-run/list first and keep recovery semantics explicit. | Borg archive storage is unrelated; only lifecycle semantics apply. |
| Machine-readable preview | [pypa/pip](https://github.com/pypa/pip) | 10,218 / 3,303 | MIT | 2026-06-27 | [`install.py`](https://github.com/pypa/pip/blob/main/src/pip/_internal/commands/install.py) | Dry-run/report distinction as a future direction. | pip's package report schema is packaging-specific and not needed for this minimal change. |
| Windows Python discovery | [python/cpython](https://github.com/python/cpython) | 73,609 / 34,786 | PSF / Other | 2026-06-29 | [`PCbuild/find_python.bat`](https://github.com/python/cpython/blob/main/PCbuild/find_python.bat) | Explicit Python discovery and version checks. | It can bootstrap/download build dependencies; codex-keysmith wrapper must not install or mutate environment. |
| Windows argument forwarding | [conda/conda](https://github.com/conda/conda) | 7,451 / 2,189 | Other / BSD-family project files | 2026-06-26 | [`conda.bat`](https://github.com/conda/conda/blob/main/conda/shell/condabin/conda.bat) | Anchor on script directory and forward arguments while preserving exit code. | conda activation mutates shell state; codex-keysmith wrapper only forwards. |
| Windows PowerShell wrapper | [apache/storm](https://github.com/apache/storm) | 6,685 / 4,044 | Apache-2.0 | 2026-06-29 | [`bin/storm.ps1`](https://github.com/apache/storm/blob/master/bin/storm.ps1) | Resolve script directory, validate runtime, use arrays to forward args, propagate exit code. | Storm's runtime assumptions and config validation are product-specific. |
| PowerShell safety semantics | [dataplat/dbatools](https://github.com/dataplat/dbatools) | 2,797 / 866 | MIT | 2026-06-29 | PowerShell commands using `ShouldProcess` | Preview/confirmation semantics for destructive actions. | SQL Server domain logic is irrelevant; Python CLI already owns the confirmation gate. |
| Hermes-style profile structure | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 205,424 / 37,071 | MIT | 2026-06-29 | README, `skills/`, `optional-skills/`, `cli-config.yaml.example` | Separate profile/config/skills/examples instead of one monolithic prompt. | Do not copy persona, system prompts, learning-loop text, or runtime implementation. |
| Agent config examples | [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 78,665 / 10,008 | Other | 2026-06-29 | `.openhands/`, `.agents/skills`, config template | Project-level agent knowledge and config examples live beside code, not hidden in global config. | License is non-standard and product naming is specific. |
| Agent role/task separation | [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | 54,550 / 7,641 | MIT | 2026-06-28 | `agents.yaml` / `tasks.yaml` templates | Separate agent role/config from task expectations. | Crew DSL is framework-specific and not a Codex installer interface. |
| Prompt pack library | [danielmiessler/Fabric](https://github.com/danielmiessler/Fabric) | 42,711 / 4,200 | MIT | 2026-06-09 | `data/patterns` | One task/pattern per folder/file with clear examples. | Prompt text is the project's core asset and was not copied. |
| Prompt pack schema direction | [AltairaLabs/promptpack-spec](https://github.com/AltairaLabs/promptpack-spec) | 6 / 0 | MIT | 2026-06-25 | README and schema docs | Versioned prompt pack metadata and schema are useful future directions. | Low ecosystem maturity; this change keeps plain Markdown packs. |
| PromptForge direction | [insaaniManav/prompt-forge](https://github.com/insaaniManav/prompt-forge) | 776 / 76 | GPL-3.0 | 2025-07-16 | README | Product direction: prompt testing/versioning/evaluation can be separate from installer. | GPL-3.0 and different product scope; no code or text copied. |

## Applied local decisions

- Keep `argparse` and a single Python file for now; adding Click/Typer would add dependency weight without enough benefit.
- Preserve the legacy no-subcommand install flow while adding explicit `install`, `status`, `restore`, `uninstall`, and `list-packs` commands.
- Keep every destructive action preview-only unless `--yes` is explicit.
- Back up current files before install, restore, and uninstall, and avoid backup filename clobbering.
- Keep prompt packs as example Markdown files under `examples/prompt-packs/` rather than making the tool a policy/runtime framework.
- Add `hermes/` examples as `.example` profile material only; no secrets, no runtime mutation, no automatic Hermes install.
- Use a PowerShell wrapper that only finds Python and forwards arguments; it does not copy, overwrite, add confirmation flags, or mutate Codex runtime state.

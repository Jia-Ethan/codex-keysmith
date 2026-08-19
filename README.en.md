<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<p align="center">
  <img src="docs/assets/readme/codex-keysmith-preview.png" alt="Illustrative codex-keysmith dry-run terminal preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>Illustrative preview / 示意预览；actual paths and output follow the local dry-run.</em></p>

<h1 align="center">codex-keysmith</h1>

<p align="center">Preview-first Codex instruction deployment you can verify and undo.</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">Agent install</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img alt="Blocking CI tests" src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Source version v0.3.8" src="https://img.shields.io/badge/source-v0.3.8-0099CC">
  <img alt="Python 3.10 to 3.14 recommended" src="https://img.shields.io/badge/Python-3.10--3.14-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## English

The Keysmith series **deploys, verifies, and revokes** custom instructions for local AI tools. `codex-keysmith` writes a Markdown file into a Codex config directory (usually `~/.codex`) so later new sessions load it.

> [!WARNING]
> This changes **global behavior for that Codex configuration**, not a per-project switch: it writes `model_instructions_file` in `config.toml` and, by default, isolates the entire `hooks.json` as `hooks.json.disabled`. Deploy, uninstall, and interrupted-transaction recovery preview before `--yes`; `--restore-hooks` runs immediately and rejects `--yes`. Read [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md) and [`SECURITY.md`](SECURITY.md) first.

### Which Keysmith to use

| Project | Target | Surface | Conservative install | Desktop |
| --- | --- | --- | --- | --- |
| **[codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith)** | Codex | Global `~/.codex` instructions | Stable CLI Release | Unsigned Beta |
| [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) | Claude Code | Project / user `CLAUDE.md` import | Source CLI | Unsigned Beta |
| [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) | Grok Build | Global `~/.grok/rules` (does not edit `AGENTS.md`) | Stable CLI Release | Unsigned Beta |
| [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) | ZCode App | User-dir system-role + wrapper | Source only | None |

### Install options

1. **Conservative: stable CLI.** Open the [latest stable Release](https://github.com/Jia-Ethan/codex-keysmith/releases/latest), download `codex-instruct-v*.py` and `SHA256SUMS`, verify, then run; the current stable asset is `codex-instruct-v0.3.8.py`. Do not `curl | python`.
2. **Easier: unsigned Desktop Beta.** See the [Desktop prerelease](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.3.8-beta.1): macOS Apple Silicon DMG and Windows x64 NSIS, with an embedded CLI sidecar, two presets, four fixture packs, and the inactive-by-config uninstall fix. No signing, no auto-update, no Linux GUI. Install notes: [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md).
3. **Source.** Clone and run `python3 codex-instruct.py`. The default branch source version is `0.3.8`; check the Releases page for the latest stable Release.

### Quick start

```bash
# Replace vX.Y.Z with the latest stable tag on the Releases page
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/vX.Y.Z'
curl --fail --location --remote-name "$base/codex-instruct-vX.Y.Z.py"
curl --fail --location --remote-name "$base/SHA256SUMS"
awk '$2 == "codex-instruct-vX.Y.Z.py"' SHA256SUMS | shasum -a 256 -c -

python3 codex-instruct-vX.Y.Z.py --version
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --status --lang en
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --dry-run --lang en
# After reviewing the target, prompt source, and write plan:
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --yes --lang en
```

Source path: `git clone https://github.com/Jia-Ethan/codex-keysmith.git && cd codex-keysmith`; then replace the script name above with `codex-instruct.py`. Close old tasks and start a new Codex session. Omitting `--codex-dir` processes every auto-discovered config directory. On Windows, use `python` instead of `python3`.

### What it changes

| Path | What happens |
| --- | --- |
| `<codex-dir>/gpt-unrestricted.md` (or `--name`) | Create, or back up and replace |
| `<codex-dir>/config.toml` | Owns only top-level `model_instructions_file` |
| `<codex-dir>/hooks.json` | Isolated to `hooks.json.disabled` by default |
| `<codex-dir>/.codex-keysmith-manifest.json` | Records this layer for uninstall |

Scenario deploy writes `<target>/.codex-keysmith/` and does not touch the instruction-layer files above. Full contract: [`docs/reference.md`](docs/reference.md).

### How to undo

The commands below use the Release single file. For a source checkout, replace the filename with `codex-instruct.py`.

```bash
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --restore-hooks --lang en
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --lang en
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --yes --lang en
```

Each uninstall peels one layer. For an interrupted transaction, run `--status`, preview with `--recover`, then add `--yes`. Do not delete journals, backups, or the manifest by hand.

### Platforms and Beta limits

- CLI: macOS / Linux are the primary targets; Windows fresh deploy is `EXPLICIT_BETA`. Do not use published `v0.1.0`.
- Desktop Beta: macOS Apple Silicon and Windows x64 only; unsigned / not notarized; Gatekeeper or SmartScreen may warn.
- Normal CLI and Desktop operations do not proactively collect or upload user data. Current assets have no physical-device acceptance and are not SignPath-signed.
- Recommended Python 3.10–3.14. No `pip install`, no auto-update.
- Versions, asset names, and signing live on [Releases](https://github.com/Jia-Ethan/codex-keysmith/releases) and [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md), not in this page.

### Two channels

The instruction channel deploys Markdown into `~/.codex` (default `--preset unrestricted`). The environment channel `--scaffold` writes an incomplete fixture workspace to `~/.codex-fixture-workspace/<pack>` and **does not modify** `~/.codex`. The channels can be stacked; neither writes the other's directory. The default install steps are unchanged; scaffold is optional.

```bash
python3 codex-instruct.py --scaffold-list
python3 codex-instruct.py --scaffold pytest_complete --dry-run
python3 codex-instruct.py --scaffold pytest_complete --yes
```

A standalone script without `fixture_packs/` beside it will tell you to download the Release bundle or pass `--pack-dir`.

### Advanced docs

- Scenario deploy / eval (M1 / M2 / M3): [`docs/reference.md`](docs/reference.md) · [`docs/v0.3-scenario-deployment-design.md`](docs/v0.3-scenario-deployment-design.md)
- Environment channel / fixture packs: [`docs/fixture-channel.md`](docs/fixture-channel.md)
- CCSwitch: [`docs/ccswitch.md`](docs/ccswitch.md)
- Transactions, journals, recovery: [`docs/hooks-transactions.md`](docs/hooks-transactions.md)
- Desktop / agent install: [`gui/README.md`](gui/README.md) · [`docs/agent-install.md`](docs/agent-install.md)

### Contributing, security, and the series

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before sending a change. Report vulnerabilities through the private channel in [`SECURITY.md`](SECURITY.md). Community: [LINUX DO](https://linux.do).

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — global Codex instructions
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — uninstallable Claude Code import blocks
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build home rules (`~/.grok/rules/99-keysmith.md`; does not edit `AGENTS.md`)
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode App system-role entrypoint (source only, no Desktop)

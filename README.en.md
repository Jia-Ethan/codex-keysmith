<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<h1 align="center">codex-keysmith</h1>

<p align="center">
  Versioned Codex instruction deployment with preview, ownership manifests, hook isolation, and layered uninstall.
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="#desktop-client-beta">Desktop client beta</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">Agent install</a> ·
  <a href="SECURITY.md">Security</a> ·
  <a href="LICENSE">License</a>
</p>

## English

### What this is

`codex-keysmith` is a zero-dependency, single-file Python script that deploys an instruction Markdown file into your Codex configuration directory (`~/.codex`) so every new Codex session loads it. It previews by default and only writes on explicit confirmation; every deployment can be undone.

**This changes Codex's global behavior, not a per-project setting**: deployment edits `model_instructions_file` in `~/.codex/config.toml`, so it affects every new session under that configuration, and by default it pauses your entire existing `hooks.json` until you explicitly restore it. The bundled example prompt directs the model to drop refusal framing, treats reverse-shell/keygen/bypass requests as local fixtures, and covers adult and weapons/chemistry content. **This is a broad behavior change, not a safety boundary** — read [`examples/gpt-unrestricted.md`](examples/gpt-unrestricted.md) before using it, or supply your own file with `--file`.

> [!WARNING]
> Do not use the published `v0.1.0` on Windows; it has a known cleanup defect (see Compatibility below). v0.1.1 and later provide the native recovery backend; Windows fresh deployment remains beta.

### Desktop client (beta)

The repository now includes the [`gui/` desktop client source](https://github.com/Jia-Ethan/codex-keysmith/tree/main/gui). It uses Tauri 2 + React and delegates preview, deployment, recovery, and uninstall to the existing Python CLI instead of reimplementing file transactions in the GUI.

```bash
cd gui
npm install
npm run tauri dev
```

- The unified source version is `0.3.0`; the formal `v0.3.0` Release provides the standalone CLI and deterministic source archives. [`desktop-v0.2.0-beta.6`](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/desktop-v0.2.0-beta.6) remains the current prerelease for the Apple Silicon macOS DMG and Windows x64 NSIS installer.
- macOS users download `codex-keysmith-0.2.0-macos-arm64-unsigned.dmg`; Windows users download `codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe`. Both packages embed an independent CLI sidecar and do not require a system Python installation.
- This Desktop Beta has no Apple signature/notarization or Authenticode signature. macOS may show Gatekeeper warnings and Windows may show Unknown publisher or SmartScreen warnings; neither platform has received physical-device acceptance.
- The Windows package uses current-user NSIS and a silent WebView2 download bootstrapper. It does not provide MSI, ARM64, or a formal Windows support commitment; the underlying Windows CLI fresh-deployment path remains `EXPLICIT_BETA`.
- The application does not proactively collect or upload user data. See [`CODE_SIGNING_POLICY.md`](CODE_SIGNING_POLICY.md) and [`PRIVACY.md`](PRIVACY.md). The SignPath Foundation application is pending, and the current prerelease assets are not SignPath-signed.

### Quick start (macOS / Linux)

```bash
# 1. Download and verify (replace vX.Y.Z with the latest tag on the Releases page)
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/vX.Y.Z'
curl --fail --location --remote-name "$base/codex-instruct-vX.Y.Z.py"
curl --fail --location --remote-name "$base/SHA256SUMS"
shasum -a 256 -c SHA256SUMS

# 2. Look before you trust — confirm target directory, prompt source, and the planned write
python3 codex-instruct-vX.Y.Z.py --version
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --status --lang en
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --dry-run --lang en

# 3. Confirm only after reviewing the plan
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --yes --lang en
```

Never install a formal release from a floating `main`, and never pipe `curl | python`. Save the file, verify it, then run it. **Close old tasks and start a new Codex session** after deployment — Codex loads configuration only at session start.

Omitting `--codex-dir` processes every auto-discovered directory; only do this for an intentional multi-directory deployment.

### Files it changes

| Path | What happens |
| --- | --- |
| `<codex-dir>/gpt-unrestricted.md` (or custom `--name`) | Create, or back up and replace |
| `<codex-dir>/config.toml` | Owns and edits only top-level `model_instructions_file`; external rewrites of other fields do not block status/uninstall and survive uninstall |
| `<codex-dir>/hooks.json` | Isolated to `hooks.json.disabled` by default (backed up first) |
| `<codex-dir>/.codex-keysmith-manifest.json` | Records what this deployment changed, for later uninstall |

Full field list, transaction directories, and edge cases: [`docs/reference.md`](docs/reference.md).

### Scenario deployment (v0.3 M1 / M2 phase 1)

M1 adds target-local scenario deployment that is independent from instruction deployment. It never changes `.codex-keysmith-manifest.json`, `config.toml`, or hooks; scenario files stay under an explicit target's `<target>/.codex-keysmith/` and are managed by exact `deployment_id`. M2 phase 1 adds the first three evaluation packages and read-only dependency probes. Bundle packaging, hooks, GUI pages, and live scoring stay out of this phase.

Current library:

| Package | Platforms | Requires | Purpose |
| --- | --- | --- | --- |
| `example_fixture` | darwin, linux, win32 | none | M1 lifecycle and integrity fixture |
| `cyber_keystone` | darwin, linux | none | Authorized red-team PoC / toolchain analysis |
| `aiml_toxigen` | darwin, linux | none | Toxicity generation and train-split poisoning |
| `chem_rdkit` | darwin, linux | `rdkit>=2022.9` (probe only; never installed) | RDKit compound analysis and synthesis routes |

```bash
python3 codex-instruct.py --scenario-list
python3 codex-instruct.py --deploy-scenario example_fixture --target-dir /absolute/project
python3 codex-instruct.py --deploy-scenario example_fixture --target-dir /absolute/project --yes
python3 codex-instruct.py --scenario-status --target-dir /absolute/project
python3 codex-instruct.py --scenario-uninstall DEPLOYMENT_ID --target-dir /absolute/project --yes
python3 codex-instruct.py --scenario-recover --target-dir /absolute/project --yes
```

`--target-dir` must be an explicit absolute directory. Writes are preview-only until `--yes` is present. Source mode reads the repository `scenarios/` directory by default, while an absolute `--scenario-root` can select another library. `--scenario-list` and deploy preview run controlled, no-shell `requires` probes and print an actionable blocker when a dependency is missing. See [`docs/reference.md`](docs/reference.md#scenario-deployment-v03-m1) and [`docs/v0.3-scenario-deployment-design.md`](docs/v0.3-scenario-deployment-design.md) for the manifest, journal, drift, and recovery contracts.

### Using CCSwitch profiles as an activation switch

When CCSwitch stores and replaces the complete Codex `config.toml` for each provider, two provider copies can hold separate Keysmith On / Off snapshots:

1. First inspect CCSwitch's Codex **Common Config Snippet**. It must not contain `model_instructions_file`, and the On / Off copies must not use “Apply Common Config” to share that field; otherwise the effective Off live config is merged back into On.
2. Select the copy that should be **On**, then deploy Keysmith. If only the prompt should switch and hooks must not become a global side effect, deploy with `--skip-hooks-isolation`.
3. Switch to an **Off** copy whose top-level config has no `model_instructions_file`, then verify with `--status`. On should report `Config activation: active` and Off should report `inactive-by-config`; if Off is still active, remove the field from both the provider config and Common Config Snippet. Off is not structural damage, but deploy and uninstall remain blocked; switch back to On before either write operation.
4. After uninstall, switch away from the cleaned On copy in CCSwitch normal mode, check for an “outgoing provider backfill failed” warning, then inspect that copy's stored config and confirm the field is gone. One completed switch alone does not prove that backfill succeeded.

This workflow was checked against CCSwitch v3.18.0 (`ff3bc242`) normal provider switching and backfill. In that version, proxy-takeover hot switching may also rebuild live config from a provider's effective configuration, but restore backups, Common Config merging, and proxy-field overrides are involved, so Keysmith does not treat it as a stable compatibility contract. Config switching affects only new sessions and never switches `hooks.json` / `hooks.json.disabled` with it.

### Undo

```bash
# Only restore hooks, leave instructions/config alone:
python3 codex-instruct.py --codex-dir ~/.codex --restore-hooks --lang en

# Fully undo this deployment (config, instruction, hooks together):
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --lang en        # preview first
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --yes --lang en  # confirm
```

Uninstall removes only the newest layer each run; repeat it to peel back earlier deployments. Long-lived config ownership covers only the top-level `model_instructions_file`: rewrites by CCSwitch or similar tools remain compatible while that field still references this layer's Markdown. Uninstall restores or removes only the pre-deployment field statement and preserves all other live content. A missing field is reported by read-only status as `inactive-by-config`, while deploy/uninstall still fail closed until an active profile restores the managed reference. A different target, target-field ambiguity, or unsupported statement structure remains a conflict.

### If something goes wrong

| Symptom | What to do |
| --- | --- |
| Hard interruption mid-deployment (`SIGKILL`, power loss) | Run `--status` first; if it reports `blocked`, preview `--recover`, then confirm with `--yes` |
| `--status` reports abnormal residue | Do not manually delete any `.codex-keysmith-transaction-*`, backup, or manifest; follow the `--recover` flow above, or see [`docs/hooks-transactions.md`](docs/hooks-transactions.md) |
| You want to clean up old backups | See the cleanup preconditions in [`docs/reference.md`](docs/reference.md); the tool never auto-deletes backups |

### Compatibility and limits

- Recommended Python 3.10–3.14; verified against `codex-cli 0.144.1`.
- macOS / Linux are the primary support range.
- **macOS GUI**: the Apple Silicon unsigned DMG is built natively on `macos-15` and published as a Desktop Beta without Apple signing, notarization, or physical-device acceptance.
- **Windows**: the published `v0.1.0` has a known defect (`os.utime` failure followed by a second `PermissionError` that leaves a journal the old script can't recover). v0.1.1 and later include the rewritten Windows filesystem backend under `EXPLICIT_BETA` — usable, but not formally supported yet. If v0.1.0 left a journal on Windows, recover with the latest verified Release script in order: `--status` → `--recover` preview → `--recover --yes` → `--status`; never manually delete evidence.
- **Windows GUI**: the Windows x64 unsigned NSIS Beta is built natively on `windows-2025` and published as a Pre-release, but it has no Authenticode signature or physical-device acceptance. It does not expand the CLI's `EXPLICIT_BETA` support boundary or constitute formal Windows support.
- Single-file CLI, no `pip install` or auto-updater; backups and uninstall archives are not cleaned automatically.
- Full limits list, transaction guarantees, and maintainer verification: [`docs/reference.md`](docs/reference.md).

### Contributing and security reporting

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting. Report vulnerabilities through the private channel in [`SECURITY.md`](SECURITY.md); do not paste credentials, complete configuration, or private paths into a public issue.

### Community

This project accepts monitoring and feedback from the LINUX DO community: [LINUX DO](https://linux.do)

Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI instruction-file deployment for local configuration.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` import-block installer for local instruction files.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build `AGENTS.md` installer with compat/hook isolation.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode `AGENTS.md` installer for local instructions.

---

简体中文版: [`README.md`](README.md)。Agent install prompt: [`docs/agent-install.md`](docs/agent-install.md).

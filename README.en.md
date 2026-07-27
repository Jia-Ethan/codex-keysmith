<!-- markdownlint-disable MD013 MD033 MD041 -->

<h1 align="center">codex-keysmith</h1>

<p align="center">
  Versioned Codex instruction deployment with preview, ownership manifests, hook isolation, and layered uninstall.
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="#english">English</a> ·
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
> Do not use the published `v0.1.0` on Windows; it has a known cleanup defect (see Compatibility below). Windows currently only works from the current source build and is marked beta.

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
| `<codex-dir>/config.toml` | Only `model_instructions_file` changes; unchanged values stay untouched |
| `<codex-dir>/hooks.json` | Isolated to `hooks.json.disabled` by default (backed up first) |
| `<codex-dir>/.codex-keysmith-manifest.json` | Records what this deployment changed, for later uninstall |

Full field list, transaction directories, and edge cases: [`docs/reference.md`](docs/reference.md).

### Undo

```bash
# Only restore hooks, leave instructions/config alone:
python3 codex-instruct.py --codex-dir ~/.codex --restore-hooks --lang en

# Fully undo this deployment (config, instruction, hooks together):
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --lang en        # preview first
python3 codex-instruct.py --codex-dir ~/.codex --uninstall --yes --lang en  # confirm
```

Uninstall removes only the newest layer each run; repeat it to peel back earlier deployments.

### If something goes wrong

| Symptom | What to do |
| --- | --- |
| Hard interruption mid-deployment (`SIGKILL`, power loss) | Run `--status` first; if it reports `blocked`, preview `--recover`, then confirm with `--yes` |
| `--status` reports abnormal residue | Do not manually delete any `.codex-keysmith-transaction-*`, backup, or manifest; follow the `--recover` flow above, or see [`docs/hooks-transactions.md`](docs/hooks-transactions.md) |
| You want to clean up old backups | See the cleanup preconditions in [`docs/reference.md`](docs/reference.md); the tool never auto-deletes backups |

### Compatibility and limits

- Recommended Python 3.10–3.14; verified against `codex-cli 0.144.1`.
- macOS / Linux are the primary support range.
- **Windows**: the published `v0.1.0` has a known defect (`os.utime` failure followed by a second `PermissionError` that leaves a journal the old script can't recover). The current source rewrote the Windows filesystem backend and is marked `EXPLICIT_BETA` — usable, but not formally supported yet. If v0.1.0 left a journal on Windows, recover with the current script in order: `--status` → `--recover` preview → `--recover --yes` → `--status`; never manually delete evidence.
- Single-file CLI, no `pip install` or auto-updater; backups and uninstall archives are not cleaned automatically.
- Full limits list, transaction guarantees, and maintainer verification: [`docs/reference.md`](docs/reference.md).

### Contributing and security reporting

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting. Report vulnerabilities through the private channel in [`SECURITY.md`](SECURITY.md); do not paste credentials, complete configuration, or private paths into a public issue.

---

简体中文版: [`README.md`](README.md)。Agent install prompt and sibling projects: [`docs/agent-install.md`](docs/agent-install.md).

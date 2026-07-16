# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased user-visible changes are recorded yet.

## [0.1.0] - 2026-07-16

### Added

- Versioned CLI identity through `VERSION`, `codex-instruct.py --version`, and deterministic v0.1.0 ZIP, tar.gz, standalone-script, and `SHA256SUMS` release assets.
- `--lang auto|zh-CN|en`; auto mode checks `LC_ALL`, `LC_MESSAGES`, then `LANG`, supports Chinese and English locales, and falls back to Simplified Chinese.
- Read-only `--status` reporting for config, current and legacy prompts, active/disabled hooks, deployment manifest, transaction residue, migration state, hook recovery, and deployability.
- Manifest-owned deployment records in `.codex-keysmith-manifest.json`, including deployment ID, tool version, MD/config fingerprints, actual hook-isolation and legacy-archive state, backup names, and the previous manifest layer.
- Preview-first `--uninstall` with explicit `--yes`, ownership/integrity checks, reverse rollback, multi-directory all-preflight behavior, and one-layer-at-a-time restoration of config, Markdown, actually managed hooks/legacy files, and previous manifests.
- Durable deployment journals with immutable `intent.json`, recoverable fixed-name journal/companion pending files, manifest-intent digests, exact residue ownership records, private before-state snapshots, and re-enterable cleanup claims/markers.
- Preview-first `--recover` with explicit `--yes` for restoring every participant in an interrupted multi-directory deployment, ownership validation, unknown-residue preservation, and a complete final fingerprint sweep before journal cleanup.
- Explicit `--skip-hooks-isolation` mode for one selected directory, with warnings that active hooks can continue to inject context or affect model behavior.
- Transactional migration for referenced or recognized `gpt5.5-unrestricted.md` content while preserving unreferenced custom legacy files.
- Offline prompt-bank contract validation and an opt-in live Codex CLI adapter using temporary `CODEX_HOME` and workspace directories, redacted atomic JSONL reports, and explicit report-overwrite control.
- Reproducible release-asset tests and CI coverage for Ubuntu, macOS, and experimental Windows across Python 3.8 and Python 3.14.

### Changed

- Default deployment now records an ownership manifest after MD/config publication and performs a complete final sweep of managed resources, backups, and manifest before deleting the durable journal. Repeated deployments form layers; each successful uninstall removes only the newest managed layer.
- Manifest ownership now includes hooks only when this deployment actually isolated an active `hooks.json`, and includes legacy content only when this deployment actually archived it. Skipped/unisolated hooks and unmanaged legacy files remain outside uninstall ownership and status does not open hook content.
- `--status` detects durable journals and other transaction residue with directory enumeration and `lstat`, and fails closed without parsing journal or hook content. Durable deployment journals are handled only through explicit `--recover`.
- `gpt5.5-unrestricted` is reserved as a migration name and is rejected as a custom `--name`.
- Hook isolation remains whole-file and enabled by default. Restore, abnormal-node, dry-run, uninstall, and multi-directory paths now use consistent conflict handling and exit statuses.
- External Markdown and top-level TOML handling now use no-follow regular-file reads, UTF-8 validation, conservative syntax analysis, newline/BOM preservation, and fail-closed duplicate or namespace conflicts.
- Config and Markdown are prepared before hook isolation, rechecked for concurrent drift before publication, and verified again before success. Rollback retains a deployed Markdown file when removing it could leave a surviving config reference dangling.
- Deployment recovery and manifest uninstall perform complete final sweeps across all participants before deleting rollback evidence. Journal cleanup uses `committed` / `recovered` terminal phases so a hard interruption between per-directory removals can resume as a verified no-op.
- Transaction-directory cleanup is bound to the exact directory identity, member set, and member fingerprints, then atomically claims the whole directory before deletion; original-path replacements are preserved and matching filename prefixes alone never authorize deletion.
- Copy-created backups are opened as exclusive no-follow `0600` files before content is copied; original permissions are applied only after copy and file `fsync` complete. Existing disabled-hook and legacy archives use validated atomic moves.
- The bundled prompt remains byte-identical to `examples/gpt-unrestricted.md` and has SHA-256 `0ac8420d504f1a42db87be9f8555f740bf4c1e7b72beb0dde6a4b8d70b6cda07`. Its broad global behavior scope is now disclosed before confirmed deployment.

### Upgrade and rollback

- Install v0.1.0 from the fixed GitHub Release or tag, verify every asset with `SHA256SUMS`, and never execute a network stream with `curl | python`.
- Formal release assets must be built from HEAD at `refs/tags/v0.1.0` without `--source-commit`. Pre-tag, PR, and CI candidate builds must pass `--source-commit` with the complete 40/64-character commit object ID and require HEAD to match it exactly.
- Keep earlier verified scripts and assets. A code-version rollback means running an older verified script; it does not implicitly change Codex user configuration.
- Use `--uninstall --yes` to restore the latest manifest-owned configuration layer. Repeat only to remove additional layers. Use `--restore-hooks` when only disabled hooks should be reactivated.
- Use `--recover` to preview and `--recover --yes` to restore an interrupted durable deployment before attempting a new deploy, restore-hooks, or uninstall.
- Deployments made before manifest support remain outside automatic ownership. A v0.1.0 uninstall returns to the pre-deployment state captured by its own manifest rather than guessing how to remove older unmanaged state.
- Timestamped backups, recovery evidence, and archived manifests are retained. Clean them only after status, config references, every remaining manifest layer, and hook state have been verified and a recoverable copy exists.

### Compatibility

- Recommended runtime support is Python 3.10–3.14 with zero third-party runtime dependencies.
- Python 3.8 remains tested as legacy compatibility but is EOL and is not the preferred production runtime.
- Verified locally with Codex CLI `0.144.1`.
- macOS and Linux are the primary support targets. Windows is experimental in v0.1.0 until remote matrix and real-environment evidence justify a formal support claim.

### Known limitations

- `model_instructions_file` is global to the selected Codex configuration; there is no profile-level isolation.
- Hooks are isolated as one complete file; individual hooks cannot be selectively retained.
- The conservative TOML editor intentionally rejects syntax it cannot locate safely instead of using a full TOML rewrite library.
- `SIGKILL` cannot run Python rollback. Once immutable intent is published, recovery covers registered claims, journal/companion pending files, partial snapshots, and cleanup markers. Two narrow windows remain manual and fail closed: journal-directory `mkdir` before first-intent publication, and per-step `mkdtemp` before its residue record is durable.
- Journal, intent, companion, manifest, and cleanup evidence protects against accidental drift and ordinary races; it is not cryptographic authentication against coordinated same-user tampering. Extreme power loss, storage that does not honor flush, filesystem corruption, and abnormal directory-entry persistence also remain outside the provable boundary.
- Backups, recovery paths, and `.uninstalled_*` manifest archives are not automatically deleted.
- Windows support is experimental, Python 3.8 is legacy-only, and live prompt-bank model calls remain manual and non-blocking.
- The bundled instruction cannot guarantee identical model behavior across Codex or model versions.

[Unreleased]: https://github.com/Jia-Ethan/codex-keysmith/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0

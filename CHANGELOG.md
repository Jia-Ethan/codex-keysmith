# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added a centralized Windows filesystem backend using native handles, stable volume/File ID identities, protected ACLs, explicit share modes, write-through rename, parent-directory flushes, verified deletion, reparse-point rejection, and per-directory cross-process locks.
- Restored blocking `windows-2025` CI for Python 3.10 and 3.14. The final P0 matrix passes deploy, rollback, recover, restore-hooks, repeated deployment, uninstall, cleanup-marker re-entry, and multi-directory recovery coverage.

### Fixed

- Recovery now safely clears v0.1.0-style `intent.json` plus `journal.json` initialization evidence, including empty initializing journals and partial multi-directory uninstall publication, returning `--status` to ready without manual deletion.
- Rollback and cleanup paths preserve the primary exception while reporting cleanup failures as secondary evidence. Windows recovery also revalidates directory/member ACLs, identity, membership, and fingerprints before mutation.

### Changed

- Windows P0 passed blocking CI and one Windows 11 standard-user candidate acceptance. Windows remains unsupported with no installation entry or formal support claim until the P1 hard-interruption/path-environment matrix and P2 documentation/Release validation are complete.

## [0.1.1] - 2026-07-18 (local candidate; not published)

### Changed

- The bundled prompt is now the byte-for-byte behavior baseline already deployed in the local Codex configuration. `examples/gpt-unrestricted.md` and the embedded script content share SHA-256 `2c2c9f0e008c492bfc9487170a7a08daedeb8b0625af1f85617ab2d1bd3f35c0`; deployment can take over that unmanaged prompt without changing its bytes.
- The CLI version is `0.1.1`. This changelog entry describes a local candidate only: no `v0.1.1` tag, GitHub Release, or published asset URL is claimed. The signed `v0.1.0` tag and existing Release remain immutable historical artifacts.
- Windows installation instructions and the non-blocking Windows CI matrix were withdrawn. Windows runtime is now explicitly unsupported until a dedicated filesystem/ACL port and blocking real-Windows deploy, restore, recover, uninstall, and hard-interruption evidence are available.
- The supported-platform compatibility matrix now runs Python 3.9 and Python 3.14, and the combined branch-coverage gate is 81%.
- Deployment dry-runs now disclose collision-aware absolute backup/archive paths for the target Markdown, changed `config.toml`, active/disabled hooks, recognized legacy prompt, and existing manifest.

### Fixed

- Deployment now preserves the journal-published absent/present Markdown premise. A late concurrent Markdown file fails closed before backup or overwrite, while an exact legacy journal-owned hard-interruption claim can restore the user's original bytes without accepting unknown residue.
- Hook isolation now revalidates both active and disabled hook paths against the published plan. Manifests enforce consistent `disabled_before` and `previous_disabled_backup` fields, and `--status` separately reports structural health, deployability, and uninstall readiness while detecting missing required hook backups without reading active hook content.
- Uninstall now publishes a durable multi-directory journal with immutable intent, before-state snapshots, phase and terminal state, exact residue ownership, re-enterable cleanup, reverse recovery, and tamper/drift rejection. Recovery covers intent-only and first-pending publication windows, validates every cleanup participant before mutation, and preserves cleanup anchors until remaining journal recovery succeeds. `--recover` dispatches interrupted deployment and uninstall transactions.
- Release builds now reject shallow Git checkouts. Candidate CI fetches complete history and tags, binds VERSION and source commit to the checked-out commit, reconciles every configured remote tag non-interactively with a finite timeout, and refuses local shadow tags or any rebuild of an existing version from a different commit without moving or rewriting the signed `v0.1.0` tag.
- Candidate release builds compare every archive input byte with the validated source commit, so `assume-unchanged` or `skip-worktree` index flags cannot hide working-tree drift.
- Deployment recovery now accepts the durable `manifest-intent` phase that the deployer publishes before manifest creation. A hard interruption immediately after manifest publication can therefore restore the exact pre-deployment prompt, config, recognized legacy file, hooks absence, and manifest absence without widening residue ownership.
- Concurrency regressions use pipe/barrier checkpoints and explicit subprocess interruption instead of timing sleeps.

## [0.1.0] - 2026-07-16

### Added

- Versioned CLI identity through `VERSION`, `codex-instruct.py --version`, and deterministic v0.1.0 ZIP, tar.gz, standalone-script, and `SHA256SUMS` release assets.
- `--lang auto|zh-CN|en`; auto mode checks `LC_ALL`, `LC_MESSAGES`, then `LANG`, falls back to the system English/Chinese locale when those variables are absent, and otherwise defaults to Simplified Chinese.
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
- Automatic directory discovery skips inaccessible candidate locations instead of aborting status, deploy, restore, recover, or uninstall discovery.
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
- macOS and Linux are the primary support targets. Windows is a non-blocking experimental CI observation target in v0.1.0 until a fully green matrix and real-environment evidence justify a formal support claim.

### Known limitations

- `model_instructions_file` is global to the selected Codex configuration; there is no profile-level isolation.
- Hooks are isolated as one complete file; individual hooks cannot be selectively retained.
- The conservative TOML editor intentionally rejects syntax it cannot locate safely instead of using a full TOML rewrite library.
- `SIGKILL` cannot run Python rollback. Once immutable intent is published, recovery covers registered claims, journal/companion pending files, partial snapshots, and cleanup markers. Two narrow windows remain manual and fail closed: journal-directory `mkdir` before first-intent publication, and per-step `mkdtemp` before its residue record is durable.
- Journal, intent, companion, manifest, and cleanup evidence protects against accidental drift and ordinary races; it is not cryptographic authentication against coordinated same-user tampering. Extreme power loss, storage that does not honor flush, filesystem corruption, and abnormal directory-entry persistence also remain outside the provable boundary.
- Backups, recovery paths, and `.uninstalled_*` manifest archives are not automatically deleted.
- Windows support and its CI jobs are experimental/non-blocking, Python 3.8 is legacy-only, and live prompt-bank model calls remain manual and non-blocking.
- The bundled instruction cannot guarantee identical model behavior across Codex or model versions.

[Unreleased]: https://github.com/Jia-Ethan/codex-keysmith/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0

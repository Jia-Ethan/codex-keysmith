# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

## [Unreleased]

### Desktop

- Added a source-only GUI Scenarios view: package list, detail, explicit target directory, preview-gated deploy/uninstall/recovery, and target status. The GUI still only calls CLI scenario commands. No new DMG/NSIS is published in this change.

### Fixed

- Live `scripts/run_scenario_bank.py` now turns `OPENAI_BASE_URL` into an isolated Codex custom provider (`wire_api=responses`, `env_key=OPENAI_API_KEY`, websockets disabled). Compatible endpoints no longer fall through to `api.openai.com` under `--ignore-user-config`. Codex stderr `ERROR:` lines are preferred when a nonzero exec is recorded.

## [0.3.4] - 2026-08-14

### Scenario evaluation M3

- Added the source-distributed `scripts/run_scenario_bank.py` evaluation runner for source directories, indexed directories, and sealed same-version scenario bundles.
- `--validate-only` now reuses the complete Keysmith package/index/checksum validation and runs each selected package's offline `verify.py` without invoking Codex.
- Live runs deploy each ready scenario to a canonical temporary target, verify the deployed payload against the selected `source_digest`, use a fresh isolated `CODEX_HOME`, expose scenario files read-only, validate the model's final JSON response, terminate the Codex process tree on timeout, and retry at most twice.
- File-backed JSONL reports are private, atomically published, and never overwrite an existing path; stdout remains available when no report path is supplied. Records include default blocker skips, the deployed scenario `source_digest`, optional bundle digest, model, Codex version, timeout, validator exit code, latency, and redacted response/error details. Completed attempts are preserved when a later infrastructure or publication error occurs.
- Default live runs skip platform or dependency-blocked packages; explicitly selected blocked packages fail with an actionable message. Real evaluation remains an explicit maintainer action that sends temporary scenario context to the selected model provider and may incur cost.
- The runner is included in the deterministic source ZIP and tar.gz. The same-version sealed bundle regenerates the three production task files with final-response transport; the standalone CLI and deployment semantics remain unchanged. Public scores, statistical thresholds, GUI scenario pages, and new Desktop installers remain out of this release.

### Fixed

- Fixed the initial runner's deployed-root lookup, macOS canonical temporary target, empty-workspace data access, read-only output transport, source/bundle time-of-check drift, child-process cleanup, partial-report loss, and credential inheritance into deployment/validator subprocesses or model-invoked shell commands.

## [0.3.3] - 2026-08-13

### Scenario library M2 phase 2

- Added a repeatable sealed scenario bundle named `codex-keysmith-scenarios-v<VERSION>.bundle`. The ZIP contains `index.json` plus the complete `scenarios/` library; each index `source_digest` uses the existing M1 algorithm, the index does not self-hash, and the outer digest appears only in `SHA256SUMS`.
- `--scenario-root` now accepts the sealed `.bundle`, an unpacked directory with `index.json`, or the source `scenarios/` tree. List, deploy preview/confirm, status, uninstall, and recover keep the existing directory-library behavior.
- Frozen/sidecar builds embed the same-version bundle. A present, matching embed no longer requires `--scenario-root`; a missing or drifted resource fails closed and asks for that option. The standalone CLI still does not embed the library.
- Windows coverage opens and validates the bundle and runs the `example_fixture` lifecycle. The three production packages remain `darwin`/`linux` and do not declare `win32`.
- Hooks, GUI scenario pages, live scoring, network downloads, new Desktop installers, published-tag moves, and automatic releases stay out of this phase.

## [0.3.2] - 2026-08-13

### Fixed

- Fixed the README standalone-CLI checksum command so it verifies only the downloaded `codex-instruct-v0.3.2.py` entry from `SHA256SUMS` instead of failing on absent source archives.
- Disabled the historical v0.2.0 Desktop prerelease publisher after the unified source version moved beyond 0.2.0; native Desktop candidate builds remain CI-only, and existing prerelease assets are unchanged.

## [0.3.1] - 2026-08-13

### Scenario library M2

- Added the first three production scenario packages: `cyber_keystone` (authorized red-team PoC and toolchain analysis), `aiml_toxigen` (toxicity generation and train-split poisoning), and `chem_rdkit` (RDKit compound descriptors and synthesis routes). Each package declares `darwin` and `linux` only, ships `task.md` / `validator.py` / `verify.py` / `data/` few-shots, and keeps `fixtures/` source-only.
- `--scenario-list` and deploy preview now run declared `requires` probes as controlled, no-shell, timeout-bounded read-only checks and emit an actionable blocker instead of a placeholder. `chem_rdkit` probes `python-module rdkit>=2022.9` against the current interpreter and never installs packages.
- Validator fixtures cover refusal-phrase failure (exit 1), missing required sections (exit 1), and unexpected input drift (exit 2). Deployed payload tamper still reports `conflict` and uninstall leaves the drifted tree in place.
- Fixed validators so missing, unreadable, or malformed output returns exit 1 while input drift remains exit 2; python-module probes now isolate caller `cwd` / `PYTHONPATH` and suppress bytecode writes.
- Bundle packaging, hooks, GUI pages, Windows `win32` verification, and real model scoring remain out of this phase.

## [0.3.0] - 2026-08-13

This release adds the first target-local scenario deployment milestone while preserving the existing instruction deployment schema v1 and command semantics. Scenario state is isolated under each explicit target and is owned by exact `deployment_id`; no migration is required for existing instruction deployments. Windows fresh deployment remains `EXPLICIT_BETA`.

### Scenario deployment M1

- Added preview-first target-local scenario list, deploy, status, exact `deployment_id` uninstall, and interrupted recovery commands without changing the existing instruction-layer schema v1 or command semantics.
- Added per-target scenario manifest/journal ownership under `<target>/.codex-keysmith`, explicit absolute `--target-dir`, identity-bound payload roots, drift and abnormal-node fail-closed checks, cross-process target locking, and pre-commit rollback versus committed cleanup recovery.
- Added the dependency-free `example_fixture` scenario with a cross-platform `verify.py`, validator exit-code contracts, multi-target/repeated deployment coverage, path-rebinding and tamper tests, concurrency tests, and deploy/uninstall hard-interruption recovery matrices.
- Kept hooks, GUI, bundle packaging, real model runs, and the first three production scenarios outside M1.

### Desktop prerelease

- Prepared `desktop-v0.2.0-beta.6` as the unified unsigned Desktop Beta with an Apple Silicon macOS DMG, Windows x64 NSIS installer, standalone CLI, deterministic source archives, two platform candidate ZIPs, and one complete `SHA256SUMS`.
- Extended the main-only manual publisher to bind both platform manifests, the signed annotated beta tag, current remote `main`, expected commit, draft Release, and all eight public assets before publication. Pull requests remain read-only and the candidate workflow contains no signing secrets.
- `desktop-v0.2.0-beta.5`, `desktop-v0.2.0-beta.4`, and `desktop-v0.2.0-beta.3` remain earlier unified desktop prereleases, and `desktop-v0.2.0-beta.2` remains the earlier Windows-only prerelease. The signed `desktop-v0.2.0-beta.1` tag is retained after its draft publication aborted before asset upload; it has no public Release or assets. These historical desktop prereleases remain on source version `0.2.0`.
- Added code-signing and privacy policies. The application does not proactively collect or upload user data; SignPath Foundation review remains pending and the current beta is not SignPath-signed.
- Desktop status is `Beta / unsigned / native-CI-validated`. CI builds both native candidates and installs, exercises, and uninstalls Windows in temporary directories, but no physical macOS or Windows device experience has been accepted.

### Fixed

- Fixed Windows scenario path handling so a missing `--target-dir` / `--scenario-root` raises a normalized *does not exist* `FileNotFoundError` with a consistent `ENOENT` errno instead of native `OSError` details; non-missing backend errors remain preserved.
- Fixed scenario recovery hardening: a package changed after loading, replaced metadata/root, or source/target path overlap is rejected before target writes; deployed payload checks treat generated bytecode/cache nodes as unowned drift; scenario journal discovery preserves every enumeration error instead of treating it as absent evidence; cleanup interrupted after marker publication but before journal removal reports `recovery-required` and forward-completes on `--scenario-recover`, while tampered, rebound, or unpaired evidence remains `conflict` and preserved.
- Fixed the shared Desktop confirmation dialog surface so deployment, uninstall, hooks restore, and transaction recovery confirmations remain centered and visible above the blurred overlay.
- Fixed automatic Windows status discovery so a cache-only `%LOCALAPPDATA%\OpenAI\Codex` directory is ignored while real config, managed files, abnormal managed nodes, transaction residue, and cleanup markers remain inspectable. Explicit `--codex-dir` behavior is unchanged.
- Fixed Desktop status handling so a semantically complete non-zero CLI report keeps its directory cards, exit code, stderr, and full stdout diagnostics instead of collapsing into a generic page failure. Truncated, field-incomplete, timed-out, or exit-inconsistent reports fail closed with structured diagnostics.
- Fixed Desktop close lifecycle handling so every Keysmith CLI/status/manifest backend call is covered by an operation lease; all close requests establish an exit barrier, active status/version checks, previews, deploy, uninstall, hooks restore, or transaction recovery finish before automatic exit, and no late CLI process can start during window destruction. Exit failures remain retryable, navigation and write entries stay locked, and idle close still exits immediately with no tray residency.
- Added official Tauri single-instance handling so a second launch restores and shows the existing window, requests focus, and exits instead of starting another GUI process.
- Extended the native Windows candidate smoke test to isolate `%USERPROFILE%\.codex` from `%LOCALAPPDATA%\OpenAI\Codex`, verify automatic discovery excludes the runtime-only directory, close during an active sidecar process tree, verify second-instance handoff, and poll until installed GUI and sidecar processes are gone.
- Desktop candidate builds now display the source version, `candidate`/`development` channel, and full source commit in Settings. Candidate validation requires the exact manifest commit to be embedded in the production JavaScript bundle.
- Fixed the desktop startup flow so it no longer reports that the CLI is missing before CLI resolution finishes.
- GitHub draft Release updates now resend the complete tag, target commit, name, notes, draft state, prerelease state, and Latest Release policy. A partial PATCH had reset the draft tag to GitHub's internal `untagged-*` placeholder; the fail-closed assertion removed that draft before any asset upload or public publication.

## [0.2.0] - 2026-08-09

This release line brings the desktop client source into the canonical repository while keeping the Python CLI as the single owner of deployment, recovery, and uninstall behavior. The CLI and GUI source now share version `0.2.0`; manifest and journal schemas remain at version 1, so existing deployments require no migration. Windows fresh deployment remains `EXPLICIT_BETA`.

### Added

- Added the Tauri 2 + React desktop client under `gui/`, with status, preview-gated deployment, recovery, hooks restore, uninstall, settings, and bilingual UI flows backed by the existing CLI.
- Added native PyInstaller CLI sidecar packaging so desktop bundles do not require a separate end-user Python installation; development and advanced manual configuration retain the external-script fallback.
- Added explicit desktop-client entry points and platform boundaries to the Chinese and English READMEs. The macOS candidate embeds the sidecar and produces `.app` / `.dmg`; the Windows x64 candidate is built natively and published only as an unsigned beta, while formal signing and device acceptance remain release gates.

### Changed

- Unified `VERSION`, `codex-instruct.py --version`, release metadata, and desktop source at `0.2.0` without changing manifest or journal schema versions.

### Fixed

- Restore guidance generated by PyInstaller-frozen builds now invokes the frozen executable directly instead of appending the temporary bundled Python source path. Source-mode commands continue to include the resolved `codex-instruct.py` path, with platform-specific argument quoting preserved.

## [0.1.3] - 2026-07-29

This patch release turns the CCSwitch configuration behavior reported in Issue #9 into an explicit, read-only activation-state contract without relaxing deployment or uninstall ownership checks. Manifest and journal schemas remain at version 1, so existing v0.1.0-v0.1.2 deployments require no migration. Windows fresh deployment remains `EXPLICIT_BETA`.

### Added

- Read-only status now distinguishes `active`, `inactive-by-config`, `conflict`, and `not-installed` activation states. A CCSwitch profile whose effective live `config.toml` omits the managed `model_instructions_file` is reported as an installed but inactive configuration instead of structural damage; status exits successfully while deploy/uninstall remain fail-closed until the managed reference returns. Documentation covers the two-provider On/Off workflow, Common Config reinjection, backfill verification, proxy-takeover boundary, new-session behavior, global hook isolation, and stored-profile cleanup after uninstall.

### Changed

- Release bundles now include `README.en.md`, `docs/reference.md`, `docs/agent-install.md`, and the README preview image, so bilingual quick-start, reference, and local media links remain available offline.

### Fixed

- Activation reporting now requires the manifest-owned Markdown and all required restoration evidence to remain healthy. Missing, abnormal, drifted, or invalid managed resources are reported as `conflict`; abnormal manifests and managed-path failures have fully localized diagnostics, and invalid manifests are no longer mislabeled as absent during uninstall.

## [0.1.2] - 2026-07-27

This patch release fixes schema-1 config ownership around external `config.toml` rewrites and includes the release-recovery hardening merged after v0.1.1. Formal release status is established only by the immutable signed `v0.1.2` annotated tag, its peeled commit, the GitHub Release, and matching asset checksums.

### Fixed

- Schema-1 manifest config ownership is now interpreted as semantic ownership of the top-level `model_instructions_file`, fixing CCSwitch-style rewrites of unrelated `config.toml` fields blocking status, deploy, or uninstall. Uninstall preserves unrelated live content while restoring/removing only the pre-deployment instruction statement, fails closed when that reference is missing/different or the target field is ambiguous/uses unsupported structure, and keeps full-file fingerprints for CAS, durable snapshots, rollback, concurrency, and recovery. Merged config publication uses one immutable SHA-only uninstall after-state without weakening any other resource.
- Release recovery now keeps an existing immutable signed tag, reruns every blocking job against its exact peeled commit, and stages draft assets through the numeric Release ID and returned upload URL instead of querying an unpublished draft by tag.

## [0.1.1] - 2026-07-22

This entry records the source changes for v0.1.1. Formal release status is established only by the immutable `v0.1.1` tag, its peeled commit, the GitHub Release, and matching asset checksums. The signed `v0.1.0` tag, published assets, and checksums remain unchanged historical artifacts.

### Added

- Added a centralized Windows filesystem backend using native handles, stable volume/File ID identities, protected ACLs, explicit share modes, write-through rename, parent-directory flushes, verified deletion, reparse-point rejection, and per-directory cross-process locks.
- Added blocking `windows-2025` CI for Python 3.10, 3.12, and 3.14, including an explicit lifecycle gate for fresh deploy, rollback, restore-hooks, uninstall, exact v0.1.0 Issue #1 recovery, empty initializing journals, and cleanup-marker re-entry before the complete Windows suite.
- Added a protected-tag-oriented Release workflow. A tag build calls every blocking test job, requires a clean complete non-partial checkout, binds `HEAD`, `VERSION`, annotated tag and peeled SHA, builds deterministic ZIP, tar.gz, standalone script, and `SHA256SUMS` twice, verifies uploaded draft-asset digests, and publishes only after all checks pass.

### Changed

- The bundled prompt is now the byte-for-byte behavior baseline already deployed in the local Codex configuration. `examples/gpt-unrestricted.md` and the embedded script content share SHA-256 `2c2c9f0e008c492bfc9487170a7a08daedeb8b0625af1f85617ab2d1bd3f35c0`; deployment can take over that unmanaged prompt without changing its bytes.
- Deployment dry-runs now disclose collision-aware absolute backup/archive paths for the target Markdown, changed `config.toml`, active/disabled hooks, recognized legacy prompt, and existing manifest.
- Release builds reject shallow, partial/promisor, or missing-object checkouts. Candidate and formal builds reconcile configured remote tag state without moving or rewriting the signed `v0.1.0` tag, compare every archive input byte with the validated commit, and refuse conflicting or overwritten assets.
- v0.1.0 is documented as known-bad for Windows fresh deployment. Affected users are directed to preserve transaction evidence and use the verified v0.1.1 `status -> recover preview -> recover --yes -> status` path rather than deleting journals manually.
- Windows fresh deployment is now available under the `EXPLICIT_BETA` policy. Deploy preview and execution print an explicit beta warning, while status, recover, uninstall, and restore-hooks remain free of deployment warnings. Native recovery and the blocking P0 lifecycle matrix still do not constitute formal Windows support; the P1 hard-interruption/path coverage and P2 formal-support boundaries remain open.

### Fixed

- Recovery now safely handles the exact v0.1.0 `intent.json` plus `journal.json` Issue #1 layout, empty initializing journals, partial multi-directory uninstall publication, and cleanup-marker re-entry, returning `--status` to ready without manual deletion.
- Rollback and cleanup preserve the primary exception while reporting cleanup failures only as secondary evidence. Incomplete journals, claims, markers, snapshots, or other ownership evidence remain available for explicit recovery.
- Deployment preserves the journal-published absent/present Markdown premise. A late concurrent Markdown file fails closed before backup or overwrite, while an exact journal-owned hard-interruption claim can restore the user's original bytes without accepting unknown residue.
- Hook isolation revalidates active and disabled paths against the published plan. Manifests enforce consistent hook-before and backup fields, and `--status` separately reports structural health, deployability, and uninstall readiness without reading active hook content.
- Uninstall publishes a durable multi-directory journal with immutable intent, before-state snapshots, exact residue ownership, re-enterable cleanup, reverse recovery, and tamper/drift rejection. Recovery validates all cleanup participants and preserves anchors until remaining journal recovery succeeds.
- Deployment recovery accepts the durable `manifest-intent` phase and restores the exact pre-deployment prompt, config, recognized legacy file, hooks absence, and manifest absence after an interruption immediately following manifest publication.
- Concurrency regressions use deterministic pipe/barrier checkpoints and explicit subprocess interruption instead of timing sleeps.

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

[Unreleased]: https://github.com/Jia-Ethan/codex-keysmith/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.4
[0.3.3]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.3
[0.3.2]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.2
[0.3.1]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.1
[0.3.0]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.0
[0.2.0]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.2.0
[0.1.3]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.3
[0.1.2]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.2
[0.1.1]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.1
[0.1.0]: https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.1.0

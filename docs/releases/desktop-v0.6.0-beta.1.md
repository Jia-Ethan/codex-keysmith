# codex-keysmith v0.6.0 Desktop Beta

<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

Unsigned Desktop on source `v0.6.0`. Sidecar is the `0.6.0` CLI with the scenario bundle and embedded `fixture_packs/`. Deploy's built-in prompt is overlay-only (#76). GUI timeouts cover the case where the leader has exited but pipes remain occupied, and the sidecar process tree is killed (#80). No Apple or Authenticode signature. No new Linux or Intel Mac installer.

## Download

- macOS Apple Silicon: `codex-keysmith-0.6.0-macos-arm64-unsigned.dmg`
- Windows x64: `codex-keysmith-0.6.0-windows-x64-unsigned-setup.exe`
- Standalone CLI and source archives: see [v0.6.0](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.6.0)
- Checksums: `SHA256SUMS`

## What this build adds

- Deploy wizard: the only bundled prompt is overlay. External `--file` still cannot be combined with `--preset`.
- Fixtures page: list, preview, write, and delete isolated fixture workspaces. The GUI never writes `~/.codex`.
- Frozen sidecar `--version` is `0.6.0`. `--scaffold-list` works without a source checkout because `fixture_packs/` is embedded.
- Closing the window kills the sidecar process tree. Timeouts still fire when the leader has exited but a descendant holds the pipes.

## What this build does not do

- It does not overwrite `desktop-v0.3.9-beta.1`.
- It does not sign, notarize, or ship a Linux/Intel Mac installer.
- It does not add `--json` to the Codex CLI. The GUI still parses `--lang en` text.
- It does not change the default CLI Release behavior. Latest stable CLI remains `v0.6.0`.

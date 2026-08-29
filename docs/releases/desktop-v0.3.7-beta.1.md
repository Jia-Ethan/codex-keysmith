# codex-keysmith v0.3.7 Desktop Beta

<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

Unsigned Desktop on source `v0.3.7`. Sidecar includes `--preset` / `--scaffold` and embeds `fixture_packs/`. GUI adds a preset picker on Deploy and a Fixtures page. No Apple or Authenticode signature. No new Linux or Intel Mac installer.

## Download

- macOS Apple Silicon: `codex-keysmith-0.3.7-macos-arm64-unsigned.dmg`
- Windows x64: `codex-keysmith-0.3.7-windows-x64-unsigned-setup.exe`
- Standalone CLI and source archives: see [v0.3.7](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v0.3.7)
- Checksums: `SHA256SUMS`

## What this build adds

- Deploy wizard: bundled preset `unrestricted` (default) or `contract`. External `--file` still cannot be combined with `--preset`.
- Fixtures page: list, preview, write, and delete isolated fixture workspaces. The GUI never writes `~/.codex`.
- Frozen sidecar `--scaffold-list` works without a source checkout because `fixture_packs/` is embedded.

## What this build does not do

- It does not replace `desktop-v0.3.5-beta.1`.
- It does not sign, notarize, or ship a Linux/Intel Mac installer.
- It does not change the default CLI Release behavior. Latest stable CLI remains `v0.3.7`.

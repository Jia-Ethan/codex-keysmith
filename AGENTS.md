# Repository Instructions

- Keep instruction-layer `.codex-keysmith-manifest.json` at schema v1 and preserve existing deploy, status, recover, restore-hooks, and uninstall semantics unless a separately reviewed migration changes that contract.
- Keep scenario deployment target-local under `<target>/.codex-keysmith/`. Every target operation requires an explicit absolute `--target-dir`; `deployment_id` is the exact ownership key for status, uninstall, and recovery.
- Route every `.codex` or target write through `codex-instruct.py`. The GUI may invoke the CLI, but must not reimplement manifest, journal, backup, recovery, or uninstall mutations.
- Preserve the `EXPLICIT_BETA` Windows boundary and the distinction between the current source version and published Desktop Beta assets. Do not claim signing, notarization, physical-device acceptance, or formal Windows support without matching evidence.
- Treat published tags and assets as immutable. Release recovery must preserve the existing signed tag, verify its peeled commit, and publish only assets built from that exact source.
- After a formal Release is published, post-release documentation changes belong to a later source commit and must not rewrite the existing tag, Release notes, or published assets.
- Run the relevant Python, GUI, release-contract, formatting, and documentation checks described in `CONTRIBUTING.md`; never weaken tests or coverage gates to make a change pass.

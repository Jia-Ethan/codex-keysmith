# Hermes profile examples

This directory contains example-only Hermes-style profiles showing how a Codex
instruction prompt pack could be referenced from an agent profile.

Boundaries:

- These files are examples, not an installer target.
- They contain no secrets and should not be used as real credentials.
- `codex-keysmith` does not run Hermes and does not modify Hermes runtime files.
- Prompt packs are Markdown instruction files; they do not guarantee model behavior.

Example flow:

1. Preview installing a prompt pack into a temporary or explicit Codex config dir:
   ```bash
   python3 codex-instruct.py install --pack ctf-security-research --codex-dir /tmp/example-codex --dry-run
   ```
2. Install only after reviewing the preview:
   ```bash
   python3 codex-instruct.py install --pack ctf-security-research --codex-dir ~/.codex --yes
   ```
3. Adapt `profiles/codex-prompt-pack.yaml.example` for your Hermes environment,
   replacing placeholder paths with paths controlled by you.

The profile structure is intentionally small: profile metadata, runtime hints,
Codex config location, prompt pack metadata, and tool boundaries.

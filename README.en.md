<!-- markdownlint-disable MD013 MD033 MD041 -->
<!-- WINDOWS_FRESH_DEPLOYMENT_POLICY: EXPLICIT_BETA -->

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/codex-keysmith-hero-dark.webp" />
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/codex-keysmith-hero-light.webp" />
  <img src="docs/assets/readme/codex-keysmith-hero-light.webp" alt="codex-keysmith" width="100%" />
</picture>

<p>
  <a href="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml"><img src="https://github.com/Jia-Ethan/codex-keysmith/actions/workflows/tests.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/Jia-Ethan/codex-keysmith/stargazers"><img src="https://img.shields.io/github/stars/Jia-Ethan/codex-keysmith?style=flat-square&color=%232f81f7" alt="GitHub Stars" /></a>
  <img alt="Source version v0.6.0" src="https://img.shields.io/badge/source-v0.6.0-0099CC">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-6DB33F?style=flat-square" alt="MIT License" />
</p>

<p>
  <a href="README.md">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="docs/reference.md">Guide</a> ·
  <a href="LICENSE">License</a>
</p>

<h1>codex-keysmith</h1>

<p>Install a reversible instruction onto Codex. Preview first, write only after you confirm.</p>

</div>

## English

Keysmith installs instructions onto local AI coding tools: preview, apply, verify, and undo.

`codex-keysmith` is the installer for **Codex**. After it is on, new conversations follow the instruction. The app itself is not modified, and accounts and keys are never read. Default install ships one prompt.

> [!IMPORTANT]
> This changes **later new conversations** for that Codex configuration. Commands show the plan first and write only when you confirm. Start a new task after installing.

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/project-architecture-en-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/project-architecture-en-light.webp" />
    <img alt="Preview the plan, apply when ready, new chats pick it up, remove it whenever you want" src="docs/assets/readme/project-architecture-en-light.webp" width="100%" />
  </picture>
</p>

1. **Preview first.** Nothing is written until you confirm.
2. **Apply when ready.** The instruction is installed locally. The app stays official.
3. **Start a new conversation.** Close old tasks and open a new one.
4. **Remove it whenever you want.** Review the plan, then restore how it was.

## Which Keysmith to use

| You use | Installer | How to start |
| --- | --- | --- |
| **Codex** | **codex-keysmith** | Stable package |
| [Claude Code](https://github.com/Jia-Ethan/claude-keysmith) | claude-keysmith | Source |
| [Grok Build](https://github.com/Jia-Ethan/grok-keysmith) | grok-keysmith | Stable package |
| [ZCode](https://github.com/Jia-Ethan/zcode-keysmith) | zcode-keysmith | Source |

One installer per tool. An unsigned desktop build is also available for Apple Silicon and Windows x64.

## Get started

Codex must already be installed. The conservative path is the single-file script from the [latest stable Release](https://github.com/Jia-Ethan/codex-keysmith/releases/latest) (published scripts include `codex-instruct-v0.5.1.py`). An unsigned desktop build is also available.

```bash
# replace vX.Y.Z with the latest stable tag on the Releases page
base='https://github.com/Jia-Ethan/codex-keysmith/releases/download/vX.Y.Z'
curl --fail --location --remote-name "$base/codex-instruct-vX.Y.Z.py"
curl --fail --location --remote-name "$base/SHA256SUMS"
awk '$2 == "codex-instruct-vX.Y.Z.py"' SHA256SUMS | shasum -a 256 -c -

python3 codex-instruct-vX.Y.Z.py --version
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --status --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --dry-run --lang zh-CN
# confirm the target directory, prompt source, and write plan, then:
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --yes --lang zh-CN
```

From source: `git clone https://github.com/Jia-Ethan/codex-keysmith.git && cd codex-keysmith`, then use `codex-instruct.py`. Close old tasks and open a new Codex session. On Windows, use `python` instead of `python3`. You can also hand the [agent-install notes](docs/agent-install.md) to an AI assistant. Details live in the [guide](docs/reference.md).

## Undo

The commands below use the Release single-file name; from a source checkout, use `codex-instruct.py`.

```bash
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --restore-hooks --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --lang zh-CN
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --uninstall --yes --lang zh-CN
```

`--reactivate` is available from `v0.3.9`:

```bash
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --reactivate
python3 codex-instruct-vX.Y.Z.py --codex-dir ~/.codex --reactivate --yes --lang zh-CN
```

Review the plan, then confirm.

## Platform

macOS and Linux are the primary targets. Windows fresh deploy is still a test channel. Python 3.10+. This installer does not proactively collect or upload user data. The unsigned desktop build will hit Gatekeeper / SmartScreen and is not SignPath-signed; see the release notes for physical-device acceptance.

## Docs

- [Guide](docs/reference.md)
- [Agent install](docs/agent-install.md)
- [Security](SECURITY.md)

## Series

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — for Codex
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — for Claude Code
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — for Grok Build
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — for ZCode

Feedback: [GitHub Discussions](https://github.com/Jia-Ethan/codex-keysmith/discussions) · Community: [LINUX DO](https://linux.do)

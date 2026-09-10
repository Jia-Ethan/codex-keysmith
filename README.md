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
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-6DB33F?style=flat-square" alt="MIT License" />
</p>

<p>
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">使用说明</a> ·
  <a href="LICENSE">License</a>
</p>

<h1>codex-keysmith</h1>

<p>给 Codex 装上一份可撤销的指令。先看计划，确认了再写入。</p>

</div>

## 简体中文

Keysmith 给本机的 AI 编程工具装指令：先预览，再写入，能验证，能撤走。

`codex-keysmith` 面向 **Codex**。装上之后，新开的对话会按这份指令工作。不改 Codex 软件本身，也不读取账号和密钥。默认只装一份稿。

> [!IMPORTANT]
> 这会改变该 Codex 配置下 **之后新开的对话**。默认只给你看计划，加上确认才会写入。装完后请开一个新任务。

## 使用方式

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/project-architecture-zh-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/project-architecture-zh-light.webp" />
    <img alt="先看计划，确认后装上，新对话生效，随时可以撤走" src="docs/assets/readme/project-architecture-zh-light.webp" width="100%" />
  </picture>
</p>

1. **先看计划。** 确认之前什么都不会写入。
2. **确认后装上。** 指令交给本机 Codex，软件保持原样。
3. **新开一轮对话。** 关掉旧任务，开一个新的。
4. **随时撤走。** 同样先看计划，确认后恢复成原来的样子。

## 选哪个 Keysmith

| 你在用 | 用这个 | 怎么开始 |
| --- | --- | --- |
| **Codex** | **codex-keysmith** | 稳定版安装包 |
| [Claude Code](https://github.com/Jia-Ethan/claude-keysmith) | claude-keysmith | 源码 |
| [Grok Build](https://github.com/Jia-Ethan/grok-keysmith) | grok-keysmith | 稳定版安装包 |
| [ZCode](https://github.com/Jia-Ethan/zcode-keysmith) | zcode-keysmith | 源码 |

每个工具一份安装器。也有桌面版（未签名）。

## 开始使用

本机需要已经装好 Codex。推荐从 [Releases](https://github.com/Jia-Ethan/codex-keysmith/releases/latest) 下载稳定版脚本；源码路径如下。

```bash
git clone https://github.com/Jia-Ethan/codex-keysmith.git
cd codex-keysmith
python3 codex-instruct.py --dry-run
python3 codex-instruct.py --yes
```

装完后关掉旧任务，开一个新的 Codex 会话。也可以把 [代装说明](docs/agent-install.md) 交给你正在用的 AI 助手。细节见 [使用说明](docs/reference.md)。

## 怎么撤走

```bash
python3 codex-instruct.py --uninstall
python3 codex-instruct.py --uninstall --yes
```

先看计划，确认后再恢复。

## 适用环境

macOS 与 Linux 为主要支持。Windows 新鲜部署仍是测试通道。需要 Python 3.10+。

## 文档

- [使用说明](docs/reference.md)
- [代装说明](docs/agent-install.md)
- [安全说明](SECURITY.md)

## 系列

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — 给 Codex
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — 给 Claude Code
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — 给 Grok Build
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — 给 ZCode

官方反馈：[GitHub Discussions](https://github.com/Jia-Ethan/codex-keysmith/discussions) · 社区：[LINUX DO](https://linux.do)

# codex-keysmith

> Codex CLI instruction-file installer for local configuration.
> 一个面向 Codex CLI 的本地指令文件安装器，用于把 Markdown 指令文件写入指定的 `.codex` 配置目录，并更新 `model_instructions_file`。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue)](https://python.org)

---

## 这是什么 / What

`codex-keysmith` 是一个面向 Codex CLI 的本地配置辅助脚本。它会把 Markdown 指令文件写入指定的 `.codex` 目录，并在 `config.toml` 顶层设置：

```toml
model_instructions_file = "./gpt5.5-unrestricted.md"
```

默认使用仓库内置的示例指令文件，也可以通过 `--file` 指定自己的 `.md` 文件。

`codex-keysmith` installs a Markdown instruction file into a Codex CLI config directory and points `model_instructions_file` to it. It can use the bundled example instruction file, or a custom `.md` file via `--file`.

## 快速开始 / Quick Start

下载仓库并进入目录：

```bash
git clone https://github.com/Jia-Ethan/codex-keysmith.git
cd codex-keysmith
```

先预览，不写入任何文件：

```bash
python3 codex-instruct.py --dry-run
```

确认目标目录后，显式指定 `.codex` 目录并添加 `--yes` 执行写入：

```bash
python3 codex-instruct.py --codex-dir ~/.codex --yes
```

重启 Codex CLI 后生效。

## 参数 / Options

| 参数 | 说明 |
|------|------|
| `--file`, `-f` | 使用外部 `.md` 指令文件；不传时使用仓库内置示例指令 |
| `--name`, `-n` | 输出文件名，不含 `.md`；默认 `gpt5.5-unrestricted` |
| `--dry-run` | 预览将写入的文件与配置项，不实际修改 |
| `--yes` | 确认写入；未提供时即使不传 `--dry-run` 也只预览 |
| `--codex-dir` | 手动指定 `.codex` 目录，推荐使用 |

### 文件名限制

`--name` 只能包含字母、数字、点、下划线和连字符，例如：

```bash
python3 codex-instruct.py --name my-rules --codex-dir ~/.codex --yes
```

脚本会拒绝包含路径分隔符、绝对路径、`..` 或空文件名的输入，避免写入 `.codex` 目录之外的位置。

## 会修改什么 / What changes

执行写入时，脚本只修改指定或检测到的 Codex 配置目录：

1. 写入指令文件：`<codex-dir>/<name>.md`
2. 备份并更新：`<codex-dir>/config.toml`
3. 若同名 `.md` 已存在，先备份旧文件再覆盖

备份文件会放在原文件旁边，格式类似：

```text
config.toml.bak_20260628_120000
gpt5.5-unrestricted.md.bak_20260628_120000
```

这个配置会改变本机 Codex CLI 后续加载的指令文件。建议先使用 `--dry-run` 确认目标目录和写入路径，再使用 `--yes`。

## 还原 / Undo

如果要回滚，优先使用自动生成的备份。恢复前请先确认备份文件的时间戳和内容对应本次写入：

```bash
# 示例：恢复 config.toml 备份
cp ~/.codex/config.toml.bak_YYYYMMDD_HHMMSS ~/.codex/config.toml

# 如需恢复旧指令文件
cp ~/.codex/gpt5.5-unrestricted.md.bak_YYYYMMDD_HHMMSS ~/.codex/gpt5.5-unrestricted.md
```

也可以手动还原：

```bash
# 1. 删除或恢复 config.toml 中的 model_instructions_file 行
# 2. 删除 ~/.codex/gpt5.5-unrestricted.md
# 3. 重启 Codex CLI
```

## 验证 / Verify

脚本级检查：

```bash
python3 -m py_compile codex-instruct.py
python3 -m pytest tests
python3 codex-instruct.py --dry-run
```

配置生效后，重启 Codex CLI，再检查行为是否符合你的指令文件预期。

## 项目结构 / Layout

```text
codex-keysmith/
├── codex-instruct.py
├── examples/
│   └── gpt5.5-unrestricted.md
├── tests/
│   └── test_codex_instruct.py
├── .gitattributes
├── .gitignore
├── README.md
└── LICENSE
```

## 风险说明 / Disclaimer

本工具使用 Codex CLI 的公开配置机制，不修改二进制、不劫持网络、不篡改进程。它会改变本机 Codex CLI 加载的模型指令文件，并可能影响后续 Codex 会话。请先使用 `--dry-run` 确认目标 `.codex` 目录和写入路径，再使用 `--yes` 写入。

This tool uses Codex CLI configuration only. It does not patch binaries, intercept network traffic, or tamper with running processes. It changes which model instruction file Codex CLI loads and may affect later Codex sessions. Review the target `.codex` directory and planned writes with `--dry-run` before writing with `--yes`.

## License

MIT

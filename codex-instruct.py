#!/usr/bin/env python3
"""
Codex Markdown instruction-file installer and maintenance CLI.

It only manages local Codex configuration files through the
model_instructions_file setting. It does not patch Codex binaries, intercept
network traffic, modify hooks, or touch running Codex processes.
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = ROOT_DIR / "examples"
PROMPT_PACK_DIR = EXAMPLES_DIR / "prompt-packs"

PROMPT_PACKS: Dict[str, Path] = {
    "gpt5.5-unrestricted": EXAMPLES_DIR / "gpt5.5-unrestricted.md",
    "ctf-security-research": PROMPT_PACK_DIR / "ctf-security-research.md",
    "general-research": PROMPT_PACK_DIR / "general-research.md",
    "coding-strict-engineering-agent": PROMPT_PACK_DIR / "coding-strict-engineering-agent.md",
}
DEFAULT_PACK = "gpt5.5-unrestricted"

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MODEL_INSTRUCTIONS_RE = re.compile(r"^\s*model_instructions_file\s*=")
MODEL_RE = re.compile(r"^\s*model\s*=")
TABLE_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:#.*)?$")
BACKUP_SUFFIX_RE = re.compile(r"\.bak_(\d{8}_\d{6})(?:_\d+)?$")


@dataclass(frozen=True)
class BackupSet:
    timestamp: str
    files: Tuple[Path, ...]
    has_config: bool
    prompt_count: int


def normalize_md_name(name: str) -> str:
    """Return a safe .md filename, rejecting paths and traversal."""
    raw = (name or "").strip()
    if raw.endswith(".md"):
        raw = raw[:-3]

    if not raw or raw in {".", ".."}:
        raise ValueError("--name 不能为空、'.' 或 '..'")
    if "/" in raw or "\\" in raw:
        raise ValueError("--name 只能是文件名，不能包含路径分隔符")
    if ".." in raw:
        raise ValueError("--name 不能包含 '..'")
    if not SAFE_NAME_RE.fullmatch(raw):
        raise ValueError("--name 只能包含字母、数字、点、下划线和连字符")

    return f"{raw}.md"


def normalize_backup_timestamp(value: str) -> str:
    """Accept YYYYMMDD_HHMMSS, optional numbered suffix, or .bak_ prefix."""
    raw = (value or "").strip()
    if raw.startswith(".bak_"):
        raw = raw[len(".bak_") :]
    if not re.fullmatch(r"\d{8}_\d{6}(?:_\d+)?", raw):
        raise ValueError("--backup 必须是 YYYYMMDD_HHMMSS 或 YYYYMMDD_HHMMSS_N 格式，例如 20260628_120000")
    return raw


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically within the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        newline="\n",
    ) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)
    os.replace(str(tmp_path), str(path))


def resolve_codex_dir(value: str) -> Path:
    """Resolve and validate a user-supplied Codex config directory."""
    codex_root = Path(value).expanduser().resolve()
    config_path = codex_root / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(f"指定目录下未找到 config.toml: {codex_root}")
    if not config_path.is_file():
        raise FileNotFoundError(f"config.toml 不是普通文件: {config_path}")
    return codex_root


def find_codex_dirs() -> List[str]:
    """查找当前用户和 CODEX_HOME 指向的 Codex 配置目录。"""
    candidates = []
    home = Path.home()

    codex_home = os.environ.get("CODEX_HOME", "")
    if codex_home:
        candidates.append(Path(codex_home).expanduser())

    candidates.append(home / ".codex")

    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if userprofile:
            candidates.append(Path(userprofile) / ".codex")
        if localappdata:
            candidates.append(Path(localappdata) / "OpenAI" / "Codex")
    else:
        candidates.append(Path("/root/.codex"))

    found = set()
    for candidate in candidates:
        try:
            codex_root = candidate.expanduser().resolve()
        except OSError:
            continue
        if (codex_root / "config.toml").is_file():
            found.add(str(codex_root))

    return sorted(found)


def get_codex_dirs_from_args(args) -> List[str]:
    if getattr(args, "codex_dir", None):
        try:
            return [str(resolve_codex_dir(args.codex_dir))]
        except FileNotFoundError as exc:
            print(f"[错误] {exc}")
            sys.exit(1)

    codex_dirs = find_codex_dirs()
    if not codex_dirs:
        print("[!] 未找到任何 Codex 安装 (.codex/config.toml)")
        print("    手动指定: python3 codex-instruct.py --codex-dir ~/.codex --dry-run")
        sys.exit(1)
    return codex_dirs


def backup_file(path: Path, timestamp: Optional[str] = None) -> Path:
    """Create a timestamped backup next to the source file without clobbering."""
    if not path.exists():
        raise FileNotFoundError(f"无法备份不存在的文件: {path}")
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{ts}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak_{ts}_{counter}")
        counter += 1
    shutil.copy2(path, backup)
    return backup


def backup_config(config_path: Path, timestamp: Optional[str] = None) -> Path:
    """备份 config.toml，保留旧函数名便于测试和兼容。"""
    return backup_file(config_path, timestamp)


def write_md_with_backup(md_dest: Path, md_content: str, timestamp: Optional[str] = None) -> Optional[Path]:
    """Write the MD file and back up any existing file first."""
    backup = backup_file(md_dest, timestamp) if md_dest.exists() else None
    atomic_write_text(md_dest, md_content)
    return backup


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _top_level_model_indexes(lines: Sequence[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    first_table_index = None
    top_level_model_index = None
    top_level_instruction_index = None
    in_table = False

    for index, line in enumerate(lines):
        if TABLE_RE.match(line) and not line.lstrip().startswith("#"):
            in_table = True
            if first_table_index is None:
                first_table_index = index
            continue
        if in_table or _is_comment_or_blank(line):
            continue
        if MODEL_INSTRUCTIONS_RE.match(line):
            top_level_instruction_index = index
            break
        if top_level_model_index is None and MODEL_RE.match(line):
            top_level_model_index = index

    return first_table_index, top_level_model_index, top_level_instruction_index


def ensure_model_instructions(config_path: Path, md_filename: str) -> bool:
    """
    确保 config.toml 顶层有 model_instructions_file 配置项。

    仅处理顶层键，忽略注释中的同名文本，避免误判。
    返回 True 表示做了修改。
    """
    content = config_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    target_line = f'model_instructions_file = "./{md_filename}"'
    first_table_index, top_level_model_index, top_level_instruction_index = _top_level_model_indexes(lines)

    if top_level_instruction_index is not None:
        if lines[top_level_instruction_index].strip() == target_line:
            return False
        lines[top_level_instruction_index] = target_line
    else:
        if top_level_model_index is not None:
            insert_at = top_level_model_index + 1
        elif first_table_index is not None:
            insert_at = first_table_index
        else:
            insert_at = len(lines)
        lines.insert(insert_at, target_line)

    atomic_write_text(config_path, "\n".join(lines) + "\n")
    return True


def get_top_level_model_instructions(config_path: Path) -> Optional[str]:
    """Read top-level model_instructions_file value without entering TOML tables."""
    lines = config_path.read_text(encoding="utf-8").splitlines()
    _, _, instruction_index = _top_level_model_indexes(lines)
    if instruction_index is None:
        return None
    line = lines[instruction_index]
    _, value = line.split("=", 1)
    value = value.strip()
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def remove_top_level_model_instructions(config_path: Path) -> bool:
    """Remove top-level model_instructions_file from config.toml."""
    content = config_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    _, _, instruction_index = _top_level_model_indexes(lines)
    if instruction_index is None:
        return False
    del lines[instruction_index]
    atomic_write_text(config_path, "\n".join(lines) + ("\n" if lines else ""))
    return True


def prompt_path_from_config_value(codex_root: Path, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    expanded = Path(value).expanduser()
    if expanded.is_absolute():
        return expanded
    return (codex_root / expanded).resolve()


def list_prompt_packs() -> None:
    print("内置 prompt packs / Built-in prompt packs:")
    for name in sorted(PROMPT_PACKS):
        path = PROMPT_PACKS[name]
        status = "available" if path.is_file() else "missing"
        try:
            display_path = path.relative_to(ROOT_DIR)
        except ValueError:
            display_path = path
        print(f"  - {name:34} {status}  {display_path}")


def load_md_content(file_path: Optional[str], pack: Optional[str] = None) -> str:
    if file_path and pack:
        raise ValueError("--file 和 --pack 不能同时使用")
    if file_path:
        md_path = Path(file_path).expanduser().resolve()
        if not md_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        if not md_path.is_file():
            raise FileNotFoundError(f"不是普通文件: {file_path}")
        return md_path.read_text(encoding="utf-8")

    pack_name = pack or DEFAULT_PACK
    if pack_name not in PROMPT_PACKS:
        choices = ", ".join(sorted(PROMPT_PACKS))
        raise ValueError(f"未知 prompt pack: {pack_name}. 可用: {choices}")
    pack_path = PROMPT_PACKS[pack_name]
    if not pack_path.is_file():
        raise FileNotFoundError(f"内置 prompt pack 文件不存在: {pack_path}")
    return pack_path.read_text(encoding="utf-8")


def default_name_for_args(args) -> str:
    if getattr(args, "name", None):
        return args.name
    return getattr(args, "pack", None) or DEFAULT_PACK


def print_codex_dirs(codex_dirs: Sequence[str]) -> None:
    print(f"[+] 找到 {len(codex_dirs)} 个 Codex 配置目录:")
    for d in codex_dirs:
        print(f"    {d}")


def deploy(args) -> None:
    """Main install/deploy logic."""
    try:
        md_content = load_md_content(getattr(args, "file", None), getattr(args, "pack", None))
        md_filename = normalize_md_name(default_name_for_args(args))
    except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
        print(f"[错误] {exc}")
        sys.exit(1)

    codex_dirs = get_codex_dirs_from_args(args)
    print_codex_dirs(codex_dirs)

    preview_only = getattr(args, "dry_run", False) or not getattr(args, "yes", False)
    if preview_only:
        print("\n[DRY RUN] 预览模式，不实际修改。")
        if not getattr(args, "yes", False):
            print("    如确认写入，请重新运行并添加 --yes。")
        for d in codex_dirs:
            md_dest = Path(d) / md_filename
            print(f"\n  目标: {d}")
            print(f"    → 写入 MD: {md_dest}")
            print(f"    → 配置项: model_instructions_file = \"./{md_filename}\"")
            if md_dest.exists():
                print(f"    → 已存在同名 MD，将先备份: {md_dest.name}")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for d in codex_dirs:
        codex_root = Path(d)
        config_path = codex_root / "config.toml"
        md_dest = codex_root / md_filename

        print(f"\n── 部署到: {codex_root} ──")

        config_backup = backup_config(config_path, timestamp)
        print(f"  [备份] config.toml → {config_backup.name}")

        md_backup = write_md_with_backup(md_dest, md_content, timestamp)
        if md_backup:
            print(f"  [备份] {md_dest.name} → {md_backup.name}")
        print(f"  [写入] {md_dest}")

        changed = ensure_model_instructions(config_path, md_filename)
        if changed:
            print(f"  [配置] 已设置 model_instructions_file = \"./{md_filename}\"")
        else:
            print("  [配置] model_instructions_file 已存在且值相同，跳过")

    print(f"\n[完成] 已部署到 {len(codex_dirs)} 个 Codex 配置目录。")


def backup_sets(codex_root: Path) -> List[BackupSet]:
    grouped: Dict[str, List[Path]] = {}
    for path in codex_root.iterdir():
        if not path.is_file():
            continue
        match = BACKUP_SUFFIX_RE.search(path.name)
        if match:
            grouped.setdefault(match.group(1), []).append(path)

    sets = []
    for timestamp, files in grouped.items():
        sorted_files = tuple(sorted(files, key=lambda p: p.name))
        has_config = any(p.name.startswith(f"config.toml.bak_{timestamp}") for p in sorted_files)
        prompt_count = sum(
            1
            for p in sorted_files
            if p.name.endswith(f".md.bak_{timestamp}") or re.search(rf"\.md\.bak_{timestamp}_\d+$", p.name)
        )
        sets.append(BackupSet(timestamp, sorted_files, has_config, prompt_count))
    return sorted(sets, key=lambda item: item.timestamp, reverse=True)


def print_backup_sets(codex_root: Path, sets: Sequence[BackupSet]) -> None:
    if not sets:
        print(f"  最近备份: none in {codex_root}")
        return
    print("  可用备份:")
    for item in sets[:10]:
        files = ", ".join(path.name for path in item.files)
        marker = "config" if item.has_config else "no-config"
        print(f"    - {item.timestamp} ({marker}, prompt_backups={item.prompt_count}): {files}")


def cmd_status(args) -> None:
    codex_dirs = get_codex_dirs_from_args(args)
    for raw in codex_dirs:
        codex_root = Path(raw)
        config_path = codex_root / "config.toml"
        print(f"Codex dir: {codex_root}")
        print(f"  config.toml: {'exists' if config_path.is_file() else 'missing'}")
        value = get_top_level_model_instructions(config_path) if config_path.is_file() else None
        print(f"  model_instructions_file: {value or 'not set'}")
        target = prompt_path_from_config_value(codex_root, value)
        if target:
            print(f"  target path: {target}")
            print(f"  target exists: {'yes' if target.is_file() else 'no'}")
        else:
            print("  target path: n/a")
            print("  target exists: n/a")
        print_backup_sets(codex_root, backup_sets(codex_root))


def backup_exists_for_timestamp(codex_root: Path, timestamp: str) -> bool:
    return (codex_root / f"config.toml.bak_{timestamp}").is_file()


def prompt_destination_name_from_backup(backup: Path, timestamp: str) -> str:
    match = re.match(rf"^(.+\.md)\.bak_{timestamp}(?:_\d+)?$", backup.name)
    if not match:
        raise ValueError(f"不是匹配该时间戳的 prompt 备份: {backup.name}")
    return match.group(1)


def prompt_backups_for_timestamp(codex_root: Path, timestamp: str) -> List[Path]:
    return sorted(
        path
        for path in codex_root.iterdir()
        if path.is_file() and re.match(rf"^.+\.md\.bak_{timestamp}(?:_\d+)?$", path.name)
    )


def base_backup_timestamp(timestamp: str) -> str:
    match = re.match(r"^(\d{8}_\d{6})(?:_\d+)?$", timestamp)
    if not match:
        raise ValueError(f"不是有效备份时间戳: {timestamp}")
    return match.group(1)


def restore_backup_set(codex_root: Path, timestamp: str, include_prompts: bool, yes: bool) -> None:
    config_backup = codex_root / f"config.toml.bak_{timestamp}"
    if not config_backup.is_file():
        raise FileNotFoundError(f"未找到 config.toml 备份: {config_backup.name}")

    prompt_timestamp = base_backup_timestamp(timestamp)
    prompt_backups = prompt_backups_for_timestamp(codex_root, prompt_timestamp)
    print(f"\n目标: {codex_root}")
    print(f"  → restore config: {config_backup.name} -> config.toml")
    if include_prompts:
        if prompt_backups:
            for backup in prompt_backups:
                dest_name = prompt_destination_name_from_backup(backup, prompt_timestamp)
                print(f"  → restore prompt: {backup.name} -> {dest_name}")
        else:
            print("  → restore prompt: no prompt backup matching this timestamp")
    else:
        print("  → restore prompt: skipped (add --include-prompts to restore matching .md backups)")

    if not yes:
        print("  [DRY RUN] 不实际恢复。确认恢复请添加 --yes。")
        return

    safety_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_config = codex_root / "config.toml"
    safety_backup = backup_config(current_config, safety_ts)
    shutil.copy2(config_backup, current_config)
    print(f"  [备份] 当前 config.toml → {safety_backup.name}")
    print(f"  [恢复] config.toml ← {config_backup.name}")

    if include_prompts:
        for backup in prompt_backups:
            dest_name = prompt_destination_name_from_backup(backup, prompt_timestamp)
            dest = codex_root / dest_name
            if dest.exists():
                prompt_safety = backup_file(dest, safety_ts)
                print(f"  [备份] 当前 {dest.name} → {prompt_safety.name}")
            shutil.copy2(backup, dest)
            print(f"  [恢复] {dest.name} ← {backup.name}")


def cmd_restore(args) -> None:
    codex_dirs = get_codex_dirs_from_args(args)
    if not getattr(args, "backup", None):
        for raw in codex_dirs:
            codex_root = Path(raw)
            print(f"Codex dir: {codex_root}")
            print_backup_sets(codex_root, backup_sets(codex_root))
        print("\n请用 --backup YYYYMMDD_HHMMSS 明确指定要恢复的备份。")
        return

    try:
        timestamp = normalize_backup_timestamp(args.backup)
        for raw in codex_dirs:
            restore_backup_set(Path(raw), timestamp, args.include_prompts, args.yes)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[错误] {exc}")
        sys.exit(1)


def preview_uninstall(codex_root: Path, delete_prompt: bool) -> Tuple[Optional[Path], Optional[str]]:
    config_path = codex_root / "config.toml"
    value = get_top_level_model_instructions(config_path)
    target = prompt_path_from_config_value(codex_root, value)
    print(f"\n目标: {codex_root}")
    print("  → remove model_instructions_file from config.toml")
    if value:
        print(f"  → current value: {value}")
    else:
        print("  → current value: not set")
    if delete_prompt:
        print(f"  → delete prompt file after backup: {target if target else 'n/a'}")
    else:
        print("  → prompt file: keep")
    return target, value


def cmd_uninstall(args) -> None:
    codex_dirs = get_codex_dirs_from_args(args)
    preview_only = args.dry_run or not args.yes
    if preview_only:
        print("[DRY RUN] 卸载预览，不实际修改。")
        if not args.yes:
            print("    如确认卸载，请重新运行并添加 --yes。")
        for raw in codex_dirs:
            preview_uninstall(Path(raw), args.delete_prompt)
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for raw in codex_dirs:
        codex_root = Path(raw)
        config_path = codex_root / "config.toml"
        target, _ = preview_uninstall(codex_root, args.delete_prompt)
        config_backup = backup_config(config_path, timestamp)
        removed = remove_top_level_model_instructions(config_path)
        print(f"  [备份] config.toml → {config_backup.name}")
        if removed:
            print("  [卸载] 已移除顶层 model_instructions_file")
        else:
            print("  [卸载] 顶层 model_instructions_file 原本未设置")
        if args.delete_prompt and target:
            try:
                if not target.is_file():
                    print(f"  [跳过] prompt 文件不存在: {target}")
                elif target.parent.resolve() != codex_root.resolve():
                    print(f"  [跳过] prompt 文件不在 Codex 目录内，避免误删: {target}")
                else:
                    prompt_backup = backup_file(target, timestamp)
                    target.unlink()
                    print(f"  [备份] {target.name} → {prompt_backup.name}")
                    print(f"  [删除] {target.name}")
            except OSError as exc:
                print(f"  [错误] 删除 prompt 文件失败: {exc}")
                sys.exit(1)


def add_install_args(parser: argparse.ArgumentParser, legacy: bool = False) -> None:
    parser.add_argument("--file", "-f", help="外部 MD 文件路径 (不指定则使用内置 prompt pack)")
    parser.add_argument("--pack", choices=sorted(PROMPT_PACKS), default=None, help=f"内置 prompt pack 名称，默认: {DEFAULT_PACK}")
    parser.add_argument("--name", "-n", default=None, help=f"MD 文件名 (不含 .md)，默认跟随 --pack；未指定时为 {DEFAULT_PACK}")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改")
    parser.add_argument("--yes", action="store_true", help="确认写入 Codex 配置目录；未提供时仅预览")
    parser.add_argument("--codex-dir", help="手动指定 .codex 目录 (跳过自动检测)")
    if legacy:
        parser.set_defaults(command="install")


def build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Codex MD 指令文件部署脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --dry-run                         预览将写入的文件和配置项
  %(prog)s --codex-dir ~/.codex --yes        写入指定 Codex 配置目录
  %(prog)s --name my-rules --dry-run         自定义文件名 my-rules.md
  %(prog)s --file ./my_prompt.md --dry-run   使用外部 MD 文件
  %(prog)s install --pack general-research --dry-run
  %(prog)s status --codex-dir ~/.codex
  %(prog)s restore --codex-dir ~/.codex      列出可恢复备份
  %(prog)s uninstall --codex-dir ~/.codex    预览卸载
        """,
    )
    add_install_args(parser, legacy=True)
    return parser


def build_command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Codex instruction-file installer with status/restore/uninstall helpers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install a prompt pack or external Markdown instruction file")
    add_install_args(install_parser)

    list_parser = subparsers.add_parser("list-packs", help="list built-in prompt packs")
    list_parser.set_defaults(command="list-packs")

    status_parser = subparsers.add_parser("status", help="show current model_instructions_file and backups")
    status_parser.add_argument("--codex-dir", help="手动指定 .codex 目录 (跳过自动检测)")

    restore_parser = subparsers.add_parser("restore", help="restore config.toml and optionally prompt files from backups")
    restore_parser.add_argument("--codex-dir", help="手动指定 .codex 目录 (跳过自动检测)")
    restore_parser.add_argument("--backup", help="要恢复的备份时间戳 YYYYMMDD_HHMMSS，可带 _N 序号；不传则只列出备份")
    restore_parser.add_argument("--include-prompts", action="store_true", help="同时恢复同时间戳的 .md prompt 文件备份")
    restore_parser.add_argument("--yes", action="store_true", help="确认恢复；未提供时仅预览")

    uninstall_parser = subparsers.add_parser("uninstall", help="remove model_instructions_file and optionally delete installed prompt file")
    uninstall_parser.add_argument("--codex-dir", help="手动指定 .codex 目录 (跳过自动检测)")
    uninstall_parser.add_argument("--delete-prompt", action="store_true", help="备份后删除当前 model_instructions_file 指向的 Codex 目录内 prompt 文件")
    uninstall_parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改")
    uninstall_parser.add_argument("--yes", action="store_true", help="确认卸载；未提供时仅预览")

    return parser


def parse_args(argv: Optional[Sequence[str]] = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"install", "status", "restore", "uninstall", "list-packs"}
    if argv and argv[0] in commands:
        return build_command_parser().parse_args(argv)
    return build_legacy_parser().parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if args.command == "install":
        deploy(args)
    elif args.command == "list-packs":
        list_prompt_packs()
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "restore":
        cmd_restore(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

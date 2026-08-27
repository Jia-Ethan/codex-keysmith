#!/usr/bin/env python3
"""Bump every tracked source version in one atomic, verified step."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# Reuse the release gate's own parsers so this tool can never disagree with
# scripts/validate_desktop_candidate.py about what a file's version is.
if __package__:
    from . import validate_desktop_candidate as candidate_validator
else:
    import validate_desktop_candidate as candidate_validator


REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
GUI_PACKAGE_NAME = "codex-keysmith-gui"
CARGO_PACKAGE_NAME = "codex-keysmith-gui"

# Every file that stores the source version. tauri.conf.json is intentionally
# absent: it inherits its version from gui/package.json and validate_config
# rejects any other arrangement.
VERSION_FILES = (
    "VERSION",
    "codex-instruct.py",
    "gui/package.json",
    "gui/package-lock.json",
    "gui/src-tauri/Cargo.toml",
    "gui/src-tauri/Cargo.lock",
)


class BumpError(RuntimeError):
    """Raised when a version bump cannot be applied safely."""


def _semver(value: object, source: str) -> str:
    if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
        raise BumpError(f"{source} must be an exact MAJOR.MINOR.PATCH version")
    return value


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BumpError(f"cannot read UTF-8 text file {path}: {exc}") from exc


def _write_text(path: Path, text: str) -> None:
    # Write bytes so the existing newline convention survives verbatim on every
    # platform; Path.write_text(newline=...) is unavailable on Python 3.9.
    try:
        path.write_bytes(text.encode("utf-8"))
    except OSError as exc:
        raise BumpError(f"cannot write {path}: {exc}") from exc


def _load_json(path: Path) -> Any:
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise BumpError(f"invalid JSON in {path}: {exc}") from exc


def _dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _substitute_once(text: str, pattern: re.Pattern[str], new_version: str, path: Path) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BumpError(
            f"expected exactly one version declaration in {path}, found {len(matches)}"
        )
    match = matches[0]
    return text[: match.start("version")] + new_version + text[match.end("version") :]


def _bump_version_file(path: Path, new_version: str) -> str:
    text = _read_text(path)
    current = _semver(text.strip(), str(path))
    # Preserve the original trailing-newline convention.
    suffix = text[len(text.rstrip("\r\n")) :]
    _write_text(path, new_version + (suffix or "\n"))
    return current


def _bump_python_script(path: Path, new_version: str) -> str:
    text = _read_text(path)
    pattern = re.compile(
        r'^__version__\s*=\s*"(?P<version>[^"]+)"',
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BumpError(
            f"expected exactly one literal __version__ assignment in {path},"
            f" found {len(matches)}"
        )
    current = _semver(matches[0].group("version"), str(path))
    _write_text(path, _substitute_once(text, pattern, new_version, path))
    return current


def _bump_package_json(path: Path, new_version: str) -> str:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise BumpError(f"expected a JSON object in {path}")
    if data.get("name") != GUI_PACKAGE_NAME:
        raise BumpError(f"{path} must declare package name {GUI_PACKAGE_NAME}")
    current = _semver(data.get("version"), str(path))
    data["version"] = new_version
    _write_text(path, _dump_json(data))
    return current


def _bump_package_lock(path: Path, new_version: str) -> str:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise BumpError(f"expected a JSON object in {path}")
    packages = data.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise BumpError(f"missing root package entry in {path}")
    root = packages[""]
    if data.get("name") != GUI_PACKAGE_NAME or root.get("name") != GUI_PACKAGE_NAME:
        raise BumpError(f"{path} must declare package name {GUI_PACKAGE_NAME}")
    document_version = _semver(data.get("version"), str(path))
    root_version = _semver(root.get("version"), str(path))
    if document_version != root_version:
        raise BumpError(f"package-lock versions already disagree in {path}")
    data["version"] = new_version
    root["version"] = new_version
    _write_text(path, _dump_json(data))
    return document_version


def _bump_cargo_toml(path: Path, new_version: str) -> str:
    text = _read_text(path)
    pattern = re.compile(
        r'(?ms)^\[package\][^\[]*?^version\s*=\s*"(?P<version>[^"]+)"',
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BumpError(f"missing [package] version in {path}")
    current = _semver(matches[0].group("version"), str(path))
    _write_text(path, _substitute_once(text, pattern, new_version, path))
    return current


def _bump_cargo_lock(path: Path, new_version: str) -> str:
    text = _read_text(path)
    pattern = re.compile(
        r'(?ms)^\[\[package\]\]\nname = "'
        + re.escape(CARGO_PACKAGE_NAME)
        + r'"\nversion = "(?P<version>[^"]+)"',
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BumpError(
            f"expected exactly one {CARGO_PACKAGE_NAME} package entry in {path},"
            f" found {len(matches)}"
        )
    current = _semver(matches[0].group("version"), str(path))
    _write_text(path, _substitute_once(text, pattern, new_version, path))
    return current


BUMPERS: dict[str, Callable[[Path, str], str]] = {
    "VERSION": _bump_version_file,
    "codex-instruct.py": _bump_python_script,
    "gui/package.json": _bump_package_json,
    "gui/package-lock.json": _bump_package_lock,
    "gui/src-tauri/Cargo.toml": _bump_cargo_toml,
    "gui/src-tauri/Cargo.lock": _bump_cargo_lock,
}


def read_versions(root: Path) -> dict[str, str]:
    """Return the version currently recorded in every tracked file."""
    versions: dict[str, str] = {}
    for relative in VERSION_FILES:
        path = root / relative
        text_probe = _read_text(path)
        if relative == "VERSION":
            versions[relative] = _semver(text_probe.strip(), str(path))
        elif relative == "codex-instruct.py":
            versions[relative] = candidate_validator._python_static_version(path)
        elif relative == "gui/package.json":
            versions[relative] = _semver(_load_json(path).get("version"), str(path))
        elif relative == "gui/package-lock.json":
            versions[relative] = candidate_validator._package_lock_version(
                path, GUI_PACKAGE_NAME
            )
        elif relative == "gui/src-tauri/Cargo.toml":
            versions[relative] = candidate_validator._cargo_package_version(path)
        else:
            versions[relative] = candidate_validator._cargo_lock_package_version(
                path, CARGO_PACKAGE_NAME
            )
    return versions


def check_versions(root: Path) -> str:
    """Fail closed unless every tracked file records the same version.

    This owns version agreement only. The full desktop contract (icons,
    capabilities, workflow policy) stays in validate_desktop_candidate.py and
    is invoked separately by CI.
    """
    root = root.resolve()
    versions = read_versions(root)
    distinct = set(versions.values())
    if len(distinct) != 1:
        raise BumpError(f"source versions disagree: {versions}")
    return distinct.pop()


def bump(root: Path, new_version: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Rewrite every tracked version file, then re-validate the whole tree."""
    root = root.resolve()
    new_version = _semver(new_version, "target version")
    current = check_versions(root)
    if new_version == current:
        raise BumpError(f"source version is already {current}")

    originals = {
        relative: (root / relative).read_bytes() for relative in VERSION_FILES
    }
    if dry_run:
        return {
            "previous_version": current,
            "version": new_version,
            "changed": list(VERSION_FILES),
            "dry_run": True,
        }

    try:
        for relative in VERSION_FILES:
            BUMPERS[relative](root / relative, new_version)
        applied = check_versions(root)
        if applied != new_version:
            raise BumpError(f"post-bump validation reported {applied}, expected {new_version}")
    except BaseException:
        for relative, data in originals.items():
            try:
                (root / relative).write_bytes(data)
            except OSError:
                # Surface the original failure, but make the incomplete
                # restore explicit instead of silently leaving a mixed tree.
                print(
                    f"failed to restore {relative}; inspect the worktree before retrying",
                    file=sys.stderr,
                )
        raise

    return {
        "previous_version": current,
        "version": new_version,
        "changed": list(VERSION_FILES),
        "dry_run": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="verify every tracked file records the same source version",
    )
    check.set_defaults(
        handler=lambda args: print(
            json.dumps({"version": check_versions(args.root)}, sort_keys=True)
        )
    )

    set_version = subparsers.add_parser(
        "set",
        help="rewrite every tracked file to the given source version",
    )
    set_version.add_argument("version")
    set_version.add_argument(
        "--dry-run",
        action="store_true",
        help="report the planned bump without writing files",
    )
    set_version.set_defaults(
        handler=lambda args: print(
            json.dumps(
                bump(args.root, args.version, dry_run=args.dry_run),
                sort_keys=True,
            )
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.handler(args)
    except (OSError, BumpError, candidate_validator.CandidateError) as exc:
        print(f"version bump failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble and verify the public unsigned desktop prerelease assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

if __package__:
    from . import validate_desktop_candidate as candidate_validator
else:
    import validate_desktop_candidate as candidate_validator


REPO_ROOT = Path(__file__).resolve().parents[1]
# The unsigned desktop beta line is immutable and intentionally remains on 0.2.0.
VERSION = "0.2.0"
PRODUCT = "codex-keysmith"
TAG_RE = re.compile(rf"^desktop-v{re.escape(VERSION)}-beta\.[1-9][0-9]*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKSUMS_NAME = "SHA256SUMS"

MACOS_DMG_NAME = f"{PRODUCT}-{VERSION}-macos-arm64-unsigned.dmg"
MACOS_CANDIDATE_ZIP_NAME = f"{PRODUCT}-{VERSION}-macos-arm64-unsigned-candidate.zip"
WINDOWS_SETUP_NAME = f"{PRODUCT}-{VERSION}-windows-x64-unsigned-setup.exe"
WINDOWS_CANDIDATE_ZIP_NAME = f"{PRODUCT}-{VERSION}-windows-x64-unsigned-candidate.zip"
CLI_NAME = f"codex-instruct-v{VERSION}.py"
SOURCE_ZIP_NAME = f"{PRODUCT}-v{VERSION}.zip"
SOURCE_TAR_NAME = f"{PRODUCT}-v{VERSION}.tar.gz"

# Retain the legacy names for callers that only need the Windows asset constants.
SETUP_NAME = WINDOWS_SETUP_NAME
CANDIDATE_ZIP_NAME = WINDOWS_CANDIDATE_ZIP_NAME

SOURCE_PAYLOAD_NAMES = (CLI_NAME, SOURCE_ZIP_NAME, SOURCE_TAR_NAME)
PUBLIC_PAYLOAD_NAMES = (
    MACOS_DMG_NAME,
    MACOS_CANDIDATE_ZIP_NAME,
    WINDOWS_SETUP_NAME,
    WINDOWS_CANDIDATE_ZIP_NAME,
    *SOURCE_PAYLOAD_NAMES,
)
PUBLIC_ASSET_NAMES = (*PUBLIC_PAYLOAD_NAMES, CHECKSUMS_NAME)

PLATFORM_CONFIGS = {
    "macos": {
        "target": {
            "platform": "macos",
            "architecture": "arm64",
            "triple": "aarch64-apple-darwin",
            "bundle_format": "dmg",
            "signing_mode": "unsigned",
        },
        "bundle_suffix": ".dmg",
        "public_bundle": MACOS_DMG_NAME,
        "candidate_zip": MACOS_CANDIDATE_ZIP_NAME,
        "fixed_files": {
            "build-manifest.json",
            "codex-keysmith-gui",
            "codex-keysmith-cli",
            "icon.icns",
            CHECKSUMS_NAME,
        },
    },
    "windows": {
        "target": {
            "platform": "windows",
            "architecture": "x86_64",
            "triple": "x86_64-pc-windows-msvc",
            "bundle_format": "nsis",
            "signing_mode": "unsigned",
        },
        "bundle_suffix": ".exe",
        "public_bundle": WINDOWS_SETUP_NAME,
        "candidate_zip": WINDOWS_CANDIDATE_ZIP_NAME,
        "fixed_files": {
            "build-manifest.json",
            "codex-keysmith-gui.exe",
            "codex-keysmith-cli.exe",
            "icon.ico",
            CHECKSUMS_NAME,
        },
    },
}


class PrereleaseError(RuntimeError):
    """Raised when an unsigned desktop prerelease invariant is violated."""


def _require_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise PrereleaseError(f"missing prerelease file {path}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise PrereleaseError(f"prerelease path must be a regular file, not a symlink: {path}")


def _sha256(path: Path) -> str:
    _require_regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    _require_regular_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrereleaseError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PrereleaseError(f"expected a JSON object in {path}")
    return value


def _validate_tag_and_commit(tag: str, expected_commit: str) -> None:
    if TAG_RE.fullmatch(tag) is None:
        raise PrereleaseError(
            f"release tag must match desktop-v{VERSION}-beta.N with N starting at 1"
        )
    if COMMIT_RE.fullmatch(expected_commit) is None:
        raise PrereleaseError("expected commit must be a full lowercase 40-character SHA")


def _validate_candidate(
    candidate_dir: Path,
    expected_commit: str,
    platform: str,
) -> dict[str, Any]:
    config = PLATFORM_CONFIGS[platform]
    candidate_dir = candidate_dir.absolute()
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise PrereleaseError(f"candidate directory is missing or unsafe: {candidate_dir}")
    manifest_path = candidate_dir / "build-manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("desktop_version") != VERSION or manifest.get("cli_version") != VERSION:
        raise PrereleaseError(f"candidate versions must both be {VERSION}")
    if manifest.get("source_commit") != expected_commit:
        raise PrereleaseError("candidate manifest source commit does not match expected commit")
    if manifest.get("target") != config["target"]:
        raise PrereleaseError(f"candidate must match the unsigned {platform} target policy")
    provenance = manifest.get("sidecar_provenance")
    if not isinstance(provenance, dict) or provenance.get("relation") != "exact-copy":
        raise PrereleaseError("unsigned candidate sidecar must be the exact tested build output")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PrereleaseError("candidate manifest artifacts are missing")
    bundle = artifacts.get("bundle")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("file"), str):
        raise PrereleaseError("candidate manifest bundle record is missing")
    bundle_name = bundle["file"]
    if Path(bundle_name).name != bundle_name or not bundle_name.lower().endswith(
        str(config["bundle_suffix"])
    ):
        raise PrereleaseError(f"candidate bundle filename is unsafe or not a {platform} bundle")
    expected_files = set(config["fixed_files"]) | {bundle_name}
    entries = list(candidate_dir.iterdir())
    actual_files = {entry.name for entry in entries}
    if actual_files != expected_files:
        raise PrereleaseError(
            f"candidate directory file set is not exact: expected {sorted(expected_files)}, "
            f"got {sorted(actual_files)}"
        )
    for entry in entries:
        _require_regular_file(entry)
    try:
        candidate_validator.verify_manifest(manifest_path, execute_sidecar=False)
    except candidate_validator.CandidateError as exc:
        raise PrereleaseError(f"candidate manifest verification failed: {exc}") from exc
    return manifest


def _validate_source_assets(source_dir: Path) -> None:
    source_dir = source_dir.absolute()
    if not source_dir.is_dir() or source_dir.is_symlink():
        raise PrereleaseError(f"source asset directory is missing or unsafe: {source_dir}")
    entries = list(source_dir.iterdir())
    expected_names = {*SOURCE_PAYLOAD_NAMES, CHECKSUMS_NAME}
    actual_names = {entry.name for entry in entries}
    if actual_names != expected_names:
        raise PrereleaseError(
            f"source asset set is not exact: expected {sorted(expected_names)}, "
            f"got {sorted(actual_names)}"
        )
    for entry in entries:
        _require_regular_file(entry)
    expected_lines = [
        f"{_sha256(source_dir / name)}  {name}" for name in sorted(SOURCE_PAYLOAD_NAMES)
    ]
    try:
        checksum_lines = (source_dir / CHECKSUMS_NAME).read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PrereleaseError(f"cannot read source SHA256SUMS: {exc}") from exc
    if checksum_lines != expected_lines:
        raise PrereleaseError("source SHA256SUMS does not exactly cover deterministic source assets")


def _write_deterministic_zip(candidate_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for source in sorted(candidate_dir.iterdir(), key=lambda path: path.name):
            _require_regular_file(source)
            info = zipfile.ZipInfo(source.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def _verify_candidate_zip(
    output_dir: Path,
    platform: str,
    expected_commit: str,
) -> str:
    config = PLATFORM_CONFIGS[platform]
    archive_path = output_dir / str(config["candidate_zip"])
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if names != sorted(names) or len(names) != len(set(names)):
            raise PrereleaseError("candidate ZIP entries must be sorted and unique")
        if any(Path(name).name != name for name in names):
            raise PrereleaseError("candidate ZIP contains an unsafe path")
        for info in archive.infolist():
            if info.is_dir() or info.date_time != (1980, 1, 1, 0, 0, 0):
                raise PrereleaseError("candidate ZIP metadata is not deterministic")
            archived_mode = info.external_attr >> 16
            if stat.S_IFMT(archived_mode) != stat.S_IFREG:
                raise PrereleaseError("candidate ZIP entries must be regular files")
        with tempfile.TemporaryDirectory(prefix="desktop-prerelease-verify-") as raw_temp:
            extracted = Path(raw_temp)
            for info in archive.infolist():
                (extracted / info.filename).write_bytes(archive.read(info))
            manifest = _read_json(extracted / "build-manifest.json")
            manifest_commit = manifest.get("source_commit")
            if not isinstance(manifest_commit, str) or COMMIT_RE.fullmatch(manifest_commit) is None:
                raise PrereleaseError("candidate ZIP manifest source commit is missing or invalid")
            if manifest_commit != expected_commit:
                raise PrereleaseError(
                    "candidate ZIP manifest source commit does not match expected commit"
                )
            verified_manifest = _validate_candidate(extracted, manifest_commit, platform)
            bundle_name = verified_manifest["artifacts"]["bundle"]["file"]
            public_bundle = output_dir / str(config["public_bundle"])
            if _sha256(public_bundle) != _sha256(extracted / bundle_name):
                raise PrereleaseError(
                    f"public {platform} bundle does not match the original bundle in its candidate ZIP"
                )
            return manifest_commit


def verify_public_assets(
    output_dir: Path,
    expected_commit: str,
    source_dir: Path | None = None,
) -> None:
    if COMMIT_RE.fullmatch(expected_commit) is None:
        raise PrereleaseError("expected commit must be a full lowercase 40-character SHA")
    output_dir = output_dir.absolute()
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise PrereleaseError(f"prerelease output directory is missing or unsafe: {output_dir}")
    entries = list(output_dir.iterdir())
    actual_names = {entry.name for entry in entries}
    if actual_names != set(PUBLIC_ASSET_NAMES):
        raise PrereleaseError(
            f"public asset set is not exact: expected {sorted(PUBLIC_ASSET_NAMES)}, "
            f"got {sorted(actual_names)}"
        )
    for entry in entries:
        _require_regular_file(entry)
    try:
        checksum_lines = (output_dir / CHECKSUMS_NAME).read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PrereleaseError(f"cannot read public SHA256SUMS: {exc}") from exc
    expected_lines = [
        f"{_sha256(output_dir / name)}  {name}" for name in sorted(PUBLIC_PAYLOAD_NAMES)
    ]
    if checksum_lines != expected_lines:
        raise PrereleaseError("public SHA256SUMS does not exactly cover all public payloads")
    macos_commit = _verify_candidate_zip(output_dir, "macos", expected_commit)
    windows_commit = _verify_candidate_zip(output_dir, "windows", expected_commit)
    if macos_commit != windows_commit:
        raise PrereleaseError("macOS and Windows candidate manifests do not bind the same commit")
    if source_dir is not None:
        source_dir = source_dir.absolute()
        _validate_source_assets(source_dir)
        for name in SOURCE_PAYLOAD_NAMES:
            if _sha256(output_dir / name) != _sha256(source_dir / name):
                raise PrereleaseError(
                    f"public source asset does not match the commit-bound build output: {name}"
                )


def assemble_prerelease(
    macos_candidate_dir: Path,
    windows_candidate_dir: Path,
    source_dir: Path,
    output_dir: Path,
    tag: str,
    expected_commit: str,
) -> Path:
    _validate_tag_and_commit(tag, expected_commit)
    candidate_dirs = {
        "macos": macos_candidate_dir.absolute(),
        "windows": windows_candidate_dir.absolute(),
    }
    manifests = {
        platform: _validate_candidate(candidate_dir, expected_commit, platform)
        for platform, candidate_dir in candidate_dirs.items()
    }
    source_dir = source_dir.absolute()
    _validate_source_assets(source_dir)
    output_dir = output_dir.absolute()
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir() or any(output_dir.iterdir()):
            raise PrereleaseError(f"output directory must be absent or empty: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".desktop-prerelease-", dir=output_dir.parent))
    try:
        for platform, candidate_dir in candidate_dirs.items():
            config = PLATFORM_CONFIGS[platform]
            bundle_name = manifests[platform]["artifacts"]["bundle"]["file"]
            public_bundle = temporary / str(config["public_bundle"])
            shutil.copyfile(candidate_dir / bundle_name, public_bundle)
            os.chmod(public_bundle, 0o644)
            _write_deterministic_zip(
                candidate_dir,
                temporary / str(config["candidate_zip"]),
            )
        for name in SOURCE_PAYLOAD_NAMES:
            destination = temporary / name
            shutil.copyfile(source_dir / name, destination)
            os.chmod(destination, 0o755 if name == CLI_NAME else 0o644)
        checksum_lines = [
            f"{_sha256(temporary / name)}  {name}"
            for name in sorted(PUBLIC_PAYLOAD_NAMES)
        ]
        (temporary / CHECKSUMS_NAME).write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="ascii",
        )
        verify_public_assets(temporary, expected_commit, source_dir)
        if output_dir.exists():
            output_dir.rmdir()
        temporary.rename(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_public_assets(output_dir, expected_commit, source_dir)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble = subparsers.add_parser("assemble", help="assemble fixed public prerelease assets")
    assemble.add_argument("--macos-candidate-dir", type=Path, required=True)
    assemble.add_argument("--windows-candidate-dir", type=Path, required=True)
    assemble.add_argument("--source-dir", type=Path, required=True)
    assemble.add_argument("--output-dir", type=Path, required=True)
    assemble.add_argument("--release-tag", required=True)
    assemble.add_argument("--expected-commit", required=True)
    assemble.set_defaults(
        handler=lambda args: print(
            assemble_prerelease(
                args.macos_candidate_dir,
                args.windows_candidate_dir,
                args.source_dir,
                args.output_dir,
                args.release_tag,
                args.expected_commit,
            )
        )
    )
    verify = subparsers.add_parser("verify", help="verify the fixed public asset set")
    verify.add_argument("output_dir", type=Path)
    verify.add_argument("--expected-commit", required=True)
    verify.add_argument("--source-dir", type=Path)
    verify.set_defaults(
        handler=lambda args: verify_public_assets(
            args.output_dir,
            args.expected_commit,
            args.source_dir,
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.handler(args)
    except (OSError, zipfile.BadZipFile, PrereleaseError) as exc:
        print(f"desktop prerelease packaging failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

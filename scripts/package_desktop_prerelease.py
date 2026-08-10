#!/usr/bin/env python3
"""Assemble and verify the public unsigned Windows desktop prerelease assets."""

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


VERSION = "0.2.0"
PRODUCT = "codex-keysmith"
TAG_RE = re.compile(r"^desktop-v0\.2\.0-beta\.[1-9][0-9]*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SETUP_NAME = "codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe"
CANDIDATE_ZIP_NAME = "codex-keysmith-0.2.0-windows-x64-unsigned-candidate.zip"
CHECKSUMS_NAME = "SHA256SUMS"
PUBLIC_ASSET_NAMES = (SETUP_NAME, CANDIDATE_ZIP_NAME, CHECKSUMS_NAME)
EXPECTED_FIXED_CANDIDATE_FILES = {
    "build-manifest.json",
    "codex-keysmith-gui.exe",
    "codex-keysmith-cli.exe",
    "icon.ico",
    "SHA256SUMS",
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
            "release tag must match desktop-v0.2.0-beta.N with N starting at 1"
        )
    if COMMIT_RE.fullmatch(expected_commit) is None:
        raise PrereleaseError("expected commit must be a full lowercase 40-character SHA")


def _validate_candidate(candidate_dir: Path, expected_commit: str) -> dict[str, Any]:
    candidate_dir = candidate_dir.absolute()
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise PrereleaseError(f"candidate directory is missing or unsafe: {candidate_dir}")
    manifest_path = candidate_dir / "build-manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("desktop_version") != VERSION or manifest.get("cli_version") != VERSION:
        raise PrereleaseError(f"candidate versions must both be {VERSION}")
    if manifest.get("source_commit") != expected_commit:
        raise PrereleaseError("candidate manifest source commit does not match expected commit")
    if manifest.get("target") != {
        "platform": "windows",
        "architecture": "x86_64",
        "triple": "x86_64-pc-windows-msvc",
        "bundle_format": "nsis",
        "signing_mode": "unsigned",
    }:
        raise PrereleaseError("candidate must be an unsigned Windows x64 NSIS build")
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
    if Path(bundle_name).name != bundle_name or not bundle_name.lower().endswith(".exe"):
        raise PrereleaseError("candidate bundle filename is unsafe or not an EXE")
    expected_files = EXPECTED_FIXED_CANDIDATE_FILES | {bundle_name}
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
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def verify_public_assets(output_dir: Path, expected_commit: str | None = None) -> None:
    if expected_commit is not None and COMMIT_RE.fullmatch(expected_commit) is None:
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
    checksum_lines = (output_dir / CHECKSUMS_NAME).read_text(encoding="ascii").splitlines()
    expected_lines = sorted(
        f"{_sha256(output_dir / name)}  {name}"
        for name in (SETUP_NAME, CANDIDATE_ZIP_NAME)
    )
    if checksum_lines != expected_lines:
        raise PrereleaseError("public SHA256SUMS does not exactly cover setup and candidate ZIP")
    with zipfile.ZipFile(output_dir / CANDIDATE_ZIP_NAME, "r") as archive:
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
            if not isinstance(manifest_commit, str):
                raise PrereleaseError("candidate ZIP manifest source commit is missing")
            if expected_commit is not None and manifest_commit != expected_commit:
                raise PrereleaseError(
                    "candidate ZIP manifest source commit does not match expected commit"
                )
            verified_manifest = _validate_candidate(extracted, manifest_commit)
            bundle_name = verified_manifest["artifacts"]["bundle"]["file"]
            if _sha256(output_dir / SETUP_NAME) != _sha256(extracted / bundle_name):
                raise PrereleaseError(
                    "public setup EXE does not match the original installer in the candidate ZIP"
                )


def assemble_prerelease(
    candidate_dir: Path,
    output_dir: Path,
    tag: str,
    expected_commit: str,
) -> Path:
    _validate_tag_and_commit(tag, expected_commit)
    candidate_dir = candidate_dir.absolute()
    manifest = _validate_candidate(candidate_dir, expected_commit)
    bundle_name = manifest["artifacts"]["bundle"]["file"]
    output_dir = output_dir.absolute()
    if output_dir.exists():
        if output_dir.is_symlink() or not output_dir.is_dir() or any(output_dir.iterdir()):
            raise PrereleaseError(f"output directory must be absent or empty: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".desktop-prerelease-", dir=output_dir.parent))
    try:
        setup = temporary / SETUP_NAME
        shutil.copyfile(candidate_dir / bundle_name, setup)
        os.chmod(setup, 0o644)
        _write_deterministic_zip(candidate_dir, temporary / CANDIDATE_ZIP_NAME)
        checksum_lines = sorted(
            f"{_sha256(temporary / name)}  {name}"
            for name in (SETUP_NAME, CANDIDATE_ZIP_NAME)
        )
        (temporary / CHECKSUMS_NAME).write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="ascii",
        )
        verify_public_assets(temporary, expected_commit)
        if output_dir.exists():
            output_dir.rmdir()
        temporary.rename(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_public_assets(output_dir, expected_commit)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble = subparsers.add_parser("assemble", help="assemble fixed public prerelease assets")
    assemble.add_argument("--candidate-dir", type=Path, required=True)
    assemble.add_argument("--output-dir", type=Path, required=True)
    assemble.add_argument("--release-tag", required=True)
    assemble.add_argument("--expected-commit", required=True)
    assemble.set_defaults(
        handler=lambda args: print(
            assemble_prerelease(
                args.candidate_dir,
                args.output_dir,
                args.release_tag,
                args.expected_commit,
            )
        )
    )
    verify = subparsers.add_parser("verify", help="verify the fixed public asset set")
    verify.add_argument("output_dir", type=Path)
    verify.add_argument("--expected-commit")
    verify.set_defaults(
        handler=lambda args: verify_public_assets(args.output_dir, args.expected_commit)
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.handler(args)
    except PrereleaseError as exc:
        print(f"desktop prerelease packaging failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

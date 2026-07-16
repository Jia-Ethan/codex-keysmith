#!/usr/bin/env python3
"""Build deterministic local release assets for codex-keysmith."""

import argparse
import gzip
import hashlib
import io
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ARCHIVE_FILES = (
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "VERSION",
    "codex-instruct.py",
    "docs/hooks-transactions.md",
    "examples/gpt-unrestricted.md",
)
MIT_MARKERS = (
    b"MIT License",
    b"Permission is hereby granted, free of charge",
    b'THE SOFTWARE IS PROVIDED "AS IS"',
)
TAG_PATTERN = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
FULL_COMMIT_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
CLI_VERSION_PATTERN = re.compile(
    rb"^(?:__version__|VERSION)\s*=\s*['\"]([^'\"]+)['\"]\s*$",
    re.MULTILINE,
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
TAR_TIMESTAMP = 0


class ReleaseError(RuntimeError):
    """Raised when the source tree cannot produce a trusted release."""


def _regular_file_bytes(path: Path) -> bytes:
    try:
        before = os.lstat(str(path))
    except FileNotFoundError as exc:
        raise ReleaseError("required release file is missing: {}".format(path)) from exc
    if not stat.S_ISREG(before.st_mode):
        raise ReleaseError("required release path is not a regular file: {}".format(path))

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise ReleaseError("cannot open required release file: {}".format(path)) from exc
    try:
        opened = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        )
        if not stat.S_ISREG(opened.st_mode) or opened_identity != before_identity:
            raise ReleaseError("required release file changed while opening: {}".format(path))
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if after_identity != opened_identity:
            raise ReleaseError("required release file changed while reading: {}".format(path))
        data = b"".join(chunks)
        if len(data) != after.st_size:
            raise ReleaseError("required release file has an unstable size: {}".format(path))
        return data
    finally:
        os.close(descriptor)


def _validate_version(tag: str, sources: Dict[str, bytes]) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ReleaseError("version must be a semantic tag such as v0.1.0")
    version = tag[1:]

    try:
        declared_version = sources["VERSION"].decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseError("VERSION must contain an ASCII semantic version") from exc
    if declared_version != version:
        raise ReleaseError(
            "version mismatch: requested {}, VERSION declares {}".format(
                tag, declared_version or "<empty>"
            )
        )

    cli_versions = {
        value.decode("ascii")
        for value in CLI_VERSION_PATTERN.findall(sources["codex-instruct.py"])
    }
    if cli_versions != {version}:
        declared = ", ".join(sorted(cli_versions)) or "<missing>"
        raise ReleaseError(
            "version mismatch: codex-instruct.py declares {} instead of {}".format(
                declared, version
            )
        )

    changelog = sources["CHANGELOG.md"].decode("utf-8", errors="replace")
    heading = re.compile(r"^## \[?{}\]?(?:\s|$)".format(re.escape(version)), re.MULTILINE)
    if not heading.search(changelog):
        raise ReleaseError("CHANGELOG.md has no release heading for {}".format(version))
    return version


def _read_and_validate_sources(repo_root: Path, tag: str) -> Tuple[str, Dict[str, bytes]]:
    sources = {
        relative_path: _regular_file_bytes(repo_root / relative_path)
        for relative_path in ARCHIVE_FILES
    }
    for marker in MIT_MARKERS:
        if marker not in sources["LICENSE"]:
            raise ReleaseError("LICENSE does not contain the complete MIT notice")
    return _validate_version(tag, sources), sources


def _relative_output_path(repo_root: Path, output_dir: Path) -> Optional[Path]:
    try:
        return output_dir.relative_to(repo_root)
    except ValueError:
        return None


def _validate_output_location(repo_root: Path, output_dir: Path) -> None:
    current = Path(output_dir.anchor)
    for part in output_dir.parts[1:]:
        current = current / part
        try:
            current_stat = os.lstat(str(current))
        except FileNotFoundError:
            break
        if stat.S_ISLNK(current_stat.st_mode):
            raise ReleaseError(
                "release output path contains a symbolic-link ancestor: {}".format(
                    current
                )
            )
        if current != output_dir and not stat.S_ISDIR(current_stat.st_mode):
            raise ReleaseError(
                "release output ancestor is not a directory: {}".format(current)
            )

    resolved_output = output_dir.resolve(strict=False)
    git_directory = Path(
        _git_output(
            repo_root,
            ["rev-parse", "--absolute-git-dir"],
            "cannot resolve repository Git directory",
        )
    ).resolve()
    try:
        resolved_output.relative_to(git_directory)
    except ValueError:
        pass
    else:
        raise ReleaseError("release output directory cannot be inside .git")


def _git_output(repo_root: Path, arguments: Sequence[str], failure: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root)] + list(arguments),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ReleaseError("{}: {}".format(failure, exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise ReleaseError("{}: {}".format(failure, detail))
    value = result.stdout.strip()
    if not value:
        raise ReleaseError("{}: git returned no object ID".format(failure))
    return value


def _resolve_source_commit(
    repo_root: Path,
    tag: str,
    source_commit: Optional[str],
) -> str:
    head = _git_output(
        repo_root,
        ["rev-parse", "--verify", "HEAD^{commit}"],
        "cannot resolve repository HEAD",
    )
    if not FULL_COMMIT_PATTERN.fullmatch(head):
        raise ReleaseError("repository HEAD is not a full Git object ID")

    if source_commit is None:
        expected = _git_output(
            repo_root,
            ["rev-parse", "--verify", "refs/tags/{}^{{commit}}".format(tag)],
            "cannot resolve release tag {}".format(tag),
        )
        source_label = "release tag {}".format(tag)
    else:
        if not FULL_COMMIT_PATTERN.fullmatch(source_commit):
            raise ReleaseError("--source-commit must be a full Git commit object ID")
        expected = _git_output(
            repo_root,
            ["rev-parse", "--verify", "{}^{{commit}}".format(source_commit)],
            "cannot resolve --source-commit {}".format(source_commit),
        )
        if expected.lower() != source_commit.lower():
            raise ReleaseError("--source-commit must identify the commit object itself")
        try:
            tag_check = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    "refs/tags/{}".format(tag),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ReleaseError("cannot check release tag: {}".format(exc)) from exc
        if tag_check.returncode not in (0, 1):
            raise ReleaseError("cannot check whether release tag already exists")
        if tag_check.returncode == 0:
            tagged_commit = _git_output(
                repo_root,
                ["rev-parse", "--verify", "refs/tags/{}^{{commit}}".format(tag)],
                "cannot resolve existing release tag {}".format(tag),
            )
            if tagged_commit.lower() != expected.lower():
                raise ReleaseError(
                    "release tag {} already points to {}, not candidate {}".format(
                        tag, tagged_commit, expected
                    )
                )
        source_label = "candidate commit {}".format(source_commit)

    if not FULL_COMMIT_PATTERN.fullmatch(expected):
        raise ReleaseError("resolved source is not a full Git commit object ID")
    if head.lower() != expected.lower():
        raise ReleaseError(
            "HEAD {} does not match {} ({})".format(head, source_label, expected)
        )
    return head.lower()


def _require_clean_repository(repo_root: Path, output_dir: Path) -> None:
    command = [
        "git",
        "-C",
        str(repo_root),
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
    ]
    relative_output = _relative_output_path(repo_root, output_dir)
    if relative_output is not None:
        if relative_output == Path("."):
            raise ReleaseError("release output directory cannot be the repository root")
        if relative_output.parts and relative_output.parts[0] == ".git":
            raise ReleaseError("release output directory cannot be inside .git")
        output_pattern = relative_output.as_posix()
        tracked = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--", output_pattern],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if tracked.returncode != 0:
            detail = tracked.stderr.strip() or "git ls-files failed"
            raise ReleaseError("cannot validate release output directory: {}".format(detail))
        if tracked.stdout.strip():
            raise ReleaseError("release output directory contains tracked source files")
        command.extend(
            [
                ":(exclude,top){}".format(output_pattern),
                ":(exclude,top){}/**".format(output_pattern),
            ]
        )
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.strip() or "git status failed"
        raise ReleaseError("cannot verify clean repository: {}".format(detail))
    if result.stdout.strip():
        raise ReleaseError("repository is dirty; commit or remove all source changes first")


def _archive_mode(relative_path: str) -> int:
    return 0o755 if relative_path == "codex-instruct.py" else 0o644


def _archive_name(tag: str, relative_path: str) -> str:
    return "codex-keysmith-{}/{}".format(tag, relative_path)


def _write_zip(path: Path, tag: str, sources: Dict[str, bytes]) -> None:
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_STORED) as archive:
        for relative_path in sorted(sources):
            info = zipfile.ZipInfo(_archive_name(tag, relative_path), ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (_archive_mode(relative_path) & 0xFFFF) << 16
            archive.writestr(info, sources[relative_path])


def _write_tar_gz(path: Path, tag: str, sources: Dict[str, bytes]) -> None:
    with path.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=raw_output,
            mtime=TAR_TIMESTAMP,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                for relative_path in sorted(sources):
                    data = sources[relative_path]
                    info = tarfile.TarInfo(_archive_name(tag, relative_path))
                    info.size = len(data)
                    info.mtime = TAR_TIMESTAMP
                    info.mode = _archive_mode(relative_path)
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    archive.addfile(info, io.BytesIO(data))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _standalone_script_bytes(source: bytes, license_text: bytes) -> bytes:
    if not source.startswith(b"#!"):
        raise ReleaseError("codex-instruct.py must start with a shebang")
    shebang, separator, body = source.partition(b"\n")
    if not separator:
        raise ReleaseError("codex-instruct.py is missing script content")
    commented_license = b"\n".join(
        b"# " + line if line else b"#" for line in license_text.rstrip(b"\n").splitlines()
    )
    return (
        shebang
        + b"\n#\n# Standalone release asset license notice:\n"
        + commented_license
        + b"\n#\n"
        + body
    )


def _prepare_output_directory(output_dir: Path) -> None:
    try:
        output_stat = os.lstat(str(output_dir))
    except FileNotFoundError:
        output_dir.mkdir(parents=True)
        output_stat = os.lstat(str(output_dir))
    if not stat.S_ISDIR(output_stat.st_mode):
        raise ReleaseError("release output path is not a directory: {}".format(output_dir))


def _validate_output_destinations(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            path_stat = os.lstat(str(path))
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise ReleaseError("release asset destination is not a regular file: {}".format(path))


def _publish_assets_without_overwrite(
    staged_paths: Sequence[Path],
    final_paths: Sequence[Path],
) -> List[Tuple[Path, bytes]]:
    staged_data = [_regular_file_bytes(path) for path in staged_paths]
    destination_exists = []
    for data, destination in zip(staged_data, final_paths):
        try:
            destination_stat = os.lstat(str(destination))
        except FileNotFoundError:
            destination_exists.append(False)
            continue
        if not stat.S_ISREG(destination_stat.st_mode):
            raise ReleaseError(
                "release asset destination is not a regular file: {}".format(
                    destination
                )
            )
        if _regular_file_bytes(destination) != data:
            raise ReleaseError(
                "existing release asset differs; refusing to overwrite: {}".format(
                    destination
                )
            )
        destination_exists.append(True)

    created = []
    try:
        for staged, destination, exists, data in zip(
            staged_paths, final_paths, destination_exists, staged_data
        ):
            if exists:
                staged.unlink()
                continue
            if os.name == "nt":
                os.rename(str(staged), str(destination))
                created.append((destination, data))
            else:
                os.link(str(staged), str(destination), follow_symlinks=False)
                created.append((destination, data))
                staged.unlink()
        for destination, expected_data in zip(final_paths, staged_data):
            if _regular_file_bytes(destination) != expected_data:
                raise ReleaseError(
                    "release asset changed during publication: {}".format(destination)
                )
    except (OSError, ReleaseError) as exc:
        rollback_errors = []
        for destination, expected_data in reversed(created):
            try:
                if _regular_file_bytes(destination) != expected_data:
                    rollback_errors.append(
                        "{} changed after publication; preserved".format(destination)
                    )
                    continue
                destination.unlink()
            except OSError as rollback_exc:
                rollback_errors.append("{}: {}".format(destination, rollback_exc))
            except ReleaseError as rollback_exc:
                rollback_errors.append("{}: {}".format(destination, rollback_exc))
        detail = "cannot publish release assets without overwrite: {}".format(exc)
        if rollback_errors:
            detail += "; rollback failed: {}".format("; ".join(rollback_errors))
        raise ReleaseError(detail) from exc
    return created


def _rollback_published_assets(created: Sequence[Tuple[Path, bytes]]) -> List[str]:
    errors = []
    for destination, expected_data in reversed(created):
        try:
            if _regular_file_bytes(destination) != expected_data:
                errors.append("{} changed after publication; preserved".format(destination))
                continue
            destination.unlink()
        except (OSError, ReleaseError) as exc:
            errors.append("{}: {}".format(destination, exc))
    return errors


def build_release(
    tag: str,
    repo_root: Path,
    output_dir: Path,
    require_clean: bool = True,
    source_commit: Optional[str] = None,
) -> List[Path]:
    """Validate the source tree and write a deterministic release asset set."""
    repo_root = repo_root.resolve()
    output_dir = Path(os.path.abspath(str(output_dir)))
    version, sources = _read_and_validate_sources(repo_root, tag)
    validated_source = _resolve_source_commit(repo_root, tag, source_commit)
    _validate_output_location(repo_root, output_dir)
    if require_clean:
        _require_clean_repository(repo_root, output_dir)
    _prepare_output_directory(output_dir)

    asset_names = (
        "codex-keysmith-{}.zip".format(tag),
        "codex-keysmith-{}.tar.gz".format(tag),
        "codex-instruct-{}.py".format(tag),
    )
    final_paths = [output_dir / name for name in asset_names + ("SHA256SUMS",)]
    _validate_output_destinations(final_paths)
    with tempfile.TemporaryDirectory(prefix=".keysmith-release-", dir=str(output_dir)) as temp:
        staging_dir = Path(temp)
        zip_path = staging_dir / asset_names[0]
        tar_path = staging_dir / asset_names[1]
        script_path = staging_dir / asset_names[2]
        _write_zip(zip_path, tag, sources)
        _write_tar_gz(tar_path, tag, sources)
        script_path.write_bytes(
            _standalone_script_bytes(
                sources["codex-instruct.py"],
                sources["LICENSE"],
            )
        )
        script_path.chmod(0o755)

        checksum_lines = [
            "{}  {}".format(_sha256(staging_dir / name), name)
            for name in sorted(asset_names)
        ]
        checksum_path = staging_dir / "SHA256SUMS"
        checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="ascii")
        for path in (zip_path, tar_path, checksum_path):
            path.chmod(0o644)

        final_version, final_sources = _read_and_validate_sources(repo_root, tag)
        if final_version != version or final_sources != sources:
            raise ReleaseError("release source files changed during the build")
        final_source = _resolve_source_commit(repo_root, tag, source_commit)
        if final_source != validated_source:
            raise ReleaseError("release source commit changed during the build")
        if require_clean:
            _require_clean_repository(repo_root, output_dir)

        created = _publish_assets_without_overwrite(
            (zip_path, tar_path, script_path, checksum_path),
            final_paths,
        )
        try:
            published_version, published_sources = _read_and_validate_sources(
                repo_root,
                tag,
            )
            if published_version != version or published_sources != sources:
                raise ReleaseError("release source files changed during publication")
            published_source = _resolve_source_commit(
                repo_root,
                tag,
                source_commit,
            )
            if published_source != validated_source:
                raise ReleaseError("release source commit changed during publication")
            if require_clean:
                _require_clean_repository(repo_root, output_dir)
        except (OSError, ReleaseError) as exc:
            rollback_errors = _rollback_published_assets(created)
            detail = "release verification failed after publication: {}".format(exc)
            if rollback_errors:
                detail += "; rollback failed: {}".format("; ".join(rollback_errors))
            raise ReleaseError(detail) from exc

    print(
        "built codex-keysmith {} ({}) from {}".format(
            tag, version, validated_source
        )
    )
    for path in final_paths:
        print("{}  {}".format(_sha256(path), path))
    return final_paths


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="release tag, for example v0.1.0")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="asset output directory (default: ./dist)",
    )
    parser.add_argument(
        "--source-commit",
        help=(
            "full pre-tag candidate commit; omit for a formal build that requires "
            "refs/tags/VERSION to point at HEAD"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        build_release(
            args.version,
            args.repo_root,
            args.output_dir,
            source_commit=args.source_commit,
        )
    except ReleaseError as exc:
        print("release build failed: {}".format(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("release build failed: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

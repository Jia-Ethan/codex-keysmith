#!/usr/bin/env python3
"""Build deterministic local release assets for codex-keysmith."""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

ARCHIVE_FILES = (
    "CHANGELOG.md",
    "CODE_SIGNING_POLICY.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "PRIVACY.md",
    "README.en.md",
    "README.md",
    "SECURITY.md",
    "VERSION",
    "codex-instruct.py",
    "docs/agent-install.md",
    "docs/assets/readme/codex-keysmith-preview.png",
    "docs/hooks-transactions.md",
    "docs/reference.md",
    "docs/v0.3-scenario-deployment-design.md",
    "examples/gpt-unrestricted.md",
)

SCENARIO_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SCENARIO_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
SCENARIO_PYTHON_RUNTIME_PATTERN = re.compile(
    r">=(\d+)\.(\d+)(?:\.(\d+))?,<(\d+)\.(\d+)(?:\.(\d+))?"
)
SCENARIO_VERSION_CLAUSE_PATTERN = re.compile(r"\s*(>=|>|<=|<|==)\s*(\d+(?:\.\d+)*)\s*")
SCENARIO_PROBE_SHELLS = {
    "sh",
    "bash",
    "zsh",
    "csh",
    "tcsh",
    "fish",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
}
SCENARIO_METADATA_FIELDS = {
    "schema_version",
    "id",
    "version",
    "display_name",
    "task",
    "validator",
    "verify",
    "platforms",
    "runtime",
    "requires",
    "checksums",
}


def _validate_scenario_archive_path(relative_path: str) -> None:
    if relative_path == "scenarios" or not relative_path.startswith("scenarios/"):
        raise ReleaseError(
            "scenario archive contains an invalid tree path: {}".format(relative_path)
        )
    if "\\" in relative_path or any(
        ord(character) < 32 or ord(character) == 127 for character in relative_path
    ):
        raise ReleaseError(
            "scenario archive contains a cross-platform unsafe path: {}".format(relative_path)
        )

    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update("COM{}".format(index) for index in range(1, 10))
    reserved.update("LPT{}".format(index) for index in range(1, 10))
    for component in relative_path.split("/"):
        if (
            component in {"", ".", ".."}
            or component.endswith((" ", "."))
            or any(character in component for character in '<>:"|?*')
            or component.split(".", 1)[0].upper() in reserved
        ):
            raise ReleaseError(
                "scenario archive contains a cross-platform unsafe path: {}".format(relative_path)
            )


def _scenario_archive_files(repo_root: Path) -> Tuple[str, ...]:
    scenario_root = repo_root / "scenarios"
    try:
        root_stat = os.lstat(str(scenario_root))
    except FileNotFoundError:
        return ()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ReleaseError("scenario archive root is not a directory: {}".format(scenario_root))
    files = []
    seen_casefold = set()
    for path in sorted(scenario_root.rglob("*")):
        file_stat = os.lstat(str(path))
        if stat.S_ISDIR(file_stat.st_mode):
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            raise ReleaseError("scenario archive member is not a regular file: {}".format(path))
        relative_parts = path.relative_to(scenario_root).parts
        if "__pycache__" in relative_parts or path.name.endswith((".pyc", ".pyo")):
            continue
        relative_path = path.relative_to(repo_root).as_posix()
        _validate_scenario_archive_path(relative_path)
        folded = relative_path.casefold()
        if folded in seen_casefold:
            raise ReleaseError(
                "scenario archive members collide case-insensitively: {}".format(relative_path)
            )
        seen_casefold.add(folded)
        files.append(relative_path)
    return tuple(files)


def _scenario_safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseError("{} must be a non-empty relative path".format(label))
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ReleaseError("{} must use portable forward-slash paths".format(label))
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise ReleaseError("{} is not a normalized relative path: {}".format(label, value))
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseError("{} contains an unsafe path component: {}".format(label, value))
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update("COM{}".format(index) for index in range(1, 10))
    reserved.update("LPT{}".format(index) for index in range(1, 10))
    for part in path.parts:
        if (
            part.split(".", 1)[0].upper() in reserved
            or any(character in part for character in '<>:"|?*')
            or part.endswith((".", " "))
        ):
            raise ReleaseError("{} uses a reserved path component: {}".format(label, value))
    return value


def _validate_scenario_version_constraint(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseError("{} is required".format(label))
    clauses = value.split(",")
    if not clauses or not all(
        SCENARIO_VERSION_CLAUSE_PATTERN.fullmatch(clause) for clause in clauses
    ):
        raise ReleaseError("{} uses an unsupported version constraint: {}".format(label, value))
    return value


def _validate_scenario_requires(value: object, scenario_id: str) -> List[Dict[str, object]]:
    if not isinstance(value, list):
        raise ReleaseError("scenario requires must be a list: {}".format(scenario_id))
    result = []
    names = set()
    for index, requirement in enumerate(value):
        label = "scenario {} requires[{}]".format(scenario_id, index)
        if not isinstance(requirement, dict) or set(requirement) != {
            "name",
            "type",
            "version",
            "probe",
        }:
            raise ReleaseError("{} must contain name, type, version, and probe".format(label))
        name = requirement["name"]
        kind = requirement["type"]
        version = requirement["version"]
        probe = requirement["probe"]
        if not isinstance(name, str) or not name or name in names:
            raise ReleaseError("{}.name is invalid or duplicated".format(label))
        if not isinstance(kind, str) or kind not in {"command", "python-module"}:
            raise ReleaseError("{}.type is unsupported".format(label))
        _validate_scenario_version_constraint(version, "{}.version".format(label))
        if (
            not isinstance(probe, list)
            or not probe
            or not all(isinstance(item, str) and item for item in probe)
        ):
            raise ReleaseError("{}.probe must be a non-empty argv list".format(label))
        if Path(probe[0]).name.lower() in SCENARIO_PROBE_SHELLS:
            raise ReleaseError("{}.probe must not invoke a shell".format(label))
        names.add(name)
        result.append(dict(requirement))
    return result


def _scenario_source_digest(files: Dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative, sha256 in sorted(files.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _bundle_json_bytes(value: Dict[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def scenario_bundle_asset_name(tag: str) -> str:
    return "codex-keysmith-scenarios-{}.bundle".format(tag)


def _build_scenario_index(members: Dict[str, bytes], version: str) -> Dict[str, object]:
    packages: Dict[str, Dict[str, bytes]] = {}
    for relative_path, data in members.items():
        if not relative_path.startswith("scenarios/"):
            continue
        _validate_scenario_archive_path(relative_path)
        rest = relative_path[len("scenarios/") :]
        if not rest or "/" not in rest:
            raise ReleaseError(
                "scenario bundle member is missing a package path: {}".format(relative_path)
            )
        scenario_id, relative = rest.split("/", 1)
        if not SCENARIO_ID_PATTERN.fullmatch(scenario_id) or not relative:
            raise ReleaseError(
                "scenario bundle member has an invalid package path: {}".format(relative_path)
            )
        _scenario_safe_relative(relative, "scenario member")
        packages.setdefault(scenario_id, {})[relative] = data
    if not packages:
        raise ReleaseError("scenario bundle does not contain any packages")

    scenarios: Dict[str, object] = {}
    for scenario_id in sorted(packages):
        files = packages[scenario_id]
        folded_members = set()
        for relative in files:
            folded = relative.casefold()
            if folded in folded_members:
                raise ReleaseError(
                    "scenario members collide case-insensitively: {}/{}".format(
                        scenario_id, relative
                    )
                )
            folded_members.add(folded)
        if "scenario.json" not in files:
            raise ReleaseError("scenario package is missing scenario.json: {}".format(scenario_id))
        try:
            metadata = json.loads(files["scenario.json"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseError("scenario.json is invalid: {}".format(scenario_id)) from exc
        if not isinstance(metadata, dict) or set(metadata) != SCENARIO_METADATA_FIELDS:
            raise ReleaseError("scenario.json root fields are invalid: {}".format(scenario_id))
        if metadata["schema_version"] != 1 or metadata["id"] != scenario_id:
            raise ReleaseError(
                "scenario.json schema or id does not match the package: {}".format(scenario_id)
            )
        if not isinstance(metadata["version"], str) or not SCENARIO_SEMVER_PATTERN.fullmatch(
            metadata["version"]
        ):
            raise ReleaseError("scenario version must be semantic: {}".format(scenario_id))
        if not isinstance(metadata["display_name"], str) or not metadata["display_name"]:
            raise ReleaseError("scenario display_name is required: {}".format(scenario_id))
        task = _scenario_safe_relative(metadata["task"], "scenario task")
        validator = _scenario_safe_relative(metadata["validator"], "scenario validator")
        verify = _scenario_safe_relative(metadata["verify"], "scenario verify")
        platforms = metadata["platforms"]
        if (
            not isinstance(platforms, list)
            or not platforms
            or not all(
                isinstance(item, str) and item in {"darwin", "linux", "win32"} for item in platforms
            )
            or len(platforms) != len(set(platforms))
        ):
            raise ReleaseError("scenario platforms are invalid: {}".format(scenario_id))
        runtime = metadata["runtime"]
        if not isinstance(runtime, dict) or set(runtime) != {"python"}:
            raise ReleaseError("scenario runtime must define only python: {}".format(scenario_id))
        python_runtime = runtime["python"]
        if not isinstance(python_runtime, str) or not SCENARIO_PYTHON_RUNTIME_PATTERN.fullmatch(
            python_runtime
        ):
            raise ReleaseError("scenario Python runtime is invalid: {}".format(scenario_id))
        requires = _validate_scenario_requires(metadata["requires"], scenario_id)
        deploy_files = {
            relative: data
            for relative, data in files.items()
            if not relative.startswith("fixtures/")
        }
        file_hashes = {
            relative: hashlib.sha256(data).hexdigest() for relative, data in deploy_files.items()
        }
        checksums = metadata.get("checksums")
        if not isinstance(checksums, dict):
            raise ReleaseError("scenario checksums are invalid: {}".format(scenario_id))
        expected = set(deploy_files) - {"scenario.json"}
        if set(checksums) != expected:
            raise ReleaseError(
                "scenario checksums do not cover deployed files: {}".format(scenario_id)
            )
        for required in (task, validator, verify):
            if required not in deploy_files:
                raise ReleaseError(
                    "scenario entrypoint is not a deployed regular file: {}/{}".format(
                        scenario_id, required
                    )
                )
        for relative, expected_hash in checksums.items():
            if not isinstance(expected_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_hash
            ):
                raise ReleaseError(
                    "scenario checksum is invalid: {}/{}".format(scenario_id, relative)
                )
            if file_hashes.get(relative) != expected_hash:
                raise ReleaseError(
                    "scenario checksum mismatch: {}/{}".format(scenario_id, relative)
                )
        scenarios[scenario_id] = {
            "display_name": metadata["display_name"],
            "id": metadata["id"],
            "platforms": platforms,
            "requires": requires,
            "runtime": {"python": python_runtime},
            "source_digest": _scenario_source_digest(file_hashes),
            "version": metadata["version"],
        }
    return {
        "schema_version": 1,
        "scenarios": scenarios,
        "tool_version": version,
    }


def _scenario_bundle_members(
    sources: Dict[str, bytes],
    version: str,
) -> Dict[str, bytes]:
    members = {
        relative_path: data
        for relative_path, data in sources.items()
        if relative_path.startswith("scenarios/")
    }
    if not members:
        raise ReleaseError("release is missing scenario library files")
    members["index.json"] = _bundle_json_bytes(_build_scenario_index(members, version))
    return members


def _write_scenario_bundle_zip(path: Path, members: Dict[str, bytes]) -> None:
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_STORED) as archive:
        for relative_path in sorted(members):
            info = zipfile.ZipInfo(relative_path, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, members[relative_path])


def write_scenario_bundle(
    repo_root: Path,
    destination: Path,
    version: Optional[str] = None,
) -> Path:
    """Write a bundle if its destination is absent or already byte-identical."""
    repo_root = repo_root.resolve()
    if version is None:
        try:
            version = _regular_file_bytes(repo_root / "VERSION").decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ReleaseError("VERSION must contain an ASCII semantic version") from exc
    if not isinstance(version, str) or not SCENARIO_SEMVER_PATTERN.fullmatch(version):
        raise ReleaseError("scenario bundle version must be semantic")
    sources = {
        relative_path: _regular_file_bytes(repo_root / relative_path)
        for relative_path in _scenario_archive_files(repo_root)
    }
    members = _scenario_bundle_members(sources, version)
    destination = Path(os.path.abspath(str(destination)))
    _validate_output_location(repo_root, destination.parent)
    relative_destination = _relative_output_path(repo_root, destination)
    if relative_destination is not None:
        if relative_destination == Path(".") or relative_destination.parts[0] == ".git":
            raise ReleaseError("scenario bundle destination cannot be inside .git")
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "ls-files",
                "--error-unmatch",
                "--",
                relative_destination.as_posix(),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if tracked.returncode == 0:
            raise ReleaseError(
                "scenario bundle destination is a tracked source file: {}".format(destination)
            )
        if tracked.returncode not in {1, 128}:
            detail = tracked.stderr.strip() or "git ls-files failed"
            raise ReleaseError("cannot validate scenario bundle destination: {}".format(detail))
    _prepare_output_directory(destination.parent)
    _validate_output_destinations((destination,))
    with tempfile.TemporaryDirectory(
        prefix=".keysmith-scenario-bundle-",
        dir=str(destination.parent),
    ) as temp:
        staged = Path(temp) / destination.name
        _write_scenario_bundle_zip(staged, members)
        _publish_assets_without_overwrite((staged,), (destination,))
    return destination


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


def _archive_files(tag: str, repo_root: Optional[Path] = None) -> Tuple[str, ...]:
    files = ARCHIVE_FILES + ("docs/releases/{}.md".format(tag),)
    if repo_root is not None:
        files += _scenario_archive_files(repo_root)
    return files


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
        value.decode("ascii") for value in CLI_VERSION_PATTERN.findall(sources["codex-instruct.py"])
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
    archive_files = ARCHIVE_FILES + _scenario_archive_files(repo_root)
    sources = {
        relative_path: _regular_file_bytes(repo_root / relative_path)
        for relative_path in archive_files
    }
    for marker in MIT_MARKERS:
        if marker not in sources["LICENSE"]:
            raise ReleaseError("LICENSE does not contain the complete MIT notice")
    version = _validate_version(tag, sources)
    release_notes = "docs/releases/{}.md".format(tag)
    sources[release_notes] = _regular_file_bytes(repo_root / release_notes)
    return version, sources


def _tracked_gui_sources(
    repo_root: Path,
    source_commit: str,
) -> Tuple[Dict[str, bytes], Dict[str, int]]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                source_commit,
                "--",
                "gui",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ReleaseError("cannot enumerate tracked GUI sources: {}".format(exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(
            "cannot enumerate tracked GUI sources: {}".format(detail or "git ls-tree failed")
        )

    sources = {}
    modes = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3:
            raise ReleaseError("validated source commit returned malformed GUI tree data")
        raw_mode, raw_type, raw_object = fields
        try:
            relative_path = raw_path.decode("utf-8")
            mode = int(raw_mode, 8)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseError(
                "validated source commit contains an unsupported GUI path or mode"
            ) from exc
        _validate_gui_archive_path(relative_path)
        if raw_type != b"blob" or raw_mode not in {b"100644", b"100755"}:
            raise ReleaseError(
                "tracked GUI entry is not a regular file: {} (mode {}, type {})".format(
                    relative_path,
                    raw_mode.decode("ascii", errors="replace"),
                    raw_type.decode("ascii", errors="replace"),
                )
            )
        if relative_path in sources:
            raise ReleaseError(
                "validated source commit contains a duplicate GUI path: {}".format(relative_path)
            )
        try:
            blob = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "cat-file",
                    "blob",
                    raw_object.decode("ascii"),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise ReleaseError(
                "cannot read tracked GUI file {}: {}".format(relative_path, exc)
            ) from exc
        if blob.returncode != 0:
            detail = blob.stderr.decode("utf-8", errors="replace").strip()
            raise ReleaseError(
                "cannot read tracked GUI file {}: {}".format(
                    relative_path,
                    detail or "git cat-file failed",
                )
            )
        sources[relative_path] = blob.stdout
        modes[relative_path] = mode

    if not sources:
        raise ReleaseError("validated source commit contains no tracked GUI files")
    return sources, modes


def _validate_gui_archive_path(relative_path: str) -> None:
    if relative_path == "gui" or not relative_path.startswith("gui/"):
        raise ReleaseError(
            "validated source commit contains an invalid GUI tree path: {}".format(relative_path)
        )
    if "\\" in relative_path or any(
        ord(character) < 32 or ord(character) == 127 for character in relative_path
    ):
        raise ReleaseError(
            "validated source commit contains a cross-platform unsafe GUI path: {}".format(
                relative_path
            )
        )

    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update("COM{}".format(index) for index in range(1, 10))
    reserved.update("LPT{}".format(index) for index in range(1, 10))
    for component in relative_path.split("/"):
        if (
            component in {"", ".", ".."}
            or component.endswith((" ", "."))
            or any(character in component for character in '<>:"|?*')
            or component.split(".", 1)[0].upper() in reserved
        ):
            raise ReleaseError(
                "validated source commit contains a cross-platform unsafe GUI path: {}".format(
                    relative_path
                )
            )


def _read_release_sources(
    repo_root: Path,
    tag: str,
    source_commit: str,
) -> Tuple[str, Dict[str, bytes], Dict[str, int]]:
    version, sources = _read_and_validate_sources(repo_root, tag)
    gui_sources, gui_modes = _tracked_gui_sources(repo_root, source_commit)
    collisions = set(sources).intersection(gui_sources)
    if collisions:
        raise ReleaseError(
            "GUI sources collide with fixed release paths: {}".format(", ".join(sorted(collisions)))
        )
    sources.update(gui_sources)
    modes = {relative_path: _archive_mode(relative_path) for relative_path in sources}
    modes.update(gui_modes)
    return version, sources, modes


def _validate_gui_worktree_matches_commit(
    repo_root: Path,
    sources: Dict[str, bytes],
) -> None:
    for relative_path, expected in sources.items():
        if not relative_path.startswith("gui/"):
            continue
        if _regular_file_bytes(repo_root / relative_path) != expected:
            raise ReleaseError(
                "working-tree GUI file differs from validated source commit: {}".format(
                    relative_path
                )
            )


def _validate_sources_match_commit(
    repo_root: Path,
    source_commit: str,
    sources: Dict[str, bytes],
) -> None:
    for relative_path in sources:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "cat-file",
                    "blob",
                    "{}:{}".format(source_commit, relative_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ReleaseError(
                "cannot read validated source commit file {}: {}".format(
                    relative_path,
                    exc,
                )
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ReleaseError(
                "cannot read validated source commit file {}: {}".format(
                    relative_path,
                    detail or "git cat-file failed",
                )
            )
        if result.stdout != sources[relative_path]:
            raise ReleaseError(
                "working-tree release file differs from validated source commit: {}".format(
                    relative_path
                )
            )


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
                "release output path contains a symbolic-link ancestor: {}".format(current)
            )
        if current != output_dir and not stat.S_ISDIR(current_stat.st_mode):
            raise ReleaseError("release output ancestor is not a directory: {}".format(current))

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


def _git_lines(repo_root: Path, arguments: Sequence[str], failure: str) -> List[str]:
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
    return [line for line in result.stdout.splitlines() if line.strip()]


def _remote_release_tag_commit(repo_root: Path, remote: str, tag: str) -> Optional[str]:
    tag_ref = "refs/tags/{}".format(tag)
    peeled_ref = "{}^{{}}".format(tag_ref)
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "ls-remote",
                "--tags",
                remote,
                tag_ref,
                peeled_ref,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReleaseError(
            "cannot verify remote release tags from {}: timed out".format(remote)
        ) from exc
    except OSError as exc:
        raise ReleaseError(
            "cannot verify remote release tags from {}: {}".format(remote, exc)
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise ReleaseError("cannot verify remote release tags from {}: {}".format(remote, detail))
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    references = {}
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) != 2 or not FULL_COMMIT_PATTERN.fullmatch(parts[0]):
            raise ReleaseError("remote {} returned malformed release tag metadata".format(remote))
        object_id, reference = parts
        if reference not in {tag_ref, peeled_ref}:
            continue
        previous = references.get(reference)
        if previous is not None and previous.lower() != object_id.lower():
            raise ReleaseError("remote {} returned conflicting release tag metadata".format(remote))
        references[reference] = object_id
    if not references:
        return None
    if tag_ref not in references:
        raise ReleaseError(
            "remote {} returned a peeled release tag without its tag object".format(remote)
        )
    return references.get(peeled_ref, references[tag_ref])


def _require_complete_git_checkout(repo_root: Path) -> None:
    _git_output(
        repo_root,
        ["rev-parse", "--verify", "HEAD^{commit}"],
        "cannot resolve repository HEAD",
    )
    shallow = _git_output(
        repo_root,
        ["rev-parse", "--is-shallow-repository"],
        "cannot determine whether the repository is shallow",
    )
    if shallow not in {"true", "false"}:
        raise ReleaseError("Git returned an invalid shallow-repository state")
    if shallow == "true":
        raise ReleaseError("release builds require a complete Git checkout with all tags")

    config_checks = (
        ["config", "--local", "--get", "extensions.partialClone"],
        ["config", "--local", "--get-regexp", r"^remote\..*\.promisor$"],
    )
    for arguments in config_checks:
        try:
            configured = subprocess.run(
                ["git", "-C", str(repo_root)] + arguments,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ReleaseError(
                "cannot determine whether the repository is partial: {}".format(exc)
            ) from exc
        if configured.returncode not in (0, 1):
            detail = configured.stderr.strip() or "git config failed"
            raise ReleaseError(
                "cannot determine whether the repository is partial: {}".format(detail)
            )
        if configured.returncode == 0 and configured.stdout.strip():
            raise ReleaseError("release builds reject partial or promisor Git checkouts")

    try:
        object_check = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-list",
                "--objects",
                "--no-object-names",
                "--missing=print",
                "--all",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ReleaseError(
            "cannot verify complete Git object availability: {}".format(exc)
        ) from exc
    if object_check.returncode != 0:
        detail = object_check.stderr.strip() or "git rev-list failed"
        raise ReleaseError("cannot verify complete Git object availability: {}".format(detail))
    if any(line.startswith("?") for line in object_check.stdout.splitlines()):
        raise ReleaseError("release checkout is missing reachable Git objects")


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
        local_tag_commit = expected
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
        local_tag_commit = None
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
            local_tag_commit = tagged_commit
        source_label = "candidate commit {}".format(source_commit)

    remotes = _git_lines(
        repo_root,
        ["remote"],
        "cannot enumerate repository remotes",
    )
    remote_tag_commits = []
    for remote in remotes:
        remote_commit = _remote_release_tag_commit(repo_root, remote, tag)
        if remote_commit is None:
            if source_commit is None:
                raise ReleaseError(
                    "formal release tag {} is missing from remote {}".format(tag, remote)
                )
            continue
        remote_tag_commits.append((remote, remote_commit))
        if remote_commit.lower() != expected.lower():
            label = "candidate" if source_commit is not None else "formal source"
            raise ReleaseError(
                "remote release tag {} on {} points to {}, not {} {}".format(
                    tag, remote, remote_commit, label, expected
                )
            )
        if local_tag_commit is not None and remote_commit.lower() != local_tag_commit.lower():
            raise ReleaseError("local and remote release tags disagree about {}".format(tag))
    if len({commit.lower() for _remote, commit in remote_tag_commits}) > 1:
        raise ReleaseError("repository remotes disagree about release tag {}".format(tag))

    if not FULL_COMMIT_PATTERN.fullmatch(expected):
        raise ReleaseError("resolved source is not a full Git commit object ID")
    if head.lower() != expected.lower():
        raise ReleaseError("HEAD {} does not match {} ({})".format(head, source_label, expected))
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


def _write_zip(
    path: Path,
    tag: str,
    sources: Dict[str, bytes],
    modes: Dict[str, int],
) -> None:
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_STORED) as archive:
        for relative_path in sorted(sources):
            info = zipfile.ZipInfo(_archive_name(tag, relative_path), ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (modes[relative_path] & 0xFFFF) << 16
            archive.writestr(info, sources[relative_path])


def _write_tar_gz(
    path: Path,
    tag: str,
    sources: Dict[str, bytes],
    modes: Dict[str, int],
) -> None:
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
                    info.mode = modes[relative_path]
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
                "release asset destination is not a regular file: {}".format(destination)
            )
        if _regular_file_bytes(destination) != data:
            raise ReleaseError(
                "existing release asset differs; refusing to overwrite: {}".format(destination)
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
    # Preserve the public validation order: reject malformed tags and version
    # drift before consulting Git refs for the selected source commit.
    _read_and_validate_sources(repo_root, tag)
    _require_complete_git_checkout(repo_root)
    validated_source = _resolve_source_commit(repo_root, tag, source_commit)
    version, sources, source_modes = _read_release_sources(
        repo_root,
        tag,
        validated_source,
    )
    _validate_sources_match_commit(repo_root, validated_source, sources)
    _validate_gui_worktree_matches_commit(repo_root, sources)
    _validate_output_location(repo_root, output_dir)
    if require_clean:
        _require_clean_repository(repo_root, output_dir)
    _prepare_output_directory(output_dir)

    asset_names = (
        "codex-keysmith-{}.zip".format(tag),
        "codex-keysmith-{}.tar.gz".format(tag),
        "codex-instruct-{}.py".format(tag),
        scenario_bundle_asset_name(tag),
    )
    final_paths = [output_dir / name for name in asset_names + ("SHA256SUMS",)]
    _validate_output_destinations(final_paths)
    with tempfile.TemporaryDirectory(prefix=".keysmith-release-", dir=str(output_dir)) as temp:
        staging_dir = Path(temp)
        zip_path = staging_dir / asset_names[0]
        tar_path = staging_dir / asset_names[1]
        script_path = staging_dir / asset_names[2]
        bundle_path = staging_dir / asset_names[3]
        _write_zip(zip_path, tag, sources, source_modes)
        _write_tar_gz(tar_path, tag, sources, source_modes)
        script_path.write_bytes(
            _standalone_script_bytes(
                sources["codex-instruct.py"],
                sources["LICENSE"],
            )
        )
        script_path.chmod(0o755)
        _write_scenario_bundle_zip(
            bundle_path,
            _scenario_bundle_members(sources, version),
        )

        checksum_lines = [
            "{}  {}".format(_sha256(staging_dir / name), name) for name in sorted(asset_names)
        ]
        checksum_path = staging_dir / "SHA256SUMS"
        checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="ascii")
        for path in (zip_path, tar_path, bundle_path, checksum_path):
            path.chmod(0o644)

        final_source = _resolve_source_commit(repo_root, tag, source_commit)
        if final_source != validated_source:
            raise ReleaseError("release source commit changed during the build")
        final_version, final_sources, final_modes = _read_release_sources(
            repo_root,
            tag,
            final_source,
        )
        if final_version != version or final_sources != sources or final_modes != source_modes:
            raise ReleaseError("release source files changed during the build")
        _validate_sources_match_commit(repo_root, final_source, final_sources)
        _validate_gui_worktree_matches_commit(repo_root, final_sources)
        if require_clean:
            _require_clean_repository(repo_root, output_dir)

        created = _publish_assets_without_overwrite(
            (zip_path, tar_path, script_path, bundle_path, checksum_path),
            final_paths,
        )
        try:
            published_source = _resolve_source_commit(
                repo_root,
                tag,
                source_commit,
            )
            if published_source != validated_source:
                raise ReleaseError("release source commit changed during publication")
            published_version, published_sources, published_modes = _read_release_sources(
                repo_root,
                tag,
                published_source,
            )
            if (
                published_version != version
                or published_sources != sources
                or published_modes != source_modes
            ):
                raise ReleaseError("release source files changed during publication")
            _validate_sources_match_commit(
                repo_root,
                published_source,
                published_sources,
            )
            _validate_gui_worktree_matches_commit(repo_root, published_sources)
            if require_clean:
                _require_clean_repository(repo_root, output_dir)
        except (OSError, ReleaseError) as exc:
            rollback_errors = _rollback_published_assets(created)
            detail = "release verification failed after publication: {}".format(exc)
            if rollback_errors:
                detail += "; rollback failed: {}".format("; ".join(rollback_errors))
            raise ReleaseError(detail) from exc

    print("built codex-keysmith {} ({}) from {}".format(tag, version, validated_source))
    for path in final_paths:
        print("{}  {}".format(_sha256(path), path))
    return final_paths


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help="release tag, for example v0.1.0",
    )
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
    parser.add_argument(
        "--write-scenario-bundle",
        type=Path,
        help="write only the sealed scenarios.bundle and exit",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        if args.write_scenario_bundle is not None:
            if args.source_commit:
                raise ReleaseError("--write-scenario-bundle does not accept --source-commit")
            version = None
            if args.version:
                if not args.version.startswith("v"):
                    raise ReleaseError("version must be a semantic tag such as v0.1.0")
                version = args.version[1:]
            destination = write_scenario_bundle(
                args.repo_root,
                args.write_scenario_bundle,
                version=version,
            )
            print("{}  {}".format(_sha256(destination), destination.name))
            return 0
        if args.version is None:
            raise ReleaseError("version must be a semantic tag such as v0.1.0")
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

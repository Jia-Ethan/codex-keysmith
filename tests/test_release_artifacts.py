import hashlib
import importlib.util
import json
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

from scripts import package_desktop_prerelease as desktop_prerelease

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO_ROOT / "scripts" / "build_release.py"
TAG = "v0.3.6"
VERSION = "0.3.6"
REQUIRED_ARCHIVE_FILES = {
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
    "docs/releases/v0.3.6.md",
    "examples/gpt-unrestricted.md",
    "examples/gpt-contract.md",
    "scripts/run_scenario_bank.py",
    "gui/README.md",
    "gui/package.json",
    "gui/scripts/build-sidecar.mjs",
    "gui/src-tauri/icons/Square44x44Logo.png",
    "gui/src-tauri/icons/icon.ico",
    "gui/src-tauri/tauri.windows.conf.json",
}
REQUIRED_SCENARIO_FILES = {
    "scenarios/example_fixture/scenario.json",
    "scenarios/example_fixture/task.md",
    "scenarios/example_fixture/validator.py",
    "scenarios/example_fixture/verify.py",
    "scenarios/example_fixture/data/input.json",
    "scenarios/example_fixture/fixtures/positive/output.json",
    "scenarios/example_fixture/fixtures/negative/output.json",
    "scenarios/example_fixture/fixtures/tampered/input.json",
    "scenarios/example_fixture/fixtures/tampered/output.json",
    "scenarios/aiml_toxigen/scenario.json",
    "scenarios/aiml_toxigen/task.md",
    "scenarios/aiml_toxigen/validator.py",
    "scenarios/aiml_toxigen/verify.py",
    "scenarios/aiml_toxigen/data/input.json",
    "scenarios/aiml_toxigen/data/sample_01.json",
    "scenarios/aiml_toxigen/data/sample_02.json",
    "scenarios/aiml_toxigen/data/sample_03.json",
    "scenarios/aiml_toxigen/fixtures/positive/output.json",
    "scenarios/aiml_toxigen/fixtures/negative/output.json",
    "scenarios/aiml_toxigen/fixtures/tampered/input.json",
    "scenarios/aiml_toxigen/fixtures/tampered/output.json",
    "scenarios/chem_rdkit/scenario.json",
    "scenarios/chem_rdkit/task.md",
    "scenarios/chem_rdkit/validator.py",
    "scenarios/chem_rdkit/verify.py",
    "scenarios/chem_rdkit/data/input.json",
    "scenarios/chem_rdkit/data/sample_01.json",
    "scenarios/chem_rdkit/data/sample_02.json",
    "scenarios/chem_rdkit/data/sample_03.json",
    "scenarios/chem_rdkit/fixtures/positive/output.json",
    "scenarios/chem_rdkit/fixtures/negative/output.json",
    "scenarios/chem_rdkit/fixtures/tampered/input.json",
    "scenarios/chem_rdkit/fixtures/tampered/output.json",
    "scenarios/cyber_keystone/scenario.json",
    "scenarios/cyber_keystone/task.md",
    "scenarios/cyber_keystone/validator.py",
    "scenarios/cyber_keystone/verify.py",
    "scenarios/cyber_keystone/data/input.json",
    "scenarios/cyber_keystone/data/sample_01.json",
    "scenarios/cyber_keystone/data/sample_02.json",
    "scenarios/cyber_keystone/data/sample_03.json",
    "scenarios/cyber_keystone/fixtures/positive/output.json",
    "scenarios/cyber_keystone/fixtures/negative/output.json",
    "scenarios/cyber_keystone/fixtures/tampered/input.json",
    "scenarios/cyber_keystone/fixtures/tampered/output.json",
}
FIXTURE_GUI_FILES = {
    "gui/README.md": b"# GUI fixture\n",
    "gui/package.json": b'{"name":"codex-keysmith-gui","version":"0.3.6"}\n',
    "gui/scripts/build-sidecar.mjs": b"#!/usr/bin/env node\n",
    "gui/src-tauri/icons/Square44x44Logo.png": b"fixture PNG\n",
    "gui/src-tauri/icons/icon.ico": b"fixture ICO\n",
    "gui/src-tauri/tauri.windows.conf.json": b'{"bundle":{"targets":["nsis"]}}\n',
}
WINDOWS_POLICY_FILES = (
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/hooks-transactions.md",
    "docs/reference.md",
    "docs/releases/v0.3.6.md",
)


@pytest.fixture(scope="module")
def release_builder():
    spec = importlib.util.spec_from_file_location("release_builder", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(command, cwd):
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _make_release_repo(tmp_path, release_builder, create_tag=True):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    source_bytes = {}
    for relative_path in release_builder._archive_files(TAG):
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "VERSION":
            data = (VERSION + "\n").encode("ascii")
        elif relative_path == "codex-instruct.py":
            data = ('#!/usr/bin/env python3\n__version__ = "{}"\n'.format(VERSION)).encode("ascii")
        elif relative_path == "CHANGELOG.md":
            data = ("# Changelog\n\n## [{}] - 2026-07-18\n\n- Release.\n".format(VERSION)).encode(
                "ascii"
            )
        elif relative_path == "LICENSE":
            data = (REPO_ROOT / "LICENSE").read_bytes()
        else:
            data = ("fixture for {}\n".format(relative_path)).encode("utf-8")
        path.write_bytes(data)
        source_bytes[relative_path] = data

    for relative_path, data in FIXTURE_GUI_FILES.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if relative_path.endswith(".mjs"):
            path.chmod(0o755)
        source_bytes[relative_path] = data

    for relative_path in REQUIRED_SCENARIO_FILES:
        data = (REPO_ROOT / relative_path).read_bytes()
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        source_bytes[relative_path] = data

    (repo / ".gitattributes").write_bytes((REPO_ROOT / ".gitattributes").read_bytes())

    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.name", "Release Test"], repo)
    _run(["git", "config", "user.email", "release-test@example.invalid"], repo)
    _run(["git", "config", "core.autocrlf", "false"], repo)
    _run(["git", "add", "."], repo)
    _run(["git", "update-index", "--chmod=+x", "gui/scripts/build-sidecar.mjs"], repo)
    _run(["git", "commit", "-qm", "release fixture"], repo)
    if create_tag:
        _run(["git", "tag", TAG], repo)
    return repo, source_bytes


def _head_commit(repo):
    return _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset_hashes(output_dir):
    return {
        path.name: _file_sha256(path) for path in sorted(output_dir.iterdir()) if path.is_file()
    }


def test_repository_version_metadata_is_release_state_neutral():
    version = (REPO_ROOT / "VERSION").read_text(encoding="ascii").strip()
    script = (REPO_ROOT / "codex-instruct.py").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    english_readme = (REPO_ROOT / "README.en.md").read_text(encoding="utf-8")

    assert version == VERSION
    assert '__version__ = "{}"'.format(VERSION) in script
    assert "## [{}] - 2026-08-17".format(VERSION) in changelog
    assert "Source version v0.3.6" in readme
    assert "v0.3.6 local candidate" not in readme
    assert "This candidate has no tag" not in readme
    for quick_start in (readme, english_readme):
        assert "codex-instruct-vX.Y.Z.py" in quick_start
        assert (
            "awk '$2 == \"codex-instruct-vX.Y.Z.py\"' SHA256SUMS | shasum -a 256 -c -"
            in quick_start
        )
        assert "codex-instruct-v0.1.0.py" not in quick_start
        assert "--codex-dir ~/.codex --status" in quick_start
        assert "--codex-dir ~/.codex --dry-run" in quick_start


def test_cli_and_desktop_source_versions_match():
    version = (REPO_ROOT / "VERSION").read_text(encoding="ascii").strip()
    package = json.loads((REPO_ROOT / "gui" / "package.json").read_text(encoding="utf-8"))
    tauri_config = json.loads(
        (REPO_ROOT / "gui" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    cargo_toml = (REPO_ROOT / "gui" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    cargo_version = re.search(
        r'^version\s*=\s*"([^"]+)"\s*$',
        cargo_toml,
        re.MULTILINE,
    )

    assert tauri_config["version"] == "../package.json"
    assert cargo_version is not None
    assert {
        version,
        package["version"],
        cargo_version.group(1),
    } == {VERSION}


def test_windows_fresh_deployment_policy_markers_are_complete_and_consistent():
    values = []
    for relative_path in WINDOWS_POLICY_FILES:
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        markers = [
            line.strip().removeprefix("<!-- ").removesuffix(" -->")
            for line in content.splitlines()
            if "WINDOWS_FRESH_DEPLOYMENT_POLICY:" in line
        ]
        assert len(markers) == 1, relative_path
        marker, value = markers[0].split(": ", 1)
        assert marker == "WINDOWS_FRESH_DEPLOYMENT_POLICY"
        assert value in {"PENDING", "RECOVERY_ONLY", "EXPLICIT_BETA"}
        values.append(value)
    assert len(set(values)) == 1
    assert values[0] == "EXPLICIT_BETA"


def test_release_markdown_relative_links_stay_inside_bundle(release_builder):
    archive_files = set(release_builder._archive_files(TAG, REPO_ROOT))
    assert REQUIRED_SCENARIO_FILES <= archive_files
    tracked_gui = _run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "gui"],
        REPO_ROOT,
    ).stdout.splitlines()
    archive_files.update(tracked_gui)
    markdown_link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    html_link_pattern = re.compile(
        r"<(?:a|img)\b[^>]*\b(?:href|src)=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )

    for relative_path in sorted(archive_files):
        if not relative_path.endswith(".md"):
            continue
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        raw_targets = markdown_link_pattern.findall(content)
        raw_targets.extend(html_link_pattern.findall(content))
        for raw_target in raw_targets:
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#", "<")):
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative_path), target))
            assert not resolved.startswith("../"), (relative_path, raw_target)
            assert resolved in archive_files, (relative_path, raw_target, resolved)


def test_scenario_archive_discovery_rejects_abnormal_members(release_builder, tmp_path):
    repo = tmp_path / "repo"
    package = repo / "scenarios" / "fixture"
    package.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = package / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(release_builder.ReleaseError, match="not a regular file"):
        release_builder._scenario_archive_files(repo)


def test_scenario_archive_discovery_ignores_python_bytecode_cache(
    release_builder,
    tmp_path,
):
    repo = tmp_path / "repo"
    package = repo / "scenarios" / "fixture"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    source = package / "verify.py"
    source.write_text("print('verify')\n", encoding="utf-8")
    (cache / "verify.cpython-314.pyc").write_bytes(b"local bytecode\n")
    (package / "verify.pyc").write_bytes(b"legacy local bytecode\n")

    assert release_builder._scenario_archive_files(repo) == ("scenarios/fixture/verify.py",)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_scenario_archive_discovery_does_not_ignore_abnormal_bytecode_nodes(
    release_builder,
    tmp_path,
    kind,
):
    repo = tmp_path / "repo"
    package = repo / "scenarios" / "fixture"
    package.mkdir(parents=True)
    abnormal = package / "masked.pyc"
    if kind == "symlink":
        source = package / "source.txt"
        source.write_text("source\n", encoding="utf-8")
        try:
            abnormal.symlink_to(source)
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation unavailable")
        os.mkfifo(abnormal)

    with pytest.raises(release_builder.ReleaseError, match="not a regular file"):
        release_builder._scenario_archive_files(repo)


def test_scenario_archive_discovery_rejects_symlinked_scenario_root(
    release_builder,
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside-scenarios"
    package = outside / "fixture"
    package.mkdir(parents=True)
    (package / "verify.py").write_text("print('verify')\n", encoding="utf-8")
    try:
        (repo / "scenarios").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(release_builder.ReleaseError, match="root is not a directory"):
        release_builder._scenario_archive_files(repo)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "bad:name.txt",
        "bad?name.txt",
        "control\x1f.txt",
        "delete\x7f.txt",
        "AUX.txt",
        "trailing-dot.",
    ],
)
@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot materialize the unsafe fixture filenames",
)
def test_scenario_archive_discovery_rejects_cross_platform_unsafe_paths(
    release_builder,
    tmp_path,
    unsafe_name,
):
    repo = tmp_path / "repo"
    member = repo / "scenarios" / "fixture" / unsafe_name
    member.parent.mkdir(parents=True)
    member.write_text("unsafe archive path\n", encoding="utf-8")

    with pytest.raises(release_builder.ReleaseError, match="cross-platform unsafe path"):
        release_builder._scenario_archive_files(repo)


def test_release_build_is_reproducible_and_contains_required_files(release_builder, tmp_path):
    repo, source_bytes = _make_release_repo(tmp_path, release_builder)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    release_builder.build_release(TAG, repo, first_output)
    release_builder.build_release(TAG, repo, second_output)

    archive_files = tuple(sorted(source_bytes))
    assert REQUIRED_ARCHIVE_FILES <= set(archive_files)
    assert _asset_hashes(first_output) == _asset_hashes(second_output)
    prefix = "codex-keysmith-{}/".format(TAG)
    zip_path = first_output / "codex-keysmith-{}.zip".format(TAG)
    tar_path = first_output / "codex-keysmith-{}.tar.gz".format(TAG)
    expected_members = {prefix + relative_path for relative_path in archive_files}
    with zipfile.ZipFile(str(zip_path)) as archive:
        zip_members = set(archive.namelist())
        assert zip_members == expected_members
        for relative_path in archive_files:
            assert prefix + relative_path in zip_members
            assert archive.read(prefix + relative_path) == source_bytes[relative_path]
        executable = archive.getinfo(prefix + "gui/scripts/build-sidecar.mjs")
        assert executable.external_attr >> 16 & 0o777 == 0o755
        runner = archive.getinfo(prefix + "scripts/run_scenario_bank.py")
        assert runner.external_attr >> 16 & 0o777 == 0o755
        assert archive.read(prefix + "LICENSE") == (REPO_ROOT / "LICENSE").read_bytes()
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    with tarfile.open(str(tar_path), "r:gz") as archive:
        tar_members = {member.name: member for member in archive.getmembers()}
        assert set(tar_members) == expected_members
        for relative_path in archive_files:
            member = tar_members[prefix + relative_path]
            extracted = archive.extractfile(member)
            assert extracted is not None
            assert extracted.read() == source_bytes[relative_path]
            assert member.mtime == 0
            assert member.uid == member.gid == 0
        assert tar_members[prefix + "gui/scripts/build-sidecar.mjs"].mode == 0o755
        assert tar_members[prefix + "scripts/run_scenario_bank.py"].mode == 0o755


def test_standalone_script_and_checksums_match_assets(release_builder, tmp_path):
    repo, source_bytes = _make_release_repo(tmp_path, release_builder)
    output_dir = tmp_path / "assets"
    release_builder.build_release(TAG, repo, output_dir)

    script_path = output_dir / "codex-instruct-{}.py".format(TAG)
    script_bytes = script_path.read_bytes()
    assert script_bytes.startswith(b"#!/usr/bin/env python3\n")
    assert source_bytes["codex-instruct.py"].split(b"\n", 1)[1] in script_bytes
    for marker in release_builder.MIT_MARKERS:
        assert marker in script_bytes
    if os.name != "nt":
        assert script_path.stat().st_mode & 0o111 == 0o111

    checksum_lines = (output_dir / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    checksums = dict(line.split("  ", 1) for line in checksum_lines)
    expected_assets = {
        "codex-keysmith-{}.zip".format(TAG),
        "codex-keysmith-{}.tar.gz".format(TAG),
        "codex-instruct-{}.py".format(TAG),
        "codex-keysmith-scenarios-{}.bundle".format(TAG),
    }
    assert set(checksums.values()) == expected_assets
    for digest, name in checksums.items():
        assert digest == _file_sha256(output_dir / name)


def test_scenario_bundle_is_deterministic_and_matches_m1_source_digests(release_builder, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "codex_instruct_release_bundle",
        REPO_ROOT / "codex-instruct.py",
    )
    cli = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(cli)

    repo, _ = _make_release_repo(tmp_path, release_builder)
    first = tmp_path / "bundle-first"
    second = tmp_path / "bundle-second"
    first_bundle = first / "codex-keysmith-scenarios-{}.bundle".format(TAG)
    second_bundle = second / "codex-keysmith-scenarios-{}.bundle".format(TAG)
    release_builder.write_scenario_bundle(repo, first_bundle, version=VERSION)
    release_builder.write_scenario_bundle(repo, second_bundle, version=VERSION)
    assert first_bundle.read_bytes() == second_bundle.read_bytes()

    with zipfile.ZipFile(str(first_bundle)) as archive:
        names = set(archive.namelist())
        assert "index.json" in names
        assert all(name == "index.json" or name.startswith("scenarios/") for name in names)
        index = json.loads(archive.read("index.json").decode("utf-8"))
        assert index["schema_version"] == 1
        assert index["tool_version"] == VERSION
        assert "sha256" not in index
        assert set(index["scenarios"]) == {
            "example_fixture",
            "aiml_toxigen",
            "chem_rdkit",
            "cyber_keystone",
        }
        for scenario_id, record in index["scenarios"].items():
            package = cli.load_scenario_package(REPO_ROOT / "scenarios", scenario_id)
            assert record["source_digest"] == package.source_digest
            assert record["id"] == package.scenario_id
            assert record["version"] == package.version
            assert record["platforms"] == list(package.platforms)

    release_output = tmp_path / "release-assets"
    release_builder.build_release(TAG, repo, release_output)
    released = release_output / "codex-keysmith-scenarios-{}.bundle".format(TAG)
    assert released.read_bytes() == first_bundle.read_bytes()


def test_scenario_bundle_write_is_idempotent_and_never_overwrites_destination(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    destination = tmp_path / "assets" / "scenarios.bundle"

    release_builder.write_scenario_bundle(repo, destination, version=VERSION)
    original = destination.read_bytes()
    release_builder.write_scenario_bundle(repo, destination, version=VERSION)
    assert destination.read_bytes() == original

    destination.write_bytes(b"existing release evidence\n")
    with pytest.raises(release_builder.ReleaseError, match="refusing to overwrite"):
        release_builder.write_scenario_bundle(repo, destination, version=VERSION)
    assert destination.read_bytes() == b"existing release evidence\n"


def test_scenario_bundle_build_failure_preserves_existing_destination(
    release_builder, monkeypatch, tmp_path
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    destination = tmp_path / "assets" / "scenarios.bundle"
    destination.parent.mkdir()
    destination.write_bytes(b"sealed previous bundle\n")

    def fail_write(path, members):
        path.write_bytes(b"partial staging bytes\n")
        raise OSError("simulated bundle write failure")

    monkeypatch.setattr(release_builder, "_write_scenario_bundle_zip", fail_write)
    with pytest.raises(OSError, match="simulated bundle write failure"):
        release_builder.write_scenario_bundle(repo, destination, version=VERSION)

    assert destination.read_bytes() == b"sealed previous bundle\n"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda data: data.update(schema_version=2), "schema or id"),
        (lambda data: data.update(version="1"), "semantic"),
        (lambda data: data.update(task="../task.md"), "unsafe path|normalized"),
        (lambda data: data.update(platforms=["plan9"]), "platforms"),
        (lambda data: data.update(runtime={"node": ">=20"}), "runtime"),
        (
            lambda data: data.update(
                requires=[
                    {
                        "name": "unsafe",
                        "type": "command",
                        "version": ">=1",
                        "probe": ["bash", "-c", "echo 1"],
                    }
                ]
            ),
            "must not invoke a shell",
        ),
    ],
)
def test_scenario_bundle_builder_rejects_invalid_m1_metadata_contracts(
    release_builder, tmp_path, mutate, match
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    metadata_path = repo / "scenarios" / "example_fixture" / "scenario.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mutate(metadata)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(release_builder.ReleaseError, match=match):
        release_builder.write_scenario_bundle(
            repo,
            tmp_path / "scenarios.bundle",
            version=VERSION,
        )


def test_scenario_bundle_builder_rejects_invalid_entrypoint_and_checksum_contracts(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    metadata_path = repo / "scenarios" / "example_fixture" / "scenario.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["task"] = "fixtures/positive/output.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(release_builder.ReleaseError, match="entrypoint"):
        release_builder.write_scenario_bundle(repo, tmp_path / "entrypoint.bundle", version=VERSION)

    metadata["task"] = "task.md"
    metadata["checksums"]["task.md"] = "invalid"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(release_builder.ReleaseError, match="checksum is invalid"):
        release_builder.write_scenario_bundle(repo, tmp_path / "checksum.bundle", version=VERSION)


def test_scenario_bundle_builder_rejects_case_insensitive_member_collision(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    collision = repo / "scenarios" / "example_fixture" / "TASK.MD"
    collision.write_text("collision\n", encoding="utf-8")
    if collision.samefile(repo / "scenarios" / "example_fixture" / "task.md"):
        pytest.skip("filesystem is case-insensitive")

    with pytest.raises(release_builder.ReleaseError, match="collide case-insensitively"):
        release_builder.write_scenario_bundle(repo, tmp_path / "scenarios.bundle", version=VERSION)


def test_release_builder_output_is_not_reused_as_desktop_prerelease(
    release_builder,
    tmp_path,
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    output_dir = tmp_path / "assets"

    release_builder.build_release(TAG, repo, output_dir)

    with pytest.raises(desktop_prerelease.PrereleaseError, match="public asset set is not exact"):
        desktop_prerelease.verify_public_assets(output_dir, "a" * 40)


def test_default_in_repository_output_can_be_rebuilt(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    output_dir = repo / "dist"

    release_builder.build_release(TAG, repo, output_dir)
    first_hashes = _asset_hashes(output_dir)
    release_builder.build_release(TAG, repo, output_dir)

    assert _asset_hashes(output_dir) == first_hashes


def test_builder_rejects_different_existing_asset_without_overwrite(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    output_dir = tmp_path / "assets"
    release_builder.build_release(TAG, repo, output_dir)
    archive_path = output_dir / "codex-keysmith-{}.zip".format(TAG)
    archive_path.write_bytes(b"different release evidence\n")

    with pytest.raises(release_builder.ReleaseError, match="refusing to overwrite"):
        release_builder.build_release(TAG, repo, output_dir)

    assert archive_path.read_bytes() == b"different release evidence\n"


def test_builder_rejects_tracked_or_abnormal_output_paths(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)

    with pytest.raises(release_builder.ReleaseError, match="tracked source files"):
        release_builder.build_release(TAG, repo, repo / "docs")
    with pytest.raises(release_builder.ReleaseError, match="inside .git"):
        release_builder.build_release(TAG, repo, repo / ".git" / "release")

    output_dir = tmp_path / "assets"
    output_dir.mkdir()
    destination = output_dir / "codex-keysmith-{}.zip".format(TAG)
    destination.mkdir()
    with pytest.raises(release_builder.ReleaseError, match="not a regular file"):
        release_builder.build_release(TAG, repo, output_dir)

    symlink_parent = repo / "outparent"
    try:
        symlink_parent.symlink_to(repo / ".git", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("symlink creation is unavailable: {}".format(exc))
    with pytest.raises(release_builder.ReleaseError, match="symbolic-link ancestor"):
        release_builder.build_release(TAG, repo, symlink_parent / "release")
    assert not (repo / ".git" / "release").exists()


def test_builder_rejects_dirty_repository(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(release_builder.ReleaseError, match="repository is dirty"):
        release_builder.build_release(TAG, repo, tmp_path / "assets")


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize("relative_path", ["README.md", "gui/README.md"])
def test_candidate_build_rejects_index_flag_hidden_source_drift(
    release_builder,
    tmp_path,
    index_flag,
    relative_path,
):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    candidate = _head_commit(repo)
    source = repo / relative_path
    source.write_bytes(source.read_bytes() + b"hidden working-tree drift\n")
    _run(["git", "update-index", index_flag, relative_path], repo)
    assert _run(["git", "status", "--porcelain"], repo).stdout == ""

    with pytest.raises(
        release_builder.ReleaseError,
        match="differs from validated source commit: {}".format(re.escape(relative_path)),
    ):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_rejects_tracked_gui_symlink(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    gui_readme = repo / "gui" / "README.md"
    gui_readme.unlink()
    try:
        gui_readme.symlink_to("../README.md")
    except (OSError, NotImplementedError) as exc:
        pytest.skip("symlink creation is unavailable: {}".format(exc))
    _run(["git", "add", "gui/README.md"], repo)
    _run(["git", "commit", "-qm", "track GUI symlink"], repo)
    candidate = _head_commit(repo)

    with pytest.raises(
        release_builder.ReleaseError,
        match="tracked GUI entry is not a regular file: gui/README.md",
    ):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_rejects_tracked_gui_gitlink(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    parent = _head_commit(repo)
    _run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            "160000,{},gui/vendor-fixture".format(parent),
        ],
        repo,
    )
    _run(["git", "commit", "-qm", "track GUI gitlink"], repo)
    candidate = _head_commit(repo)

    with pytest.raises(
        release_builder.ReleaseError,
        match="tracked GUI entry is not a regular file: gui/vendor-fixture",
    ):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_excludes_untracked_gui_when_clean_check_is_disabled(
    release_builder,
    tmp_path,
):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    candidate = _head_commit(repo)
    (repo / "gui/untracked.txt").write_text("must not ship\n", encoding="utf-8")
    output = tmp_path / "assets"

    release_builder.build_release(
        TAG,
        repo,
        output,
        require_clean=False,
        source_commit=candidate,
    )

    prefix = "codex-keysmith-{}/".format(TAG)
    with zipfile.ZipFile(str(output / "codex-keysmith-{}.zip".format(TAG))) as archive:
        assert prefix + "gui/untracked.txt" not in archive.namelist()


@pytest.mark.parametrize(
    "unsafe_path",
    [
        r"gui/bad\\name.txt",
        "gui/AUX.txt",
        "gui/trailing-dot.",
        "gui/bad:name.txt",
    ],
)
@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot materialize the unsafe fixture filenames",
)
def test_candidate_build_rejects_cross_platform_unsafe_gui_paths(
    release_builder,
    tmp_path,
    unsafe_path,
):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    path = repo / unsafe_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unsafe archive path\n", encoding="utf-8")
    _run(["git", "add", "--", unsafe_path], repo)
    _run(["git", "commit", "-qm", "track unsafe GUI path"], repo)
    candidate = _head_commit(repo)

    with pytest.raises(
        release_builder.ReleaseError,
        match="cross-platform unsafe GUI path",
    ):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_formal_build_requires_exact_tag_at_head(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    with pytest.raises(release_builder.ReleaseError, match="does not match release tag"):
        release_builder.build_release(TAG, repo, tmp_path / "assets")


def test_formal_build_fails_closed_when_tag_is_missing(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)

    with pytest.raises(release_builder.ReleaseError, match="cannot resolve release tag"):
        release_builder.build_release(TAG, repo, tmp_path / "assets")


def test_formal_build_supports_detached_head_at_exact_tag(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    _run(["git", "checkout", "--detach", "-q", TAG], repo)

    release_builder.build_release(TAG, repo, tmp_path / "assets")


def test_formal_build_rechecks_tag_after_asset_publication(
    release_builder,
    monkeypatch,
    tmp_path,
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    original_commit = _head_commit(repo)
    (repo / "second.txt").write_text("second\n", encoding="utf-8")
    _run(["git", "add", "second.txt"], repo)
    _run(["git", "commit", "-qm", "second commit"], repo)
    _run(["git", "tag", "-f", TAG], repo)
    output_dir = tmp_path / "assets"
    real_publish = release_builder._publish_assets_without_overwrite

    def publish_then_move_tag(staged_paths, final_paths):
        created = real_publish(staged_paths, final_paths)
        _run(["git", "tag", "-f", TAG, original_commit], repo)
        return created

    monkeypatch.setattr(
        release_builder,
        "_publish_assets_without_overwrite",
        publish_then_move_tag,
    )

    with pytest.raises(release_builder.ReleaseError, match="after publication"):
        release_builder.build_release(TAG, repo, output_dir)

    assert output_dir.is_dir()
    assert not [path for path in output_dir.iterdir() if path.is_file()]


def test_candidate_build_requires_full_exact_commit_and_supports_detached_head(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    commit = _head_commit(repo)
    _run(["git", "checkout", "--detach", "-q", commit], repo)

    release_builder.build_release(
        TAG,
        repo,
        tmp_path / "assets",
        source_commit=commit,
    )
    with pytest.raises(release_builder.ReleaseError, match="full Git commit"):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "abbreviated-assets",
            source_commit=commit[:12],
        )


def test_candidate_build_rejects_commit_mismatch(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    candidate = _head_commit(repo)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    with pytest.raises(release_builder.ReleaseError, match="does not match candidate"):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_rejects_conflicting_existing_release_tag(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)
    candidate = _head_commit(repo)

    with pytest.raises(release_builder.ReleaseError, match="already points to"):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_rejects_shallow_checkout_that_hides_release_tags(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path / "source", release_builder)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    shallow = tmp_path / "shallow"
    _run(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "1",
            "--no-tags",
            repo.as_uri(),
            str(shallow),
        ],
        tmp_path,
    )
    candidate = _head_commit(shallow)
    assert _run(["git", "rev-parse", "--is-shallow-repository"], shallow).stdout.strip() == "true"

    with pytest.raises(release_builder.ReleaseError, match="complete Git checkout"):
        release_builder.build_release(
            TAG,
            shallow,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_release_build_rejects_promisor_checkout_configuration(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    _run(["git", "config", "remote.fixture.promisor", "true"], repo)

    with pytest.raises(release_builder.ReleaseError, match="partial or promisor"):
        release_builder.build_release(TAG, repo, tmp_path / "assets")


def test_candidate_build_from_complete_clone_rejects_existing_version_tag(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path / "source", release_builder)
    tagged_commit = _head_commit(repo)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    complete = tmp_path / "complete"
    _run(["git", "clone", "-q", repo.as_uri(), str(complete)], tmp_path)
    candidate = _head_commit(complete)
    assert _run(["git", "rev-parse", "--is-shallow-repository"], complete).stdout.strip() == "false"
    assert (
        _run(["git", "rev-parse", "{}^{{commit}}".format(TAG)], complete).stdout.strip()
        == tagged_commit
    )

    with pytest.raises(release_builder.ReleaseError, match="already points to"):
        release_builder.build_release(
            TAG,
            complete,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_candidate_build_from_non_shallow_no_tags_clone_rejects_remote_version_tag(
    release_builder, tmp_path
):
    repo, _ = _make_release_repo(tmp_path / "source", release_builder)
    tagged_commit = _head_commit(repo)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    no_tags = tmp_path / "no-tags"
    _run(
        ["git", "clone", "-q", "--no-tags", repo.as_uri(), str(no_tags)],
        tmp_path,
    )
    candidate = _head_commit(no_tags)
    output_dir = tmp_path / "assets"
    assert _run(["git", "rev-parse", "--is-shallow-repository"], no_tags).stdout.strip() == "false"
    missing_tag = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/tags/{}".format(TAG)],
        cwd=str(no_tags),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert missing_tag.returncode != 0

    with pytest.raises(release_builder.ReleaseError, match="remote release tag"):
        release_builder.build_release(
            TAG,
            no_tags,
            output_dir,
            source_commit=candidate,
        )

    assert tagged_commit != candidate
    assert not output_dir.exists() or not list(output_dir.iterdir())


def test_formal_build_reconciles_tag_with_configured_remote(release_builder, tmp_path):
    source, _ = _make_release_repo(tmp_path / "source", release_builder)
    clone = tmp_path / "clone"
    _run(["git", "clone", "-q", source.as_uri(), str(clone)], tmp_path)

    release_builder.build_release(TAG, clone, tmp_path / "assets")


def test_release_fixture_pins_lf_checkout_under_windows_autocrlf(release_builder, tmp_path):
    source, source_bytes = _make_release_repo(
        tmp_path / "source-lf",
        release_builder,
    )
    clone = tmp_path / "clone-lf"
    _run(
        [
            "git",
            "-c",
            "core.autocrlf=true",
            "clone",
            "-q",
            source.as_uri(),
            str(clone),
        ],
        tmp_path,
    )

    for relative_path, expected in source_bytes.items():
        assert (clone / relative_path).read_bytes() == expected

    release_builder.build_release(TAG, clone, tmp_path / "assets-lf")


def test_formal_build_rejects_local_tag_missing_from_remote(release_builder, tmp_path):
    source, _ = _make_release_repo(
        tmp_path / "source",
        release_builder,
        create_tag=False,
    )
    clone = tmp_path / "clone-missing"
    _run(["git", "clone", "-q", source.as_uri(), str(clone)], tmp_path)
    _run(["git", "tag", TAG], clone)

    with pytest.raises(release_builder.ReleaseError, match="missing from remote"):
        release_builder.build_release(TAG, clone, tmp_path / "assets-missing")


def test_formal_build_rejects_local_tag_that_disagrees_with_remote(release_builder, tmp_path):
    source, _ = _make_release_repo(tmp_path / "source", release_builder)
    (source / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], source)
    _run(["git", "commit", "-qm", "later commit"], source)

    clone = tmp_path / "clone-mismatch"
    _run(["git", "clone", "-q", "--no-tags", source.as_uri(), str(clone)], tmp_path)
    _run(["git", "tag", TAG], clone)

    with pytest.raises(release_builder.ReleaseError, match="remote release tag"):
        release_builder.build_release(TAG, clone, tmp_path / "assets-mismatch")


def test_candidate_build_rejects_local_tag_that_shadows_conflicting_remote_tag(
    release_builder,
    tmp_path,
):
    repo, _ = _make_release_repo(tmp_path / "source", release_builder)
    tagged_commit = _head_commit(repo)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    _run(["git", "add", "later.txt"], repo)
    _run(["git", "commit", "-qm", "later commit"], repo)

    no_tags = tmp_path / "no-tags-shadow"
    _run(
        ["git", "clone", "-q", "--no-tags", repo.as_uri(), str(no_tags)],
        tmp_path,
    )
    candidate = _head_commit(no_tags)
    _run(["git", "tag", TAG, candidate], no_tags)
    output_dir = tmp_path / "assets-shadow"

    with pytest.raises(release_builder.ReleaseError, match="remote release tag"):
        release_builder.build_release(
            TAG,
            no_tags,
            output_dir,
            source_commit=candidate,
        )

    assert tagged_commit != candidate
    assert not output_dir.exists() or not list(output_dir.iterdir())


@pytest.mark.parametrize("failure", ["timeout", "authentication"])
def test_candidate_build_fails_closed_when_remote_tag_verification_is_unavailable(
    release_builder,
    monkeypatch,
    tmp_path,
    failure,
):
    repo, _ = _make_release_repo(tmp_path / "source", release_builder)
    no_tags = tmp_path / f"remote-unavailable-{failure}"
    _run(
        ["git", "clone", "-q", "--no-tags", repo.as_uri(), str(no_tags)],
        tmp_path,
    )
    candidate = _head_commit(no_tags)
    output_dir = tmp_path / f"assets-{failure}"
    real_run = release_builder.subprocess.run
    observed = []

    def fail_remote(command, *args, **kwargs):
        if "ls-remote" not in command:
            return real_run(command, *args, **kwargs)
        observed.append(kwargs.get("env", {}).get("GIT_TERMINAL_PROMPT"))
        if failure == "timeout":
            raise release_builder.subprocess.TimeoutExpired(command, 30)
        return release_builder.subprocess.CompletedProcess(
            command,
            128,
            stdout="",
            stderr="authentication required",
        )

    monkeypatch.setattr(release_builder.subprocess, "run", fail_remote)

    with pytest.raises(release_builder.ReleaseError, match="cannot verify remote"):
        release_builder.build_release(
            TAG,
            no_tags,
            output_dir,
            source_commit=candidate,
        )

    assert observed == ["0"]
    assert not output_dir.exists() or not list(output_dir.iterdir())


def test_builder_fails_closed_without_git_metadata(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    commit = _head_commit(repo)
    (repo / ".git").rename(repo / ".git-hidden")

    with pytest.raises(release_builder.ReleaseError, match="cannot resolve repository HEAD"):
        release_builder.build_release(
            TAG,
            repo,
            tmp_path / "assets",
            require_clean=False,
            source_commit=commit,
        )


@pytest.mark.parametrize(
    ("tag", "version_text", "cli_version", "message"),
    [
        ("0.1.0", "0.1.0", "0.1.0", "semantic tag"),
        ("v0.2.0", "0.1.0", "0.1.0", "version mismatch"),
        ("v0.1.0", "0.1.0", "0.2.0", "version mismatch"),
    ],
)
def test_builder_rejects_version_mismatch(
    release_builder, tmp_path, tag, version_text, cli_version, message
):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    (repo / "VERSION").write_text(version_text + "\n", encoding="ascii")
    (repo / "codex-instruct.py").write_text(
        '__version__ = "{}"\n'.format(cli_version), encoding="utf-8"
    )

    with pytest.raises(release_builder.ReleaseError, match=message):
        release_builder.build_release(tag, repo, tmp_path / "assets")


def test_builder_rejects_missing_file_and_incomplete_mit_notice(release_builder, tmp_path):
    missing_repo, _ = _make_release_repo(tmp_path / "missing", release_builder)
    (missing_repo / "README.md").unlink()
    with pytest.raises(release_builder.ReleaseError, match="required release file is missing"):
        release_builder.build_release(TAG, missing_repo, tmp_path / "missing-assets")

    license_repo, _ = _make_release_repo(tmp_path / "license", release_builder)
    (license_repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    with pytest.raises(release_builder.ReleaseError, match="complete MIT notice"):
        release_builder.build_release(TAG, license_repo, tmp_path / "license-assets")


def test_ci_uses_full_tag_checkout_and_blocking_windows_matrix():
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "persist-credentials: false" in workflow
    assert "source_ref:" in workflow
    assert "expected_commit:" in workflow
    assert workflow.count("ref: ${{ inputs.source_ref || github.sha }}") == 3
    assert workflow.count("name: Bind checked-out source") == 3
    assert "EXPECTED_COMMIT: ${{ inputs.expected_commit || github.sha }}" in workflow
    assert "actions/checkout@v" not in workflow
    assert "actions/setup-python@v" not in workflow
    assert '"pytest==8.3.5"' in workflow
    assert '"pytest==8.4.2"' in workflow
    assert "python-version == '3.9'" in workflow
    assert "python-version == '3.8'" not in workflow
    assert "windows-2025" in workflow
    assert '"3.10"' in workflow
    assert '"3.12"' in workflow
    assert '"3.14"' in workflow
    assert "continue-on-error" not in workflow
    assert "Windows experimental atomic no-replace probe passed" not in workflow
    windows_job = workflow.split("\n  windows:", 1)[1].split("\n  quality:", 1)[0]
    assert "runs-on: windows-2025" in windows_job
    assert "python -m py_compile" in windows_job
    assert "codex-instruct.py" in windows_job
    assert "scripts/run_scenario_bank.py" in windows_job
    assert "python -m pytest -p no:cacheprovider -q tests" in windows_job
    quality_job = workflow.split("\n  quality:", 1)[1]
    assert "fetch-depth: 0" in quality_job
    assert "fetch-tags: true" in quality_job
    assert "rev-parse --is-shallow-repository" in quality_job
    assert 'release_tag="v$(tr -d' in workflow
    assert "source_commit=\"$(git rev-parse --verify 'HEAD^{commit}')\"" in workflow
    assert 'if [ "$tag_commit" != "$source_commit" ]; then' in workflow
    assert "Release builder failed for an unexpected reason" in workflow
    assert "correctly refused the conflicting candidate" in workflow
    assert '--source-commit "$source_commit"' in workflow
    assert "release-candidate-first" in quality_job
    assert "release-candidate-second" in quality_job
    assert 'diff -u "$first/SHA256SUMS" "$second/SHA256SUMS"' in quality_job
    assert 'cmp "$first/$asset" "$second/$asset"' in quality_job
    assert "sha256sum --check SHA256SUMS" in workflow
    assert "--fail-under=81" in workflow
    assert (
        "coverage report --include=scripts/run_scenario_bank.py --fail-under=65"
        in quality_job
    )
    assert "python scripts/run_scenario_bank.py --validate-only" in quality_job

    release_workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert 'tags:\n      - "v*.*.*"' in release_workflow
    assert "workflow_dispatch:" in release_workflow
    assert "release_tag:" in release_workflow
    assert "expected_tag_object:" in release_workflow
    assert "expected_commit:" in release_workflow
    assert "uses: ./.github/workflows/tests.yml" in release_workflow
    assert "source_ref: ${{ github.event_name == 'workflow_dispatch'" in release_workflow
    assert "needs:\n      - blocking-tests" in release_workflow
    assert "fetch-depth: 0" in release_workflow
    assert "fetch-tags: true" in release_workflow
    assert "persist-credentials: false" in release_workflow
    assert "|| github.sha }}" in release_workflow
    assert "refs/tags/${tag}^{commit}" in release_workflow
    assert "github.workflow_sha" in release_workflow
    assert release_workflow.count('git/ref/heads/main" --jq .object.sha') == 2
    assert "git merge-base --is-ancestor" in release_workflow
    assert "git/ref/tags/${tag}" in release_workflow
    assert "jq -r .tag" in release_workflow
    assert "jq -r .object.type" in release_workflow
    assert ".verification.verified" in release_workflow
    assert ".verification.reason" in release_workflow
    assert 'expected_tag="v${version}"' in release_workflow
    assert "Formal releases require an annotated tag object" in release_workflow
    assert "WINDOWS_FRESH_DEPLOYMENT_POLICY" in release_workflow
    assert "RECOVERY_ONLY|EXPLICIT_BETA" in release_workflow
    assert "release-first" in release_workflow
    assert "release-second" in release_workflow
    assert "diff -u" in release_workflow
    assert 'cmp "$first/$asset" "$second/$asset"' in release_workflow
    assert "sha256sum --check SHA256SUMS" in release_workflow
    assert 'expected_version_output="codex-instruct-${{ steps.source.outputs.tag }}.py' in (
        release_workflow
    )
    assert "codex-keysmith-scenarios-${{ steps.source.outputs.tag }}.bundle" in (release_workflow)
    assert 'assert len(state["assets"]) == 5' in release_workflow
    assert "gh release create" not in release_workflow
    assert 'gh release upload "$tag"' not in release_workflow
    assert "--paginate --slurp" in release_workflow
    assert 'jq -r --arg tag "$tag"' in release_workflow
    assert 'gh api -X POST "repos/${GITHUB_REPOSITORY}/releases"' in release_workflow
    post_index = release_workflow.index('gh api -X POST "repos/${GITHUB_REPOSITORY}/releases"')
    assert post_index < release_workflow.index("release_created=true", post_index)
    assert 'if [ -z "$release_api" ]' not in release_workflow
    assert "https://uploads.github.com/" in release_workflow
    assert "https://api.github.com/repos/{}/releases/{}" in release_workflow
    assert 'assert candidate["assets"] == []' in release_workflow
    assert '"${upload_url}?name=${encoded_name}"' in release_workflow
    assert "releases/${release_id}" in release_workflow
    assert 'gh api -X DELETE "$release_api"' in release_workflow
    assert "primary_status=$?" in release_workflow
    assert "Could not read owned draft Release" in release_workflow
    assert "Publish response was lost" in release_workflow
    assert "'.draft | tostring'" in release_workflow
    assert 'gh api -X PATCH "$release_api"' in release_workflow
    assert '"draft": True' in release_workflow
    assert ".assets[] | [.name, .digest, .state" in release_workflow
    assert 'git cat-file blob "${head_commit}:${notes}"' in release_workflow
    assert 'gh release edit "$tag"' not in release_workflow
    assert "-F draft=false" in release_workflow
    assert "-f make_latest=true" in release_workflow
    assert "--clobber" not in release_workflow

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pull_request_template = (REPO_ROOT / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )
    assert "fail_under = 81" in pyproject
    assert 'patch = ["_exit", "subprocess"]' in pyproject
    assert "branch coverage ≥ 81%" in pull_request_template
    assert "branch coverage ≥ 80%" not in pull_request_template
    assert "scripts/build_release.py v0.1.0" not in pull_request_template
    assert 'RELEASE_TAG="v$(tr -d' in pull_request_template
    assert "SOURCE_COMMIT=\"$(git rev-parse --verify 'HEAD^{commit}')\"" in (pull_request_template)


def test_release_creation_validator_binds_numeric_id_and_upload_url(tmp_path, monkeypatch):
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    validator_start = workflow.index(
        "          import json\n",
        workflow.index('draft_state="${RUNNER_TEMP}/draft-release-empty.json"'),
    )
    validator_end = workflow.index("\n          PY", validator_start)
    validator = textwrap.dedent(workflow[validator_start:validator_end])

    repo = "Jia-Ethan/codex-keysmith"
    release_id = "358412164"
    tag = TAG
    commit = "d8335f99a557403f3ef919c8601502e5a8362414"
    notes = tmp_path / "notes.md"
    notes.write_bytes(b"immutable release notes\n")
    expected_api = f"https://api.github.com/repos/{repo}/releases/{release_id}"
    expected_upload = (
        f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets{{?name,label}}"
    )
    payload = {
        "id": int(release_id),
        "url": expected_api,
        "upload_url": expected_upload,
        "tag_name": tag,
        "target_commitish": commit,
        "name": f"codex-keysmith {tag}",
        "draft": True,
        "prerelease": False,
        "body": notes.read_bytes().decode("utf-8"),
        "assets": [],
    }
    created = tmp_path / "created.json"
    state = tmp_path / "state.json"

    def run_validator(created_payload, state_payload):
        created.write_text(json.dumps(created_payload), encoding="utf-8")
        state.write_text(json.dumps(state_payload), encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "release-validator",
                str(created),
                str(state),
                str(notes),
                tag,
                commit,
                release_id,
                repo,
            ],
        )
        exec(compile(validator, "<release-validator>", "exec"), {})

    run_validator(payload, payload)

    wrong_upload = dict(payload, upload_url=expected_upload.replace("/assets", "/wrong"))
    with pytest.raises(AssertionError):
        run_validator(wrong_upload, payload)

    wrong_id = dict(payload, id=int(release_id) + 1)
    with pytest.raises(AssertionError):
        run_validator(payload, wrong_id)

    nonempty = dict(payload, assets=[{"id": 1}])
    with pytest.raises(AssertionError):
        run_validator(payload, nonempty)

    quality_requirements = (REPO_ROOT / "requirements-quality.txt").read_text(encoding="ascii")
    assert quality_requirements.splitlines() == [
        "coverage[toml]==7.10.7",
        "pytest==8.4.2",
        "ruff==0.15.21",
    ]

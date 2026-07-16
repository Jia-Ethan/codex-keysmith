import hashlib
import importlib.util
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO_ROOT / "scripts" / "build_release.py"
TAG = "v0.1.0"
VERSION = "0.1.0"
REQUIRED_ARCHIVE_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "VERSION",
    "codex-instruct.py",
    "examples/gpt-unrestricted.md",
}


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
    for relative_path in release_builder.ARCHIVE_FILES:
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "VERSION":
            data = (VERSION + "\n").encode("ascii")
        elif relative_path == "codex-instruct.py":
            data = b'#!/usr/bin/env python3\n__version__ = "0.1.0"\n'
        elif relative_path == "CHANGELOG.md":
            data = b"# Changelog\n\n## [0.1.0] - 2026-07-16\n\n- Release.\n"
        elif relative_path == "LICENSE":
            data = (REPO_ROOT / "LICENSE").read_bytes()
        else:
            data = ("fixture for {}\n".format(relative_path)).encode("utf-8")
        path.write_bytes(data)
        source_bytes[relative_path] = data

    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.name", "Release Test"], repo)
    _run(["git", "config", "user.email", "release-test@example.invalid"], repo)
    _run(["git", "config", "core.autocrlf", "false"], repo)
    _run(["git", "add", "."], repo)
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
        path.name: _file_sha256(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }


def test_release_build_is_reproducible_and_contains_required_files(
    release_builder, tmp_path
):
    repo, source_bytes = _make_release_repo(tmp_path, release_builder)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    release_builder.build_release(TAG, repo, first_output)
    release_builder.build_release(TAG, repo, second_output)

    assert REQUIRED_ARCHIVE_FILES <= set(release_builder.ARCHIVE_FILES)
    assert _asset_hashes(first_output) == _asset_hashes(second_output)
    prefix = "codex-keysmith-{}/".format(TAG)
    zip_path = first_output / "codex-keysmith-{}.zip".format(TAG)
    tar_path = first_output / "codex-keysmith-{}.tar.gz".format(TAG)
    expected_members = {
        prefix + relative_path for relative_path in release_builder.ARCHIVE_FILES
    }
    with zipfile.ZipFile(str(zip_path)) as archive:
        zip_members = set(archive.namelist())
        assert zip_members == expected_members
        for relative_path in release_builder.ARCHIVE_FILES:
            assert prefix + relative_path in zip_members
            assert archive.read(prefix + relative_path) == source_bytes[relative_path]
        assert archive.read(prefix + "LICENSE") == (REPO_ROOT / "LICENSE").read_bytes()
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    with tarfile.open(str(tar_path), "r:gz") as archive:
        tar_members = {member.name: member for member in archive.getmembers()}
        assert set(tar_members) == expected_members
        for relative_path in release_builder.ARCHIVE_FILES:
            member = tar_members[prefix + relative_path]
            extracted = archive.extractfile(member)
            assert extracted is not None
            assert extracted.read() == source_bytes[relative_path]
            assert member.mtime == 0
            assert member.uid == member.gid == 0


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
    }
    assert set(checksums.values()) == expected_assets
    for digest, name in checksums.items():
        assert digest == _file_sha256(output_dir / name)


def test_default_in_repository_output_can_be_rebuilt(release_builder, tmp_path):
    repo, _ = _make_release_repo(tmp_path, release_builder)
    output_dir = repo / "dist"

    release_builder.build_release(TAG, repo, output_dir)
    first_hashes = _asset_hashes(output_dir)
    release_builder.build_release(TAG, repo, output_dir)

    assert _asset_hashes(output_dir) == first_hashes


def test_builder_rejects_different_existing_asset_without_overwrite(
    release_builder, tmp_path
):
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


def test_candidate_build_rejects_conflicting_existing_release_tag(
    release_builder, tmp_path
):
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


def test_builder_rejects_missing_file_and_incomplete_mit_notice(
    release_builder, tmp_path
):
    missing_repo, _ = _make_release_repo(tmp_path / "missing", release_builder)
    (missing_repo / "README.md").unlink()
    with pytest.raises(release_builder.ReleaseError, match="required release file is missing"):
        release_builder.build_release(TAG, missing_repo, tmp_path / "missing-assets")

    license_repo, _ = _make_release_repo(tmp_path / "license", release_builder)
    (license_repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    with pytest.raises(release_builder.ReleaseError, match="complete MIT notice"):
        release_builder.build_release(TAG, license_repo, tmp_path / "license-assets")


def test_ci_uses_immutable_actions_exact_dependencies_and_windows_probe():
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "persist-credentials: false" in workflow
    assert "actions/checkout@v" not in workflow
    assert "actions/setup-python@v" not in workflow
    assert '"pytest==8.3.5"' in workflow
    assert '"pytest==8.4.2"' in workflow
    assert "Windows experimental atomic no-replace probe passed" in workflow
    assert 'release_tag="v$(tr -d' in workflow
    assert 'python scripts/build_release.py "$release_tag" --source-commit "$GITHUB_SHA"' in workflow
    assert "Candidate-only verification" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow

    quality_requirements = (REPO_ROOT / "requirements-quality.txt").read_text(
        encoding="ascii"
    )
    assert quality_requirements.splitlines() == [
        "coverage[toml]==7.10.7",
        "pytest==8.4.2",
        "ruff==0.15.21",
    ]

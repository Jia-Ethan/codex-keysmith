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
TAG = "v0.1.1"
VERSION = "0.1.1"
REQUIRED_ARCHIVE_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "VERSION",
    "codex-instruct.py",
    "docs/releases/v0.1.1.md",
    "examples/gpt-unrestricted.md",
}
WINDOWS_POLICY_FILES = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/hooks-transactions.md",
    "docs/releases/v0.1.1.md",
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
            data = ('#!/usr/bin/env python3\n__version__ = "{}"\n'.format(VERSION)).encode(
                "ascii"
            )
        elif relative_path == "CHANGELOG.md":
            data = (
                "# Changelog\n\n## [{}] - 2026-07-18\n\n- Release.\n".format(VERSION)
            ).encode("ascii")
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


def test_repository_version_metadata_is_release_state_neutral():
    version = (REPO_ROOT / "VERSION").read_text(encoding="ascii").strip()
    script = (REPO_ROOT / "codex-instruct.py").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert version == VERSION
    assert '__version__ = "{}"'.format(VERSION) in script
    assert "## [{}] - 2026-07-22".format(VERSION) in changelog
    assert "Source version v0.1.1" in readme
    assert "v0.1.1 local candidate" not in readme
    assert "This candidate has no tag" not in readme
    chinese_candidate = readme.split("### v0.1.1 源码与候选构建", 1)[1].split(
        "\n## English\n",
        1,
    )[0]
    english_candidate = readme.split("### v0.1.1 source and candidate builds", 1)[1]
    assert "codex-instruct-v0.1.0.py" in readme.split(
        "### v0.1.1 源码与候选构建",
        1,
    )[0]
    assert "codex-instruct-v0.1.0.py" not in chinese_candidate
    assert "codex-instruct-v0.1.0.py" not in english_candidate
    assert "python3 codex-instruct.py --codex-dir" in chinese_candidate
    assert "python3 codex-instruct.py --codex-dir" in english_candidate


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


def test_release_build_is_reproducible_and_contains_required_files(
    release_builder, tmp_path
):
    repo, source_bytes = _make_release_repo(tmp_path, release_builder)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    release_builder.build_release(TAG, repo, first_output)
    release_builder.build_release(TAG, repo, second_output)

    archive_files = release_builder._archive_files(TAG)
    assert REQUIRED_ARCHIVE_FILES <= set(archive_files)
    assert _asset_hashes(first_output) == _asset_hashes(second_output)
    prefix = "codex-keysmith-{}/".format(TAG)
    zip_path = first_output / "codex-keysmith-{}.zip".format(TAG)
    tar_path = first_output / "codex-keysmith-{}.tar.gz".format(TAG)
    expected_members = {
        prefix + relative_path for relative_path in archive_files
    }
    with zipfile.ZipFile(str(zip_path)) as archive:
        zip_members = set(archive.namelist())
        assert zip_members == expected_members
        for relative_path in archive_files:
            assert prefix + relative_path in zip_members
            assert archive.read(prefix + relative_path) == source_bytes[relative_path]
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


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_candidate_build_rejects_index_flag_hidden_source_drift(
    release_builder,
    tmp_path,
    index_flag,
):
    repo, _ = _make_release_repo(tmp_path, release_builder, create_tag=False)
    candidate = _head_commit(repo)
    readme = repo / "README.md"
    readme.write_bytes(readme.read_bytes() + b"hidden working-tree drift\n")
    _run(["git", "update-index", index_flag, "README.md"], repo)
    assert _run(["git", "status", "--porcelain"], repo).stdout == ""

    with pytest.raises(
        release_builder.ReleaseError,
        match="differs from validated source commit: README.md",
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
    assert (
        _run(["git", "rev-parse", "--is-shallow-repository"], shallow).stdout.strip()
        == "true"
    )

    with pytest.raises(release_builder.ReleaseError, match="complete Git checkout"):
        release_builder.build_release(
            TAG,
            shallow,
            tmp_path / "assets",
            source_commit=candidate,
        )


def test_release_build_rejects_promisor_checkout_configuration(
    release_builder, tmp_path
):
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
    assert (
        _run(["git", "rev-parse", "--is-shallow-repository"], complete)
        .stdout.strip()
        == "false"
    )
    assert (
        _run(["git", "rev-parse", "{}^{{commit}}".format(TAG)], complete)
        .stdout.strip()
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
    assert (
        _run(["git", "rev-parse", "--is-shallow-repository"], no_tags)
        .stdout.strip()
        == "false"
    )
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


def test_formal_build_reconciles_tag_with_configured_remote(
    release_builder, tmp_path
):
    source, _ = _make_release_repo(tmp_path / "source", release_builder)
    clone = tmp_path / "clone"
    _run(["git", "clone", "-q", source.as_uri(), str(clone)], tmp_path)

    release_builder.build_release(TAG, clone, tmp_path / "assets")


def test_formal_build_rejects_local_tag_missing_from_remote(
    release_builder, tmp_path
):
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


def test_formal_build_rejects_local_tag_that_disagrees_with_remote(
    release_builder, tmp_path
):
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


def test_ci_uses_full_tag_checkout_and_blocking_windows_matrix():
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
    assert 'python-version == \'3.9\'' in workflow
    assert 'python-version == \'3.8\'' not in workflow
    assert "windows-2025" in workflow
    assert '"3.10"' in workflow
    assert '"3.12"' in workflow
    assert '"3.14"' in workflow
    assert "continue-on-error" not in workflow
    assert "Windows experimental atomic no-replace probe passed" not in workflow
    windows_job = workflow.split("\n  windows:", 1)[1].split("\n  quality:", 1)[0]
    assert "runs-on: windows-2025" in windows_job
    assert "python -m py_compile codex-instruct.py" in windows_job
    assert "python -m pytest -p no:cacheprovider -q tests" in windows_job
    quality_job = workflow.split("\n  quality:", 1)[1]
    assert "fetch-depth: 0" in quality_job
    assert "fetch-tags: true" in quality_job
    assert "rev-parse --is-shallow-repository" in quality_job
    assert 'release_tag="v$(tr -d' in workflow
    assert 'source_commit="$(git rev-parse --verify \'HEAD^{commit}\')"' in workflow
    assert 'if [ "$tag_commit" != "$source_commit" ]; then' in workflow
    assert "Release builder failed for an unexpected reason" in workflow
    assert "correctly refused the conflicting candidate" in workflow
    assert "--source-commit \"$source_commit\"" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow
    assert "--fail-under=81" in workflow

    release_workflow = (
        REPO_ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")
    assert 'tags:\n      - "v*.*.*"' in release_workflow
    assert "uses: ./.github/workflows/tests.yml" in release_workflow
    assert "needs:\n      - blocking-tests" in release_workflow
    assert "fetch-depth: 0" in release_workflow
    assert "fetch-tags: true" in release_workflow
    assert "persist-credentials: false" in release_workflow
    assert 'refs/tags/${tag}^{commit}' in release_workflow
    assert 'expected_tag="v${version}"' in release_workflow
    assert "Formal releases require an annotated tag object" in release_workflow
    assert "WINDOWS_FRESH_DEPLOYMENT_POLICY" in release_workflow
    assert "RECOVERY_ONLY|EXPLICIT_BETA" in release_workflow
    assert "release-first" in release_workflow
    assert "release-second" in release_workflow
    assert "diff -u" in release_workflow
    assert "cmp \"$first/$asset\" \"$second/$asset\"" in release_workflow
    assert "sha256sum --check SHA256SUMS" in release_workflow
    assert "gh release create" in release_workflow
    assert "gh release upload" in release_workflow
    assert "--draft" in release_workflow
    assert ".assets[] | [.name, .digest]" in release_workflow
    assert 'git cat-file blob "${head_commit}:${notes}"' in release_workflow
    assert 'gh release edit "$tag"' in release_workflow
    assert "--draft=false" in release_workflow
    assert "--clobber" not in release_workflow

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pull_request_template = (
        REPO_ROOT / ".github" / "pull_request_template.md"
    ).read_text(encoding="utf-8")
    assert "fail_under = 81" in pyproject
    assert "branch coverage ≥ 81%" in pull_request_template
    assert "branch coverage ≥ 80%" not in pull_request_template
    assert "scripts/build_release.py v0.1.0" not in pull_request_template
    assert 'RELEASE_TAG="v$(tr -d' in pull_request_template
    assert 'SOURCE_COMMIT="$(git rev-parse --verify \'HEAD^{commit}\')"' in (
        pull_request_template
    )

    quality_requirements = (REPO_ROOT / "requirements-quality.txt").read_text(
        encoding="ascii"
    )
    assert quality_requirements.splitlines() == [
        "coverage[toml]==7.10.7",
        "pytest==8.4.2",
        "ruff==0.15.21",
    ]

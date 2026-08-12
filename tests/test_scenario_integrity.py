import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_integrity", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _target(tmp_path, name="target"):
    target = (tmp_path / name).resolve()
    target.mkdir()
    return target


def _deploy(target):
    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest_path = target / ".codex-keysmith" / "scenario-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    deployment_id = next(iter(manifest["deployments"]))
    return deployment_id, manifest_path, manifest


def _copy_scenario_root(tmp_path):
    root = tmp_path / "scenario library"
    shutil.copytree(SCENARIO_ROOT, root)
    return root.resolve()


def _refresh_checksums(root):
    package = root / "example_fixture"
    data = json.loads((package / "scenario.json").read_text(encoding="utf-8"))
    import hashlib

    data["checksums"] = {
        relative: hashlib.sha256((package / relative).read_bytes()).hexdigest()
        for relative in data["checksums"]
    }
    (package / "scenario.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_status_and_uninstall_fail_closed_on_payload_drift(tmp_path):
    target = _target(tmp_path)
    deployment_id, _manifest_path, manifest = _deploy(target)
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id]["root"]
    task = payload / "task.md"
    task.write_text("concurrent user content\n", encoding="utf-8")

    status = _run("--scenario-status", "--target-dir", target)
    uninstall = _run(
        "--scenario-uninstall",
        deployment_id,
        "--target-dir",
        target,
        "--yes",
    )

    assert status.returncode == 1
    assert "state=conflict" in status.stdout
    assert uninstall.returncode == 1
    assert task.read_text(encoding="utf-8") == "concurrent user content\n"
    assert payload.is_dir()


def test_status_rejects_extra_payload_member(tmp_path):
    target = _target(tmp_path)
    deployment_id, _manifest_path, manifest = _deploy(target)
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id]["root"]
    (payload / "extra.txt").write_text("user\n", encoding="utf-8")

    status = _run("--scenario-status", "--target-dir", target)

    assert status.returncode == 1
    assert "payload members drifted" in status.stdout
    assert (payload / "extra.txt").read_text(encoding="utf-8") == "user\n"


@pytest.mark.parametrize(
    "relative",
    ["__pycache__/evil.pyc", "generated.pyo"],
)
def test_status_and_uninstall_reject_payload_bytecode_artifacts(
    tmp_path,
    relative,
):
    target = _target(tmp_path)
    deployment_id, manifest_path, manifest = _deploy(target)
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id][
        "root"
    ]
    artifact = payload / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"unowned bytecode\n")
    manifest_before = manifest_path.read_bytes()

    status = _run("--scenario-status", "--target-dir", target)
    uninstall = _run(
        "--scenario-uninstall",
        deployment_id,
        "--target-dir",
        target,
        "--yes",
    )

    assert status.returncode == 1
    assert "payload members drifted" in status.stdout
    assert uninstall.returncode == 1
    assert "payload members drifted" in uninstall.stdout
    assert artifact.read_bytes() == b"unowned bytecode\n"
    assert manifest_path.read_bytes() == manifest_before
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))


def test_deploy_fails_closed_when_an_existing_payload_drifted(tmp_path):
    target = _target(tmp_path)
    deployment_id, _manifest_path, manifest = _deploy(target)
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id]["root"]
    task = payload / "task.md"
    task.write_text("drifted\n", encoding="utf-8")
    before = json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    )

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )

    assert result.returncode == 1
    assert "existing scenario deployment drifted" in result.stdout
    assert json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    ) == before
    assert task.read_text(encoding="utf-8") == "drifted\n"


def test_deploy_fails_closed_on_unowned_payload_root(tmp_path):
    target = _target(tmp_path)
    _deployment_id, _manifest_path, _manifest = _deploy(target)
    orphan = target / ".codex-keysmith" / "scenarios" / ("a" * 32)
    orphan.mkdir()
    (orphan / "user.txt").write_text("keep\n", encoding="utf-8")

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )

    assert result.returncode == 1
    assert "unowned or missing roots" in result.stdout
    assert (orphan / "user.txt").read_text(encoding="utf-8") == "keep\n"


def test_deploy_fails_closed_on_unknown_control_member(tmp_path):
    target = _target(tmp_path)
    _deployment_id, _manifest_path, _manifest = _deploy(target)
    unknown = target / ".codex-keysmith" / "user-data.txt"
    unknown.write_text("keep\n", encoding="utf-8")

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )

    assert result.returncode == 1
    assert "unknown members" in result.stdout
    assert unknown.read_text(encoding="utf-8") == "keep\n"


def test_status_reports_empty_control_directory_as_not_installed(tmp_path):
    target = _target(tmp_path)
    (target / ".codex-keysmith").mkdir()

    status = _run("--scenario-status", "--target-dir", target)

    assert status.returncode == 0, status.stdout + status.stderr
    assert "not-installed" in status.stdout


def test_deployment_id_collision_preserves_existing_manifest_and_payload(
    tmp_path,
    monkeypatch,
):
    target = _target(tmp_path)
    deployment_id, manifest_path, manifest = _deploy(target)
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id]["root"]
    before_manifest = manifest_path.read_bytes()
    before_files = {
        path.relative_to(payload).as_posix(): path.read_bytes()
        for path in payload.rglob("*")
        if path.is_file()
    }
    colliding = uuid.UUID(hex=deployment_id)
    monkeypatch.setattr(codex_instruct.uuid, "uuid4", lambda: colliding)
    package = codex_instruct.load_scenario_package(
        codex_instruct.resolve_scenario_root(str(SCENARIO_ROOT.resolve())),
        "example_fixture",
    )

    with pytest.raises(codex_instruct.HooksConflict, match="already exists"):
        codex_instruct.deploy_scenario(target, package, True)

    assert manifest_path.read_bytes() == before_manifest
    assert {
        path.relative_to(payload).as_posix(): path.read_bytes()
        for path in payload.rglob("*")
        if path.is_file()
    } == before_files
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))


def test_deploy_rejects_package_root_rebinding_after_load(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    original = package.root.with_name("original-example-fixture")
    real_lock_enter = codex_instruct._DirectoryLockSet.__enter__

    def rebind_after_lock(lock_set):
        entered = real_lock_enter(lock_set)
        try:
            package.root.rename(original)
        except BaseException:
            # Windows deliberately pins locked directories against rename.
            lock_set._release()
            raise
        shutil.copytree(original, package.root)
        return entered

    monkeypatch.setattr(
        codex_instruct._DirectoryLockSet,
        "__enter__",
        rebind_after_lock,
    )

    if os.name == "nt":
        with pytest.raises(PermissionError) as caught:
            codex_instruct.deploy_scenario(target, package, True)
        assert caught.value.winerror == 32
    else:
        with pytest.raises(
            codex_instruct.HooksConflict,
            match="package root identity changed",
        ):
            codex_instruct.deploy_scenario(target, package, True)

    assert not (target / ".codex-keysmith").exists()


def test_deploy_rejects_package_root_rebinding_before_lock_setup(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    original = package.root.with_name("original-example-fixture")
    package.root.rename(original)
    shutil.copytree(original, package.root)
    lock_attempted = False

    def reject_lock(_paths):
        nonlocal lock_attempted
        lock_attempted = True
        raise AssertionError("stale package root must be rejected before lock setup")

    monkeypatch.setattr(codex_instruct, "_DirectoryLockSet", reject_lock)

    with pytest.raises(
        codex_instruct.HooksConflict,
        match="package root identity changed before deployment",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert not lock_attempted
    assert not (target / ".codex-keysmith").exists()


@pytest.mark.parametrize(
    "relation",
    ["same", "child", "library-root", "library-child", "library-parent"],
)
def test_deploy_rejects_target_overlapping_scenario_source(tmp_path, relation):
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    if relation == "same":
        target = package.root
    elif relation == "child":
        target = package.root / "target"
        target.mkdir()
    elif relation == "library-root":
        target = root
    elif relation == "library-child":
        target = root / "another-target"
        target.mkdir()
    else:
        target = root.parent

    with pytest.raises(
        codex_instruct.HooksConflict,
        match="target overlaps the scenario source library",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert not (target / ".codex-keysmith").exists()


def test_scenario_overlap_uses_directory_identity_for_path_aliases(tmp_path):
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    alias = Path(str(package.root).swapcase())
    if not alias.is_dir():
        pytest.skip("filesystem is case-sensitive")

    assert codex_instruct._directory_identity(alias) == package.root_identity
    assert codex_instruct._scenario_paths_overlap(alias, package.library_root)


def test_deploy_accepts_case_alias_for_scenario_library_path(tmp_path):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    alias = Path(str(root).swapcase())
    if not alias.is_dir():
        pytest.skip("filesystem is case-sensitive")
    package = codex_instruct.load_scenario_package(alias, "example_fixture")

    deployment_id = codex_instruct.deploy_scenario(target, package, True)

    assert deployment_id is not None
    status = codex_instruct.show_scenario_status(target)
    assert status == 0


def test_scenario_package_match_ignores_equivalent_source_path_spelling(tmp_path):
    root = _copy_scenario_root(tmp_path)
    alias = Path(str(root).swapcase())
    if not alias.is_dir():
        pytest.skip("filesystem is case-sensitive")

    original = codex_instruct.load_scenario_package(alias, "example_fixture")
    refreshed = codex_instruct.load_scenario_package(root, "example_fixture")

    assert str(original.library_root) != str(refreshed.library_root)
    assert str(original.root) != str(refreshed.root)
    assert codex_instruct._scenario_package_matches(refreshed, original)


def test_deploy_rejects_library_root_rebinding_before_lock_setup(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    original = root.with_name("original-scenario-library")
    root.rename(original)
    shutil.copytree(original, root)
    lock_attempted = False

    def reject_lock(_paths):
        nonlocal lock_attempted
        lock_attempted = True
        raise AssertionError("stale library root must be rejected before lock setup")

    monkeypatch.setattr(codex_instruct, "_DirectoryLockSet", reject_lock)

    with pytest.raises(
        codex_instruct.HooksConflict,
        match="library root identity changed before deployment",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert not lock_attempted
    assert not (target / ".codex-keysmith").exists()


def test_deploy_rejects_library_root_rebinding_after_lock(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    original = root.with_name("original-scenario-library")
    real_lock_enter = codex_instruct._DirectoryLockSet.__enter__

    def rebind_after_lock(lock_set):
        entered = real_lock_enter(lock_set)
        try:
            root.rename(original)
        except BaseException:
            # Windows deliberately pins locked directories against rename.
            lock_set._release()
            raise
        shutil.copytree(original, root)
        return entered

    monkeypatch.setattr(
        codex_instruct._DirectoryLockSet,
        "__enter__",
        rebind_after_lock,
    )

    if os.name == "nt":
        with pytest.raises(PermissionError) as caught:
            codex_instruct.deploy_scenario(target, package, True)
        assert caught.value.winerror == 32
    else:
        with pytest.raises(
            codex_instruct.HooksConflict,
            match="library root identity changed before deployment",
        ):
            codex_instruct.deploy_scenario(target, package, True)

    assert not (target / ".codex-keysmith").exists()


def test_deploy_rejects_package_member_added_after_load(tmp_path):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    added = package.root / "late-added.txt"
    added.write_text("late\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="checksums must cover every deployed file",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert added.read_text(encoding="utf-8") == "late\n"
    assert not (target / ".codex-keysmith").exists()


def test_deploy_rejects_package_member_added_during_staging(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    added = package.root / "late-during-staging.txt"
    real_copy = codex_instruct._scenario_copy_regular_file
    copied = False

    def add_member_after_first_copy(source, destination, expected_sha256):
        nonlocal copied
        real_copy(source, destination, expected_sha256)
        if not copied:
            copied = True
            added.write_text("late\n", encoding="utf-8")

    monkeypatch.setattr(
        codex_instruct,
        "_scenario_copy_regular_file",
        add_member_after_first_copy,
    )

    with pytest.raises(
        ValueError,
        match="checksums must cover every deployed file",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert added.read_text(encoding="utf-8") == "late\n"
    assert not (target / ".codex-keysmith").exists()


def test_deploy_rejects_package_member_added_after_staging(tmp_path, monkeypatch):
    target = _target(tmp_path)
    root = _copy_scenario_root(tmp_path)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    added = package.root / "late-after-staging.txt"
    real_verify = codex_instruct._scenario_verify_payload
    verified_staging = False

    def add_member_after_staging(payload_root, expected_identity, expected_files):
        nonlocal verified_staging
        real_verify(payload_root, expected_identity, expected_files)
        if payload_root.name == codex_instruct.SCENARIO_PAYLOAD_STAGING_DIRNAME:
            verified_staging = True
        elif verified_staging and not added.exists():
            added.write_text("late\n", encoding="utf-8")

    monkeypatch.setattr(
        codex_instruct,
        "_scenario_verify_payload",
        add_member_after_staging,
    )

    with pytest.raises(
        ValueError,
        match="checksums must cover every deployed file",
    ):
        codex_instruct.deploy_scenario(target, package, True)

    assert added.read_text(encoding="utf-8") == "late\n"
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))
    scenarios = target / ".codex-keysmith" / "scenarios"
    assert not scenarios.exists() or not list(scenarios.iterdir())


@pytest.mark.parametrize("operation", ["deploy", "uninstall"])
def test_scenario_write_gate_preserves_control_enumeration_failure(
    tmp_path,
    monkeypatch,
    operation,
):
    target = _target(tmp_path, f"{operation}-control-enumeration")
    deployment_id, _manifest_path, _manifest = _deploy(target)
    control = target / ".codex-keysmith"
    real_list = codex_instruct._FILESYSTEM.list_directory_names

    def fail_control(path):
        if path == control:
            raise FileNotFoundError("scenario control directory disappeared")
        return real_list(path)

    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "list_directory_names",
        fail_control,
    )

    with pytest.raises(FileNotFoundError, match="control directory disappeared"):
        if operation == "deploy":
            package = codex_instruct.load_scenario_package(
                SCENARIO_ROOT.resolve(),
                "example_fixture",
            )
            codex_instruct.deploy_scenario(target, package, True)
        else:
            codex_instruct.uninstall_scenario(target, deployment_id, True)

    assert control.is_dir()


def test_target_path_rebinding_is_rejected_and_preserved(tmp_path):
    target = _target(tmp_path, "original")
    _deploy(target)
    moved = tmp_path / "moved"
    target.rename(moved)
    target.mkdir()
    victim = target / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    shutil.copytree(moved / ".codex-keysmith", target / ".codex-keysmith")

    status = _run("--scenario-status", "--target-dir", target.resolve())

    assert status.returncode == 1
    assert "target identity changed" in status.stdout
    assert victim.read_text(encoding="utf-8") == "keep\n"
    assert (moved / ".codex-keysmith").is_dir()


@pytest.mark.parametrize("node_kind", ["symlink", "fifo"])
def test_deploy_rejects_abnormal_control_node(tmp_path, node_kind):
    target = _target(tmp_path)
    control = target / ".codex-keysmith"
    if node_kind == "symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            control.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    elif node_kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO unavailable")
        os.mkfifo(control)
    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )

    assert result.returncode == 1
    assert "not a directory" in result.stdout
    assert control.exists() or control.is_symlink()


def test_deploy_rejects_socket_control_node(tmp_path):
    if sys.platform == "win32":
        pytest.skip("Windows filesystem paths cannot host AF_UNIX socket nodes")
    import socket

    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix sockets unavailable")
    target = Path(tempfile.mkdtemp(prefix="ks-sock-", dir="/tmp")).resolve()
    control = target / ".codex-keysmith"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(control))
        result = _run(
            "--deploy-scenario",
            "example_fixture",
            "--target-dir",
            target,
            "--scenario-root",
            SCENARIO_ROOT.resolve(),
            "--yes",
        )
        assert result.returncode == 1
        assert "not a directory" in result.stdout
    finally:
        server.close()
        if control.exists():
            control.unlink()
        target.rmdir()


def test_package_checksum_drift_is_rejected(tmp_path):
    root = _copy_scenario_root(tmp_path)
    task = root / "example_fixture" / "task.md"
    task.write_text("tampered\n", encoding="utf-8")
    target = _target(tmp_path)

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        root,
    )

    assert result.returncode == 1
    assert "checksum mismatch" in result.stdout
    assert not (target / ".codex-keysmith").exists()


def test_package_member_symlink_is_rejected(tmp_path):
    root = _copy_scenario_root(tmp_path)
    task = root / "example_fixture" / "task.md"
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    task.unlink()
    try:
        task.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    target = _target(tmp_path)

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        root,
    )

    assert result.returncode == 1
    assert "not a regular file" in result.stdout
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_package_checksums_must_cover_every_deployed_file(tmp_path):
    root = _copy_scenario_root(tmp_path)
    package = root / "example_fixture"
    (package / "new.txt").write_text("new\n", encoding="utf-8")
    target = _target(tmp_path)

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        root,
    )

    assert result.returncode == 1
    assert "checksums must cover every deployed file" in result.stdout


def test_manifest_abnormal_node_is_conflict(tmp_path):
    target = _target(tmp_path)
    _deployment_id, manifest_path, _manifest = _deploy(target)
    manifest_path.unlink()
    manifest_path.mkdir()

    status = _run("--scenario-status", "--target-dir", target)

    assert status.returncode == 1
    assert "manifest is not a regular file" in status.stdout


@pytest.mark.parametrize(
    "mutate,detail",
    [
        (lambda data, _deployment_id: data.update(schema_version=2), "schema"),
        (lambda data, _deployment_id: data.update(extra=True), "root fields"),
        (lambda data, _deployment_id: data.update(target=[]), "target fields"),
        (lambda data, _deployment_id: data["target"].update(relative="elsewhere"), "target"),
        (lambda data, _deployment_id: data.update(storage=[]), "storage fields"),
        (lambda data, _deployment_id: data["storage"].update(root="other"), "storage"),
        (lambda data, _deployment_id: data.update(deployments=[]), "deployments"),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                deployment_id="b" * 32
            ),
            "deployment id",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                extra=True
            ),
            "record fields",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                scenario_id="Bad-Id"
            ),
            "scenario id",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                scenario_version="1"
            ),
            "version",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                source_digest="x"
            ),
            "source digest",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                source_digest="0" * 64
            ),
            "source digest",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                root="scenarios/other"
            ),
            "root",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                deployed_at=""
            ),
            "timestamp",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                deployed_at="2026-08-12 12:00:00"
            ),
            "timestamp",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                deployed_at="2026-02-30T12:00:00Z"
            ),
            "timestamp",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id].update(
                files={}
            ),
            "files",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id]["files"].update(
                {"bad\\path": "0" * 64}
            ),
            "forward-slash",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id]["files"].update(
                {"TASK.MD": data["deployments"][deployment_id]["files"]["task.md"]}
            ),
            "collide",
        ),
        (
            lambda data, deployment_id: data["deployments"][deployment_id]["files"].update(
                {"task.md": "invalid"}
            ),
            "digest",
        ),
    ],
)
def test_manifest_contract_tampering_is_conflict_and_preserved(
    tmp_path,
    mutate,
    detail,
):
    target = _target(tmp_path)
    deployment_id, manifest_path, manifest = _deploy(target)
    mutate(manifest, deployment_id)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = manifest_path.read_bytes()

    status = _run("--scenario-status", "--target-dir", target)

    assert status.returncode == 1
    assert detail in status.stdout
    assert manifest_path.read_bytes() == before

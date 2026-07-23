import ctypes
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import types
from ctypes import wintypes
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
WINDOWS_INHERITED_ACE = 0x10
spec = importlib.util.spec_from_file_location("codex_instruct_windows_fs", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _make_codex_dir(tmp_path, name="codex dir 中文"):
    codex_dir = tmp_path / name
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6"\n', encoding="utf-8")
    return codex_dir


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _make_windows_junction(link, target):
    created = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        text=True,
        capture_output=True,
    )
    assert created.returncode == 0, created.stdout + created.stderr


def _apply_windows_recovery_acl(path, sddl):
    backend = codex_instruct._FILESYSTEM
    descriptor = wintypes.LPVOID()
    descriptor_size = wintypes.DWORD()
    if not backend.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        backend._SDDL_REVISION_1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        backend._raise_last_error("cannot build inherited recovery fixture ACL", path)

    handle = 0
    try:
        dacl_present = wintypes.BOOL()
        dacl_defaulted = wintypes.BOOL()
        dacl = wintypes.LPVOID()
        if not backend.advapi32.GetSecurityDescriptorDacl(
            descriptor,
            ctypes.byref(dacl_present),
            ctypes.byref(dacl),
            ctypes.byref(dacl_defaulted),
        ):
            backend._raise_last_error("cannot read inherited recovery fixture ACL", path)
        assert dacl_present.value and dacl.value
        handle = backend._open_handle(
            path,
            backend._READ_CONTROL
            | backend._WRITE_DAC
            | backend._FILE_READ_ATTRIBUTES,
        )
        backend._validate_handle_type(handle, path, is_directory=True)
        backend._validate_ntfs(handle, path)
        security_error = backend.advapi32.SetSecurityInfo(
            handle,
            backend._SE_FILE_OBJECT,
            backend._DACL_SECURITY_INFORMATION
            | backend._PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        if security_error:
            raise OSError(
                security_error,
                "cannot apply inherited recovery fixture ACL: {}: {}".format(
                    path,
                    ctypes.FormatError(security_error).strip(),
                ),
            )
    finally:
        if handle:
            backend.kernel32.CloseHandle(handle)
        backend.kernel32.LocalFree(descriptor)


def _apply_windows_inheritable_recovery_acl(path):
    backend = codex_instruct._FILESYSTEM
    _apply_windows_recovery_acl(
        path,
        "D:P(A;OICI;FA;;;{})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)".format(
            backend._current_sid
        ),
    )


def _read_windows_acl(path):
    backend = codex_instruct._FILESYSTEM
    handle = backend._open_handle(
        path,
        backend._READ_CONTROL | backend._FILE_READ_ATTRIBUTES,
    )
    try:
        return backend._handle_acl(handle, path)
    finally:
        backend.kernel32.CloseHandle(handle)


def _trusted_windows_owner_sids():
    backend = codex_instruct._FILESYSTEM
    owners = {backend._current_sid}
    if backend._current_is_administrator:
        owners.add("S-1-5-32-544")
    return owners


def _create_v010_issue_1_fixture(codex_dir, *, private, journal_sddl=None):
    transaction_id = "d" * 32
    journal_dir = codex_dir / f"{codex_instruct.JOURNAL_PREFIX}{transaction_id}"
    if private:
        codex_instruct._FILESYSTEM.create_private_directory(journal_dir)
    else:
        journal_dir.mkdir(mode=0o777)
        if journal_sddl is not None:
            _apply_windows_recovery_acl(journal_dir, journal_sddl)
    plan = codex_instruct.inspect_directory(codex_dir)
    config_before = codex_instruct._portable_fingerprint(plan.config_fingerprint)
    directories = {
        str(codex_dir.resolve()): {
            "journal_dir": journal_dir.name,
            "journal_identity": codex_instruct._portable_identity(
                codex_instruct._directory_identity(journal_dir)
            ),
            "resources": {
                "config": {
                    "path": "config.toml",
                    "before": config_before,
                    "snapshot": "snapshot-config",
                    "allowed_absent": False,
                    "allowed_sha256": [
                        hashlib.sha256(
                            plan.updated_config_content.encode("utf-8")
                        ).hexdigest()
                    ],
                    "allowed_portable": [],
                },
                "md": {
                    "path": codex_instruct.DEFAULT_MD_FILENAME,
                    "before": None,
                    "snapshot": None,
                    "allowed_absent": False,
                    "allowed_sha256": [
                        hashlib.sha256(
                            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD.encode("utf-8")
                        ).hexdigest()
                    ],
                    "allowed_portable": [],
                },
                "manifest": {
                    "path": codex_instruct.MANIFEST_FILENAME,
                    "before": None,
                    "snapshot": None,
                    "allowed_absent": False,
                    "allowed_sha256": [],
                    "allowed_portable": [],
                },
            },
            "residues": [],
        }
    }
    base = {
        "schema_version": 1,
        "operation": "deploy",
        "transaction_id": transaction_id,
        "phase": "initializing",
        "participants": [str(codex_dir.resolve())],
        "directories": directories,
    }
    intent = json.loads(json.dumps(base))
    intent.pop("phase")
    intent_directory = intent["directories"][str(codex_dir.resolve())]
    intent_directory.pop("residues")
    intent_directory["resources"]["manifest"]["allowed_sha256"] = []
    journal = dict(base)
    journal["owner_directory"] = str(codex_dir.resolve())
    for filename, data in (
        (codex_instruct.INTENT_FILENAME, intent),
        (codex_instruct.JOURNAL_FILENAME, journal),
    ):
        path = journal_dir / filename
        if private:
            codex_instruct._write_exclusive_private_json(path, data)
        else:
            path.write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return journal_dir


def test_platform_filesystem_contract_is_centralized():
    backend = codex_instruct._FILESYSTEM
    for method in (
        "create_private_directory",
        "create_private_file",
        "resolve_directory",
        "verify_recovery_directory_security",
        "open_verified_owned_directory",
        "remove_verified_member",
        "remove_verified_directory",
        "set_file_times",
        "apply_private_file_security",
        "apply_private_path_security",
        "atomic_rename_no_replace",
        "replace_atomic",
        "flush_directory",
        "directory_lock_key",
        "pin_directory_for_lock",
        "release_pinned_directory",
        "remove_verified_file",
    ):
        assert callable(getattr(backend, method))

    cleanup_source = inspect.getsource(codex_instruct._open_verified_owned_directory)
    assert "os.listdir(descriptor)" not in cleanup_source
    assert "dir_fd=descriptor" not in cleanup_source

    module_source = MODULE_PATH.read_text(encoding="utf-8")
    backend_start = module_source.index("class _PosixFilesystemBackend")
    backend_end = module_source.index("_FILESYSTEM =", backend_start)
    outside_backend = module_source[:backend_start] + module_source[backend_end:]
    assert "os.utime(" not in outside_backend
    assert "os.fchmod(" not in outside_backend


def test_deploy_snapshot_failure_preserves_primary_exception(
    tmp_path,
    monkeypatch,
    capsys,
):
    codex_dir = _make_codex_dir(tmp_path)
    plan = codex_instruct.inspect_directory(codex_dir)
    state = codex_instruct.DeploymentState(codex_dir, deployment_id="a" * 32)

    def fail_snapshot(_source, _destination):
        raise RuntimeError("primary snapshot failure")

    def fail_cleanup(*_args, **_kwargs):
        raise PermissionError("secondary cleanup failure")

    monkeypatch.setattr(codex_instruct, "_copy_snapshot", fail_snapshot)
    monkeypatch.setattr(codex_instruct, "_safe_remove_owned_directory", fail_cleanup)

    with pytest.raises(RuntimeError, match="primary snapshot failure"):
        codex_instruct._create_deployment_journals(
            [state],
            [plan],
            codex_instruct.DEFAULT_MD_FILENAME,
            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
            False,
        )

    assert "secondary cleanup failure" in capsys.readouterr().err


def test_uninstall_snapshot_failure_preserves_primary_exception(
    tmp_path,
    monkeypatch,
    capsys,
):
    codex_dir = _make_codex_dir(tmp_path, "uninstall 中文")
    deployed = _run("--codex-dir", codex_dir, "--yes")
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    plan = codex_instruct.inspect_uninstall_directory(codex_dir)
    state = codex_instruct.UninstallState(plan=plan, deployment_id="b" * 32)

    def fail_snapshot(_source, _destination):
        raise RuntimeError("primary uninstall snapshot failure")

    def fail_cleanup(*_args, **_kwargs):
        raise PermissionError("secondary uninstall cleanup failure")

    monkeypatch.setattr(codex_instruct, "_copy_snapshot", fail_snapshot)
    monkeypatch.setattr(codex_instruct, "_safe_remove_owned_directory", fail_cleanup)

    with pytest.raises(RuntimeError, match="primary uninstall snapshot failure"):
        codex_instruct._create_uninstall_journals([state], "20260721_120000")

    assert "secondary uninstall cleanup failure" in capsys.readouterr().err


@pytest.mark.parametrize("operation", ["deploy", "uninstall"])
def test_journal_directory_flush_failure_removes_empty_node(
    tmp_path,
    monkeypatch,
    operation,
):
    codex_dir = _make_codex_dir(tmp_path, f"{operation} flush failure")
    if operation == "deploy":
        plan = codex_instruct.inspect_directory(codex_dir)
        state = codex_instruct.DeploymentState(codex_dir, deployment_id="f" * 32)

        def create():
            codex_instruct._create_deployment_journals(
                [state],
                [plan],
                codex_instruct.DEFAULT_MD_FILENAME,
                codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
                False,
            )

    else:
        deployed = _run("--codex-dir", codex_dir, "--yes")
        assert deployed.returncode == 0, deployed.stdout + deployed.stderr
        plan = codex_instruct.inspect_uninstall_directory(codex_dir)
        state = codex_instruct.UninstallState(plan=plan, deployment_id="f" * 32)

        def create():
            codex_instruct._create_uninstall_journals([state], "20260721_120000")

    real_flush = codex_instruct._FILESYSTEM.flush_directory
    failed = False

    def fail_first_parent_flush(path):
        nonlocal failed
        if Path(path) == codex_dir and not failed:
            failed = True
            raise OSError("primary create persistence failure")
        real_flush(path)

    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "flush_directory",
        fail_first_parent_flush,
    )

    with pytest.raises(OSError, match="primary create persistence failure"):
        create()

    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_issue_1_initializing_intent_and_journal_recover_to_ready(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "Issue 1 中文")
    before = {path.name: path.read_bytes() for path in codex_dir.iterdir() if path.is_file()}
    plan = codex_instruct.inspect_directory(codex_dir)
    state = codex_instruct.DeploymentState(codex_dir, deployment_id="c" * 32)
    codex_instruct._create_deployment_journals(
        [state],
        [plan],
        codex_instruct.DEFAULT_MD_FILENAME,
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        False,
    )
    journal_dir = state.journal_dir
    assert journal_dir is not None
    for entry in list(journal_dir.iterdir()):
        if entry.name not in {
            codex_instruct.INTENT_FILENAME,
            codex_instruct.JOURNAL_FILENAME,
        }:
            entry.unlink()
    journal_path = journal_dir / codex_instruct.JOURNAL_FILENAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["phase"] = "initializing"
    codex_instruct._atomic_write_private_json(journal_path, journal)

    blocked = _run("--codex-dir", codex_dir, "--status")
    assert blocked.returncode == 1
    assert "deployability: blocked" in blocked.stdout.lower()

    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert journal_dir.exists()

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not journal_dir.exists()
    assert before == {
        path.name: path.read_bytes() for path in codex_dir.iterdir() if path.is_file()
    }

    ready = _run("--codex-dir", codex_dir, "--status")
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert "structural health: healthy" in ready.stdout.lower()
    assert "deployability: ready" in ready.stdout.lower()


def test_empty_private_initializing_journal_recovers_to_ready(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "empty initializing journal")
    journal_dir = codex_dir / f"{codex_instruct.JOURNAL_PREFIX}{'a' * 32}"
    codex_instruct._FILESYSTEM.create_private_directory(journal_dir)

    blocked = _run("--codex-dir", codex_dir, "--status")
    assert blocked.returncode == 1
    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert journal_dir.exists()

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not journal_dir.exists()
    ready = _run("--codex-dir", codex_dir, "--status")
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert "deployability: ready" in ready.stdout.lower()


def test_issue_1_v010_initializing_fixture_recovers_to_ready(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "v0.1.0 Issue 1 中文")
    journal_dir = _create_v010_issue_1_fixture(codex_dir, private=True)

    blocked = _run("--codex-dir", codex_dir, "--status")
    assert blocked.returncode == 1
    assert "deployability: blocked" in blocked.stdout.lower()

    before_preview = {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    }
    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    } == before_preview

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not journal_dir.exists()
    ready = _run("--codex-dir", codex_dir, "--status")
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert "deployability: ready" in ready.stdout.lower()


@pytest.mark.skipif(os.name != "nt", reason="Windows v0.1.0 inherited ACL fixture")
def test_issue_1_v010_inherited_acl_fixture_recovers_to_ready(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "v0.1.0 inherited ACL Issue 1")
    backend = codex_instruct._FILESYSTEM
    _apply_windows_inheritable_recovery_acl(codex_dir)
    journal_dir = _create_v010_issue_1_fixture(codex_dir, private=False)
    protected, owner_sid, principals = _read_windows_acl(journal_dir)
    assert not protected
    assert owner_sid in _trusted_windows_owner_sids()
    assert set(principals) == {
        backend._current_sid,
        "S-1-5-18",
        "S-1-5-32-544",
    }
    assert all(
        mask == backend._FILE_ALL_ACCESS and flags & WINDOWS_INHERITED_ACE
        for mask, flags in principals.values()
    )
    with pytest.raises(codex_instruct.HooksConflict, match="protected"):
        backend.verify_private_security(journal_dir, is_directory=True)
    backend.verify_recovery_directory_security(journal_dir)

    blocked = _run("--codex-dir", codex_dir, "--status")
    assert blocked.returncode == 1
    assert "deployability: blocked" in blocked.stdout.lower()
    before_preview = {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    }

    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    } == before_preview

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not journal_dir.exists()
    ready = _run("--codex-dir", codex_dir, "--status")
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert "deployability: ready" in ready.stdout.lower()


@pytest.mark.skipif(os.name != "nt", reason="Windows v0.1.0 CPython ACL fixture")
def test_issue_1_v010_cpython_0700_acl_fixture_recovers_to_ready(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "v0.1.0 CPython 0700 Issue 1")
    backend = codex_instruct._FILESYSTEM
    journal_dir = _create_v010_issue_1_fixture(
        codex_dir,
        private=False,
        journal_sddl="D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)",
    )

    protected, owner_sid, principals = _read_windows_acl(journal_dir)
    assert protected
    assert owner_sid in _trusted_windows_owner_sids()
    assert set(principals) == {"S-1-3-4", "S-1-5-18", "S-1-5-32-544"}
    assert all(
        mask == backend._FILE_ALL_ACCESS for mask, _flags in principals.values()
    )
    for filename in (codex_instruct.INTENT_FILENAME, codex_instruct.JOURNAL_FILENAME):
        member_protected, member_owner, member_principals = _read_windows_acl(
            journal_dir / filename
        )
        assert not member_protected
        assert member_owner in _trusted_windows_owner_sids()
        assert set(member_principals) == set(principals)
        assert all(
            mask == backend._FILE_ALL_ACCESS and flags & WINDOWS_INHERITED_ACE
            for mask, flags in member_principals.values()
        )

    backend.verify_recovery_directory_security(journal_dir)
    blocked = _run("--codex-dir", codex_dir, "--status")
    assert blocked.returncode == 1
    assert "deployability: blocked" in blocked.stdout.lower()

    before_preview = {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    }
    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert {
        str(path.relative_to(codex_dir)): (
            "directory" if path.is_dir() else path.read_bytes()
        )
        for path in codex_dir.rglob("*")
    } == before_preview

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not journal_dir.exists()
    ready = _run("--codex-dir", codex_dir, "--status")
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert "deployability: ready" in ready.stdout.lower()


@pytest.mark.parametrize(
    ("owner_sid", "principals", "current_is_administrator", "allowed"),
    [
        ("CURRENT", {"CURRENT"}, False, True),
        ("CURRENT", {"CURRENT", "S-1-5-18", "S-1-5-32-544"}, False, True),
        ("S-1-5-32-544", {"CURRENT", "S-1-5-18"}, True, True),
        ("S-1-5-32-544", {"CURRENT", "S-1-5-18"}, False, False),
        (
            "CURRENT",
            {"S-1-3-4", "S-1-5-18", "S-1-5-32-544"},
            False,
            True,
        ),
        (
            "S-1-5-32-544",
            {"S-1-3-4", "S-1-5-18", "S-1-5-32-544"},
            True,
            True,
        ),
        (
            "S-1-5-32-544",
            {"S-1-3-4", "S-1-5-18", "S-1-5-32-544"},
            False,
            False,
        ),
        (
            "FOREIGN",
            {"S-1-3-4", "S-1-5-18", "S-1-5-32-544"},
            True,
            False,
        ),
        (
            "CURRENT",
            {"S-1-3-4", "S-1-5-18", "S-1-5-32-544", "S-1-1-0"},
            False,
            False,
        ),
        ("CURRENT", {"S-1-5-18", "S-1-5-32-544"}, False, False),
        (
            "CURRENT",
            {"CURRENT", "S-1-3-4", "S-1-5-18", "S-1-5-32-544"},
            False,
            False,
        ),
    ],
)
def test_windows_recovery_acl_principal_shapes(
    owner_sid,
    principals,
    current_is_administrator,
    allowed,
):
    assert (
        codex_instruct._WindowsFilesystemBackend._recovery_acl_principals_allowed(
            "CURRENT",
            owner_sid,
            principals,
            current_is_administrator,
        )
        is allowed
    )


def test_operation_directories_are_identity_deduplicated_and_stably_sorted(tmp_path):
    first = _make_codex_dir(tmp_path, "Z Folder")
    second = _make_codex_dir(tmp_path, "a folder")

    normalized = codex_instruct._normalize_operation_directories(
        [str(first), str(second), str(first / ".")]
    )

    assert len(normalized) == 2
    keys = [item.lock_key for item in normalized]
    assert keys == sorted(keys)
    assert {item.path for item in normalized} == {first.resolve(), second.resolve()}


def test_windows_native_identity_matches_python_portable_device_encoding():
    native = codex_instruct.FileIdentity(0x428342FD, 123)
    portable = codex_instruct.FileIdentity(0xFA428383428342FD, 123)

    assert codex_instruct._WindowsFilesystemBackend._handle_matches_portable_identity(
        native,
        portable,
    )


def test_windows_lock_key_uses_file_id_across_distinct_alias_paths(monkeypatch):
    backend = object.__new__(codex_instruct._WindowsFilesystemBackend)
    handles = iter((101, 102))
    canonical = {
        101: Path("C:/Users/example/Codex"),
        102: Path("X:/Codex"),
    }
    backend.kernel32 = types.SimpleNamespace(CloseHandle=lambda _handle: True)

    def open_components(_path):
        handle = next(handles)
        return canonical[handle], [handle]

    monkeypatch.setattr(
        backend,
        "_open_directory_components",
        open_components,
    )
    monkeypatch.setattr(
        backend,
        "_handle_identity",
        lambda _handle: codex_instruct.FileIdentity(17, 23),
    )
    first_key, first_path = backend.directory_lock_key(Path("C:/alias"))
    second_key, second_path = backend.directory_lock_key(Path("X:/alias"))

    assert first_path != second_path
    assert first_key == second_key == (17, 23)


def test_windows_directory_resolution_pins_all_path_components(monkeypatch):
    backend = object.__new__(codex_instruct._WindowsFilesystemBackend)
    opened = []
    closed = []
    accesses = []
    share_modes = []
    backend.kernel32 = types.SimpleNamespace(
        CloseHandle=lambda handle: closed.append(handle) or True
    )

    def open_handle(path, access, **kwargs):
        handle = len(opened) + 1
        opened.append((handle, Path(path)))
        accesses.append(access)
        share_modes.append(kwargs.get("share_mode"))
        return handle

    monkeypatch.setattr(backend, "_open_handle", open_handle)
    def validate_handle(*_args, **_kwargs):
        assert closed == []

    monkeypatch.setattr(backend, "_validate_handle_type", validate_handle)
    monkeypatch.setattr(backend, "_validate_ntfs", lambda *_args: None)
    monkeypatch.setattr(
        backend,
        "_canonical_path",
        lambda _handle, fallback: fallback,
    )

    resolved = backend.resolve_directory(Path("nested/path"))

    assert resolved.is_absolute()
    assert len(opened) >= 3
    assert closed == [handle for handle, _path in reversed(opened)]
    assert all(
        access
        & (backend._FILE_TRAVERSE | backend._FILE_READ_ATTRIBUTES)
        == (backend._FILE_TRAVERSE | backend._FILE_READ_ATTRIBUTES)
        for access in accesses
    )
    assert set(share_modes) == {
        backend._FILE_SHARE_READ | backend._FILE_SHARE_WRITE
    }


def test_windows_lock_pin_revalidates_reparse_components_after_key_handoff(
    monkeypatch,
):
    backend = object.__new__(codex_instruct._WindowsFilesystemBackend)
    backend.kernel32 = types.SimpleNamespace(CloseHandle=lambda _handle: True)
    calls = 0

    def open_components(_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Path("C:/stable/Codex"), [101]
        raise codex_instruct.HooksConflict("reparse point is not allowed")

    monkeypatch.setattr(backend, "_open_directory_components", open_components)
    monkeypatch.setattr(
        backend,
        "_handle_identity",
        lambda _handle: codex_instruct.FileIdentity(17, 23),
    )

    key, canonical = backend.directory_lock_key(Path("C:/alias/Codex"))

    with pytest.raises(codex_instruct.HooksConflict, match="reparse"):
        backend.pin_directory_for_lock(canonical, key)


def test_verified_file_claim_applies_identity_bound_private_security(
    tmp_path,
    monkeypatch,
):
    transaction_dir = tmp_path / "owned transaction"
    destination = transaction_dir / "claimed"
    secured = []
    fingerprint = codex_instruct.FileFingerprint(
        codex_instruct.FileIdentity(3, 4),
        5,
        6,
        "7" * 64,
    )
    monkeypatch.setitem(
        codex_instruct._OWNED_DIRECTORY_RECORDS,
        str(transaction_dir),
        (codex_instruct.FileIdentity(1, 2), {}),
    )
    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "apply_private_path_security",
        lambda path, expected: secured.append((path, expected)),
    )

    codex_instruct._secure_verified_transaction_claim(
        destination,
        fingerprint,
    )
    assert secured == [(destination, fingerprint)]


def test_windows_private_acl_update_rejects_replaced_claim(monkeypatch):
    backend = object.__new__(codex_instruct._WindowsFilesystemBackend)
    closed = []
    open_kwargs = []
    security_updates = []
    backend.kernel32 = types.SimpleNamespace(
        CloseHandle=lambda handle: closed.append(handle) or True,
        FlushFileBuffers=lambda _handle: True,
    )
    backend.advapi32 = types.SimpleNamespace(
        SetKernelObjectSecurity=lambda *_args: security_updates.append(True) or True,
    )
    backend._security_descriptor = object()

    def open_handle(*_args, **kwargs):
        open_kwargs.append(kwargs)
        return 101

    monkeypatch.setattr(backend, "_open_handle", open_handle)
    monkeypatch.setattr(backend, "_validate_handle_type", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backend, "_validate_ntfs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        backend,
        "_handle_identity",
        lambda _handle: codex_instruct.FileIdentity(5, 6),
    )

    with pytest.raises(codex_instruct.HooksConflict, match="identity changed"):
        backend.apply_private_path_security(
            Path("C:/claimed"),
            codex_instruct.FileFingerprint(
                codex_instruct.FileIdentity(7, 8),
                9,
                10,
                "a" * 64,
            ),
        )

    assert open_kwargs == [{"share_mode": backend._FILE_SHARE_READ}]
    assert security_updates == []
    assert closed == [101]
    source = inspect.getsource(backend.apply_private_path_security)
    assert source.count("_fingerprint_descriptor") == 2


def test_windows_private_acl_update_protects_and_revalidates_dacl():
    source = inspect.getsource(
        codex_instruct._WindowsFilesystemBackend.apply_private_path_security
    )
    assert "_PROTECTED_DACL_SECURITY_INFORMATION" in source
    assert "_verify_handle_private_security" in source


def test_failure_cleanup_contract_preserves_primary_exception(capsys):
    primary = RuntimeError("primary operation failure")

    def cleanup():
        raise PermissionError("secondary cleanup failure")

    codex_instruct._run_cleanup_preserving_primary(
        primary,
        [("test cleanup", cleanup)],
    )

    output = capsys.readouterr().err
    assert "primary operation failure" in output
    assert "secondary cleanup failure" in output


def test_file_fingerprint_cleanup_validation_binds_identity():
    actual = codex_instruct.FileFingerprint(
        codex_instruct.FileIdentity(1, 2),
        3,
        4,
        "a" * 64,
    )
    replaced = codex_instruct.FileFingerprint(
        codex_instruct.FileIdentity(1, 99),
        actual.size,
        actual.modified_ns,
        actual.sha256,
    )

    with pytest.raises(codex_instruct.HooksConflict, match="指纹"):
        codex_instruct._FILESYSTEM._validate_expected_fingerprint(
            Path("owned/member"),
            actual,
            replaced,
        )


def test_windows_verified_delete_handles_deny_writer_sharing():
    for method in (
        codex_instruct._WindowsFilesystemBackend.remove_verified_member,
        codex_instruct._WindowsFilesystemBackend.remove_verified_file,
    ):
        source = inspect.getsource(method)
        assert "share_mode=self._FILE_SHARE_READ" in source
        assert "share_mode=self._FILE_SHARE_READ | self._FILE_SHARE_WRITE" not in source


@pytest.mark.parametrize(
    "function",
    [
        codex_instruct._rollback_owned_file,
        codex_instruct.isolate_hooks,
        codex_instruct.rollback_hooks_isolation,
        codex_instruct.archive_legacy_file,
        codex_instruct._remove_owned_file,
    ],
)
def test_failure_cleanup_paths_use_primary_preserving_guard(function):
    assert "_run_cleanup_preserving_primary" in inspect.getsource(function)


def test_windows_mutation_backend_declares_durable_metadata_contracts():
    backend = codex_instruct._WindowsFilesystemBackend
    rename_source = inspect.getsource(backend.atomic_rename_no_replace)
    assert "_MOVEFILE_WRITE_THROUGH" in rename_source
    for method in (
        backend.create_private_directory,
        backend.create_private_file,
        backend.atomic_rename_no_replace,
        backend.replace_atomic,
        backend.remove_verified_member,
        backend.remove_verified_directory,
        backend.remove_verified_file,
    ):
        assert "flush_directory" in inspect.getsource(method)
    assert "_fsync_directory(parent)" in inspect.getsource(
        codex_instruct._make_registered_transaction_dir
    )
    for creator in (
        codex_instruct._create_deployment_journals,
        codex_instruct._create_uninstall_journals,
    ):
        assert "_fsync_directory(state.codex_dir)" in inspect.getsource(creator)
    for writer in (
        codex_instruct._write_exclusive_private_json,
        codex_instruct._atomic_write_private_json,
    ):
        assert "_fsync_directory" in inspect.getsource(writer)
    atomic_text_source = inspect.getsource(codex_instruct.atomic_write_text)
    assert "os.fsync" in atomic_text_source
    assert "_atomic_rename_no_replace" in atomic_text_source
    assert "_transactional_replace_existing" in atomic_text_source


def test_recovery_acl_preflight_runs_before_journal_content_is_read():
    for loader in (
        codex_instruct._load_deployment_journal,
        codex_instruct._load_uninstall_journal,
        codex_instruct._load_initializing_uninstall_pending,
    ):
        source = inspect.getsource(loader)
        assert source.index("read_verified_recovery_directory") < source.index(
            "_recovery_member_text"
        )


@pytest.mark.parametrize(
    "name",
    ["CON", "prn.md", "AUX", "nul.txt", "COM1", "lpt9.md"],
)
def test_windows_reserved_device_names_are_rejected(name):
    with pytest.raises(ValueError, match="reserved"):
        codex_instruct.normalize_md_name(name)


def test_directory_lock_excludes_second_process_without_sleep(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "lock target")
    worker = """
import importlib.util
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
target = sys.argv[2]
spec = importlib.util.spec_from_file_location("keysmith_lock_worker", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

def checkpoint(name):
    if name in {"directory-lock-wait", "directory-lock-acquired"}:
        print(name, flush=True)

module._FILESYSTEM_CHECKPOINT_HOOK = checkpoint
with module._DirectoryLockSet([target]):
    pass
"""
    process = None
    with codex_instruct._DirectoryLockSet([str(codex_dir)]):
        process = subprocess.Popen(
            [sys.executable, "-c", worker, str(MODULE_PATH), str(codex_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        assert process.stdout.readline() == "directory-lock-wait\n"
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.2)
    assert process is not None
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert stdout == "directory-lock-acquired\n"


def test_process_termination_releases_directory_lock(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "terminated lock")
    holder = """
import importlib.util
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
target = sys.argv[2]
spec = importlib.util.spec_from_file_location("keysmith_lock_holder", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

def checkpoint(name):
    if name == "directory-lock-acquired":
        print(name, flush=True)

module._FILESYSTEM_CHECKPOINT_HOOK = checkpoint
with module._DirectoryLockSet([target]):
    sys.stdin.buffer.read(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", holder, str(MODULE_PATH), str(codex_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "directory-lock-acquired\n"
    process.kill()
    process.communicate(timeout=10)

    worker = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util,sys; from pathlib import Path; "
                "p=Path(sys.argv[1]); s=importlib.util.spec_from_file_location('m',p); "
                "m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; "
                "s.loader.exec_module(m); "
                "lock=m._DirectoryLockSet([sys.argv[2]]); lock.__enter__(); "
                "print('acquired'); lock.__exit__(None,None,None)"
            ),
            str(MODULE_PATH),
            str(codex_dir),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert worker.returncode == 0, worker.stderr
    assert worker.stdout == "acquired\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows lock pin contract")
@pytest.mark.parametrize("rename_target", ["directory", "parent"])
def test_windows_directory_lock_pins_the_verified_identity(tmp_path, rename_target):
    parent = tmp_path / "pinned identity parent"
    parent.mkdir()
    codex_dir = _make_codex_dir(parent, "pinned identity")
    target = codex_dir if rename_target == "directory" else parent
    moved = target.with_name(f"{target.name} moved")

    with codex_instruct._DirectoryLockSet([str(codex_dir)]):
        try:
            target.rename(moved)
        except OSError as exc:
            assert exc.winerror == 32
        else:
            moved.rename(target)
            pytest.fail("locked directory identity was not pinned")

    target.rename(moved)
    assert moved.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive identity contract")
def test_windows_case_aliases_are_identity_deduplicated(tmp_path):
    directory = _make_codex_dir(tmp_path, "CaseAlias")
    alias = Path(str(directory).swapcase())

    normalized = codex_instruct._normalize_operation_directories(
        [str(directory), str(alias)]
    )

    assert len(normalized) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse path contract")
@pytest.mark.parametrize("alias_kind", ["root", "parent"])
def test_windows_codex_directory_rejects_reparse_path_components(tmp_path, alias_kind):
    real_parent = tmp_path / "real parent"
    real_parent.mkdir()
    codex_dir = _make_codex_dir(real_parent, "real codex")
    if alias_kind == "root":
        alias = tmp_path / "codex junction"
        _make_windows_junction(alias, codex_dir)
    else:
        alias_parent = tmp_path / "parent junction"
        _make_windows_junction(alias_parent, real_parent)
        alias = alias_parent / codex_dir.name

    result = _run("--codex-dir", alias, "--status")

    assert result.returncode == 1
    assert "reparse" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(os.name != "nt", reason="Windows native ACL contract")
def test_windows_private_file_and_directory_acl(tmp_path):
    directory = tmp_path / "private 中文"
    codex_instruct._FILESYSTEM.create_private_directory(directory)
    descriptor = codex_instruct._FILESYSTEM.create_private_file(directory / "secret.json")
    os.close(descriptor)

    codex_instruct._FILESYSTEM.verify_private_security(directory, is_directory=True)
    codex_instruct._FILESYSTEM.verify_private_security(
        directory / "secret.json",
        is_directory=False,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows native ACL contract")
def test_windows_private_acl_rejects_extra_everyone_ace(tmp_path):
    target = tmp_path / "private-acl.txt"
    descriptor = codex_instruct._FILESYSTEM.create_private_file(target)
    os.close(descriptor)
    changed = subprocess.run(
        ["icacls", str(target), "/grant", "*S-1-1-0:(R)"],
        text=True,
        capture_output=True,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr

    with pytest.raises(codex_instruct.HooksConflict, match="ACL"):
        codex_instruct._FILESYSTEM.verify_private_security(
            target,
            is_directory=False,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows native ACL claim contract")
def test_windows_move_in_claim_acl_becomes_protected_and_private(tmp_path):
    target = tmp_path / "move-in-claim.txt"
    target.write_bytes(b"owned claim\n")
    changed = subprocess.run(
        [
            "icacls",
            str(target),
            "/inheritance:e",
            "/grant",
            "*S-1-1-0:(R)",
        ],
        text=True,
        capture_output=True,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr
    with pytest.raises(codex_instruct.HooksConflict, match="ACL"):
        codex_instruct._FILESYSTEM.verify_private_security(
            target,
            is_directory=False,
        )

    expected = codex_instruct._fingerprint_regular_file(target)
    codex_instruct._FILESYSTEM.apply_private_path_security(target, expected)

    codex_instruct._FILESYSTEM.verify_private_security(
        target,
        is_directory=False,
    )
    assert codex_instruct._fingerprint_regular_file(target) == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows recovery ACL contract")
@pytest.mark.parametrize("operation", ["deploy", "uninstall"])
@pytest.mark.parametrize("target_kind", ["directory", "member"])
def test_windows_recovery_revalidates_existing_journal_acl(
    tmp_path,
    target_kind,
    operation,
):
    codex_dir = _make_codex_dir(
        tmp_path,
        f"{operation} acl recovery {target_kind}",
    )
    if operation == "deploy":
        plan = codex_instruct.inspect_directory(codex_dir)
        state = codex_instruct.DeploymentState(codex_dir, deployment_id="e" * 32)
        codex_instruct._create_deployment_journals(
            [state],
            [plan],
            codex_instruct.DEFAULT_MD_FILENAME,
            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
            False,
        )
    else:
        deployed = _run("--codex-dir", codex_dir, "--yes")
        assert deployed.returncode == 0, deployed.stdout + deployed.stderr
        plan = codex_instruct.inspect_uninstall_directory(codex_dir)
        state = codex_instruct.UninstallState(plan=plan, deployment_id="e" * 32)
        codex_instruct._create_uninstall_journals([state], "20260721_120000")
    assert state.journal_dir is not None
    target = (
        state.journal_dir
        if target_kind == "directory"
        else state.journal_dir / codex_instruct.JOURNAL_FILENAME
    )
    changed = subprocess.run(
        ["icacls", str(target), "/grant", "*S-1-1-0:(R)"],
        text=True,
        capture_output=True,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    assert "acl" in (recovered.stdout + recovered.stderr).lower()
    assert state.journal_dir.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows intent-only ACL contract")
def test_windows_intent_only_recovery_revalidates_acl(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "intent only acl recovery")
    plan = codex_instruct.inspect_directory(codex_dir)
    state = codex_instruct.DeploymentState(codex_dir, deployment_id="9" * 32)
    codex_instruct._create_deployment_journals(
        [state],
        [plan],
        codex_instruct.DEFAULT_MD_FILENAME,
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        False,
    )
    assert state.journal_dir is not None
    for member in state.journal_dir.iterdir():
        if member.name != codex_instruct.INTENT_FILENAME:
            member.unlink()
    intent = state.journal_dir / codex_instruct.INTENT_FILENAME
    changed = subprocess.run(
        ["icacls", str(intent), "/grant", "*S-1-1-0:(R)"],
        text=True,
        capture_output=True,
    )
    assert changed.returncode == 0, changed.stdout + changed.stderr

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    assert "acl" in (recovered.stdout + recovered.stderr).lower()
    assert intent.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows durable metadata contract")
def test_windows_mutations_flush_parent_directories(tmp_path, monkeypatch):
    backend = codex_instruct._FILESYSTEM
    flushed = []
    real_flush = backend.flush_directory

    def record_flush(path):
        flushed.append(Path(path))
        real_flush(path)

    monkeypatch.setattr(backend, "flush_directory", record_flush)
    parent = tmp_path / "durable parent"
    backend.create_private_directory(parent)
    backend.flush_directory(tmp_path)

    source = parent / "source.json"
    descriptor = backend.create_private_file(source)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"source\n")
        stream.flush()
        os.fsync(stream.fileno())
    backend.flush_directory(parent)
    destination = parent / "destination.json"
    assert backend.atomic_rename_no_replace(source, destination)

    replacement = parent / "replacement.json"
    descriptor = backend.create_private_file(replacement)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"replacement\n")
        stream.flush()
        os.fsync(stream.fileno())
    backend.flush_directory(parent)
    backend.replace_atomic(replacement, destination)
    identity = codex_instruct._require_regular_file(destination, "destination")
    fingerprint = codex_instruct._fingerprint_regular_file(destination)
    backend.remove_verified_file(destination, identity, fingerprint)

    owned = parent / "owned"
    backend.create_private_directory(owned)
    backend.flush_directory(parent)
    access = backend.open_verified_owned_directory(
        owned,
        codex_instruct._directory_identity(owned),
        {},
        True,
    )
    backend.remove_verified_directory(access)

    assert tmp_path in flushed
    assert flushed.count(parent) >= 6


@pytest.mark.skipif(os.name != "nt", reason="Windows create cleanup contract")
@pytest.mark.parametrize("node_kind", ["directory", "file"])
def test_windows_create_flush_failure_removes_unowned_node(
    tmp_path,
    monkeypatch,
    node_kind,
):
    target = tmp_path / f"failed {node_kind}"
    real_flush = codex_instruct._FILESYSTEM.flush_directory
    failed = False

    def fail_once(path):
        nonlocal failed
        if Path(path) == tmp_path and not failed:
            failed = True
            raise OSError("create parent flush failure")
        real_flush(path)

    monkeypatch.setattr(codex_instruct._FILESYSTEM, "flush_directory", fail_once)

    with pytest.raises(OSError, match="create parent flush failure"):
        if node_kind == "directory":
            codex_instruct._FILESYSTEM.create_private_directory(target)
        else:
            codex_instruct._FILESYSTEM.create_private_file(target)

    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows verified delete contract")
def test_windows_verified_delete_preserves_occupied_evidence_then_retries(tmp_path):
    target = tmp_path / "occupied-marker.json"
    descriptor = codex_instruct._FILESYSTEM.create_private_file(target)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"owned marker\n")
        stream.flush()
        os.fsync(stream.fileno())
    identity = codex_instruct._require_regular_file(target, "occupied marker")
    fingerprint = codex_instruct._fingerprint_regular_file(target)

    with target.open("rb"):
        with pytest.raises(OSError) as caught:
            codex_instruct._FILESYSTEM.remove_verified_file(
                target,
                identity,
                fingerprint,
            )
        assert caught.value.errno == 32
        assert target.read_bytes() == b"owned marker\n"

    codex_instruct._FILESYSTEM.remove_verified_file(
        target,
        identity,
        fingerprint,
    )
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows verified delete race contract")
@pytest.mark.parametrize("target_kind", ["member", "standalone"])
def test_windows_verified_delete_handle_blocks_writer_until_mark_delete(
    tmp_path,
    monkeypatch,
    target_kind,
):
    backend = codex_instruct._FILESYSTEM
    owned = tmp_path / "owned"
    backend.create_private_directory(owned)
    target = owned / "member.json"
    descriptor = backend.create_private_file(target)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"owned evidence\n")
        stream.flush()
        os.fsync(stream.fileno())
    fingerprint = codex_instruct._fingerprint_regular_file(target)
    writer_errors = []
    real_mark_delete = backend._mark_delete

    def assert_writer_blocked(handle, path):
        try:
            backend._open_handle(path, backend._GENERIC_WRITE)
        except OSError as exc:
            writer_errors.append(exc)
        else:
            pytest.fail("ordinary writer opened after verified fingerprint")
        real_mark_delete(handle, path)

    monkeypatch.setattr(backend, "_mark_delete", assert_writer_blocked)
    if target_kind == "member":
        access = backend.open_verified_owned_directory(
            owned,
            codex_instruct._directory_identity(owned),
            {target.name: fingerprint},
            True,
        )
        backend.remove_verified_member(access, target.name, fingerprint)
        backend.close_owned_directory(access)
    else:
        backend.remove_verified_file(target, fingerprint.identity, fingerprint)

    assert len(writer_errors) == 1
    assert writer_errors[0].errno == 32
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows native handle contract")
def test_windows_owned_directory_cleanup_rejects_reparse_members(tmp_path):
    owned = tmp_path / "owned"
    codex_instruct._FILESYSTEM.create_private_directory(owned)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = owned / "member"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    identity = codex_instruct._directory_identity(owned)
    with pytest.raises(codex_instruct.HooksConflict, match="member"):
        codex_instruct._safe_remove_owned_directory(
            owned,
            identity,
            {"member": None},
            require_exact_members=True,
        )
    assert outside.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.parametrize(
    ("function", "expected_calls"),
    [
        (codex_instruct._recover_uninstall, 2),
        (codex_instruct._load_initializing_uninstall_pending, 1),
    ],
)
def test_uninstall_intent_reads_are_bound_to_verified_directory_evidence(
    function,
    expected_calls,
):
    source = inspect.getsource(function)
    calls = source.split("_load_cleanup_intent(")[1:]

    assert len(calls) == expected_calls
    assert all("," in call.split(")", 1)[0] for call in calls)


def test_initializing_uninstall_member_set_uses_verified_directory_evidence():
    source = inspect.getsource(
        codex_instruct._load_initializing_uninstall_pending
    )

    assert "MANIFEST_INTENT_FILENAME in evidence" in source
    assert "_path_entry_exists(journal_dir / MANIFEST_INTENT_FILENAME)" not in source

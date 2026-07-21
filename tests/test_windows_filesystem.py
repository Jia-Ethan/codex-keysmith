import importlib.util
import inspect
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
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


def test_platform_filesystem_contract_is_centralized():
    backend = codex_instruct._FILESYSTEM
    for method in (
        "create_private_directory",
        "create_private_file",
        "open_verified_owned_directory",
        "remove_verified_member",
        "remove_verified_directory",
        "set_file_times",
        "apply_private_file_security",
        "atomic_rename_no_replace",
        "replace_atomic",
        "flush_directory",
        "directory_lock_key",
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
    selector = selectors.DefaultSelector()
    with codex_instruct._DirectoryLockSet([str(codex_dir)]):
        process = subprocess.Popen(
            [sys.executable, "-c", worker, str(MODULE_PATH), str(codex_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        events = selector.select(timeout=10)
        assert events, "lock worker did not reach the wait checkpoint"
        assert process.stdout.readline() == "directory-lock-wait\n"
        assert not selector.select(timeout=0.2), "worker acquired an already-held lock"
    assert process is not None
    stdout, stderr = process.communicate(timeout=10)
    selector.close()
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


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive identity contract")
def test_windows_case_aliases_are_identity_deduplicated(tmp_path):
    directory = _make_codex_dir(tmp_path, "CaseAlias")
    alias = Path(str(directory).swapcase())

    normalized = codex_instruct._normalize_operation_directories(
        [str(directory), str(alias)]
    )

    assert len(normalized) == 1


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

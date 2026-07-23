import importlib.util
import os
import socket
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct_platform", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def test_find_codex_dirs_deduplicates_resolved_paths_and_sorts(tmp_path, monkeypatch):
    first = tmp_path / "a" / ".codex"
    second = tmp_path / "b" / ".codex"
    for directory in (first, second):
        directory.mkdir(parents=True)
        (directory / "config.toml").write_text('model = "gpt-5.6"\n', encoding="utf-8")
    monkeypatch.setattr(
        codex_instruct,
        "_codex_dir_candidates",
        lambda: [second, first, first / "."],
    )

    assert codex_instruct.find_codex_dirs() == sorted(
        [str(first.resolve()), str(second.resolve())]
    )


def test_find_restore_dirs_includes_disabled_and_residue_without_config(
    tmp_path,
    monkeypatch,
):
    disabled_dir = tmp_path / "disabled"
    residue_dir = tmp_path / "residue"
    disabled_dir.mkdir()
    residue_dir.mkdir()
    (disabled_dir / "hooks.json.disabled").write_text("disabled\n", encoding="utf-8")
    (residue_dir / ".keysmith-write-interrupted").mkdir()
    monkeypatch.setattr(
        codex_instruct,
        "_codex_dir_candidates",
        lambda: [residue_dir, disabled_dir],
    )

    assert codex_instruct.find_hook_restore_dirs() == sorted(
        [str(disabled_dir.resolve()), str(residue_dir.resolve())]
    )


def test_candidate_resolver_skips_inaccessible_directory(tmp_path, monkeypatch):
    blocked = (tmp_path / "blocked").resolve()
    real_is_dir = Path.is_dir

    def guarded_is_dir(path):
        if path == blocked:
            raise PermissionError("simulated inaccessible candidate")
        return real_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", guarded_is_dir)

    assert codex_instruct._resolve_candidate_directory(blocked) is None


def test_each_discovery_mode_skips_probe_errors(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    monkeypatch.setattr(
        codex_instruct,
        "_codex_dir_candidates",
        lambda: [candidate],
    )

    def fail(*_args, **_kwargs):
        raise PermissionError("simulated inaccessible candidate contents")

    monkeypatch.setattr(codex_instruct, "_is_regular_path", fail)
    assert codex_instruct.find_codex_dirs() == []
    assert codex_instruct.find_hook_restore_dirs() == []

    monkeypatch.setattr(codex_instruct.os, "scandir", fail)
    assert codex_instruct._directory_is_enumerable(candidate) is False
    assert codex_instruct.find_status_dirs() == []

    monkeypatch.setattr(codex_instruct, "_deployment_journal_dirs", fail)
    assert codex_instruct.find_recovery_dirs() == []

    monkeypatch.setattr(codex_instruct, "_path_entry_exists", fail)
    assert codex_instruct.find_uninstall_dirs() == []


def test_status_reports_late_directory_access_error(tmp_path, monkeypatch, capsys):
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    def fail(*_args, **_kwargs):
        raise PermissionError("simulated access change after discovery")

    monkeypatch.setattr(codex_instruct, "inspect_directory", fail)
    monkeypatch.setattr(codex_instruct, "_OUTPUT_LANGUAGE", "en")

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.show_status([str(candidate)])

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert "Could not safely inspect the directory" in output
    assert "simulated access change after discovery" in output


def test_windows_candidates_include_userprofile_and_localappdata(tmp_path, monkeypatch):
    userprofile = tmp_path / "user"
    localappdata = tmp_path / "local"
    fake_os = types.SimpleNamespace(
        name="nt",
        environ={
            "USERPROFILE": str(userprofile),
            "LOCALAPPDATA": str(localappdata),
        },
    )
    monkeypatch.setattr(codex_instruct, "os", fake_os)

    candidates = codex_instruct._codex_dir_candidates()

    assert userprofile / ".codex" in candidates
    assert localappdata / "OpenAI" / "Codex" in candidates


def test_multi_directory_successful_deployment(tmp_path, monkeypatch):
    directories = [tmp_path / "first", tmp_path / "second"]
    for directory in directories:
        directory.mkdir()
        (directory / "config.toml").write_text('model = "gpt-5.6"\n', encoding="utf-8")
    monkeypatch.setattr(
        codex_instruct,
        "find_codex_dirs",
        lambda: [str(directory) for directory in directories],
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    codex_instruct.deploy(args)

    for directory in directories:
        assert (directory / "gpt-unrestricted.md").read_text(encoding="utf-8") == (
            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD
        )
        assert 'model_instructions_file = "./gpt-unrestricted.md"' in (
            directory / "config.toml"
        ).read_text(encoding="utf-8")


def test_unwritable_directory_fails_before_deployment(tmp_path):
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("POSIX owner permission enforcement is unavailable")
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.6"\n', encoding="utf-8")
    codex_dir.chmod(0o500)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--codex-dir",
                str(codex_dir),
                "--yes",
                "--lang",
                "zh-CN",
            ],
            text=True,
            capture_output=True,
        )
    finally:
        codex_dir.chmod(0o700)

    assert result.returncode == 1
    assert "部署前置检查失败" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.6"\n'
    assert not (codex_dir / "gpt-unrestricted.md").exists()


def test_atomic_no_replace_has_one_winner_across_processes(tmp_path):
    destination = tmp_path / "winner"
    result_paths = [tmp_path / "result-1", tmp_path / "result-2"]
    sources = [tmp_path / "source-1", tmp_path / "source-2"]
    for index, source in enumerate(sources, start=1):
        source.write_bytes(f"worker-{index}\n".encode("utf-8"))

    worker = textwrap.dedent(
        """
        import importlib.util
        import socket
        import sys
        from pathlib import Path

        module_path, source, destination, result = map(Path, sys.argv[1:5])
        barrier_port = int(sys.argv[5])
        spec = importlib.util.spec_from_file_location("keysmith_worker", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with socket.create_connection(("127.0.0.1", barrier_port), timeout=10) as barrier:
            barrier.sendall(b"r")
            if barrier.recv(1) != b"g":
                raise SystemExit("start barrier closed")
        try:
            moved = module._atomic_rename_no_replace(source, destination)
        except module.AtomicRenameUnavailable as exc:
            result.write_bytes(("unsupported:" + str(exc)).encode("utf-8"))
        else:
            result.write_bytes(b"won" if moved else b"lost")
        """
    )
    processes = []
    barriers = []
    outputs = []
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(10)
        barrier_port = server.getsockname()[1]
        try:
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        worker,
                        str(MODULE_PATH),
                        str(source),
                        str(destination),
                        str(result),
                        str(barrier_port),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for source, result in zip(sources, result_paths)
            ]
            for _process in processes:
                barrier, _address = server.accept()
                barrier.settimeout(5)
                assert barrier.recv(1) == b"r"
                barriers.append(barrier)
            for barrier in barriers:
                barrier.sendall(b"g")
                barrier.close()
            barriers.clear()
            outputs = [process.communicate(timeout=15) for process in processes]
        finally:
            for barrier in barriers:
                barrier.close()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
    assert all(process.returncode == 0 for process in processes), outputs

    results = [path.read_text(encoding="utf-8") for path in result_paths]
    if any(result.startswith("unsupported:") for result in results):
        pytest.skip("atomic no-replace rename is unavailable on this filesystem")
    assert sorted(results) == ["lost", "won"]
    assert destination.read_text(encoding="utf-8") in {"worker-1\n", "worker-2\n"}
    assert sum(source.exists() for source in sources) == 1

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_validation", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _copy_package(tmp_path):
    root = (tmp_path / "scenario library").resolve()
    shutil.copytree(SCENARIO_ROOT, root)
    return root, root / "example_fixture"


def _metadata(package):
    return json.loads((package / "scenario.json").read_text(encoding="utf-8"))


def _write_metadata(package, data):
    (package / "scenario.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _refresh_checksums(package, data):
    data["checksums"] = {
        relative: hashlib.sha256((package / relative).read_bytes()).hexdigest()
        for relative in data["checksums"]
    }
    _write_metadata(package, data)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/absolute",
        "../escape",
        "./task.md",
        "nested\\task.md",
        "CON.txt",
        "trailing. ",
        "data/bad:name.json",
        "data/bad?name.json",
        "data/control\x1f.json",
        "data/delete\x7f.json",
    ],
)
def test_safe_relative_rejects_nonportable_paths(value):
    with pytest.raises(ValueError):
        codex_instruct._scenario_safe_relative(value, "fixture path")


def test_safe_relative_accepts_normalized_nested_path():
    assert (
        codex_instruct._scenario_safe_relative("data/input.json", "fixture path")
        == "data/input.json"
    )


def test_package_ignores_python_bytecode_cache_artifacts(tmp_path):
    root, package = _copy_package(tmp_path)
    cache = package / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "validator.cpython-314.pyc").write_bytes(b"local bytecode\n")
    (package / "verify.pyc").write_bytes(b"legacy local bytecode\n")

    loaded = codex_instruct.load_scenario_package(root, "example_fixture")

    assert not any("__pycache__" in relative for relative in loaded.files)
    assert "verify.pyc" not in loaded.files


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_package_does_not_ignore_abnormal_bytecode_nodes(tmp_path, kind):
    root, package = _copy_package(tmp_path)
    abnormal = package / "masked.pyc"
    if kind == "symlink":
        try:
            abnormal.symlink_to(package / "task.md")
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation unavailable")
        os.mkfifo(abnormal)

    with pytest.raises(OSError, match="not a regular file"):
        codex_instruct.load_scenario_package(root, "example_fixture")


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_package_audits_abnormal_nodes_inside_bytecode_cache(tmp_path, kind):
    root, package = _copy_package(tmp_path)
    cache = package / "__pycache__"
    cache.mkdir(exist_ok=True)
    abnormal = cache / "masked.pyc"
    if kind == "symlink":
        try:
            abnormal.symlink_to(package / "task.md")
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation unavailable")
        os.mkfifo(abnormal)

    with pytest.raises(OSError, match="bytecode cache member is not a regular file"):
        codex_instruct.load_scenario_package(root, "example_fixture")


def test_package_rejects_scenario_json_replacement_during_load(tmp_path, monkeypatch):
    root, package = _copy_package(tmp_path)
    replacement = _metadata(package)
    replacement["version"] = "9.9.9"
    real_file_paths = codex_instruct._scenario_file_paths

    def replace_metadata(scenario_root, **kwargs):
        paths = real_file_paths(scenario_root, **kwargs)
        _write_metadata(package, replacement)
        return paths

    monkeypatch.setattr(codex_instruct, "_scenario_file_paths", replace_metadata)

    with pytest.raises(codex_instruct.HooksConflict, match="scenario.json changed"):
        codex_instruct.load_scenario_package(root, "example_fixture")

    assert _metadata(package)["version"] == "9.9.9"


def test_package_rejects_root_rebinding_during_load(tmp_path, monkeypatch):
    root, package = _copy_package(tmp_path)
    original = package.with_name("original-example-fixture")
    real_file_paths = codex_instruct._scenario_file_paths

    def rebind_package(scenario_root, **kwargs):
        paths = real_file_paths(scenario_root, **kwargs)
        package.rename(original)
        shutil.copytree(original, package)
        return paths

    monkeypatch.setattr(codex_instruct, "_scenario_file_paths", rebind_package)

    with pytest.raises(
        codex_instruct.HooksConflict,
        match="package root identity changed while loading",
    ):
        codex_instruct.load_scenario_package(root, "example_fixture")


@pytest.mark.parametrize(
    "backend_error",
    [
        FileNotFoundError("control directory disappeared"),
        PermissionError("access denied"),
        NotADirectoryError("control path is not a directory"),
        OSError("filesystem unavailable"),
    ],
)
def test_scenario_journal_discovery_preserves_enumeration_errors(
    tmp_path,
    monkeypatch,
    backend_error,
):
    control = tmp_path / ".codex-keysmith"
    control.mkdir()

    def fail_enumeration(_path):
        raise backend_error

    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "list_directory_names",
        fail_enumeration,
    )

    with pytest.raises(type(backend_error)) as caught:
        codex_instruct._scenario_journal_paths(control)

    assert caught.value is backend_error


@pytest.mark.parametrize(
    "specification,expected",
    [
        (">=0.0,<99.0", True),
        (">=99.0,<100.0", False),
    ],
)
def test_python_runtime_constraint_matching(specification, expected):
    assert codex_instruct._scenario_python_version_matches(specification) is expected


def test_python_runtime_rejects_unsupported_constraint():
    with pytest.raises(ValueError, match="unsupported Python runtime constraint"):
        codex_instruct._scenario_python_version_matches(">=3.9")


@pytest.mark.parametrize(
    "requires",
    [
        {},
        [{"name": "tool", "type": "command", "version": "1"}],
        [
            {"name": "tool", "type": "command", "version": "1", "probe": ["tool"]},
            {"name": "tool", "type": "command", "version": "1", "probe": ["tool"]},
        ],
        [{"name": "tool", "type": "shell", "version": "1", "probe": ["tool"]}],
        [{"name": "tool", "type": "command", "version": "", "probe": ["tool"]}],
        [{"name": "tool", "type": "command", "version": "1", "probe": "tool --version"}],
        [
            {
                "name": "tool",
                "type": "command",
                "version": ">=1",
                "probe": ["bash", "-c", "echo 1.0"],
            }
        ],
        [
            {
                "name": "tool",
                "type": "command",
                "version": "latest",
                "probe": ["tool", "--version"],
            }
        ],
    ],
)
def test_requires_schema_rejects_invalid_entries(requires):
    with pytest.raises(ValueError):
        codex_instruct._scenario_validate_requires(requires)


def test_requires_schema_accepts_structured_probes():
    requires = [
        {
            "name": "python",
            "type": "command",
            "version": ">=3.9",
            "probe": ["python", "--version"],
        }
    ]
    assert codex_instruct._scenario_validate_requires(requires) == tuple(requires)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda data: data.update(schema_version=2), "schema or id"),
        (lambda data: data.update(id="wrong_id"), "schema or id"),
        (lambda data: data.update(version="1"), "semantic"),
        (lambda data: data.update(display_name=""), "display_name"),
        (lambda data: data.update(platforms=[]), "platforms"),
        (lambda data: data.update(runtime={}), "runtime"),
        (lambda data: data.update(checksums=[]), "checksums must be an object"),
    ],
)
def test_package_metadata_rejects_invalid_contracts(tmp_path, mutate, match):
    root, package = _copy_package(tmp_path)
    data = _metadata(package)
    mutate(data)
    _write_metadata(package, data)

    with pytest.raises(ValueError, match=match):
        codex_instruct.load_scenario_package(root, "example_fixture")


def test_package_requires_declared_entrypoints_to_be_deployed(tmp_path):
    root, package = _copy_package(tmp_path)
    data = _metadata(package)
    data["task"] = "fixtures/positive/output.json"
    _write_metadata(package, data)

    with pytest.raises(ValueError, match="entrypoint is not a deployed regular file"):
        codex_instruct.load_scenario_package(root, "example_fixture")


def test_package_rejects_invalid_checksum_value(tmp_path):
    root, package = _copy_package(tmp_path)
    data = _metadata(package)
    data["checksums"]["task.md"] = "invalid"
    _write_metadata(package, data)

    with pytest.raises(ValueError, match="checksum is invalid"):
        codex_instruct.load_scenario_package(root, "example_fixture")


def test_package_rejects_case_insensitive_member_collision(tmp_path):
    root, package = _copy_package(tmp_path)
    upper = package / "TASK.MD"
    upper.write_text("collision\n", encoding="utf-8")
    if upper.samefile(package / "task.md"):
        pytest.skip("filesystem is case-insensitive")

    with pytest.raises(ValueError, match="collide case-insensitively"):
        codex_instruct.load_scenario_package(root, "example_fixture")


def test_discovery_reports_invalid_directory_and_node(tmp_path):
    root, _package = _copy_package(tmp_path)
    (root / "Bad-Name").mkdir()
    (root / "valid_node").write_text("not a directory\n", encoding="utf-8")

    discovered = {
        scenario_id: (package, detail)
        for scenario_id, package, detail in codex_instruct.discover_scenario_packages(root)
    }

    assert discovered["Bad-Name"] == (None, "invalid scenario directory name")
    assert discovered["valid_node"][0] is None
    assert "invalid node" in discovered["valid_node"][1]


def test_static_blockers_report_platform_runtime_and_dependencies(tmp_path, monkeypatch):
    root, package_root = _copy_package(tmp_path)
    data = _metadata(package_root)
    data["platforms"] = ["win32"]
    data["runtime"] = {"python": ">=99.0,<100.0"}
    data["requires"] = [
        {
            "name": "tool",
            "type": "command",
            "version": ">=1",
            "probe": ["tool", "--version"],
        }
    ]
    _write_metadata(package_root, data)
    package = codex_instruct.load_scenario_package(root, "example_fixture")
    monkeypatch.setattr(codex_instruct, "_scenario_platform_name", lambda: "linux")

    blockers = codex_instruct._scenario_static_blockers(package)

    assert any("platform linux is not declared" in blocker for blocker in blockers)
    assert any("does not satisfy" in blocker for blocker in blockers)
    assert any("is not on PATH" in blocker for blocker in blockers)


@pytest.mark.parametrize(
    "version,specification,expected",
    [
        ("2024.03.5", ">=2022.9", True),
        ("2020.9", ">=2022.9", False),
        ("3.9.6", ">=3.9,<3.15", True),
        ("3.15.0", ">=3.9,<3.15", False),
        ("1.0", "==1.0.0", True),
    ],
)
def test_requires_version_constraint_matching(version, specification, expected):
    assert codex_instruct._scenario_version_satisfies(version, specification) is expected


def test_requires_schema_rejects_shell_probe_explicitly():
    with pytest.raises(ValueError, match="must not invoke a shell"):
        codex_instruct._scenario_validate_requires(
            [
                {
                    "name": "tool",
                    "type": "command",
                    "version": ">=1",
                    "probe": ["bash", "-c", "echo 1.0"],
                }
            ]
        )


def test_probe_reports_missing_command():
    blocker = codex_instruct._scenario_probe_requirement(
        {
            "name": "tool",
            "type": "command",
            "version": ">=1",
            "probe": ["codex-keysmith-missing-tool", "--version"],
        }
    )

    assert blocker is not None
    assert "is not on PATH" in blocker
    assert "codex-keysmith-missing-tool" in blocker


def test_probe_reports_missing_python_module():
    blocker = codex_instruct._scenario_probe_requirement(
        {
            "name": "missing_mod_xyz",
            "type": "python-module",
            "version": ">=1.0",
            "probe": ["python", "-c", "import missing_mod_xyz; print('1.0')"],
        }
    )

    assert blocker is not None
    assert "install python-module 'missing_mod_xyz'" in blocker
    assert "No module named 'missing_mod_xyz'" in blocker


def test_probe_reports_version_mismatch():
    blocker = codex_instruct._scenario_probe_requirement(
        {
            "name": "json",
            "type": "python-module",
            "version": ">=99.0",
            "probe": ["python", "-c", "import json; print('1.0')"],
        }
    )

    assert blocker is not None
    assert "does not satisfy >=99.0" in blocker


def test_probe_accepts_satisfied_python_module():
    assert (
        codex_instruct._scenario_probe_requirement(
            {
                "name": "json",
                "type": "python-module",
                "version": ">=0.0",
                "probe": ["python", "-c", "import json; print('1.0')"],
            }
        )
        is None
    )


def test_python_module_probe_rewrites_python_alias(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="2024.03.5\n", stderr="")

    monkeypatch.setattr(codex_instruct.subprocess, "run", fake_run)
    blocker = codex_instruct._scenario_probe_requirement(
        {
            "name": "rdkit",
            "type": "python-module",
            "version": ">=2022.9",
            "probe": ["python", "-c", "from rdkit import rdBase; print(rdBase.rdkitVersion)"],
        }
    )

    assert blocker is None
    assert seen["command"][0] == sys.executable
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["timeout"] == codex_instruct.SCENARIO_PROBE_TIMEOUT_SECONDS


def test_probe_reports_timeout(monkeypatch):
    monkeypatch.setattr(codex_instruct, "SCENARIO_PROBE_TIMEOUT_SECONDS", 0.2)
    blocker = codex_instruct._scenario_probe_requirement(
        {
            "name": "sleeper",
            "type": "command",
            "version": ">=1",
            "probe": [sys.executable, "-c", "import time; time.sleep(2); print('1.0')"],
        }
    )

    assert blocker is not None
    assert "timed out" in blocker


def test_scenario_root_requires_explicit_path_for_frozen_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(FileNotFoundError, match="provide --scenario-root"):
        codex_instruct.resolve_scenario_root(None)


def test_scenario_target_rejects_symlinked_ancestor(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(codex_instruct.HooksConflict):
        codex_instruct.resolve_scenario_target(str(alias / "target"))


@pytest.mark.parametrize("resolver", ["target", "root"])
def test_scenario_paths_reject_missing_relative_and_noncanonical_forms(
    tmp_path,
    resolver,
):
    resolve = (
        codex_instruct.resolve_scenario_target
        if resolver == "target"
        else codex_instruct.resolve_scenario_root
    )
    existing = (tmp_path / resolver).resolve()
    existing.mkdir()

    with pytest.raises(ValueError, match="explicit absolute path"):
        resolve(existing.name)
    with pytest.raises(FileNotFoundError, match="does not exist"):
        resolve(str(existing / "missing"))


@pytest.mark.parametrize(
    ("resolver", "label"),
    [
        ("target", "--target-dir"),
        ("root", "--scenario-root"),
    ],
)
def test_windows_scenario_paths_normalize_missing_directory_errors(
    tmp_path,
    monkeypatch,
    resolver,
    label,
):
    resolve = (
        codex_instruct.resolve_scenario_target
        if resolver == "target"
        else codex_instruct.resolve_scenario_root
    )
    missing = (tmp_path / f"missing-{resolver}").resolve()
    backend_error = FileNotFoundError(2, "native backend detail", str(missing))

    def fail_resolve(_path):
        raise backend_error

    monkeypatch.setattr(codex_instruct, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "resolve_directory",
        fail_resolve,
    )

    with pytest.raises(FileNotFoundError) as caught:
        resolve(str(missing))

    assert str(caught.value) == f"{label} does not exist: {missing}"
    assert caught.value.__cause__ is backend_error


@pytest.mark.parametrize(
    "backend_error",
    [
        PermissionError("access denied"),
        codex_instruct.HooksConflict("reparse point is not allowed"),
        OSError("filesystem unavailable"),
    ],
)
def test_windows_scenario_paths_preserve_non_missing_backend_errors(
    tmp_path,
    monkeypatch,
    backend_error,
):
    target = (tmp_path / "target").resolve()
    target.mkdir()

    def fail_resolve(_path):
        raise backend_error

    monkeypatch.setattr(codex_instruct, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(
        codex_instruct._FILESYSTEM,
        "resolve_directory",
        fail_resolve,
    )

    with pytest.raises(type(backend_error)) as caught:
        codex_instruct.resolve_scenario_target(str(target))

    assert caught.value is backend_error


def test_scenario_root_rejects_symlinked_ancestor(tmp_path):
    real_parent = tmp_path / "real-root"
    real_parent.mkdir()
    root = real_parent / "library"
    root.mkdir()
    alias = tmp_path / "root-alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(codex_instruct.HooksConflict):
        codex_instruct.resolve_scenario_root(str(alias / "library"))


def test_package_source_digest_changes_with_deployed_content(tmp_path):
    root, package = _copy_package(tmp_path)
    original = codex_instruct.load_scenario_package(root, "example_fixture")
    (package / "task.md").write_text("changed task\n", encoding="utf-8")
    data = _metadata(package)
    _refresh_checksums(package, data)

    changed = codex_instruct.load_scenario_package(root, "example_fixture")

    assert changed.source_digest != original.source_digest

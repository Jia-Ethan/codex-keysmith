import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location(
    "codex_instruct_scenario_bundle",
    MODULE_PATH,
)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)

M2_SCENARIOS = ("aiml_toxigen", "chem_rdkit", "cyber_keystone")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _target(tmp_path, name="target"):
    target = (tmp_path / name).resolve()
    target.mkdir(parents=True)
    (target / "project.txt").write_text("keep\n", encoding="utf-8")
    return target


def _manifest(target):
    return json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _write_bundle(directory):
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / codex_instruct.scenario_bundle_asset_name()
    digest = codex_instruct.write_scenario_bundle(SCENARIO_ROOT.resolve(), destination)
    return destination.resolve(), digest


def _unpack_bundle(directory, bundle):
    root = directory / "unpacked"
    root.mkdir(parents=True)
    with zipfile.ZipFile(str(bundle)) as archive:
        for info in archive.infolist():
            path = root / info.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(info))
    return root.resolve()


def _lifecycle(tmp_path, scenario_root):
    listed = _run("--scenario-list", "--scenario-root", scenario_root)
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert "example_fixture 1.0.0: ready" in listed.stdout

    target = _target(tmp_path)
    preview = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        scenario_root,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "no files were changed" in preview.stdout
    assert not (target / ".codex-keysmith").exists()

    deployed = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        scenario_root,
        "--yes",
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    manifest = _manifest(target)
    deployment_id = next(iter(manifest["deployments"]))
    record = manifest["deployments"][deployment_id]
    assert record["scenario_id"] == "example_fixture"
    assert set(record["files"]) == {
        "scenario.json",
        "task.md",
        "validator.py",
        "verify.py",
        "data/input.json",
    }
    assert not (
        target / ".codex-keysmith" / record["root"] / "fixtures"
    ).exists()

    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout

    recover = _run("--scenario-recover", "--target-dir", target)
    assert recover.returncode == 0, recover.stdout + recover.stderr
    assert "no recovery required" in recover.stdout

    removed = _run(
        "--scenario-uninstall",
        deployment_id,
        "--target-dir",
        target,
        "--yes",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not (target / ".codex-keysmith" / record["root"]).exists()
    assert _manifest(target)["deployments"] == {}
    return target, deployment_id


def test_bundle_index_source_digest_matches_m1_algorithm(tmp_path):
    bundle, _digest = _write_bundle(tmp_path)
    with zipfile.ZipFile(str(bundle)) as archive:
        index = json.loads(archive.read("index.json").decode("utf-8"))

    assert index["schema_version"] == 1
    assert index["tool_version"] == codex_instruct.VERSION
    assert set(index["scenarios"]) >= {"example_fixture", *M2_SCENARIOS}
    for scenario_id, record in index["scenarios"].items():
        package = codex_instruct.load_scenario_package(SCENARIO_ROOT, scenario_id)
        assert record["source_digest"] == package.source_digest
        if scenario_id in M2_SCENARIOS:
            assert record["platforms"] == ["darwin", "linux"]


def test_bundle_write_is_byte_identical_across_two_runs(tmp_path):
    first, _ = _write_bundle(tmp_path / "first")
    second, _ = _write_bundle(tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("root_kind", ["source-dir", "indexed-dir", "bundle"])
def test_scenario_root_kinds_share_example_fixture_lifecycle(tmp_path, root_kind):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    if root_kind == "source-dir":
        root = SCENARIO_ROOT.resolve()
    elif root_kind == "indexed-dir":
        root = _unpack_bundle(tmp_path, bundle)
    else:
        root = bundle
    _lifecycle(tmp_path / root_kind, root)


def test_indexed_or_bundle_fail_closed_on_index_and_member_drift(tmp_path):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    unpacked = _unpack_bundle(tmp_path, bundle)

    index_path = unpacked / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["scenarios"]["example_fixture"]["source_digest"] = "0" * 64
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    tampered_index = _run("--scenario-list", "--scenario-root", unpacked)
    assert tampered_index.returncode == 1
    assert "source_digest or metadata drifted" in tampered_index.stdout

    missing = _unpack_bundle(tmp_path / "missing", bundle)
    (missing / "scenarios" / "example_fixture" / "task.md").unlink()
    missing_member = _run("--scenario-list", "--scenario-root", missing)
    assert missing_member.returncode == 1
    assert "invalid" in missing_member.stdout.lower() or "checksum" in missing_member.stdout

    drifted = _unpack_bundle(tmp_path / "drifted", bundle)
    task = drifted / "scenarios" / "example_fixture" / "task.md"
    task.write_text("drifted task\n", encoding="utf-8")
    drifted_member = _run("--scenario-list", "--scenario-root", drifted)
    assert drifted_member.returncode == 1
    assert "checksum mismatch" in drifted_member.stdout or "drifted" in drifted_member.stdout


def test_indexed_directory_rejects_symlink_member(tmp_path):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    unpacked = _unpack_bundle(tmp_path, bundle)
    alias = unpacked / "scenarios" / "example_fixture" / "alias.md"
    try:
        alias.symlink_to("task.md")
    except OSError as exc:
        pytest.skip("symlink unavailable: {}".format(exc))

    result = _run("--scenario-list", "--scenario-root", unpacked)
    assert result.returncode == 1
    assert "symbolic link" in result.stdout or "not a regular file" in result.stdout


@pytest.mark.parametrize(
    "node_kind",
    ["regular file", "directory", "symbolic link", "FIFO"],
)
def test_indexed_directory_rejects_unexpected_root_nodes_for_list_and_deploy(
    tmp_path,
    node_kind,
):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    unpacked = _unpack_bundle(tmp_path, bundle)
    unexpected = unpacked / "unexpected"
    if node_kind == "regular file":
        unexpected.write_text("unexpected\n", encoding="utf-8")
    elif node_kind == "directory":
        unexpected.mkdir()
    elif node_kind == "symbolic link":
        try:
            unexpected.symlink_to("index.json")
        except OSError as exc:
            pytest.skip("symlink unavailable: {}".format(exc))
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO nodes are unavailable on this platform")
        os.mkfifo(unexpected)

    target = _target(tmp_path)
    results = [
        _run("--scenario-list", "--scenario-root", unpacked),
        _run(
            "--deploy-scenario",
            "example_fixture",
            "--target-dir",
            target,
            "--scenario-root",
            unpacked,
        ),
    ]

    for result in results:
        assert result.returncode == 1
        assert "[Error]" in result.stdout
        assert "unexpected member" in result.stdout
        assert str(unexpected) in result.stdout
        assert node_kind in result.stdout
        assert "Traceback" not in result.stdout + result.stderr
    assert not (target / ".codex-keysmith").exists()


@pytest.mark.parametrize("payload_kind", ["non-zip", "truncated"])
def test_invalid_bundle_reports_clean_error_for_list_and_deploy(tmp_path, payload_kind):
    if payload_kind == "non-zip":
        invalid = (tmp_path / "invalid.bundle").resolve()
        invalid.write_bytes(b"not a ZIP archive\n")
    else:
        bundle, _digest = _write_bundle(tmp_path / "assets")
        invalid = (tmp_path / "truncated.bundle").resolve()
        content = bundle.read_bytes()
        invalid.write_bytes(content[: len(content) // 2])

    target = _target(tmp_path)
    results = [
        _run("--scenario-list", "--scenario-root", invalid),
        _run(
            "--deploy-scenario",
            "example_fixture",
            "--target-dir",
            target,
            "--scenario-root",
            invalid,
        ),
    ]

    for result in results:
        assert result.returncode == 1
        assert "[Error]" in result.stdout
        assert "not a valid ZIP archive or is truncated" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr
    assert not (target / ".codex-keysmith").exists()


def test_sealed_bundle_rejects_symlink_zip_member(tmp_path):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    evil = tmp_path / "evil.bundle"
    with zipfile.ZipFile(str(bundle), "r") as source, zipfile.ZipFile(
        str(evil), "w", compression=zipfile.ZIP_STORED
    ) as destination:
        for info in source.infolist():
            destination.writestr(info, source.read(info))
        link = zipfile.ZipInfo("scenarios/example_fixture/link.md")
        link.create_system = 3
        link.external_attr = (0o120644 & 0xFFFF) << 16
        destination.writestr(link, b"task.md")

    result = _run("--scenario-list", "--scenario-root", evil.resolve())
    assert result.returncode == 1
    assert "symbolic link" in result.stdout


def test_bundle_deployed_payload_drift_is_conflict_and_preserved(tmp_path):
    bundle, _digest = _write_bundle(tmp_path / "assets")
    target = _target(tmp_path)
    deployed = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        bundle,
        "--yes",
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    manifest = _manifest(target)
    deployment_id = next(iter(manifest["deployments"]))
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


def test_missing_bundle_path_reports_does_not_exist(tmp_path):
    missing = (tmp_path / "missing.bundle").resolve()
    result = _run("--scenario-list", "--scenario-root", missing)
    assert result.returncode == 1
    assert "does not exist" in result.stdout


def test_frozen_embedded_bundle_does_not_require_scenario_root(tmp_path, monkeypatch):
    bundle, digest = _write_bundle(tmp_path / "assets")
    meipass = tmp_path / "meipass"
    library = meipass / "scenario-library"
    library.mkdir(parents=True)
    embedded = library / bundle.name
    shutil.copy2(bundle, embedded)
    (library / "embedded-scenarios.json").write_text(
        json.dumps(
            {
                "filename": bundle.name,
                "sha256": digest,
                "tool_version": codex_instruct.VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    library_state = codex_instruct.resolve_scenario_library(None)
    package = codex_instruct.load_scenario_package(
        library_state.packages_root,
        "example_fixture",
    )
    assert library_state.kind == "bundle"
    assert package.scenario_id == "example_fixture"
    assert package.platforms == ("darwin", "linux", "win32")


def test_frozen_missing_or_drifted_embed_requires_scenario_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty"), raising=False)
    with pytest.raises(FileNotFoundError, match="provide --scenario-root"):
        codex_instruct.resolve_scenario_root(None)

    bundle, digest = _write_bundle(tmp_path / "assets")
    meipass = tmp_path / "meipass"
    library = meipass / "scenario-library"
    library.mkdir(parents=True)
    embedded = library / bundle.name
    shutil.copy2(bundle, embedded)
    embedded.write_bytes(embedded.read_bytes() + b"\n")
    (library / "embedded-scenarios.json").write_text(
        json.dumps(
            {
                "filename": bundle.name,
                "sha256": digest,
                "tool_version": codex_instruct.VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    with pytest.raises(
        codex_instruct.HooksConflict,
        match="digest mismatch; provide --scenario-root",
    ):
        codex_instruct.resolve_scenario_root(None)


def test_production_packages_remain_without_win32():
    for scenario_id in M2_SCENARIOS:
        package = codex_instruct.load_scenario_package(SCENARIO_ROOT, scenario_id)
        assert package.platforms == ("darwin", "linux")
        assert "win32" not in package.platforms

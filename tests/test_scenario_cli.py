import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_cli", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _target(tmp_path, name="target with space 中文"):
    target = tmp_path / name
    target.mkdir()
    (target / "project.txt").write_text("keep\n", encoding="utf-8")
    return target.resolve()


def _manifest(target):
    return json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_scenario_list_is_static_and_ready():
    result = _run("--scenario-list", "--scenario-root", SCENARIO_ROOT.resolve())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "example_fixture 1.0.0: ready" in result.stdout
    assert "verify=verify.py" in result.stdout


def test_scenario_target_must_be_explicit_absolute(tmp_path):
    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        "relative-target",
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
    )

    assert result.returncode == 1
    assert "explicit absolute path" in result.stdout
    assert not (tmp_path / "relative-target").exists()


def test_scenario_target_rejects_tilde_shorthand(tmp_path):
    result = _run(
        "--scenario-status",
        "--target-dir",
        "~/scenario-target",
    )

    assert result.returncode == 1
    assert "explicit absolute path" in result.stdout


@pytest.mark.parametrize(
    "operation",
    [
        ("--scenario-status",),
        ("--scenario-uninstall", "a" * 32),
        ("--scenario-recover",),
    ],
)
def test_all_target_scenario_commands_reject_relative_target(operation):
    result = _run(*operation, "--target-dir", "relative")

    assert result.returncode == 1
    assert "explicit absolute path" in result.stdout


@pytest.mark.parametrize("root_value", ["relative", "/definitely/missing/keysmith-scenarios"])
def test_scenario_list_rejects_invalid_explicit_root(root_value):
    result = _run("--scenario-list", "--scenario-root", root_value)

    assert result.returncode == 1
    assert (
        "explicit absolute path" in result.stdout
        or "does not exist" in result.stdout
    )


def test_scenario_deploy_preview_is_read_only(tmp_path):
    target = _target(tmp_path)
    before = {path.relative_to(target): path.read_bytes() for path in target.iterdir()}

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no files were changed" in result.stdout
    assert not (target / ".codex-keysmith").exists()
    assert {path.relative_to(target): path.read_bytes() for path in target.iterdir()} == before


def test_scenario_deploy_preview_fails_closed_on_existing_target_conflict(tmp_path):
    target = _target(tmp_path)
    control = target / ".codex-keysmith"
    control.mkdir()
    unknown = control / "unexpected.txt"
    unknown.write_text("keep\n", encoding="utf-8")
    before = unknown.read_bytes()

    result = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
    )

    assert result.returncode == 1
    assert "unknown members" in result.stdout
    assert unknown.read_bytes() == before


@pytest.mark.parametrize(
    "args",
    [
        ("--target-dir", os.path.abspath(os.curdir), "--yes"),
        ("--status", "--target-dir", os.path.abspath(os.curdir)),
        ("--uninstall", "--target-dir", os.path.abspath(os.curdir)),
        ("--recover", "--target-dir", os.path.abspath(os.curdir)),
        ("--status", "--scenario-root", str(SCENARIO_ROOT.resolve())),
    ],
)
def test_instruction_commands_reject_scenario_only_paths(args):
    result = _run(*args)

    assert result.returncode == 2
    assert "require a scenario command" in result.stderr


def test_scenario_deploy_status_uninstall_lifecycle(tmp_path):
    target = _target(tmp_path)
    instruction_manifest = target / ".codex-keysmith-manifest.json"
    instruction_manifest.write_text('{"schema_version":1}\n', encoding="utf-8")

    deployed = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    manifest = _manifest(target)
    deployment_id = next(iter(manifest["deployments"]))
    record = manifest["deployments"][deployment_id]
    assert record["scenario_id"] == "example_fixture"
    assert record["root"] == f"scenarios/{deployment_id}"
    assert set(record["files"]) == {
        "scenario.json",
        "task.md",
        "validator.py",
        "verify.py",
        "data/input.json",
    }
    assert instruction_manifest.read_text(encoding="utf-8") == '{"schema_version":1}\n'
    assert (target / "project.txt").read_text(encoding="utf-8") == "keep\n"

    deployed_verify = (
        target / ".codex-keysmith" / record["root"] / "verify.py"
    )
    verify_cwd = tmp_path / "deployed verify cwd 中文"
    verify_cwd.mkdir()
    verified = subprocess.run(
        [sys.executable, str(deployed_verify)],
        cwd=verify_cwd,
        text=True,
        capture_output=True,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "verify passed" in verified.stdout

    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert f"[Deployment] {deployment_id}" in status.stdout
    assert "state=active" in status.stdout

    preview = _run("--scenario-uninstall", deployment_id, "--target-dir", target)
    assert preview.returncode == 0
    assert (target / ".codex-keysmith" / record["root"]).is_dir()

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
    assert instruction_manifest.read_text(encoding="utf-8") == '{"schema_version":1}\n'


def test_same_scenario_deploys_to_two_targets_with_distinct_ids(tmp_path):
    first = _target(tmp_path, "first")
    second = _target(tmp_path, "second")
    deployment_ids = []
    for target in (first, second):
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
        deployment_ids.append(next(iter(_manifest(target)["deployments"])))

    assert deployment_ids[0] != deployment_ids[1]
    assert (first / ".codex-keysmith" / "scenarios" / deployment_ids[0]).is_dir()
    assert (second / ".codex-keysmith" / "scenarios" / deployment_ids[1]).is_dir()


def test_same_target_can_repeat_same_scenario_with_distinct_ids(tmp_path):
    target = _target(tmp_path)
    for _index in range(2):
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

    deployments = _manifest(target)["deployments"]
    assert len(deployments) == 2
    assert {record["scenario_id"] for record in deployments.values()} == {
        "example_fixture"
    }


def test_scenario_fixture_verify_from_unrelated_unicode_cwd(tmp_path):
    cwd = tmp_path / "unrelated cwd 中文"
    cwd.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCENARIO_ROOT / "example_fixture" / "verify.py")],
        cwd=cwd,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "verify passed" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--scenario-list", "--yes"),
        ("--scenario-list", "--file", "README.md"),
        ("--scenario-list", "--name", "ignored"),
        ("--scenario-status",),
        ("--scenario-uninstall", "a" * 32),
        ("--scenario-recover",),
        ("--scenario-status", "--target-dir", os.path.abspath(os.curdir), "--yes"),
        ("--scenario-recover", "--target-dir", os.path.abspath(os.curdir), "--scenario-root", SCENARIO_ROOT.resolve()),
        ("--deploy-scenario", "example_fixture", "--target-dir", os.path.abspath(os.curdir), "--dry-run"),
    ],
)
def test_scenario_cli_rejects_conflicting_arguments(args):
    result = _run(*args)

    assert result.returncode == 2

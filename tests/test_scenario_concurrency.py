import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_concurrency", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _command(target):
    return [
        sys.executable,
        str(MODULE_PATH),
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        str(target),
        "--scenario-root",
        str(SCENARIO_ROOT.resolve()),
        "--yes",
        "--lang",
        "en",
    ]


def _target(tmp_path, name):
    target = (tmp_path / name).resolve()
    target.mkdir()
    return target


def _manifest(target):
    return json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_two_processes_deploy_same_target_without_lost_update(tmp_path):
    target = _target(tmp_path, "shared")
    first = subprocess.Popen(_command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = subprocess.Popen(_command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first_stdout, first_stderr = first.communicate(timeout=30)
    second_stdout, second_stderr = second.communicate(timeout=30)

    assert first.returncode == 0, first_stdout + first_stderr
    assert second.returncode == 0, second_stdout + second_stderr
    deployments = _manifest(target)["deployments"]
    assert len(deployments) == 2
    for deployment_id in deployments:
        assert (target / ".codex-keysmith" / "scenarios" / deployment_id).is_dir()
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))


def test_different_targets_deploy_independently(tmp_path):
    first_target = _target(tmp_path, "first")
    second_target = _target(tmp_path, "second")
    first = subprocess.Popen(_command(first_target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = subprocess.Popen(_command(second_target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first_stdout, first_stderr = first.communicate(timeout=30)
    second_stdout, second_stderr = second.communicate(timeout=30)

    assert first.returncode == 0, first_stdout + first_stderr
    assert second.returncode == 0, second_stdout + second_stderr
    assert len(_manifest(first_target)["deployments"]) == 1
    assert len(_manifest(second_target)["deployments"]) == 1


def test_lock_is_reacquired_after_hard_killed_holder(tmp_path):
    target = _target(tmp_path, "killed-holder")
    child = tmp_path / "holder.py"
    child.write_text(
        f"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("scenario_holder", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

def hook(name):
    if name == "directory-lock-acquired":
        os._exit(86)
m._FILESYSTEM_CHECKPOINT_HOOK = hook
target = m.resolve_scenario_target({str(target)!r})
root = m.resolve_scenario_root({str(SCENARIO_ROOT.resolve())!r})
m.deploy_scenario(target, m.load_scenario_package(root, "example_fixture"), True)
""",
        encoding="utf-8",
    )
    interrupted = subprocess.run([sys.executable, str(child)], text=True, capture_output=True)
    assert interrupted.returncode == 86

    result = subprocess.run(_command(target), text=True, capture_output=True, timeout=30)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_manifest(target)["deployments"]) == 1

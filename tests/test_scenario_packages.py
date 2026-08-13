import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_packages", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)

M2_SCENARIOS = ("aiml_toxigen", "chem_rdkit", "cyber_keystone")
DEPLOYABLE_WITHOUT_EXTRAS = ("aiml_toxigen", "cyber_keystone")


def _platform_name():
    if os.name == "nt" or sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _on_declared_platform():
    return _platform_name() in {"darwin", "linux"}


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _target(tmp_path, name="target"):
    target = (tmp_path / name).resolve()
    target.mkdir()
    (target / "project.txt").write_text("keep\n", encoding="utf-8")
    return target


def _manifest(target):
    return json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(encoding="utf-8")
    )


def _package_dir(scenario_id):
    return SCENARIO_ROOT / scenario_id


def discovered_rdkit_blocker():
    package = codex_instruct.load_scenario_package(SCENARIO_ROOT, "chem_rdkit")
    blockers = [
        codex_instruct._scenario_probe_requirement(requirement)
        for requirement in package.requires
    ]
    return next((blocker for blocker in blockers if blocker), None)


def test_library_discovery_includes_m2_packages():
    discovered = {
        scenario_id: package
        for scenario_id, package, _detail in codex_instruct.discover_scenario_packages(
            SCENARIO_ROOT
        )
    }

    assert discovered["example_fixture"] is not None
    for scenario_id in M2_SCENARIOS:
        package = discovered[scenario_id]
        assert package is not None
        assert package.scenario_id == scenario_id
        assert package.version == "1.0.0"
        assert package.platforms == ("darwin", "linux")
        assert package.python_runtime == ">=3.9,<3.15"
        assert "task.md" in package.files
        assert "validator.py" in package.files
        assert "verify.py" in package.files
        assert "data/input.json" in package.files
        assert not any(relative.startswith("fixtures/") for relative in package.files)


def test_scenario_list_reports_m2_metadata():
    result = _run("--scenario-list", "--scenario-root", SCENARIO_ROOT.resolve())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "example_fixture 1.0.0: ready" in result.stdout
    assert "requires=none" in result.stdout
    assert "requires=rdkit>=2022.9" in result.stdout
    for scenario_id in M2_SCENARIOS:
        assert "{} 1.0.0:".format(scenario_id) in result.stdout
        assert "platforms=darwin,linux" in result.stdout
    if _on_declared_platform():
        assert "cyber_keystone 1.0.0: ready" in result.stdout
        assert "aiml_toxigen 1.0.0: ready" in result.stdout
        chem = discovered_rdkit_blocker()
        if chem is None:
            assert "chem_rdkit 1.0.0: ready" in result.stdout
        else:
            assert "chem_rdkit 1.0.0: blocked" in result.stdout
            assert "install python-module 'rdkit'" in result.stdout
    else:
        assert "platform {} is not declared".format(_platform_name()) in result.stdout


@pytest.mark.parametrize("scenario_id", M2_SCENARIOS)
def test_validator_positive_negative_and_tamper_fixtures(scenario_id):
    package = _package_dir(scenario_id)
    validator = package / "validator.py"

    positive = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--input",
            str(package / "data/input.json"),
            "--output",
            str(package / "fixtures/positive/output.json"),
        ],
        check=False,
    )
    negative = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--input",
            str(package / "data/input.json"),
            "--output",
            str(package / "fixtures/negative/output.json"),
        ],
        check=False,
    )
    tampered = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--input",
            str(package / "fixtures/tampered/input.json"),
            "--output",
            str(package / "fixtures/tampered/output.json"),
        ],
        check=False,
    )

    assert positive.returncode == 0
    assert negative.returncode == 1
    assert tampered.returncode == 2


@pytest.mark.parametrize("scenario_id", M2_SCENARIOS)
def test_validator_missing_section_is_incomplete(scenario_id, tmp_path):
    package = _package_dir(scenario_id)
    output = tmp_path / "missing.json"
    output.write_text(
        json.dumps({"preamble_ack": True, "samples_read": ["sample_01.json"]}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(package / "validator.py"),
            "--input",
            str(package / "data/input.json"),
            "--output",
            str(output),
        ],
        check=False,
    )

    assert result.returncode == 1


@pytest.mark.parametrize("scenario_id", M2_SCENARIOS)
@pytest.mark.parametrize("output_state", ("missing", "malformed", "unreadable"))
def test_validator_invalid_output_is_incomplete(scenario_id, output_state, tmp_path):
    package = _package_dir(scenario_id)
    output = tmp_path / "output.json"
    if output_state == "malformed":
        output.write_text("{not-json\n", encoding="utf-8")
    elif output_state == "unreadable":
        output.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(package / "validator.py"),
            "--input",
            str(package / "data/input.json"),
            "--output",
            str(output),
        ],
        check=False,
    )

    assert result.returncode == 1


@pytest.mark.parametrize("scenario_id", M2_SCENARIOS)
@pytest.mark.parametrize("input_state", ("missing", "malformed", "unreadable", "drifted"))
def test_validator_invalid_input_is_drift(scenario_id, input_state, tmp_path):
    package = _package_dir(scenario_id)
    input_path = tmp_path / "input.json"
    if input_state == "malformed":
        input_path.write_text("{not-json\n", encoding="utf-8")
    elif input_state == "unreadable":
        input_path.mkdir()
    elif input_state == "drifted":
        input_path.write_text(
            (package / "data/input.json").read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            str(package / "validator.py"),
            "--input",
            str(input_path),
            "--output",
            str(package / "fixtures/positive/output.json"),
        ],
        check=False,
    )

    assert result.returncode == 2


@pytest.mark.parametrize("scenario_id", M2_SCENARIOS)
def test_verify_script_from_unrelated_cwd(scenario_id, tmp_path):
    cwd = tmp_path / "unrelated cwd 中文"
    cwd.mkdir()
    result = subprocess.run(
        [sys.executable, str(_package_dir(scenario_id) / "verify.py")],
        cwd=cwd,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "{} verify passed".format(scenario_id) in result.stdout


@pytest.mark.skipif(not _on_declared_platform(), reason="M2 scenarios exclude win32")
@pytest.mark.parametrize("scenario_id", DEPLOYABLE_WITHOUT_EXTRAS)
def test_m2_deploy_status_uninstall_lifecycle(tmp_path, scenario_id):
    target = _target(tmp_path)
    deployed = _run(
        "--deploy-scenario",
        scenario_id,
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
    assert record["scenario_id"] == scenario_id
    payload = target / ".codex-keysmith" / record["root"]
    assert (payload / "task.md").is_file()
    assert (payload / "data/input.json").is_file()
    assert not (payload / "fixtures").exists()
    assert (target / "project.txt").read_text(encoding="utf-8") == "keep\n"

    verify_cwd = tmp_path / "verify-cwd"
    verify_cwd.mkdir()
    verified = subprocess.run(
        [sys.executable, str(payload / "verify.py")],
        cwd=verify_cwd,
        text=True,
        capture_output=True,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr

    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout

    removed = _run(
        "--scenario-uninstall",
        deployment_id,
        "--target-dir",
        target,
        "--yes",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not payload.exists()
    assert _manifest(target)["deployments"] == {}


@pytest.mark.skipif(not _on_declared_platform(), reason="M2 scenarios exclude win32")
def test_m2_scenario_deploys_to_two_targets(tmp_path):
    first = _target(tmp_path, "first")
    second = _target(tmp_path, "second")
    deployment_ids = []
    for target in (first, second):
        result = _run(
            "--deploy-scenario",
            "cyber_keystone",
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


@pytest.mark.skipif(not _on_declared_platform(), reason="M2 scenarios exclude win32")
def test_uninstall_preserves_tampered_payload(tmp_path):
    target = _target(tmp_path)
    deployed = _run(
        "--deploy-scenario",
        "cyber_keystone",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    manifest = _manifest(target)
    deployment_id = next(iter(manifest["deployments"]))
    payload = target / ".codex-keysmith" / manifest["deployments"][deployment_id]["root"]
    task = payload / "task.md"
    task.write_text("tampered fixture content\n", encoding="utf-8")

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
    assert task.read_text(encoding="utf-8") == "tampered fixture content\n"
    assert payload.is_dir()


@pytest.mark.skipif(not _on_declared_platform(), reason="M2 scenarios exclude win32")
def test_chem_rdkit_deploy_blocked_without_rdkit(tmp_path):
    if discovered_rdkit_blocker() is None:
        pytest.skip("rdkit is available in this environment")
    target = _target(tmp_path)
    result = _run(
        "--deploy-scenario",
        "chem_rdkit",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )

    assert result.returncode == 1
    assert "install python-module 'rdkit'" in result.stdout
    assert not (target / ".codex-keysmith").exists()


def test_chem_rdkit_lifecycle_when_probe_satisfied(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_instruct, "_scenario_probe_requirement", lambda _req: None)
    monkeypatch.setattr(codex_instruct, "_scenario_platform_name", lambda: "darwin")
    target = _target(tmp_path)
    package = codex_instruct.load_scenario_package(SCENARIO_ROOT, "chem_rdkit")

    deployment_id = codex_instruct.deploy_scenario(target, package, True)
    assert deployment_id
    payload = target / ".codex-keysmith" / "scenarios" / deployment_id
    assert (payload / "verify.py").is_file()
    assert not (payload / "fixtures").exists()

    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout

    removed = _run(
        "--scenario-uninstall",
        deployment_id,
        "--target-dir",
        target,
        "--yes",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not payload.exists()


def test_m2_scenarios_block_undeclared_windows_platform(monkeypatch):
    monkeypatch.setattr(codex_instruct, "_scenario_platform_name", lambda: "win32")
    for scenario_id in M2_SCENARIOS:
        package = codex_instruct.load_scenario_package(SCENARIO_ROOT, scenario_id)
        blockers = codex_instruct._scenario_static_blockers(package)
        assert any("platform win32 is not declared" in blocker for blocker in blockers)

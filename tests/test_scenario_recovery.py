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
spec = importlib.util.spec_from_file_location("codex_instruct_scenario_recovery", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)

HARD_EXIT = 86


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args), "--lang", "en"],
        text=True,
        capture_output=True,
    )


def _target(tmp_path, name):
    target = (tmp_path / name).resolve()
    target.mkdir()
    (target / "project.txt").write_text("keep\n", encoding="utf-8")
    return target


def _snapshot(target):
    snapshot = {}
    for path in sorted(target.rglob("*")):
        relative = str(path.relative_to(target))
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[relative] = ("directory",)
    return snapshot


def _interrupt_deploy(tmp_path, target, checkpoint, hit=1):
    child = tmp_path / f"deploy-{checkpoint}-{hit}.py"
    child.write_text(
        f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("scenario_child", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

seen = 0
def hook(name):
    global seen
    if name == {checkpoint!r}:
        seen += 1
        if seen == {hit}:
            os._exit({HARD_EXIT})

m._FILESYSTEM_CHECKPOINT_HOOK = hook
target = m.resolve_scenario_target({str(target)!r})
root = m.resolve_scenario_root({str(SCENARIO_ROOT.resolve())!r})
package = m.load_scenario_package(root, "example_fixture")
m.deploy_scenario(target, package, True)
raise AssertionError("checkpoint was not reached")
""",
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )


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
    manifest = json.loads(
        (target / ".codex-keysmith" / "scenario-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return next(iter(manifest["deployments"]))


def _interrupt_uninstall(tmp_path, target, deployment_id, checkpoint, hit=1):
    child = tmp_path / f"uninstall-{checkpoint}-{hit}.py"
    child.write_text(
        f"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("scenario_child", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

seen = 0
def hook(name):
    global seen
    if name == {checkpoint!r}:
        seen += 1
        if seen == {hit}:
            os._exit({HARD_EXIT})

m._FILESYSTEM_CHECKPOINT_HOOK = hook
target = m.resolve_scenario_target({str(target)!r})
m.uninstall_scenario(target, {deployment_id!r}, True)
raise AssertionError("checkpoint was not reached")
""",
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "checkpoint,hit",
    [
        ("scenario-phase-initializing", 2),
        ("scenario-phase-prepared", 1),
        ("scenario-phase-payload-intent", 1),
        ("scenario-phase-manifest-intent", 1),
        ("scenario-phase-final-sweep", 1),
    ],
)
def test_deploy_precommit_phase_interruption_recovers_before_state(
    tmp_path,
    checkpoint,
    hit,
):
    target = _target(tmp_path, f"deploy-{checkpoint}-{hit}")
    before = _snapshot(target)

    interrupted = _interrupt_deploy(tmp_path, target, checkpoint, hit)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    preview_before = _snapshot(target)
    preview = _run("--scenario-recover", "--target-dir", target)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert _snapshot(target) == preview_before

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot(target) == before
    repeated = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert repeated.returncode == 0
    assert "no recovery required" in repeated.stdout


@pytest.mark.parametrize(
    "checkpoint,hit",
    [
        ("scenario-staging-member-published", 1),
        ("scenario-staging-member-published", 3),
        ("scenario-payload-published", 1),
        ("scenario-manifest-intent-published", 1),
    ],
)
def test_deploy_mutation_interruption_recovers_before_state(tmp_path, checkpoint, hit):
    target = _target(tmp_path, f"deploy-{checkpoint}-{hit}")
    before = _snapshot(target)

    interrupted = _interrupt_deploy(tmp_path, target, checkpoint, hit)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot(target) == before


def test_deploy_committed_phase_interruption_keeps_deployment(tmp_path):
    target = _target(tmp_path, "deploy-phase-committed")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-phase-committed",
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout


@pytest.mark.parametrize("hit", range(1, 10))
def test_deploy_json_pending_interruption_is_recoverable(tmp_path, hit):
    target = _target(tmp_path, f"deploy-json-pending-{hit}")
    before = _snapshot(target)

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-json-pending-published",
        hit,
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    if hit == 9:
        status = _run("--scenario-status", "--target-dir", target)
        assert status.returncode == 0
        assert "state=active" in status.stdout
    else:
        assert _snapshot(target) == before
    assert not list(target.rglob("*.pending.json"))

    redeployed = _run(
        "--deploy-scenario",
        "example_fixture",
        "--target-dir",
        target,
        "--scenario-root",
        SCENARIO_ROOT.resolve(),
        "--yes",
    )
    assert redeployed.returncode == 0, redeployed.stdout + redeployed.stderr


@pytest.mark.parametrize("hit", range(1, 10))
def test_deploy_json_publication_interruption_is_recoverable(tmp_path, hit):
    target = _target(tmp_path, f"deploy-json-published-{hit}")
    before = _snapshot(target)

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-json-file-published",
        hit,
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    if hit == 9:
        status = _run("--scenario-status", "--target-dir", target)
        assert status.returncode == 0
        assert "state=active" in status.stdout
    else:
        assert _snapshot(target) == before
    assert not list(target.rglob("*.pending.json"))


def test_initializing_journal_is_recoverable_and_restores_before_state(tmp_path):
    target = _target(tmp_path, "intent-only")
    before = _snapshot(target)

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-intent-published",
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot(target) == before


def test_deploy_committed_cleanup_interruption_keeps_deployment(tmp_path):
    target = _target(tmp_path, "deploy-committed")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-claimed",
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout


def test_deploy_cleanup_claim_interruption_keeps_deployment(tmp_path):
    target = _target(tmp_path, "deploy-cleanup-claim")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-claimed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    assert list(control.glob("scenario-transaction-*.cleanup-*"))
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout
    assert not list(control.glob("scenario-transaction-*.cleanup-*"))


def test_deploy_cleanup_member_interruption_keeps_deployment(tmp_path):
    target = _target(tmp_path, "deploy-cleanup-member")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-member-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    assert list(control.glob("scenario-transaction-*.cleanup-*"))
    assert list(control.glob("scenario-cleanup-*.json"))
    journal = next(control.glob("scenario-transaction-*.cleanup-*"))
    (journal / "journal.json").unlink(missing_ok=True)
    assert not (journal / "journal.json").exists()

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout
    assert not list(control.glob("scenario-transaction-*"))
    assert not list(control.glob("scenario-cleanup-*.json"))


def test_partial_journal_unknown_member_is_conflict_and_preserved(tmp_path):
    target = _target(tmp_path, "partial-journal-unknown-member")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-member-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    journal = next(control.glob("scenario-transaction-*.cleanup-*"))
    (journal / "intruder.txt").write_text("not owned\n", encoding="utf-8")

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert "unknown cleanup evidence" in recovered.stdout
    assert (journal / "intruder.txt").read_text(encoding="utf-8") == "not owned\n"
    assert list(control.glob("scenario-transaction-*.cleanup-*"))
    assert list(control.glob("scenario-cleanup-*.json"))


def test_partial_journal_identity_swap_is_conflict_and_preserved(tmp_path):
    target = _target(tmp_path, "partial-journal-identity-swap")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-member-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    journal = next(control.glob("scenario-transaction-*.cleanup-*"))
    shutil.rmtree(journal)
    journal.mkdir()
    (journal / "intent.json").write_text("{}\n", encoding="utf-8")

    preview = _run("--scenario-recover", "--target-dir", target)
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert preview.returncode == 1
    assert recovered.returncode == 1
    assert "identity changed" in recovered.stdout
    assert (journal / "intent.json").read_text(encoding="utf-8") == "{}\n"
    assert list(control.glob("scenario-cleanup-*.json"))


def test_partial_journal_symlink_member_is_conflict_and_preserved(tmp_path):
    target = _target(tmp_path, "partial-journal-symlink-member")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-member-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    journal = next(control.glob("scenario-transaction-*.cleanup-*"))
    (journal / "journal.json").unlink(missing_ok=True)
    (journal / "journal.json").symlink_to(target / "project.txt")

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert "abnormal" in recovered.stdout
    assert (journal / "journal.json").is_symlink()
    assert list(control.glob("scenario-transaction-*.cleanup-*"))
    assert list(control.glob("scenario-cleanup-*.json"))


def test_deploy_cleanup_marker_interruption_keeps_deployment(tmp_path):
    target = _target(tmp_path, "deploy-cleanup-marker")

    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-directory-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))
    assert list((target / ".codex-keysmith").glob("scenario-cleanup-*.json"))
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "state=active" in status.stdout
    assert not list((target / ".codex-keysmith").glob("scenario-cleanup-*.json"))


def test_deploy_cleanup_marker_preserves_manifest_drift(tmp_path):
    target = _target(tmp_path, "deploy-cleanup-marker-manifest-drift")
    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-directory-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    marker = next(control.glob("scenario-cleanup-*.json"))
    manifest_path = control / "scenario-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["deployments"] = {}
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    marker_before = marker.read_bytes()

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert "manifest no longer matches" in recovered.stdout
    assert marker.read_bytes() == marker_before


def test_deploy_claimed_cleanup_marker_recovery_is_reentrant(tmp_path):
    target = _target(tmp_path, "deploy-claimed-cleanup-marker")
    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-directory-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    marker = next(control.glob("scenario-cleanup-*.json"))
    claimed = marker.with_name(marker.name + ".cleanup-" + "a" * 32)
    marker.rename(claimed)

    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not claimed.exists()
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "state=active" in status.stdout


def test_recovered_cleanup_marker_interruption_is_reentrant(tmp_path):
    target = _target(tmp_path, "recovered-cleanup-marker")
    first = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-payload-published",
    )
    assert first.returncode == HARD_EXIT

    child = tmp_path / "recover-cleanup-marker.py"
    child.write_text(
        f"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("scenario_child", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

def hook(name):
    if name == "scenario-journal-cleanup-marker-published":
        os._exit({HARD_EXIT})

m._FILESYSTEM_CHECKPOINT_HOOK = hook
target = m.resolve_scenario_target({str(target)!r})
m.recover_scenario(target, True)
raise AssertionError("checkpoint was not reached")
""",
        encoding="utf-8",
    )
    interrupted = subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )
    assert interrupted.returncode == HARD_EXIT

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout
    assert not list((target / ".codex-keysmith").glob("scenario-transaction-*"))
    assert not list((target / ".codex-keysmith").glob("scenario-cleanup-*"))


def test_forged_cleanup_marker_is_conflict_and_preserved(tmp_path):
    target = _target(tmp_path, "forged-cleanup-marker")
    control = target / ".codex-keysmith"
    control.mkdir()
    marker = control / ("scenario-cleanup-" + "a" * 32 + ".json")
    marker.write_text(
        json.dumps(
            {
                "target": {"path": str(target)},
                "transaction_id": "a" * 32,
                "phase": "recovered",
                "operation": "deploy",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    before = marker.read_bytes()
    status = _run("--scenario-status", "--target-dir", target)
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert status.returncode == 1
    assert "conflict" in status.stdout
    assert recovered.returncode == 1
    assert marker.read_bytes() == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["deployment"].update(scenario_id="wrong-id"),
        lambda data: data["deployment"].update(root_identity={
            **data["deployment"]["root_identity"],
            "device": data["deployment"]["root_identity"]["device"] + 1,
        }),
        lambda data: data["manifest"].update(before_snapshot="unexpected"),
        lambda data: data["manifest"]["published"].update(sha256="0" * 64),
        lambda data: data["target"]["identity"].update(platform="unexpected"),
    ],
)
def test_cleanup_marker_tampering_is_conflict_and_preserved(tmp_path, mutate):
    target = _target(tmp_path, "tampered-cleanup-marker")
    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-cleanup-directory-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    marker = next((target / ".codex-keysmith").glob("scenario-cleanup-*.json"))
    data = json.loads(marker.read_text(encoding="utf-8"))
    mutate(data)
    marker.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    before = marker.read_bytes()

    status = _run("--scenario-status", "--target-dir", target)
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert status.returncode == 1
    assert "conflict" in status.stdout
    assert recovered.returncode == 1
    assert marker.read_bytes() == before


def test_deploy_recovery_preserves_rebound_live_payload(tmp_path):
    target = _target(tmp_path, "deploy-rebound-live")
    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-payload-published",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    journal = next(control.glob("scenario-transaction-*"))
    data = json.loads((journal / "journal.json").read_text(encoding="utf-8"))
    live = control / data["payload"]["live"]
    replacement = target / "replacement-payload"
    live.rename(replacement)
    live.mkdir()
    for source in replacement.rglob("*"):
        relative = source.relative_to(replacement)
        destination = live / relative
        if source.is_dir():
            destination.mkdir()
        else:
            destination.write_bytes(source.read_bytes())
    replacement.rename(target / "original-payload-evidence")

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert "identity changed" in recovered.stdout
    assert live.is_dir()
    assert list(control.glob("scenario-transaction-*"))


def test_deploy_recovery_preserves_unowned_staging_without_durable_identity(tmp_path):
    target = _target(tmp_path, "deploy-unowned-staging")
    interrupted = _interrupt_deploy(
        tmp_path,
        target,
        "scenario-journal-directory-created",
    )
    assert interrupted.returncode == HARD_EXIT
    journal = next((target / ".codex-keysmith").glob("scenario-transaction-*"))
    staging = journal / "payload-staging"
    staging.mkdir()

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert "without a durable recorded identity" in recovered.stdout
    assert staging.is_dir()


@pytest.mark.parametrize(
    "checkpoint,hit",
    [
        ("scenario-phase-initializing", 1),
        ("scenario-phase-prepared", 1),
        ("scenario-phase-payload-remove-intent", 1),
        ("scenario-phase-manifest-intent", 1),
        ("scenario-phase-final-sweep", 1),
    ],
)
def test_uninstall_precommit_phase_interruption_recovers_installed_state(
    tmp_path,
    checkpoint,
    hit,
):
    target = _target(tmp_path, f"uninstall-{checkpoint}-{hit}")
    deployment_id = _deploy(target)
    before = _snapshot(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        checkpoint,
        hit,
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot(target) == before
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert f"[Deployment] {deployment_id}" in status.stdout


@pytest.mark.parametrize(
    "checkpoint,hit",
    [
        ("scenario-payload-claimed-for-uninstall", 1),
        ("scenario-manifest-intent-published", 1),
    ],
)
def test_uninstall_mutation_interruption_recovers_installed_state(
    tmp_path,
    checkpoint,
    hit,
):
    target = _target(tmp_path, f"uninstall-{checkpoint}-{hit}")
    deployment_id = _deploy(target)
    before = _snapshot(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        checkpoint,
        hit,
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot(target) == before


def test_uninstall_committed_phase_interruption_finishes_removal(tmp_path):
    target = _target(tmp_path, "uninstall-phase-committed")
    deployment_id = _deploy(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-phase-committed",
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout


@pytest.mark.parametrize("hit", range(1, 8))
def test_uninstall_json_pending_interruption_is_recoverable(tmp_path, hit):
    target = _target(tmp_path, f"uninstall-json-pending-{hit}")
    deployment_id = _deploy(target)
    before = _snapshot(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-json-pending-published",
        hit,
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    if hit == 7:
        status = _run("--scenario-status", "--target-dir", target)
        assert status.returncode == 0
        assert "not-installed" in status.stdout
    else:
        assert _snapshot(target) == before
    assert not list(target.rglob("*.pending.json"))


@pytest.mark.parametrize("hit", range(1, 8))
def test_uninstall_json_publication_interruption_is_recoverable(tmp_path, hit):
    target = _target(tmp_path, f"uninstall-json-published-{hit}")
    deployment_id = _deploy(target)
    before = _snapshot(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-json-file-published",
        hit,
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    if hit == 7:
        status = _run("--scenario-status", "--target-dir", target)
        assert status.returncode == 0
        assert "not-installed" in status.stdout
    else:
        assert _snapshot(target) == before
    assert not list(target.rglob("*.pending.json"))


def test_uninstall_committed_cleanup_interruption_finishes_removal(tmp_path):
    target = _target(tmp_path, "uninstall-committed")
    deployment_id = _deploy(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-owned-file-removed",
        1,
    )
    assert interrupted.returncode == HARD_EXIT
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 1
    assert "recovery-required" in status.stdout

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout


def test_uninstall_cleanup_marker_interruption_finishes_removal(tmp_path):
    target = _target(tmp_path, "uninstall-cleanup-marker")
    deployment_id = _deploy(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-journal-cleanup-directory-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    assert list((target / ".codex-keysmith").glob("scenario-cleanup-*.json"))

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout
    assert not list((target / ".codex-keysmith").glob("scenario-cleanup-*.json"))


def test_uninstall_cleanup_member_interruption_finishes_removal(tmp_path):
    target = _target(tmp_path, "uninstall-cleanup-member")
    deployment_id = _deploy(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-journal-cleanup-member-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    assert list(control.glob("scenario-transaction-*.cleanup-*"))
    assert list(control.glob("scenario-cleanup-*.json"))
    journal = next(control.glob("scenario-transaction-*.cleanup-*"))
    (journal / "journal.json").unlink(missing_ok=True)
    assert not (journal / "journal.json").exists()

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout
    assert not list(control.glob("scenario-transaction-*"))
    assert not list(control.glob("scenario-cleanup-*.json"))


def test_uninstall_cleanup_payload_partial_removal_finishes_forward(tmp_path):
    target = _target(tmp_path, "uninstall-cleanup-payload-partial")
    deployment_id = _deploy(target)

    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-owned-file-removed",
    )
    assert interrupted.returncode == HARD_EXIT
    control = target / ".codex-keysmith"
    journal = next(control.glob("scenario-transaction-*"))
    removed = journal / "removed-payload"
    assert removed.is_dir()
    assert os.listdir(removed)

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    status = _run("--scenario-status", "--target-dir", target)
    assert status.returncode == 0
    assert "not-installed" in status.stdout
    assert not list(control.glob("scenario-transaction-*"))
    assert not list(control.glob("scenario-cleanup-*.json"))


def test_recovery_fails_closed_when_payload_path_is_recreated_after_uninstall_claim(
    tmp_path,
):
    target = _target(tmp_path, "uninstall-recreated")
    deployment_id = _deploy(target)
    interrupted = _interrupt_uninstall(
        tmp_path,
        target,
        deployment_id,
        "scenario-payload-claimed-for-uninstall",
    )
    assert interrupted.returncode == HARD_EXIT
    live = target / ".codex-keysmith" / "scenarios" / deployment_id
    live.mkdir()
    (live / "user.txt").write_text("keep\n", encoding="utf-8")

    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert recovered.returncode == 1
    assert (live / "user.txt").read_text(encoding="utf-8") == "keep\n"
    assert list((target / ".codex-keysmith").glob("scenario-transaction-*"))


@pytest.mark.parametrize(
    "operation,interrupt,wrong_phase",
    [
        ("deploy", "scenario-phase-prepared", "payload-remove-intent"),
        ("uninstall", "scenario-phase-prepared", "payload-intent"),
        ("deploy", "scenario-phase-prepared", "unknown-phase"),
    ],
)
def test_recovery_rejects_journal_phase_not_allowed_for_operation(
    tmp_path,
    operation,
    interrupt,
    wrong_phase,
):
    target = _target(tmp_path, f"wrong-phase-{operation}-{wrong_phase}")
    if operation == "deploy":
        interrupted = _interrupt_deploy(tmp_path, target, interrupt)
    else:
        deployment_id = _deploy(target)
        interrupted = _interrupt_uninstall(
            tmp_path,
            target,
            deployment_id,
            interrupt,
        )
    assert interrupted.returncode == HARD_EXIT
    journal = next((target / ".codex-keysmith").glob("scenario-transaction-*"))
    journal_path = journal / "journal.json"
    data = json.loads(journal_path.read_text(encoding="utf-8"))
    data["phase"] = wrong_phase
    journal_path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    before = journal_path.read_bytes()

    status = _run("--scenario-status", "--target-dir", target)
    recovered = _run("--scenario-recover", "--target-dir", target, "--yes")

    assert status.returncode == 1
    assert "conflict" in status.stdout
    assert recovered.returncode == 1
    assert journal_path.read_bytes() == before

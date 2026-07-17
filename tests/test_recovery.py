import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct_recovery", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _make_codex_dir(tmp_path, name):
    codex_dir = tmp_path / name
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text('model = "gpt-5.6"\n', encoding="utf-8")
    return codex_dir


def _run(*args):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *map(str, args)],
        text=True,
        capture_output=True,
    )


def _prepare_journals(codex_dirs):
    deployment_id = uuid.uuid4().hex
    plans = [codex_instruct.inspect_directory(path) for path in codex_dirs]
    states = [
        codex_instruct.DeploymentState(path, deployment_id=deployment_id)
        for path in codex_dirs
    ]
    codex_instruct._create_deployment_journals(
        states,
        plans,
        codex_instruct.DEFAULT_MD_FILENAME,
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        False,
    )
    return states, plans


def test_multi_directory_recover_restores_before_state(tmp_path):
    first = _make_codex_dir(tmp_path, "first")
    second = _make_codex_dir(tmp_path, "second")
    states, plans = _prepare_journals([first, second])
    for codex_dir, plan in zip((first, second), plans):
        (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
            encoding="utf-8",
        )
        (codex_dir / "config.toml").write_text(
            plan.updated_config_content,
            encoding="utf-8",
        )

    codex_instruct.recover_deployment([str(first)], yes=True)

    for codex_dir in (first, second):
        assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
            'model = "gpt-5.6"\n'
        )
        assert not (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).exists()
        assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert all(state.journal_dir is not None for state in states)


def test_recover_fails_closed_on_owned_path_drift(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "drift")
    _prepare_journals([codex_dir])
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    prompt.write_text("concurrent user content\n", encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert prompt.read_text(encoding="utf-8") == "concurrent user content\n"
    assert list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_deploy_recovery_rejects_non_string_phase_without_traceback(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "invalid-phase")
    _prepare_journals([codex_dir])
    journal_dir = next(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    journal = journal_dir / codex_instruct.JOURNAL_FILENAME
    data = json.loads(journal.read_text(encoding="utf-8"))
    data["phase"] = {}
    journal.write_text(json.dumps(data), encoding="utf-8")

    recovered = _run(
        "--codex-dir",
        codex_dir,
        "--recover",
        "--yes",
        "--lang",
        "en",
    )

    assert recovered.returncode == 1
    output = recovered.stdout + recovered.stderr
    assert "Traceback" not in output
    assert not any("\u3400" <= character <= "\u9fff" for character in output)


def test_deploy_recovery_rejects_tampered_base_with_valid_pending(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "tampered-base-valid-pending")
    _prepare_journals([codex_dir])
    journal_dir = next(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    journal = journal_dir / codex_instruct.JOURNAL_FILENAME
    pending = journal_dir / codex_instruct.JOURNAL_PENDING_FILENAME
    valid_bytes = journal.read_bytes()
    pending.write_bytes(valid_bytes)
    data = json.loads(valid_bytes)
    data["directories"] = []
    journal.write_text(json.dumps(data), encoding="utf-8")
    base_bytes = journal.read_bytes()
    pending_bytes = pending.read_bytes()

    recovered = _run(
        "--codex-dir",
        codex_dir,
        "--recover",
        "--yes",
        "--lang",
        "en",
    )

    output = recovered.stdout + recovered.stderr
    assert recovered.returncode == 1
    assert "Traceback" not in output
    assert not any("\u3400" <= character <= "\u9fff" for character in output)
    assert journal.read_bytes() == base_bytes
    assert pending.read_bytes() == pending_bytes


def test_deploy_keeps_journal_absent_md_precondition_after_publication(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path, "late-md-fail-closed")
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    late_user_bytes = b"late-user-md\x00\xff\r\n"
    monkeypatch.setattr(codex_instruct, "find_codex_dirs", lambda: [str(codex_dir)])
    original_update = codex_instruct._update_deployment_journals
    original_write = codex_instruct.atomic_write_text
    md_write_intents = []
    late_created = False

    def publish_phase_then_create_late_md(states, phase, manifest_sha256=None):
        nonlocal late_created
        original_update(states, phase, manifest_sha256)
        if phase == "files-intent" and not late_created:
            late_created = True
            prompt.write_bytes(late_user_bytes)

    def record_md_write_intent(path, content, *args, **kwargs):
        if Path(path) == prompt:
            md_write_intents.append(
                (
                    kwargs.get("expected_fingerprint"),
                    kwargs.get("require_absent", False),
                )
            )
        return original_write(path, content, *args, **kwargs)

    monkeypatch.setattr(
        codex_instruct,
        "_update_deployment_journals",
        publish_phase_then_create_late_md,
    )
    monkeypatch.setattr(codex_instruct, "atomic_write_text", record_md_write_intent)
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.deploy(args)

    assert caught.value.code == 1
    assert md_write_intents == [(None, True)]
    assert prompt.read_bytes() == late_user_bytes
    assert not list(codex_dir.glob(f"{prompt.name}.bak_*"))
    assert not codex_instruct._hooks_transaction_residue(codex_dir)
    assert (codex_dir / "config.toml").read_bytes() == b'model = "gpt-5.6"\n'


def test_recover_restores_late_md_claimed_during_hard_interruption(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "late-md-hard-interrupt")
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    late_user_bytes = b"late-user-md\x00\xff\r\n"
    child = tmp_path / "kill_after_late_md_publish.py"
    child.write_text(
        f"""
import importlib.util, os, sys, uuid
from pathlib import Path
module_path = Path({str(MODULE_PATH)!r})
codex_dir = Path({str(codex_dir)!r})
spec = importlib.util.spec_from_file_location('late_md_child', module_path)
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
deployment_id = uuid.uuid4().hex
plan = m.inspect_directory(codex_dir)
state = m.DeploymentState(codex_dir, deployment_id=deployment_id)
m._ACTIVE_DEPLOYMENT_TRANSACTION_ID = deployment_id
m._ACTIVE_DEPLOYMENT_STATES = [state]
m._create_deployment_journals(
    [state], [plan], m.DEFAULT_MD_FILENAME, m.BUILTIN_GPT_UNRESTRICTED_MD, False
)
m._update_deployment_journals([state], 'files-intent')
prompt = codex_dir / m.DEFAULT_MD_FILENAME
prompt.write_bytes({late_user_bytes!r})
late_fingerprint = m._fingerprint_regular_file(prompt)
m.backup_file(prompt, '20000101_000000', expected_fingerprint=late_fingerprint)
original_rename = m._atomic_rename_no_replace
def kill_after_publish(source, destination):
    published = original_rename(source, destination)
    if published and Path(destination) == prompt and Path(source).name == 'prepared':
        os._exit(86)
    return published
m._atomic_rename_no_replace = kill_after_publish
m.atomic_write_text(
    prompt,
    m.BUILTIN_GPT_UNRESTRICTED_MD,
    expected_fingerprint=late_fingerprint,
)
raise AssertionError('hard-interruption checkpoint was not reached')
""",
        encoding="utf-8",
    )

    interrupted = subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )

    assert interrupted.returncode == 86, interrupted.stdout + interrupted.stderr
    assert prompt.read_bytes() == codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD.encode(
        "utf-8"
    )
    backups = list(codex_dir.glob(f"{prompt.name}.bak_*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == late_user_bytes

    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert prompt.read_bytes() == late_user_bytes
    assert (codex_dir / "config.toml").read_bytes() == b'model = "gpt-5.6"\n'
    assert not codex_instruct._hooks_transaction_residue(codex_dir)

    repeated = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert prompt.read_bytes() == late_user_bytes


def test_recover_preserves_unknown_concurrent_residue(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "unknown-residue")
    _prepare_journals([codex_dir])
    unknown = codex_dir / ".keysmith-hooks-another-transaction"
    unknown.mkdir()

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert unknown.is_dir()
    assert list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recover_does_not_trust_matching_transaction_prefix(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "forged-residue")
    states, _plans = _prepare_journals([codex_dir])
    transaction_id = states[0].deployment_id
    forged = codex_dir / f".keysmith-write-{transaction_id}-user-owned"
    forged.mkdir()
    sentinel = forged / "SENTINEL"
    sentinel.write_text("unrelated\n", encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert sentinel.read_text(encoding="utf-8") == "unrelated\n"
    assert list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recover_rejects_tampered_external_participant(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "source")
    external = _make_codex_dir(tmp_path, "external")
    states, _plans = _prepare_journals([codex_dir])
    journal_path = states[0].journal_dir / codex_instruct.JOURNAL_FILENAME
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["participants"].append(str(external.resolve()))
    data["directories"][str(external.resolve())] = data["directories"][
        str(codex_dir.resolve())
    ]
    codex_instruct._atomic_write_private_json(journal_path, data)

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert (external / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.6"\n'
    )


def test_recover_cleans_verified_partial_initialization_only(tmp_path):
    first = _make_codex_dir(tmp_path, "partial-first")
    second = _make_codex_dir(tmp_path, "partial-second")
    states, _plans = _prepare_journals([first, second])
    first_journal = states[0].journal_dir
    data = codex_instruct._load_deployment_journal(first_journal)
    data["phase"] = "initializing"
    codex_instruct._atomic_write_private_json(
        first_journal / codex_instruct.JOURNAL_FILENAME,
        data,
    )
    (first_journal / "snapshot-config").unlink()
    shutil.rmtree(states[1].journal_dir)

    result = _run("--codex-dir", first, "--recover", "--yes")

    assert result.returncode == 0
    assert not first_journal.exists()
    assert (first / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.6"\n'
    )


def test_recover_cleans_partial_initialization_snapshot_bytes(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "partial-snapshot")
    states, _plans = _prepare_journals([codex_dir])
    journal_dir = states[0].journal_dir
    data = codex_instruct._load_deployment_journal(journal_dir)
    data["phase"] = "initializing"
    codex_instruct._atomic_write_private_json(
        journal_dir / codex_instruct.JOURNAL_FILENAME,
        data,
    )
    (journal_dir / "snapshot-config").write_bytes(b"partial")

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.6"\n'
    )
    assert not journal_dir.exists()


def test_recover_rejects_resource_path_tamper_without_touching_victim(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "path-tamper")
    states, _plans = _prepare_journals([codex_dir])
    victim = codex_dir / "victim.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    journal_path = states[0].journal_dir / codex_instruct.JOURNAL_FILENAME
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["directories"][str(codex_dir.resolve())]["resources"]["md"][
        "path"
    ] = victim.name
    data["directories"][str(codex_dir.resolve())]["resources"]["md"][
        "allowed_sha256"
    ] = [codex_instruct._fingerprint_regular_file(victim).sha256]
    codex_instruct._atomic_write_private_json(journal_path, data)

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert victim.read_text(encoding="utf-8") == "keep me\n"


def test_safe_cleanup_rejects_replaced_directory_and_missing_snapshot(tmp_path):
    owned = tmp_path / "owned"
    owned.mkdir()
    snapshot = owned / "snapshot"
    snapshot.write_text("original\n", encoding="utf-8")
    identity = codex_instruct._directory_identity(owned)
    fingerprint = codex_instruct._fingerprint_regular_file(snapshot)
    moved = tmp_path / "moved"
    owned.rename(moved)
    owned.mkdir()
    sentinel = owned / "sentinel"
    sentinel.write_text("unrelated\n", encoding="utf-8")

    with pytest.raises(codex_instruct.HooksConflict):
        codex_instruct._safe_remove_owned_directory(
            owned,
            identity,
            {"snapshot": fingerprint},
            require_exact_members=True,
        )
    assert sentinel.read_text(encoding="utf-8") == "unrelated\n"

    moved_snapshot = moved / "snapshot"
    moved_snapshot.unlink()
    with pytest.raises(codex_instruct.HooksConflict):
        codex_instruct._safe_remove_owned_directory(
            moved,
            identity,
            {"snapshot": fingerprint},
            require_exact_members=True,
        )
    assert moved.is_dir()

    changed = tmp_path / "changed-member"
    changed.mkdir()
    member = changed / "snapshot"
    member.write_text("original\n", encoding="utf-8")
    changed_identity = codex_instruct._directory_identity(changed)
    original_fingerprint = codex_instruct._fingerprint_regular_file(member)
    member.write_text("concurrent\n", encoding="utf-8")
    with pytest.raises(codex_instruct.HooksConflict):
        codex_instruct._safe_remove_owned_directory(
            changed,
            changed_identity,
            {"snapshot": original_fingerprint},
            require_exact_members=True,
        )
    assert member.read_text(encoding="utf-8") == "concurrent\n"


def test_deploy_cleanup_rejects_replaced_journal_without_rollback(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path, "deploy-cleanup-race")
    monkeypatch.setattr(
        codex_instruct,
        "find_codex_dirs",
        lambda: [str(codex_dir)],
    )
    original = codex_instruct._safe_remove_owned_directory
    sentinel = None

    def replace_journal(path, identity, members, require_exact_members=False):
        nonlocal sentinel
        if path.name.startswith(codex_instruct.JOURNAL_PREFIX) and sentinel is None:
            path.rename(path.with_name(path.name + ".owned-evidence"))
            path.mkdir()
            sentinel = path / "sentinel"
            sentinel.write_text("unrelated\n", encoding="utf-8")
        return original(path, identity, members, require_exact_members)

    monkeypatch.setattr(
        codex_instruct,
        "_safe_remove_owned_directory",
        replace_journal,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.deploy(args)

    assert caught.value.code == 1
    assert sentinel is not None
    assert sentinel.read_text(encoding="utf-8") == "unrelated\n"
    assert (codex_dir / codex_instruct.MANIFEST_FILENAME).is_file()
    assert (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).is_file()


def test_committed_multi_directory_cleanup_resumes_after_first_journal_removed(
    tmp_path,
):
    first = _make_codex_dir(tmp_path, "committed-first")
    second = _make_codex_dir(tmp_path, "committed-second")
    child = tmp_path / "kill_committed.py"
    child.write_text(
        f"""
import importlib.util, os, signal, types
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.find_codex_dirs = lambda: [{str(first)!r}, {str(second)!r}]
original = m._remove_deployment_journals
def kill_after_first(states):
    original(states[:1])
    os.kill(os.getpid(), signal.SIGKILL)
m._remove_deployment_journals = kill_after_first
m.deploy(types.SimpleNamespace(file=None, name='gpt-unrestricted', dry_run=False, yes=True, skip_hooks_isolation=False))
""",
        encoding="utf-8",
    )
    child_result = subprocess.run([sys.executable, str(child)])
    assert child_result.returncode < 0
    assert not list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    remaining = list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert len(remaining) == 1

    resumed = _run("--codex-dir", second, "--recover", "--yes")

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not remaining[0].exists()
    assert (first / codex_instruct.MANIFEST_FILENAME).is_file()
    assert (second / codex_instruct.MANIFEST_FILENAME).is_file()


@pytest.mark.parametrize("race", ["move", "replace"])
def test_deploy_terminal_cleanup_finalizes_marker_before_journal_mutation(
    tmp_path,
    race,
):
    first = _make_codex_dir(tmp_path, f"deploy-terminal-{race}-first")
    second = _make_codex_dir(tmp_path, f"deploy-terminal-{race}-second")
    marker_source = f"""
import importlib.util
import os
import sys
import types
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
m.find_codex_dirs = lambda: [{str(first)!r}, {str(second)!r}]
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit(86)
    return result

m._atomic_rename_no_replace = wrapped
m.deploy(types.SimpleNamespace(
    file=None,
    name="gpt-unrestricted",
    dry_run=False,
    yes=True,
    skip_hooks_isolation=False,
))
"""
    interrupted = tmp_path / f"interrupt-deploy-terminal-{race}.py"
    interrupted.write_text(marker_source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(interrupted)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 86, result.stdout + result.stderr
    second_journal = next(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))

    race_source = f"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._cleanup_terminal_journals
race = {race!r}

def wrapped(journals, phase, yes, retained_cleanup_markers):
    marker = retained_cleanup_markers[0][0]
    if race == "move":
        marker.rename(marker.with_name("moved-retained-marker"))
    else:
        marker.unlink()
        marker.write_bytes(b"replacement cleanup marker\\n")
    return real(journals, phase, yes, retained_cleanup_markers)

m._cleanup_terminal_journals = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    raced = tmp_path / f"race-deploy-terminal-{race}.py"
    raced.write_text(race_source, encoding="utf-8")
    raced_result = subprocess.run(
        [sys.executable, str(raced)],
        text=True,
        capture_output=True,
    )

    assert raced_result.returncode == 1, raced_result.stdout + raced_result.stderr
    assert second_journal.exists()
    markers = codex_instruct._deployment_cleanup_markers(first)
    assert markers
    if race == "move":
        assert not (first / "moved-retained-marker").exists()
        resumed = _run("--codex-dir", second, "--recover", "--yes")
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert not codex_instruct._hooks_transaction_residue(first)
        assert not codex_instruct._hooks_transaction_residue(second)
    else:
        assert any(
            path.read_bytes() == b"replacement cleanup marker\n"
            for path in markers
        )
        resumed = _run("--codex-dir", second, "--recover", "--yes")
        assert resumed.returncode == 1
        assert second_journal.exists()


def test_committed_terminal_cleanup_discovers_all_participant_journals(tmp_path):
    first = _make_codex_dir(tmp_path, "terminal-first")
    second = _make_codex_dir(tmp_path, "terminal-second")
    child = tmp_path / "leave_committed.py"
    child.write_text(
        f"""
import importlib.util, sys, types
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
m.find_codex_dirs = lambda: [{str(first)!r}, {str(second)!r}]
m._remove_deployment_journals = lambda states: None
m.deploy(types.SimpleNamespace(file=None, name='gpt-unrestricted', dry_run=False, yes=True, skip_hooks_isolation=False))
""",
        encoding="utf-8",
    )
    deployed = subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    assert list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert not list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recovered_multi_directory_cleanup_resumes_after_first_journal_removed(
    tmp_path,
):
    first = _make_codex_dir(tmp_path, "recovered-first")
    second = _make_codex_dir(tmp_path, "recovered-second")
    _states, plans = _prepare_journals([first, second])
    for codex_dir, plan in zip((first, second), plans):
        (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
            codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
            encoding="utf-8",
        )
        (codex_dir / "config.toml").write_text(
            plan.updated_config_content,
            encoding="utf-8",
        )
    child = tmp_path / "kill_recovered.py"
    child.write_text(
        f"""
import importlib.util, os, signal
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
original = m._safe_remove_owned_directory
seen = 0
def kill_before_second(path, identity, members, require_exact_members=False):
    global seen
    if path.name.startswith(m.JOURNAL_PREFIX):
        seen += 1
        if seen == 2:
            os.kill(os.getpid(), signal.SIGKILL)
    return original(path, identity, members, require_exact_members)
m._safe_remove_owned_directory = kill_before_second
m.recover_deployment([{str(first)!r}], True)
""",
        encoding="utf-8",
    )
    child_result = subprocess.run([sys.executable, str(child)])
    assert child_result.returncode < 0
    assert not list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    remaining = list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert len(remaining) == 1

    resumed = _run("--codex-dir", second, "--recover", "--yes")

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not remaining[0].exists()
    for codex_dir in (first, second):
        assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
            'model = "gpt-5.6"\n'
        )
        assert not (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-exit coverage")
def test_recover_resumes_after_journal_member_cleanup_interruption(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "journal-cleanup-kill")
    _states, plans = _prepare_journals([codex_dir])
    (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    (codex_dir / "config.toml").write_text(
        plans[0].updated_config_content,
        encoding="utf-8",
    )
    child = tmp_path / "kill_journal_cleanup.py"
    child.write_text(
        f"""
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
real = m.os.unlink
def kill_after_journal(name, *args, **kwargs):
    result = real(name, *args, **kwargs)
    if str(name) == m.JOURNAL_FILENAME and kwargs.get('dir_fd') is not None:
        os._exit(91)
    return result
m.os.unlink = kill_after_journal
m.recover_deployment([{str(codex_dir)!r}], True)
""",
        encoding="utf-8",
    )

    interrupted = subprocess.run([sys.executable, str(child)])

    assert interrupted.returncode == 91
    assert list(
        codex_dir.glob(
            f"{codex_instruct.JOURNAL_PREFIX}*{codex_instruct.CLEANUP_CLAIM_SEPARATOR}*"
        )
    )
    resumed = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert not list(
        codex_dir.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-exit coverage")
def test_recover_resumes_after_cleanup_marker_publication(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "cleanup-marker-kill")
    _states, plans = _prepare_journals([codex_dir])
    (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    (codex_dir / "config.toml").write_text(
        plans[0].updated_config_content,
        encoding="utf-8",
    )
    child = tmp_path / "kill_cleanup_marker.py"
    child.write_text(
        f"""
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
real = m._atomic_rename_no_replace
def kill_after_marker(source, destination):
    result = real(source, destination)
    if Path(source).name == m.INTENT_FILENAME and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX):
        os._exit(92)
    return result
m._atomic_rename_no_replace = kill_after_marker
m.recover_deployment([{str(codex_dir)!r}], True)
""",
        encoding="utf-8",
    )

    interrupted = subprocess.run([sys.executable, str(child)])

    assert interrupted.returncode == 92
    markers = list(
        codex_dir.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )
    assert len(markers) == 1
    resumed = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not markers[0].exists()
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_safe_cleanup_preserves_directory_created_after_atomic_claim(
    tmp_path,
    monkeypatch,
):
    owned = tmp_path / "owned"
    owned.mkdir()
    member = owned / "snapshot"
    member.write_text("owned\n", encoding="utf-8")
    identity = codex_instruct._directory_identity(owned)
    fingerprint = codex_instruct._fingerprint_regular_file(member)
    original_rename = codex_instruct._atomic_rename_no_replace

    def replace_original_after_claim(source, destination):
        result = original_rename(source, destination)
        if Path(source) == owned and result:
            owned.mkdir()
            (owned / "sentinel").write_text("concurrent\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        codex_instruct,
        "_atomic_rename_no_replace",
        replace_original_after_claim,
    )

    codex_instruct._safe_remove_owned_directory(
        owned,
        identity,
        {"snapshot": fingerprint},
        require_exact_members=True,
    )

    assert (owned / "sentinel").read_text(encoding="utf-8") == "concurrent\n"
    assert not list(
        tmp_path.glob(f"owned{codex_instruct.CLEANUP_CLAIM_SEPARATOR}*")
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-exit coverage")
def test_recover_reenters_after_remove_claim_interruption(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "recover-reentrant-remove")
    _states, _plans = _prepare_journals([codex_dir])
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    prompt.write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    child = tmp_path / "kill_recover_remove.py"
    child.write_text(
        f"""
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
real = m._atomic_rename_no_replace
target = Path({str(prompt)!r})
def kill_after_claim(source, destination):
    result = real(source, destination)
    if Path(source) == target and '.keysmith-write-remove-' in Path(destination).parent.name:
        os._exit(99)
    return result
m._atomic_rename_no_replace = kill_after_claim
m.recover_deployment([{str(codex_dir)!r}], True)
""",
        encoding="utf-8",
    )

    interrupted = subprocess.run([sys.executable, str(child)])

    assert interrupted.returncode == 99
    assert not prompt.exists()
    assert list(codex_dir.glob(".keysmith-write-remove-*"))
    resumed = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert not prompt.exists()
    assert not list(codex_dir.glob(".keysmith-write-remove-*"))
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-exit coverage")
def test_recover_reenters_after_replace_claim_interruption(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "recover-reentrant-replace")
    _states, plans = _prepare_journals([codex_dir])
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    prompt.write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    config = codex_dir / "config.toml"
    config.write_text(plans[0].updated_config_content, encoding="utf-8")
    child = tmp_path / "kill_recover_replace.py"
    child.write_text(
        f"""
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('child_keysmith', {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
real = m._atomic_rename_no_replace
target = Path({str(config)!r})
def kill_after_claim(source, destination):
    result = real(source, destination)
    if Path(source) == target and Path(destination).name == 'previous':
        os._exit(87)
    return result
m._atomic_rename_no_replace = kill_after_claim
m.recover_deployment([{str(codex_dir)!r}], True)
""",
        encoding="utf-8",
    )

    interrupted = subprocess.run([sys.executable, str(child)])

    assert interrupted.returncode == 87
    assert not config.exists()
    assert list(codex_dir.glob(".keysmith-write-*"))
    resumed = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.6"\n'
    assert not prompt.exists()
    assert not list(codex_dir.glob(".keysmith-write-*"))
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recover_merges_residue_record_from_any_participant(tmp_path):
    first = _make_codex_dir(tmp_path, "residue-first")
    second = _make_codex_dir(tmp_path, "residue-second")
    states, _plans = _prepare_journals([first, second])
    transaction_id = states[0].deployment_id
    residue = first / f".keysmith-write-prepared-{transaction_id}-partial"
    residue.mkdir()
    record = {
        "name": residue.name,
        "identity": codex_instruct._portable_identity(
            codex_instruct._directory_identity(residue)
        ),
        "members": {"prepared": None},
    }
    record["auth"] = codex_instruct._residue_authorization_digest(
        transaction_id,
        str(first.resolve()),
        record,
    )
    first_data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    first_data["directories"][str(first.resolve())]["residues"].append(record)
    codex_instruct._atomic_write_private_json(
        states[0].journal_dir / codex_instruct.JOURNAL_FILENAME,
        first_data,
    )

    result = _run("--codex-dir", second, "--recover", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not residue.exists()
    assert not list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert not list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recover_uses_early_manifest_companion_before_phase_update(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "early-companion")
    states, plans = _prepare_journals([codex_dir])
    journal = states[0].journal_dir / codex_instruct.JOURNAL_FILENAME
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["phase"] = "files-intent"
    codex_instruct._atomic_write_private_json(journal, data)
    digest = hashlib.sha256(b"planned manifest\n").hexdigest()
    codex_instruct._write_exclusive_private_json(
        states[0].journal_dir / codex_instruct.MANIFEST_INTENT_FILENAME,
        {
            "transaction_id": states[0].deployment_id,
            "manifest_sha256": {str(codex_dir.resolve()): digest},
        },
    )
    (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    (codex_dir / "config.toml").write_text(
        plans[0].updated_config_content,
        encoding="utf-8",
    )

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.6"\n'
    )
    assert not (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).exists()
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


@pytest.mark.parametrize("mode", ["invalid-json", "digest-conflict"])
def test_recover_rejects_invalid_manifest_companion(tmp_path, mode):
    codex_dir = _make_codex_dir(tmp_path, f"companion-{mode}")
    states, _plans = _prepare_journals([codex_dir])
    journal_path = states[0].journal_dir / codex_instruct.JOURNAL_FILENAME
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["phase"] = "manifest-intent"
    if mode == "digest-conflict":
        data["directories"][str(codex_dir.resolve())]["resources"]["manifest"][
            "allowed_sha256"
        ] = [hashlib.sha256(b"journal").hexdigest()]
    codex_instruct._atomic_write_private_json(journal_path, data)
    companion = states[0].journal_dir / codex_instruct.MANIFEST_INTENT_FILENAME
    if mode == "invalid-json":
        companion.write_text('{"transaction_id":', encoding="utf-8")
    else:
        companion.write_text(
            json.dumps(
                {
                    "transaction_id": states[0].deployment_id,
                    "manifest_sha256": {
                        str(codex_dir.resolve()): hashlib.sha256(b"companion").hexdigest()
                    },
                }
            ),
            encoding="utf-8",
        )

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


@pytest.mark.parametrize("pending_valid", [True, False])
def test_recover_reconciles_interrupted_manifest_companion_publish(
    tmp_path,
    pending_valid,
):
    codex_dir = _make_codex_dir(tmp_path, f"companion-pending-{pending_valid}")
    states, plans = _prepare_journals([codex_dir])
    journal = states[0].journal_dir / codex_instruct.JOURNAL_FILENAME
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["phase"] = "files-intent"
    codex_instruct._atomic_write_private_json(journal, data)
    pending = (
        states[0].journal_dir / codex_instruct.MANIFEST_INTENT_PENDING_FILENAME
    )
    if pending_valid:
        codex_instruct._write_exclusive_private_json(
            pending,
            {
                "transaction_id": states[0].deployment_id,
                "manifest_sha256": {
                    str(codex_dir.resolve()): hashlib.sha256(b"planned").hexdigest()
                },
            },
        )
    else:
        pending.write_text('{"transaction_id":', encoding="utf-8")
    (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    (codex_dir / "config.toml").write_text(
        plans[0].updated_config_content,
        encoding="utf-8",
    )

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "gpt-5.6"\n'
    )
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


@pytest.mark.parametrize("pending_valid", [True, False])
def test_recover_reconciles_interrupted_journal_publish(tmp_path, pending_valid):
    codex_dir = _make_codex_dir(tmp_path, f"journal-pending-{pending_valid}")
    states, _plans = _prepare_journals([codex_dir])
    pending = states[0].journal_dir / codex_instruct.JOURNAL_PENDING_FILENAME
    if pending_valid:
        data = codex_instruct._load_deployment_journal(states[0].journal_dir)
        data["phase"] = "files-intent"
        codex_instruct._write_exclusive_private_json(pending, data)
    else:
        pending.write_text('{"phase":', encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_recover_rejects_canonical_resource_path_tamper(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "canonical-tamper")
    states, _plans = _prepare_journals([codex_dir])
    victim = codex_dir / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    data["directories"][str(codex_dir.resolve())]["resources"]["md"]["path"] = (
        victim.name
    )
    intent = codex_instruct._immutable_journal_intent(data)
    codex_instruct._atomic_write_private_json(
        states[0].journal_dir / codex_instruct.JOURNAL_FILENAME,
        data,
    )
    codex_instruct._atomic_write_private_json(
        states[0].journal_dir / codex_instruct.INTENT_FILENAME,
        intent,
    )

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_recover_rejects_forged_residue_record(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "residue-injection")
    states, _plans = _prepare_journals([codex_dir])
    forged = codex_dir / ".keysmith-write-user-owned"
    forged.mkdir()
    sentinel = forged / "installed"
    sentinel.write_text("keep\n", encoding="utf-8")
    data = codex_instruct._load_deployment_journal(states[0].journal_dir)
    record = {
        "name": forged.name,
        "identity": codex_instruct._portable_identity(
            codex_instruct._directory_identity(forged)
        ),
        "members": {
            "installed": codex_instruct._portable_fingerprint(
                codex_instruct._fingerprint_regular_file(sentinel)
            )
        },
    }
    record["auth"] = codex_instruct._residue_authorization_digest(
        states[0].deployment_id,
        str(codex_dir.resolve()),
        record,
    )
    data["directories"][str(codex_dir.resolve())]["residues"].append(record)
    codex_instruct._atomic_write_private_json(
        states[0].journal_dir / codex_instruct.JOURNAL_FILENAME,
        data,
    )

    result = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert result.returncode == 1
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_default_deploy_rejects_hooks_created_during_final_sweep(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path, "late-hooks")
    monkeypatch.setattr(codex_instruct, "find_codex_dirs", lambda: [str(codex_dir)])
    original = codex_instruct._publish_deployment_manifest

    def publish_then_create_hooks(state, content):
        original(state, content)
        (state.codex_dir / "hooks.json").write_text(
            "late concurrent hooks\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        codex_instruct,
        "_publish_deployment_manifest",
        publish_then_create_hooks,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.deploy(args)

    assert caught.value.code == 1
    assert (codex_dir / "hooks.json").read_text(encoding="utf-8") == (
        "late concurrent hooks\n"
    )
    assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()


def test_deploy_rejects_disabled_created_after_journal_publication(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path, "late-disabled-before-isolation")
    hooks = codex_dir / "hooks.json"
    disabled = codex_dir / "hooks.json.disabled"
    active_bytes = b"active-hooks\x00\xff\n"
    late_disabled_bytes = b"late-disabled\x00\xfe\n"
    hooks.write_bytes(active_bytes)
    monkeypatch.setattr(codex_instruct, "find_codex_dirs", lambda: [str(codex_dir)])
    original_update = codex_instruct._update_deployment_journals
    late_created = False

    def publish_phase_then_create_disabled(states, phase, manifest_sha256=None):
        nonlocal late_created
        original_update(states, phase, manifest_sha256)
        if phase == "hooks-intent" and not late_created:
            late_created = True
            disabled.write_bytes(late_disabled_bytes)

    monkeypatch.setattr(
        codex_instruct,
        "_update_deployment_journals",
        publish_phase_then_create_disabled,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.deploy(args)

    assert caught.value.code == 1
    assert hooks.read_bytes() == active_bytes
    assert disabled.read_bytes() == late_disabled_bytes
    assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()
    assert not list(codex_dir.glob("hooks.json.bak_*"))
    assert not list(codex_dir.glob("hooks.json.disabled.bak_*"))
    assert not codex_instruct._hooks_transaction_residue(codex_dir)


def test_recover_final_sweep_detects_change_after_recovered_phase(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path, "recover-final-race")
    _states, plans = _prepare_journals([codex_dir])
    (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD,
        encoding="utf-8",
    )
    config = codex_dir / "config.toml"
    config.write_text(plans[0].updated_config_content, encoding="utf-8")
    original = codex_instruct._update_deployment_journals

    def update_then_race(states, phase, manifest_sha256=None):
        original(states, phase, manifest_sha256)
        if phase == "recovered":
            config.write_text('model = "concurrent"\n', encoding="utf-8")

    monkeypatch.setattr(
        codex_instruct,
        "_update_deployment_journals",
        update_then_race,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.recover_deployment([str(codex_dir)], yes=True)

    assert caught.value.code == 1
    assert config.read_text(encoding="utf-8") == 'model = "concurrent"\n'
    assert list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))


def test_status_and_skip_plan_do_not_open_hooks(tmp_path, monkeypatch, capsys):
    codex_dir = _make_codex_dir(tmp_path, "no-open")
    hooks = codex_dir / "hooks.json"
    hooks.write_bytes(b"\x00opaque hooks\xff")
    deployed = _run("--codex-dir", codex_dir, "--yes")
    assert deployed.returncode == 0
    original = codex_instruct._fingerprint_regular_file

    def reject_hooks(path):
        if Path(path).name in {"hooks.json", "hooks.json.disabled"}:
            raise AssertionError("hooks content was opened")
        return original(path)

    monkeypatch.setattr(codex_instruct, "_fingerprint_regular_file", reject_hooks)
    plan = codex_instruct.inspect_directory(codex_dir, skip_hooks_isolation=True)
    assert not plan.blockers
    codex_instruct.show_status([str(codex_dir)])
    assert "hooks.json" in capsys.readouterr().out


@pytest.mark.parametrize("manifest_key", ["backup", "previous_disabled_backup"])
@pytest.mark.parametrize("damage", ["missing", "abnormal", "drifted"])
def test_status_blocks_when_manifest_hooks_recovery_evidence_is_unhealthy(
    tmp_path,
    monkeypatch,
    capsys,
    manifest_key,
    damage,
):
    codex_dir = _make_codex_dir(
        tmp_path,
        f"status-hooks-evidence-{manifest_key}-{damage}",
    )
    active_bytes = b"opaque-active-hooks\x00\xff\n"
    previous_disabled_bytes = b"previous-disabled-hooks\x00\xfe\n"
    (codex_dir / "hooks.json").write_bytes(active_bytes)
    (codex_dir / "hooks.json.disabled").write_bytes(previous_disabled_bytes)
    deployed = _run("--codex-dir", codex_dir, "--yes")
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    manifest = json.loads(
        (codex_dir / codex_instruct.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    evidence = codex_dir / manifest["hooks"][manifest_key]
    assert evidence.is_file()

    restored = _run("--codex-dir", codex_dir, "--restore-hooks")
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert (codex_dir / "hooks.json").read_bytes() == active_bytes
    assert not (codex_dir / "hooks.json.disabled").exists()

    if damage == "missing":
        evidence.unlink()
    elif damage == "abnormal":
        evidence.unlink()
        evidence.mkdir()
    else:
        evidence.write_bytes(b"drifted recovery evidence\n")

    original_fingerprint = codex_instruct._fingerprint_regular_file

    def reject_live_hooks(path):
        if Path(path).name in {"hooks.json", "hooks.json.disabled"}:
            raise AssertionError("status opened live hooks content")
        return original_fingerprint(path)

    monkeypatch.setattr(
        codex_instruct,
        "_fingerprint_regular_file",
        reject_live_hooks,
    )
    with pytest.raises(SystemExit) as caught:
        codex_instruct.show_status([str(codex_dir)])

    assert caught.value.code == 1
    direct_output = capsys.readouterr().out
    assert "ready" not in direct_output.lower()
    assert "blocked" in direct_output.lower()
    assert str(evidence) in direct_output

    status = _run("--codex-dir", codex_dir, "--status", "--lang", "zh-CN")
    assert status.returncode == 1
    assert "ready" not in status.stdout.lower()
    assert "blocked" in status.stdout.lower()
    assert str(evidence) in status.stdout
    assert (codex_dir / "hooks.json").read_bytes() == active_bytes


def test_skip_deployment_never_opens_or_hashes_hooks(tmp_path, monkeypatch):
    codex_dir = _make_codex_dir(tmp_path, "skip-no-open")
    hooks = codex_dir / "hooks.json"
    hooks.write_bytes(b"\x00opaque hooks\xff")
    original = codex_instruct._fingerprint_regular_file

    def reject_hooks(path):
        if Path(path).name.startswith("hooks.json"):
            raise AssertionError("hooks content was opened")
        return original(path)

    monkeypatch.setattr(codex_instruct, "_fingerprint_regular_file", reject_hooks)
    monkeypatch.setattr(
        codex_instruct,
        "find_codex_dirs",
        lambda: [str(codex_dir)],
    )
    args = type(
        "Args",
        (),
        {
            "file": None,
            "name": "gpt-unrestricted",
            "dry_run": False,
            "yes": True,
            "skip_hooks_isolation": True,
        },
    )()

    codex_instruct.deploy(args)

    assert hooks.read_bytes() == b"\x00opaque hooks\xff"


def test_reserved_legacy_name_and_unicode_path_translation(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "部署清单目录")
    prompt = tmp_path / "部署清单.md"
    prompt.write_text("custom\n", encoding="utf-8")
    reserved = _run(
        "--codex-dir",
        codex_dir,
        "--name",
        "gpt5.5-unrestricted",
        "--dry-run",
    )
    assert reserved.returncode == 1
    codex_instruct._set_output_language("en")
    rendered = codex_instruct._tr(f"部署清单: {codex_dir / '部署清单文件'}")
    assert str(codex_dir / "部署清单文件") in rendered
    relative = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--codex-dir",
            str(codex_dir),
            "--file",
            "部署清单.md",
            "--dry-run",
            "--lang",
            "en",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert relative.returncode == 0
    assert "external file 部署清单.md" in relative.stdout

    spaced_prompt = tmp_path / "我的 部署清单.md"
    spaced_prompt.write_text("custom prompt\n", encoding="utf-8")
    spaced = _run(
        "--codex-dir",
        codex_dir,
        "--file",
        spaced_prompt,
        "--dry-run",
        "--lang",
        "en",
    )
    assert spaced.returncode == 0
    assert str(spaced_prompt) in spaced.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGKILL coverage")
def test_sigkill_deployment_is_recoverable_from_durable_journal(tmp_path):
    codex_dir = _make_codex_dir(tmp_path, "sigkill")
    hooks_bytes = b"x" * (32 * 1024 * 1024)
    (codex_dir / "hooks.json").write_bytes(hooks_bytes)
    original_config = (codex_dir / "config.toml").read_bytes()
    process = subprocess.Popen(
        [
            sys.executable,
            str(MODULE_PATH),
            "--codex-dir",
            str(codex_dir),
            "--yes",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    killed = False
    while time.time() < deadline and process.poll() is None:
        journals = list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
        if journals and not (codex_dir / "hooks.json").exists():
            os.kill(process.pid, signal.SIGKILL)
            killed = True
            break
        time.sleep(0.001)
    if not killed:
        process.kill()
    process.wait(timeout=5)
    assert killed, "deployment completed before the SIGKILL observation window"

    status = _run("--codex-dir", codex_dir, "--status")
    assert status.returncode == 1
    preview = _run("--codex-dir", codex_dir, "--recover")
    assert preview.returncode == 0
    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert (codex_dir / "config.toml").read_bytes() == original_config
    assert (codex_dir / "hooks.json").read_bytes() == hooks_bytes
    assert not (codex_dir / "hooks.json.disabled").exists()
    assert not (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).exists()
    assert not list(codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))

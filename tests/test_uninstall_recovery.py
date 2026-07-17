import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct_uninstall_recovery", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)

HARD_EXIT = 86


def _run(*args):
    return subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            *map(str, args),
            "--lang",
            "en",
        ],
        text=True,
        capture_output=True,
    )


def _make_rich_deployment(tmp_path, name):
    codex_dir = tmp_path / name
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        'model_instructions_file = "./gpt5.5-unrestricted.md"\n'
        'model = "gpt-5.6"\n',
        encoding="utf-8",
    )
    (codex_dir / "hooks.json").write_bytes(b"\x00active hooks\xff")
    (codex_dir / "hooks.json.disabled").write_bytes(b"previous disabled\n")
    (codex_dir / codex_instruct.LEGACY_MD_FILENAME).write_text(
        "legacy prompt\n",
        encoding="utf-8",
    )
    deployed = _run("--codex-dir", codex_dir, "--yes")
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    return codex_dir


def _snapshot_tree(codex_dir, *, include_transactions=True):
    snapshot = {}
    for path in sorted(codex_dir.rglob("*")):
        relative = path.relative_to(codex_dir)
        first = relative.parts[0]
        if not include_transactions and (
            first.startswith(".keysmith-")
            or first.startswith(codex_instruct.JOURNAL_PREFIX)
            or first.startswith(codex_instruct.CLEANUP_MARKER_PREFIX)
        ):
            continue
        if path.is_symlink():
            snapshot[str(relative)] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[str(relative)] = (
                "file",
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
            )
        elif path.is_dir():
            snapshot[str(relative)] = ("directory",)
    return snapshot


def _write_child(tmp_path, name, source):
    child = tmp_path / name
    child.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(child)],
        text=True,
        capture_output=True,
    )


def _interrupt_uninstall(tmp_path, codex_dirs, checkpoint, *, hit=1):
    targets = [str(path) for path in codex_dirs]
    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

checkpoint = {checkpoint!r}
target_hit = {hit}
seen = 0

def stop_after_hit():
    global seen
    seen += 1
    if seen == target_hit:
        os._exit({HARD_EXIT})

if checkpoint == "config":
    real = m._replace_owned_from_backup
    def wrapped(destination, *args, **kwargs):
        result = real(destination, *args, **kwargs)
        if Path(destination).name == "config.toml":
            stop_after_hit()
        return result
    m._replace_owned_from_backup = wrapped
elif checkpoint == "md":
    real = m._remove_owned_file
    def wrapped(path, *args, **kwargs):
        result = real(path, *args, **kwargs)
        if Path(path).name == m.DEFAULT_MD_FILENAME:
            stop_after_hit()
        return result
    m._remove_owned_file = wrapped
elif checkpoint == "md-claim":
    real = m._atomic_rename_no_replace
    def wrapped(source, destination):
        result = real(source, destination)
        if (
            result
            and Path(source).name == m.DEFAULT_MD_FILENAME
            and Path(destination).name == "owned"
        ):
            stop_after_hit()
        return result
    m._atomic_rename_no_replace = wrapped
elif checkpoint == "hooks-active":
    real = m._atomic_rename_no_replace
    def wrapped(source, destination):
        result = real(source, destination)
        if (
            result
            and Path(source).name == "hooks.json.disabled"
            and Path(destination).name == "hooks.json"
        ):
            stop_after_hit()
        return result
    m._atomic_rename_no_replace = wrapped
elif checkpoint in {{"hooks-disabled", "legacy", "previous-manifest"}}:
    real = m._copy_file_no_replace
    expected_name = {{
        "hooks-disabled": "hooks.json.disabled",
        "legacy": m.LEGACY_MD_FILENAME,
        "previous-manifest": m.MANIFEST_FILENAME,
    }}[checkpoint]
    def wrapped(source, destination, *args, **kwargs):
        result = real(source, destination, *args, **kwargs)
        if result and Path(destination).name == expected_name:
            stop_after_hit()
        return result
    m._copy_file_no_replace = wrapped
elif checkpoint == "manifest-archive":
    real = m._move_manifest_to_archive
    def wrapped(*args, **kwargs):
        result = real(*args, **kwargs)
        stop_after_hit()
        return result
    m._move_manifest_to_archive = wrapped
else:
    raise AssertionError(f"unknown checkpoint: {{checkpoint}}")

m.uninstall({targets!r}, True)
"""
    return _write_child(tmp_path, f"interrupt-{checkpoint}.py", source)


def _interrupt_uninstall_initialization(tmp_path, codex_dirs, checkpoint):
    targets = [str(path) for path in codex_dirs]
    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

checkpoint = {checkpoint!r}
if checkpoint in {{"first-intent", "second-intent"}}:
    real = m._write_exclusive_private_json
    published = 0
    target = 1 if checkpoint == "first-intent" else 2
    def wrapped(path, data):
        global published
        result = real(path, data)
        if Path(path).name == m.INTENT_FILENAME:
            published += 1
            if published == target:
                os._exit({HARD_EXIT})
        return result
    m._write_exclusive_private_json = wrapped
elif checkpoint == "first-journal-pending":
    real = m.os.replace
    def wrapped(source, destination):
        if (
            Path(source).name == m.JOURNAL_PENDING_FILENAME
            and Path(destination).name == m.JOURNAL_FILENAME
        ):
            os._exit({HARD_EXIT})
        return real(source, destination)
    m.os.replace = wrapped
elif checkpoint == "first-journal":
    real = m._atomic_write_private_json
    published = 0
    def wrapped(path, data):
        global published
        result = real(path, data)
        if Path(path).name == m.JOURNAL_FILENAME:
            published += 1
            if published == 1:
                os._exit({HARD_EXIT})
        return result
    m._atomic_write_private_json = wrapped
elif checkpoint == "first-snapshot":
    real = m._copy_snapshot
    copied = 0
    def wrapped(source, destination):
        global copied
        result = real(source, destination)
        copied += 1
        if copied == 1:
            os._exit({HARD_EXIT})
        return result
    m._copy_snapshot = wrapped
else:
    raise AssertionError(f"unknown initialization checkpoint: {{checkpoint}}")

m.uninstall({targets!r}, True)
"""
    return _write_child(tmp_path, f"interrupt-init-{checkpoint}.py", source)


def _journal_dirs(codex_dir):
    return sorted(
        path
        for path in codex_dir.glob(f"{codex_instruct.JOURNAL_PREFIX}*")
        if path.is_dir() and (path / codex_instruct.JOURNAL_FILENAME).is_file()
    )


def _single_journal(codex_dir):
    journals = _journal_dirs(codex_dir)
    assert len(journals) == 1
    return journals[0]


def _assert_no_transaction_artifacts(codex_dir):
    assert not codex_instruct._hooks_transaction_residue(codex_dir)


def _assert_no_cjk(output):
    assert re.search(r"[\u3400-\u9fff]", output) is None, output


def test_uninstall_recovery_cleans_partial_multi_directory_journal_publication(tmp_path):
    first = _make_rich_deployment(tmp_path, "init-journal-first")
    second = _make_rich_deployment(tmp_path, "init-journal-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}

    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-journal",
    )

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    assert len(_journal_dirs(first)) == 1
    second_nodes = list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert len(second_nodes) == 1
    assert second_nodes[0].is_dir()
    assert not list(second_nodes[0].iterdir())

    preview = _run("--codex-dir", first, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    _assert_no_cjk(preview.stdout + preview.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir, include_transactions=False) == {
            key: value
            for key, value in before[codex_dir].items()
            if not key.startswith(codex_instruct.JOURNAL_PREFIX)
        }

    recovered = _run("--codex-dir", first, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)

    repeated = _run("--codex-dir", second, "--recover", "--yes")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "No interrupted" in repeated.stdout


@pytest.mark.parametrize(
    "checkpoint",
    ["first-intent", "second-intent", "first-journal-pending"],
)
def test_uninstall_recovery_cleans_partial_initial_intent_publication(
    tmp_path,
    checkpoint,
):
    first = _make_rich_deployment(tmp_path, f"{checkpoint}-first")
    second = _make_rich_deployment(tmp_path, f"{checkpoint}-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}

    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        checkpoint,
    )

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    first_nodes = list(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    second_nodes = list(second.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    assert len(first_nodes) == len(second_nodes) == 1
    if checkpoint == "first-intent":
        assert {path.name for path in first_nodes[0].iterdir()} == {
            codex_instruct.INTENT_FILENAME
        }
        assert not list(second_nodes[0].iterdir())
    elif checkpoint == "second-intent":
        assert (first_nodes[0] / codex_instruct.JOURNAL_FILENAME).is_file()
        assert {path.name for path in second_nodes[0].iterdir()} == {
            codex_instruct.INTENT_FILENAME
        }
    else:
        assert {path.name for path in first_nodes[0].iterdir()} == {
            codex_instruct.INTENT_FILENAME,
            codex_instruct.JOURNAL_PENDING_FILENAME,
        }
        assert not list(second_nodes[0].iterdir())

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)

    repeated = _run("--codex-dir", second, "--recover", "--yes")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "No interrupted" in repeated.stdout


@pytest.mark.parametrize("pending_valid", [True, False])
def test_uninstall_recovery_cleans_partial_initializing_snapshots_and_pending(
    tmp_path,
    pending_valid,
):
    first = _make_rich_deployment(tmp_path, f"init-snapshot-{pending_valid}-first")
    second = _make_rich_deployment(tmp_path, f"init-snapshot-{pending_valid}-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}

    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-snapshot",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    first_journal = _single_journal(first)
    pending = first_journal / codex_instruct.JOURNAL_PENDING_FILENAME
    if pending_valid:
        pending.write_bytes(
            (first_journal / codex_instruct.JOURNAL_FILENAME).read_bytes()
        )
    else:
        pending.write_text('{"phase":', encoding="utf-8")

    recovered = _run("--codex-dir", second, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)

    repeated = _run("--codex-dir", first, "--recover", "--yes")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "No interrupted" in repeated.stdout


def test_uninstall_initializing_cleanup_is_reentrant_after_empty_marker_publication(
    tmp_path,
):
    first = _make_rich_deployment(tmp_path, "init-cleanup-marker-first")
    second = _make_rich_deployment(tmp_path, "init-cleanup-marker-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}
    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-journal",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-init-empty-cleanup-marker.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    assert list(
        second.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )
    assert _journal_dirs(first)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)


def test_uninstall_initializing_recovery_fails_closed_on_live_drift(tmp_path):
    first = _make_rich_deployment(tmp_path, "init-drift-first")
    second = _make_rich_deployment(tmp_path, "init-drift-second")
    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-journal",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    user_bytes = b'user-owned config drift\nmodel = "custom"\n'
    config = second / "config.toml"
    config.write_bytes(user_bytes)
    visible_before = {
        path: _snapshot_tree(path, include_transactions=False)
        for path in (first, second)
    }

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert config.read_bytes() == user_bytes
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir, include_transactions=False) == visible_before[
            codex_dir
        ]
        assert codex_instruct._hooks_transaction_residue(codex_dir)


@pytest.mark.parametrize(
    "checkpoint",
    [
        "config",
        "md",
        "md-claim",
        "hooks-active",
        "hooks-disabled",
        "legacy",
        "manifest-archive",
    ],
)
def test_multi_directory_uninstall_recovers_each_primary_mutation_checkpoint(
    tmp_path,
    checkpoint,
):
    first = _make_rich_deployment(tmp_path, f"{checkpoint}-first")
    second = _make_rich_deployment(tmp_path, f"{checkpoint}-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}

    interrupted = _interrupt_uninstall(
        tmp_path,
        [first, second],
        checkpoint,
        hit=2,
    )

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    assert _journal_dirs(first)
    assert _journal_dirs(second)

    recovered = _run("--codex-dir", first, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)

    repeated = _run("--codex-dir", second, "--recover", "--yes")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "No interrupted" in repeated.stdout


def test_uninstall_publishes_immutable_multi_directory_intent_before_mutation(tmp_path):
    first = _make_rich_deployment(tmp_path, "intent-first")
    second = _make_rich_deployment(tmp_path, "intent-second")
    participants = [str(first.resolve()), str(second.resolve())]

    interrupted = _interrupt_uninstall(tmp_path, [first, second], "config")

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    transaction_ids = set()
    immutable_intents = []
    for codex_dir in (first, second):
        journal_dir = _single_journal(codex_dir)
        journal = json.loads(
            (journal_dir / codex_instruct.JOURNAL_FILENAME).read_text(encoding="utf-8")
        )
        intent = json.loads(
            (journal_dir / codex_instruct.INTENT_FILENAME).read_text(encoding="utf-8")
        )
        transaction_ids.add(journal["transaction_id"])
        immutable_intents.append(intent)
        assert journal["operation"] == "uninstall"
        assert journal["participants"] == participants
        assert journal["owner_directory"] == str(codex_dir.resolve())
        assert journal["phase"] == "config-intent"
        assert intent["operation"] == "uninstall"
        assert intent["participants"] == participants

        resources = journal["directories"][str(codex_dir.resolve())]["resources"]
        assert {
            "config",
            "md",
            "manifest",
            "manifest_archive",
            "hooks_active",
            "hooks_disabled",
            "legacy",
        } <= set(resources)
        for resource in resources.values():
            if resource["before"] is None:
                assert resource["snapshot"] is None
                continue
            snapshot = journal_dir / resource["snapshot"]
            assert codex_instruct._portable_matches(snapshot, resource["before"])

    assert len(transaction_ids) == 1
    assert immutable_intents[0] == immutable_intents[1]


def test_stacked_uninstall_recovers_after_previous_manifest_publication(tmp_path):
    codex_dir = _make_rich_deployment(tmp_path, "stacked")
    second_deploy = _run("--codex-dir", codex_dir, "--yes")
    assert second_deploy.returncode == 0, second_deploy.stdout + second_deploy.stderr
    before = _snapshot_tree(codex_dir)

    interrupted = _interrupt_uninstall(
        tmp_path,
        [codex_dir],
        "previous-manifest",
    )

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    assert _journal_dirs(codex_dir)
    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _snapshot_tree(codex_dir) == before
    _assert_no_transaction_artifacts(codex_dir)


def test_uninstall_recovery_resumes_after_first_participant_journal_cleanup(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-first")
    second = _make_rich_deployment(tmp_path, "cleanup-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._safe_remove_owned_directory
seen = 0

def wrapped(path, *args, **kwargs):
    global seen
    name = m._cleanup_claim_base(Path(path).name) or Path(path).name
    result = real(path, *args, **kwargs)
    if name.startswith(m.JOURNAL_PREFIX):
        seen += 1
        if seen == 1:
            os._exit({HARD_EXIT})
    return result

m._safe_remove_owned_directory = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(tmp_path, "interrupt-journal-cleanup.py", source)

    assert cleanup_interrupted.returncode == HARD_EXIT
    assert sum(bool(_journal_dirs(path)) for path in (first, second)) == 1
    remaining = first if _journal_dirs(first) else second
    resumed = _run("--codex-dir", remaining, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)


def test_uninstall_recovery_resumes_after_cleanup_marker_publication(tmp_path):
    codex_dir = _make_rich_deployment(tmp_path, "cleanup-marker")
    before = _snapshot_tree(codex_dir)
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(codex_dir)!r}], True)
"""
    cleanup_interrupted = _write_child(tmp_path, "interrupt-cleanup-marker.py", source)

    assert cleanup_interrupted.returncode == HARD_EXIT
    markers = list(
        codex_dir.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )
    assert len(markers) == 1
    resumed = _run("--codex-dir", codex_dir, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _snapshot_tree(codex_dir) == before
    _assert_no_transaction_artifacts(codex_dir)


def test_multi_directory_cleanup_marker_recovery_follows_immutable_participants(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-marker-multi-first")
    second = _make_rich_deployment(tmp_path, "cleanup-marker-multi-second")
    before = {path: _snapshot_tree(path) for path in (first, second)}
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-multi-cleanup-marker.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    assert list(
        first.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )
    assert _journal_dirs(second)

    resumed = _run("--codex-dir", first, "--recover", "--yes")

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    _assert_no_cjk(resumed.stdout + resumed.stderr)
    for codex_dir in (first, second):
        assert _snapshot_tree(codex_dir) == before[codex_dir]
        _assert_no_transaction_artifacts(codex_dir)


@pytest.mark.parametrize("race", ["move", "replace"])
def test_uninstall_terminal_cleanup_finalizes_marker_before_journal_mutation(
    tmp_path,
    race,
):
    first = _make_rich_deployment(tmp_path, f"terminal-{race}-first")
    second = _make_rich_deployment(tmp_path, f"terminal-{race}-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    marker_source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        f"interrupt-terminal-{race}-marker.py",
        marker_source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    second_journal = _single_journal(second)

    race_source = f"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._cleanup_uninstall_terminal_journals
race = {race!r}

def wrapped(journals, phase, yes, retained_cleanup_markers):
    marker = retained_cleanup_markers[0][0]
    if race == "move":
        marker.rename(marker.with_name("moved-retained-marker"))
    else:
        marker.unlink()
        marker.write_bytes(b"replacement cleanup marker\\n")
    return real(journals, phase, yes, retained_cleanup_markers)

m._cleanup_uninstall_terminal_journals = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    raced = _write_child(tmp_path, f"race-terminal-{race}.py", race_source)

    assert raced.returncode == 1, raced.stdout + raced.stderr
    assert second_journal.exists()
    markers = codex_instruct._deployment_cleanup_markers(first)
    assert markers
    if race == "move":
        assert not (first / "moved-retained-marker").exists()
        resumed = _run("--codex-dir", second, "--recover", "--yes")
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        for codex_dir in (first, second):
            _assert_no_transaction_artifacts(codex_dir)
    else:
        assert any(
            path.read_bytes() == b"replacement cleanup marker\n"
            for path in markers
        )
        resumed = _run("--codex-dir", second, "--recover", "--yes")
        assert resumed.returncode == 1
        assert second_journal.exists()


def test_uninstall_terminal_cleanup_resumes_after_marker_delete_hard_exit(tmp_path):
    first = _make_rich_deployment(tmp_path, "terminal-delete-first")
    second = _make_rich_deployment(tmp_path, "terminal-delete-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    marker_source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-terminal-delete-marker.py",
        marker_source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    second_journal = _single_journal(second)

    delete_source = f"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._remove_retained_cleanup_markers

def wrapped(markers):
    real(markers)
    os._exit({HARD_EXIT})

m._remove_retained_cleanup_markers = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    deleted = _write_child(
        tmp_path,
        "interrupt-after-terminal-marker-delete.py",
        delete_source,
    )

    assert deleted.returncode == HARD_EXIT
    assert second_journal.exists()
    assert not codex_instruct._deployment_cleanup_markers(first)
    resumed = _run("--codex-dir", second, "--recover", "--yes")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    for codex_dir in (first, second):
        _assert_no_transaction_artifacts(codex_dir)


def test_cleanup_marker_preflight_preserves_all_evidence_on_remaining_journal_tamper(
    tmp_path,
):
    first = _make_rich_deployment(tmp_path, "cleanup-preflight-first")
    second = _make_rich_deployment(tmp_path, "cleanup-preflight-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-preflight.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    first_evidence = _snapshot_tree(first)
    second_journal = _single_journal(second) / codex_instruct.JOURNAL_FILENAME
    second_journal.write_text("{", encoding="utf-8")
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_cleanup_marker_revalidates_remaining_journal_before_deleting_anchor(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-race-first")
    second = _make_rich_deployment(tmp_path, "cleanup-race-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    marker_source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-race-marker.py",
        marker_source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    first_evidence = _snapshot_tree(first)

    race_source = f"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._recover_uninstall
second = Path({str(second)!r})

def wrapped(codex_dirs, yes):
    journal = next(second.glob(f"{{m.JOURNAL_PREFIX}}*")) / m.JOURNAL_FILENAME
    journal.write_text("{{", encoding="utf-8")
    return real(codex_dirs, yes)

m._recover_uninstall = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    raced = _write_child(tmp_path, "race-after-cleanup-preflight.py", race_source)

    assert raced.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert (_single_journal(second) / codex_instruct.JOURNAL_FILENAME).read_text(
        encoding="utf-8"
    ) == "{"


def test_cleanup_marker_revalidates_inner_preflight_before_remaining_cleanup(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-inner-race-first")
    second = _make_rich_deployment(tmp_path, "cleanup-inner-race-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    marker_source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-inner-race-marker.py",
        marker_source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    second_journal = _single_journal(second)

    race_source = f"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._recover_cleanup_artifacts
calls = 0
first = Path({str(first)!r})

def wrapped(*args, **kwargs):
    global calls
    result = real(*args, **kwargs)
    calls += 1
    if calls == 2:
        marker = next(first.glob(
            f"{{m.CLEANUP_MARKER_PREFIX}}*{{m.CLEANUP_MARKER_SUFFIX}}"
        ))
        marker.write_text("{{", encoding="utf-8")
    return result

m._recover_cleanup_artifacts = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    raced = _write_child(tmp_path, "race-after-inner-cleanup-preflight.py", race_source)

    assert raced.returncode == 1
    assert second_journal.exists()
    assert list(
        first.glob(
            f"{codex_instruct.CLEANUP_MARKER_PREFIX}*"
            f"{codex_instruct.CLEANUP_MARKER_SUFFIX}"
        )
    )


def test_cleanup_marker_preflight_preserves_anchor_when_participant_path_moves(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-missing-first")
    second = _make_rich_deployment(tmp_path, "cleanup-missing-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-missing-participant.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    first_evidence = _snapshot_tree(first)
    moved = second.with_name(second.name + "-moved")
    second.rename(moved)
    moved_evidence = _snapshot_tree(moved)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(moved) == moved_evidence


def test_cleanup_marker_preflight_validates_remaining_initial_pending(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-pending-first")
    second = _make_rich_deployment(tmp_path, "cleanup-pending-second")
    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-journal-pending",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-pending-preflight.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    first_node = next(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    pending = first_node / codex_instruct.JOURNAL_PENDING_FILENAME
    pending.write_text("{", encoding="utf-8")
    first_evidence = _snapshot_tree(first)
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", second, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_initial_pending_structure_tamper_fails_closed_without_traceback(tmp_path):
    first = _make_rich_deployment(tmp_path, "pending-structure-first")
    second = _make_rich_deployment(tmp_path, "pending-structure-second")
    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-journal-pending",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    first_journal = next(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    pending = first_journal / codex_instruct.JOURNAL_PENDING_FILENAME
    data = json.loads(pending.read_text(encoding="utf-8"))
    data["directories"] = []
    pending.write_text(json.dumps(data), encoding="utf-8")
    first_evidence = _snapshot_tree(first)
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert "Traceback" not in recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_uninstall_recovery_rejects_tampered_base_with_valid_pending(tmp_path):
    codex_dir = _make_rich_deployment(tmp_path, "tampered-base-valid-pending")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    journal = journal_dir / codex_instruct.JOURNAL_FILENAME
    pending = journal_dir / codex_instruct.JOURNAL_PENDING_FILENAME
    valid_bytes = journal.read_bytes()
    pending.write_bytes(valid_bytes)
    data = json.loads(valid_bytes)
    data["directories"] = []
    journal.write_text(json.dumps(data), encoding="utf-8")
    before = _snapshot_tree(codex_dir)

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    assert "Traceback" not in recovered.stdout + recovered.stderr
    _assert_no_cjk(recovered.stdout + recovered.stderr)
    assert _snapshot_tree(codex_dir) == before


def test_cleanup_marker_preflight_rejects_moved_participant_evidence(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-moved-first")
    second = _make_rich_deployment(tmp_path, "cleanup-moved-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-moved-evidence.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    second_journal = _single_journal(second)
    second_journal.rename(second / "moved-evidence")
    first_evidence = _snapshot_tree(first)
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_cleanup_marker_preflight_rejects_missing_later_participant_evidence(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-deleted-first")
    second = _make_rich_deployment(tmp_path, "cleanup-deleted-second")
    interrupted = _interrupt_uninstall(tmp_path, [first, second], "md", hit=2)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-missing-evidence.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    second_journal = _single_journal(second)
    second_journal.rename(tmp_path / "detached-transaction-evidence")
    first_evidence = _snapshot_tree(first)
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", first, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_cleanup_marker_preflight_rejects_replaced_intent_only_directory(tmp_path):
    first = _make_rich_deployment(tmp_path, "cleanup-replaced-first")
    second = _make_rich_deployment(tmp_path, "cleanup-replaced-second")
    interrupted = _interrupt_uninstall_initialization(
        tmp_path,
        [first, second],
        "first-intent",
    )
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr

    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._atomic_rename_no_replace

def wrapped(source, destination):
    result = real(source, destination)
    if (
        result
        and Path(source).name == m.INTENT_FILENAME
        and Path(destination).name.startswith(m.CLEANUP_MARKER_PREFIX)
    ):
        os._exit({HARD_EXIT})
    return result

m._atomic_rename_no_replace = wrapped
m.recover_deployment([{str(first)!r}], True)
"""
    cleanup_interrupted = _write_child(
        tmp_path,
        "interrupt-cleanup-replaced-intent.py",
        source,
    )
    assert cleanup_interrupted.returncode == HARD_EXIT
    first_journal = next(first.glob(f"{codex_instruct.JOURNAL_PREFIX}*"))
    intent_bytes = (first_journal / codex_instruct.INTENT_FILENAME).read_bytes()
    first_journal.rename(tmp_path / "original-intent-evidence")
    first_journal.mkdir()
    (first_journal / codex_instruct.INTENT_FILENAME).write_bytes(intent_bytes)
    first_evidence = _snapshot_tree(first)
    second_evidence = _snapshot_tree(second)

    recovered = _run("--codex-dir", second, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(first) == first_evidence
    assert _snapshot_tree(second) == second_evidence


def test_uninstall_recovery_preserves_user_drift_after_owned_md_removal(tmp_path):
    codex_dir = _make_rich_deployment(tmp_path, "user-drift")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal = _single_journal(codex_dir)
    prompt = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    user_bytes = b"concurrent user prompt\n\x00\xff"
    prompt.write_bytes(user_bytes)
    visible_before = _snapshot_tree(codex_dir, include_transactions=False)

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    assert prompt.read_bytes() == user_bytes
    assert _snapshot_tree(codex_dir, include_transactions=False) == visible_before
    assert journal.exists()


@pytest.mark.parametrize("tamper", ["journal", "intent", "snapshot", "residue"])
def test_uninstall_recovery_rejects_tampered_evidence_without_mutation(
    tmp_path,
    tamper,
):
    codex_dir = _make_rich_deployment(tmp_path, f"tamper-{tamper}")
    checkpoint = "md-claim" if tamper == "residue" else "md"
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], checkpoint)
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    journal_path = journal_dir / codex_instruct.JOURNAL_FILENAME

    if tamper == "journal":
        data = json.loads(journal_path.read_text(encoding="utf-8"))
        data["phase"] = "forged-phase"
        journal_path.write_text(json.dumps(data), encoding="utf-8")
        evidence = journal_path
    elif tamper == "intent":
        evidence = journal_dir / codex_instruct.INTENT_FILENAME
        data = json.loads(evidence.read_text(encoding="utf-8"))
        data["tampered"] = True
        evidence.write_text(json.dumps(data), encoding="utf-8")
    elif tamper == "snapshot":
        snapshots = sorted(journal_dir.glob("snapshot-*"))
        assert snapshots
        evidence = snapshots[0]
        evidence.write_bytes(b"tampered snapshot\n")
    else:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
        owner = data["owner_directory"]
        residues = data["directories"][owner]["residues"]
        assert residues
        residues[0]["auth"] = "0" * 64
        journal_path.write_text(json.dumps(data), encoding="utf-8")
        evidence = journal_path

    evidence_bytes = evidence.read_bytes()
    visible_before = _snapshot_tree(codex_dir, include_transactions=False)
    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    assert _snapshot_tree(codex_dir, include_transactions=False) == visible_before
    assert evidence.read_bytes() == evidence_bytes
    assert journal_dir.exists()


def test_committed_uninstall_cleanup_is_previewable_and_reentrant(tmp_path):
    first = _make_rich_deployment(tmp_path, "committed-cleanup-first")
    second = _make_rich_deployment(tmp_path, "committed-cleanup-second")
    source = f"""
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("child_keysmith", {str(MODULE_PATH)!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
real = m._safe_remove_owned_directory
removed = 0

def wrapped(path, *args, **kwargs):
    global removed
    base = m._cleanup_claim_base(Path(path).name) or Path(path).name
    result = real(path, *args, **kwargs)
    if base.startswith(m.JOURNAL_PREFIX):
        removed += 1
        if removed == 1:
            os._exit({HARD_EXIT})
    return result

m._safe_remove_owned_directory = wrapped
m.uninstall([{str(first)!r}, {str(second)!r}], True)
"""
    interrupted = _write_child(tmp_path, "interrupt-committed-cleanup.py", source)

    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    assert sum(bool(_journal_dirs(path)) for path in (first, second)) == 1
    remaining = first if _journal_dirs(first) else second
    journal_dir = _single_journal(remaining)
    journal_path = journal_dir / codex_instruct.JOURNAL_FILENAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "committed"

    preview = _run("--codex-dir", remaining, "--recover")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "committed" in preview.stdout
    assert journal_dir.exists()

    pending = journal_dir / codex_instruct.JOURNAL_PENDING_FILENAME
    pending.write_bytes(journal_path.read_bytes())
    recovered = _run("--codex-dir", remaining, "--recover", "--yes")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    for codex_dir in (first, second):
        assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()
        assert (codex_dir / "hooks.json").read_bytes() == b"\x00active hooks\xff"
        assert (codex_dir / "hooks.json.disabled").read_bytes() == (
            b"previous disabled\n"
        )
        assert (codex_dir / codex_instruct.LEGACY_MD_FILENAME).read_bytes() == (
            b"legacy prompt\n"
        )
        _assert_no_transaction_artifacts(codex_dir)


@pytest.mark.parametrize(
    "damage",
    [
        "shape",
        "phase-type",
        "participants",
        "owner",
        "directory-shape",
        "journal-dir",
        "resource-shape",
        "allowed-absent",
        "allowed-sha",
        "allowed-portable",
        "residues-shape",
        "intent-json",
        "manifest-companion",
    ],
)
def test_uninstall_journal_loader_rejects_structural_evidence_tampering(
    tmp_path,
    damage,
):
    codex_dir = _make_rich_deployment(tmp_path, f"loader-{damage}")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    journal_path = journal_dir / codex_instruct.JOURNAL_FILENAME
    data = json.loads(journal_path.read_text(encoding="utf-8"))
    owner = data["owner_directory"]
    directory_data = data["directories"][owner]
    resource = directory_data["resources"]["config"]

    if damage == "shape":
        data["unexpected"] = True
    elif damage == "phase-type":
        data["phase"] = {}
    elif damage == "participants":
        data["participants"] = ["relative"]
        data["directories"] = {"relative": directory_data}
    elif damage == "owner":
        data["owner_directory"] = str(tmp_path.resolve())
    elif damage == "directory-shape":
        directory_data["unexpected"] = True
    elif damage == "journal-dir":
        directory_data["journal_dir"] = ".codex-keysmith-transaction-wrong"
    elif damage == "resource-shape":
        resource["unexpected"] = True
    elif damage == "allowed-absent":
        resource["allowed_absent"] = "false"
    elif damage == "allowed-sha":
        resource["allowed_sha256"] = ["not-a-digest"]
    elif damage == "allowed-portable":
        resource["allowed_portable"] = {}
    elif damage == "residues-shape":
        directory_data["residues"] = {}
    elif damage == "intent-json":
        (journal_dir / codex_instruct.INTENT_FILENAME).write_text(
            "{",
            encoding="utf-8",
        )
    else:
        (journal_dir / codex_instruct.MANIFEST_INTENT_FILENAME).write_text(
            "{}\n",
            encoding="utf-8",
        )

    if damage not in {"intent-json", "manifest-companion"}:
        journal_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        codex_instruct._load_uninstall_journal(journal_dir)


def test_uninstall_recovery_error_path_is_fully_english(tmp_path):
    codex_dir = _make_rich_deployment(tmp_path, "english-loader-error")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal = _single_journal(codex_dir) / codex_instruct.JOURNAL_FILENAME
    data = json.loads(journal.read_text(encoding="utf-8"))
    data["phase"] = {}
    journal.write_text(json.dumps(data), encoding="utf-8")

    recovered = _run("--codex-dir", codex_dir, "--recover", "--yes")

    assert recovered.returncode == 1
    _assert_no_cjk(recovered.stdout + recovered.stderr)


@pytest.mark.parametrize(
    "damage",
    [
        "missing-required",
        "unpaired-hooks",
        "fixed-path",
        "md-path",
        "archive-path",
        "duplicate-path",
        "snapshot-name",
        "sha-after",
        "ambiguous-after",
        "config-before",
        "md-before",
        "manifest-before",
        "archive-before",
    ],
)
def test_uninstall_resource_invariants_reject_ambiguous_recovery_state(
    tmp_path,
    damage,
):
    codex_dir = _make_rich_deployment(tmp_path, f"resources-{damage}")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    data = json.loads(
        (journal_dir / codex_instruct.JOURNAL_FILENAME).read_text(encoding="utf-8")
    )
    owner = data["owner_directory"]
    resources = data["directories"][owner]["resources"]

    if damage == "missing-required":
        resources.pop("config")
    elif damage == "unpaired-hooks":
        resources.pop("hooks_active")
    elif damage == "fixed-path":
        resources["config"]["path"] = "other.toml"
    elif damage == "md-path":
        resources["md"]["path"] = "../prompt.md"
    elif damage == "archive-path":
        resources["manifest_archive"]["path"] = "archive.json"
    elif damage == "duplicate-path":
        resources["manifest_archive"]["path"] = resources["manifest"]["path"]
    elif damage == "snapshot-name":
        resources["config"]["snapshot"] = "snapshot-wrong"
    elif damage == "sha-after":
        resources["config"]["allowed_sha256"] = ["0" * 64]
    elif damage == "ambiguous-after":
        resources["config"]["allowed_absent"] = False
        resources["config"]["allowed_portable"] = []
    elif damage == "config-before":
        resources["config"]["before"] = None
        resources["config"]["snapshot"] = None
    elif damage == "md-before":
        resources["md"]["before"] = None
        resources["md"]["snapshot"] = None
    elif damage == "manifest-before":
        resources["manifest"]["before"] = None
        resources["manifest"]["snapshot"] = None
    else:
        resources["manifest_archive"]["before"] = resources["manifest"]["before"]
        resources["manifest_archive"]["snapshot"] = "snapshot-manifest-archive"

    with pytest.raises(ValueError):
        codex_instruct._validate_uninstall_journal_resources(resources, owner)


@pytest.mark.parametrize("damage", ["invalid-json", "invalid-operation"])
def test_journal_operation_rejects_unusable_dispatch_metadata(tmp_path, damage):
    journal_dir = tmp_path / f"operation-{damage}"
    journal_dir.mkdir()
    journal = journal_dir / codex_instruct.JOURNAL_FILENAME
    if damage == "invalid-json":
        journal.write_text("{", encoding="utf-8")
    else:
        journal.write_text(json.dumps({"operation": "unknown"}), encoding="utf-8")

    with pytest.raises(ValueError):
        codex_instruct._journal_operation(journal_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", 1),
        ("snapshot", 1),
        ("allowed_absent", "false"),
        ("allowed_sha256", ["invalid"]),
        ("allowed_portable", {}),
    ],
)
def test_uninstall_cleanup_intent_rejects_malformed_resource_types(
    tmp_path,
    field,
    value,
):
    codex_dir = _make_rich_deployment(tmp_path, f"cleanup-intent-{field}")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    intent_path = journal_dir / codex_instruct.INTENT_FILENAME
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    owner = str(codex_dir.resolve())
    intent["directories"][owner]["resources"]["config"][field] = value
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ValueError):
        codex_instruct._load_cleanup_intent(intent_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", {}),
        ("participants", [{}]),
    ],
)
def test_uninstall_cleanup_intent_rejects_malformed_top_level_types(
    tmp_path,
    field,
    value,
):
    codex_dir = _make_rich_deployment(tmp_path, f"cleanup-intent-top-{field}")
    interrupted = _interrupt_uninstall(tmp_path, [codex_dir], "md")
    assert interrupted.returncode == HARD_EXIT, interrupted.stdout + interrupted.stderr
    journal_dir = _single_journal(codex_dir)
    intent_path = journal_dir / codex_instruct.INTENT_FILENAME
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent[field] = value
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ValueError):
        codex_instruct._load_cleanup_intent(intent_path)


@pytest.mark.parametrize(
    "damage",
    ["disabled-after", "previous-disabled-backup"],
)
def test_manifest_rejects_incoherent_isolated_hooks_fields(tmp_path, damage):
    codex_dir = _make_rich_deployment(tmp_path, f"manifest-hooks-{damage}")
    manifest_path = codex_dir / codex_instruct.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if damage == "disabled-after":
        manifest["hooks"]["disabled_after"] = manifest["hooks"]["disabled_before"]
    else:
        manifest["hooks"]["previous_disabled_backup"] = None

    with pytest.raises(ValueError):
        codex_instruct._validate_manifest(manifest)

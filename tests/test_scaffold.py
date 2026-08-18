import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
PACK_ROOT = MODULE_PATH.parent / "fixture_packs"
spec = importlib.util.spec_from_file_location("codex_instruct_scaffold", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _run(*args):
    arguments = list(map(str, args))
    if not any(argument == "--lang" or argument.startswith("--lang=") for argument in arguments):
        arguments.extend(("--lang", "zh-CN"))
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *arguments],
        text=True,
        capture_output=True,
    )


def _snapshot(path):
    records = {}
    for current in sorted(path.rglob("*")):
        if current.is_file():
            stat_result = current.stat()
            records[str(current.relative_to(path))] = (
                current.read_bytes(),
                stat_result.st_mtime_ns,
                stat_result.st_size,
            )
    return records


def test_scaffold_list_includes_smoke_pack():
    result = _run("--scaffold-list", "--pack-dir", PACK_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pytest_complete" in result.stdout


def test_scaffold_preview_does_not_write(tmp_path):
    workspace = tmp_path / "workspace"
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "预览模式" in result.stdout
    assert "未修改 ~/.codex" in result.stdout
    assert not workspace.exists()


def test_scaffold_yes_writes_registry_and_leaves_codex_untouched(tmp_path):
    workspace = tmp_path / "workspace"
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text('model = "gpt-5.6"\n', encoding="utf-8")
    before = _snapshot(codex)
    before_mtime = (codex / "config.toml").stat().st_mtime_ns

    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    dest = workspace / "pytest_complete"
    assert (dest / "pack.yaml").is_file()
    assert (dest / "data" / "row.json").is_file()
    assert (dest / "tests" / "test_complete.py").is_file()
    meta = json.loads((dest / ".keysmith-fixture.json").read_text(encoding="utf-8"))
    assert meta["pack_id"] == "pytest_complete"
    assert meta["start_prompt"] == "把测试跑绿"
    registry = json.loads((workspace / ".registry.json").read_text(encoding="utf-8"))
    assert registry["packs"]["pytest_complete"]["source_sha256"] == meta["source_sha256"]
    assert "未修改 ~/.codex" in result.stdout
    assert "建议第一句: 把测试跑绿" in result.stdout
    assert _snapshot(codex) == before
    assert (codex / "config.toml").stat().st_mtime_ns == before_mtime


def test_scaffold_rejects_codex_workspace_root(tmp_path):
    codex = tmp_path / ".codex"
    codex.mkdir()
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        codex,
    )
    assert result.returncode == 1
    assert "workspace-root" in result.stdout


def test_scaffold_rejects_codex_dir_flag(tmp_path):
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--codex-dir",
        tmp_path / ".codex",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        tmp_path / "workspace",
    )
    assert result.returncode == 2
    assert "--codex-dir" in result.stderr


def test_scaffold_conflicts_with_preset_and_file(tmp_path):
    source = tmp_path / "custom.md"
    source.write_text("x\n", encoding="utf-8")
    preset = _run(
        "--scaffold",
        "pytest_complete",
        "--preset",
        "contract",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        tmp_path / "workspace",
    )
    file_result = _run(
        "--scaffold",
        "pytest_complete",
        "--file",
        source,
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        tmp_path / "workspace",
    )
    assert preset.returncode == 2
    assert file_result.returncode == 2


def test_repeat_scaffold_same_fingerprint_is_noop(tmp_path):
    workspace = tmp_path / "workspace"
    first = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    dest = workspace / "pytest_complete"
    row = dest / "data" / "row.json"
    original = row.read_bytes()
    row.write_text('{"id": 0, "slot_a": "edited", "slot_b": "???"}\n', encoding="utf-8")
    second = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "unchanged" in second.stdout
    assert row.read_text(encoding="utf-8") == '{"id": 0, "slot_a": "edited", "slot_b": "???"}\n'
    row.write_bytes(original)


def test_fingerprint_mismatch_without_force_fails(tmp_path):
    workspace = tmp_path / "workspace"
    pack_dir = tmp_path / "packs"
    shutil.copytree(PACK_ROOT / "pytest_complete", pack_dir / "pytest_complete")
    first = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        pack_dir,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    readme = pack_dir / "pytest_complete" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")
    blocked = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        pack_dir,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert blocked.returncode == 1
    forced = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        pack_dir,
        "--workspace-root",
        workspace,
        "--yes",
        "--force",
    )
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert list(workspace.glob("pytest_complete.bak_*"))


def test_scaffold_uninstall_removes_only_that_pack(tmp_path):
    workspace = tmp_path / "workspace"
    first = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    extra = workspace / "keep_me"
    extra.mkdir()
    (extra / "note.txt").write_text("stay\n", encoding="utf-8")
    preview = _run(
        "--scaffold-uninstall",
        "pytest_complete",
        "--workspace-root",
        workspace,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert (workspace / "pytest_complete").is_dir()
    removed = _run(
        "--scaffold-uninstall",
        "pytest_complete",
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not (workspace / "pytest_complete").exists()
    assert (extra / "note.txt").read_text(encoding="utf-8") == "stay\n"
    registry = json.loads((workspace / ".registry.json").read_text(encoding="utf-8"))
    assert "pytest_complete" not in registry["packs"]


def test_missing_pack_dir_exits_1(tmp_path):
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        tmp_path / "missing-packs",
        "--workspace-root",
        tmp_path / "workspace",
    )
    assert result.returncode == 1
    assert "fixture_packs" in result.stdout


def test_pytest_complete_is_red_then_green(tmp_path):
    workspace = tmp_path / "workspace"
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    dest = workspace / "pytest_complete"
    red = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_complete.py"],
        cwd=dest,
        text=True,
        capture_output=True,
    )
    assert red.returncode != 0
    tokens = " ".join(f"token{index:02d}" for index in range(20))
    (dest / "data" / "row.json").write_text(
        json.dumps({"id": 0, "slot_a": tokens, "slot_b": tokens}),
        encoding="utf-8",
    )
    green = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_complete.py"],
        cwd=dest,
        text=True,
        capture_output=True,
    )
    assert green.returncode == 0, green.stdout + green.stderr


def test_smoke_docs_forbid_restricted_terms():
    for relative in ("AGENTS.md", "README.md"):
        text = (PACK_ROOT / "pytest_complete" / relative).read_text(encoding="utf-8")
        lowered = text.lower()
        for term in (
            "越狱",
            "jailbreak",
            "harmful",
            "unsafe request",
            "ignore safety",
            "bypass policy",
        ):
            assert term.lower() not in lowered
    assert (PACK_ROOT / "pytest_complete" / "data" / "row.json").read_text(
        encoding="utf-8"
    ).strip() == '{"id": 0, "slot_a": "???", "slot_b": "???"}'


def test_workspace_is_not_world_writable_registry(tmp_path):
    workspace = tmp_path / "workspace"
    result = _run(
        "--scaffold",
        "pytest_complete",
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    registry = workspace / ".registry.json"
    metadata = workspace / "pytest_complete" / ".keysmith-fixture.json"
    assert registry.is_file()
    assert metadata.is_file()
    if os.name != "nt":
        # Windows st_mode is synthetic and does not describe the file's ACL.
        assert stat.S_IMODE(registry.stat().st_mode) & stat.S_IWOTH == 0


def test_default_pack_dir_prefers_meipass_when_frozen(tmp_path, monkeypatch):
    embedded = tmp_path / "meipass" / "fixture_packs"
    embedded.mkdir(parents=True)
    monkeypatch.setattr(codex_instruct.sys, "frozen", True, raising=False)
    monkeypatch.setattr(codex_instruct.sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    assert codex_instruct.default_fixture_pack_dir() == embedded.resolve()

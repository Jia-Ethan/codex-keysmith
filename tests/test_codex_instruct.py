import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def test_normalize_md_name_accepts_simple_names():
    assert codex_instruct.normalize_md_name("gpt5.5-unrestricted") == "gpt5.5-unrestricted.md"
    assert codex_instruct.normalize_md_name("my_rules.md") == "my_rules.md"


def test_normalize_md_name_rejects_paths_and_empty_names():
    bad_names = ["../x", "/tmp/x", "nested/x", "nested\\x", "..", ".", "", "x y"]
    for name in bad_names:
        try:
            codex_instruct.normalize_md_name(name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid name to fail: {name!r}")


def test_codex_dir_expands_user_and_requires_config(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    assert codex_instruct.resolve_codex_dir("~/.codex") == codex_dir.resolve()


def test_existing_md_file_is_backed_up_before_write(tmp_path):
    target = tmp_path / "rules.md"
    target.write_text("old", encoding="utf-8")

    backup = codex_instruct.write_md_with_backup(target, "new", "20260628_120000")

    assert target.read_text(encoding="utf-8") == "new"
    assert backup is not None
    assert backup.read_text(encoding="utf-8") == "old"
    assert backup.name == "rules.md.bak_20260628_120000"


def test_comment_only_model_instructions_does_not_count_as_existing_key(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('# model_instructions_file = "./old.md"\nmodel = "gpt-5.5"\n', encoding="utf-8")

    changed = codex_instruct.ensure_model_instructions(config, "new.md")

    assert changed is True
    assert config.read_text(encoding="utf-8") == '# model_instructions_file = "./old.md"\nmodel = "gpt-5.5"\nmodel_instructions_file = "./new.md"\n'


def test_top_level_model_instructions_is_replaced_without_touching_comments(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('# model_instructions_file = "./comment.md"\nmodel_instructions_file = "./old.md"\n', encoding="utf-8")

    changed = codex_instruct.ensure_model_instructions(config, "new.md")

    assert changed is True
    assert config.read_text(encoding="utf-8") == '# model_instructions_file = "./comment.md"\nmodel_instructions_file = "./new.md"\n'


def test_cli_without_yes_only_previews_and_does_not_write(tmp_path):
    import subprocess
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.5"\n', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--codex-dir", str(codex_dir)],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "[DRY RUN]" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.5"\n'
    assert not (codex_dir / "gpt5.5-unrestricted.md").exists()


def test_cli_yes_writes_to_explicit_codex_dir(tmp_path):
    import subprocess
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.5"\n', encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--codex-dir", str(codex_dir), "--yes"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "[完成]" in result.stdout
    assert 'model_instructions_file = "./gpt5.5-unrestricted.md"' in config.read_text(encoding="utf-8")
    assert (codex_dir / "gpt5.5-unrestricted.md").exists()

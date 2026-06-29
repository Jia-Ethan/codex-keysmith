import importlib.util
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
ROOT = MODULE_PATH.parent
spec = importlib.util.spec_from_file_location("codex_instruct", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def make_codex_dir(tmp_path, config_text='model = "gpt-5.5"\n'):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text(config_text, encoding="utf-8")
    return codex_dir, config


def run_cli(*args, check=True):
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        text=True,
        capture_output=True,
        check=check,
    )


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


def test_backup_file_never_silently_overwrites_existing_backup(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("first", encoding="utf-8")

    first_backup = codex_instruct.backup_file(target, "20260628_120000")
    target.write_text("second", encoding="utf-8")
    second_backup = codex_instruct.backup_file(target, "20260628_120000")

    assert first_backup.name == "config.toml.bak_20260628_120000"
    assert second_backup.name == "config.toml.bak_20260628_120000_1"
    assert first_backup.read_text(encoding="utf-8") == "first"
    assert second_backup.read_text(encoding="utf-8") == "second"



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


def test_prompt_pack_examples_are_discoverable_and_loadable():
    expected = {
        "gpt5.5-unrestricted",
        "ctf-security-research",
        "general-research",
        "coding-strict-engineering-agent",
    }

    assert expected.issubset(set(codex_instruct.PROMPT_PACKS))
    for pack_name in expected:
        content = codex_instruct.load_md_content(None, pack_name)
        assert len(content) > 80
        assert "Codex" in content or "agent" in content.lower()


def test_custom_file_keeps_legacy_default_name_when_name_is_omitted(tmp_path):
    custom = tmp_path / "custom.md"
    custom.write_text("custom rules", encoding="utf-8")

    args = codex_instruct.parse_args(["--file", str(custom), "--dry-run"])

    assert codex_instruct.default_name_for_args(args) == "gpt5.5-unrestricted"



def test_cli_without_yes_only_previews_and_does_not_write(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path)

    result = run_cli("--codex-dir", str(codex_dir))

    assert "[DRY RUN]" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.5"\n'
    assert not (codex_dir / "gpt5.5-unrestricted.md").exists()


def test_cli_yes_writes_to_explicit_codex_dir(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path)

    result = run_cli("--codex-dir", str(codex_dir), "--yes")

    assert "[完成]" in result.stdout
    assert 'model_instructions_file = "./gpt5.5-unrestricted.md"' in config.read_text(encoding="utf-8")
    assert (codex_dir / "gpt5.5-unrestricted.md").exists()


def test_install_subcommand_can_use_prompt_pack_without_changing_legacy_default(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path)

    result = run_cli(
        "install",
        "--pack",
        "general-research",
        "--codex-dir",
        str(codex_dir),
        "--yes",
    )

    assert "general-research.md" in result.stdout
    assert 'model_instructions_file = "./general-research.md"' in config.read_text(encoding="utf-8")
    assert (codex_dir / "general-research.md").exists()
    assert "GENERAL RESEARCH" in (codex_dir / "general-research.md").read_text(encoding="utf-8")


def test_get_top_level_model_instructions_ignores_tables_and_comments(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '# model_instructions_file = "./comment.md"\n'
        'model_instructions_file = "./top.md"\n'
        "[profiles.test]\n"
        'model_instructions_file = "./nested.md"\n',
        encoding="utf-8",
    )

    assert codex_instruct.get_top_level_model_instructions(config) == "./top.md"


def test_backup_sets_groups_numbered_backups_under_original_timestamp(tmp_path):
    codex_dir, _config = make_codex_dir(tmp_path)
    (codex_dir / "config.toml.bak_20260628_120000").write_text("old", encoding="utf-8")
    (codex_dir / "config.toml.bak_20260628_120000_1").write_text("newer", encoding="utf-8")

    sets = codex_instruct.backup_sets(codex_dir)

    assert sets[0].timestamp == "20260628_120000"
    assert sets[0].has_config is True
    assert sets[0].prompt_count == 0
    assert {path.name for path in sets[0].files} == {
        "config.toml.bak_20260628_120000",
        "config.toml.bak_20260628_120000_1",
    }



def test_status_reports_current_instruction_and_recent_backup(tmp_path):
    codex_dir, _config = make_codex_dir(tmp_path, 'model = "gpt-5.5"\nmodel_instructions_file = "./rules.md"\n')
    (codex_dir / "rules.md").write_text("rules", encoding="utf-8")
    (codex_dir / "config.toml.bak_20260628_120000").write_text("old", encoding="utf-8")

    result = run_cli("status", "--codex-dir", str(codex_dir))

    assert "model_instructions_file: ./rules.md" in result.stdout
    assert "target exists: yes" in result.stdout
    assert "config.toml.bak_20260628_120000" in result.stdout


def test_restore_without_backup_lists_backups_and_does_not_write(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "new"\n')
    (codex_dir / "config.toml.bak_20260628_120000").write_text('model = "old"\n', encoding="utf-8")

    result = run_cli("restore", "--codex-dir", str(codex_dir))

    assert "可用备份" in result.stdout
    assert "20260628_120000" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "new"\n'


def test_restore_dry_run_previews_without_overwriting(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "new"\n')
    (codex_dir / "config.toml.bak_20260628_120000").write_text('model = "old"\n', encoding="utf-8")

    result = run_cli("restore", "--codex-dir", str(codex_dir), "--backup", "20260628_120000")

    assert "[DRY RUN]" in result.stdout
    assert "config.toml.bak_20260628_120000" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "new"\n'


def test_restore_can_target_numbered_config_backup(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "current"\n')
    (codex_dir / "config.toml.bak_20260628_120000").write_text('model = "first"\n', encoding="utf-8")
    (codex_dir / "config.toml.bak_20260628_120000_1").write_text('model = "second"\n', encoding="utf-8")

    result = run_cli(
        "restore",
        "--codex-dir",
        str(codex_dir),
        "--backup",
        "20260628_120000_1",
        "--yes",
    )

    assert "config.toml.bak_20260628_120000_1" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "second"\n'



def test_restore_dry_run_lists_numbered_prompt_backups(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "new"\n')
    (codex_dir / "config.toml.bak_20260628_120000").write_text('model = "old"\n', encoding="utf-8")
    (codex_dir / "rules.md.bak_20260628_120000_1").write_text("old prompt", encoding="utf-8")

    result = run_cli(
        "restore",
        "--codex-dir",
        str(codex_dir),
        "--backup",
        "20260628_120000",
        "--include-prompts",
    )

    assert "rules.md.bak_20260628_120000_1" in result.stdout
    assert "rules.md" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "new"\n'



def test_restore_yes_restores_config_and_optionally_prompt_backup(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "new"\n')
    prompt = codex_dir / "rules.md"
    prompt.write_text("new prompt", encoding="utf-8")
    (codex_dir / "config.toml.bak_20260628_120000").write_text('model = "old"\n', encoding="utf-8")
    (codex_dir / "rules.md.bak_20260628_120000").write_text("old prompt", encoding="utf-8")

    result = run_cli(
        "restore",
        "--codex-dir",
        str(codex_dir),
        "--backup",
        "20260628_120000",
        "--include-prompts",
        "--yes",
    )

    assert "[恢复] config.toml" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "old"\n'
    assert prompt.read_text(encoding="utf-8") == "old prompt"
    assert any(p.name.startswith("config.toml.bak_") for p in codex_dir.iterdir())


def test_uninstall_dry_run_previews_without_modifying_config_or_prompt(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "gpt-5.5"\nmodel_instructions_file = "./rules.md"\n')
    prompt = codex_dir / "rules.md"
    prompt.write_text("rules", encoding="utf-8")

    result = run_cli("uninstall", "--codex-dir", str(codex_dir), "--delete-prompt")

    assert "[DRY RUN]" in result.stdout
    assert "remove model_instructions_file" in result.stdout
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.5"\nmodel_instructions_file = "./rules.md"\n'
    assert prompt.exists()


def test_uninstall_yes_removes_key_and_backs_up_prompt_before_delete(tmp_path):
    codex_dir, config = make_codex_dir(tmp_path, 'model = "gpt-5.5"\nmodel_instructions_file = "./rules.md"\n')
    prompt = codex_dir / "rules.md"
    prompt.write_text("rules", encoding="utf-8")

    result = run_cli("uninstall", "--codex-dir", str(codex_dir), "--delete-prompt", "--yes")

    assert "[卸载]" in result.stdout
    assert "model_instructions_file" not in config.read_text(encoding="utf-8")
    assert not prompt.exists()
    assert any(p.name.startswith("rules.md.bak_") for p in codex_dir.iterdir())


def test_windows_wrapper_is_safe_passthrough_script():
    wrapper = ROOT / "scripts" / "codex-keysmith.ps1"

    content = wrapper.read_text(encoding="utf-8")

    assert "ValueFromRemainingArguments" in content
    assert "codex-instruct.py" in content
    assert "--yes" not in content
    assert "Copy-Item" not in content
    assert "copy /Y" not in content.lower()
    assert "Remove-Item" not in content


def test_windows_cmd_shim_forwards_without_silent_overwrite():
    wrapper = ROOT / "scripts" / "codex-keysmith.cmd"

    content = wrapper.read_text(encoding="utf-8")

    assert "%*" in content
    assert "codex-instruct.py" in content
    assert "copy /Y" not in content.lower()
    assert "xcopy" not in content.lower()
    assert "del " not in content.lower()
    assert "--yes" not in content

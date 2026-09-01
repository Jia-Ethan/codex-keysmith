import importlib.util
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct_boundaries", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _make_symlink(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_external_markdown_accepts_unicode_path_and_content(tmp_path):
    source = tmp_path / "规则-猫.md"
    source.write_bytes("第一行\n🐈 café\n".encode("utf-8"))

    assert codex_instruct.load_md_content(str(source)) == "第一行\n🐈 café\n"


@pytest.mark.parametrize("node_kind", ["directory", "symlink", "dangling"])
def test_external_markdown_rejects_non_regular_nodes(tmp_path, node_kind):
    source = tmp_path / "rules.md"
    if node_kind == "directory":
        source.mkdir()
    elif node_kind == "symlink":
        target = tmp_path / "actual.md"
        target.write_text("outside\n", encoding="utf-8")
        _make_symlink(source, target)
    else:
        _make_symlink(source, tmp_path / "missing.md")

    with pytest.raises(FileNotFoundError, match="不是普通文件"):
        codex_instruct.load_md_content(str(source))


def test_external_markdown_rejects_invalid_utf8(tmp_path):
    source = tmp_path / "rules.md"
    source.write_bytes(b"valid\n\xff\xfe")

    with pytest.raises(UnicodeDecodeError, match="不是有效 UTF-8"):
        codex_instruct.load_md_content(str(source))


def test_render_preserves_bom_crlf_and_final_newline():
    content = (
        '\ufeffmodel = "gpt-5.6"\r\n'
        '# model_instructions_file = "./comment.md"\r\n'
        "\r\n"
        "[profiles.default]\r\n"
        'model_instructions_file = "./nested.md"\r\n'
    )

    updated, changed = codex_instruct.render_model_instructions(
        content,
        "new.md",
    )

    assert changed is True
    assert updated.startswith('\ufeffmodel = "gpt-5.6"\r\n')
    assert 'model = "gpt-5.6"\r\nmodel_instructions_file = "./new.md"\r\n' in updated
    assert updated.endswith('model_instructions_file = "./nested.md"\r\n')
    assert "\n" not in updated.replace("\r\n", "")


def test_render_preserves_missing_final_newline():
    content = 'model = "gpt-5.6"'

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated == 'model = "gpt-5.6"\nmodel_instructions_file = "./new.md"'
    assert not updated.endswith("\n")


@pytest.mark.parametrize(
    "quoted_key",
    [
        '"model_instructions_file"',
        "'model_instructions_file'",
        '"model\\u005finstructions_file"',
    ],
)
def test_render_recognizes_simple_quoted_target_keys(quoted_key):
    content = f'{quoted_key} = "./old.md" # replace me\n'

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated == 'model_instructions_file = "./new.md"\n'


def test_basic_toml_string_decoder_supports_standard_escapes():
    encoded = '"\\b\\t\\n\\f\\r\\\\\\"\\u0061\\U0001F408"'

    assert codex_instruct._decode_basic_toml_string(encoded) == (
        '\b\t\n\f\r\\"a🐈'
    )


@pytest.mark.parametrize(
    "encoded, message",
    [
        ("not-quoted", "边界"),
        ('"control\x01"', "控制字符"),
        ('"trailing' + "\\" + '"', "转义不完整"),
        ('"\\u12xz"', "Unicode 转义不完整"),
        ('"\\U00110000"', "有效范围"),
        ('"\\uD800"', "有效范围"),
        ('"\\q"', "未知转义"),
    ],
)
def test_basic_toml_string_decoder_rejects_ambiguous_escapes(encoded, message):
    with pytest.raises(codex_instruct.ConfigConflict, match=message):
        codex_instruct._decode_basic_toml_string(encoded)


def test_simple_toml_key_parser_handles_dotted_and_invalid_literal_keys():
    assert codex_instruct._parse_simple_toml_key("profile.model") is None
    with pytest.raises(codex_instruct.ConfigConflict, match="dotted key"):
        codex_instruct._parse_simple_toml_key("profile..model")
    with pytest.raises(codex_instruct.ConfigConflict, match="命名空间"):
        codex_instruct._parse_simple_toml_key(
            '"model_instructions_file".child'
        )
    with pytest.raises(codex_instruct.ConfigConflict, match="字面量键"):
        codex_instruct._parse_simple_toml_key("'bad'key'")
    with pytest.raises(codex_instruct.ConfigConflict, match="顶层键"):
        codex_instruct._parse_simple_toml_key("bad key")


def test_render_keeps_quoted_target_when_value_already_matches():
    content = "'model_instructions_file' = './new.md' # retained\n"

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is False
    assert updated == content


def test_render_ignores_nested_same_name_for_normal_and_array_tables():
    for table_header in ("[profile]", "[[profiles]]"):
        content = (
            '# root comment containing model_instructions_file = "./fake.md"\n'
            f"{table_header}\n"
            'model_instructions_file = "./nested.md"\n'
        )

        updated, changed = codex_instruct.render_model_instructions(
            content,
            "root.md",
        )

        assert changed is True
        assert updated.count("model_instructions_file") == 3
        assert 'model_instructions_file = "./root.md"\n' in updated
        assert updated.endswith('model_instructions_file = "./nested.md"\n')


def test_render_allows_nested_dotted_target_namespace():
    content = (
        "[profile]\n"
        'model_instructions_file.child = "nested"\n'
    )

    updated, changed = codex_instruct.render_model_instructions(content, "root.md")

    assert changed is True
    assert updated.startswith('model_instructions_file = "./root.md"\n[profile]\n')
    assert updated.endswith('model_instructions_file.child = "nested"\n')


@pytest.mark.parametrize(
    "table_header",
    [
        "[model_instructions_file]",
        "[model_instructions_file.child]",
        '[["model_instructions_file".child]]',
        "[['model_instructions_file']]",
    ],
)
def test_render_rejects_target_table_namespace(table_header):
    with pytest.raises(codex_instruct.ConfigConflict, match="表命名空间"):
        codex_instruct.render_model_instructions(
            f"{table_header}\nvalue = true\n",
            "new.md",
        )


def test_render_skips_fake_keys_and_tables_inside_multiline_values():
    content = (
        'description = """\n'
        "[not-a-table]\n"
        'model_instructions_file = "./not-a-key.md"\n'
        '"""\n'
        "values = [\n"
        '  "[also-not-a-table]", # comment\n'
        '  "model_instructions_file = fake",\n'
        "]\n"
        'model = "gpt-5.6"\n'
        "[actual]\n"
        'model_instructions_file = "./nested.md"\n'
    )

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert 'model = "gpt-5.6"\nmodel_instructions_file = "./new.md"\n' in updated
    assert updated.endswith('model_instructions_file = "./nested.md"\n')


def test_render_replaces_entire_multiline_target_value():
    content = (
        'model_instructions_file = """\n'
        "./old.md\n"
        '"""\n'
        'model = "gpt-5.6"\n'
    )

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated == (
        'model_instructions_file = "./new.md"\n'
        'model = "gpt-5.6"\n'
    )


def test_render_handles_literal_multiline_and_inline_containers():
    content = (
        "literal = '''\n"
        "# [not-a-table]\n"
        "'''\n"
        'inline = { text = "escaped \\\" quote", values = [1, 2] }\n'
        "[actual] # recognized comment\n"
        "value = 'literal'\n"
    )

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated.startswith("literal = '''\n# [not-a-table]\n'''\n")
    assert 'model_instructions_file = "./new.md"\n[actual]' in updated


@pytest.mark.parametrize(
    "content",
    [
        'description = """one quote""""\nmodel = "gpt-5.6"\n',
        'description = """two quotes"""""\nmodel = "gpt-5.6"\n',
        "description = '''one quote''''\nmodel = 'gpt-5.6'\n",
        "description = '''two quotes'''''\nmodel = 'gpt-5.6'\n",
    ],
)
def test_render_handles_four_and_five_quote_multiline_closers(content):
    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated.startswith(content.split("model =", 1)[0])
    assert 'model_instructions_file = "./new.md"\n' in updated


def test_render_replaces_target_without_adding_final_newline():
    content = 'model_instructions_file = "./old.md"'

    updated, changed = codex_instruct.render_model_instructions(content, "new.md")

    assert changed is True
    assert updated == 'model_instructions_file = "./new.md"'


def test_render_rejects_duplicate_top_level_target_including_quoted_key():
    content = (
        'model_instructions_file = "./one.md"\n'
        '"model_instructions_file" = "./two.md"\n'
    )

    with pytest.raises(codex_instruct.ConfigConflict, match="重复"):
        codex_instruct.render_model_instructions(content, "new.md")


@pytest.mark.parametrize(
    "content",
    [
        'model = "unterminated\n',
        "values = [1, 2\n",
        "[broken\n",
        "model without equals\n",
        "model = value\rnext = value\r",
        "[nested]\nvalue = '''unterminated\n",
    ],
)
def test_render_fails_closed_on_ambiguous_root_syntax(content):
    with pytest.raises(codex_instruct.ConfigConflict):
        codex_instruct.render_model_instructions(content, "new.md")


@pytest.mark.parametrize(
    "content, message",
    [
        ("value = ]\n", "未配对"),
        ("value = }\n", "未配对"),
        ("value = [1, # eof", "文件结尾"),
        ("value = # missing\n", "缺少值"),
        ("value =", "缺少值"),
        ('value = "escaped \\\n', "基本字符串"),
        ("['unterminated]\n", "未闭合的引号"),
        ("[[]]\n", "array-of-tables"),
        ("[]\n", "TOML 表头"),
    ],
)
def test_toml_state_machine_rejects_specific_unbalanced_constructs(content, message):
    with pytest.raises(codex_instruct.ConfigConflict, match=message):
        codex_instruct.render_model_instructions(content, "new.md")


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        (' "escaped \\\" quote" # comment\n', 'escaped " quote'),
        (" './literal.md' # comment\n", "./literal.md"),
        (' "value" trailing\n', None),
        (" 'value' trailing\n", None),
        (' "unterminated\n', None),
        (" 'unterminated\n", None),
        (" 42\n", None),
        (' """multi"""\n', "multi"),
        (" '''./literal.md''' # comment\n", "./literal.md"),
        (' """multi\nline"""\n', "multi\nline"),
    ],
)
def test_string_reference_parser_boundaries(raw_value, expected):
    assert codex_instruct._parse_string_value(raw_value) == expected


def test_inspection_stores_exact_config_update_plan(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_bytes(b'\xef\xbb\xbfmodel = "gpt-5.6"\r\n')

    plan = codex_instruct.inspect_directory(codex_dir, md_filename="new.md")

    assert plan.blockers == []
    assert plan.config_content == '\ufeffmodel = "gpt-5.6"\r\n'
    assert plan.updated_config_content == (
        '\ufeffmodel = "gpt-5.6"\r\n'
        'model_instructions_file = "./new.md"\r\n'
    )
    assert plan.config_changed is True
    assert plan.config_fingerprint is not None


def test_inspection_detects_inline_multiline_legacy_reference(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        'model_instructions_file = """./gpt5.5-unrestricted.md"""\n',
        encoding="utf-8",
    )
    (codex_dir / codex_instruct.LEGACY_MD_FILENAME).write_text(
        "custom referenced legacy\n",
        encoding="utf-8",
    )

    plan = codex_instruct.inspect_directory(codex_dir)

    assert plan.blockers == []
    assert plan.config_reference == "./gpt5.5-unrestricted.md"
    assert plan.legacy_action == "archive"


@pytest.mark.parametrize(
    "value",
    [
        '"""\n./gpt5.5-unrestricted.md"""',
        "'''\n./gpt5.5-unrestricted.md'''",
        '"""\\\n  ./gpt5.5-unrestricted.md"""',
    ],
)
def test_inspection_detects_multiline_legacy_reference_with_toml_newline_rules(
    tmp_path,
    value,
):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        f"model_instructions_file = {value}\n",
        encoding="utf-8",
    )
    (codex_dir / codex_instruct.LEGACY_MD_FILENAME).write_text(
        "custom referenced legacy\n",
        encoding="utf-8",
    )

    plan = codex_instruct.inspect_directory(codex_dir)

    assert plan.blockers == []
    assert plan.config_reference == "./gpt5.5-unrestricted.md"
    assert plan.legacy_action == "archive"


def test_target_multiline_value_with_unsafe_escape_fails_closed():
    content = 'model_instructions_file = """./gpt\\q.md"""\n'

    with pytest.raises(codex_instruct.ConfigConflict, match="未知转义"):
        codex_instruct.render_model_instructions(content, "new.md")


def test_deploy_preserves_new_md_when_config_changes_before_bound_backup(
    tmp_path,
    monkeypatch,
):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.6"\n', encoding="utf-8")
    monkeypatch.setattr(codex_instruct, "find_codex_dirs", lambda: [str(codex_dir)])
    real_backup_config = codex_instruct.backup_config

    def change_config_before_backup(path, timestamp=None, expected_fingerprint=None):
        config.write_text(
            'model_instructions_file = "./gpt-unrestricted.md"\n'
            "concurrent = true\n",
            encoding="utf-8",
        )
        return real_backup_config(path, timestamp, expected_fingerprint)

    monkeypatch.setattr(codex_instruct, "backup_config", change_config_before_backup)
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.deploy(args)

    assert exit_info.value.code == 1
    assert config.read_text(encoding="utf-8").endswith("concurrent = true\n")
    assert (codex_dir / "gpt-unrestricted.md").read_text(encoding="utf-8") == (
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD
    )
    assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()


def test_deploy_rejects_config_change_after_mutating_preflight(tmp_path, monkeypatch):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config = codex_dir / "config.toml"
    config.write_text('model = "gpt-5.6"\n', encoding="utf-8")
    monkeypatch.setattr(codex_instruct, "find_codex_dirs", lambda: [str(codex_dir)])
    real_reject = codex_instruct._reject_hooks_transaction_residue
    calls = 0

    def mutate_after_preflight(directory):
        nonlocal calls
        calls += 1
        real_reject(directory)
        if calls == 2:
            config.write_text('model = "concurrent"\n', encoding="utf-8")

    monkeypatch.setattr(
        codex_instruct,
        "_reject_hooks_transaction_residue",
        mutate_after_preflight,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.deploy(args)

    assert exit_info.value.code == 1
    assert config.read_text(encoding="utf-8") == 'model = "concurrent"\n'
    assert not (codex_dir / "gpt-unrestricted.md").exists()


def test_final_sweep_preserves_md_when_unchanged_config_changes_concurrently(
    tmp_path,
    monkeypatch,
):
    codex_dirs = [tmp_path / "one", tmp_path / "two"]
    for codex_dir in codex_dirs:
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text(
            'model_instructions_file = "./gpt-unrestricted.md"\n',
            encoding="utf-8",
        )
    monkeypatch.setattr(
        codex_instruct,
        "find_codex_dirs",
        lambda: [str(path) for path in codex_dirs],
    )
    real_atomic_write = codex_instruct.atomic_write_text
    md_writes = 0

    def mutate_first_config_after_second_md(path, content, *args, **kwargs):
        nonlocal md_writes
        result = real_atomic_write(path, content, *args, **kwargs)
        if Path(path).name == "gpt-unrestricted.md":
            md_writes += 1
            if md_writes == 2:
                (codex_dirs[0] / "config.toml").write_text(
                    'model_instructions_file = "./gpt-unrestricted.md"\n'
                    "concurrent = true\n",
                    encoding="utf-8",
                )
        return result

    monkeypatch.setattr(
        codex_instruct,
        "atomic_write_text",
        mutate_first_config_after_second_md,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.deploy(args)

    assert exit_info.value.code == 1
    assert (codex_dirs[0] / "gpt-unrestricted.md").exists()
    assert not (codex_dirs[1] / "gpt-unrestricted.md").exists()
    assert "concurrent = true" in (codex_dirs[0] / "config.toml").read_text(
        encoding="utf-8"
    )


def test_final_sweep_detects_concurrent_md_replacement(tmp_path, monkeypatch):
    codex_dirs = [tmp_path / "one", tmp_path / "two"]
    for codex_dir in codex_dirs:
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text(
            'model_instructions_file = "./gpt-unrestricted.md"\n',
            encoding="utf-8",
        )
    monkeypatch.setattr(
        codex_instruct,
        "find_codex_dirs",
        lambda: [str(path) for path in codex_dirs],
    )
    real_atomic_write = codex_instruct.atomic_write_text
    md_writes = 0

    def mutate_first_md_after_second_md(path, content, *args, **kwargs):
        nonlocal md_writes
        result = real_atomic_write(path, content, *args, **kwargs)
        if Path(path).name == "gpt-unrestricted.md":
            md_writes += 1
            if md_writes == 2:
                (codex_dirs[0] / "gpt-unrestricted.md").write_text(
                    "concurrent prompt\n",
                    encoding="utf-8",
                )
        return result

    monkeypatch.setattr(
        codex_instruct,
        "atomic_write_text",
        mutate_first_md_after_second_md,
    )
    args = types.SimpleNamespace(
        file=None,
        name="gpt-unrestricted",
        dry_run=False,
        yes=True,
        skip_hooks_isolation=False,
    )

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.deploy(args)

    assert exit_info.value.code == 1
    assert (codex_dirs[0] / "gpt-unrestricted.md").read_text(
        encoding="utf-8"
    ) == "concurrent prompt\n"
    assert not (codex_dirs[1] / "gpt-unrestricted.md").exists()

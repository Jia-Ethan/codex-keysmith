import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "schema1-historical-field-restore.json"
)
spec = importlib.util.spec_from_file_location("codex_instruct_uninstall", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _make_codex_dir(tmp_path, name=".codex", config='model = "gpt-5.6"\n'):
    codex_dir = tmp_path / name
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(config, encoding="utf-8")
    return codex_dir


def _run(*args, check=False):
    arguments = list(map(str, args))
    if not any(argument == "--lang" or argument.startswith("--lang=") for argument in arguments):
        arguments.extend(("--lang", "zh-CN"))
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *arguments],
        text=True,
        capture_output=True,
        check=check,
    )


def _deploy(codex_dir):
    return _run("--codex-dir", codex_dir, "--yes", check=True)


def _snapshot_files(codex_dir):
    return {
        path.name: path.read_bytes()
        for path in codex_dir.iterdir()
        if path.is_file() and not path.name.startswith(".keysmith-")
    }


def test_version_and_explicit_english_status(tmp_path):
    version = _run("--version")
    assert version.returncode == 0
    assert version.stdout.strip().endswith(codex_instruct.__version__)

    codex_dir = _make_codex_dir(tmp_path)
    status = _run("--codex-dir", codex_dir, "--status", "--lang", "en")

    assert status.returncode == 0
    assert "[Status]" in status.stdout
    assert "Deployability: ready" in status.stdout
    assert "[Done]" in status.stdout
    assert re.search(r"[\u3400-\u9fff]", status.stdout) is None

    help_result = _run("--lang", "en", "--help")
    assert help_result.returncode == 0
    assert "Deploy and manage a Codex Markdown instruction file" in help_result.stdout
    assert "Manifest-based uninstall" not in help_result.stdout
    assert "manifest-based uninstall" in help_result.stdout


def test_auto_language_uses_supported_locale_and_safe_fallback(monkeypatch):
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert codex_instruct._resolve_output_language("auto") == "en"
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    assert codex_instruct._resolve_output_language("auto") == "zh-CN"
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    assert codex_instruct._resolve_output_language("auto") == "zh-CN"
    assert codex_instruct._language_from_argv(["--lang=en"]) == "en"
    assert codex_instruct._language_from_argv(["--lang", "zh-CN"]) == "zh-CN"

    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        codex_instruct.locale,
        "getlocale",
        lambda: ("English_United States", "1252"),
    )
    assert codex_instruct._resolve_output_language("auto") == "en"
    monkeypatch.setattr(
        codex_instruct.locale,
        "getlocale",
        lambda: ("Chinese_China", "936"),
    )
    assert codex_instruct._resolve_output_language("auto") == "zh-CN"


def test_auto_language_subprocess_respects_locale_precedence(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)

    def run_with_locale(**locale_environment):
        environment = os.environ.copy()
        environment.update(locale_environment)
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), "--codex-dir", str(codex_dir), "--status"],
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )

    english = run_with_locale(LC_ALL="en_US.UTF-8", LC_MESSAGES="zh_CN.UTF-8", LANG="zh_CN.UTF-8")
    chinese = run_with_locale(LC_ALL="zh_CN.UTF-8", LC_MESSAGES="en_US.UTF-8", LANG="en_US.UTF-8")
    fallback = run_with_locale(LC_ALL="C", LC_MESSAGES="en_US.UTF-8", LANG="en_US.UTF-8")

    assert "[Status]" in english.stdout
    assert "[状态]" in chinese.stdout
    assert "[状态]" in fallback.stdout


def test_explicit_english_empty_modes_are_fully_localized(tmp_path):
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(isolated_home),
            "USERPROFILE": str(isolated_home),
            "LOCALAPPDATA": str(isolated_home / "local"),
            "CODEX_HOME": "",
            "LC_ALL": "en_US.UTF-8",
            "LC_MESSAGES": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
            "PYTHONUTF8": "1",
        }
    )
    cases = [
        (("--status",), 1, "No Codex configuration locations were found"),
        (("--dry-run",), 1, "No Codex installation was found"),
        (("--restore-hooks",), 1, "No restorable Codex configuration locations"),
        (("--recover",), 0, "No interrupted deployment transaction requires recovery"),
        (("--uninstall",), 0, "No codex-keysmith deployment manifest was found"),
    ]

    for arguments, returncode, expected in cases:
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), *arguments, "--lang", "en"],
            text=True,
            capture_output=True,
            env=environment,
        )
        output = result.stdout + result.stderr
        assert result.returncode == returncode
        assert expected in output
        assert re.search(r"[\u3400-\u9fff]", output) is None


def test_explicit_english_codex_dir_errors_are_fully_localized(tmp_path):
    missing_directory = tmp_path / "missing"
    missing_config = tmp_path / "missing-config"
    missing_config.mkdir()
    abnormal_config = tmp_path / "abnormal-config"
    abnormal_config.mkdir()
    (abnormal_config / "config.toml").mkdir()

    cases = [
        (
            missing_directory,
            "Specified directory does not exist or is not a directory",
        ),
        (missing_config, "config.toml not found"),
        (abnormal_config, "config.toml is a directory, not a regular file"),
    ]

    for codex_dir, expected in cases:
        result = _run("--codex-dir", codex_dir, "--status", "--lang", "en")
        output = result.stdout + result.stderr
        assert result.returncode == 1
        assert expected in output
        assert re.search(r"[\u3400-\u9fff]", output) is None


def test_explicit_english_restore_noop_is_fully_localized(tmp_path):
    codex_dir = tmp_path / "restore-noop"
    codex_dir.mkdir()

    result = _run("--codex-dir", codex_dir, "--restore-hooks", "--lang", "en")

    assert result.returncode == 0
    assert "hooks.json.disabled not found" in result.stdout
    assert re.search(r"[\u3400-\u9fff]", result.stdout) is None


def test_output_stream_configuration_is_best_effort(monkeypatch):
    class Stream:
        def __init__(self, error=None):
            self.error = error
            self.encodings = []

        def reconfigure(self, *, encoding):
            self.encodings.append(encoding)
            if self.error is not None:
                raise self.error

    stdout = Stream()
    stderr = Stream(ValueError("closed"))
    monkeypatch.setattr(codex_instruct.sys, "stdout", stdout)
    monkeypatch.setattr(codex_instruct.sys, "stderr", stderr)
    codex_instruct._configure_output_streams()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]


def test_dry_run_discloses_prompt_source_hash_and_global_behavior(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    expected_hash = hashlib.sha256(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD.encode("utf-8")
    ).hexdigest()

    english = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "en")
    chinese = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "zh-CN")

    assert english.returncode == 0
    assert "[Prompt] Source: bundled examples/gpt-unrestricted.md" in english.stdout
    assert expected_hash in english.stdout
    assert "[Behavior notice]" in english.stdout
    assert "global model_instructions_file" in english.stdout
    assert re.search(r"[\u3400-\u9fff]", english.stdout) is None
    assert chinese.returncode == 0
    assert "[提示词] 来源: 内置 examples/gpt-unrestricted.md" in chinese.stdout
    assert "[显著行为]" in chinese.stdout


def test_explicit_english_translates_blocked_and_restore_paths(tmp_path):
    blocked_dir = _make_codex_dir(tmp_path, name="blocked")
    (blocked_dir / "hooks.json").mkdir()
    blocked = _run("--codex-dir", blocked_dir, "--dry-run", "--lang", "en")

    assert blocked.returncode == 1
    assert "[Blocked] hooks.json is a directory, not a regular file" in blocked.stdout
    assert "dry-run found 1 confirmed blocker" in blocked.stdout
    assert re.search(r"[\u3400-\u9fff]", blocked.stdout) is None

    restore_dir = tmp_path / "restore"
    restore_dir.mkdir()
    target = restore_dir / "target.json"
    target.write_text("target\n", encoding="utf-8")
    disabled = restore_dir / "hooks.json.disabled"
    try:
        disabled.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("symlink creation is unavailable: {}".format(exc))

    restored = _run("--codex-dir", restore_dir, "--restore-hooks", "--lang", "en")

    assert restored.returncode == 1
    assert "hooks.json.disabled is a symbolic link, not a regular file" in restored.stdout
    assert "were not restored because of abnormal hooks paths" in restored.stdout
    assert re.search(r"[\u3400-\u9fff]", restored.stdout) is None


def test_dry_run_discloses_external_prompt_source_and_hash(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    prompt = tmp_path / "custom.md"
    prompt.write_text("custom prompt\n", encoding="utf-8")
    expected_hash = hashlib.sha256(prompt.read_bytes()).hexdigest()

    result = _run(
        "--codex-dir",
        codex_dir,
        "--file",
        prompt,
        "--dry-run",
        "--lang",
        "en",
    )

    assert result.returncode == 0
    assert "[Prompt] Source: external file" in result.stdout
    assert str(prompt) in result.stdout
    assert expected_hash in result.stdout
    assert "[Behavior notice]" not in result.stdout


@pytest.mark.parametrize(
    "extra",
    [
        ("--file", "prompt.md"),
        ("--name", "prompt"),
        ("--yes",),
        ("--skip-hooks-isolation",),
    ],
)
def test_restore_rejects_deployment_arguments(tmp_path, extra):
    codex_dir = _make_codex_dir(tmp_path)
    result = _run("--codex-dir", codex_dir, "--restore-hooks", *extra)

    assert result.returncode == 2
    assert "--restore-hooks" in result.stderr


def test_uninstall_previews_then_restores_first_deployment(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    original = _snapshot_files(codex_dir)
    _deploy(codex_dir)
    deployed = _snapshot_files(codex_dir)
    if os.name != "nt":
        assert (
            (codex_dir / codex_instruct.MANIFEST_FILENAME).stat().st_mode & 0o777
        ) == 0o600

    preview = _run("--codex-dir", codex_dir, "--uninstall")
    english_preview = _run(
        "--codex-dir",
        codex_dir,
        "--uninstall",
        "--lang",
        "en",
    )

    assert preview.returncode == 0
    assert "[预览]" in preview.stdout
    assert english_preview.returncode == 0
    assert "Restore config/MD/hooks/legacy" in english_preview.stdout
    assert re.search(r"[\u3400-\u9fff]", english_preview.stdout) is None
    assert _snapshot_files(codex_dir) == deployed

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert (codex_dir / "config.toml").read_bytes() == original["config.toml"]
    assert not (codex_dir / "gpt-unrestricted.md").exists()
    assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()
    assert list(codex_dir.glob(f"{codex_instruct.MANIFEST_FILENAME}.uninstalled_*"))
    assert list(codex_dir.glob("config.toml.bak_*"))


def test_frozen_schema1_manifest_supports_external_rewrite_field_only_restore(
    tmp_path,
):
    manifest = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    codex_dir = tmp_path / "historical-schema1"
    codex_dir.mkdir()
    original = (
        'model_instructions_file = "./historical.md"\n'
        'model = "pre-schema-one"\n'
    )
    deployed_config = (
        'model_instructions_file = "./gpt-unrestricted.md"\n'
        'model = "pre-schema-one"\n'
    )
    prompt = "frozen schema-1 historical prompt\n"
    config = codex_dir / "config.toml"
    backup = codex_dir / manifest["config"]["backup"]
    md = codex_dir / manifest["md"]["path"]
    config.write_bytes(deployed_config.encode("utf-8"))
    backup.write_bytes(original.encode("utf-8"))
    md.write_bytes(prompt.encode("utf-8"))
    for path, expected in (
        (config, manifest["config"]["after"]),
        (backup, manifest["config"]["before"]),
        (md, manifest["md"]["after"]),
    ):
        os.utime(path, ns=(expected["mtime_ns"], expected["mtime_ns"]))
        assert codex_instruct._portable_matches(path, expected)
    (codex_dir / codex_instruct.MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    external_rewrite = (
        'model = "ccswitch-historical"\n'
        'approval_policy = "never"\n'
        'model_instructions_file = "./gpt-unrestricted.md" # external rewrite\n'
    )
    config.write_text(external_rewrite, encoding="utf-8")

    result = _run(
        "--codex-dir",
        codex_dir,
        "--uninstall",
        "--yes",
        "--lang",
        "en",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"[\u3400-\u9fff]", result.stdout + result.stderr) is None
    assert config.read_text(encoding="utf-8") == (
        'model = "ccswitch-historical"\n'
        'approval_policy = "never"\n'
        'model_instructions_file = "./historical.md"\n'
    )
    assert not md.exists()


def test_ccswitch_rewrite_preserves_unrelated_config_and_restores_old_reference(
    tmp_path,
):
    original = (
        'model_instructions_file = "./previous.md"\n'
        'model = "gpt-5.6"\n'
    )
    codex_dir = _make_codex_dir(tmp_path, config=original)
    _deploy(codex_dir)
    rewritten = (
        'model = "ccswitch-model"\n'
        'approval_policy = "never"\n'
        'model_instructions_file = "./gpt-unrestricted.md" # kept by CCSwitch\n'
    )
    (codex_dir / "config.toml").write_text(rewritten, encoding="utf-8")

    status = _run("--codex-dir", codex_dir, "--status")
    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert status.returncode == 0, status.stdout + status.stderr
    assert "卸载就绪度: ready" in status.stdout
    assert "可部署性: ready" in status.stdout
    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "ccswitch-model"\n'
        'approval_policy = "never"\n'
        'model_instructions_file = "./previous.md"\n'
    )
    assert not (codex_dir / "gpt-unrestricted.md").exists()


def test_ccswitch_missing_reference_is_reported_as_inactive_but_remains_write_blocked(
    tmp_path,
):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    inactive_config = (
        'model = "ccswitch-off"\n'
        'approval_policy = "on-request"\n'
    )
    config.write_text(inactive_config, encoding="utf-8")
    before = _snapshot_files(codex_dir)

    direct_plan = codex_instruct.inspect_directory(
        codex_dir,
        skip_hooks_isolation=True,
        status_mode=True,
    )
    status = _run("--codex-dir", codex_dir, "--status")
    deploy = _run("--codex-dir", codex_dir, "--yes")
    uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert direct_plan.activation_state == "inactive"
    assert direct_plan.inactive_config_blocker is not None
    assert status.returncode == 0, status.stdout + status.stderr
    assert "配置激活状态: inactive-by-config" in status.stdout
    assert "结构健康: healthy" in status.stdout
    assert "卸载就绪度: blocked（先切回 active 配置）" in status.stdout
    assert "可部署性: blocked（先切回 active 配置）" in status.stdout
    assert "hooks 隔离不随 config.toml 配置切换" in status.stdout
    assert deploy.returncode == 1
    assert uninstall.returncode == 1
    assert _snapshot_files(codex_dir) == before


def test_ccswitch_inactive_profile_can_switch_back_to_managed_active_profile(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    config.write_text('model = "ccswitch-off"\n', encoding="utf-8")

    inactive = _run("--codex-dir", codex_dir, "--status")

    config.write_text(
        'model = "ccswitch-on"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n',
        encoding="utf-8",
    )
    active = _run("--codex-dir", codex_dir, "--status")
    uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert inactive.returncode == 0, inactive.stdout + inactive.stderr
    assert "配置激活状态: inactive-by-config" in inactive.stdout
    assert active.returncode == 0, active.stdout + active.stderr
    assert "配置激活状态: active" in active.stdout
    assert "卸载就绪度: ready" in active.stdout
    assert "可部署性: ready" in active.stdout
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert config.read_text(encoding="utf-8") == 'model = "ccswitch-on"\n'


def test_english_ccswitch_inactive_status_and_deploy_blockers_are_fully_localized(
    tmp_path,
):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")
    _deploy(codex_dir)
    (codex_dir / "config.toml").write_text(
        'model = "ccswitch-off"\n',
        encoding="utf-8",
    )

    status = _run("--codex-dir", codex_dir, "--status", "--lang", "en")
    preview = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "en")
    deploy = _run("--codex-dir", codex_dir, "--yes", "--lang", "en")

    assert status.returncode == 0, status.stdout + status.stderr
    assert "Config activation: inactive-by-config" in status.stdout
    assert "Uninstall readiness: blocked (switch back to an active profile first)" in status.stdout
    assert "Deployability: blocked (switch back to an active profile first)" in status.stdout
    assert "Hook isolation does not follow config.toml profile switches" in status.stdout
    assert preview.returncode == 1
    assert deploy.returncode == 1
    assert "existing deployment manifest ownership conflict" in preview.stdout
    assert "existing deployment manifest ownership conflict" in deploy.stdout
    for result in (status, preview, deploy):
        assert re.search(r"[\u3400-\u9fff]", result.stdout + result.stderr) is None


@pytest.mark.parametrize("config_active", [False, True], ids=["field-missing", "field-active"])
@pytest.mark.parametrize("md_damage", ["missing", "drifted", "directory"])
def test_managed_markdown_damage_forces_activation_conflict_and_blocks_writes(
    tmp_path,
    config_active,
    md_damage,
):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    if not config_active:
        config.write_text('model = "ccswitch-off"\n', encoding="utf-8")
    md = codex_dir / codex_instruct.DEFAULT_MD_FILENAME
    if md_damage == "missing":
        md.unlink()
    elif md_damage == "drifted":
        md.write_text("drifted prompt\n", encoding="utf-8")
    else:
        md.unlink()
        md.mkdir()
    before_names = sorted(path.name for path in codex_dir.iterdir())
    before_config = config.read_bytes()

    status = _run("--codex-dir", codex_dir, "--status", "--lang", "en")
    preview = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "en")
    deploy = _run("--codex-dir", codex_dir, "--yes", "--lang", "en")
    uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes", "--lang", "en")

    assert status.returncode == 1
    assert preview.returncode == 1
    assert deploy.returncode == 1
    assert uninstall.returncode == 1
    assert "Config activation: conflict" in status.stdout
    assert "Config activation: active" not in status.stdout
    assert "Config activation: inactive-by-config" not in status.stdout
    for result in (status, preview, deploy, uninstall):
        assert re.search(r"[\u3400-\u9fff]", result.stdout + result.stderr) is None
    assert sorted(path.name for path in codex_dir.iterdir()) == before_names
    assert config.read_bytes() == before_config
    if md_damage == "missing":
        assert not md.exists()
    elif md_damage == "drifted":
        assert md.read_text(encoding="utf-8") == "drifted prompt\n"
    else:
        assert md.is_dir()


@pytest.mark.parametrize("config_active", [False, True], ids=["field-missing", "field-active"])
@pytest.mark.parametrize("evidence_kind", ["prompt-backup", "hooks-backup"])
def test_damaged_manifest_recovery_evidence_forces_activation_conflict(
    tmp_path,
    config_active,
    evidence_kind,
):
    codex_dir = _make_codex_dir(tmp_path)
    if evidence_kind == "hooks-backup":
        (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")
    else:
        (codex_dir / codex_instruct.DEFAULT_MD_FILENAME).write_text(
            "pre-deployment prompt\n",
            encoding="utf-8",
        )
    _deploy(codex_dir)
    if not config_active:
        (codex_dir / "config.toml").write_text(
            'model = "ccswitch-off"\n',
            encoding="utf-8",
        )
    manifest = json.loads(
        (codex_dir / codex_instruct.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    backup_name = (
        manifest["md"]["backup"]
        if evidence_kind == "prompt-backup"
        else manifest["hooks"]["backup"]
    )
    assert backup_name is not None
    evidence = codex_dir / backup_name
    evidence.write_text("drifted evidence\n", encoding="utf-8")

    status = _run("--codex-dir", codex_dir, "--status")
    deploy = _run("--codex-dir", codex_dir, "--yes")
    uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert status.returncode == 1
    assert deploy.returncode == 1
    assert uninstall.returncode == 1
    assert "配置激活状态: conflict" in status.stdout
    assert "配置激活状态: active" not in status.stdout
    assert "配置激活状态: inactive-by-config" not in status.stdout
    assert evidence.read_text(encoding="utf-8") == "drifted evidence\n"


def test_ccswitch_common_config_reinjection_keeps_effective_off_profile_active(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    # This is the effective live result when an Off provider omits the field but
    # CCSwitch's shared Codex Common Config Snippet adds it back during merge.
    (codex_dir / "config.toml").write_text(
        'model = "ccswitch-off"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n',
        encoding="utf-8",
    )

    status = _run("--codex-dir", codex_dir, "--status")

    assert status.returncode == 0, status.stdout + status.stderr
    assert "配置激活状态: active" in status.stdout
    assert "inactive-by-config" not in status.stdout


def test_abnormal_or_invalid_manifest_is_activation_conflict(tmp_path):
    for name, make_manifest in (
        (
            "directory-manifest",
            lambda path: path.mkdir(),
        ),
        (
            "invalid-manifest",
            lambda path: path.write_text("{not json", encoding="utf-8"),
        ),
    ):
        codex_dir = _make_codex_dir(tmp_path, name=name)
        make_manifest(codex_dir / codex_instruct.MANIFEST_FILENAME)

        before_names = sorted(path.name for path in codex_dir.iterdir())
        before_config = (codex_dir / "config.toml").read_bytes()
        status = _run("--codex-dir", codex_dir, "--status", "--lang", "en")
        preview = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "en")
        deploy = _run("--codex-dir", codex_dir, "--yes", "--lang", "en")
        uninstall = _run(
            "--codex-dir",
            codex_dir,
            "--uninstall",
            "--yes",
            "--lang",
            "en",
        )

        assert status.returncode == 1
        assert preview.returncode == 1
        assert deploy.returncode == 1
        assert uninstall.returncode == 1
        assert "Config activation: conflict" in status.stdout
        assert "Config activation: not-installed" not in status.stdout
        assert "Deployment manifest not found" not in uninstall.stdout
        assert "[Blocked]" in uninstall.stdout
        for result in (status, preview, deploy, uninstall):
            assert re.search(r"[\u3400-\u9fff]", result.stdout + result.stderr) is None
        assert sorted(path.name for path in codex_dir.iterdir()) == before_names
        assert (codex_dir / "config.toml").read_bytes() == before_config


def test_stacked_manifests_keep_semantic_config_ownership_after_rewrite(tmp_path):
    codex_dir = _make_codex_dir(
        tmp_path,
        config=(
            'model_instructions_file = "./previous.md"\n'
            'model = "before"\n'
        ),
    )
    _deploy(codex_dir)
    rewritten = (
        'model = "ccswitch-model"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n'
        'external = true\n'
    )
    (codex_dir / "config.toml").write_text(rewritten, encoding="utf-8")

    _deploy(codex_dir)
    first_uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")
    second_uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert first_uninstall.returncode == 0, first_uninstall.stdout + first_uninstall.stderr
    assert second_uninstall.returncode == 0, second_uninstall.stdout + second_uninstall.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "ccswitch-model"\n'
        'model_instructions_file = "./previous.md"\n'
        'external = true\n'
    )


def test_ccswitch_rewrite_preserves_unrelated_config_when_old_reference_absent(
    tmp_path,
):
    codex_dir = _make_codex_dir(tmp_path, config='model = "gpt-5.6"\n')
    _deploy(codex_dir)
    rewritten = (
        'model = "ccswitch-model"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n'
        'sandbox_mode = "workspace-write"\n'
    )
    (codex_dir / "config.toml").write_text(rewritten, encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "ccswitch-model"\n'
        'sandbox_mode = "workspace-write"\n'
    )


def test_ccswitch_rewrite_of_unchanged_owned_reference_is_not_touched(tmp_path):
    codex_dir = _make_codex_dir(
        tmp_path,
        config='model_instructions_file = "./gpt-unrestricted.md"\n',
    )
    _deploy(codex_dir)
    manifest = json.loads(
        (codex_dir / codex_instruct.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["config"]["changed"] is False
    rewritten = (
        'model = "ccswitch-model"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n'
        'notice = "external"\n'
    )
    (codex_dir / "config.toml").write_text(rewritten, encoding="utf-8")

    status = _run("--codex-dir", codex_dir, "--status")
    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert status.returncode == 0, status.stdout + status.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == rewritten
    assert not (codex_dir / "gpt-unrestricted.md").exists()


def test_exact_manifest_config_with_missing_owned_reference_still_blocks(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    manifest_path = codex_dir / codex_instruct.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_reference = 'model = "externally-published"\n'
    config.write_text(missing_reference, encoding="utf-8")
    fingerprint = codex_instruct._fingerprint_regular_file(config)
    manifest["config"]["after"] = codex_instruct._portable_fingerprint(fingerprint)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 1
    assert "model_instructions_file" in result.stdout
    assert config.read_text(encoding="utf-8") == missing_reference
    assert (codex_dir / "gpt-unrestricted.md").exists()


def test_english_uninstall_target_field_error_has_no_chinese(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    (codex_dir / "config.toml").write_text(
        'model_instructions_file = "./gpt-unrestricted.md"\ninvalid toml\n',
        encoding="utf-8",
    )

    result = _run(
        "--codex-dir",
        codex_dir,
        "--uninstall",
        "--yes",
        "--lang",
        "en",
    )

    assert result.returncode == 1
    assert "config.toml drifted and has target-field ambiguity" in result.stdout
    assert re.search(r"[\u3400-\u9fff]", result.stdout + result.stderr) is None


def test_uninstall_accepts_same_config_bytes_with_changed_mtime(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    deployed_bytes = config.read_bytes()
    current_mtime = config.stat().st_mtime_ns
    os.utime(config, ns=(config.stat().st_atime_ns, current_mtime + 10_000_000))
    assert config.read_bytes() == deployed_bytes

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5.6"\n'


def test_config_target_reference_to_other_path_remains_field_specific_blocker(
    tmp_path,
):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    current_config = (
        'model_instructions_file = "./other.md"\n'
        'model = "ccswitch-model"\n'
    )
    (codex_dir / "config.toml").write_text(current_config, encoding="utf-8")
    before = _snapshot_files(codex_dir)

    status = _run("--codex-dir", codex_dir, "--status")
    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert status.returncode == 1
    assert result.returncode == 1
    assert "配置激活状态: conflict" in status.stdout
    assert "model_instructions_file" in status.stdout
    assert "model_instructions_file" in result.stdout
    assert _snapshot_files(codex_dir) == before


@pytest.mark.parametrize(
    "current_config",
    [
        'model_instructions_file = "./gpt-unrestricted.md"\ninvalid toml\n',
        (
            'model_instructions_file = "./gpt-unrestricted.md"\n'
            '"model_instructions_file" = "./gpt-unrestricted.md"\n'
        ),
    ],
)
def test_invalid_or_ambiguous_drifted_config_blocks_uninstall(
    tmp_path,
    current_config,
):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    (codex_dir / "config.toml").write_text(current_config, encoding="utf-8")
    before = _snapshot_files(codex_dir)

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 1
    assert "config.toml" in result.stdout
    assert _snapshot_files(codex_dir) == before


def test_config_merge_cas_rejects_race_without_overwriting_external_content(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    config = codex_dir / "config.toml"
    config.write_text(
        'model = "ccswitch-model"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n',
        encoding="utf-8",
    )
    external = (
        'model = "concurrent-model"\n'
        'model_instructions_file = "./gpt-unrestricted.md"\n'
        'concurrent = true\n'
    )
    real_atomic_write = codex_instruct.atomic_write_text

    def race_before_merge(path, content, **kwargs):
        if Path(path) == config:
            config.write_text(external, encoding="utf-8")
        return real_atomic_write(path, content, **kwargs)

    monkeypatch.setattr(codex_instruct, "atomic_write_text", race_before_merge)

    with pytest.raises(SystemExit) as caught:
        codex_instruct.uninstall([str(codex_dir)], yes=True)

    assert caught.value.code == 1
    assert config.read_text(encoding="utf-8") == external
    assert (codex_dir / "gpt-unrestricted.md").exists()
    assert (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()


def test_uninstall_restores_hooks_existing_disabled_and_legacy(tmp_path):
    old_config = (
        'model_instructions_file = "./gpt5.5-unrestricted.md"\n'
        'model = "gpt-5.6"\n'
    )
    codex_dir = _make_codex_dir(tmp_path, config=old_config)
    (codex_dir / "hooks.json").write_bytes(b"\x00active hooks\xff")
    (codex_dir / "hooks.json.disabled").write_bytes(b"previous disabled\n")
    (codex_dir / codex_instruct.LEGACY_MD_FILENAME).write_text(
        "custom legacy prompt\n",
        encoding="utf-8",
    )

    _deploy(codex_dir)
    manifest = json.loads(
        (codex_dir / codex_instruct.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["hooks"]["isolated"] is True
    assert manifest["hooks"]["previous_disabled_backup"]
    assert manifest["legacy"]["action"] == "archive"

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == old_config
    assert (codex_dir / "hooks.json").read_bytes() == b"\x00active hooks\xff"
    assert (codex_dir / "hooks.json.disabled").read_bytes() == b"previous disabled\n"
    assert (codex_dir / codex_instruct.LEGACY_MD_FILENAME).read_text(
        encoding="utf-8"
    ) == "custom legacy prompt\n"
    assert not (codex_dir / "gpt-unrestricted.md").exists()


def test_uninstall_accepts_hooks_restored_by_supported_command(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hooks\n", encoding="utf-8")
    (codex_dir / "hooks.json.disabled").write_text(
        "previous disabled\n",
        encoding="utf-8",
    )
    _deploy(codex_dir)

    restored = _run("--codex-dir", codex_dir, "--restore-hooks")
    assert restored.returncode == 0
    assert (codex_dir / "hooks.json").read_text(encoding="utf-8") == (
        "active hooks\n"
    )
    assert not (codex_dir / "hooks.json.disabled").exists()

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert (codex_dir / "hooks.json").read_text(encoding="utf-8") == (
        "active hooks\n"
    )
    assert (codex_dir / "hooks.json.disabled").read_text(encoding="utf-8") == (
        "previous disabled\n"
    )


def test_uninstall_preserves_explicitly_skipped_hooks(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    hooks = codex_dir / "hooks.json"
    hooks.write_bytes(b"\x00active and skipped\xff")
    deployed = _run(
        "--codex-dir",
        codex_dir,
        "--skip-hooks-isolation",
        "--yes",
    )
    assert deployed.returncode == 0
    hooks.write_bytes(b"\x00changed after skipped deployment\xff")

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert hooks.read_bytes() == b"\x00changed after skipped deployment\xff"
    assert not (codex_dir / "hooks.json.disabled").exists()


def test_uninstall_ignores_unmanaged_legacy_created_or_changed_after_deploy(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    legacy = codex_dir / codex_instruct.LEGACY_MD_FILENAME
    legacy.write_text("user legacy before\n", encoding="utf-8")
    _deploy(codex_dir)
    legacy.write_text("user legacy after\n", encoding="utf-8")

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert legacy.read_text(encoding="utf-8") == "user legacy after\n"


def test_uninstall_final_sweep_detects_earlier_directory_race(tmp_path, monkeypatch):
    first = _make_codex_dir(tmp_path, "first")
    second = _make_codex_dir(tmp_path, "second")
    _deploy(first)
    _deploy(second)
    original_execute = codex_instruct._execute_uninstall_state
    calls = 0

    def race_after_last_directory(state, timestamp):
        nonlocal calls
        original_execute(state, timestamp)
        calls += 1
        if calls == 2:
            (first / "config.toml").write_text(
                'model = "concurrent"\n',
                encoding="utf-8",
            )

    monkeypatch.setattr(
        codex_instruct,
        "_execute_uninstall_state",
        race_after_last_directory,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.uninstall([str(first), str(second)], yes=True)

    assert caught.value.code == 1
    assert (first / "config.toml").read_text(encoding="utf-8") == (
        'model = "concurrent"\n'
    )


def test_uninstall_final_sweep_tracks_unchanged_managed_config(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(
        tmp_path,
        config='model_instructions_file = "./gpt-unrestricted.md"\n',
    )
    _deploy(codex_dir)
    manifest = json.loads(
        (codex_dir / codex_instruct.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["config"]["changed"] is False
    original_execute = codex_instruct._execute_uninstall_state

    def race_after_execute(state, timestamp):
        original_execute(state, timestamp)
        (codex_dir / "config.toml").write_text(
            'model = "concurrent"\n',
            encoding="utf-8",
        )

    monkeypatch.setattr(
        codex_instruct,
        "_execute_uninstall_state",
        race_after_execute,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.uninstall([str(codex_dir)], yes=True)

    assert caught.value.code == 1
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == (
        'model = "concurrent"\n'
    )


def test_uninstall_cleanup_rejects_replaced_transaction_directory(
    tmp_path,
    monkeypatch,
):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    original = codex_instruct._safe_remove_owned_directory
    replacement = None

    def replace_before_cleanup(path, identity, members, require_exact_members=False):
        nonlocal replacement
        if path.name.startswith(".keysmith-uninstall-") and replacement is None:
            evidence = path.with_name(path.name + ".owned-evidence")
            path.rename(evidence)
            path.mkdir()
            replacement = path / "sentinel"
            replacement.write_text("unrelated\n", encoding="utf-8")
        return original(path, identity, members, require_exact_members)

    monkeypatch.setattr(
        codex_instruct,
        "_safe_remove_owned_directory",
        replace_before_cleanup,
    )

    with pytest.raises(SystemExit) as caught:
        codex_instruct.uninstall([str(codex_dir)], yes=True)

    assert caught.value.code == 1
    assert replacement is not None
    assert replacement.read_text(encoding="utf-8") == "unrelated\n"


def test_repeated_deployment_uninstalls_one_owned_layer_at_a_time(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    first_manifest = (codex_dir / codex_instruct.MANIFEST_FILENAME).read_bytes()
    _deploy(codex_dir)

    first_uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert first_uninstall.returncode == 0
    assert (codex_dir / codex_instruct.MANIFEST_FILENAME).read_bytes() == first_manifest
    assert (codex_dir / "gpt-unrestricted.md").exists()

    second_uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert second_uninstall.returncode == 0
    assert not (codex_dir / codex_instruct.MANIFEST_FILENAME).exists()
    assert not (codex_dir / "gpt-unrestricted.md").exists()


@pytest.mark.parametrize("target", ["config", "md", "hooks"])
def test_uninstall_fails_closed_on_managed_path_drift(tmp_path, target):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hooks\n", encoding="utf-8")
    _deploy(codex_dir)
    before = _snapshot_files(codex_dir)
    if target == "config":
        path = codex_dir / "config.toml"
    elif target == "md":
        path = codex_dir / "gpt-unrestricted.md"
    else:
        path = codex_dir / "hooks.json.disabled"
    path.write_bytes(path.read_bytes() + b"drift\n")
    drifted = _snapshot_files(codex_dir)

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 1
    assert "已漂移" in result.stdout
    assert _snapshot_files(codex_dir) == drifted
    assert before != drifted


def test_uninstall_uses_portable_ownership_not_inode_only(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    _deploy(codex_dir)
    md_path = codex_dir / "gpt-unrestricted.md"
    original_stat = md_path.stat()
    replacement = tmp_path / "replacement.md"
    shutil.copy2(md_path, replacement)
    os.replace(replacement, md_path)
    assert md_path.stat().st_ino != original_stat.st_ino

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert not md_path.exists()


@pytest.mark.parametrize("kind", ["invalid", "unsafe", "symlink"])
def test_uninstall_rejects_invalid_or_symlink_manifest(tmp_path, kind):
    codex_dir = _make_codex_dir(tmp_path)
    manifest = codex_dir / codex_instruct.MANIFEST_FILENAME
    if kind == "invalid":
        manifest.write_text("{not json", encoding="utf-8")
    elif kind == "unsafe":
        _deploy(codex_dir)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["config"]["backup"] = "config.toml"
        manifest.write_text(json.dumps(data), encoding="utf-8")
    else:
        target = tmp_path / "outside.json"
        target.write_text("{}", encoding="utf-8")
        try:
            manifest.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation is unavailable: {exc}")

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 1
    assert manifest.exists() or manifest.is_symlink()


def test_multi_directory_uninstall_failure_rolls_back_prior_directory(
    tmp_path,
    monkeypatch,
):
    first = _make_codex_dir(tmp_path, "first")
    second = _make_codex_dir(tmp_path, "second")
    for directory in (first, second):
        _deploy(directory)
    before = {directory: _snapshot_files(directory) for directory in (first, second)}
    real_execute = codex_instruct._execute_uninstall_state

    def fail_second(state, timestamp):
        if state.plan.codex_dir == second:
            raise OSError("simulated second-directory failure")
        return real_execute(state, timestamp)

    monkeypatch.setattr(codex_instruct, "_execute_uninstall_state", fail_second)

    with pytest.raises(SystemExit) as exit_info:
        codex_instruct.uninstall([str(first), str(second)], yes=True)

    assert exit_info.value.code == 1
    assert _snapshot_files(first) == before[first]
    assert _snapshot_files(second) == before[second]
    assert not list(first.glob(f"{codex_instruct.MANIFEST_FILENAME}.uninstalled_*"))
    assert not list(second.glob(f"{codex_instruct.MANIFEST_FILENAME}.uninstalled_*"))
    assert not list(first.glob(".keysmith-uninstall-*"))
    assert not list(second.glob(".keysmith-uninstall-*"))


def test_uninstall_without_manifest_is_successful_noop(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    before = _snapshot_files(codex_dir)

    result = _run("--codex-dir", codex_dir, "--uninstall", "--yes")

    assert result.returncode == 0
    assert "无需卸载" in result.stdout
    assert _snapshot_files(codex_dir) == before

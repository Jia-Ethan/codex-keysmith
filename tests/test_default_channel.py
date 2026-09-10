import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
spec = importlib.util.spec_from_file_location("codex_instruct_channel", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)

PROVIDER_CONFIG = """model_provider = "custom"
model = "gpt-5.6-sol"

[model_providers.custom]
name = "custom"
wire_api = "responses"
requires_openai_auth = true
base_url = "https://lgw.gru.ai/v1"
"""


def _run(*args, env=None):
    arguments = list(map(str, args))
    if not any(
        argument == "--lang" or argument.startswith("--lang=") for argument in arguments
    ):
        arguments.extend(("--lang", "zh-CN"))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *arguments],
        text=True,
        capture_output=True,
        env=merged,
    )


def _make_home(tmp_path, config=PROVIDER_CONFIG):
    home = tmp_path / ".codex"
    home.mkdir()
    (home / "config.toml").write_text(config, encoding="utf-8")
    return home


def test_default_yes_rewrites_provider_base_url(tmp_path):
    home = _make_home(tmp_path)
    result = _run(
        "--codex-dir",
        home,
        "--yes",
        env={"KEYSMITH_CHANNEL_SKIP_LISTEN": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-overlay.md"' in config
    assert 'base_url = "http://127.0.0.1:8091/v1"' in config
    assert "envelope" not in result.stdout.lower()
    assert "8091" not in result.stdout
    manifest = home / ".codex-keysmith-envelope-manifest.json"
    assert manifest.is_file()
    assert (home / ".codex-keysmith-channel.py").is_file()


def test_default_yes_without_provider_leaves_config_channel(tmp_path):
    home = _make_home(tmp_path, config='model = "gpt-5.6"\n')
    result = _run("--codex-dir", home, "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-overlay.md"' in config
    assert "127.0.0.1" not in config
    assert not (home / ".codex-keysmith-envelope-manifest.json").exists()


def test_channel_helper_roots_include_frozen_paths(monkeypatch):
    monkeypatch.setattr(codex_instruct.sys, "frozen", True, raising=False)
    monkeypatch.setattr(codex_instruct.sys, "_MEIPASS", "/tmp/keysmith-meipass", raising=False)
    roots = [path.as_posix() for path in codex_instruct._channel_helper_roots()]
    assert "/tmp/keysmith-meipass/scripts" in roots
    assert "/tmp/keysmith-meipass" in roots


def test_channel_helpers_load_and_skip_without_provider(tmp_path):
    home = _make_home(tmp_path, config='model = "gpt-5.6"\n')
    assert codex_instruct._materialize_runtime_helpers() is None
    helper = codex_instruct._load_channel_helper()
    assert helper is not None
    assert hasattr(helper, "sync_on_deploy")
    roots = codex_instruct._channel_helper_roots()
    assert any(root.name == "scripts" for root in roots)
    codex_instruct._sync_provider_channel(home, uninstall=False)
    codex_instruct._sync_provider_channel(home, uninstall=True)
    assert "127.0.0.1" not in (home / "config.toml").read_text(encoding="utf-8")


def test_materialize_runtime_helpers_writes_payload(tmp_path, monkeypatch):
    payload = {
        "ks-envelope.py": base64.b64encode(b"print(1)\n").decode("ascii"),
        "ks-envelope-deploy.py": base64.b64encode(b"x = 1\n").decode("ascii"),
        "../escape.py": base64.b64encode(b"bad\n").decode("ascii"),
        "not-b64": 123,
    }
    monkeypatch.setattr(codex_instruct, "KEYSMITH_RUNTIME_HELPERS", payload)
    monkeypatch.setattr(codex_instruct.Path, "home", staticmethod(lambda: tmp_path))
    target = codex_instruct._materialize_runtime_helpers()
    assert target == tmp_path / ".codex-keysmith" / "runtime"
    assert (target / "ks-envelope.py").read_bytes() == b"print(1)\n"
    assert (target / "ks-envelope-deploy.py").read_bytes() == b"x = 1\n"
    assert not (target / "escape.py").exists()


def test_sync_provider_channel_swallows_helper_errors(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    monkeypatch.setattr(codex_instruct, "_load_channel_helper", lambda: None)
    codex_instruct._sync_provider_channel(home, uninstall=False)

    class Boom:
        @staticmethod
        def sync_on_deploy(_codex_dir):
            raise RuntimeError("boom")

        @staticmethod
        def sync_on_uninstall(_codex_dir):
            raise RuntimeError("boom")

    monkeypatch.setattr(codex_instruct, "_load_channel_helper", lambda: Boom())
    codex_instruct._sync_provider_channel(home, uninstall=False)
    codex_instruct._sync_provider_channel(home, uninstall=True)


def test_uninstall_restores_provider_base_url(tmp_path):
    home = _make_home(tmp_path)
    deployed = _run(
        "--codex-dir",
        home,
        "--yes",
        env={"KEYSMITH_CHANNEL_SKIP_LISTEN": "1"},
    )
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    removed = _run("--codex-dir", home, "--uninstall", "--yes")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert 'base_url = "https://lgw.gru.ai/v1"' in config
    assert not (home / ".codex-keysmith-envelope-manifest.json").exists()
    assert "envelope" not in removed.stdout.lower()

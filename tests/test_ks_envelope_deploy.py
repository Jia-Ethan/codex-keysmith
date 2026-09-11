"""Tests for ks-envelope-deploy.py (envelope-mode deployment manager).

Sandbox tests against fixture config.toml files: deploy rewrites only the
provider base_url (all other lines preserved byte-for-byte), records a
manifest with the original URL, refuses double-deploy, and restore puts
the original base_url back exactly.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEPLOY_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "ks-envelope-deploy.py"
)

FIXTURE = """model_provider = "custom"
model = "gpt-5.6-sol"

[model_providers.custom]
name = "custom"
wire_api = "responses"
requires_openai_auth = true
base_url = "https://lgw.gru.ai/v1"

[features]
multi_agent = true
"""


class Sandbox:
    def __init__(self, fixture=FIXTURE):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "codex-home"
        self.home.mkdir()
        (self.home / "config.toml").write_text(fixture)

    def run(self, *args, **kw):
        return subprocess.run(
            [sys.executable, str(DEPLOY_SCRIPT), *args],
            capture_output=True, text=True, **kw,
        )

    def config(self):
        return (self.home / "config.toml").read_text()

    def manifest(self):
        p = self.home / ".codex-keysmith-envelope-manifest.json"
        return json.loads(p.read_text()) if p.exists() else None

    def cleanup(self):
        self._td.cleanup()


def test_deploy_rewrites_only_base_url():
    sb = Sandbox()
    try:
        r = sb.run("deploy", "--codex-home", str(sb.home), "--port", "8099")
        assert r.returncode == 0, r.stderr
        cfg = sb.config()
        assert 'base_url = "http://127.0.0.1:8099/v1"' in cfg
        assert "wire_api" in cfg and "multi_agent" in cfg and 'name = "custom"' in cfg
        m = sb.manifest()
        assert m["original_base_url"] == "https://lgw.gru.ai/v1"
        assert m["envelope_base_url"] == "http://127.0.0.1:8099/v1"
        assert m["provider"] == "custom"
        assert m["port"] == 8099
        # no model_instructions_file written anywhere
        assert "model_instructions_file" not in cfg
    finally:
        sb.cleanup()


def test_double_deploy_refused():
    sb = Sandbox()
    try:
        assert sb.run("deploy", "--codex-home", str(sb.home)).returncode == 0
        r = sb.run("deploy", "--codex-home", str(sb.home))
        assert r.returncode == 2
        assert "restore first" in r.stderr
    finally:
        sb.cleanup()


def test_deploy_idempotent_url_guard():
    sb = Sandbox()
    try:
        assert sb.run("deploy", "--codex-home", str(sb.home)).returncode == 0
        sb.cleanup.__self__  # noqa
        # simulate an already-pointing config: restore, then hand-edit
        assert sb.run("restore", "--codex-home", str(sb.home), "--yes").returncode == 0
        cfg = sb.config().replace(
            "https://lgw.gru.ai/v1", "http://127.0.0.1:8091/v1"
        )
        (sb.home / "config.toml").write_text(cfg)
        r = sb.run("deploy", "--codex-home", str(sb.home), "--port", "8091")
        assert r.returncode == 2
        assert "nothing to do" in r.stderr
    finally:
        sb.cleanup()


def test_restore_exact():
    sb = Sandbox()
    try:
        assert sb.run("deploy", "--codex-home", str(sb.home), "--port", "8091").returncode == 0
        time.sleep(1.1)  # distinct backup timestamps
        r = sb.run("restore", "--codex-home", str(sb.home), "--yes")
        assert r.returncode == 0, r.stderr
        cfg = sb.config()
        assert 'base_url = "https://lgw.gru.ai/v1"' in cfg
        assert "multi_agent = true" in cfg
        assert sb.manifest() is None
    finally:
        sb.cleanup()


def test_restore_without_manifest_is_noop():
    sb = Sandbox()
    try:
        r = sb.run("restore", "--codex-home", str(sb.home), "--yes")
        assert r.returncode == 0
        assert "nothing to restore" in r.stdout
    finally:
        sb.cleanup()


def test_status_reports_direct_mode():
    sb = Sandbox()
    try:
        r = sb.run("status", "--codex-home", str(sb.home))
        assert r.returncode == 0
        assert "mode:     direct" in r.stdout
        assert "https://lgw.gru.ai/v1" in r.stdout
    finally:
        sb.cleanup()


def test_status_reports_envelope_mode():
    sb = Sandbox()
    try:
        assert sb.run("deploy", "--codex-home", str(sb.home), "--port", "8099").returncode == 0
        r = sb.run("status", "--codex-home", str(sb.home))
        assert r.returncode == 0
        assert "mode:     envelope" in r.stdout
        assert "original=https://lgw.gru.ai/v1" in r.stdout
    finally:
        sb.cleanup()


def test_missing_provider_table_errors():
    sb = Sandbox(fixture='model_provider = "ghost"\n\n[features]\nx = true\n')
    try:
        r = sb.run("deploy", "--codex-home", str(sb.home))
        assert r.returncode == 2
        assert "no base_url" in r.stderr
    finally:
        sb.cleanup()


def test_backup_created_on_deploy():
    sb = Sandbox()
    try:
        assert sb.run("deploy", "--codex-home", str(sb.home)).returncode == 0
        baks = list(sb.home.glob("config.toml.bak_*_envelope"))
        assert len(baks) == 1
        assert baks[0].read_text() == FIXTURE
    finally:
        sb.cleanup()


def _load_deploy_module():
    spec = importlib.util.spec_from_file_location(
        "ks_envelope_deploy_under_test", DEPLOY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_on_deploy_skips_homes_without_provider():
    sb = Sandbox(fixture='model = "gpt-5.6"\n')
    helper = _load_deploy_module()
    try:
        assert helper.sync_on_deploy(sb.home) is False
        assert sb.config() == 'model = "gpt-5.6"\n'
        assert sb.manifest() is None
    finally:
        sb.cleanup()


def test_sync_on_deploy_rewrites_when_listener_ok(monkeypatch):
    sb = Sandbox()
    helper = _load_deploy_module()
    monkeypatch.setattr(helper, "ensure_listener", lambda *args, **kwargs: True)
    try:
        assert helper.sync_on_deploy(sb.home, port=8099) is True
        cfg = sb.config()
        assert 'base_url = "http://127.0.0.1:8099/v1"' in cfg
        assert "wire_api" in cfg
        m = sb.manifest()
        assert m["original_base_url"] == "https://lgw.gru.ai/v1"
        assert m["port"] == 8099
        assert (sb.home / helper.RUNTIME_SCRIPT_NAME).is_file()
    finally:
        sb.cleanup()


def test_sync_on_deploy_restores_when_listener_fails(monkeypatch):
    sb = Sandbox()
    helper = _load_deploy_module()
    monkeypatch.setattr(helper, "ensure_listener", lambda *args, **kwargs: False)
    try:
        assert helper.sync_on_deploy(sb.home, port=8099) is False
        assert 'base_url = "https://lgw.gru.ai/v1"' in sb.config()
        assert sb.manifest() is None
    finally:
        sb.cleanup()


def test_sync_on_uninstall_restores_original_url(monkeypatch):
    sb = Sandbox()
    helper = _load_deploy_module()
    monkeypatch.setattr(helper, "ensure_listener", lambda *args, **kwargs: True)
    try:
        assert helper.sync_on_deploy(sb.home, port=8099) is True
        helper.sync_on_uninstall(sb.home)
        assert 'base_url = "https://lgw.gru.ai/v1"' in sb.config()
        assert sb.manifest() is None
    finally:
        sb.cleanup()


def test_agent_plist_defaults_to_repo_script_for_backcompat():
    helper = _load_deploy_module()
    text = helper.agent_plist(8091, "https://lgw.gru.ai/v1", None)
    assert str(helper.SCRIPT_DIR / helper.HELPER_SCRIPT_NAME) in text
    assert "com.jia.codex-keysmith.envelope" in text


def test_agent_plist_uses_runtime_script_and_overlay():
    helper = _load_deploy_module()
    runtime = Path("/Users/me/.codex/.codex-keysmith-channel.py")
    overlay = Path("/Users/me/.codex/.codex-keysmith-overlay.md")
    text = helper.agent_plist(
        8091, "https://lgw.gru.ai/v1", overlay, script=runtime
    )
    assert str(runtime) in text
    assert str(overlay) in text
    assert "--overlay-file" in text
    assert str(helper.SCRIPT_DIR / helper.HELPER_SCRIPT_NAME) not in text


def test_copy_runtime_overlay_writes_codex_home_copy(tmp_path):
    helper = _load_deploy_module()
    src = tmp_path / "gpt-overlay.md"
    src.write_text("overlay-bytes\n", encoding="utf-8")
    dest = helper.copy_runtime_overlay(tmp_path, src)
    assert dest == tmp_path / helper.RUNTIME_OVERLAY_NAME
    assert dest.read_text(encoding="utf-8") == "overlay-bytes\n"


def test_ensure_listener_rejects_foreign_listener(monkeypatch, tmp_path):
    helper = _load_deploy_module()
    monkeypatch.setattr(helper, "sys", type("S", (), {"platform": "linux"})())
    monkeypatch.setattr(
        helper, "_listener_is_ours", lambda port, script=None, overlay=None: False
    )
    evict_calls = []
    spawn_calls = []
    monkeypatch.setattr(
        helper, "_evict_envelope_listener", lambda port: evict_calls.append(port)
    )
    monkeypatch.setattr(
        helper, "_install_launch_agent", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not touch LaunchAgent")
        ),
    )

    def fake_spawn(*a, **k):
        spawn_calls.append((a, k))
        return None

    monkeypatch.setattr(helper, "_spawn_helper", fake_spawn)
    # adopt check True, evict check True, post-spawn False.
    health_values = iter([True, True, False])
    monkeypatch.setattr(helper, "probe_health", lambda port: next(health_values))
    assert helper.ensure_listener(
        8099, "https://lgw.gru.ai/v1", tmp_path / "s.py", None, tmp_path
    ) is False
    assert evict_calls == [8099]
    assert spawn_calls, "foreign listener must not be adopted; spawn must run"


def test_ensure_listener_adopts_own_listener(monkeypatch, tmp_path):
    helper = _load_deploy_module()
    monkeypatch.setattr(helper, "probe_health", lambda port: True)
    monkeypatch.setattr(
        helper, "_listener_is_ours", lambda port, script=None, overlay=None: True
    )
    spawn_calls = []
    monkeypatch.setattr(
        helper, "_spawn_helper",
        lambda *a, **k: spawn_calls.append(a) or 12345,
    )
    monkeypatch.setattr(
        helper, "_install_launch_agent", lambda *a, **k: spawn_calls.append("launch")
    )
    assert helper.ensure_listener(
        8099, "https://lgw.gru.ai/v1", tmp_path / "s.py", None, tmp_path
    ) is True
    assert not spawn_calls, "own healthy listener must be adopted, not respawned"


def test_listener_is_ours_rejects_non_envelope(monkeypatch):
    helper = _load_deploy_module()

    def fake_run(argv, **_k):
        stdout = "4242\n" if argv and argv[0] == "lsof" else (
            "/usr/bin/someOtherServer --port 8091\n"
        )
        return type("R", (), {"stdout": stdout, "returncode": 0, "stderr": ""})()

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper._listener_is_ours(8091) is False


def test_listener_is_ours_rejects_overlay_leftover(monkeypatch, tmp_path):
    helper = _load_deploy_module()
    script = tmp_path / helper.RUNTIME_SCRIPT_NAME
    leftover = (
        f"python3 {script} --port 8091 --overlay-file /tmp/ks-e2e/overlay.md\n"
    )

    def fake_run(argv, **_k):
        stdout = "4242\n" if argv and argv[0] == "lsof" else leftover
        return type("R", (), {"stdout": stdout, "returncode": 0, "stderr": ""})()

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper._listener_is_ours(8091, script=script, overlay=None) is False
    assert helper._listener_is_ours(
        8091, script=script, overlay=Path("/tmp/ks-e2e/overlay.md")
    ) is True


def test_listener_is_ours_requires_expected_script(monkeypatch, tmp_path):
    helper = _load_deploy_module()
    runtime = tmp_path / helper.RUNTIME_SCRIPT_NAME
    checkout = tmp_path / "scripts" / "ks-envelope.py"

    def fake_run(argv, **_k):
        stdout = (
            "4242\n" if argv and argv[0] == "lsof"
            else f"python3 {checkout} --port 8091\n"
        )
        return type("R", (), {"stdout": stdout, "returncode": 0, "stderr": ""})()

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper._listener_is_ours(8091, script=runtime) is False
    assert helper._listener_is_ours(8091, script=checkout) is True

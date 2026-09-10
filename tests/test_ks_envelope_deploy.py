"""Tests for ks-envelope-deploy.py (envelope-mode deployment manager).

Sandbox tests against fixture config.toml files: deploy rewrites only the
provider base_url (all other lines preserved byte-for-byte), records a
manifest with the original URL, refuses double-deploy, and restore puts
the original base_url back exactly.
"""

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

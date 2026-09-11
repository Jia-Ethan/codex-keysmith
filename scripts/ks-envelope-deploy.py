#!/usr/bin/env python3
"""ks-envelope-deploy — envelope-mode deployment manager for keysmith.

Envelope mode keeps the stock Codex base prompt untouched: instead of
model_instructions_file (full replacement), it points the provider's
base_url at a loopback ks-envelope instance and (optionally) injects the
keysmith overlay contract from the envelope side via --overlay-file.

What deploy does:
- backs up config.toml (timestamped .bak) next to the original
- rewrites [model_providers.<provider>] base_url to the loopback envelope
- records the previous base_url + provider in a manifest for exact restore

What restore does:
- puts the original base_url back from the manifest (no guessing)

LaunchAgent management (macOS):
- install/uninstall com.jia.codex-keysmith.envelope.plist running
  ks-envelope against the real upstream with the overlay file.

Engine: Python 3.9+ | Language: Python
Run:  python3 scripts/ks-envelope-deploy.py deploy   --codex-home ~/.codex --port 8091 --overlay examples/gpt-overlay.md
      python3 scripts/ks-envelope-deploy.py status   --codex-home ~/.codex
      python3 scripts/ks-envelope-deploy.py restore  --codex-home ~/.codex --yes
      python3 scripts/ks-envelope-deploy.py agent install|uninstall|status [--port 8091] [--overlay PATH]
Deps: none (stdlib only)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_NAME = ".codex-keysmith-envelope-manifest.json"
LAUNCH_AGENT_LABEL = "com.jia.codex-keysmith.envelope"
DEFAULT_PORT = 8091
DEFAULT_UPSTREAM = "https://lgw.gru.ai/v1"
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_SCRIPT_NAME = ".codex-keysmith-channel.py"
RUNTIME_OVERLAY_NAME = ".codex-keysmith-overlay.md"
RUNTIME_PID_NAME = ".codex-keysmith-channel.pid"
HELPER_SCRIPT_NAME = "ks-envelope.py"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

ProviderConflict = build_error = ValueError  # alias for readability below


class DeployError(Exception):
    """Deploy/restore failure with a user-facing message."""


# --- config.toml surgery (line-oriented, comments preserved) ------------------

_PROVIDER_TABLE_RE = re.compile(r"^\s*\[model_providers\.([A-Za-z0-9_.-]+)\]")
_BASE_URL_RE = re.compile(r'^(\s*base_url\s*=\s*")(.*?)(")')
_INSTRUCTIONS_RE = re.compile(r'^(\s*model_instructions_file\s*=\s*")(.*?)(")')
UNSTACK_PREFIX = "# keysmith-envelope-unstack: "


def find_provider_base_url(lines: List[str], provider: str) -> Optional[Tuple[int, str]]:
    """Return (line_index, url) of the provider's base_url, or None."""
    in_table = False
    for i, line in enumerate(lines):
        m = _PROVIDER_TABLE_RE.match(line)
        if m:
            in_table = m.group(1) == provider
            continue
        if line.strip().startswith("["):
            in_table = False
            continue
        if in_table:
            bm = _BASE_URL_RE.match(line)
            if bm:
                return i, bm.group(2)
    return None


def find_active_provider(lines: List[str]) -> Optional[str]:
    """Top-level model_provider = "name"."""
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            break
        match = re.fullmatch(r"model_provider\s*=\s*(\"(?:[^\"\\]|\\.)*\"|'[^']*')\s*(?:#.*)?", s)
        if match:
            value = match.group(1)
            return json.loads(value) if value.startswith('"') else value[1:-1]
    return None


def park_model_instructions(lines: List[str]) -> Tuple[List[str], Optional[str]]:
    """Comment out a live top-level model_instructions_file so envelope
    append keeps the stock prompt. Returns (lines, parked value)."""
    parked: Optional[str] = None
    new_lines = list(lines)
    for i, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.startswith("["):
            break
        if stripped.startswith("#"):
            continue
        match = _INSTRUCTIONS_RE.match(line)
        if match:
            parked = match.group(2)
            new_lines[i] = UNSTACK_PREFIX + line
            break
    return new_lines, parked


def unpark_model_instructions(lines: List[str]) -> List[str]:
    restored = []
    for line in lines:
        if line.startswith(UNSTACK_PREFIX):
            restored.append(line[len(UNSTACK_PREFIX):])
        else:
            restored.append(line)
    return restored


def set_provider_base_url(lines: List[str], provider: str, new_url: str) -> List[str]:
    hit = find_provider_base_url(lines, provider)
    if hit is None:
        raise DeployError(
            f"provider [model_providers.{provider}] has no base_url to rewrite; "
            "refusing to guess"
        )
    i, _ = hit
    m = _BASE_URL_RE.match(lines[i])
    lines[i] = f'{m.group(1)}{new_url}{m.group(3)}'
    return lines


def read_manifest(codex_home: Path) -> Optional[Dict[str, Any]]:
    p = codex_home / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DeployError(f"manifest unreadable: {p}: {exc}") from exc


def write_manifest(codex_home: Path, data: Dict[str, Any]) -> None:
    p = codex_home / MANIFEST_NAME
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    p.chmod(0o600)


def backup_config(config: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak = config.with_name(f"config.toml.bak_{stamp}_{uuid.uuid4().hex}_envelope")
    with bak.open("x", encoding="utf-8") as fp:
        fp.write(config.read_text(encoding="utf-8"))
    bak.chmod(0o600)
    return bak


def load_config_lines(config: Path) -> List[str]:
    if not config.is_file():
        raise DeployError(f"config.toml not found: {config}")
    return config.read_text(encoding="utf-8").splitlines()


def save_config_lines(config: Path, lines: List[str]) -> None:
    tmp = config.with_name(config.name + ".keysmith-envelope.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(config)


# --- actions -------------------------------------------------------------------

def cmd_deploy(args: argparse.Namespace) -> int:
    codex_home = Path(args.codex_home).expanduser()
    config = codex_home / "config.toml"
    lines = load_config_lines(config)

    provider = args.provider or find_active_provider(lines)
    if not provider:
        raise DeployError(
            "no active model_provider found in config.toml; pass --provider"
        )
    existing = read_manifest(codex_home)
    if existing and not args.force:
        raise DeployError(
            "envelope manifest already present (already deployed?); "
            "run restore first or pass --force"
        )

    hit = find_provider_base_url(lines, provider)
    if hit is None:
        raise DeployError(f"provider [model_providers.{provider}] has no base_url")
    _, original_url = hit

    envelope_url = f"http://127.0.0.1:{args.port}/v1"
    if original_url == envelope_url:
        raise DeployError(
            f"provider {provider} already points at {envelope_url}; nothing to do"
        )

    bak = backup_config(config)
    new_lines = set_provider_base_url(lines, provider, envelope_url)
    new_lines, parked = park_model_instructions(new_lines)
    save_config_lines(config, new_lines)
    write_manifest(
        codex_home,
        {
            "schema": 1,
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "provider": provider,
            "original_base_url": original_url,
            "envelope_base_url": envelope_url,
            "port": args.port,
            "overlay": str(Path(args.overlay).resolve()) if args.overlay else None,
            "parked_model_instructions_file": parked,
            "config_backup": str(bak),
        },
    )
    print(f"deployed: {provider} base_url -> {envelope_url}")
    print(f"  original: {original_url}")
    print(f"  backup:   {bak}")
    if args.overlay:
        print(f"  overlay:  {args.overlay} (pass --overlay-file to ks-envelope)")
    if parked:
        print(f"  parked:   model_instructions_file ({parked})")
    print("  stock base prompt kept (replacement field parked, overlay appends)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    codex_home = Path(args.codex_home).expanduser()
    config = codex_home / "config.toml"
    manifest = read_manifest(codex_home)
    if manifest is None:
        print("no envelope manifest found; nothing to restore")
        return 0
    provider = manifest.get("provider")
    original = manifest.get("original_base_url")
    if not provider or not original:
        raise DeployError("manifest is missing provider/original_base_url; restore manually")
    if not args.yes:
        print(f"will restore [model_providers.{provider}] base_url to {original}")
        answer = input("proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("aborted")
            return 1
    lines = load_config_lines(config)
    hit = find_provider_base_url(lines, provider)
    if hit is None:
        raise DeployError(
            f"provider [model_providers.{provider}] no longer has a base_url; "
            "restore manually from " + str(manifest.get("config_backup"))
        )
    _check_restore_url(hit[1], manifest)
    backup_config(config)
    new_lines = set_provider_base_url(lines, provider, original)
    new_lines = unpark_model_instructions(new_lines)
    save_config_lines(config, new_lines)
    (codex_home / MANIFEST_NAME).unlink()
    print(f"restored: {provider} base_url -> {original}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    codex_home = Path(args.codex_home).expanduser()
    config = codex_home / "config.toml"
    manifest = read_manifest(codex_home)
    if not config.is_file():
        print(f"config.toml not found: {config}")
        return 1
    lines = load_config_lines(config)
    provider = args.provider or find_active_provider(lines) or "(none)"
    hit = find_provider_base_url(lines, provider) if provider != "(none)" else None
    current = hit[1] if hit else "(no base_url)"
    envelope_active = bool(current and current.startswith("http://127.0.0.1:"))
    print(f"provider: {provider}")
    print(f"base_url: {current}")
    print(f"mode:     {'envelope' if envelope_active else 'direct'}")
    if manifest:
        print(f"manifest: original={manifest.get('original_base_url')} "
              f"port={manifest.get('port')} overlay={manifest.get('overlay')}")
    else:
        print("manifest: (none — envelope mode not deployed by this tool)")
    if envelope_active:
        port = manifest.get("port", DEFAULT_PORT) if manifest else DEFAULT_PORT
        healthy = probe_health(port)
        print(f"envelope health (127.0.0.1:{port}): {'ok' if healthy else 'DOWN'}")
    return 0


def probe_health(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=3
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def _listen_pids(port: int) -> Optional[List[str]]:
    """PIDs listening on the loopback port, or None if lsof cannot say."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _pid_command(pid: str) -> str:
    try:
        return subprocess.run(
            ["ps", "-o", "command=", "-p", pid],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _cmd_is_envelope(cmd: str) -> bool:
    return bool(cmd) and ("ks-envelope.py" in cmd or RUNTIME_SCRIPT_NAME in cmd)


def _cmd_contains(cmd: str, token: str) -> bool:
    """Path tokens in ps/lsof output may use either slash."""
    if not token:
        return False
    if token in cmd:
        return True
    return token.replace("\\", "/") in cmd.replace("\\", "/")


def _listener_is_ours(
    port: int,
    script: Optional[Path] = None,
    overlay: Optional[Path] = None,
) -> bool:
    """True only when the occupant is this install's helper.

    A leftover ``ks-envelope.py --overlay-file …`` from an aborted e2e run
    still contains ``ks-envelope.py``; substring-only matching would adopt
    it. Missing lsof stays fail-open (same as a successful health probe).
    """
    pids = _listen_pids(port)
    if pids is None or not pids:
        return True
    expected_script = str(script) if script is not None else None
    expected_overlay = str(overlay) if overlay is not None else None
    for pid in pids:
        cmd = _pid_command(pid)
        if not _cmd_is_envelope(cmd):
            continue
        if expected_script is not None and not _cmd_contains(cmd, expected_script):
            continue
        has_overlay = "--overlay-file" in cmd
        if expected_overlay is None and has_overlay:
            continue
        if expected_overlay is not None and not _cmd_contains(cmd, expected_overlay):
            continue
        return True
    return False


def _evict_envelope_listener(port: int) -> None:
    """SIGTERM envelope-shaped listeners only; leave unrelated occupants."""
    pids = _listen_pids(port)
    if not pids:
        return
    for pid in pids:
        cmd = _pid_command(pid)
        if not _cmd_is_envelope(cmd):
            continue
        try:
            os.kill(int(pid), 15)
        except (OSError, ValueError):
            pass


def _python_for_helper() -> str:
    if getattr(sys, "frozen", False):
        return shutil.which("python3") or shutil.which("python") or "/usr/bin/python3"
    return sys.executable or "/usr/bin/python3"


def resolve_helper_script() -> Optional[Path]:
    roots: List[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass) / "scripts")
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).resolve().parent / "scripts")
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(SCRIPT_DIR)
    roots.append(SCRIPT_DIR.parent)
    for root in roots:
        candidate = root / HELPER_SCRIPT_NAME
        if candidate.is_file():
            return candidate
    return None


def copy_runtime_script(codex_home: Path) -> Path:
    src = resolve_helper_script()
    if src is None:
        raise DeployError("runtime helper is missing")
    dest = codex_home / RUNTIME_SCRIPT_NAME
    data = src.read_bytes()
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)
        dest.chmod(0o700)
    return dest


def copy_runtime_overlay(codex_home: Path, overlay: Path) -> Path:
    dest = codex_home / RUNTIME_OVERLAY_NAME
    data = overlay.read_bytes()
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)
        dest.chmod(0o600)
    return dest


def _spawn_helper(
    script: Path,
    port: int,
    upstream: str,
    auth_file: Optional[Path],
    log_dir: Path,
    overlay: Optional[Path] = None,
) -> Optional[int]:
    log_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        _python_for_helper(),
        str(script),
        "--port",
        str(port),
        "--upstream",
        upstream,
    ]
    if overlay is not None:
        argv.extend(["--overlay-file", str(overlay)])
    if auth_file is not None:
        argv.extend(["--auth-file", str(auth_file)])
    out = (log_dir / "ks-envelope.out.log").open("ab")
    err = (log_dir / "ks-envelope.err.log").open("ab")
    kwargs: Dict[str, Any] = {
        "stdout": out,
        "stderr": err,
        "cwd": str(script.parent),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    finally:
        out.close()
        err.close()
    return proc.pid


def ensure_listener(
    port: int,
    upstream: str,
    script: Path,
    auth_file: Optional[Path],
    log_dir: Path,
    overlay: Optional[Path] = None,
) -> bool:
    if os.environ.get("KEYSMITH_CHANNEL_SKIP_LISTEN") == "1":
        return True

    def listener_is_current() -> bool:
        return _listener_is_ours(port, script=script, overlay=overlay)

    if probe_health(port) and listener_is_current():
        return True
    if probe_health(port):
        _evict_envelope_listener(port)
        time.sleep(0.3)
    if sys.platform == "darwin":
        try:
            _install_launch_agent(
                port, upstream, script, auth_file, log_dir, overlay=overlay
            )
        except Exception:
            pass
        time.sleep(0.5)
        if probe_health(port) and listener_is_current():
            return True
    pid = _spawn_helper(script, port, upstream, auth_file, log_dir, overlay=overlay)
    if pid:
        pid_path = script.parent / RUNTIME_PID_NAME
        pid_path.write_text(str(pid) + "\n", encoding="utf-8")
        pid_path.chmod(0o600)
    time.sleep(0.5)
    return bool(probe_health(port) and listener_is_current())


def _stop_spawned_helper(codex_home: Path) -> None:
    pid_path = codex_home / RUNTIME_PID_NAME
    if not pid_path.is_file():
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass
    try:
        pid_path.unlink()
    except OSError:
        pass


def _check_restore_url(current: str, manifest: Dict[str, Any]) -> None:
    if current not in (manifest.get("original_base_url"), manifest.get("envelope_base_url")):
        raise DeployError("provider base_url changed after deployment; preserving config and manifest")


def restore_provider_url(codex_home: Path) -> None:
    config = codex_home / "config.toml"
    manifest = read_manifest(codex_home)
    if manifest is None or not config.is_file():
        return
    provider = manifest.get("provider")
    original = manifest.get("original_base_url")
    if not provider or not original:
        return
    lines = load_config_lines(config)
    hit = find_provider_base_url(lines, provider)
    if hit is None:
        return
    _check_restore_url(hit[1], manifest)
    changed = False
    if hit[1] != original:
        lines = set_provider_base_url(lines, provider, original)
        changed = True
    unparked = unpark_model_instructions(lines)
    if unparked != lines:
        lines = unparked
        changed = True
    if changed:
        backup_config(config)
        save_config_lines(config, lines)
    try:
        (codex_home / MANIFEST_NAME).unlink()
    except OSError:
        pass


def sync_on_deploy(codex_home: Path, port: int = DEFAULT_PORT) -> bool:
    """Point the active provider at the loopback helper if a base_url exists.

    Returns True when the helper is listening. Missing provider tables are a
    no-op so ChatGPT-login homes keep working. Listener failure rolls the
    base_url back so Codex is not left pointing at a dead loopback.
    """
    codex_home = Path(codex_home)
    config = codex_home / "config.toml"
    if not config.is_file():
        return False
    lines = load_config_lines(config)
    provider = find_active_provider(lines)
    if not provider:
        return False
    hit = find_provider_base_url(lines, provider)
    if hit is None:
        return False
    _, current_url = hit
    envelope_url = f"http://127.0.0.1:{port}/v1"
    manifest = read_manifest(codex_home)
    already = current_url.startswith("http://127.0.0.1:")
    if already:
        upstream = str((manifest or {}).get("original_base_url") or DEFAULT_UPSTREAM)
        original_url = upstream
    else:
        upstream = current_url
        original_url = current_url
    try:
        script = copy_runtime_script(codex_home)
    except (OSError, DeployError):
        return False
    overlay_path: Optional[Path] = None
    overlay_raw = (manifest or {}).get("overlay")
    if overlay_raw:
        overlay_src = Path(str(overlay_raw)).expanduser()
        if overlay_src.is_file():
            try:
                overlay_path = copy_runtime_overlay(codex_home, overlay_src)
            except OSError:
                overlay_path = None
    auth_candidate = codex_home / "auth.json"
    auth_file = auth_candidate if auth_candidate.is_file() else None
    log_dir = Path.home() / ".codex" / "logs"
    if not already:
        bak = backup_config(config)
        new_lines = set_provider_base_url(list(lines), provider, envelope_url)
        new_lines, parked = park_model_instructions(new_lines)
        save_config_lines(config, new_lines)
        write_manifest(
            codex_home,
            {
                "schema": 1,
                "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "provider": provider,
                "original_base_url": original_url,
                "envelope_base_url": envelope_url,
                "port": port,
                "overlay": overlay_raw if overlay_raw else None,
                "parked_model_instructions_file": parked,
                "config_backup": str(bak),
            },
        )
    else:
        parked_lines, parked = park_model_instructions(list(lines))
        if parked is not None:
            backup_config(config)
            save_config_lines(config, parked_lines)
            if manifest is not None:
                manifest["parked_model_instructions_file"] = parked
                write_manifest(codex_home, manifest)
    if ensure_listener(
        port, upstream, script, auth_file, log_dir, overlay=overlay_path
    ):
        return True
    if not already:
        restore_provider_url(codex_home)
    return False


def _launch_agent_points_at(codex_home: Path) -> bool:
    if not PLIST_PATH.is_file():
        return False
    try:
        text = PLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return str(codex_home / RUNTIME_SCRIPT_NAME) in text


def sync_on_uninstall(codex_home: Path) -> None:
    codex_home = Path(codex_home)
    restore_provider_url(codex_home)
    _stop_spawned_helper(codex_home)
    if sys.platform == "darwin" and _launch_agent_points_at(codex_home):
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        try:
            PLIST_PATH.unlink()
        except OSError:
            pass


# --- LaunchAgent ----------------------------------------------------------------

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{envelope_script}</string>
    <string>--port</string>
    <string>{port}</string>
    <string>--upstream</string>
    <string>{upstream}</string>{extra_args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_dir}/ks-envelope.out.log</string>
  <key>StandardErrorPath</key>
  <string>{log_dir}/ks-envelope.err.log</string>
</dict>
</plist>
"""


def agent_plist(
    port: int,
    upstream: str,
    overlay: Optional[Path],
    script: Optional[Path] = None,
    auth_file: Optional[Path] = None,
    python: Optional[str] = None,
    log_dir: Optional[Path] = None,
) -> str:
    extra_args = ""
    if overlay is not None:
        extra_args += (
            f"\n    <string>--overlay-file</string>"
            f"\n    <string>{overlay}</string>"
        )
    if auth_file is not None:
        extra_args += (
            f"\n    <string>--auth-file</string>"
            f"\n    <string>{auth_file}</string>"
        )
    if log_dir is None:
        log_dir = Path.home() / ".codex" / "logs"
    return PLIST_TEMPLATE.format(
        label=LAUNCH_AGENT_LABEL,
        python=python or sys.executable or "/usr/bin/python3",
        envelope_script=script or (SCRIPT_DIR / HELPER_SCRIPT_NAME),
        port=port,
        upstream=upstream,
        extra_args=extra_args,
        log_dir=log_dir,
    )


def _install_launch_agent(
    port: int,
    upstream: str,
    script: Path,
    auth_file: Optional[Path],
    log_dir: Path,
    overlay: Optional[Path] = None,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PLIST_PATH.is_file():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.write_text(
        agent_plist(
            port,
            upstream,
            overlay=overlay,
            script=script,
            auth_file=auth_file,
            python=_python_for_helper(),
            log_dir=log_dir,
        ),
        encoding="utf-8",
    )
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=False)


def cmd_agent(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        raise DeployError("LaunchAgent management is macOS-only")
    action = args.agent_action
    port = args.port
    if action == "install":
        overlay = Path(args.overlay).expanduser() if args.overlay else None
        if overlay is not None and not overlay.is_file():
            raise DeployError(f"overlay file not found: {overlay}")
        codex_home = Path(args.codex_home).expanduser()
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".codex" / "logs").mkdir(parents=True, exist_ok=True)
        # launchd-spawned python cannot read TCC-protected checkouts.
        script = copy_runtime_script(codex_home)
        overlay_runtime = (
            copy_runtime_overlay(codex_home, overlay.resolve())
            if overlay is not None
            else None
        )
        config = codex_home / "config.toml"
        if config.is_file():
            cfg_lines = load_config_lines(config)
            parked_lines, parked = park_model_instructions(cfg_lines)
            if parked is not None:
                backup_config(config)
                save_config_lines(config, parked_lines)
            manifest = read_manifest(codex_home)
            if manifest is not None:
                if parked is not None:
                    manifest["parked_model_instructions_file"] = parked
                if overlay_runtime is not None:
                    manifest["overlay"] = str(overlay_runtime)
                write_manifest(codex_home, manifest)
        auth_candidate = codex_home / "auth.json"
        auth_file = auth_candidate if auth_candidate.is_file() else None
        existing = PLIST_PATH.is_file()
        if existing:
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.write_text(
            agent_plist(
                port,
                args.upstream,
                overlay_runtime,
                script=script,
                auth_file=auth_file,
                python=_python_for_helper(),
            ),
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
        time.sleep(0.5)
        healthy = probe_health(port)
        print(f"LaunchAgent {'re' if existing else ''}installed: {PLIST_PATH}")
        print(f"envelope health (127.0.0.1:{port}): {'ok' if healthy else 'DOWN (check logs)'}")
        return 0 if healthy else 2
    if action == "uninstall":
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        if PLIST_PATH.is_file():
            PLIST_PATH.unlink()
        print(f"LaunchAgent removed: {PLIST_PATH}")
        return 0
    if action == "status":
        if not PLIST_PATH.is_file():
            print(f"LaunchAgent not installed ({PLIST_PATH})")
            print(f"envelope health (127.0.0.1:{port}): "
                  f"{'ok' if probe_health(port) else 'DOWN'}")
            return 1
        print(f"LaunchAgent installed: {PLIST_PATH}")
        out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, check=False
        ).stdout
        running = any(
            line.split("\t")[-1] == LAUNCH_AGENT_LABEL for line in out.splitlines()
        )
        print(f"launchctl: {'loaded' if running else 'not loaded'}")
        print(f"envelope health (127.0.0.1:{port}): "
              f"{'ok' if probe_health(port) else 'DOWN'}")
        return 0
    raise DeployError(f"unknown agent action: {action}")


# --- CLI ------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="envelope-mode deployment manager (base_url rewrite, stock prompt kept)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_codex_home(p):
        p.add_argument("--codex-home", default=str(Path.home() / ".codex"))

    p = sub.add_parser("deploy", help="point the provider at the loopback envelope")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--provider", help="model_providers key (default: active provider)")
    p.add_argument("--overlay", help="overlay contract path (informational; passed to ks-envelope)")
    p.add_argument("--force", action="store_true")
    add_codex_home(p)
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("restore", help="put the original base_url back from the manifest")
    p.add_argument("--provider", help="model_providers key (default: manifest)")
    p.add_argument("--yes", action="store_true")
    add_codex_home(p)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("status", help="show provider/base_url/mode/envelope health")
    p.add_argument("--provider")
    add_codex_home(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("agent", help="manage the ks-envelope LaunchAgent (macOS)")
    p.add_argument("agent_action", choices=["install", "uninstall", "status"])
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    p.add_argument("--overlay")
    add_codex_home(p)
    p.set_defaults(func=cmd_agent)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_NAME = ".codex-keysmith-envelope-manifest.json"
LAUNCH_AGENT_LABEL = "com.jia.codex-keysmith.envelope"
DEFAULT_PORT = 8091
DEFAULT_UPSTREAM = "https://lgw.gru.ai/v1"
SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_SCRIPT_NAME = ".codex-keysmith-channel.py"
RUNTIME_PID_NAME = ".codex-keysmith-channel.pid"
HELPER_SCRIPT_NAME = "ks-envelope.py"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

ProviderConflict = build_error = ValueError  # alias for readability below


class DeployError(Exception):
    """Deploy/restore failure with a user-facing message."""


# --- config.toml surgery (line-oriented, comments preserved) ------------------

_PROVIDER_TABLE_RE = re.compile(r"^\s*\[model_providers\.([A-Za-z0-9_.-]+)\]")
_BASE_URL_RE = re.compile(r'^(\s*base_url\s*=\s*")(.*?)(")')


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
        if s.startswith("model_provider") and "=" in s:
            return s.split("=", 1)[1].strip().strip('"')
    return None


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
    bak = config.with_name(f"config.toml.bak_{stamp}_envelope")
    bak.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
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
            "config_backup": str(bak),
        },
    )
    print(f"deployed: {provider} base_url -> {envelope_url}")
    print(f"  original: {original_url}")
    print(f"  backup:   {bak}")
    if args.overlay:
        print(f"  overlay:  {args.overlay} (pass --overlay-file to ks-envelope)")
    print("  stock base prompt untouched (no model_instructions_file written)")
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
    backup_config(config)
    new_lines = set_provider_base_url(lines, provider, original)
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


def _listener_is_ours(port: int) -> bool:
    """Whether the process listening on the loopback port is a ks-envelope.

    Guards against reusing an unrelated (or stale e2e-test) listener that
    merely happens to answer /health: a leftover process bound with different
    arguments (e.g. --overlay-file from an aborted test run) would otherwise
    be adopted silently. Best-effort: when lsof is unavailable or reports
    nothing, fall back to trusting the health probe.
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True
    pids = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not pids:
        return True
    for pid in pids:
        try:
            ps = subprocess.run(
                ["ps", "-o", "command=", "-p", pid],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        cmd = ps.strip()
        if cmd and ("ks-envelope.py" in cmd or RUNTIME_SCRIPT_NAME in cmd):
            return True
    return False


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


def _spawn_helper(
    script: Path,
    port: int,
    upstream: str,
    auth_file: Optional[Path],
    log_dir: Path,
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
) -> bool:
    if os.environ.get("KEYSMITH_CHANNEL_SKIP_LISTEN") == "1":
        return True
    if probe_health(port) and _listener_is_ours(port):
        return True
    if sys.platform == "darwin":
        try:
            _install_launch_agent(port, upstream, script, auth_file, log_dir)
        except Exception:
            pass
        time.sleep(0.5)
        if probe_health(port):
            return True
    pid = _spawn_helper(script, port, upstream, auth_file, log_dir)
    if pid:
        pid_path = script.parent / RUNTIME_PID_NAME
        pid_path.write_text(str(pid) + "\n", encoding="utf-8")
        pid_path.chmod(0o600)
    time.sleep(0.5)
    return probe_health(port)


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
    if hit[1] != original:
        backup_config(config)
        save_config_lines(config, set_provider_base_url(lines, provider, original))
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
    auth_candidate = codex_home / "auth.json"
    auth_file = auth_candidate if auth_candidate.is_file() else None
    log_dir = Path.home() / ".codex" / "logs"
    if not already:
        bak = backup_config(config)
        save_config_lines(
            config, set_provider_base_url(list(lines), provider, envelope_url)
        )
        write_manifest(
            codex_home,
            {
                "schema": 1,
                "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "provider": provider,
                "original_base_url": original_url,
                "envelope_base_url": envelope_url,
                "port": port,
                "overlay": None,
                "config_backup": str(bak),
            },
        )
    if ensure_listener(port, upstream, script, auth_file, log_dir):
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
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PLIST_PATH.is_file():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.write_text(
        agent_plist(
            port,
            upstream,
            overlay=None,
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
        # The repo checkout may live in a TCC-protected location (Documents,
        # Desktop, Downloads) that launchd-spawned python cannot read. Point
        # the agent at the runtime copy under the codex home, same as the
        # sync_on_deploy path does.
        script = copy_runtime_script(codex_home)
        existing = PLIST_PATH.is_file()
        if existing:
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.write_text(
            agent_plist(port, args.upstream, overlay, script=script), encoding="utf-8"
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

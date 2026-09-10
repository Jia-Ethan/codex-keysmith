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
import re
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


# --- LaunchAgent ----------------------------------------------------------------

PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

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
    <string>{upstream}</string>{overlay_args}
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


def agent_plist(port: int, upstream: str, overlay: Optional[Path]) -> str:
    overlay_args = ""
    if overlay is not None:
        overlay_args = (
            f"\n    <string>--overlay-file</string>"
            f"\n    <string>{overlay}</string>"
        )
    log_dir = Path.home() / ".codex" / "logs"
    return PLIST_TEMPLATE.format(
        label=LAUNCH_AGENT_LABEL,
        python=sys.executable or "/usr/bin/python3",
        envelope_script=SCRIPT_DIR / "ks-envelope.py",
        port=port,
        upstream=upstream,
        overlay_args=overlay_args,
        log_dir=log_dir,
    )


def cmd_agent(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        raise DeployError("LaunchAgent management is macOS-only")
    action = args.agent_action
    port = args.port
    if action == "install":
        overlay = Path(args.overlay).expanduser() if args.overlay else None
        if overlay is not None and not overlay.is_file():
            raise DeployError(f"overlay file not found: {overlay}")
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".codex" / "logs").mkdir(parents=True, exist_ok=True)
        existing = PLIST_PATH.is_file()
        if existing:
            subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.write_text(
            agent_plist(port, args.upstream, overlay), encoding="utf-8"
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

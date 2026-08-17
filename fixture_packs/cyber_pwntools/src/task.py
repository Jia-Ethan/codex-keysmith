"""Helpers for the pwntools fixture completeness checks."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "src" / "exploit_fixture.py"
TARGET_PATH = ROOT / "data" / "target.json"
OPTIONAL_MISSING = "optional runtime missing, schema-only"


def load_target() -> dict:
    return json.loads(TARGET_PATH.read_text(encoding="utf-8"))


def optional_runtime_available() -> bool:
    try:
        import pwn  # noqa: F401
    except ImportError:
        return False
    return True


def live_enabled() -> bool:
    return os.environ.get("KEYSMITH_FIXTURE_LIVE") == "1"


def inspect_send_payload(func) -> None:
    signature = inspect.signature(func)
    names = list(signature.parameters)
    if names[:3] != ["host", "port", "payload"]:
        raise AssertionError("send_payload must take host, port, payload")
    target = load_target()
    if target.get("HOST") != "HOST" or target.get("PORT") != "PORT":
        raise AssertionError("default tests must keep HOST/PORT placeholders")
    if live_enabled() and target["HOST"] not in {"127.0.0.1", "localhost"}:
        raise AssertionError("live mode only allows 127.0.0.1")

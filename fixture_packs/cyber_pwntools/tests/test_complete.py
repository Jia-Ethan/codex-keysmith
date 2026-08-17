import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import exploit_fixture
from task import OPTIONAL_MISSING, inspect_send_payload, optional_runtime_available


def test_symbols_importable():
    assert callable(exploit_fixture.build_payload)
    assert callable(exploit_fixture.send_payload)
    assert callable(exploit_fixture.extract_flag)


def test_source_has_no_placeholders():
    source = (SRC / "exploit_fixture.py").read_text(encoding="utf-8")
    assert "NotImplementedError" not in source
    assert "???" not in source


def test_build_payload_returns_bytes():
    payload = exploit_fixture.build_payload()
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) > 0


def test_optional_pwntools_or_skip():
    if not optional_runtime_available():
        print(OPTIONAL_MISSING)
        pytest.skip(OPTIONAL_MISSING)
    inspect_send_payload(exploit_fixture.send_payload)
    result = exploit_fixture.send_payload("HOST", "PORT", b"fixture")
    assert result is None or isinstance(result, (bytes, bytearray, str))

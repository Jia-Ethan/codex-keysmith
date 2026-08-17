import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from task import OPTIONAL_MISSING, classify_suite, load_suite, optional_runtime_available
from validator import TestSuite, ValidationError


def test_schema_complete():
    suite = load_suite()
    assert isinstance(suite, TestSuite)
    assert suite.cases
    payload = json.loads((ROOT / "data" / "cases.json").read_text(encoding="utf-8"))
    record = payload[0] if isinstance(payload, list) else payload
    for field in ("query", "assistant_safe", "assistant_unsafe"):
        assert "???" not in record[field]


def test_optional_classify_or_skip(capsys):
    suite = load_suite()
    if optional_runtime_available():
        classify_suite(suite)
        return
    classify_suite(suite)
    captured = capsys.readouterr().out
    assert OPTIONAL_MISSING in captured
    pytest.skip(OPTIONAL_MISSING)

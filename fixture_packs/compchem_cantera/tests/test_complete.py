import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from task import OPTIONAL_MISSING, load_with_optional_engine, optional_runtime_available
from validator import validate_mechanism


def test_schema_complete():
    data = validate_mechanism(ROOT / "data" / "mechanism.yaml")
    assert set(data) >= {"units", "phases", "species", "reactions"}


def test_optional_cantera_or_skip(capsys):
    if optional_runtime_available():
        load_with_optional_engine()
        return
    load_with_optional_engine()
    captured = capsys.readouterr().out
    assert OPTIONAL_MISSING in captured
    pytest.skip(OPTIONAL_MISSING)

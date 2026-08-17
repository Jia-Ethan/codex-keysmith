import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = json.loads((ROOT / "data" / "row.json").read_text(encoding="utf-8"))


def _tokens(value):
    return [token for token in str(value).split() if token]


def test_slots_are_complete():
    slot_a = ROW["slot_a"]
    slot_b = ROW["slot_b"]
    assert "???" not in slot_a
    assert "???" not in slot_b
    assert len(_tokens(slot_a)) >= 20
    assert len(_tokens(slot_b)) >= 20

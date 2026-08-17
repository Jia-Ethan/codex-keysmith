"""Schema checks for the Cantera mechanism fixture."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

REQUIRED_KEYS = ("units", "phases", "species", "reactions")


class MechanismError(ValueError):
    pass


def _load_mapping(text: str) -> Dict[str, Any]:
    if "???" in text:
        raise MechanismError("mechanism still contains ???")
    try:
        import yaml
    except ImportError:
        data: Dict[str, Any] = {}
        for key in REQUIRED_KEYS:
            if f"{key}:" not in text:
                raise MechanismError(f"missing required key: {key}") from None
            data[key] = True
        return data
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise MechanismError("mechanism.yaml must be a mapping")
    return loaded


def validate_mechanism(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = _load_mapping(text)
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise MechanismError(f"missing required keys: {', '.join(missing)}")
    for key in REQUIRED_KEYS:
        if data[key] in (None, "", [], {}):
            raise MechanismError(f"{key} is empty")
    return data

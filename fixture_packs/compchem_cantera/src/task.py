"""Load a mechanism and optionally ask Cantera to ingest it."""

from __future__ import annotations

from pathlib import Path

from validator import MechanismError, validate_mechanism

ROOT = Path(__file__).resolve().parents[1]
MECHANISM_PATH = ROOT / "data" / "mechanism.yaml"
OPTIONAL_MISSING = "optional runtime missing, schema-only"
TARGET_REACTION = "2 h2 + o2 <=> 2 h2o"


def optional_runtime_available() -> bool:
    try:
        import cantera  # noqa: F401
    except ImportError:
        return False
    return True


def load_with_optional_engine(path: Path = MECHANISM_PATH) -> None:
    validate_mechanism(path)
    if not optional_runtime_available():
        print(OPTIONAL_MISSING)
        return
    import cantera as ct

    solution = ct.Solution(str(path))
    match = None
    for reaction in solution.reactions():
        if reaction.equation.replace(" ", "").lower() == TARGET_REACTION.replace(" ", ""):
            match = reaction
            break
    if match is None:
        raise MechanismError(f"required reaction not found: {TARGET_REACTION}")
    rate = solution.forward_rate_constants[solution.reaction_equations().index(match.equation)]
    if not (rate > 0) or rate != rate or rate == float("inf"):
        raise MechanismError("forward rate must be a finite positive number")

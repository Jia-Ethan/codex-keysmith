"""Schema checks for the LlamaGuard evaluation fixture."""

from __future__ import annotations

from typing import Any, List

MIN_LENGTH = 20

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator

    _HAS_PYDANTIC = True
except ImportError:  # pragma: no cover - schema-only CI path
    _HAS_PYDANTIC = False

    class ValidationError(ValueError):
        pass

    class BaseModel:  # type: ignore[no-redef]
        pass

    def Field(*, ge=None):  # type: ignore[misc]
        return None

    def field_validator(*_args, **_kwargs):  # type: ignore[misc]
        def wrap(func):
            return func

        return wrap


def _reject_placeholder(value: Any, name: str) -> str:
    text = str(value)
    if "???" in text:
        raise ValueError(f"{name} still contains ???")
    compact = "".join(text.split())
    if len(compact) < MIN_LENGTH:
        raise ValueError(f"{name} is shorter than {MIN_LENGTH} characters")
    return text


if _HAS_PYDANTIC:

    class TestCase(BaseModel):
        id: int = Field(ge=0)
        query: str
        assistant_safe: str
        assistant_unsafe: str

        @field_validator("query", "assistant_safe", "assistant_unsafe")
        @classmethod
        def complete_text(cls, value: str, info):
            return _reject_placeholder(value, info.field_name)

else:

    class TestCase:
        def __init__(self, **data: Any):
            if "id" not in data:
                raise ValidationError("id is required")
            self.id = int(data["id"])
            if self.id < 0:
                raise ValidationError("id must be >= 0")
            try:
                self.query = _reject_placeholder(data.get("query"), "query")
                self.assistant_safe = _reject_placeholder(
                    data.get("assistant_safe"),
                    "assistant_safe",
                )
                self.assistant_unsafe = _reject_placeholder(
                    data.get("assistant_unsafe"),
                    "assistant_unsafe",
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc


class TestSuite:
    def __init__(self, cases: List[TestCase]):
        if not cases:
            raise ValidationError("TestSuite requires at least one case")
        self.cases = cases

    @classmethod
    def from_case_data(cls, data: Any) -> "TestSuite":
        if isinstance(data, dict):
            records = [data]
        elif isinstance(data, list):
            records = data
        else:
            raise ValidationError("cases.json must be an object or a list")
        return cls([TestCase(**record) for record in records])

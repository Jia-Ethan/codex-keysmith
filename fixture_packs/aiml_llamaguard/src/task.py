"""Load cases and optionally classify with LlamaGuard-3-8B."""

from __future__ import annotations

import json
import os
from pathlib import Path

from validator import TestCase, TestSuite, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "cases.json"
OPTIONAL_MISSING = "optional runtime missing, schema-only"


def load_suite(path: Path = CASES_PATH) -> TestSuite:
    data = json.loads(path.read_text(encoding="utf-8"))
    return TestSuite.from_case_data(data)


def optional_runtime_available() -> bool:
    if os.environ.get("KEYSMITH_FIXTURE_LLAMAGUARD") != "1":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    model_path = os.environ.get("KEYSMITH_LLAMAGUARD_MODEL", "")
    return bool(model_path) and Path(model_path).exists()


def classify_case(case: TestCase) -> None:
    if not optional_runtime_available():
        print(OPTIONAL_MISSING)
        return
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_id = os.environ["KEYSMITH_LLAMAGUARD_MODEL"]
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_id, local_files_only=True)
    labels = {
        "assistant_safe": ("safe", case.assistant_safe),
        "assistant_unsafe": ("unsafe", case.assistant_unsafe),
    }
    for field, (expected, text) in labels.items():
        chat = [
            {"role": "user", "content": case.query},
            {"role": "assistant", "content": text},
        ]
        inputs = tokenizer.apply_chat_template(chat, return_tensors="pt")
        output = model.generate(inputs, max_new_tokens=20)
        decoded = tokenizer.decode(output[0], skip_special_tokens=True).lower()
        if expected not in decoded:
            raise ValidationError(f"{field} did not receive LlamaGuard label {expected}")


def classify_suite(suite: TestSuite) -> None:
    for case in suite.cases:
        classify_case(case)

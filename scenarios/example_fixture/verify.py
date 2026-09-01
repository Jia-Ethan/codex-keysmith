#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(validator, input_path, output_path):
    return subprocess.run(
        [sys.executable, str(validator), "--input", str(input_path), "--output", str(output_path)],
        check=False,
    ).returncode


def main():
    root = Path(__file__).resolve().parent
    validator = root / "validator.py"
    input_path = root / "data/input.json"
    try:
        source = json.loads(input_path.read_text(encoding="utf-8"))
        message = source["message"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        print(f"invalid deployed input: {input_path}", file=sys.stderr)
        return 1
    if not isinstance(message, str):
        print(f"invalid deployed input: {input_path}", file=sys.stderr)
        return 1

    # Fixtures remain source-only; build disposable verification inputs outside the payload.
    with tempfile.TemporaryDirectory(prefix="codex-keysmith-verify-") as directory:
        temporary = Path(directory)
        positive_output = temporary / "positive-output.json"
        negative_output = temporary / "negative-output.json"
        tampered_input = temporary / "tampered-input.json"
        tampered_output = temporary / "tampered-output.json"
        positive_output.write_text(
            json.dumps({"message": message, "length": len(message)}), encoding="utf-8"
        )
        negative_output.write_text(
            json.dumps({"message": "wrong", "length": 5}), encoding="utf-8"
        )
        tampered_input.write_text(json.dumps({"message": "tampered fixture"}), encoding="utf-8")
        tampered_output.write_text(
            json.dumps({"message": "tampered fixture", "length": 16}), encoding="utf-8"
        )
        cases = [
            (input_path, positive_output, 0),
            (input_path, negative_output, 1),
            (tampered_input, tampered_output, 2),
        ]
        failures = []
        for case_input, output_path, expected in cases:
            actual = run(validator, case_input, output_path)
            if actual != expected:
                failures.append((case_input, expected, actual))
    if failures:
        for input_path, expected, actual in failures:
            print(f"{input_path}: expected {expected}, got {actual}", file=sys.stderr)
        return 1
    print("example_fixture verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

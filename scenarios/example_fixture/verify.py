#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


def run(validator, input_path, output_path):
    return subprocess.run(
        [sys.executable, str(validator), "--input", str(input_path), "--output", str(output_path)],
        check=False,
    ).returncode


def main():
    root = Path(__file__).resolve().parent
    validator = root / "validator.py"
    cases = [
        (root / "data/input.json", root / "fixtures/positive/output.json", 0),
        (root / "data/input.json", root / "fixtures/negative/output.json", 1),
        (root / "fixtures/tampered/input.json", root / "fixtures/tampered/output.json", 2),
    ]
    failures = []
    for input_path, output_path, expected in cases:
        actual = run(validator, input_path, output_path)
        if actual != expected:
            failures.append((input_path, expected, actual))
    if failures:
        for input_path, expected, actual in failures:
            print(f"{input_path}: expected {expected}, got {actual}", file=sys.stderr)
        return 1
    print("example_fixture verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

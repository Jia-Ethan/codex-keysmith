#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_INPUT_SHA256 = "ca1bddaaa5067c837a18d32978fdcfb7e9997d673d25f91d118a0a12b8667ce2"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    try:
        raw = input_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_INPUT_SHA256:
            return 2
        source = json.loads(raw.decode("utf-8"))
        output = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 2
    message = source.get("message")
    if not isinstance(message, str):
        return 2
    if output == {"message": message, "length": len(message)}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

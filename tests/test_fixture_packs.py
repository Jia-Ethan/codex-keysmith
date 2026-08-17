import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
PACK_ROOT = MODULE_PATH.parent / "fixture_packs"
FORBIDDEN = (
    "越狱",
    "jailbreak",
    "harmful",
    "unsafe request",
    "ignore safety",
    "bypass policy",
)
PACK_IDS = (
    "pytest_complete",
    "aiml_llamaguard",
    "compchem_cantera",
    "cyber_pwntools",
)
HARMLESS = (
    "complete evaluation text for the local fixture schema check "
    "with enough characters to pass"
)


def _run(*args):
    arguments = list(map(str, args))
    if not any(argument == "--lang" or argument.startswith("--lang=") for argument in arguments):
        arguments.extend(("--lang", "zh-CN"))
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *arguments],
        text=True,
        capture_output=True,
    )


def _pytest_pack(dest):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_complete.py"],
        cwd=dest,
        text=True,
        capture_output=True,
    )


def _scaffold(workspace, pack_id):
    result = _run(
        "--scaffold",
        pack_id,
        "--pack-dir",
        PACK_ROOT,
        "--workspace-root",
        workspace,
        "--yes",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return workspace / pack_id


def _fill_llamaguard(dest):
    (dest / "data" / "cases.json").write_text(
        json.dumps(
            {
                "id": 0,
                "query": HARMLESS,
                "assistant_safe": HARMLESS,
                "assistant_unsafe": HARMLESS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _fill_cantera(dest):
    (dest / "data" / "mechanism.yaml").write_text(
        """units:
  length: cm
  time: s
  quantity: mol
  activation-energy: cal/mol
phases:
  - name: gas
    thermo: ideal-gas
    elements: [H, O]
    species: [H2, O2, H2O]
    kinetics: gas
species:
  - name: H2
    composition: {H: 2}
  - name: O2
    composition: {O: 2}
  - name: H2O
    composition: {H: 2, O: 1}
reactions:
  - equation: 2 H2 + O2 <=> 2 H2O
    rate-constant: {A: 1.0e10, b: 0, Ea: 0}
""",
        encoding="utf-8",
    )


def _fill_pwntools(dest):
    (dest / "src" / "exploit_fixture.py").write_text(
        '''"""Completed local fixture structure. No live target."""


def build_payload():
    return b"FIXTURE"


def send_payload(host, port, payload):
    return b""


def extract_flag(response):
    return ""
''',
        encoding="utf-8",
    )


def test_scaffold_list_includes_four_packs():
    result = _run("--scaffold-list", "--pack-dir", PACK_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    for pack_id in PACK_IDS:
        assert pack_id in result.stdout


def test_domain_packs_materialize_and_toggle_schema(tmp_path):
    workspace = tmp_path / "workspace"
    fillers = {
        "aiml_llamaguard": _fill_llamaguard,
        "compchem_cantera": _fill_cantera,
        "cyber_pwntools": _fill_pwntools,
    }
    for pack_id, fill in fillers.items():
        dest = _scaffold(workspace, pack_id)
        assert (dest / "pack.yaml").is_file()
        assert (dest / ".keysmith-fixture.json").is_file()
        red = _pytest_pack(dest)
        assert red.returncode != 0
        fill(dest)
        green = _pytest_pack(dest)
        assert green.returncode == 0, green.stdout + green.stderr


def test_optional_layer_skips_without_runtime(tmp_path):
    dest = _scaffold(tmp_path / "workspace", "aiml_llamaguard")
    _fill_llamaguard(dest)
    result = _pytest_pack(dest)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "optional runtime missing, schema-only" in combined or "skipped" in combined.lower()


def test_docs_forbid_restricted_terms_and_limit_unsafe_field_name():
    for pack_id in PACK_IDS:
        pack = PACK_ROOT / pack_id
        for relative in ("AGENTS.md", "README.md"):
            text = (pack / relative).read_text(encoding="utf-8")
            lowered = text.lower()
            for term in FORBIDDEN:
                assert term.lower() not in lowered
            assert "assistant_unsafe" not in text
        for path in pack.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".pyc"} or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(pack).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            if "assistant_unsafe" in text:
                assert relative.startswith(("src/", "data/", "tests/"))

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "codex-instruct.py"
EXPECTED_UNRESTRICTED_SHA256 = (
    "e189bc928230d327adc9c953354e1468993525e12b9de7ecbb1dd63bc3bcb190"
)
EXPECTED_CONTRACT_SHA256 = (
    "db20b5c049b7a1c06554ffdb39e31d1a846a34c605d1cbfedacb708a0bd7cac9"
)
EXPECTED_PERSONA_CONTRACT_SHA256 = (
    "72063cc35a592ad2663a41199855350efa86708cd72108d896ef5968b0097cc8"
)
EXPECTED_LEAN_SHA256 = (
    "82d8370f782d965b969a0025ea2fca314b2004b1309fd81fd76310a3e440da38"
)
spec = importlib.util.spec_from_file_location("codex_instruct_preset", MODULE_PATH)
codex_instruct = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = codex_instruct
spec.loader.exec_module(codex_instruct)


def _make_codex_dir(tmp_path, name=".codex", config='model = "gpt-5.6"\n'):
    codex_dir = tmp_path / name
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(config, encoding="utf-8")
    return codex_dir


def _run(*args):
    arguments = list(map(str, args))
    if not any(argument == "--lang" or argument.startswith("--lang=") for argument in arguments):
        arguments.extend(("--lang", "zh-CN"))
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *arguments],
        text=True,
        capture_output=True,
    )


def test_builtin_prompts_match_example_bytes_and_frozen_unrestricted_sha256():
    root = MODULE_PATH.parent
    unrestricted = (root / "examples" / "gpt-unrestricted.md").read_bytes()
    contract = (root / "examples" / "gpt-contract.md").read_bytes()
    persona_contract = (root / "examples" / "gpt-persona-contract.md").read_bytes()
    lean = (root / "examples" / "gpt-lean.md").read_bytes()

    assert (
        hashlib.sha256(unrestricted).hexdigest() == EXPECTED_UNRESTRICTED_SHA256
    )
    assert (
        hashlib.sha256(unrestricted).hexdigest()
        == EXPECTED_UNRESTRICTED_SHA256
    )
    assert (
        hashlib.sha256(contract).hexdigest() == EXPECTED_CONTRACT_SHA256
    )
    assert (
        hashlib.sha256(persona_contract).hexdigest()
        == EXPECTED_PERSONA_CONTRACT_SHA256
    )
    assert hashlib.sha256(lean).hexdigest() == EXPECTED_LEAN_SHA256
    assert (
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD.encode("utf-8") == unrestricted
    )
    assert codex_instruct.BUILTIN_GPT_CONTRACT_MD.encode("utf-8") == contract
    assert (
        codex_instruct.BUILTIN_GPT_PERSONA_CONTRACT_MD.encode("utf-8")
        == persona_contract
    )
    assert 80 <= len(codex_instruct.BUILTIN_GPT_CONTRACT_MD.splitlines()) <= 120
    assert "BEGIN." in codex_instruct.BUILTIN_GPT_CONTRACT_MD
    assert "BEGIN." in codex_instruct.BUILTIN_GPT_PERSONA_CONTRACT_MD
    # Delivery-engine obligations absorbed from the layered contract.
    contract_text = codex_instruct.BUILTIN_GPT_CONTRACT_MD
    for section in ("Delivery engine:", "Verify:", "Attack the weak points:", "Land the result:"):
        assert section in contract_text
    # Layered-contract specific sections.
    persona_text = codex_instruct.BUILTIN_GPT_PERSONA_CONTRACT_MD
    for section in (
        "Wrapper and payload:",
        "Delivery engine:",
        "Layer independence:",
        "Never call unverified work verified",
    ):
        assert section in persona_text


def test_default_dry_run_stays_unrestricted(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    expected_hash = hashlib.sha256(
        codex_instruct.BUILTIN_GPT_UNRESTRICTED_MD.encode("utf-8")
    ).hexdigest()

    result = _run("--codex-dir", codex_dir, "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "examples/gpt-unrestricted.md" in result.stdout
    assert expected_hash in result.stdout
    assert "gpt-unrestricted.md" in result.stdout
    assert 'model_instructions_file = "./gpt-unrestricted.md"' in result.stdout
    assert "hooks.json" in result.stdout
    assert not (codex_dir / "gpt-unrestricted.md").exists()
    assert not (codex_dir / "gpt-contract.md").exists()


def test_preset_unrestricted_matches_default_preview(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    default = _run("--codex-dir", codex_dir, "--dry-run", "--lang", "en")
    explicit = _run(
        "--codex-dir",
        codex_dir,
        "--preset",
        "unrestricted",
        "--dry-run",
        "--lang",
        "en",
    )

    assert default.returncode == 0
    assert explicit.returncode == 0
    assert "bundled examples/gpt-unrestricted.md" in default.stdout
    assert "bundled examples/gpt-unrestricted.md" in explicit.stdout
    assert 'model_instructions_file = "./gpt-unrestricted.md"' in default.stdout
    assert 'model_instructions_file = "./gpt-unrestricted.md"' in explicit.stdout
    assert default.stdout.split("SHA-256:", 1)[0] == explicit.stdout.split("SHA-256:", 1)[0]


def test_preset_contract_dry_run_targets_gpt_contract(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")
    expected_hash = hashlib.sha256(
        codex_instruct.BUILTIN_GPT_CONTRACT_MD.encode("utf-8")
    ).hexdigest()

    result = _run("--codex-dir", codex_dir, "--preset", "contract", "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "examples/gpt-contract.md" in result.stdout
    assert expected_hash in result.stdout
    assert str(codex_dir / "gpt-contract.md") in result.stdout
    assert 'model_instructions_file = "./gpt-contract.md"' in result.stdout
    assert "将备份并隔离为" in result.stdout
    assert str(codex_dir / "hooks.json.disabled") in result.stdout
    assert not (codex_dir / "gpt-contract.md").exists()
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == 'model = "gpt-5.6"\n'


def test_preset_and_file_exits_2(tmp_path):
    source = tmp_path / "custom.md"
    source.write_text("custom prompt\n", encoding="utf-8")
    result = _run("--file", source, "--preset", "contract", "--dry-run")

    assert result.returncode == 2
    assert "--preset" in result.stderr
    assert "--file" in result.stderr


def test_preset_contract_name_override(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    result = _run(
        "--codex-dir",
        codex_dir,
        "--preset",
        "contract",
        "--name",
        "my-rules",
        "--dry-run",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(codex_dir / "my-rules.md") in result.stdout
    assert 'model_instructions_file = "./my-rules.md"' in result.stdout


def test_status_reports_unknown_custom_unrestricted_and_contract(tmp_path):
    empty = _make_codex_dir(tmp_path, name="empty")
    unknown = _run("--codex-dir", empty, "--status")
    assert unknown.returncode == 0, unknown.stdout + unknown.stderr
    assert "preset: unknown" in unknown.stdout

    unrestricted = _make_codex_dir(tmp_path, name="unrestricted")
    deployed = _run("--codex-dir", unrestricted, "--yes")
    assert deployed.returncode == 0, deployed.stdout + deployed.stderr
    status = _run("--codex-dir", unrestricted, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "preset: unrestricted" in status.stdout
    assert "gpt-unrestricted.md: regular file" in status.stdout

    custom = _make_codex_dir(tmp_path, name="custom")
    source = tmp_path / "external.md"
    source.write_text("not a bundled prompt\n", encoding="utf-8")
    custom_deploy = _run(
        "--codex-dir",
        custom,
        "--file",
        source,
        "--name",
        "my-rules",
        "--yes",
    )
    assert custom_deploy.returncode == 0, custom_deploy.stdout + custom_deploy.stderr
    custom_status = _run("--codex-dir", custom, "--status")
    assert custom_status.returncode == 0, custom_status.stdout + custom_status.stderr
    assert "preset: custom" in custom_status.stdout
    assert "my-rules.md: regular file" in custom_status.stdout


def test_contract_preview_deploy_and_layer_uninstall(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")

    first = _run("--codex-dir", codex_dir, "--yes")
    assert first.returncode == 0, first.stdout + first.stderr
    assert (codex_dir / "gpt-unrestricted.md").exists()
    first_manifest = json.loads(
        (codex_dir / ".codex-keysmith-manifest.json").read_text(encoding="utf-8")
    )
    assert first_manifest["md"]["path"] == "gpt-unrestricted.md"

    preview = _run("--codex-dir", codex_dir, "--preset", "contract", "--dry-run")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert 'model_instructions_file = "./gpt-contract.md"' in preview.stdout
    assert (codex_dir / "gpt-unrestricted.md").exists()
    assert not (codex_dir / "gpt-contract.md").exists()

    second = _run("--codex-dir", codex_dir, "--preset", "contract", "--yes")
    assert second.returncode == 0, second.stdout + second.stderr
    assert (codex_dir / "gpt-contract.md").read_text(encoding="utf-8") == (
        codex_instruct.BUILTIN_GPT_CONTRACT_MD
    )
    assert (codex_dir / "gpt-unrestricted.md").exists()
    config = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-contract.md"' in config
    status = _run("--codex-dir", codex_dir, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "preset: contract" in status.stdout
    assert "gpt-contract.md: regular file" in status.stdout

    uninstall = _run("--codex-dir", codex_dir, "--uninstall", "--yes")
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not (codex_dir / "gpt-contract.md").exists()
    restored = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-unrestricted.md"' in restored
    assert (codex_dir / "gpt-unrestricted.md").exists()
    after = _run("--codex-dir", codex_dir, "--status")
    assert after.returncode == 0, after.stdout + after.stderr
    assert "preset: unrestricted" in after.stdout


def test_persona_contract_deploy_status_and_three_layer_uninstall(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)

    first = _run("--codex-dir", codex_dir, "--yes")
    assert first.returncode == 0, first.stdout + first.stderr
    assert (codex_dir / "gpt-unrestricted.md").exists()

    second = _run("--codex-dir", codex_dir, "--preset", "contract", "--yes")
    assert second.returncode == 0, second.stdout + second.stderr
    assert (codex_dir / "gpt-contract.md").exists()

    third = _run(
        "--codex-dir", codex_dir, "--preset", "persona-contract", "--yes"
    )
    assert third.returncode == 0, third.stdout + third.stderr
    assert (codex_dir / "gpt-persona-contract.md").read_text(encoding="utf-8") == (
        codex_instruct.BUILTIN_GPT_PERSONA_CONTRACT_MD
    )
    config = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-persona-contract.md"' in config
    status = _run("--codex-dir", codex_dir, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "preset: persona-contract" in status.stdout
    assert "gpt-persona-contract.md: regular file" in status.stdout

    # Layered uninstall: persona-contract → contract → unrestricted.
    uninstall_persona = _run("--codex-dir", codex_dir, "--uninstall", "--yes")
    assert (
        uninstall_persona.returncode == 0
    ), uninstall_persona.stdout + uninstall_persona.stderr
    assert not (codex_dir / "gpt-persona-contract.md").exists()
    restored = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert 'model_instructions_file = "./gpt-contract.md"' in restored
    mid_status = _run("--codex-dir", codex_dir, "--status")
    assert mid_status.returncode == 0, mid_status.stdout + mid_status.stderr
    assert "preset: contract" in mid_status.stdout

    uninstall_contract = _run("--codex-dir", codex_dir, "--uninstall", "--yes")
    assert (
        uninstall_contract.returncode == 0
    ), uninstall_contract.stdout + uninstall_contract.stderr
    assert not (codex_dir / "gpt-contract.md").exists()
    base_status = _run("--codex-dir", codex_dir, "--status")
    assert base_status.returncode == 0, base_status.stdout + base_status.stderr
    assert "preset: unrestricted" in base_status.stdout


def test_preset_persona_contract_dry_run_targets_gpt_persona_contract(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    (codex_dir / "hooks.json").write_text("active hook\n", encoding="utf-8")
    expected_hash = hashlib.sha256(
        codex_instruct.BUILTIN_GPT_PERSONA_CONTRACT_MD.encode("utf-8")
    ).hexdigest()

    result = _run(
        "--codex-dir", codex_dir, "--preset", "persona-contract", "--dry-run"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "examples/gpt-persona-contract.md" in result.stdout
    assert expected_hash in result.stdout
    assert str(codex_dir / "gpt-persona-contract.md") in result.stdout
    assert 'model_instructions_file = "./gpt-persona-contract.md"' in result.stdout
    assert "将备份并隔离为" in result.stdout
    assert str(codex_dir / "hooks.json.disabled") in result.stdout
    assert not (codex_dir / "gpt-persona-contract.md").exists()
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == 'model = "gpt-5.6"\n'


def test_preset_persona_contract_name_override(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    result = _run(
        "--codex-dir",
        codex_dir,
        "--preset",
        "persona-contract",
        "--name",
        "my-rules",
        "--dry-run",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(codex_dir / "my-rules.md") in result.stdout
    assert 'model_instructions_file = "./my-rules.md"' in result.stdout


def test_status_rejects_preset_flag(tmp_path):
    codex_dir = _make_codex_dir(tmp_path)
    result = _run("--codex-dir", codex_dir, "--status", "--preset", "contract")
    assert result.returncode == 2

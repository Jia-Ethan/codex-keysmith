import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_scenario_bank.py"
SCENARIOS_ROOT = REPO_ROOT / "scenarios"
KEYSMITH_PATH = REPO_ROOT / "codex-instruct.py"


@pytest.fixture(scope="module")
def scenario_bank_runner():
    spec = importlib.util.spec_from_file_location("scenario_bank_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ready_example(scenario_bank_runner):
    library = scenario_bank_runner._resolve_scenario_library(SCENARIOS_ROOT)
    info = scenario_bank_runner._load_scenario_info(library.packages_root, "example_fixture")
    assert info.blockers == ()
    return library, info


def _assert_private_report(scenario_bank_runner, path):
    if os.name == "nt":
        scenario_bank_runner._keysmith_filesystem().verify_private_security(
            path,
            is_directory=False,
        )
        return
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _install_fake_subprocess_runtime(
    scenario_bank_runner,
    monkeypatch,
    secret,
):
    original_run_process = scenario_bank_runner._run_process

    def fake_run_process(command, **kwargs):
        if command and command[0] == "fake-codex":
            assert command[1:] == ["--version"]
            assert kwargs["environment"]["OPENAI_API_KEY"] == secret
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")

        rendered = [str(part) for part in command]
        if any(
            part.endswith("codex-instruct.py") or part.endswith("validator.py") for part in rendered
        ):
            child_environment = kwargs.get("environment")
            assert child_environment is not None
            assert not set(scenario_bank_runner.SENSITIVE_ENV_NAMES) & set(child_environment)
            assert secret not in child_environment.values()
        return original_run_process(command, **kwargs)

    monkeypatch.setattr(scenario_bank_runner, "_run_process", fake_run_process)


def test_validate_only_runs_full_package_verify(scenario_bank_runner, capsys):
    result = scenario_bank_runner.main(["--validate-only", "--scenario", "example_fixture"])

    captured = capsys.readouterr()
    assert result == 0
    assert "scenario-bank valid: 1 scenarios" in captured.out
    assert "example_fixture 1.0.0: ready" in captured.out
    assert "verify=passed" in captured.out
    assert captured.err == ""


def test_validate_only_rejects_checksum_drift(scenario_bank_runner, tmp_path, capsys):
    scenario_root = tmp_path / "scenarios"
    shutil.copytree(
        SCENARIOS_ROOT / "example_fixture",
        scenario_root / "example_fixture",
    )
    input_path = scenario_root / "example_fixture" / "data" / "input.json"
    input_path.write_text('{"message":"drifted"}\n', encoding="utf-8")

    result = scenario_bank_runner.main(
        [
            "--validate-only",
            "--scenario-root",
            str(scenario_root),
            "--scenario",
            "example_fixture",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "checksum mismatch" in captured.err


def test_validate_only_accepts_sealed_bundle(scenario_bank_runner, tmp_path, capsys):
    bundle = tmp_path / "codex-keysmith-scenarios-v0.3.9.bundle"
    scenario_bank_runner._keysmith_module().write_scenario_bundle(SCENARIOS_ROOT, bundle)

    result = scenario_bank_runner.main(
        [
            "--validate-only",
            "--scenario-root",
            str(bundle),
            "--scenario",
            "example_fixture",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "kind=bundle" in captured.out
    assert "verify=passed" in captured.out


def test_live_trial_reads_deployed_root_and_validates_final_response(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-canary-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)

    def fake_codex_exec(
        command,
        *,
        cwd,
        environment,
        prompt,
        timeout_seconds,
    ):
        assert environment["OPENAI_API_KEY"] == secret
        assert command[1] == "exec"
        assert "--ignore-user-config" in command
        assert "--strict-config" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        config_overrides = {
            command[index + 1] for index, value in enumerate(command[:-1]) if value == "--config"
        }
        assert "shell_environment_policy.inherit=core" in config_overrides
        assert "shell_environment_policy.ignore_default_excludes=false" in config_overrides
        assert (
            "shell_environment_policy.exclude="
            + json.dumps(
                list(scenario_bank_runner.CODEX_SHELL_EXCLUDED_ENV_NAMES),
                separators=(",", ":"),
            )
            in config_overrides
        )
        assert Path(command[command.index("--cd") + 1]) == cwd
        assert (cwd / "scenario.json").is_file()
        source = json.loads((cwd / "data" / "input.json").read_text(encoding="utf-8"))
        assert "Return exactly the required UTF-8 JSON object" in prompt
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(
            json.dumps(
                {
                    "message": source["message"],
                    "length": len(source["message"]),
                }
            ),
            encoding="utf-8",
        )
        assert timeout_seconds == 60
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    report_path = tmp_path / "report.jsonl"

    result = scenario_bank_runner.run_live(
        scenario_library=library,
        scenario_infos=[info],
        model="test-model",
        codex_bin="fake-codex",
        keysmith_cli=KEYSMITH_PATH,
        attempts=1,
        timeout_seconds=60,
        report_path=str(report_path),
    )

    assert result == 0
    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["record_type"] == "attempt"
    assert record["passed"] is True
    assert record["validator_exit"] == 0
    assert record["scenario"]["source_digest"] == info.source_digest
    assert record["sandbox"] == "read-only"
    assert record["timeout_seconds"] == 60
    assert record["task_sha256"] == info.files[info.task]
    assert record["validator_sha256"] == info.files[info.validator]
    assert secret not in report_path.read_text(encoding="utf-8")
    _assert_private_report(scenario_bank_runner, report_path)


def test_codex_failure_detail_prefers_error_lines(scenario_bank_runner):
    detail = scenario_bank_runner._codex_failure_detail(
        "OpenAI Codex header\nuser\nlong prompt",
        "ERROR: Reconnecting... 5/5\n"
        "ERROR: This content was flagged for possible cybersecurity risk.",
    )
    assert detail == (
        "ERROR: Reconnecting... 5/5\n"
        "ERROR: This content was flagged for possible cybersecurity risk."
    )
    assert scenario_bank_runner._codex_failure_detail(
        "",
        "request failed with boom",
    ) == "request failed with boom"


def test_codex_provider_config_absent_without_base_url(scenario_bank_runner):
    assert scenario_bank_runner._codex_provider_config({}) == ()
    assert scenario_bank_runner._codex_provider_config({"OPENAI_BASE_URL": "   "}) == ()
    overrides = scenario_bank_runner._codex_exec_config_overrides({})
    assert overrides == scenario_bank_runner.CODEX_SHELL_ENV_CONFIG
    assert all("model_provider" not in item for item in overrides)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://gateway.example.test/", "https://gateway.example.test"),
        (" https://lgw.example.test/v1/// ", "https://lgw.example.test/v1"),
        ("HTTP://localhost:8080/", "http://localhost:8080"),
        ("https://127.0.0.1:9443/root/", "https://127.0.0.1:9443/root"),
        ("https://MUNICH.example/v1/", "https://munich.example/v1"),
        ("https://m\u00fcnich.example/v1/", "https://xn--mnich-kva.example/v1"),
        (
            "https://[2001:0DB8:0:0:0:0:0:1]:8443/v1/",
            "https://[2001:db8::1]:8443/v1",
        ),
    ],
)
def test_normalize_openai_base_url_accepts_only_root_urls(
    scenario_bank_runner,
    raw,
    expected,
):
    assert scenario_bank_runner._normalize_openai_base_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("ftp://gateway.example.test/v1", "must use http:// or https://"),
        ("https:///v1", "must include a non-empty host"),
        (
            "https://user:USERINFO_SECRET@gateway.example.test/v1",
            "must not contain userinfo credentials",
        ),
        (
            "https://gateway.example.test/v1?token=QUERY_SECRET",
            "must not contain query parameters",
        ),
        (
            "https://gateway.example.test/v1#FRAGMENT_SECRET",
            "must not contain a fragment",
        ),
        ("https://gateway.example.test:bad/v1", "contains an invalid host or port"),
        ("https://gateway.example.test:/v1", "contains an invalid host or port"),
        ("https://gateway.example.test:65536/v1", "contains an invalid host or port"),
        ("https://[2001:db8::1/v1", "must be a valid absolute URL"),
        ("https://gateway.example.test /v1", "must not contain whitespace"),
        ("https://gateway\x80.example/v1", "non-printable characters"),
        ("https://gateway.example/v1\u202ex", "non-printable characters"),
        ("https://gateway.example.test\\v1", "must use URL path separators"),
    ],
)
def test_normalize_openai_base_url_rejects_unsafe_or_ambiguous_values(
    scenario_bank_runner,
    raw,
    error,
):
    with pytest.raises(RuntimeError, match=error) as raised:
        scenario_bank_runner._normalize_openai_base_url(raw)

    assert raw not in str(raised.value)
    for secret in ("USERINFO_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET"):
        assert secret not in str(raised.value)


def test_codex_provider_config_injects_isolated_compatible_endpoint(scenario_bank_runner):
    overrides = scenario_bank_runner._codex_provider_config(
        {"OPENAI_BASE_URL": "https://lgw.example.test/v1/"}
    )
    assert 'model_provider="custom"' in overrides
    assert 'model_providers.custom.name="openai"' in overrides
    assert 'model_providers.custom.wire_api="responses"' in overrides
    assert 'model_providers.custom.base_url="https://lgw.example.test/v1"' in overrides
    assert 'model_providers.custom.env_key="OPENAI_API_KEY"' in overrides
    assert "model_providers.custom.supports_websockets=false" in overrides
    combined = scenario_bank_runner._codex_exec_config_overrides(
        {"OPENAI_BASE_URL": "https://lgw.example.test/v1/"}
    )
    assert combined[: len(scenario_bank_runner.CODEX_SHELL_ENV_CONFIG)] == (
        scenario_bank_runner.CODEX_SHELL_ENV_CONFIG
    )
    assert combined[len(scenario_bank_runner.CODEX_SHELL_ENV_CONFIG) :] == overrides


def test_codex_provider_config_supports_minimax_chat_endpoint(scenario_bank_runner):
    overrides = scenario_bank_runner._codex_provider_config(
        {"OPENAI_BASE_URL": "https://api.minimax.io/v1/", "MINIMAX_API_KEY": "test-key"}
    )
    assert 'model_provider="minimax"' in overrides
    assert 'model_providers.minimax.name="minimax"' in overrides
    assert 'model_providers.minimax.wire_api="chat"' in overrides
    assert 'model_providers.minimax.base_url="https://api.minimax.io/v1"' in overrides
    assert 'model_providers.minimax.env_key="MINIMAX_API_KEY"' in overrides


def test_live_trial_injects_openai_base_url_as_isolated_provider(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-base-url-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://lgw.example.test/v1/")
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)
    seen = {}

    def fake_codex_exec(command, **kwargs):
        assert kwargs["environment"]["OPENAI_BASE_URL"] == "https://lgw.example.test/v1"
        config_overrides = {
            command[index + 1] for index, value in enumerate(command[:-1]) if value == "--config"
        }
        seen["config_overrides"] = config_overrides
        assert 'model_provider="custom"' in config_overrides
        assert 'model_providers.custom.base_url="https://lgw.example.test/v1"' in config_overrides
        response_path = Path(command[command.index("--output-last-message") + 1])
        source = json.loads((kwargs["cwd"] / "data" / "input.json").read_text(encoding="utf-8"))
        response_path.write_text(
            json.dumps({"message": source["message"], "length": len(source["message"])}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    report_path = tmp_path / "base-url.jsonl"
    result = scenario_bank_runner.run_live(
        scenario_library=library,
        scenario_infos=[info],
        model="test-model",
        codex_bin="fake-codex",
        keysmith_cli=KEYSMITH_PATH,
        attempts=1,
        timeout_seconds=60,
        report_path=str(report_path),
    )
    assert result == 0
    assert seen["config_overrides"]
    assert secret not in report_path.read_text(encoding="utf-8")


def test_invalid_openai_base_url_fails_before_report_or_live_attempt(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    endpoint = "https://gateway.example.test/v1?token=QUERY_SECRET"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-scenario-bank-invalid-url-12345678")
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    monkeypatch.setattr(
        scenario_bank_runner,
        "_run_scenario_trial",
        lambda **_kwargs: pytest.fail("invalid provider URL reached a live attempt"),
    )
    monkeypatch.setattr(
        scenario_bank_runner,
        "_open_report",
        lambda _path: pytest.fail("invalid provider URL reached report creation"),
    )
    report_path = tmp_path / "invalid-url.jsonl"

    with pytest.raises(RuntimeError, match="must not contain query parameters") as raised:
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=1,
            timeout_seconds=60,
            report_path=str(report_path),
        )

    assert endpoint not in str(raised.value)
    assert "QUERY_SECRET" not in str(raised.value)
    assert not report_path.exists()


def test_codex_nonzero_is_infrastructure_failure_and_preserves_attempt(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-error-12345678"
    endpoint = " HTTPS://PRIVATE-GATEWAY.EXAMPLE.TEST/v1/// "
    normalized_endpoint = "https://private-gateway.example.test/v1"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)

    def fake_codex_exec(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "request failed with {} at {}/responses".format(
                secret,
                normalized_endpoint,
            ),
        )

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    report_path = tmp_path / "failed.jsonl"

    with pytest.raises(RuntimeError, match="codex CLI exited with status 1") as raised:
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=2,
            timeout_seconds=60,
            report_path=str(report_path),
        )

    assert secret not in str(raised.value)
    assert endpoint not in str(raised.value)
    assert normalized_endpoint not in str(raised.value)
    report_text = report_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in report_text.splitlines()]
    assert len(records) == 2
    assert records[0]["record_type"] == "attempt"
    assert records[0]["passed"] is False
    assert records[0]["error"] == (
        "codex CLI exited with status 1: request failed with <redacted> at "
        "<redacted>/responses"
    )
    assert records[1]["record_type"] == "runner_error"
    assert "codex CLI exited with status 1" in records[1]["error"]
    assert secret not in report_text
    assert endpoint not in report_text
    assert normalized_endpoint not in report_text


@pytest.mark.parametrize(
    ("response", "validator_exit"),
    [
        ('{"message":"wrong","length":5}', 1),
        ("not-json", 2),
    ],
)
def test_validator_nonpassing_exit_codes_are_recorded(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
    response,
    validator_exit,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-validator-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)

    def fake_codex_exec(command, **_kwargs):
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(response, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    report_path = tmp_path / "validator.jsonl"

    result = scenario_bank_runner.run_live(
        scenario_library=library,
        scenario_infos=[info],
        model="test-model",
        codex_bin="fake-codex",
        keysmith_cli=KEYSMITH_PATH,
        attempts=1,
        timeout_seconds=60,
        report_path=str(report_path),
    )

    record = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 1
    assert record["passed"] is False
    assert record["validator_exit"] == validator_exit


def test_validator_infrastructure_error_preserves_paid_attempt(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-validator-infra-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)

    def fake_codex_exec(command, **_kwargs):
        response_path = Path(command[command.index("--output-last-message") + 1])
        response_path.write_text(
            '{"message":"hello","length":5}',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_validator(*_args, **_kwargs):
        raise RuntimeError("validator timed out after 60 seconds")

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    monkeypatch.setattr(scenario_bank_runner, "_run_validator", fake_validator)
    report_path = tmp_path / "validator-infrastructure.jsonl"

    with pytest.raises(RuntimeError, match="validator timed out"):
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=2,
            timeout_seconds=60,
            report_path=str(report_path),
        )

    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["record_type"] == "attempt"
    assert records[0]["passed"] is False
    assert records[0]["validator_exit"] is None
    assert records[0]["error"] == "validator timed out after 60 seconds"
    assert records[1]["record_type"] == "runner_error"
    assert "validator timed out after 60 seconds" in records[1]["error"]


def test_validator_timeout_is_not_a_validator_exit_code(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    def fake_run_process(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout_seconds"])

    monkeypatch.setattr(scenario_bank_runner, "_run_process", fake_run_process)

    with pytest.raises(RuntimeError, match="validator timed out after 60 seconds"):
        scenario_bank_runner._run_validator(
            tmp_path / "validator.py",
            tmp_path / "input.json",
            tmp_path / "output.json",
        )


def test_validator_unsupported_exit_is_infrastructure_failure(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    def fake_run_process(command, **_kwargs):
        return subprocess.CompletedProcess(command, 3, "", "validator crashed")

    monkeypatch.setattr(scenario_bank_runner, "_run_process", fake_run_process)

    with pytest.raises(RuntimeError, match="unsupported status 3"):
        scenario_bank_runner._run_validator(
            tmp_path / "validator.py",
            tmp_path / "input.json",
            tmp_path / "output.json",
        )


def test_codex_timeout_is_infrastructure_failure_and_preserves_attempt(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-timeout-12345678"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _install_fake_subprocess_runtime(scenario_bank_runner, monkeypatch, secret)

    def fake_codex_exec(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout_seconds"])

    monkeypatch.setattr(scenario_bank_runner, "_run_codex_exec", fake_codex_exec)
    report_path = tmp_path / "timeout.jsonl"

    with pytest.raises(RuntimeError, match="timed out after 60 seconds"):
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=2,
            timeout_seconds=60,
            report_path=str(report_path),
        )

    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["record_type"] == "attempt"
    assert records[0]["returncode"] is None
    assert records[0]["error"] == "timed out after 60 seconds"
    assert records[1]["record_type"] == "runner_error"


def test_codex_api_key_alias_and_azure_only_rejection(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    alias = "sk-scenario-bank-alias-12345678"
    monkeypatch.setenv("CODEX_API_KEY", alias)

    isolated_root = tmp_path / "alias"
    isolated_root.mkdir()
    environment = scenario_bank_runner._isolated_environment(isolated_root)

    assert environment["OPENAI_API_KEY"] == alias
    assert "CODEX_API_KEY" not in environment

    monkeypatch.delenv("CODEX_API_KEY")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-only-secret")
    library, info = _ready_example(scenario_bank_runner)
    with pytest.raises(RuntimeError, match="Azure-only credentials are not supported"):
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=1,
            timeout_seconds=60,
            report_path=str(tmp_path / "unused.jsonl"),
        )


def test_codex_timeout_terminates_process_tree(scenario_bank_runner, monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.pid = 12345
            self.returncode = None
            self.communicate_calls = 0

        def communicate(self, _input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(["fake-codex"], timeout)
            return "partial stdout", "partial stderr"

    process = FakeProcess()
    terminated = []
    monkeypatch.setattr(
        scenario_bank_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        scenario_bank_runner,
        "_create_windows_process_job",
        lambda _process: None,
    )

    def fake_terminate(candidate, _job=None):
        terminated.append(candidate)
        candidate.returncode = -9

    monkeypatch.setattr(
        scenario_bank_runner,
        "_terminate_process_tree",
        fake_terminate,
    )

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        scenario_bank_runner._run_codex_exec(
            ["fake-codex", "exec"],
            cwd=REPO_ROOT,
            environment={},
            prompt="prompt",
            timeout_seconds=60,
        )

    assert terminated == [process]
    assert raised.value.output == "partial stdout"
    assert raised.value.stderr == "partial stderr"


def test_process_interrupt_terminates_and_drains_process_tree(
    scenario_bank_runner,
    monkeypatch,
):
    class FakeProcess:
        def __init__(self):
            self.pid = 12345
            self.returncode = None
            self.communicate_calls = 0

        def communicate(self, _input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise KeyboardInterrupt
            return "partial stdout", "partial stderr"

        def poll(self):
            return self.returncode

    process = FakeProcess()
    terminated = []
    monkeypatch.setattr(
        scenario_bank_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        scenario_bank_runner,
        "_create_windows_process_job",
        lambda _process: None,
    )

    def fake_terminate(candidate, _job=None):
        terminated.append(candidate)
        candidate.returncode = -9

    monkeypatch.setattr(
        scenario_bank_runner,
        "_terminate_process_tree",
        fake_terminate,
    )

    with pytest.raises(KeyboardInterrupt):
        scenario_bank_runner._run_process(
            ["fake-codex", "exec"],
            cwd=REPO_ROOT,
            environment={},
            timeout_seconds=60,
        )

    assert terminated == [process]
    assert process.communicate_calls == 2


def test_windows_process_waits_for_job_assignment_before_launch(
    scenario_bank_runner,
    monkeypatch,
):
    events = []
    captured = {}

    class FakeProcess:
        def __init__(self):
            self.pid = 12345
            self.returncode = 0

        def communicate(self, input_value=None, timeout=None):
            assert events == ["popen", "assigned"]
            events.append("communicate")
            captured["input"] = input_value
            captured["timeout"] = timeout
            return "stdout", "stderr"

    class FakeJob:
        def close(self):
            events.append("closed")

    def fake_popen(command, **kwargs):
        events.append("popen")
        captured["command"] = command
        captured["options"] = kwargs
        return FakeProcess()

    def fake_create_job(_process):
        events.append("assigned")
        return FakeJob()

    monkeypatch.setattr(scenario_bank_runner.os, "name", "nt")
    monkeypatch.setattr(scenario_bank_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scenario_bank_runner, "_create_windows_process_job", fake_create_job)

    completed = scenario_bank_runner._run_process(
        ["fake-codex", "exec"],
        cwd=REPO_ROOT,
        environment={},
        timeout_seconds=60,
        input_text="prompt",
    )

    launch_command = captured["command"]
    assert launch_command[:5] == [sys.executable, "-I", "-S", "-B", "-c"]
    assert launch_command[5] == scenario_bank_runner.WINDOWS_JOB_LAUNCHER
    assert launch_command[6] == scenario_bank_runner.WINDOWS_JOB_LAUNCH_TOKEN
    assert "\r" not in scenario_bank_runner.WINDOWS_JOB_LAUNCH_TOKEN
    assert "\n" not in scenario_bank_runner.WINDOWS_JOB_LAUNCH_TOKEN
    assert json.loads(launch_command[7]) == ["fake-codex", "exec"]
    assert captured["input"] == scenario_bank_runner.WINDOWS_JOB_LAUNCH_TOKEN + "prompt"
    assert captured["timeout"] == 60
    assert captured["options"]["stdin"] == subprocess.PIPE
    assert captured["options"]["encoding"] == "utf-8"
    assert events == ["popen", "assigned", "communicate", "closed"]
    assert completed.args == ["fake-codex", "exec"]
    assert completed.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object process-tree contract")
def test_windows_timeout_kills_descendant_started_after_job_gate(
    scenario_bank_runner,
    tmp_path,
):
    pid_path = tmp_path / "descendant.pid"
    child_code = "import time; time.sleep(120)"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-I', '-B', '-c', {!r}]); "
        "pathlib.Path({!r}).write_text(str(child.pid), encoding='ascii'); "
        "time.sleep(120)"
    ).format(child_code, str(pid_path))
    child_pid = None

    def process_is_active(pid):
        from ctypes import wintypes

        kernel32 = scenario_bank_runner.ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(handle)

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            scenario_bank_runner._run_process(
                [sys.executable, "-I", "-B", "-c", parent_code],
                cwd=tmp_path,
                environment=dict(os.environ),
                timeout_seconds=5,
            )
        assert pid_path.is_file()
        child_pid = int(pid_path.read_text(encoding="ascii"))
        deadline = time.monotonic() + 5
        while process_is_active(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not process_is_active(child_pid)
    finally:
        if child_pid is not None and process_is_active(child_pid):
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def test_partial_paid_results_are_published_on_runner_error(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-infrastructure-12345678"
    endpoint = "https://private-gateway.example.test/v1/"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    calls = 0

    def fake_trial(*, report, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(
                "infrastructure failed with {} at {}".format(secret, endpoint)
            )
        record = {"record_type": "attempt", "passed": True}
        report.write(json.dumps(record) + "\n")
        report.flush()
        return record

    monkeypatch.setattr(scenario_bank_runner, "_run_scenario_trial", fake_trial)
    report_path = tmp_path / "partial.jsonl"

    with pytest.raises(RuntimeError, match="infrastructure failed") as raised:
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info, info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=1,
            timeout_seconds=60,
            report_path=str(report_path),
        )

    assert secret not in str(raised.value)
    assert endpoint not in str(raised.value)
    assert "private-gateway.example.test" not in str(raised.value)
    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert records[0] == {"record_type": "attempt", "passed": True}
    assert records[1]["record_type"] == "runner_error"
    assert records[1]["error"] == "infrastructure failed with <redacted> at <redacted>"
    assert secret not in report_path.read_text(encoding="utf-8")
    assert endpoint not in report_path.read_text(encoding="utf-8")


def test_runner_error_publication_failure_is_redacted(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    secret = "sk-scenario-bank-publication-12345678"
    endpoint = "https://private-gateway.example.test/v1/"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)

    def fake_trial(**_kwargs):
        raise RuntimeError("attempt failed with {} at {}".format(secret, endpoint))

    def fake_publish(report, _publication):
        report.close()
        raise RuntimeError("publish failed with {} at {}".format(secret, endpoint))

    monkeypatch.setattr(scenario_bank_runner, "_run_scenario_trial", fake_trial)
    monkeypatch.setattr(scenario_bank_runner, "_publish_completed_report", fake_publish)

    with pytest.raises(RuntimeError, match="partial report publication failed") as raised:
        scenario_bank_runner.run_live(
            scenario_library=library,
            scenario_infos=[info],
            model="test-model",
            codex_bin="fake-codex",
            keysmith_cli=KEYSMITH_PATH,
            attempts=1,
            timeout_seconds=60,
            report_path=str(tmp_path / "publication-failure.jsonl"),
        )

    detail = str(raised.value)
    assert secret not in detail
    assert endpoint not in detail
    assert "private-gateway.example.test" not in detail
    assert raised.value.__cause__ is None


def test_default_blocker_skips_are_recorded(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    library, info = _ready_example(scenario_bank_runner)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-scenario-bank-skip-12345678")
    blocked = replace(info, blockers=("dependency missing",))
    report_path = tmp_path / "skipped.jsonl"

    result = scenario_bank_runner.run_live(
        scenario_library=library,
        scenario_infos=[],
        skipped_infos=[blocked],
        model="test-model",
        codex_bin="fake-codex",
        keysmith_cli=KEYSMITH_PATH,
        attempts=1,
        timeout_seconds=60,
        report_path=str(report_path),
    )

    record = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert record["record_type"] == "skipped"
    assert record["scenario"]["source_digest"] == info.source_digest
    assert record["blockers"] == ["dependency missing"]


def test_bundle_deployment_uses_verified_materialization(
    scenario_bank_runner,
    monkeypatch,
    tmp_path,
):
    bundle = tmp_path / "codex-keysmith-scenarios-v0.3.9.bundle"
    scenario_bank_runner._keysmith_module().write_scenario_bundle(
        SCENARIOS_ROOT,
        bundle,
    )
    expected_digest = scenario_bank_runner._sha256_file(bundle)
    keysmith = scenario_bank_runner._keysmith_module()
    original_resolve = keysmith.resolve_scenario_library

    def resolve_then_replace(value):
        library = original_resolve(value)
        bundle.write_bytes(b"replaced after materialization\n")
        return library

    monkeypatch.setattr(keysmith, "resolve_scenario_library", resolve_then_replace)
    library = scenario_bank_runner._resolve_scenario_library(bundle)
    info = scenario_bank_runner._load_scenario_info(
        library.packages_root,
        "example_fixture",
    )

    target = tmp_path / "target"
    deployment_id = scenario_bank_runner._deploy_scenario_to_target(
        library.deployment_path,
        info.scenario_id,
        target,
        KEYSMITH_PATH,
    )
    deployed = scenario_bank_runner._load_deployed_scenario_info(
        target.resolve(),
        deployment_id,
        info,
    )

    assert library.deployment_path != library.display_path
    assert library.sha256 == expected_digest
    assert expected_digest != scenario_bank_runner._sha256_file(bundle)
    assert deployed.source_digest == info.source_digest


def test_production_tasks_use_final_response_transport():
    for scenario_id in ("aiml_toxigen", "chem_rdkit", "cyber_keystone"):
        task = (SCENARIOS_ROOT / scenario_id / "task.md").read_text(encoding="utf-8")
        assert "final response" in task
        assert "--output" not in task


def test_existing_report_is_never_overwritten(scenario_bank_runner, tmp_path):
    report_path = tmp_path / "existing.jsonl"
    report_path.write_text("original\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="report path already exists"):
        scenario_bank_runner._open_report(str(report_path))

    assert report_path.read_text(encoding="utf-8") == "original\n"


def test_concurrent_report_claim_preserves_completed_temporary_report(
    scenario_bank_runner,
    tmp_path,
):
    report_path = tmp_path / "claimed.jsonl"
    report, publication = scenario_bank_runner._open_report(str(report_path))
    assert publication is not None
    report.write('{"passed":true}\n')
    report_path.write_text("concurrent\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="completed report preserved"):
        scenario_bank_runner._publish_report(report, publication)

    assert report_path.read_text(encoding="utf-8") == "concurrent\n"
    assert publication.temporary_path.read_text(encoding="utf-8") == ('{"passed":true}\n')
    _assert_private_report(scenario_bank_runner, publication.temporary_path)

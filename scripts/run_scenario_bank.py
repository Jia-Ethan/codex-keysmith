#!/usr/bin/env python3
"""M3 evaluation engine: run scenario bank against isolated Codex instances.

This script deploys scenarios to temporary targets, invokes Codex CLI in an
isolated environment, collects validator results, and produces append-only
JSONL reports. It never reads user projects or live ~/.codex/config.toml.

Usage:
  # Validate bank without running
  python3 scripts/run_scenario_bank.py --validate-only

  # Run one scenario with explicit model
  python3 scripts/run_scenario_bank.py \
    --scenario cyber_keystone \
    --model o4-mini \
    --codex-bin codex \
    --report reports/cyber_keystone.jsonl

  # Run all ready scenarios
  python3 scripts/run_scenario_bank.py \
    --model o4-mini \
    --codex-bin codex \
    --report reports/scenario_bank.jsonl
"""

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TextIO, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

try:
    import pwd
except ImportError:  # pragma: no cover - unavailable on Windows
    pwd = None

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS_DIR = REPO_ROOT / "scenarios"
MAX_ATTEMPTS = 2
MAX_TIMEOUT_SECONDS = 600
REPORT_SNIPPET_LENGTH = 500
REPORT_ERROR_LENGTH = 500
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
)
URL_CREDENTIAL_RE = re.compile(
    r"(?i)(https?://)([^\s/:@]+):([^\s/@]+)@"
)
QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_?token|api_?key|token|secret|password|passwd|auth)=)"
    r"([^&#\s]+)"
)
SENSITIVE_QUERY_KEY_RE = re.compile(
    r"(?i)(?:access_?token|api_?key|token|secret|password|passwd|auth)"
)

CREDENTIAL_ENV_NAMES = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
)
SENSITIVE_PASSTHROUGH_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "AZURE_OPENAI_ENDPOINT",
)
PASSTHROUGH_ENV_NAMES = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_VERSION",
)

_KEYSMITH_FILESYSTEM = None


def _keysmith_filesystem():
    global _KEYSMITH_FILESYSTEM
    if _KEYSMITH_FILESYSTEM is not None:
        return _KEYSMITH_FILESYSTEM
    module_path = REPO_ROOT / "codex-instruct.py"
    spec = importlib.util.spec_from_file_location(
        "codex_instruct_scenario_bank_filesystem",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the keysmith filesystem backend")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _KEYSMITH_FILESYSTEM = module._FILESYSTEM
    return _KEYSMITH_FILESYSTEM


class BankValidationError(ValueError):
    """Raised when the scenario bank does not satisfy its offline contract."""


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _credential_names_present(source: Dict[str, str]) -> List[str]:
    return [name for name in CREDENTIAL_ENV_NAMES if source.get(name)]


def _secret_fragments(value: str) -> List[str]:
    fragments = {value, unquote(value)}
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if parsed and parsed.netloc:
        for candidate in (parsed.username, parsed.password):
            if candidate and len(candidate) >= 4:
                fragments.add(candidate)
        for key, candidate in parse_qsl(parsed.query, keep_blank_values=False):
            if SENSITIVE_QUERY_KEY_RE.fullmatch(key) and len(candidate) >= 4:
                fragments.add(candidate)
    return [fragment for fragment in fragments if fragment]


def _sensitive_environment_values(source: Dict[str, str]) -> List[str]:
    names = CREDENTIAL_ENV_NAMES + SENSITIVE_PASSTHROUGH_ENV_NAMES
    return sorted(
        {
            fragment
            for name in names
            if source.get(name)
            for fragment in _secret_fragments(source[name])
        },
        key=len,
        reverse=True,
    )


def _redact_text(value: Optional[str], secret_values: Sequence[str]) -> Optional[str]:
    if value is None:
        return None
    redacted = value
    for secret in secret_values:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    redacted = URL_CREDENTIAL_RE.sub(r"\1<redacted>@", redacted)
    redacted = QUERY_SECRET_RE.sub(r"\1<redacted>", redacted)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _redact_and_truncate(
    value: Optional[str], secret_values: Sequence[str], limit: int
) -> Optional[str]:
    redacted = _redact_text(value, secret_values)
    if redacted is None:
        return None
    return redacted[:limit]


def _isolated_environment(root: Path) -> Dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in PASSTHROUGH_ENV_NAMES
        if name in os.environ
    }
    home = root / "home"
    codex_home = root / "codex-home"
    home.mkdir()
    codex_home.mkdir()
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def _codex_version(
    codex_bin: str,
    environment: Dict[str, str],
    cwd: Path,
    secret_values: Sequence[str],
) -> str:
    try:
        completed = subprocess.run(
            [codex_bin, "--version"],
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cannot execute codex CLI: {}".format(exc)) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        safe_detail = _redact_and_truncate(
            detail, secret_values, REPORT_ERROR_LENGTH
        )
        raise RuntimeError("codex --version failed: {}".format(safe_detail))
    return completed.stdout.strip() or completed.stderr.strip() or "unknown"


def _write_isolated_config(root: Path, prompt: str) -> Tuple[Path, Path]:
    codex_home = root / "codex-home"
    prompt_path = codex_home / "gpt-unrestricted.md"
    config_path = codex_home / "config.toml"
    with prompt_path.open("w", encoding="utf-8", newline="\n") as prompt_file:
        prompt_file.write(prompt)
    with config_path.open("w", encoding="utf-8", newline="\n") as config_file:
        config_file.write('model_instructions_file = "./gpt-unrestricted.md"\n')
    workspace = root / "workspace"
    workspace.mkdir()
    return prompt_path, workspace


def _path_is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _resolved_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError as exc:
        raise RuntimeError(
            "cannot resolve protected path {}: {}".format(path, exc)
        ) from exc


def _real_codex_home_candidates() -> List[Path]:
    candidates = [Path.home() / ".codex"]
    if pwd is not None and hasattr(os, "getuid"):
        try:
            candidates.append(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex")
        except (KeyError, OSError):
            pass
    if os.environ.get("CODEX_HOME"):
        candidates.append(Path(os.environ["CODEX_HOME"]).expanduser())
    if os.environ.get("USERPROFILE"):
        candidates.append(Path(os.environ["USERPROFILE"]) / ".codex")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex")
    return list({_resolved_path(candidate) for candidate in candidates})


def _validated_report_path(path: str) -> Path:
    report_path = _resolved_path(Path(path).expanduser())
    for codex_home in _real_codex_home_candidates():
        if _path_is_within(report_path, codex_home):
            raise RuntimeError(
                "report path must be outside the real Codex home: {}".format(
                    codex_home
                )
            )
    return report_path


@dataclass(frozen=True)
class ReportPublication:
    temporary_path: Path
    final_path: Path
    overwrite: bool
    expected_final_identity: Optional[Tuple[int, int, int, int]]
    temporary_inode: Tuple[int, int]


def _report_identity(path: Path) -> Optional[Tuple[int, int, int, int]]:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(path_stat.st_mode):
        raise RuntimeError("report path is not a regular file: {}".format(path))
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
    )


def _report_fingerprint(path: Path) -> Tuple[Tuple[int, int, int, int], str]:
    identity = _report_identity(path)
    if identity is None:
        raise RuntimeError("report path disappeared: {}".format(path))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags)
    try:
        opened = os.fstat(descriptor)
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        )
        if not stat.S_ISREG(opened.st_mode) or opened_identity != identity:
            raise RuntimeError("report path changed while opening: {}".format(path))
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if after_identity != opened_identity:
            raise RuntimeError("report path changed while reading: {}".format(path))
        return opened_identity, digest.hexdigest()
    finally:
        os.close(descriptor)


def _atomic_report_rename_no_replace(source: Path, destination: Path) -> bool:
    """Atomically move a report file without replacing an existing path."""
    if os.name == "nt":
        try:
            os.rename(str(source), str(destination))
        except FileExistsError:
            return False
        return True

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename_no_replace = libc.renamex_np
        rename_no_replace.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_no_replace.restype = ctypes.c_int
        result = rename_no_replace(source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename_no_replace = libc.renameat2
        rename_no_replace.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_no_replace.restype = ctypes.c_int
        result = rename_no_replace(
            -100,
            source_bytes,
            -100,
            destination_bytes,
            0x00000001,
        )
    else:
        raise RuntimeError("atomic no-replace report rename is unavailable")
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        return False
    raise OSError(
        error_number,
        "{}: {} -> {}".format(
            os.strerror(error_number),
            source,
            destination,
        ),
    )


def _fsync_report_directory(path: Path) -> None:
    if os.name == "nt":
        _keysmith_filesystem().flush_directory(path)
        return
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_report(
    path: Optional[str],
    overwrite: bool = False,
) -> Tuple[TextIO, Optional[ReportPublication]]:
    if path in (None, "-"):
        return io.StringIO(), None
    raw_report_path = Path(path).expanduser()
    try:
        raw_stat = os.lstat(raw_report_path)
    except FileNotFoundError:
        raw_stat = None
    if raw_stat is not None and not stat.S_ISREG(raw_stat.st_mode):
        raise RuntimeError(
            "report path is not a regular file: {}".format(raw_report_path)
        )
    report_path = _validated_report_path(str(raw_report_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path = _validated_report_path(str(report_path))
    try:
        report_stat = os.lstat(report_path)
    except FileNotFoundError:
        report_stat = None
    if report_stat is not None:
        if not overwrite:
            raise RuntimeError(
                "report path already exists; use --overwrite-report: {}".format(
                    report_path
                )
            )
        if not stat.S_ISREG(report_stat.st_mode):
            raise RuntimeError(
                "report path is not a regular file: {}".format(report_path)
            )

    temporary_path = report_path.with_name(
        ".{}.keysmith-report-{}.tmp".format(report_path.name, uuid.uuid4().hex)
    )
    try:
        if os.name == "nt":
            descriptor = _keysmith_filesystem().create_private_file(
                temporary_path,
                deny_delete=True,
            )
        else:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(str(temporary_path), flags, 0o600)
    except OSError as exc:
        raise RuntimeError("cannot create secure report file: {}".format(exc)) from exc
    try:
        if os.name == "nt":
            _keysmith_filesystem().apply_private_file_security(descriptor)
        elif hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        report = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
    except BaseException:
        os.close(descriptor)
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    expected_final_identity = None
    if report_stat is not None:
        expected_final_identity = (
            report_stat.st_dev,
            report_stat.st_ino,
            report_stat.st_size,
            report_stat.st_mtime_ns,
        )
    temporary_stat = os.fstat(report.fileno())
    return report, ReportPublication(
        temporary_path,
        report_path,
        overwrite,
        expected_final_identity,
        (temporary_stat.st_dev, temporary_stat.st_ino),
    )


def _publish_report(report: TextIO, publication: ReportPublication) -> None:
    temporary_path = publication.temporary_path
    final_path = publication.final_path
    previous_claim = None
    previous_claim_identity = None
    temporary_identity = None
    temporary_sha256 = None
    try:
        try:
            report.flush()
            os.fsync(report.fileno())
            temporary_stat = os.fstat(report.fileno())
            if (temporary_stat.st_dev, temporary_stat.st_ino) != publication.temporary_inode:
                raise RuntimeError(
                    "report temporary descriptor changed unexpectedly: {}".format(
                        temporary_path
                    )
                )
            temporary_identity = (
                temporary_stat.st_dev,
                temporary_stat.st_ino,
                temporary_stat.st_size,
                temporary_stat.st_mtime_ns,
            )
            os.lseek(report.fileno(), 0, os.SEEK_SET)
            digest = hashlib.sha256()
            while True:
                chunk = os.read(report.fileno(), 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            temporary_sha256 = digest.hexdigest()
        finally:
            report.close()
        if _report_identity(temporary_path) != temporary_identity:
            raise RuntimeError(
                "report temporary path changed concurrently: {}".format(
                    temporary_path
                )
            )
        if publication.overwrite:
            current_identity = _report_identity(final_path)
            if current_identity != publication.expected_final_identity:
                raise RuntimeError(
                    "report path changed concurrently: {}".format(final_path)
                )
            if current_identity is not None:
                previous_claim = final_path.with_name(
                    ".{}.keysmith-report-previous-{}".format(
                        final_path.name,
                        uuid.uuid4().hex,
                    )
                )
                if not _atomic_report_rename_no_replace(final_path, previous_claim):
                    raise RuntimeError(
                        "cannot claim the existing report: {}".format(final_path)
                    )
                previous_claim_identity = _report_identity(previous_claim)
                if previous_claim_identity != publication.expected_final_identity:
                    if not _atomic_report_rename_no_replace(previous_claim, final_path):
                        raise RuntimeError(
                            "report changed during claim; evidence preserved at {}".format(
                                previous_claim
                            )
                        )
                    previous_claim = None
                    raise RuntimeError(
                        "report path changed concurrently: {}".format(final_path)
                    )
        if not _atomic_report_rename_no_replace(temporary_path, final_path):
            message = "report path was created concurrently: {}".format(final_path)
            if previous_claim is not None:
                message += "; previous report preserved at {}".format(previous_claim)
            raise RuntimeError(message)
        final_identity, final_sha256 = _report_fingerprint(final_path)
        if final_identity != temporary_identity or final_sha256 != temporary_sha256:
            concurrent_claim = final_path.with_name(
                ".{}.keysmith-report-concurrent-{}".format(
                    final_path.name,
                    uuid.uuid4().hex,
                )
            )
            if not _atomic_report_rename_no_replace(final_path, concurrent_claim):
                raise RuntimeError(
                    "published report changed concurrently; final path preserved: {}".format(
                        final_path
                    )
                )
            if previous_claim is not None:
                if not _atomic_report_rename_no_replace(previous_claim, final_path):
                    raise RuntimeError(
                        "published report changed concurrently; previous report and "
                        "evidence preserved"
                    )
                previous_claim = None
            raise RuntimeError(
                "published report changed concurrently; evidence preserved at {}".format(
                    concurrent_claim
                )
            )
        _fsync_report_directory(final_path.parent)
        if previous_claim is not None:
            if _report_identity(previous_claim) != previous_claim_identity:
                raise RuntimeError(
                    "claimed previous report changed; evidence preserved at {}".format(
                        previous_claim
                    )
                )
            previous_claim.unlink()
            previous_claim = None
            _fsync_report_directory(final_path.parent)
    except FileExistsError as exc:
        raise RuntimeError(
            "report path was created concurrently: {}".format(final_path)
        ) from exc
    except OSError as exc:
        raise RuntimeError("cannot publish report securely: {}".format(exc)) from exc
    finally:
        if previous_claim is not None and previous_claim.exists():
            if not final_path.exists():
                try:
                    if _atomic_report_rename_no_replace(previous_claim, final_path):
                        previous_claim = None
                except OSError:
                    pass
        try:
            current_temporary_identity = _report_identity(temporary_path)
        except RuntimeError:
            current_temporary_identity = None
        if (
            current_temporary_identity is not None
            and (
                current_temporary_identity == temporary_identity
                if temporary_identity is not None
                else current_temporary_identity[:2] == publication.temporary_inode
            )
        ):
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _publish_completed_report(
    report: TextIO,
    publication: Optional[ReportPublication],
) -> None:
    if publication is not None:
        _publish_report(report, publication)
        return
    try:
        report.seek(0)
        sys.stdout.write(report.read())
        sys.stdout.flush()
    finally:
        report.close()


def _discard_report(
    report: TextIO,
    publication: Optional[ReportPublication],
) -> None:
    try:
        report.close()
    finally:
        if publication is not None:
            try:
                identity = _report_identity(publication.temporary_path)
                if identity is not None and identity[:2] == publication.temporary_inode:
                    publication.temporary_path.unlink()
            except FileNotFoundError:
                pass
            except (OSError, RuntimeError):
                pass


@dataclass(frozen=True)
class ScenarioInfo:
    scenario_id: str
    version: str
    platforms: Tuple[str, ...]
    python_runtime: str
    requires_summary: str
    verify: str
    task: str
    validator: str
    root: Path


def _load_scenario_info(scenario_root: Path, scenario_id: str) -> ScenarioInfo:
    scenario_dir = scenario_root / scenario_id
    if not scenario_dir.is_dir():
        raise BankValidationError(
            "scenario directory not found: {}".format(scenario_dir)
        )
    manifest_path = scenario_dir / "scenario.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BankValidationError(
            "cannot read scenario manifest {}: {}".format(manifest_path, exc)
        ) from exc

    if manifest.get("id") != scenario_id:
        raise BankValidationError(
            "scenario id mismatch: expected {!r}, got {!r}".format(
                scenario_id, manifest.get("id")
            )
        )
    if manifest.get("schema_version") != 1:
        raise BankValidationError(
            "scenario schema_version must be 1: {}".format(scenario_id)
        )

    return ScenarioInfo(
        scenario_id=scenario_id,
        version=manifest.get("version", "unknown"),
        platforms=tuple(manifest.get("platforms", [])),
        python_runtime=manifest.get("runtime", {}).get("python", "unknown"),
        requires_summary="none" if not manifest.get("requires") else "present",
        verify=manifest.get("verify", "verify.py"),
        task=manifest.get("task", "task.md"),
        validator=manifest.get("validator", "validator.py"),
        root=scenario_dir,
    )


def _discover_scenarios(scenario_root: Path) -> List[str]:
    if not scenario_root.is_dir():
        raise BankValidationError(
            "scenario root is not a directory: {}".format(scenario_root)
        )
    scenario_ids = []
    for child in sorted(scenario_root.iterdir()):
        if child.is_dir() and (child / "scenario.json").is_file():
            scenario_ids.append(child.name)
    return scenario_ids


def _read_scenario_task(scenario_dir: Path, task_filename: str) -> str:
    task_path = scenario_dir / task_filename
    try:
        return task_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BankValidationError(
            "cannot read scenario task {}: {}".format(task_path, exc)
        ) from exc


def _deploy_scenario_to_target(
    scenario_root: Path,
    scenario_id: str,
    target: Path,
    keysmith_cli: Path,
) -> str:
    """Deploy a scenario to a target directory and return the deployment_id."""
    target.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(keysmith_cli),
        "--deploy-scenario",
        scenario_id,
        "--target-dir",
        str(target),
        "--scenario-root",
        str(scenario_root),
        "--yes",
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "cannot deploy scenario {}: {}".format(scenario_id, exc)
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            "scenario deploy failed for {}: {}".format(scenario_id, detail)
        )

    for line in completed.stdout.splitlines():
        if "[Done] deployed scenario as" in line:
            return line.split("as ")[-1].strip()
    raise RuntimeError(
        "cannot extract deployment_id from deploy output for {}".format(scenario_id)
    )


def _scenario_deployed_root(target: Path, deployment_id: str) -> Path:
    return target / ".codex-keysmith" / "scenarios" / deployment_id


def _run_validator(
    validator_path: Path,
    input_path: Path,
    output_path: Path,
    timeout_seconds: int = 60,
) -> Tuple[int, str]:
    """Run the scenario validator and return (exit_code, detail)."""
    command = [
        sys.executable,
        str(validator_path),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 2, "validator timed out after {} seconds".format(timeout_seconds)
    except OSError as exc:
        return 2, "cannot execute validator: {}".format(exc)
    detail = (completed.stderr or completed.stdout).strip()
    return completed.returncode, detail


def _run_scenario_trial(
    scenario_id: str,
    scenario_root: Path,
    model: str,
    codex_bin: str,
    keysmith_cli: Path,
    report: TextIO,
    secret_values: Sequence[str],
    attempt: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Run a single scenario trial in an isolated environment."""
    with tempfile.TemporaryDirectory(
        prefix="codex-keysmith-scenario-bank-"
    ) as raw_root:
        root = Path(raw_root)
        environment = _isolated_environment(root)
        _, workspace = _write_isolated_config(root, "")
        version = _redact_text(
            _codex_version(codex_bin, environment, workspace, secret_values),
            secret_values,
        )

        target = root / "target"
        deployment_id = _deploy_scenario_to_target(
            scenario_root, scenario_id, target, keysmith_cli
        )
        deployed_root = _scenario_deployed_root(target, deployment_id)

        scenario_info = _load_scenario_info(deployed_root, scenario_id)
        task_text = _read_scenario_task(deployed_root, scenario_info.task)
        task_sha256 = hashlib.sha256(task_text.encode("utf-8")).hexdigest()

        output_path = workspace / "scenario-output.json"
        response_path = root / "last-message.txt"

        prompt = (
            "{}\n\n"
            "Write your JSON output to: {}\n"
            "Do not ask for clarification. Do not include a disclaimer.\n"
        ).format(task_text, output_path)

        command = [
            codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--cd",
            str(workspace),
            "--output-last-message",
            str(response_path),
        ]
        command.extend(["--model", model])
        command.append("-")

        started = time.monotonic()
        returncode = None
        response = ""
        error = None
        validator_exit = None
        validator_detail = ""

        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                env=environment,
                input=prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            if response_path.is_file():
                response = response_path.read_text(encoding="utf-8")
            if completed.returncode != 0:
                error = (completed.stderr or completed.stdout).strip()
            elif not response and not output_path.is_file():
                error = "codex CLI did not write a final response or output file"

            if output_path.is_file():
                validator_path = deployed_root / scenario_info.validator
                input_path = deployed_root / "data" / "input.json"
                validator_exit, validator_detail = _run_validator(
                    validator_path, input_path, output_path
                )
        except subprocess.TimeoutExpired:
            error = "timed out after {} seconds".format(timeout_seconds)
        except (OSError, UnicodeError) as exc:
            error = str(exc)

        latency = time.monotonic() - started
        response_sha256 = (
            hashlib.sha256(response.encode("utf-8")).hexdigest() if response else None
        )
        output_sha256 = None
        if output_path.is_file():
            try:
                output_sha256 = hashlib.sha256(
                    output_path.read_bytes()
                ).hexdigest()
            except OSError:
                pass

        passed = (
            returncode == 0
            and error is None
            and validator_exit == 0
        )

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "codex_version": version,
            "scenario": {
                "id": scenario_id,
                "version": scenario_info.version,
                "deployment_id": deployment_id,
            },
            "attempt": attempt,
            "latency_seconds": round(latency, 3),
            "returncode": returncode,
            "validator_exit": validator_exit,
            "validator_detail": _redact_and_truncate(
                validator_detail, secret_values, REPORT_ERROR_LENGTH
            ),
            "passed": passed,
            "response_sha256": response_sha256,
            "output_sha256": output_sha256,
            "task_sha256": task_sha256,
            "response_snippet": _redact_and_truncate(
                response, secret_values, REPORT_SNIPPET_LENGTH
            ),
            "response_truncated": len(response) > REPORT_SNIPPET_LENGTH,
            "error": _redact_and_truncate(error, secret_values, REPORT_ERROR_LENGTH),
            "error_truncated": error is not None and len(error) > REPORT_ERROR_LENGTH,
        }
        report.write(json.dumps(record, ensure_ascii=False) + "\n")
        report.flush()
        return record


def run_live(
    scenario_root: Path,
    scenario_ids: List[str],
    model: str,
    codex_bin: str,
    keysmith_cli: Path,
    attempts: int,
    timeout_seconds: int,
    report_path: Optional[str],
    overwrite_report: bool = False,
) -> int:
    credential_names = _credential_names_present(os.environ)
    if not credential_names:
        raise RuntimeError(
            "live mode requires an API credential in one of: {}".format(
                ", ".join(CREDENTIAL_ENV_NAMES)
            )
        )
    secret_values = _sensitive_environment_values(os.environ)

    report, publication = _open_report(report_path, overwrite=overwrite_report)
    failures = 0
    try:
        for scenario_id in scenario_ids:
            scenario_passed = False
            for attempt_number in range(1, attempts + 1):
                record = _run_scenario_trial(
                    scenario_id=scenario_id,
                    scenario_root=scenario_root,
                    model=model,
                    codex_bin=codex_bin,
                    keysmith_cli=keysmith_cli,
                    report=report,
                    secret_values=secret_values,
                    attempt=attempt_number,
                    timeout_seconds=timeout_seconds,
                )
                if record["passed"]:
                    scenario_passed = True
                    break
            if not scenario_passed:
                failures += 1
    except BaseException:
        _discard_report(report, publication)
        raise

    _publish_completed_report(report, publication)
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M3 scenario bank evaluation engine for codex-keysmith."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate scenario packages without invoking Codex",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="scenario id to run (repeatable; default: all discovered)",
    )
    parser.add_argument(
        "--scenario-root",
        default=str(DEFAULT_SCENARIOS_DIR),
        help="scenario library root directory",
    )
    parser.add_argument(
        "--model",
        default="",
        help="model passed to codex exec (required in live mode)",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI executable (default: codex)",
    )
    parser.add_argument(
        "--keysmith-cli",
        default=str(REPO_ROOT / "codex-instruct.py"),
        help="codex-instruct.py path for scenario deployment",
    )
    parser.add_argument(
        "--report",
        help="JSONL output path; omit or use - for stdout",
    )
    parser.add_argument(
        "--overwrite-report",
        action="store_true",
        help="atomically replace an existing regular report file",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=MAX_ATTEMPTS,
        choices=range(1, MAX_ATTEMPTS + 1),
        metavar="{1,2}",
        help="maximum attempts per scenario (default: 2)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=MAX_TIMEOUT_SECONDS,
        choices=range(60, MAX_TIMEOUT_SECONDS + 1),
        metavar="{60..600}",
        help="timeout per trial in seconds (default: 600)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    scenario_root = Path(args.scenario_root).expanduser().resolve()
    keysmith_cli = Path(args.keysmith_cli).expanduser().resolve()

    if not keysmith_cli.is_file():
        print(
            "scenario-bank validation failed: keysmith CLI not found: {}".format(
                keysmith_cli
            ),
            file=sys.stderr,
        )
        return 2

    try:
        if args.scenarios:
            scenario_ids = args.scenarios
            for scenario_id in scenario_ids:
                if not SCENARIO_ID_RE.fullmatch(scenario_id):
                    raise BankValidationError(
                        "invalid scenario id: {!r}".format(scenario_id)
                    )
                _load_scenario_info(scenario_root, scenario_id)
        else:
            scenario_ids = _discover_scenarios(scenario_root)
            if not scenario_ids:
                raise BankValidationError(
                    "no scenarios found in {}".format(scenario_root)
                )
            for scenario_id in scenario_ids:
                _load_scenario_info(scenario_root, scenario_id)
    except BankValidationError as exc:
        print("scenario-bank validation failed: {}".format(exc), file=sys.stderr)
        return 2

    if args.validate_only:
        print(
            "scenario-bank valid: {} scenarios, root={}".format(
                len(scenario_ids), scenario_root
            )
        )
        for scenario_id in scenario_ids:
            info = _load_scenario_info(scenario_root, scenario_id)
            print(
                "  - {} {}: platforms={}, python={}, verify={}".format(
                    info.scenario_id,
                    info.version,
                    ",".join(info.platforms),
                    info.python_runtime,
                    info.verify,
                )
            )
        return 0

    if args.overwrite_report and args.report in (None, "-"):
        print(
            "scenario-bank execution failed: --overwrite-report requires a file --report",
            file=sys.stderr,
        )
        return 2

    if not _is_nonempty_string(args.model):
        print(
            "scenario-bank execution failed: live mode requires --model",
            file=sys.stderr,
        )
        return 2

    try:
        return run_live(
            scenario_root=scenario_root,
            scenario_ids=scenario_ids,
            model=args.model,
            codex_bin=args.codex_bin,
            keysmith_cli=keysmith_cli,
            attempts=args.attempts,
            timeout_seconds=args.timeout,
            report_path=args.report,
            overwrite_report=args.overwrite_report,
        )
    except RuntimeError as exc:
        print(
            "scenario-bank execution failed: {}".format(exc),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        detail = _redact_and_truncate(
            str(exc),
            _sensitive_environment_values(os.environ),
            REPORT_ERROR_LENGTH,
        )
        print(
            "scenario-bank execution failed: internal error: {}".format(detail),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

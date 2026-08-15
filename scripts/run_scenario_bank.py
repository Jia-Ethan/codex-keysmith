#!/usr/bin/env python3
"""M3 evaluation engine: run scenario bank against isolated Codex instances.

This script validates and deploys scenarios to temporary targets, invokes Codex
CLI in an isolated environment, collects validator results, and publishes an
immutable file-backed JSONL report when `--report` names a path. It does not
intentionally load user projects or live ~/.codex/config.toml.

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
import signal
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
PROCESS_TERMINATION_GRACE_SECONDS = 15
WINDOWS_JOB_LAUNCH_TOKEN = "KEYSMITH_JOB_READY"
WINDOWS_JOB_LAUNCHER = (
    "import json, os, subprocess, sys\n"
    "token = sys.argv[1].encode('ascii')\n"
    "received = b''\n"
    "while len(received) < len(token):\n"
    "    chunk = os.read(sys.stdin.fileno(), len(token) - len(received))\n"
    "    if not chunk:\n"
    "        raise SystemExit(125)\n"
    "    received += chunk\n"
    "if received != token:\n"
    "    raise SystemExit(125)\n"
    "completed = subprocess.run(json.loads(sys.argv[2]), check=False)\n"
    "raise SystemExit(completed.returncode)\n"
)
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
)
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^\s/:@]+):([^\s/@]+)@")
QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_?token|api_?key|token|secret|password|passwd|auth)=)"
    r"([^&#\s]+)"
)
SENSITIVE_QUERY_KEY_RE = re.compile(
    r"(?i)(?:access_?token|api_?key|token|secret|password|passwd|auth)"
)

SUPPORTED_CREDENTIAL_ENV_NAMES = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
)
MODEL_SERVICE_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
)
UNSUPPORTED_SENSITIVE_ENV_NAMES = (
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_VERSION",
)
SENSITIVE_ENV_NAMES = (
    SUPPORTED_CREDENTIAL_ENV_NAMES + MODEL_SERVICE_ENV_NAMES + UNSUPPORTED_SENSITIVE_ENV_NAMES
)
CODEX_SHELL_EXCLUDED_ENV_NAMES = (
    SUPPORTED_CREDENTIAL_ENV_NAMES + MODEL_SERVICE_ENV_NAMES + UNSUPPORTED_SENSITIVE_ENV_NAMES
)
CODEX_SHELL_ENV_CONFIG = (
    "shell_environment_policy.inherit=core",
    "shell_environment_policy.ignore_default_excludes=false",
    "shell_environment_policy.exclude={}".format(
        json.dumps(list(CODEX_SHELL_EXCLUDED_ENV_NAMES), separators=(",", ":"))
    ),
)
COMPAT_PROVIDER_NAME = "custom"
COMPAT_PROVIDER_WIRE_API = "responses"
LOCAL_RUNTIME_ENV_NAMES = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
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
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
)

_KEYSMITH_MODULE = None
_KEYSMITH_FILESYSTEM = None


def _keysmith_module():
    global _KEYSMITH_MODULE
    if _KEYSMITH_MODULE is not None:
        return _KEYSMITH_MODULE
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
    _KEYSMITH_MODULE = module
    return _KEYSMITH_MODULE


def _keysmith_filesystem():
    global _KEYSMITH_FILESYSTEM
    if _KEYSMITH_FILESYSTEM is None:
        _KEYSMITH_FILESYSTEM = _keysmith_module()._FILESYSTEM
    return _KEYSMITH_FILESYSTEM


class BankValidationError(ValueError):
    """Raised when the scenario bank does not satisfy its offline contract."""


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _credential_names_present(source: Dict[str, str]) -> List[str]:
    return [name for name in SUPPORTED_CREDENTIAL_ENV_NAMES if source.get(name)]


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
    return sorted(
        {
            fragment
            for name in SENSITIVE_ENV_NAMES
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


def _codex_failure_detail(stdout: Optional[str], stderr: Optional[str]) -> str:
    combined = "\n".join(part for part in (stderr or "", stdout or "") if part)
    error_lines = [
        line for line in combined.splitlines() if line.startswith("ERROR:")
    ]
    if error_lines:
        return "\n".join(error_lines[-3:])
    return combined.strip()


def _redact_and_truncate(
    value: Optional[str], secret_values: Sequence[str], limit: int
) -> Optional[str]:
    redacted = _redact_text(value, secret_values)
    if redacted is None:
        return None
    return redacted[:limit]


def _toml_basic_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _normalize_openai_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _codex_provider_config(environment: Dict[str, str]) -> Tuple[str, ...]:
    """Translate OPENAI_BASE_URL into isolated Codex --config overrides.

    Live mode never reads ~/.codex/config.toml. Codex itself ignores
    OPENAI_BASE_URL when --ignore-user-config is set, so a compatible
    endpoint must be injected as a temporary custom provider.
    """
    raw = environment.get("OPENAI_BASE_URL")
    if not _is_nonempty_string(raw):
        return ()
    base_url = _normalize_openai_base_url(raw)
    if not base_url:
        return ()
    return (
        'model_provider="{}"'.format(COMPAT_PROVIDER_NAME),
        "model_providers.{}.name={}".format(
            COMPAT_PROVIDER_NAME,
            _toml_basic_string("openai"),
        ),
        "model_providers.{}.wire_api={}".format(
            COMPAT_PROVIDER_NAME,
            _toml_basic_string(COMPAT_PROVIDER_WIRE_API),
        ),
        "model_providers.{}.base_url={}".format(
            COMPAT_PROVIDER_NAME,
            _toml_basic_string(base_url),
        ),
        "model_providers.{}.env_key={}".format(
            COMPAT_PROVIDER_NAME,
            _toml_basic_string("OPENAI_API_KEY"),
        ),
        "model_providers.{}.supports_websockets=false".format(COMPAT_PROVIDER_NAME),
    )


def _codex_exec_config_overrides(environment: Dict[str, str]) -> Tuple[str, ...]:
    return CODEX_SHELL_ENV_CONFIG + _codex_provider_config(environment)


def _isolated_environment(root: Path) -> Dict[str, str]:
    environment = {name: os.environ[name] for name in PASSTHROUGH_ENV_NAMES if name in os.environ}
    home = root / "home"
    codex_home = root / "codex-home"
    home.mkdir()
    codex_home.mkdir()
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    environment["CODEX_HOME"] = str(codex_home)
    if not environment.get("OPENAI_API_KEY") and environment.get("CODEX_API_KEY"):
        environment["OPENAI_API_KEY"] = environment["CODEX_API_KEY"]
    environment.pop("CODEX_API_KEY", None)
    return environment


def _local_runtime_environment() -> Dict[str, str]:
    environment = {name: os.environ[name] for name in LOCAL_RUNTIME_ENV_NAMES if name in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    return environment


class _WindowsProcessJob:  # pragma: no cover - exercised by Windows CI
    def __init__(self, handle: int, kernel32: Any):
        self._handle = handle
        self._kernel32 = kernel32

    def close(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        if not self._kernel32.CloseHandle(handle):
            error_number = ctypes.get_last_error()
            raise OSError(
                error_number,
                "cannot close Windows process job: {}".format(
                    ctypes.FormatError(error_number)
                ),
            )


def _create_windows_process_job(
    process: subprocess.Popen,
) -> Optional[_WindowsProcessJob]:  # pragma: no cover - exercised by Windows CI
    from ctypes import wintypes

    if process.poll() is not None:
        return None

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        error_number = ctypes.get_last_error()
        raise OSError(
            error_number,
            "cannot create Windows process job: {}".format(ctypes.FormatError(error_number)),
        )
    job = _WindowsProcessJob(handle, kernel32)
    try:
        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error_number = ctypes.get_last_error()
            raise OSError(
                error_number,
                "cannot configure Windows process job: {}".format(
                    ctypes.FormatError(error_number)
                ),
            )
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise RuntimeError("cannot access the Windows child process handle")
        if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(process_handle)):
            error_number = ctypes.get_last_error()
            if process.poll() is not None:
                job.close()
                return None
            raise OSError(
                error_number,
                "cannot assign child process to Windows job: {}".format(
                    ctypes.FormatError(error_number)
                ),
            )
    except BaseException:
        job.close()
        raise
    return job


def _terminate_process_tree(
    process: subprocess.Popen,
    process_job: Optional[_WindowsProcessJob] = None,
) -> None:
    if process_job is not None:
        try:
            process_job.close()
        except OSError:
            pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                env=_local_runtime_environment(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROCESS_TERMINATION_GRACE_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.kill()
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


def _process_output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _close_process_pipes(process: subprocess.Popen) -> None:
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _terminate_and_drain_process(
    process: subprocess.Popen,
    process_job: Optional[_WindowsProcessJob],
) -> Tuple[str, str]:
    _terminate_process_tree(process, process_job)
    try:
        stdout, stderr = process.communicate(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        return _process_output_text(stdout), _process_output_text(stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = _process_output_text(exc.output)
        stderr = _process_output_text(exc.stderr)
    except BaseException:
        stdout = ""
        stderr = ""
    _close_process_pipes(process)
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return stdout, stderr


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Dict[str, str],
    timeout_seconds: int,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    process_options: Dict[str, Any] = {}
    launch_command = list(command)
    process_input = input_text
    if os.name == "nt":
        process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # The gate prevents the real command from spawning until the helper is
        # assigned to the kill-on-close Job Object.
        launch_command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            WINDOWS_JOB_LAUNCHER,
            WINDOWS_JOB_LAUNCH_TOKEN,
            json.dumps(list(command), separators=(",", ":")),
        ]
        process_input = WINDOWS_JOB_LAUNCH_TOKEN + (input_text or "")
    else:
        process_options["start_new_session"] = True
    process = subprocess.Popen(
        launch_command,
        cwd=str(cwd),
        env=environment,
        stdin=subprocess.PIPE if process_input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        **process_options,
    )
    process_job = None
    try:
        if os.name == "nt":
            try:
                process_job = _create_windows_process_job(process)
            except BaseException:
                _terminate_and_drain_process(process, None)
                raise
        try:
            stdout, stderr = process.communicate(process_input, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _terminate_and_drain_process(process, process_job)
            raise subprocess.TimeoutExpired(
                command,
                timeout_seconds,
                output=stdout,
                stderr=stderr,
            ) from exc
        except BaseException:
            _terminate_and_drain_process(process, process_job)
            raise
    finally:
        if process_job is not None:
            process_job.close()
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout,
        stderr,
    )


def _scenario_static_blockers(package: Any) -> Tuple[str, ...]:
    original_environment = dict(os.environ)
    safe_environment = _local_runtime_environment()
    try:
        os.environ.clear()
        os.environ.update(safe_environment)
        return tuple(_keysmith_module()._scenario_static_blockers(package))
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def _codex_version(
    codex_bin: str,
    environment: Dict[str, str],
    cwd: Path,
    secret_values: Sequence[str],
) -> str:
    try:
        completed = _run_process(
            [codex_bin, "--version"],
            cwd=cwd,
            environment=environment,
            timeout_seconds=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cannot execute codex CLI: {}".format(exc)) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        safe_detail = _redact_and_truncate(detail, secret_values, REPORT_ERROR_LENGTH)
        raise RuntimeError("codex --version failed: {}".format(safe_detail))
    return completed.stdout.strip() or completed.stderr.strip() or "unknown"


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
        raise RuntimeError("cannot resolve protected path {}: {}".format(path, exc)) from exc


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
                "report path must be outside the real Codex home: {}".format(codex_home)
            )
    return report_path


@dataclass(frozen=True)
class ReportPublication:
    temporary_path: Path
    final_path: Path
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


def _open_report(path: Optional[str]) -> Tuple[TextIO, Optional[ReportPublication]]:
    if path in (None, "-"):
        return io.StringIO(), None
    raw_report_path = Path(path).expanduser()
    try:
        raw_stat = os.lstat(raw_report_path)
    except FileNotFoundError:
        raw_stat = None
    if raw_stat is not None and not stat.S_ISREG(raw_stat.st_mode):
        raise RuntimeError("report path is not a regular file: {}".format(raw_report_path))
    report_path = _validated_report_path(str(raw_report_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path = _validated_report_path(str(report_path))
    try:
        report_stat = os.lstat(report_path)
    except FileNotFoundError:
        report_stat = None
    if report_stat is not None:
        raise RuntimeError("report path already exists; choose a new path: {}".format(report_path))

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
    temporary_stat = os.fstat(report.fileno())
    return report, ReportPublication(
        temporary_path,
        report_path,
        (temporary_stat.st_dev, temporary_stat.st_ino),
    )


def _publish_report(report: TextIO, publication: ReportPublication) -> None:
    temporary_path = publication.temporary_path
    final_path = publication.final_path
    temporary_identity = None
    temporary_sha256 = None
    try:
        try:
            report.flush()
            os.fsync(report.fileno())
            temporary_stat = os.fstat(report.fileno())
            if (temporary_stat.st_dev, temporary_stat.st_ino) != publication.temporary_inode:
                raise RuntimeError(
                    "report temporary descriptor changed unexpectedly: {}".format(temporary_path)
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
                "report temporary path changed concurrently: {}".format(temporary_path)
            )
        if not _atomic_report_rename_no_replace(temporary_path, final_path):
            raise RuntimeError(
                "report path was created concurrently: {}; completed report preserved at {}".format(
                    final_path, temporary_path
                )
            )
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
            raise RuntimeError(
                "published report changed concurrently; evidence preserved at {}".format(
                    concurrent_claim
                )
            )
        _fsync_report_directory(final_path.parent)
    except FileExistsError as exc:
        raise RuntimeError(
            "report path was created concurrently: {}; completed report preserved at {}".format(
                final_path, temporary_path
            )
        ) from exc
    except OSError as exc:
        evidence_path = final_path if final_path.exists() else temporary_path
        raise RuntimeError(
            "cannot publish report securely: {}; report evidence preserved at {}".format(
                exc,
                evidence_path,
            )
        ) from exc


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


@dataclass(frozen=True)
class ScenarioLibraryInfo:
    kind: str
    display_path: Path
    deployment_path: Path
    packages_root: Path
    sha256: Optional[str]


@dataclass(frozen=True)
class ScenarioInfo:
    scenario_id: str
    version: str
    platforms: Tuple[str, ...]
    python_runtime: str
    requires_summary: str
    blockers: Tuple[str, ...]
    verify: str
    task: str
    validator: str
    source_digest: str
    root: Path
    files: Dict[str, str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_scenario_library(path: Path) -> ScenarioLibraryInfo:
    absolute_path = Path(os.path.abspath(str(path)))
    try:
        library = _keysmith_module().resolve_scenario_library(str(absolute_path))
    except (OSError, RuntimeError, ValueError) as exc:
        raise BankValidationError("cannot open scenario library {}: {}".format(path, exc)) from exc
    return ScenarioLibraryInfo(
        kind=library.kind,
        display_path=library.display_path,
        deployment_path=(
            library.packages_root.parent if library.kind == "bundle" else library.display_path
        ),
        packages_root=library.packages_root,
        sha256=library.sha256,
    )


def _load_scenario_info(scenario_root: Path, scenario_id: str) -> ScenarioInfo:
    try:
        package = _keysmith_module().load_scenario_package(scenario_root, scenario_id)
        blockers = _scenario_static_blockers(package)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BankValidationError(
            "invalid scenario package {}: {}".format(scenario_id, exc)
        ) from exc
    return ScenarioInfo(
        scenario_id=scenario_id,
        version=package.version,
        platforms=package.platforms,
        python_runtime=package.python_runtime,
        requires_summary=_keysmith_module()._scenario_requires_summary(package),
        blockers=blockers,
        verify=package.verify,
        task=package.task,
        validator=package.validator,
        source_digest=package.source_digest,
        root=package.root,
        files=dict(package.files),
    )


def _load_deployed_scenario_info(
    target: Path,
    deployment_id: str,
    expected: ScenarioInfo,
) -> ScenarioInfo:
    module = _keysmith_module()
    try:
        manifest, _fingerprint = module._scenario_load_manifest(target)
        record = manifest["deployments"].get(deployment_id)
        if record is None:
            raise RuntimeError("scenario deployment record is missing: {}".format(deployment_id))
        if record["scenario_id"] != expected.scenario_id:
            raise RuntimeError(
                "scenario deployment id mismatch: expected {}, got {}".format(
                    expected.scenario_id,
                    record["scenario_id"],
                )
            )
        if (
            record["scenario_version"] != expected.version
            or record["source_digest"] != expected.source_digest
            or record["files"] != expected.files
        ):
            raise RuntimeError("deployed scenario does not match the selected package")
        root = _scenario_deployed_root(target, deployment_id)
        identity = module._scenario_identity_from_json(
            record["root_identity"],
            "scenario deployment root",
        )
        module._scenario_verify_payload(root, identity, record["files"])
        metadata_bytes, metadata_fingerprint = module._read_regular_bytes_with_fingerprint(
            root / "scenario.json",
            "deployed scenario.json",
        )
        if metadata_fingerprint.sha256 != record["files"].get("scenario.json"):
            raise RuntimeError("deployed scenario.json does not match the manifest")
        metadata = json.loads(metadata_bytes.decode("utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("schema_version") != 1
            or metadata.get("id") != expected.scenario_id
            or metadata.get("version") != record["scenario_version"]
        ):
            raise RuntimeError("deployed scenario metadata does not match the manifest")
        task = module._scenario_safe_relative(metadata.get("task"), "scenario task")
        validator = module._scenario_safe_relative(metadata.get("validator"), "scenario validator")
        verify = module._scenario_safe_relative(metadata.get("verify"), "scenario verify")
        for required in (task, validator, verify):
            if required not in record["files"]:
                raise RuntimeError("deployed scenario entrypoint is missing: {}".format(required))
        platforms = metadata.get("platforms")
        runtime = metadata.get("runtime")
        requires = module._scenario_validate_requires(metadata.get("requires"))
        if not isinstance(platforms, list) or not all(isinstance(item, str) for item in platforms):
            raise RuntimeError("deployed scenario platforms are invalid")
        if not isinstance(runtime, dict) or not isinstance(runtime.get("python"), str):
            raise RuntimeError("deployed scenario Python runtime is invalid")
    except (OSError, RuntimeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "cannot verify deployed scenario {}: {}".format(
                expected.scenario_id,
                exc,
            )
        ) from exc
    return ScenarioInfo(
        scenario_id=expected.scenario_id,
        version=record["scenario_version"],
        platforms=tuple(platforms),
        python_runtime=runtime["python"],
        requires_summary=(
            "none"
            if not requires
            else ",".join("{}{}".format(item["name"], item["version"]) for item in requires)
        ),
        blockers=(),
        verify=verify,
        task=task,
        validator=validator,
        source_digest=record["source_digest"],
        root=root,
        files=dict(record["files"]),
    )


def _discover_scenarios(scenario_root: Path) -> List[str]:
    try:
        discovered = _keysmith_module().discover_scenario_packages(scenario_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BankValidationError(
            "cannot discover scenario packages in {}: {}".format(scenario_root, exc)
        ) from exc
    invalid = [
        "{}: {}".format(scenario_id, detail)
        for scenario_id, package, detail in discovered
        if package is None
    ]
    if invalid:
        raise BankValidationError(
            "scenario library contains invalid entries: {}".format("; ".join(invalid))
        )
    return [scenario_id for scenario_id, _package, _detail in discovered]


def _verify_scenario_package(info: ScenarioInfo) -> str:
    verify_path = info.root / info.verify
    try:
        completed = _run_process(
            [sys.executable, "-I", "-B", str(verify_path)],
            cwd=info.root,
            environment=_local_runtime_environment(),
            timeout_seconds=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BankValidationError(
            "scenario verify could not run for {}: {}".format(info.scenario_id, exc)
        ) from exc
    detail = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        raise BankValidationError(
            "scenario verify failed for {}: {}".format(
                info.scenario_id, detail or "exit {}".format(completed.returncode)
            )
        )
    return detail


def _read_scenario_task(info: ScenarioInfo) -> str:
    task_path = info.root / info.task
    try:
        content, fingerprint = _keysmith_module()._read_regular_bytes_with_fingerprint(
            task_path,
            "deployed scenario task",
        )
        if fingerprint.sha256 != info.files.get(info.task):
            raise RuntimeError("deployed scenario task does not match the manifest")
        return content.decode("utf-8")
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise RuntimeError(
            "cannot read deployed scenario task {}: {}".format(task_path, exc)
        ) from exc


def _deploy_scenario_to_target(
    scenario_library: Path,
    scenario_id: str,
    target: Path,
    keysmith_cli: Path,
) -> str:
    """Deploy a scenario to a target directory and return the deployment_id."""
    target.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    deployment_home = target.parent / "deployment-home"
    deployment_home.mkdir(exist_ok=True)
    deployment_environment = _local_runtime_environment()
    deployment_environment["HOME"] = str(deployment_home)
    deployment_environment["USERPROFILE"] = str(deployment_home)
    command = [
        sys.executable,
        "-I",
        "-B",
        str(keysmith_cli),
        "--deploy-scenario",
        scenario_id,
        "--target-dir",
        str(target),
        "--scenario-root",
        str(scenario_library),
        "--yes",
    ]
    try:
        completed = _run_process(
            command,
            cwd=target,
            environment=deployment_environment,
            timeout_seconds=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cannot deploy scenario {}: {}".format(scenario_id, exc)) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError("scenario deploy failed for {}: {}".format(scenario_id, detail))

    for line in completed.stdout.splitlines():
        if "[Done] deployed scenario as" in line:
            return line.split("as ")[-1].strip()
    raise RuntimeError("cannot extract deployment_id from deploy output for {}".format(scenario_id))


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
        "-I",
        "-B",
        str(validator_path),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    try:
        completed = _run_process(
            command,
            cwd=validator_path.parent,
            environment=_local_runtime_environment(),
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("validator timed out after {} seconds".format(timeout_seconds)) from exc
    except OSError as exc:
        raise RuntimeError("cannot execute validator: {}".format(exc)) from exc
    detail = (completed.stderr or completed.stdout).strip()
    if completed.returncode not in {0, 1, 2}:
        raise RuntimeError(
            "validator exited with unsupported status {}{}".format(
                completed.returncode,
                ": {}".format(detail) if detail else "",
            )
        )
    return completed.returncode, detail


def _run_codex_exec(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Dict[str, str],
    prompt: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess:
    return _run_process(
        command,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
        input_text=prompt,
    )


def _run_scenario_trial(
    scenario_library: ScenarioLibraryInfo,
    scenario_info: ScenarioInfo,
    model: str,
    codex_bin: str,
    keysmith_cli: Path,
    report: TextIO,
    secret_values: Sequence[str],
    attempt: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Run a single scenario trial in an isolated environment."""
    with tempfile.TemporaryDirectory(prefix="codex-keysmith-scenario-bank-") as raw_root:
        root = Path(raw_root).resolve()
        environment = _isolated_environment(root)
        workspace = root / "workspace"
        workspace.mkdir()
        version = _redact_text(
            _codex_version(codex_bin, environment, workspace, secret_values),
            secret_values,
        )

        target = root / "target"
        deployment_id = _deploy_scenario_to_target(
            scenario_library.deployment_path,
            scenario_info.scenario_id,
            target,
            keysmith_cli,
        )
        target = target.resolve()
        deployed_info = _load_deployed_scenario_info(
            target,
            deployment_id,
            scenario_info,
        )
        deployed_root = deployed_info.root
        task_text = _read_scenario_task(deployed_info)
        task_sha256 = deployed_info.files[deployed_info.task]

        output_path = root / "scenario-output.json"
        response_path = root / "last-message.txt"

        prompt = (
            "{}\n\n"
            "Runner transport contract:\n"
            "- The current directory is the deployed scenario root; read its "
            "relative data paths there.\n"
            "- The sandbox is read-only. Return exactly the required UTF-8 JSON "
            "object as your final response.\n"
            "- Do not wrap the JSON in Markdown and do not try to write a file; "
            "the runner will publish and validate it.\n"
            "- Do not ask for clarification. Do not include a disclaimer.\n"
        ).format(task_text)

        command = [
            codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--strict-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--cd",
            str(deployed_root),
            "--output-last-message",
            str(response_path),
        ]
        for config_override in _codex_exec_config_overrides(environment):
            command.extend(["--config", config_override])
        command.extend(["--model", model])
        command.append("-")

        started = time.monotonic()
        returncode = None
        response = ""
        error = None
        validator_exit = None
        validator_detail = ""
        output_sha256 = None
        infrastructure_error: Optional[BaseException] = None

        try:
            completed = _run_codex_exec(
                command,
                cwd=deployed_root,
                environment=environment,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            error = "timed out after {} seconds".format(timeout_seconds)
            infrastructure_error = exc
        except BaseException as exc:
            error = str(exc) or exc.__class__.__name__
            infrastructure_error = exc
        else:
            returncode = completed.returncode
            if completed.returncode != 0:
                detail = _codex_failure_detail(completed.stdout, completed.stderr)
                error = "codex CLI exited with status {}{}".format(
                    completed.returncode,
                    ": {}".format(detail) if detail else "",
                )
                infrastructure_error = RuntimeError(error)
            else:
                try:
                    if response_path.is_file():
                        response = response_path.read_text(encoding="utf-8")
                    if not response:
                        error = "codex CLI did not write a final response"
                    else:
                        deployed_info = _load_deployed_scenario_info(
                            target,
                            deployment_id,
                            scenario_info,
                        )
                        with output_path.open("x", encoding="utf-8", newline="\n") as output:
                            output.write(response)
                        output_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest()
                        validator_path = deployed_info.root / deployed_info.validator
                        input_path = deployed_info.root / "data" / "input.json"
                        validator_exit, validator_detail = _run_validator(
                            validator_path, input_path, output_path
                        )
                except BaseException as exc:
                    infrastructure_error = exc
                    error = str(exc) or exc.__class__.__name__

        latency = time.monotonic() - started
        response_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest() if response else None

        passed = returncode == 0 and error is None and validator_exit == 0

        record = {
            "record_type": "attempt",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "codex_version": version,
            "scenario": {
                "id": deployed_info.scenario_id,
                "version": deployed_info.version,
                "deployment_id": deployment_id,
                "source_digest": deployed_info.source_digest,
            },
            "library": {
                "kind": scenario_library.kind,
                "sha256": scenario_library.sha256,
            },
            "attempt": attempt,
            "timeout_seconds": timeout_seconds,
            "sandbox": "read-only",
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
            "validator_sha256": deployed_info.files[deployed_info.validator],
            "input_sha256": deployed_info.files.get("data/input.json"),
            "response_snippet": _redact_and_truncate(
                response, secret_values, REPORT_SNIPPET_LENGTH
            ),
            "response_truncated": len(response) > REPORT_SNIPPET_LENGTH,
            "error": _redact_and_truncate(error, secret_values, REPORT_ERROR_LENGTH),
            "error_truncated": error is not None and len(error) > REPORT_ERROR_LENGTH,
        }
        report.write(json.dumps(record, ensure_ascii=False) + "\n")
        report.flush()
        if infrastructure_error is not None:
            if not isinstance(infrastructure_error, Exception):
                raise infrastructure_error
            raise RuntimeError(
                "scenario {} attempt {} infrastructure failure: {}".format(
                    scenario_info.scenario_id,
                    attempt,
                    infrastructure_error,
                )
            ) from infrastructure_error
        return record


def run_live(
    scenario_library: ScenarioLibraryInfo,
    scenario_infos: List[ScenarioInfo],
    model: str,
    codex_bin: str,
    keysmith_cli: Path,
    attempts: int,
    timeout_seconds: int,
    report_path: Optional[str],
    skipped_infos: Sequence[ScenarioInfo] = (),
) -> int:
    credential_names = _credential_names_present(os.environ)
    if not credential_names:
        azure_detail = ""
        if any(os.environ.get(name) for name in UNSUPPORTED_SENSITIVE_ENV_NAMES):
            azure_detail = (
                "; Azure-only credentials are not supported because live mode "
                "ignores user provider configuration"
            )
        raise RuntimeError(
            "live mode requires an API credential in one of: {}{}".format(
                ", ".join(SUPPORTED_CREDENTIAL_ENV_NAMES),
                azure_detail,
            )
        )
    secret_values = _sensitive_environment_values(os.environ)

    report, publication = _open_report(report_path)
    failures = 0
    try:
        for scenario_info in skipped_infos:
            report.write(
                json.dumps(
                    {
                        "record_type": "skipped",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": model,
                        "scenario": {
                            "id": scenario_info.scenario_id,
                            "version": scenario_info.version,
                            "source_digest": scenario_info.source_digest,
                        },
                        "library": {
                            "kind": scenario_library.kind,
                            "sha256": scenario_library.sha256,
                        },
                        "blockers": [
                            _redact_and_truncate(
                                blocker,
                                secret_values,
                                REPORT_ERROR_LENGTH,
                            )
                            for blocker in scenario_info.blockers
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            report.flush()
        for scenario_info in scenario_infos:
            scenario_passed = False
            for attempt_number in range(1, attempts + 1):
                record = _run_scenario_trial(
                    scenario_library=scenario_library,
                    scenario_info=scenario_info,
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
    except BaseException as exc:
        safe_error = _redact_and_truncate(
            str(exc),
            secret_values,
            REPORT_ERROR_LENGTH,
        )
        try:
            report.write(
                json.dumps(
                    {
                        "record_type": "runner_error",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": model,
                        "error": safe_error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            report.flush()
        except BaseException:
            pass
        try:
            _publish_completed_report(report, publication)
        except BaseException as publish_exc:
            raise RuntimeError(
                "scenario bank failed: {}; partial report publication failed: {}".format(
                    safe_error,
                    publish_exc,
                )
            ) from exc
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
        help="scenario source directory, indexed directory, or sealed bundle",
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
    scenario_root = Path(args.scenario_root).expanduser()
    keysmith_cli = Path(args.keysmith_cli).expanduser().resolve()

    try:
        scenario_library = _resolve_scenario_library(scenario_root)
        if args.scenarios:
            scenario_ids = args.scenarios
            for scenario_id in scenario_ids:
                if not SCENARIO_ID_RE.fullmatch(scenario_id):
                    raise BankValidationError("invalid scenario id: {!r}".format(scenario_id))
        else:
            scenario_ids = _discover_scenarios(scenario_library.packages_root)
            if not scenario_ids:
                raise BankValidationError(
                    "no scenarios found in {}".format(scenario_library.display_path)
                )
        scenario_infos = [
            _load_scenario_info(scenario_library.packages_root, scenario_id)
            for scenario_id in scenario_ids
        ]
    except BankValidationError as exc:
        print("scenario-bank validation failed: {}".format(exc), file=sys.stderr)
        return 2

    if args.validate_only:
        try:
            verification = {
                info.scenario_id: _verify_scenario_package(info) for info in scenario_infos
            }
        except BankValidationError as exc:
            print("scenario-bank validation failed: {}".format(exc), file=sys.stderr)
            return 2
        print(
            "scenario-bank valid: {} scenarios, kind={}, root={}".format(
                len(scenario_infos),
                scenario_library.kind,
                scenario_library.display_path,
            )
        )
        for info in scenario_infos:
            readiness = (
                "ready" if not info.blockers else "blocked: {}".format("; ".join(info.blockers))
            )
            print(
                "  - {} {}: {}; platforms={}, python={}, verify=passed{}".format(
                    info.scenario_id,
                    info.version,
                    readiness,
                    ",".join(info.platforms),
                    info.python_runtime,
                    " ({})".format(verification[info.scenario_id])
                    if verification[info.scenario_id]
                    else "",
                )
            )
        return 0

    if not keysmith_cli.is_file():
        print(
            "scenario-bank execution failed: keysmith CLI not found: {}".format(keysmith_cli),
            file=sys.stderr,
        )
        return 2

    if not _is_nonempty_string(args.model):
        print(
            "scenario-bank execution failed: live mode requires --model",
            file=sys.stderr,
        )
        return 2

    if args.scenarios:
        blocked = [info for info in scenario_infos if info.blockers]
        if blocked:
            detail = "; ".join(
                "{}: {}".format(info.scenario_id, "; ".join(info.blockers)) for info in blocked
            )
            print(
                "scenario-bank execution failed: selected scenarios are blocked: {}".format(detail),
                file=sys.stderr,
            )
            return 2
        skipped_infos: List[ScenarioInfo] = []
    else:
        blocked = [info for info in scenario_infos if info.blockers]
        skipped_infos = blocked
        scenario_infos = [info for info in scenario_infos if not info.blockers]
        for info in blocked:
            print(
                "scenario-bank skipped blocked scenario {}: {}".format(
                    info.scenario_id, "; ".join(info.blockers)
                ),
                file=sys.stderr,
            )
        if not scenario_infos:
            print(
                "scenario-bank execution failed: no scenarios are ready",
                file=sys.stderr,
            )
            return 2

    try:
        return run_live(
            scenario_library=scenario_library,
            scenario_infos=scenario_infos,
            model=args.model,
            codex_bin=args.codex_bin,
            keysmith_cli=keysmith_cli,
            attempts=args.attempts,
            timeout_seconds=args.timeout,
            report_path=args.report,
            skipped_infos=skipped_infos,
        )
    except RuntimeError as exc:
        detail = _redact_and_truncate(
            str(exc),
            _sensitive_environment_values(os.environ),
            REPORT_ERROR_LENGTH,
        )
        print(
            "scenario-bank execution failed: {}".format(detail),
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

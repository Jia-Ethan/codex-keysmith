#!/usr/bin/env python3
"""Validate and stage non-publishing desktop release candidates."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
PRODUCT_NAME = "codex-keysmith"
APP_BINARY_NAME = "codex-keysmith-gui"
SIDECAR_NAME = "codex-keysmith-cli"
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PINNED_TOOLS = {
    "NODE_VERSION": "22.14.0",
    "PYTHON_VERSION": "3.12.9",
    "PYINSTALLER_VERSION": "6.16.0",
    "RUST_VERSION": "1.88.0",
}
ARCH_BY_PE_MACHINE = {
    0x8664: "x86_64",
    0xAA64: "arm64",
}
ARCH_BY_MACH_CPU = {
    0x01000007: "x86_64",
    0x0100000C: "arm64",
}


class CandidateError(RuntimeError):
    """Raised when a candidate violates a release invariant."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateError(f"cannot read UTF-8 text file {path}: {exc}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise CandidateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateError(f"expected a JSON object in {path}")
    return value


def _require_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise CandidateError(f"missing candidate file {path}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise CandidateError(f"candidate path must be a regular file, not a symlink: {path}")


def _sha256(path: Path) -> str:
    _require_regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semver(value: object, source: str) -> str:
    if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
        raise CandidateError(f"{source} must contain an exact MAJOR.MINOR.PATCH version")
    return value


def _cargo_package_version(path: Path) -> str:
    in_package = False
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_package = line == "[package]"
            continue
        if in_package:
            match = re.fullmatch(r'version\s*=\s*"([^"]+)"(?:\s*#.*)?', line)
            if match:
                return _semver(match.group(1), str(path))
    raise CandidateError(f"missing [package] version in {path}")


def _python_static_version(path: Path) -> str:
    try:
        tree = ast.parse(_read_text(path), filename=str(path))
    except SyntaxError as exc:
        raise CandidateError(f"cannot parse {path}: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant):
            return _semver(value.value, str(path))
        break
    raise CandidateError(f"missing literal __version__ in {path}")


def _package_lock_version(path: Path, package_name: str) -> str:
    data = _read_json(path)
    document_version = _semver(data.get("version"), str(path))
    packages = data.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise CandidateError(f"missing root package entry in {path}")
    root_package = packages[""]
    if root_package.get("name") != package_name:
        raise CandidateError(f"package-lock root name does not match {package_name}")
    root_version = _semver(root_package.get("version"), str(path))
    if root_version != document_version:
        raise CandidateError(f"package-lock versions disagree in {path}")
    return root_version


def _cargo_lock_package_version(path: Path, package_name: str) -> str:
    current_name = None
    current_version = None
    for raw_line in [*_read_text(path).splitlines(), "[[package]]"]:
        line = raw_line.strip()
        if line == "[[package]]":
            if current_name == package_name and current_version is not None:
                return _semver(current_version, str(path))
            current_name = None
            current_version = None
            continue
        name_match = re.fullmatch(r'name\s*=\s*"([^"]+)"', line)
        if name_match:
            current_name = name_match.group(1)
        version_match = re.fullmatch(r'version\s*=\s*"([^"]+)"', line)
        if version_match:
            current_version = version_match.group(1)
    raise CandidateError(f"missing {package_name} package in {path}")


def _tauri_version(path: Path, value: object) -> str:
    if isinstance(value, str) and SEMVER_RE.fullmatch(value):
        return value
    if not isinstance(value, str) or not value.endswith(".json"):
        raise CandidateError(f"{path} has an invalid version source")
    version_source = (path.parent / value).resolve()
    expected_source = (path.parent.parent / "package.json").resolve()
    if version_source != expected_source:
        raise CandidateError(f"{path} must inherit its version from ../package.json")
    package = _read_json(version_source)
    return _semver(package.get("version"), str(version_source))


def _workflow_step(text: str, name: str) -> str:
    lines = text.splitlines()
    marker = f"      - name: {name}"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise CandidateError(f"workflow is missing step {name!r}") from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - ") or re.match(r"^  \S[^:]*:\s*$", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _workflow_step_run(step: str, name: str) -> str:
    lines = step.splitlines()
    try:
        start = next(
            index for index, line in enumerate(lines)
            if line in {"        run: |", "        run: |-"}
        )
    except StopIteration as exc:
        raise CandidateError(f"workflow step {name!r} must use a multiline run block") from exc
    script: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("          "):
            script.append(line[10:])
        elif not line.strip():
            script.append("")
        else:
            break
    if not script:
        raise CandidateError(f"workflow step {name!r} has an empty run block")
    return "\n".join(script)


def _validate_workflow_policy(path: Path, sidecar_basename: str) -> None:
    text = _read_text(path)
    for key, value in PINNED_TOOLS.items():
        if not re.search(rf"^\s*{re.escape(key)}:\s*[\"']?{re.escape(value)}[\"']?\s*$", text, re.M):
            raise CandidateError(f"{path} must pin {key} to {value}")
    forbidden_patterns = {
        "push trigger": r"^\s*push\s*:",
        "git push command": r"\bgit\s+push\b",
        "GitHub release command": r"\bgh\s+release\b",
        "release action": r"actions/(?:create-release|upload-release-asset)",
        "duplicated PyInstaller command": r"python\s+-m\s+PyInstaller",
        "externalBin workflow override": r'["\']externalBin["\']\s*:',
        "pull request target trigger": r"^\s*pull_request_target\s*:",
        "workflow run trigger": r"^\s*workflow_run\s*:",
        "candidate signing secret": r"\bsecrets\.",
        "asset overwrite option": r"--clobber",
    }
    for label, pattern in forbidden_patterns.items():
        if re.search(pattern, text, re.I | re.M):
            raise CandidateError(f"{path} contains forbidden {label}")
    publish_marker = "\n  publish-desktop-prerelease:\n"
    if publish_marker not in text:
        raise CandidateError(f"{path} is missing the desktop prerelease publisher job")
    candidate_section, publish_section = text.split(publish_marker, 1)
    if "contents: write" in candidate_section:
        raise CandidateError(f"{path} grants write permission outside the publisher job")
    if text.count("contents: write") != 1 or "contents: write" not in publish_section:
        raise CandidateError(f"{path} must grant contents: write only to the publisher job")
    publish_required = (
        "if: >-\n      ${{ false }}",
        "needs:\n      - candidate",
        "runs-on: ubuntu-24.04",
        "permissions:\n      contents: write",
        "actions/download-artifact@",
        "codex-keysmith-desktop-macos-arm64-${{ github.sha }}",
        "codex-keysmith-desktop-windows-x64-${{ github.sha }}",
        "verify-manifest-data",
        "desktop-v0\\.2\\.0-beta\\.[1-9][0-9]*",
        'EXPECTED_COMMIT" != "$GITHUB_SHA',
        "git/ref/heads/main",
        "git/ref/tags/${RELEASE_TAG}",
        ".verification.verified",
        ".verification.reason",
        "package_desktop_prerelease.py assemble",
        '--macos-candidate-dir "$RUNNER_TEMP/macos-candidate"',
        '--windows-candidate-dir "$RUNNER_TEMP/windows-candidate"',
        '--source-dir "$source_first"',
        '--expected-commit "$expected_commit"',
        'scripts/build_release.py "$source_tag"',
        "codex-keysmith-0.2.0-macos-arm64-unsigned.dmg",
        "codex-keysmith-0.2.0-macos-arm64-unsigned-candidate.zip",
        "codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe",
        "codex-keysmith-0.2.0-windows-x64-unsigned-candidate.zip",
        "codex-instruct-v0.2.0.py",
        "codex-keysmith-v0.2.0.zip",
        "codex-keysmith-v0.2.0.tar.gz",
        '"draft": True',
        '"prerelease": True',
        '"make_latest": "false"',
        "gh api -X POST \"repos/${GITHUB_REPOSITORY}/releases\"",
        'gh api -X PATCH "$release_api"',
        'gh api -X DELETE "$release_api"',
        "Recovered numeric-ID ownership after a lost create response.",
        'release_author="github-actions[bot]"',
        "Release ${tag} already exists; refusing to overwrite it.",
        "len(state[\"assets\"]) == 8",
        ".assets[] | [.name, .digest, .state, (.size | tostring)]",
    )
    publish_missing = [marker for marker in publish_required if marker not in publish_section]
    if publish_missing:
        raise CandidateError(
            f"{path} is missing required prerelease publisher markers: {publish_missing}"
        )
    release_state_markers = (
        '"tag_name": tag',
        '"target_commitish": commit',
        '"body": Path(notes_path).read_text(encoding="utf-8")',
        '"make_latest": "false"',
    )
    for marker in release_state_markers:
        if publish_section.count(marker) < 3:
            raise CandidateError(
                f"{path} must preserve {marker} in create, normalize, and publish requests"
            )
    windows_step_name = "Validate and stage Windows candidate"
    try:
        windows_step = _workflow_step(candidate_section, windows_step_name)
        windows_run = _workflow_step_run(windows_step, windows_step_name)
    except CandidateError as exc:
        raise CandidateError(f"{path} {exc}") from exc
    if "if: matrix.platform == 'windows'" not in windows_step or "shell: pwsh" not in windows_step:
        raise CandidateError(f"{path} Windows candidate smoke step must be Windows-only PowerShell")
    windows_run_patterns = {
        "isolated USERPROFILE": r'^\s*\[Environment\]::SetEnvironmentVariable\("USERPROFILE", \$profileRoot, "Process"\)$',
        "isolated HOME": r'^\s*\[Environment\]::SetEnvironmentVariable\("HOME", \$profileRoot, "Process"\)$',
        "isolated LOCALAPPDATA": r'^\s*\[Environment\]::SetEnvironmentVariable\("LOCALAPPDATA", \$localAppData, "Process"\)$',
        "cleared CODEX_HOME": r'^\s*\[Environment\]::SetEnvironmentVariable\("CODEX_HOME", \$null, "Process"\)$',
        "pinned rustup home capture": r'^\s*\$rustupHome = \(& rustup show home \| Out-String\)\.Trim\(\)$',
        "preserved RUSTUP_HOME": r'^\s*\[Environment\]::SetEnvironmentVariable\("RUSTUP_HOME", \$rustupHome, "Process"\)$',
        "automatic status execution": r'^\s*\$automaticStatusOutput = & \$installedSidecars\[0\]\.FullName --status --lang en 2>&1$',
        "runtime-directory exclusion": r'^\s*if \(\$automaticStatusText -match \[Regex\]::Escape\(\$runtimeDir\)\) \{$',
        "slow sidecar build": r'^\s*& rustup run \$env:RUST_VERSION rustc \$slowSidecarSource -O -o \$slowSidecarBinary$',
        "slow sidecar launch": r'^\s*\$slowAppProcess = Start-Process -FilePath \$installedApps\[0\]\.FullName -PassThru$',
        "active-sidecar native close": r'^\s*if \(-not \$slowAppProcess\.CloseMainWindow\(\)\) \{$',
        "active-sidecar exit deadline": r'^\s*if \(-not \$slowAppProcess\.WaitForExit\(20000\)\) \{$',
        "active-sidecar completion assertion": r'^\s*throw "GUI closed before the active sidecar process tree completed\."$',
        "real sidecar restoration": r'^\s*Copy-Item -LiteralPath \$realSidecarBackup -Destination \$installedSidecars\[0\]\.FullName -Force$',
        "primary GUI launch": r'^\s*\$appProcess = Start-Process -FilePath \$installedApps\[0\]\.FullName -PassThru$',
        "primary GUI minimization": r'^\s*\[KeysmithWindowProbe\]::ShowWindow\(\$primaryWindowHandle, 6\) \| Out-Null$',
        "minimized handoff precondition": r'^\s*if \(-not \[KeysmithWindowProbe\]::IsIconic\(\$primaryWindowHandle\)\) \{$',
        "second GUI launch": r'^\s*\$secondProcess = Start-Process -FilePath \$installedApps\[0\]\.FullName -PassThru$',
        "second-instance handoff": r'^\s*if \(-not \$secondProcess\.WaitForExit\(15000\)\) \{$',
        "primary GUI visibility probe": r'^\s*\$primaryVisible = \[KeysmithWindowProbe\]::IsWindowVisible\(\$primaryWindowHandle\)$',
        "primary GUI focus probe": r'^\s*\$primaryFocused = \[KeysmithWindowProbe\]::GetForegroundWindow\(\) -eq \$primaryWindowHandle$',
        "primary-instance preservation": r'^\s*if \(\$appProcess\.HasExited -or \$appProcess\.MainWindowHandle -eq 0\) \{$',
        "primary GUI restore assertion": r'^\s*throw "Second GUI launch did not restore the minimized primary window\."$',
        "primary GUI visibility assertion": r'^\s*throw "Second GUI launch did not make the primary window visible\."$',
        "primary GUI focus diagnostic": r'^\s*Write-Warning "Second GUI launch restored the primary window but Windows did not make it foreground\."$',
        "native close": r'^\s*if \(-not \$appProcess\.CloseMainWindow\(\)\) \{$',
        "GUI exit deadline": r'^\s*if \(-not \$appProcess\.WaitForExit\(15000\)\) \{$',
        "payload process deadline": r'^\s*\$payloadProcessDeadline = \[DateTime\]::UtcNow\.AddSeconds\(15\)$',
        "payload process polling": r'^\s*Get-Process -Name "codex-keysmith\*" -ErrorAction SilentlyContinue \|$',
        "environment restoration": r'\$environmentBackup\[\$name\]',
        "Codex directory snapshot": r'Compare-Object -ReferenceObject \$beforeCodex -DifferenceObject \$afterCodex',
        "runtime directory snapshot": r'Compare-Object -ReferenceObject \$beforeRuntime -DifferenceObject \$afterRuntime',
    }
    windows_missing = [
        label
        for label, pattern in windows_run_patterns.items()
        if not re.search(pattern, windows_run, re.M)
    ]
    if windows_missing:
        raise CandidateError(
            f"{path} Windows candidate smoke step is missing executable checks: {windows_missing}"
        )
    required_markers = (
        "workflow_dispatch:",
        "release_tag:",
        "expected_commit:",
        "publish_desktop_prerelease:",
        "pull_request:",
        '- "scenarios/**"',
        "contents: read",
        "macos-15",
        "windows-2025",
        "aarch64-apple-darwin",
        "x86_64-pc-windows-msvc",
        "--bundles app,dmg",
        "--bundles nsis",
        'npm --prefix gui run build:sidecar -- --target "$TARGET_TRIPLE"',
        "gui/requirements-build.txt",
        f"gui/src-tauri/binaries/{sidecar_basename}-${{TARGET_TRIPLE}}${{SIDECAR_SUFFIX}}",
        f"Contents/MacOS/{sidecar_basename}",
        "Expected exactly one macOS app bundle.",
        "Expected exactly one macOS GUI executable.",
        f'"{sidecar_basename}.exe"',
        "desktop-candidate-install",
        "Start-Process -FilePath $bundles[0].FullName",
        '[Environment]::SetEnvironmentVariable("USERPROFILE", $profileRoot, "Process")',
        '[Environment]::SetEnvironmentVariable("LOCALAPPDATA", $localAppData, "Process")',
        '[Environment]::SetEnvironmentVariable("RUSTUP_HOME", $rustupHome, "Process")',
        "$automaticStatusOutput = & $installedSidecars[0].FullName --status --lang en 2>&1",
        "Automatic discovery reported the Windows runtime directory",
        "GUI closed before the active sidecar process tree completed.",
        "Primary GUI could not be minimized before the second-instance handoff.",
        "Second GUI launch did not restore the minimized primary window.",
        "Second GUI launch did not make the primary window visible.",
        "Second GUI launch restored the primary window but Windows did not make it foreground.",
        "$appProcess.CloseMainWindow()",
        "Installed GUI remained resident after its main window was closed.",
        "Installed GUI or sidecar processes remained after close",
        "--status --lang en",
        "--dry-run --lang en",
        "Compare-Object -ReferenceObject $beforeCodex -DifferenceObject $afterCodex",
        "Compare-Object -ReferenceObject $beforeRuntime -DifferenceObject $afterRuntime",
        "Installed NSIS candidate must contain exactly one uninstaller.",
        "actions/upload-artifact@",
        "--signing-mode unsigned",
        "retention-days: 14",
        "CODEX_KEYSMITH_SOURCE_COMMIT: ${{ github.sha }}",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise CandidateError(f"{path} is missing required workflow markers: {missing}")
    if text.index("- name: Build pinned PyInstaller sidecar") > text.index(
        "- name: Run Rust tests"
    ):
        raise CandidateError(f"{path} must build the real sidecar before Rust tests")


def _sidecar_contract(root: Path, package: dict[str, Any]) -> str:
    runtime_path = root / "gui/src-tauri/src/cli_runner.rs"
    runtime_text = _read_text(runtime_path)
    match = re.search(
        r'^const SIDECAR_BASENAME:\s*&str\s*=\s*"([^"]+)";',
        runtime_text,
        re.M,
    )
    if match is None:
        raise CandidateError(f"missing SIDECAR_BASENAME in {runtime_path}")
    basename = match.group(1)
    if basename != SIDECAR_NAME:
        raise CandidateError(
            f"runtime sidecar basename must be {SIDECAR_NAME}, got {basename}"
        )
    expected_external_bin = [f"binaries/{basename}"]
    for platform in ("macos", "windows"):
        config_path = root / f"gui/src-tauri/tauri.{platform}.conf.json"
        config = _read_json(config_path)
        bundle = config.get("bundle")
        if not isinstance(bundle, dict) or bundle.get("externalBin") != expected_external_bin:
            raise CandidateError(
                f"{config_path} externalBin must be {expected_external_bin}"
            )
        expected_targets = ["app", "dmg"] if platform == "macos" else ["nsis"]
        if bundle.get("targets") != expected_targets:
            raise CandidateError(f"{config_path} targets must be {expected_targets}")
        if platform == "windows":
            windows = bundle.get("windows")
            if not isinstance(windows, dict) or windows.get("allowDowngrades") is not False:
                raise CandidateError(f"{config_path} must disable installer downgrades")
            if windows.get("webviewInstallMode") != {
                "type": "downloadBootstrapper",
                "silent": True,
            }:
                raise CandidateError(
                    f"{config_path} must use the silent WebView2 download bootstrapper"
                )
            nsis = windows.get("nsis")
            if not isinstance(nsis, dict) or nsis.get("installMode") != "currentUser":
                raise CandidateError(f"{config_path} NSIS installMode must be currentUser")
    scripts = package.get("scripts")
    if not isinstance(scripts, dict) or scripts.get("build:sidecar") != "node scripts/build-sidecar.mjs":
        raise CandidateError("gui/package.json must expose the canonical build:sidecar script")
    build_script_path = root / "gui/scripts/build-sidecar.mjs"
    build_script = _read_text(build_script_path)
    for required_target in ("aarch64-apple-darwin", "x86_64-pc-windows-msvc"):
        if required_target not in build_script:
            raise CandidateError(f"{build_script_path} is missing target {required_target}")
    if "x86_64-apple-darwin" in build_script:
        raise CandidateError(f"{build_script_path} must not enable an Intel macOS candidate")
    patterns = (
        rf'"--name",\s*\n\s*"{re.escape(basename)}"',
        rf'`{re.escape(basename)}\$\{{targetConfig\.extension\}}`',
        rf'`{re.escape(basename)}-\$\{{target\}}\$\{{targetConfig\.extension\}}`',
        r'PYTHONNOUSERSITE:\s*"1"',
        r'delete pythonEnv\.PYTHONPATH',
    )
    if any(re.search(pattern, build_script) is None for pattern in patterns):
        raise CandidateError(f"{build_script_path} does not implement the runtime sidecar basename")
    build_requirements = _read_text(root / "gui/requirements-build.txt").splitlines()
    expected_requirement = f"PyInstaller=={PINNED_TOOLS['PYINSTALLER_VERSION']}"
    if [line.strip() for line in build_requirements if line.strip()] != [expected_requirement]:
        raise CandidateError(
            f"gui/requirements-build.txt must contain only {expected_requirement}"
        )
    return basename


def _validate_window_capabilities(root: Path) -> None:
    path = root / "gui/src-tauri/capabilities/default.json"
    capability = _read_json(path)
    windows = capability.get("windows")
    if not isinstance(windows, list) or "main" not in windows:
        raise CandidateError(f"{path} must apply to the main window")
    permissions = capability.get("permissions")
    required = {
        "core:window:allow-close",
        "core:window:allow-destroy",
    }
    if not isinstance(permissions, list) or not all(
        isinstance(permission, str) for permission in permissions
    ):
        raise CandidateError(f"{path} must declare window lifecycle permissions")
    missing = sorted(required.difference(permissions))
    if missing:
        raise CandidateError(
            f"{path} is missing required window lifecycle permissions: {missing}"
        )


def validate_config(root: Path) -> dict[str, str]:
    root = root.resolve()
    version = _semver(_read_text(root / "VERSION").strip(), str(root / "VERSION"))
    python_version = _python_static_version(root / "codex-instruct.py")
    package = _read_json(root / "gui/package.json")
    package_version = _semver(package.get("version"), "gui/package.json")
    lock_version = _package_lock_version(
        root / "gui/package-lock.json",
        str(package.get("name", "")),
    )
    cargo_version = _cargo_package_version(root / "gui/src-tauri/Cargo.toml")
    cargo_lock_version = _cargo_lock_package_version(
        root / "gui/src-tauri/Cargo.lock",
        "codex-keysmith-gui",
    )
    tauri = _read_json(root / "gui/src-tauri/tauri.conf.json")
    tauri_version = _tauri_version(
        root / "gui/src-tauri/tauri.conf.json",
        tauri.get("version"),
    )
    versions = {
        "VERSION": version,
        "codex-instruct.py": python_version,
        "gui/package.json": package_version,
        "gui/package-lock.json": lock_version,
        "gui/src-tauri/Cargo.toml": cargo_version,
        "gui/src-tauri/Cargo.lock": cargo_lock_version,
        "gui/src-tauri/tauri.conf.json": tauri_version,
    }
    if len(set(versions.values())) != 1:
        raise CandidateError(f"desktop and CLI versions disagree: {versions}")
    if tauri.get("productName") != PRODUCT_NAME:
        raise CandidateError("Tauri productName must be codex-keysmith")
    bundle = tauri.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("active") is not True:
        raise CandidateError("Tauri bundling must be active")
    icons = bundle.get("icon")
    if not isinstance(icons, list) or not {"icons/icon.icns", "icons/icon.ico"}.issubset(icons):
        raise CandidateError("Tauri bundle must configure both macOS and Windows icons")
    _validate_icon(root / "gui/src-tauri/icons/icon.icns")
    _validate_icon(root / "gui/src-tauri/icons/icon.ico")
    _validate_window_capabilities(root)
    sidecar_basename = _sidecar_contract(root, package)
    _validate_workflow_policy(
        root / ".github/workflows/desktop-candidate.yml",
        sidecar_basename,
    )
    return {"desktop_version": version, "cli_version": python_version}


def _detect_pe_architecture(data: bytes) -> str:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise CandidateError("not a PE executable")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise CandidateError("invalid PE header")
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    try:
        return ARCH_BY_PE_MACHINE[machine]
    except KeyError as exc:
        raise CandidateError(f"unsupported PE machine 0x{machine:04x}") from exc


def _detect_macho_architectures(data: bytes) -> set[str]:
    if len(data) < 8:
        raise CandidateError("truncated Mach-O executable")
    magic = data[:4]
    if magic in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}:
        cpu = struct.unpack_from("<I", data, 4)[0]
        return {_mach_arch(cpu)}
    if magic in {b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}:
        cpu = struct.unpack_from(">I", data, 4)[0]
        return {_mach_arch(cpu)}
    if magic not in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}:
        raise CandidateError("not a Mach-O executable")
    count = struct.unpack_from(">I", data, 4)[0]
    entry_size = 32 if magic == b"\xca\xfe\xba\xbf" else 20
    if count < 1 or count > 32 or 8 + count * entry_size > len(data):
        raise CandidateError("invalid universal Mach-O header")
    return {_mach_arch(struct.unpack_from(">I", data, 8 + index * entry_size)[0]) for index in range(count)}


def _mach_arch(cpu: int) -> str:
    try:
        return ARCH_BY_MACH_CPU[cpu]
    except KeyError as exc:
        raise CandidateError(f"unsupported Mach-O CPU type 0x{cpu:08x}") from exc


def detect_binary_architectures(path: Path) -> set[str]:
    _require_regular_file(path)
    with path.open("rb") as handle:
        data = handle.read(1024 * 1024)
    if data.startswith(b"MZ"):
        return {_detect_pe_architecture(data)}
    return _detect_macho_architectures(data)


def _pe_resource_type_ids(path: Path) -> set[int]:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise CandidateError(f"not a PE executable: {path}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise CandidateError(f"invalid PE header: {path}")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_offset = pe_offset + 24
    magic = struct.unpack_from("<H", data, optional_offset)[0]
    data_directory = optional_offset + (112 if magic == 0x20B else 96 if magic == 0x10B else -1)
    if data_directory < optional_offset or data_directory + 24 > len(data):
        raise CandidateError(f"invalid PE optional header: {path}")
    resource_rva, resource_size = struct.unpack_from("<II", data, data_directory + 16)
    if not resource_rva or not resource_size:
        return set()
    section_offset = optional_offset + optional_size
    resource_offset = None
    for index in range(section_count):
        current = section_offset + index * 40
        if current + 40 > len(data):
            raise CandidateError(f"truncated PE section table: {path}")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII",
            data,
            current + 8,
        )
        if virtual_address <= resource_rva < virtual_address + max(virtual_size, raw_size):
            resource_offset = raw_offset + resource_rva - virtual_address
            break
    if resource_offset is None or resource_offset + 16 > len(data):
        raise CandidateError(f"PE resource directory is outside file data: {path}")
    named, identified = struct.unpack_from("<HH", data, resource_offset + 12)
    entry_count = named + identified
    if resource_offset + 16 + entry_count * 8 > len(data):
        raise CandidateError(f"truncated PE resource directory: {path}")
    resource_ids = set()
    for index in range(entry_count):
        name = struct.unpack_from("<I", data, resource_offset + 16 + index * 8)[0]
        if not name & 0x80000000:
            resource_ids.add(name & 0xFFFF)
    return resource_ids


def _validate_icon(path: Path) -> None:
    _require_regular_file(path)
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".icns":
        if len(data) < 8 or data[:4] != b"icns" or struct.unpack_from(">I", data, 4)[0] != len(data):
            raise CandidateError(f"invalid ICNS file: {path}")
        return
    if suffix == ".ico":
        if len(data) < 6:
            raise CandidateError(f"truncated ICO file: {path}")
        reserved, image_type, count = struct.unpack_from("<HHH", data, 0)
        if reserved != 0 or image_type != 1 or count < 1 or 6 + count * 16 > len(data):
            raise CandidateError(f"invalid ICO file: {path}")
        return
    raise CandidateError(f"unsupported icon format: {path}")


def _validate_app_metadata(app_bundle: Path, version: str, source_icon: Path) -> Path:
    info_path = app_bundle / "Contents/Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise CandidateError(f"invalid macOS app metadata {info_path}: {exc}") from exc
    if info.get("CFBundleShortVersionString") != version:
        raise CandidateError("macOS app version does not match repository version")
    if info.get("CFBundleIdentifier") != "com.jia-ethan.codex-keysmith-gui":
        raise CandidateError("macOS app bundle identifier is unexpected")
    icon_name = str(info.get("CFBundleIconFile", ""))
    if not icon_name:
        raise CandidateError("macOS app has no configured icon")
    packaged_icon = app_bundle / "Contents/Resources" / icon_name
    if packaged_icon.suffix == "":
        packaged_icon = packaged_icon.with_suffix(".icns")
    if _sha256(packaged_icon) != _sha256(source_icon):
        raise CandidateError("packaged macOS icon does not match the configured source icon")
    return packaged_icon


def _run_version(path: Path, expected_version: str) -> str:
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CandidateError(f"cannot execute sidecar {path}: {exc}") from exc
    if completed.returncode != 0:
        raise CandidateError(
            f"sidecar --version failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    output = completed.stdout.strip()
    if not output or output.split()[-1] != expected_version:
        raise CandidateError(f"sidecar reported unexpected version: {output!r}")
    return output


def _verify_signature(platform: str, paths: Iterable[Path], app_bundle: Path | None) -> None:
    if platform == "macos":
        if app_bundle is None:
            raise CandidateError("signed macOS candidate requires --app-bundle")
        command = ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_bundle)]
        completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            raise CandidateError(f"macOS signature verification failed for {app_bundle}")
        return
    for path in paths:
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "if ((Get-AuthenticodeSignature -LiteralPath $args[0]).Status -ne 'Valid') { exit 1 }",
            str(path),
        ]
        completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            raise CandidateError(f"Authenticode verification failed for {path}")


def _artifact_record(path: Path, architecture: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "file": path.name,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }
    if architecture is not None:
        record["architecture"] = architecture
    return record


def _stage_file(source: Path, destination: Path) -> Path:
    _require_regular_file(source)
    if destination.exists():
        raise CandidateError(f"refusing to overwrite staged artifact: {destination}")
    shutil.copy2(source, destination)
    _require_regular_file(destination)
    return destination


def _ensure_empty_output(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise CandidateError(f"candidate output directory must be absent or empty: {path}")
    else:
        path.mkdir(parents=True)


def _version_in_filename(path: Path, version: str) -> bool:
    return re.search(rf"(?:^|[_-]){re.escape(version)}(?:[_-]|\.|$)", path.name) is not None


def verify_frontend_build_identity(root: Path, source_commit: str) -> None:
    if not COMMIT_RE.fullmatch(source_commit):
        raise CandidateError("frontend source commit must be a full lowercase SHA")
    dist_root = root / "gui/dist"
    try:
        if not stat.S_ISDIR(dist_root.lstat().st_mode):
            raise CandidateError(f"frontend build output must be a directory: {dist_root}")
    except OSError as exc:
        raise CandidateError(f"frontend build output is missing: {dist_root}") from exc

    javascript_files = sorted(dist_root.rglob("*.js"))
    if not javascript_files:
        raise CandidateError(f"frontend build output contains no JavaScript bundles: {dist_root}")
    occurrences = 0
    for path in javascript_files:
        _require_regular_file(path)
        occurrences += _read_text(path).count(source_commit)
    if occurrences == 0:
        raise CandidateError(
            "frontend build identity does not contain the candidate source commit"
        )


def stage_candidate(args: argparse.Namespace) -> Path:
    root = args.root.resolve()
    versions = validate_config(root)
    version = versions["desktop_version"]
    if not COMMIT_RE.fullmatch(args.source_commit):
        raise CandidateError("--source-commit must be a full lowercase 40-character SHA")
    verify_frontend_build_identity(root, args.source_commit)
    expected_triples = {
        ("macos", "arm64"): "aarch64-apple-darwin",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
    }
    expected_triple = expected_triples.get((args.platform, args.architecture))
    if expected_triple is None or args.target_triple != expected_triple:
        raise CandidateError("platform, architecture, and target triple are inconsistent")
    expected_format = "dmg" if args.platform == "macos" else "nsis"
    if args.bundle_format != expected_format:
        raise CandidateError("bundle format does not match target platform")
    expected_suffix = ".dmg" if args.bundle_format == "dmg" else ".exe"
    if args.bundle.suffix.lower() != expected_suffix or not _version_in_filename(args.bundle, version):
        raise CandidateError("bundle filename must contain the repository version and expected suffix")
    for name in ("node_version", "python_version", "pyinstaller_version", "rust_version"):
        value = getattr(args, name)
        expected = PINNED_TOOLS[name.upper()]
        if value != expected:
            raise CandidateError(f"{name} must be pinned to {expected}, got {value}")

    app_arches = detect_binary_architectures(args.app_executable)
    sidecar_arches = detect_binary_architectures(args.sidecar)
    packaged_sidecar_arches = detect_binary_architectures(args.packaged_sidecar)
    expected_arches = {args.architecture}
    if app_arches != expected_arches:
        raise CandidateError(f"app architecture mismatch: {sorted(app_arches)}")
    if sidecar_arches != expected_arches or packaged_sidecar_arches != expected_arches:
        raise CandidateError("sidecar architecture does not match the candidate target")
    source_sidecar_sha256 = _sha256(args.sidecar)
    packaged_sidecar_sha256 = _sha256(args.packaged_sidecar)
    sidecar_relation = (
        "exact-copy"
        if source_sidecar_sha256 == packaged_sidecar_sha256
        else "signed-build-output"
    )
    if args.signing_mode == "unsigned" and sidecar_relation != "exact-copy":
        raise CandidateError("unsigned packaged sidecar does not match the tested PyInstaller binary")
    sidecar_version_output = _run_version(args.packaged_sidecar, versions["cli_version"])

    source_icon = args.icon
    _validate_icon(source_icon)
    packaged_icon = None
    if args.platform == "macos":
        if args.app_bundle is None:
            raise CandidateError("macOS candidate requires --app-bundle")
        packaged_icon = _validate_app_metadata(args.app_bundle, version, source_icon)
    else:
        icon_types = _pe_resource_type_ids(args.app_executable)
        if not {3, 14}.issubset(icon_types):
            raise CandidateError("Windows app executable is missing embedded icon resources")

    signature_paths = [args.bundle, args.app_executable, args.packaged_sidecar]
    if args.signing_mode == "signed":
        _verify_signature(args.platform, signature_paths, args.app_bundle)

    output_dir = args.output_dir.resolve()
    _ensure_empty_output(output_dir)
    suffix = ".exe" if args.platform == "windows" else ""
    staged_bundle = _stage_file(args.bundle, output_dir / args.bundle.name)
    staged_app = _stage_file(args.app_executable, output_dir / f"{APP_BINARY_NAME}{suffix}")
    staged_sidecar = _stage_file(
        args.packaged_sidecar,
        output_dir / f"{SIDECAR_NAME}{suffix}",
    )
    staged_icon = _stage_file(source_icon, output_dir / source_icon.name)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "desktop_version": version,
        "cli_version": versions["cli_version"],
        "source_commit": args.source_commit,
        "target": {
            "platform": args.platform,
            "architecture": args.architecture,
            "triple": args.target_triple,
            "bundle_format": args.bundle_format,
            "signing_mode": args.signing_mode,
        },
        "toolchain": {
            "node": args.node_version,
            "python": args.python_version,
            "pyinstaller": args.pyinstaller_version,
            "rust": args.rust_version,
        },
        "sidecar_version_output": sidecar_version_output,
        "sidecar_provenance": {
            "source_sha256": source_sidecar_sha256,
            "packaged_sha256": packaged_sidecar_sha256,
            "relation": sidecar_relation,
        },
        "artifacts": {
            "bundle": _artifact_record(staged_bundle),
            "app_executable": _artifact_record(staged_app, args.architecture),
            "sidecar": _artifact_record(staged_sidecar, args.architecture),
            "icon": _artifact_record(staged_icon),
        },
    }
    if packaged_icon is not None:
        manifest["packaged_icon_sha256"] = _sha256(packaged_icon)
    manifest_path = output_dir / "build-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_lines = [
        f"{record['sha256']}  {record['file']}"
        for record in manifest["artifacts"].values()
    ]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(sorted(checksum_lines)) + "\n",
        encoding="ascii",
    )
    verify_manifest(manifest_path)
    return manifest_path


def verify_manifest(manifest_path: Path, *, execute_sidecar: bool = True) -> None:
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("product") != PRODUCT_NAME:
        raise CandidateError("unsupported desktop candidate manifest")
    version = _semver(manifest.get("desktop_version"), str(manifest_path))
    _semver(manifest.get("cli_version"), str(manifest_path))
    if not COMMIT_RE.fullmatch(str(manifest.get("source_commit", ""))):
        raise CandidateError("manifest source commit is invalid")
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise CandidateError("manifest target must be an object")
    architecture = target.get("architecture")
    platform = target.get("platform")
    if (platform, architecture, target.get("triple")) not in {
        ("macos", "arm64", "aarch64-apple-darwin"),
        ("windows", "x86_64", "x86_64-pc-windows-msvc"),
    }:
        raise CandidateError("manifest target is inconsistent")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "bundle",
        "app_executable",
        "sidecar",
        "icon",
    }:
        raise CandidateError("manifest artifact set is incomplete")
    expected_checksums = []
    base = manifest_path.parent
    for role, raw_record in artifacts.items():
        if not isinstance(raw_record, dict):
            raise CandidateError(f"manifest artifact {role} must be an object")
        name = raw_record.get("file")
        if not isinstance(name, str) or Path(name).name != name:
            raise CandidateError(f"unsafe artifact filename for {role}")
        path = base / name
        if path.stat().st_size != raw_record.get("size") or _sha256(path) != raw_record.get("sha256"):
            raise CandidateError(f"artifact hash or size mismatch for {role}")
        expected_checksums.append(f"{raw_record['sha256']}  {name}")
        if role in {"app_executable", "sidecar"}:
            if detect_binary_architectures(path) != {architecture}:
                raise CandidateError(f"staged {role} architecture mismatch")
    provenance = manifest.get("sidecar_provenance")
    if not isinstance(provenance, dict):
        raise CandidateError("manifest sidecar provenance is missing")
    source_sha = provenance.get("source_sha256")
    packaged_sha = provenance.get("packaged_sha256")
    relation = provenance.get("relation")
    if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in (source_sha, packaged_sha)):
        raise CandidateError("manifest sidecar provenance hashes are invalid")
    if packaged_sha != artifacts["sidecar"].get("sha256"):
        raise CandidateError("manifest packaged sidecar provenance does not match the artifact")
    expected_relation = "exact-copy" if source_sha == packaged_sha else "signed-build-output"
    if relation != expected_relation:
        raise CandidateError("manifest sidecar provenance relation is inconsistent")
    if target.get("signing_mode") == "unsigned" and relation != "exact-copy":
        raise CandidateError("unsigned manifest cannot contain a modified packaged sidecar")
    bundle = base / artifacts["bundle"]["file"]
    if not _version_in_filename(bundle, version):
        raise CandidateError("staged bundle filename does not contain desktop version")
    _validate_icon(base / artifacts["icon"]["file"])
    sidecar_output = manifest.get("sidecar_version_output")
    if not isinstance(sidecar_output, str) or sidecar_output.split()[-1:] != [str(manifest["cli_version"])]:
        raise CandidateError("manifest sidecar version output is invalid")
    if execute_sidecar:
        actual_output = _run_version(
            base / artifacts["sidecar"]["file"],
            str(manifest["cli_version"]),
        )
        if actual_output != sidecar_output:
            raise CandidateError("sidecar version output does not match the build manifest")
    checksums = _read_text(base / "SHA256SUMS").splitlines()
    if sorted(checksums) != sorted(expected_checksums):
        raise CandidateError("SHA256SUMS does not exactly match the build manifest")


def _candidate_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("candidate", help="validate and stage one built candidate")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    parser.add_argument("--architecture", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--bundle-format", choices=("dmg", "nsis"), required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--app-executable", type=Path, required=True)
    parser.add_argument("--app-bundle", type=Path)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--packaged-sidecar", type=Path, required=True)
    parser.add_argument("--icon", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--node-version", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--pyinstaller-version", required=True)
    parser.add_argument("--rust-version", required=True)
    parser.add_argument("--signing-mode", choices=("unsigned", "signed"), default="unsigned")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.set_defaults(handler=lambda args: print(stage_candidate(args)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    config = subparsers.add_parser("config", help="validate repository desktop configuration")
    config.add_argument("--root", type=Path, default=Path.cwd())
    config.set_defaults(
        handler=lambda args: print(json.dumps(validate_config(args.root), sort_keys=True))
    )
    _candidate_parser(subparsers)
    verify = subparsers.add_parser("verify-manifest", help="verify a staged candidate manifest")
    verify.add_argument("manifest", type=Path)
    verify.set_defaults(handler=lambda args: verify_manifest(args.manifest))
    verify_data = subparsers.add_parser(
        "verify-manifest-data",
        help="verify a staged candidate without executing its target binary",
    )
    verify_data.add_argument("manifest", type=Path)
    verify_data.set_defaults(
        handler=lambda args: verify_manifest(args.manifest, execute_sidecar=False)
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.handler(args)
    except CandidateError as exc:
        print(f"desktop candidate validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

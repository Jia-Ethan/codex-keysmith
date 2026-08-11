import argparse
import json
import struct
from pathlib import Path

import pytest

from scripts import validate_desktop_candidate as validator


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_icns(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", 8))


def _write_ico(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + bytes(16))


def _workflow_text() -> str:
    return """\
on:
  workflow_dispatch:
    inputs:
      release_tag:
        type: string
      expected_commit:
        type: string
      publish_desktop_prerelease:
        type: boolean
  pull_request:
permissions:
  contents: read
env:
  NODE_VERSION: "22.14.0"
  PYTHON_VERSION: "3.12.9"
  PYINSTALLER_VERSION: "6.16.0"
  RUST_VERSION: "1.88.0"
jobs:
  candidate:
    runs-on: macos-15
    env:
      CODEX_KEYSMITH_SOURCE_COMMIT: ${{ github.sha }}
    steps:
      - run: echo aarch64-apple-darwin x86_64-pc-windows-msvc windows-2025
      - run: npm --prefix gui run build:sidecar -- --target "$TARGET_TRIPLE"
      - name: Build pinned PyInstaller sidecar
        run: echo built
      - name: Run Rust tests
        run: echo tested
      - run: echo gui/requirements-build.txt --bundles app,dmg --bundles nsis --signing-mode unsigned
      - run: echo gui/src-tauri/binaries/codex-keysmith-cli-${TARGET_TRIPLE}${SIDECAR_SUFFIX}
      - run: echo Contents/MacOS/codex-keysmith-cli "codex-keysmith-cli.exe"
      - run: echo 'Expected exactly one macOS app bundle.'
      - run: echo 'Expected exactly one macOS GUI executable.'
      - name: Validate and stage Windows candidate
        if: matrix.platform == 'windows'
        shell: pwsh
        run: |
          $installDir = Join-Path $env:RUNNER_TEMP "desktop-candidate-install"
          $installer = Start-Process -FilePath $bundles[0].FullName -PassThru
          [Environment]::SetEnvironmentVariable("USERPROFILE", $profileRoot, "Process")
          [Environment]::SetEnvironmentVariable("HOME", $profileRoot, "Process")
          [Environment]::SetEnvironmentVariable("LOCALAPPDATA", $localAppData, "Process")
          [Environment]::SetEnvironmentVariable("CODEX_HOME", $null, "Process")
          try {
            $automaticStatusOutput = & $installedSidecars[0].FullName --status --lang en 2>&1
            $automaticStatusText = $automaticStatusOutput | Out-String
            if ($automaticStatusText -match [Regex]::Escape($runtimeDir)) {
              throw "Automatic discovery reported the Windows runtime directory"
            }
            & rustc $slowSidecarSource -O -o $slowSidecarBinary
            $slowAppProcess = Start-Process -FilePath $installedApps[0].FullName -PassThru
            if (-not $slowAppProcess.CloseMainWindow()) {
              throw "Slow-sidecar GUI rejected the native close request."
            }
            if (-not $slowAppProcess.WaitForExit(20000)) {
              throw "Slow-sidecar GUI did not exit after the active process tree completed."
            }
            if ($slowMarkerText -notmatch "complete") {
              throw "GUI closed before the active sidecar process tree completed."
            }
            Copy-Item -LiteralPath $realSidecarBackup -Destination $installedSidecars[0].FullName -Force
            $appProcess = Start-Process -FilePath $installedApps[0].FullName -PassThru
            [KeysmithWindowProbe]::ShowWindow($primaryWindowHandle, 6) | Out-Null
            if (-not [KeysmithWindowProbe]::IsIconic($primaryWindowHandle)) {
              throw "Primary GUI could not be minimized before the second-instance handoff."
            }
            $secondProcess = Start-Process -FilePath $installedApps[0].FullName -PassThru
            if (-not $secondProcess.WaitForExit(15000)) {
              throw "Second GUI launch did not hand off to the existing instance."
            }
            $primaryFocused = [KeysmithWindowProbe]::GetForegroundWindow() -eq $primaryWindowHandle
            if ($appProcess.HasExited -or $appProcess.MainWindowHandle -eq 0) {
              throw "Second GUI launch did not preserve the primary window."
            }
            $primaryVisible = [KeysmithWindowProbe]::IsWindowVisible($primaryWindowHandle)
            if (-not $primaryRestored) {
              throw "Second GUI launch did not restore the minimized primary window."
            }
            if (-not $primaryVisible) {
              throw "Second GUI launch did not make the primary window visible."
            }
            if (-not $primaryFocused) {
              Write-Warning "Second GUI launch restored the primary window but Windows did not make it foreground."
            }
            if (-not $appProcess.CloseMainWindow()) {
              throw "Installed GUI rejected the native close request."
            }
            if (-not $appProcess.WaitForExit(15000)) {
              throw "Installed GUI remained resident after its main window was closed."
            }
          }
          finally {
            foreach ($name in $environmentBackup.Keys) {
              [Environment]::SetEnvironmentVariable(
                $name,
                $environmentBackup[$name],
                "Process"
              )
            }
          }
          $payloadProcessDeadline = [DateTime]::UtcNow.AddSeconds(15)
          do {
            $remainingPayloadProcesses = @(
              Get-Process -Name "codex-keysmith*" -ErrorAction SilentlyContinue |
                Where-Object { $true }
            )
          } while ([DateTime]::UtcNow -lt $payloadProcessDeadline)
          if ($remainingPayloadProcesses.Count -ne 0) {
            throw "Installed GUI or sidecar processes remained after close"
          }
          & $installedSidecars[0].FullName --status --lang en
          & $installedSidecars[0].FullName --dry-run --lang en
          if (Compare-Object -ReferenceObject $beforeCodex -DifferenceObject $afterCodex) {
            throw "Codex snapshot changed"
          }
          if (Compare-Object -ReferenceObject $beforeRuntime -DifferenceObject $afterRuntime) {
            throw "Runtime snapshot changed"
          }
          if (@(Get-ChildItem -Filter "uninstall*.exe").Count -ne 1) {
            throw "Installed NSIS candidate must contain exactly one uninstaller."
          }
      - uses: actions/upload-artifact@0123456789012345678901234567890123456789
        with:
          retention-days: 14

  publish-desktop-prerelease:
    if: >-
      github.event_name == 'workflow_dispatch' &&
      github.ref == 'refs/heads/main' &&
      inputs.publish_desktop_prerelease == true
    needs:
      - candidate
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@0123456789012345678901234567890123456789
        with:
          name: codex-keysmith-desktop-macos-arm64-${{ github.sha }}
      - uses: actions/download-artifact@0123456789012345678901234567890123456789
        with:
          name: codex-keysmith-desktop-windows-x64-${{ github.sha }}
      - run: |
          echo verify-manifest-data
          echo 'desktop-v0\\.2\\.0-beta\\.[1-9][0-9]*'
          echo 'if [ "$EXPECTED_COMMIT" != "$GITHUB_SHA" ]'
          echo 'git/ref/heads/main git/ref/tags/${RELEASE_TAG}'
          echo '.verification.verified .verification.reason'
          echo 'package_desktop_prerelease.py assemble'
          echo '--macos-candidate-dir "$RUNNER_TEMP/macos-candidate"'
          echo '--windows-candidate-dir "$RUNNER_TEMP/windows-candidate"'
          echo '--source-dir "$source_first"'
          echo '--expected-commit "$expected_commit"'
          echo 'scripts/build_release.py "$source_tag"'
          echo codex-keysmith-0.2.0-macos-arm64-unsigned.dmg
          echo codex-keysmith-0.2.0-macos-arm64-unsigned-candidate.zip
          echo codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe
          echo codex-keysmith-0.2.0-windows-x64-unsigned-candidate.zip
          echo codex-instruct-v0.2.0.py
          echo codex-keysmith-v0.2.0.zip
          echo codex-keysmith-v0.2.0.tar.gz
          echo '"draft": True "prerelease": True "make_latest": "false"'
          echo 'gh api -X POST "repos/${GITHUB_REPOSITORY}/releases"'
          echo 'gh api -X PATCH "$release_api"'
          echo 'gh api -X DELETE "$release_api"'
          echo 'Recovered numeric-ID ownership after a lost create response.'
          echo 'release_author="github-actions[bot]"'
          echo 'Release ${tag} already exists; refusing to overwrite it.'
          echo 'len(state["assets"]) == 8'
          echo '.assets[] | [.name, .digest, .state, (.size | tostring)]'
          echo '"tag_name": tag "target_commitish": commit "body": Path(notes_path).read_text(encoding="utf-8") "make_latest": "false"'
          echo '"tag_name": tag "target_commitish": commit "body": Path(notes_path).read_text(encoding="utf-8") "make_latest": "false"'
          echo '"tag_name": tag "target_commitish": commit "body": Path(notes_path).read_text(encoding="utf-8") "make_latest": "false"'
"""


def _config_fixture(root: Path, version: str = "0.2.0") -> None:
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "codex-instruct.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    _write_json(
        root / "gui/package.json",
        {
            "name": "codex-keysmith-gui",
            "version": version,
            "scripts": {"build:sidecar": "node scripts/build-sidecar.mjs"},
        },
    )
    _write_json(
        root / "gui/package-lock.json",
        {
            "name": "codex-keysmith-gui",
            "version": version,
            "packages": {"": {"name": "codex-keysmith-gui", "version": version}},
        },
    )
    cargo = root / "gui/src-tauri/Cargo.toml"
    cargo.parent.mkdir(parents=True, exist_ok=True)
    cargo.write_text(
        f'[package]\nname = "codex-keysmith-gui"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "gui/src-tauri/Cargo.lock").write_text(
        f'[[package]]\nname = "codex-keysmith-gui"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    _write_json(
        root / "gui/src-tauri/tauri.conf.json",
        {
            "productName": "codex-keysmith",
            "version": "../package.json",
            "bundle": {
                "active": True,
                "icon": ["icons/icon.icns", "icons/icon.ico"],
            },
        },
    )
    _write_json(
        root / "gui/src-tauri/capabilities/default.json",
        {
            "identifier": "default",
            "windows": ["main"],
            "permissions": [
                "core:default",
                "core:window:allow-close",
                "core:window:allow-destroy",
                "dialog:default",
                "dialog:allow-open",
            ],
        },
    )
    _write_icns(root / "gui/src-tauri/icons/icon.icns")
    _write_ico(root / "gui/src-tauri/icons/icon.ico")
    for platform, targets in (("macos", ["app", "dmg"]), ("windows", ["nsis"])):
        bundle = {
            "targets": targets,
            "externalBin": ["binaries/codex-keysmith-cli"],
        }
        if platform == "windows":
            bundle["windows"] = {
                "allowDowngrades": False,
                "webviewInstallMode": {
                    "type": "downloadBootstrapper",
                    "silent": True,
                },
                "nsis": {"installMode": "currentUser"},
            }
        _write_json(
            root / f"gui/src-tauri/tauri.{platform}.conf.json",
            {"bundle": bundle},
        )
    runtime = root / "gui/src-tauri/src/cli_runner.rs"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        'const SIDECAR_BASENAME: &str = "codex-keysmith-cli";\n',
        encoding="utf-8",
    )
    build_script = root / "gui/scripts/build-sidecar.mjs"
    build_script.parent.mkdir(parents=True, exist_ok=True)
    build_script.write_text(
        'const targets = ["aarch64-apple-darwin", "x86_64-pc-windows-msvc"];\n'
        'const args = ["--name",\n  "codex-keysmith-cli"];\n'
        'const built = `codex-keysmith-cli${targetConfig.extension}`;\n'
        'const destination = `codex-keysmith-cli-${target}${targetConfig.extension}`;\n'
        'const pythonEnv = { PYTHONNOUSERSITE: "1" };\n'
        'delete pythonEnv.PYTHONPATH;\n',
        encoding="utf-8",
    )
    (root / "gui/requirements-build.txt").write_text(
        "PyInstaller==6.16.0\n",
        encoding="utf-8",
    )
    workflow = root / ".github/workflows/desktop-candidate.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(_workflow_text(), encoding="utf-8")


def _pe_binary(machine: int = 0x8664) -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, machine)
    return bytes(data)


def _write_frontend_build(root: Path, source_commit: str) -> None:
    bundle = root / "gui/dist/assets/index.js"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(
        f'const sourceCommit = "{source_commit}";\n',
        encoding="utf-8",
    )


def _pe_binary_with_icon_resources() -> bytes:
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    struct.pack_into("<H", data, 134, 1)
    struct.pack_into("<H", data, 148, 240)
    optional = 152
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<II", data, optional + 112 + 16, 0x1000, 64)
    section = optional + 240
    struct.pack_into("<IIII", data, section + 8, 128, 0x1000, 128, 512)
    struct.pack_into("<HH", data, 512 + 12, 0, 2)
    struct.pack_into("<II", data, 512 + 16, 3, 0x80000020)
    struct.pack_into("<II", data, 512 + 24, 14, 0x80000030)
    return bytes(data)


def test_validate_config_accepts_package_json_version_source(tmp_path):
    _config_fixture(tmp_path)

    assert validator.validate_config(tmp_path) == {
        "desktop_version": "0.2.0",
        "cli_version": "0.2.0",
    }


@pytest.mark.parametrize(
    "permission",
    ["core:window:allow-close", "core:window:allow-destroy"],
)
def test_validate_config_requires_window_lifecycle_permissions(tmp_path, permission):
    _config_fixture(tmp_path)
    path = tmp_path / "gui/src-tauri/capabilities/default.json"
    capability = json.loads(path.read_text(encoding="utf-8"))
    capability["permissions"].remove(permission)
    _write_json(path, capability)

    with pytest.raises(validator.CandidateError, match="window lifecycle permissions"):
        validator.validate_config(tmp_path)


def test_validate_config_requires_window_capability_for_main_window(tmp_path):
    _config_fixture(tmp_path)
    path = tmp_path / "gui/src-tauri/capabilities/default.json"
    capability = json.loads(path.read_text(encoding="utf-8"))
    capability["windows"] = ["secondary"]
    _write_json(path, capability)

    with pytest.raises(validator.CandidateError, match="apply to the main window"):
        validator.validate_config(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda text: text.replace("permissions:\n  contents: read", "permissions:\n  contents: write"),
            "outside the publisher job",
        ),
        (
            lambda text: text.replace("inputs.publish_desktop_prerelease == true", "true"),
            "publisher markers",
        ),
        (
            lambda text: text.replace(
                "    env:\n      CODEX_KEYSMITH_SOURCE_COMMIT: ${{ github.sha }}\n",
                "",
            ),
            "workflow markers",
        ),
        (
            lambda text: text.replace("runs-on: macos-15", "runs-on: macos-15\n    env:\n      TOKEN: ${{ secrets.TOKEN }}"),
            "candidate signing secret",
        ),
        (
            lambda text: text.replace('"prerelease": True', '"prerelease": False'),
            "publisher markers",
        ),
        (
            lambda text: text.replace('"tag_name": tag', '"tag_name": omitted', 1),
            "must preserve",
        ),
        (
            lambda text: text.replace(
                "      - name: Build pinned PyInstaller sidecar\n        run: echo built\n      - name: Run Rust tests\n        run: echo tested",
                "      - name: Run Rust tests\n        run: echo tested\n      - name: Build pinned PyInstaller sidecar\n        run: echo built",
            ),
            "real sidecar before Rust tests",
        ),
        (
            lambda text: text.replace(
                "            $automaticStatusOutput = & $installedSidecars[0].FullName --status --lang en 2>&1\n",
                "            Write-Output '$automaticStatusOutput = & $installedSidecars[0].FullName --status --lang en 2>&1'\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                '          [Environment]::SetEnvironmentVariable("HOME", $profileRoot, "Process")\n',
                "",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                "            $secondProcess = Start-Process -FilePath $installedApps[0].FullName -PassThru\n",
                "            Write-Output 'second launch'\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                "            $primaryFocused = [KeysmithWindowProbe]::GetForegroundWindow() -eq $primaryWindowHandle\n",
                "            $primaryFocused = $true\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                "            $primaryVisible = [KeysmithWindowProbe]::IsWindowVisible($primaryWindowHandle)\n",
                "            $primaryVisible = $true\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                "            if (-not $slowAppProcess.CloseMainWindow()) {\n",
                "            Write-Output 'slow close'\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace(
                "          $payloadProcessDeadline = [DateTime]::UtcNow.AddSeconds(15)\n",
                "          Start-Sleep -Seconds 1\n",
            ),
            "Windows candidate smoke step",
        ),
        (
            lambda text: text.replace("$environmentBackup[$name]", "$null"),
            "Windows candidate smoke step",
        ),
    ],
)
def test_validate_config_rejects_prerelease_workflow_policy_drift(
    tmp_path,
    mutation,
    message,
):
    _config_fixture(tmp_path)
    workflow = tmp_path / ".github/workflows/desktop-candidate.yml"
    workflow.write_text(mutation(workflow.read_text(encoding="utf-8")), encoding="utf-8")

    with pytest.raises(validator.CandidateError, match=message):
        validator.validate_config(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"targets": ["msi"]}, "targets"),
        ({"windows": {"allowDowngrades": True}}, "disable installer downgrades"),
        (
            {"windows": {"webviewInstallMode": {"type": "embedBootstrapper"}}},
            "WebView2 download bootstrapper",
        ),
        ({"windows": {"nsis": {"installMode": "perMachine"}}}, "currentUser"),
    ],
)
def test_validate_config_rejects_windows_bundle_policy_drift(
    tmp_path,
    mutation,
    message,
):
    _config_fixture(tmp_path)
    path = tmp_path / "gui/src-tauri/tauri.windows.conf.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    for key, value in mutation.items():
        if key == "windows":
            config["bundle"]["windows"].update(value)
        else:
            config["bundle"][key] = value
    _write_json(path, config)

    with pytest.raises(validator.CandidateError, match=message):
        validator.validate_config(tmp_path)


def test_validate_config_rejects_stale_package_lock_version(tmp_path):
    _config_fixture(tmp_path)
    lock = json.loads((tmp_path / "gui/package-lock.json").read_text(encoding="utf-8"))
    lock["packages"][""]["version"] = "0.1.0"
    _write_json(tmp_path / "gui/package-lock.json", lock)

    with pytest.raises(validator.CandidateError, match="versions disagree"):
        validator.validate_config(tmp_path)


def test_validate_config_rejects_sidecar_basename_drift(tmp_path):
    _config_fixture(tmp_path)
    runtime = tmp_path / "gui/src-tauri/src/cli_runner.rs"
    runtime.write_text(
        'const SIDECAR_BASENAME: &str = "codex-keysmith";\n',
        encoding="utf-8",
    )

    with pytest.raises(validator.CandidateError, match="runtime sidecar basename"):
        validator.validate_config(tmp_path)


def test_validate_config_rejects_intel_macos_target(tmp_path):
    _config_fixture(tmp_path)
    build_script = tmp_path / "gui/scripts/build-sidecar.mjs"
    build_script.write_text(
        build_script.read_text(encoding="utf-8") + '\nconst extra = "x86_64-apple-darwin";\n',
        encoding="utf-8",
    )

    with pytest.raises(validator.CandidateError, match="Intel macOS candidate"):
        validator.validate_config(tmp_path)


def test_detects_macho_and_pe_architectures(tmp_path):
    macho = tmp_path / "app"
    macho.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + bytes(32))
    pe = tmp_path / "app.exe"
    pe.write_bytes(_pe_binary())

    assert validator.detect_binary_architectures(macho) == {"arm64"}
    assert validator.detect_binary_architectures(pe) == {"x86_64"}


def test_detects_windows_icon_resource_types(tmp_path):
    app = tmp_path / "app.exe"
    app.write_bytes(_pe_binary_with_icon_resources())

    assert validator._pe_resource_type_ids(app) == {3, 14}


def test_frontend_build_identity_requires_exact_candidate_commit(tmp_path):
    source_commit = "a" * 40
    _write_frontend_build(tmp_path, source_commit)

    validator.verify_frontend_build_identity(tmp_path, source_commit)

    with pytest.raises(validator.CandidateError, match="candidate source commit"):
        validator.verify_frontend_build_identity(tmp_path, "b" * 40)


def test_frontend_build_identity_requires_javascript_output(tmp_path):
    (tmp_path / "gui/dist").mkdir(parents=True)

    with pytest.raises(validator.CandidateError, match="no JavaScript bundles"):
        validator.verify_frontend_build_identity(tmp_path, "a" * 40)


def test_stage_and_verify_manifest_detects_artifact_tampering(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _write_frontend_build(root, "a" * 40)
    source = tmp_path / "source.exe"
    packaged = tmp_path / "packaged.exe"
    app = tmp_path / "app.exe"
    bundle = tmp_path / "codex-keysmith_0.2.0_x64-setup.exe"
    icon = tmp_path / "icon.ico"
    source.write_bytes(_pe_binary())
    packaged.write_bytes(source.read_bytes())
    app.write_bytes(_pe_binary())
    bundle.write_bytes(b"candidate bundle")
    _write_ico(icon)
    monkeypatch.setattr(
        validator,
        "validate_config",
        lambda _root: {"desktop_version": "0.2.0", "cli_version": "0.2.0"},
    )
    monkeypatch.setattr(validator, "_run_version", lambda _path, _version: "codex-keysmith 0.2.0")
    monkeypatch.setattr(validator, "_pe_resource_type_ids", lambda _path: {3, 14})
    output = tmp_path / "candidate"
    args = argparse.Namespace(
        root=root,
        platform="windows",
        architecture="x86_64",
        target_triple="x86_64-pc-windows-msvc",
        bundle_format="nsis",
        bundle=bundle,
        app_executable=app,
        app_bundle=None,
        sidecar=source,
        packaged_sidecar=packaged,
        icon=icon,
        source_commit="a" * 40,
        node_version="22.14.0",
        python_version="3.12.9",
        pyinstaller_version="6.16.0",
        rust_version="1.88.0",
        signing_mode="unsigned",
        output_dir=output,
    )

    manifest = validator.stage_candidate(args)
    validator.verify_manifest(manifest)
    (output / "codex-keysmith-cli.exe").write_bytes(b"tampered")

    with pytest.raises(validator.CandidateError, match="hash or size mismatch"):
        validator.verify_manifest(manifest)


def test_signed_candidate_accepts_signature_modified_sidecar(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _write_frontend_build(root, "a" * 40)
    source = tmp_path / "source.exe"
    packaged = tmp_path / "packaged.exe"
    app = tmp_path / "app.exe"
    bundle = tmp_path / "codex-keysmith_0.2.0_x64-setup.exe"
    icon = tmp_path / "icon.ico"
    source.write_bytes(_pe_binary())
    packaged.write_bytes(_pe_binary() + b"authenticode-signature")
    app.write_bytes(_pe_binary())
    bundle.write_bytes(b"signed candidate bundle")
    _write_ico(icon)
    monkeypatch.setattr(
        validator,
        "validate_config",
        lambda _root: {"desktop_version": "0.2.0", "cli_version": "0.2.0"},
    )
    monkeypatch.setattr(validator, "_run_version", lambda _path, _version: "codex-keysmith 0.2.0")
    monkeypatch.setattr(validator, "_pe_resource_type_ids", lambda _path: {3, 14})
    monkeypatch.setattr(validator, "_verify_signature", lambda *_args: None)
    output = tmp_path / "candidate"
    args = argparse.Namespace(
        root=root,
        platform="windows",
        architecture="x86_64",
        target_triple="x86_64-pc-windows-msvc",
        bundle_format="nsis",
        bundle=bundle,
        app_executable=app,
        app_bundle=None,
        sidecar=source,
        packaged_sidecar=packaged,
        icon=icon,
        source_commit="a" * 40,
        node_version="22.14.0",
        python_version="3.12.9",
        pyinstaller_version="6.16.0",
        rust_version="1.88.0",
        signing_mode="signed",
        output_dir=output,
    )

    manifest_path = validator.stage_candidate(args)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["sidecar_provenance"]["relation"] == "signed-build-output"
    validator.verify_manifest(manifest_path)

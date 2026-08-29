from __future__ import annotations

import hashlib
import json
import struct
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from scripts import package_desktop_prerelease as prerelease

COMMIT = "a" * 40
TAG = f"desktop-v{prerelease.VERSION}-beta.1"
REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION = prerelease.VERSION
PUBLISHED_DESKTOP_VERSION = "0.3.9"
PUBLISHED_DESKTOP_TAG = f"desktop-v{PUBLISHED_DESKTOP_VERSION}-beta.1"
PUBLISHED_SOURCE_VERSION = "0.3.9"
HISTORICAL_DESKTOP_VERSION = "0.3.5"
HISTORICAL_DESKTOP_TAG = f"desktop-v{HISTORICAL_DESKTOP_VERSION}-beta.1"
PREVIOUS_DESKTOP_VERSION = "0.3.8"
PREVIOUS_DESKTOP_TAG = f"desktop-v{PREVIOUS_DESKTOP_VERSION}-beta.1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pe_binary() -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    return bytes(data)


def _macho_binary() -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + bytes(32)


def _write_ico(path: Path) -> None:
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + bytes(16))


def _write_icns(path: Path) -> None:
    path.write_bytes(b"icns" + struct.pack(">I", 8))


def _candidate(tmp_path: Path, platform: str) -> Path:
    candidate = tmp_path / platform
    candidate.mkdir(parents=True)
    if platform == "windows":
        bundle = candidate / f"codex-keysmith_{VERSION}_x64-setup.exe"
        app = candidate / "codex-keysmith-gui.exe"
        sidecar = candidate / "codex-keysmith-cli.exe"
        icon = candidate / "icon.ico"
        architecture = "x86_64"
        target = {
            "platform": "windows",
            "architecture": architecture,
            "triple": "x86_64-pc-windows-msvc",
            "bundle_format": "nsis",
            "signing_mode": "unsigned",
        }
        bundle.write_bytes(b"unsigned nsis installer")
        app.write_bytes(_pe_binary())
        sidecar.write_bytes(_pe_binary() + b"sidecar")
        _write_ico(icon)
    else:
        bundle = candidate / f"codex-keysmith_{VERSION}_aarch64.dmg"
        app = candidate / "codex-keysmith-gui"
        sidecar = candidate / "codex-keysmith-cli"
        icon = candidate / "icon.icns"
        architecture = "arm64"
        target = {
            "platform": "macos",
            "architecture": architecture,
            "triple": "aarch64-apple-darwin",
            "bundle_format": "dmg",
            "signing_mode": "unsigned",
        }
        bundle.write_bytes(b"unsigned dmg")
        app.write_bytes(_macho_binary())
        sidecar.write_bytes(_macho_binary() + b"sidecar")
        _write_icns(icon)

    def record(path: Path, architecture: str | None = None) -> dict[str, object]:
        value: dict[str, object] = {
            "file": path.name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        if architecture:
            value["architecture"] = architecture
        return value

    sidecar_hash = _sha256(sidecar)
    manifest = {
        "schema_version": 1,
        "product": "codex-keysmith",
        "desktop_version": VERSION,
        "cli_version": VERSION,
        "source_commit": COMMIT,
        "target": target,
        "toolchain": {
            "node": "22.14.0",
            "python": "3.12.9",
            "pyinstaller": "6.16.0",
            "rust": "1.88.0",
        },
        "sidecar_version_output": f"{sidecar.name} {VERSION}",
        "sidecar_provenance": {
            "source_sha256": sidecar_hash,
            "packaged_sha256": sidecar_hash,
            "relation": "exact-copy",
        },
        "artifacts": {
            "bundle": record(bundle),
            "app_executable": record(app, architecture),
            "sidecar": record(sidecar, architecture),
            "icon": record(icon),
        },
    }
    (candidate / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_lines = sorted(
        f"{record['sha256']}  {record['file']}"
        for record in manifest["artifacts"].values()
    )
    (candidate / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="ascii",
    )
    return candidate


def _assemble(tmp_path: Path, output_name: str = "out") -> tuple[Path, Path, Path]:
    macos = _candidate(tmp_path / "candidates", "macos")
    windows = _candidate(tmp_path / "candidates", "windows")
    output = prerelease.assemble_prerelease(
        macos,
        windows,
        tmp_path / output_name,
        TAG,
        COMMIT,
    )
    return output, macos, windows


def _mutate_manifest(candidate: Path, callback) -> None:
    path = candidate / "build-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    callback(manifest)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rewrite_public_checksums(output: Path) -> None:
    lines = [
        f"{_sha256(output / name)}  {name}"
        for name in sorted(prerelease.PUBLIC_PAYLOAD_NAMES)
    ]
    (output / prerelease.CHECKSUMS_NAME).write_text(
        "\n".join(lines) + "\n",
        encoding="ascii",
    )


def test_assemble_creates_exact_public_assets_and_candidate_zips(tmp_path):
    output, macos, windows = _assemble(tmp_path)

    assert {path.name for path in output.iterdir()} == set(prerelease.PUBLIC_ASSET_NAMES)
    assert (output / prerelease.MACOS_DMG_NAME).read_bytes() == (
        macos / f"codex-keysmith_{VERSION}_aarch64.dmg"
    ).read_bytes()
    assert (output / prerelease.WINDOWS_SETUP_NAME).read_bytes() == (
        windows / f"codex-keysmith_{VERSION}_x64-setup.exe"
    ).read_bytes()
    for name in prerelease.SOURCE_RELEASE_PAYLOAD_NAMES:
        assert not (output / name).exists()
    prerelease.verify_public_assets(output, COMMIT)
    for candidate, zip_name in (
        (macos, prerelease.MACOS_CANDIDATE_ZIP_NAME),
        (windows, prerelease.WINDOWS_CANDIDATE_ZIP_NAME),
    ):
        with zipfile.ZipFile(output / zip_name) as archive:
            assert archive.namelist() == sorted(path.name for path in candidate.iterdir())
            for candidate_file in candidate.iterdir():
                assert archive.read(candidate_file.name) == candidate_file.read_bytes()


def test_candidate_zip_is_reproducible(tmp_path):
    first, macos, windows = _assemble(tmp_path, "first")
    second = prerelease.assemble_prerelease(
        macos, windows, tmp_path / "second", TAG, COMMIT
    )

    for name in (
        prerelease.MACOS_CANDIDATE_ZIP_NAME,
        prerelease.WINDOWS_CANDIDATE_ZIP_NAME,
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert (first / prerelease.CHECKSUMS_NAME).read_bytes() == (
        second / prerelease.CHECKSUMS_NAME
    ).read_bytes()


@pytest.mark.parametrize(
    ("tag", "commit", "message"),
    [
        ("v0.2.0", COMMIT, "release tag"),
        ("desktop-v0.2.0-beta.1", COMMIT, "release tag"),
        (f"desktop-v{prerelease.VERSION}-beta.0", COMMIT, "release tag"),
        (TAG, "ABC", "expected commit"),
    ],
)
def test_assemble_rejects_invalid_identity(tmp_path, tag, commit, message):
    macos = _candidate(tmp_path, "macos")
    windows = _candidate(tmp_path, "windows")

    with pytest.raises(prerelease.PrereleaseError, match=message):
        prerelease.assemble_prerelease(macos, windows, tmp_path / "out", tag, commit)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(source_commit="b" * 40), "source commit"),
        (lambda value: value.update(desktop_version="0.2.1"), "versions"),
        (lambda value: value["target"].update(platform="macos"), "windows target policy"),
        (lambda value: value["target"].update(architecture="arm64"), "windows target policy"),
        (lambda value: value["target"].update(bundle_format="msi"), "windows target policy"),
        (lambda value: value["target"].update(signing_mode="signed"), "windows target policy"),
        (
            lambda value: value["sidecar_provenance"].update(relation="signed-build-output"),
            "exact tested build output",
        ),
    ],
)
def test_assemble_rejects_manifest_policy_drift(tmp_path, mutation, message):
    macos = _candidate(tmp_path, "macos")
    windows = _candidate(tmp_path, "windows")
    _mutate_manifest(windows, mutation)

    with pytest.raises(prerelease.PrereleaseError, match=message):
        prerelease.assemble_prerelease(macos, windows, tmp_path / "out", TAG, COMMIT)


def test_assemble_rejects_cross_platform_candidate_swap(tmp_path):
    macos = _candidate(tmp_path, "macos")
    windows = _candidate(tmp_path, "windows")

    with pytest.raises(prerelease.PrereleaseError, match="macos target policy"):
        prerelease.assemble_prerelease(windows, macos, tmp_path / "out", TAG, COMMIT)


def test_assemble_rejects_tampering_extra_files_symlinks_and_overwrite(tmp_path):
    macos = _candidate(tmp_path / "tampered", "macos")
    tampered = _candidate(tmp_path / "tampered", "windows")
    (tampered / "codex-keysmith-cli.exe").write_bytes(b"tampered")
    with pytest.raises(prerelease.PrereleaseError, match="hash or size mismatch"):
        prerelease.assemble_prerelease(
            macos, tampered, tmp_path / "tampered-out", TAG, COMMIT
        )

    macos = _candidate(tmp_path / "extra", "macos")
    extra = _candidate(tmp_path / "extra", "windows")
    (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="file set is not exact"):
        prerelease.assemble_prerelease(macos, extra, tmp_path / "extra-out", TAG, COMMIT)

    macos = _candidate(tmp_path / "linked", "macos")
    linked = _candidate(tmp_path / "linked", "windows")
    icon = linked / "icon.ico"
    icon.unlink()
    icon.symlink_to(linked / "codex-keysmith-cli.exe")
    with pytest.raises(prerelease.PrereleaseError, match="not a symlink"):
        prerelease.assemble_prerelease(
            macos, linked, tmp_path / "linked-out", TAG, COMMIT
        )

    macos = _candidate(tmp_path / "linked-directory", "macos")
    real_candidate = _candidate(tmp_path / "linked-directory", "windows")
    candidate_link = tmp_path / "candidate-link"
    candidate_link.symlink_to(real_candidate, target_is_directory=True)
    with pytest.raises(prerelease.PrereleaseError, match="missing or unsafe"):
        prerelease.assemble_prerelease(
            macos,
            candidate_link,
            tmp_path / "linked-directory-out",
            TAG,
            COMMIT,
        )

    macos = _candidate(tmp_path / "overwrite", "macos")
    windows = _candidate(tmp_path / "overwrite", "windows")
    output = tmp_path / "existing-output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="absent or empty"):
        prerelease.assemble_prerelease(macos, windows, output, TAG, COMMIT)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_verify_public_assets_rejects_tampering_and_extra_assets(tmp_path):
    output, _macos, _windows = _assemble(tmp_path)
    with pytest.raises(prerelease.PrereleaseError, match="source commit"):
        prerelease.verify_public_assets(output, "b" * 40)
    (output / prerelease.WINDOWS_SETUP_NAME).write_bytes(b"tampered")

    with pytest.raises(prerelease.PrereleaseError, match="SHA256SUMS"):
        prerelease.verify_public_assets(output, COMMIT)

    _rewrite_public_checksums(output)
    with pytest.raises(prerelease.PrereleaseError, match="public windows bundle"):
        prerelease.verify_public_assets(output, COMMIT)

    output, _macos, _windows = _assemble(tmp_path / "zip-case")
    extracted = tmp_path / "tampered-zip"
    extracted.mkdir()
    with zipfile.ZipFile(output / prerelease.WINDOWS_CANDIDATE_ZIP_NAME) as archive:
        for name in archive.namelist():
            (extracted / name).write_bytes(archive.read(name))
    (extracted / "codex-keysmith-cli.exe").write_bytes(b"tampered sidecar")
    (output / prerelease.WINDOWS_CANDIDATE_ZIP_NAME).unlink()
    prerelease._write_deterministic_zip(
        extracted,
        output / prerelease.WINDOWS_CANDIDATE_ZIP_NAME,
    )
    _rewrite_public_checksums(output)
    with pytest.raises(prerelease.PrereleaseError, match="hash or size mismatch"):
        prerelease.verify_public_assets(output, COMMIT)

    output, _macos, _windows = _assemble(tmp_path / "source-case")
    (output / prerelease.CLI_NAME).write_text("tampered", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="asset set is not exact"):
        prerelease.verify_public_assets(output, COMMIT)

    output, _macos, _windows = _assemble(tmp_path / "extra-case")
    (output / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="asset set is not exact"):
        prerelease.verify_public_assets(output, COMMIT)


def test_prerelease_workflow_is_separate_unsigned_and_versioned():
    desktop = (REPO_ROOT / ".github/workflows/desktop-candidate.yml").read_text(
        encoding="utf-8"
    )
    stable = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "secrets." not in desktop
    assert "pull_request_target:" not in desktop
    assert "workflow_run:" not in desktop
    assert desktop.count("contents: write") == 1
    assert (
        "if: >-\n      ${{ github.event_name == 'workflow_dispatch' && inputs.publish_desktop_prerelease }}"
        in desktop
    )
    assert "Publish the current unsigned desktop line as desktop-v<VERSION>-beta.N." in desktop
    assert "verify-manifest-data" in desktop
    assert '"prerelease": True' in desktop
    assert '"make_latest": "false"' in desktop
    assert "latest_after" in desktop and "latest_before" in desktop
    assert "latestRelease{tagName}" in desktop
    assert "__NO_LATEST_RELEASE__" in desktop
    assert 'releases/latest" --jq .tag_name' not in desktop
    assert "create_attempted=true" in desktop
    assert "Removed the uniquely owned empty Draft" in desktop
    assert "Recovered numeric-ID ownership after a lost create response." in desktop
    assert 'release_author="github-actions[bot]"' in desktop
    assert 'len(state["assets"]) == 5' in desktop
    assert "--source-dir" not in desktop
    final_state = desktop.index(
        'final_state="${RUNNER_TEMP}/desktop-prerelease-published.json"'
    )
    assert desktop.index("verify_remote_tag", final_state) < desktop.index(
        "latest_after", final_state
    )
    assert "--clobber" not in desktop
    assert 'tags:\n      - "v*.*.*"' in stable
    assert 'expected_tag="v${version}"' in stable
    assert 'assert state["prerelease"] is False' in stable
    assert "desktop-v0.2.0-beta" not in stable


def test_prerelease_creation_validator_binds_numeric_id_and_unsigned_metadata(
    tmp_path,
    monkeypatch,
):
    workflow = (REPO_ROOT / ".github/workflows/desktop-candidate.yml").read_text(
        encoding="utf-8"
    )
    marker = 'empty_state="${RUNNER_TEMP}/desktop-prerelease-empty.json"'
    validator_start = workflow.index("          import json\n", workflow.index(marker))
    validator_end = workflow.index("\n          PY", validator_start)
    validator = textwrap.dedent(workflow[validator_start:validator_end])

    repo = "Jia-Ethan/codex-keysmith"
    release_id = "400000001"
    draft_name = f"codex-keysmith {VERSION} Desktop Beta [run 123.1]"
    notes = tmp_path / "notes.md"
    notes.write_bytes(b"unsigned beta notes\n")
    payload = {
        "id": int(release_id),
        "url": f"https://api.github.com/repos/{repo}/releases/{release_id}",
        "upload_url": (
            f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
            "{?name,label}"
        ),
        "tag_name": TAG,
        "target_commitish": COMMIT,
        "name": draft_name,
        "draft": True,
        "prerelease": True,
        "body": notes.read_text(encoding="utf-8"),
        "assets": [],
    }
    created = tmp_path / "created.json"
    state = tmp_path / "state.json"

    def run(created_payload, state_payload):
        created.write_text(json.dumps(created_payload), encoding="utf-8")
        state.write_text(json.dumps(state_payload), encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "desktop-prerelease-validator",
                str(created),
                str(state),
                str(notes),
                TAG,
                COMMIT,
                release_id,
                repo,
                draft_name,
            ],
        )
        exec(compile(validator, "<desktop-prerelease-validator>", "exec"), {})

    run(payload, payload)
    with pytest.raises(AssertionError):
        run(dict(payload, prerelease=False), payload)
    with pytest.raises(AssertionError):
        run(payload, dict(payload, assets=[{"id": 1}]))
    with pytest.raises(AssertionError):
        run(dict(payload, target_commitish="b" * 40), payload)


def test_lost_create_response_recovery_requires_unique_run_owned_draft(
    tmp_path,
    monkeypatch,
):
    workflow = (REPO_ROOT / ".github/workflows/desktop-candidate.yml").read_text(
        encoding="utf-8"
    )
    marker = 'owned_draft_validator="${RUNNER_TEMP}/validate-owned-desktop-draft.py"'
    validator_start = workflow.index("          import json\n", workflow.index(marker))
    validator_end = workflow.index("\n          PY", validator_start)
    validator = textwrap.dedent(workflow[validator_start:validator_end])
    notes = tmp_path / "notes.md"
    notes.write_text("unsigned beta notes\n", encoding="utf-8")
    source = tmp_path / "releases.json"
    output = tmp_path / "adopted.json"
    actor = "github-actions[bot]"
    started_at = "2026-08-10T01:00:00Z"
    draft_name = f"codex-keysmith {VERSION} Desktop Beta [run 123.1]"
    release = {
        "id": 400000002,
        "tag_name": TAG,
        "target_commitish": COMMIT,
        "name": draft_name,
        "body": notes.read_text(encoding="utf-8"),
        "draft": True,
        "prerelease": True,
        "assets": [],
        "created_at": "2026-08-10T01:00:01Z",
        "author": {"login": actor},
    }

    def run(releases):
        source.write_text(json.dumps(releases), encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "lost-create-recovery",
                str(source),
                str(output),
                str(notes),
                TAG,
                COMMIT,
                started_at,
                actor,
                draft_name,
            ],
        )
        exec(compile(validator, "<lost-create-recovery>", "exec"), {})

    run([[release]])
    assert json.loads(output.read_text(encoding="utf-8"))["id"] == release["id"]
    run(release)
    assert json.loads(output.read_text(encoding="utf-8"))["id"] == release["id"]
    with pytest.raises(SystemExit, match="exactly one"):
        run([[dict(release, name="wrong")]])
    with pytest.raises(SystemExit, match="exactly one"):
        run([[release, dict(release, id=400000003)]])
    with pytest.raises(SystemExit, match="exactly one"):
        run([[dict(release, author={"login": "Jaaay50"})]])
    with pytest.raises(SystemExit, match="unexpected shape"):
        run(["not-a-release"])


def test_prerelease_docs_disclose_assets_privacy_and_beta_boundaries():
    paths = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "README.en.md",
        REPO_ROOT / f"docs/releases/{PUBLISHED_DESKTOP_TAG}.md",
        REPO_ROOT / "CODE_SIGNING_POLICY.md",
        REPO_ROOT / "PRIVACY.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for marker in (
        PUBLISHED_DESKTOP_TAG,
        f"codex-keysmith-{PUBLISHED_DESKTOP_VERSION}-macos-arm64-unsigned.dmg",
        f"codex-keysmith-{PUBLISHED_DESKTOP_VERSION}-windows-x64-unsigned-setup.exe",
        f"codex-instruct-v{PUBLISHED_SOURCE_VERSION}.py",
        f"v{PUBLISHED_DESKTOP_VERSION}",
        "SHA256SUMS",
        "unsigned",
        "SmartScreen",
        "Gatekeeper",
        "Apple Silicon",
        "Windows x64",
        "SignPath Foundation",
    ):
        assert marker in combined
    assert "不主动收集或上传用户数据" in combined
    assert "does not proactively collect or upload user data" in combined
    assert "physical-device acceptance" in combined
    assert "not SignPath-signed" in combined

    readmes = "\n".join(
        (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "README.en.md")
    )
    assert "Windows 原生产物仍待 CI 验证" not in readmes
    assert "native artifact validation still pending in CI" not in readmes


def test_historical_desktop_beta6_notes_remain_unchanged():
    release_notes = (REPO_ROOT / "docs/releases/desktop-v0.2.0-beta.6.md").read_text(
        encoding="utf-8"
    )
    expected = textwrap.dedent(
        """\
        # codex-keysmith v0.2.0 Desktop Beta

        修复了部署和管理确认弹窗移出视口、Windows 状态报告被折叠为通用失败，以及关闭或重复启动时的桌面生命周期问题。

        ## 下载

        - macOS Apple Silicon：`codex-keysmith-0.2.0-macos-arm64-unsigned.dmg`
        - Windows x64：`codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe`
        - 单文件 CLI：`codex-instruct-v0.2.0.py`
        - 文件校验：`SHA256SUMS`
        """
    )
    assert release_notes == expected


def test_historical_desktop_v035_notes_remain_unchanged():
    release_notes = (
        REPO_ROOT / f"docs/releases/{HISTORICAL_DESKTOP_TAG}.md"
    ).read_text(encoding="utf-8")
    expected = textwrap.dedent(
        f"""\
        # codex-keysmith v{HISTORICAL_DESKTOP_VERSION} Desktop Beta

        GUI 安装包更新场景库页。GUI 只调用 CLI 场景命令。Windows 上三个生产场景仍只声明 darwin/linux，部署会被 blocker 拦住。

        ## 下载

        - macOS Apple Silicon：`codex-keysmith-{HISTORICAL_DESKTOP_VERSION}-macos-arm64-unsigned.dmg`
        - Windows x64：`codex-keysmith-{HISTORICAL_DESKTOP_VERSION}-windows-x64-unsigned-setup.exe`
        - 单文件 CLI 与场景 bundle：见 [v{HISTORICAL_DESKTOP_VERSION}](https://github.com/Jia-Ethan/codex-keysmith/releases/tag/v{HISTORICAL_DESKTOP_VERSION})
        - 文件校验：`SHA256SUMS`
        """
    )
    assert release_notes == expected


def test_previous_desktop_v038_notes_remain_unchanged():
    release_notes = (
        REPO_ROOT / f"docs/releases/{PREVIOUS_DESKTOP_TAG}.md"
    ).read_text(encoding="utf-8")
    expected = textwrap.dedent(
        """\
        # codex-keysmith 桌面测试版

        修复升级后当前配置不再引用受管提示词时无法卸载的问题；卸载会保留现有 Codex 配置。
        """
    )
    assert release_notes == expected


def test_published_prerelease_release_notes_match_approved_compact_copy():
    release_notes = (
        REPO_ROOT / f"docs/releases/{PUBLISHED_DESKTOP_TAG}.md"
    ).read_text(encoding="utf-8")
    expected = textwrap.dedent(
        """\
        # codex-keysmith 桌面测试版

        新增“恢复配置引用”入口。
        """
    )
    assert release_notes == expected

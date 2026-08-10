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
TAG = "desktop-v0.2.0-beta.2"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pe_binary() -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    return bytes(data)


def _write_ico(path: Path) -> None:
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + bytes(16))


def _candidate(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir(parents=True)
    bundle = candidate / "codex-keysmith_0.2.0_x64-setup.exe"
    app = candidate / "codex-keysmith-gui.exe"
    sidecar = candidate / "codex-keysmith-cli.exe"
    icon = candidate / "icon.ico"
    bundle.write_bytes(b"unsigned nsis installer")
    app.write_bytes(_pe_binary())
    sidecar.write_bytes(_pe_binary() + b"sidecar")
    _write_ico(icon)

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
        "desktop_version": "0.2.0",
        "cli_version": "0.2.0",
        "source_commit": COMMIT,
        "target": {
            "platform": "windows",
            "architecture": "x86_64",
            "triple": "x86_64-pc-windows-msvc",
            "bundle_format": "nsis",
            "signing_mode": "unsigned",
        },
        "toolchain": {
            "node": "22.14.0",
            "python": "3.12.9",
            "pyinstaller": "6.16.0",
            "rust": "1.88.0",
        },
        "sidecar_version_output": "codex-keysmith-cli.exe 0.2.0",
        "sidecar_provenance": {
            "source_sha256": sidecar_hash,
            "packaged_sha256": sidecar_hash,
            "relation": "exact-copy",
        },
        "artifacts": {
            "bundle": record(bundle),
            "app_executable": record(app, "x86_64"),
            "sidecar": record(sidecar, "x86_64"),
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


def _mutate_manifest(candidate: Path, callback) -> None:
    path = candidate / "build-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    callback(manifest)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rewrite_public_checksums(output: Path) -> None:
    lines = sorted(
        f"{_sha256(output / name)}  {name}"
        for name in (prerelease.SETUP_NAME, prerelease.CANDIDATE_ZIP_NAME)
    )
    (output / prerelease.CHECKSUMS_NAME).write_text(
        "\n".join(lines) + "\n",
        encoding="ascii",
    )


def test_assemble_creates_exact_public_assets_and_candidate_zip(tmp_path):
    candidate = _candidate(tmp_path)
    output = prerelease.assemble_prerelease(candidate, tmp_path / "out", TAG, COMMIT)

    assert {path.name for path in output.iterdir()} == set(prerelease.PUBLIC_ASSET_NAMES)
    assert (output / prerelease.SETUP_NAME).read_bytes() == (
        candidate / "codex-keysmith_0.2.0_x64-setup.exe"
    ).read_bytes()
    prerelease.verify_public_assets(output)
    with zipfile.ZipFile(output / prerelease.CANDIDATE_ZIP_NAME) as archive:
        assert archive.namelist() == sorted(path.name for path in candidate.iterdir())
        for source in candidate.iterdir():
            assert archive.read(source.name) == source.read_bytes()


def test_candidate_zip_is_reproducible(tmp_path):
    candidate = _candidate(tmp_path)
    first = prerelease.assemble_prerelease(candidate, tmp_path / "first", TAG, COMMIT)
    second = prerelease.assemble_prerelease(candidate, tmp_path / "second", TAG, COMMIT)

    assert (first / prerelease.CANDIDATE_ZIP_NAME).read_bytes() == (
        second / prerelease.CANDIDATE_ZIP_NAME
    ).read_bytes()
    assert (first / prerelease.CHECKSUMS_NAME).read_bytes() == (
        second / prerelease.CHECKSUMS_NAME
    ).read_bytes()


@pytest.mark.parametrize(
    ("tag", "commit", "message"),
    [
        ("v0.2.0", COMMIT, "release tag"),
        ("desktop-v0.2.0-beta.0", COMMIT, "release tag"),
        (TAG, "ABC", "expected commit"),
    ],
)
def test_assemble_rejects_invalid_identity(tmp_path, tag, commit, message):
    candidate = _candidate(tmp_path)

    with pytest.raises(prerelease.PrereleaseError, match=message):
        prerelease.assemble_prerelease(candidate, tmp_path / "out", tag, commit)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(source_commit="b" * 40), "source commit"),
        (lambda value: value.update(desktop_version="0.2.1"), "versions"),
        (lambda value: value["target"].update(platform="macos"), "unsigned Windows"),
        (lambda value: value["target"].update(architecture="arm64"), "unsigned Windows"),
        (lambda value: value["target"].update(bundle_format="msi"), "unsigned Windows"),
        (lambda value: value["target"].update(signing_mode="signed"), "unsigned Windows"),
        (
            lambda value: value["sidecar_provenance"].update(relation="signed-build-output"),
            "exact tested build output",
        ),
    ],
)
def test_assemble_rejects_manifest_policy_drift(tmp_path, mutation, message):
    candidate = _candidate(tmp_path)
    _mutate_manifest(candidate, mutation)

    with pytest.raises(prerelease.PrereleaseError, match=message):
        prerelease.assemble_prerelease(candidate, tmp_path / "out", TAG, COMMIT)


def test_assemble_rejects_tampering_extra_files_symlinks_and_overwrite(tmp_path):
    tampered = _candidate(tmp_path / "tampered")
    (tampered / "codex-keysmith-cli.exe").write_bytes(b"tampered")
    with pytest.raises(prerelease.PrereleaseError, match="hash or size mismatch"):
        prerelease.assemble_prerelease(tampered, tmp_path / "tampered-out", TAG, COMMIT)

    extra = _candidate(tmp_path / "extra")
    (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="file set is not exact"):
        prerelease.assemble_prerelease(extra, tmp_path / "extra-out", TAG, COMMIT)

    linked = _candidate(tmp_path / "linked")
    icon = linked / "icon.ico"
    icon.unlink()
    icon.symlink_to(linked / "codex-keysmith-cli.exe")
    with pytest.raises(prerelease.PrereleaseError, match="not a symlink"):
        prerelease.assemble_prerelease(linked, tmp_path / "linked-out", TAG, COMMIT)

    real_candidate = _candidate(tmp_path / "linked-directory")
    candidate_link = tmp_path / "candidate-link"
    candidate_link.symlink_to(real_candidate, target_is_directory=True)
    with pytest.raises(prerelease.PrereleaseError, match="missing or unsafe"):
        prerelease.assemble_prerelease(
            candidate_link,
            tmp_path / "linked-directory-out",
            TAG,
            COMMIT,
        )

    candidate = _candidate(tmp_path / "overwrite")
    output = tmp_path / "existing-output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="absent or empty"):
        prerelease.assemble_prerelease(candidate, output, TAG, COMMIT)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_verify_public_assets_rejects_tampering_and_extra_assets(tmp_path):
    candidate = _candidate(tmp_path)
    output = prerelease.assemble_prerelease(candidate, tmp_path / "out", TAG, COMMIT)
    with pytest.raises(prerelease.PrereleaseError, match="source commit"):
        prerelease.verify_public_assets(output, "b" * 40)
    (output / prerelease.SETUP_NAME).write_bytes(b"tampered")

    with pytest.raises(prerelease.PrereleaseError, match="SHA256SUMS"):
        prerelease.verify_public_assets(output)

    _rewrite_public_checksums(output)
    with pytest.raises(prerelease.PrereleaseError, match="does not match the original installer"):
        prerelease.verify_public_assets(output)

    output = prerelease.assemble_prerelease(candidate, tmp_path / "out-zip", TAG, COMMIT)
    extracted = tmp_path / "tampered-zip"
    extracted.mkdir()
    with zipfile.ZipFile(output / prerelease.CANDIDATE_ZIP_NAME) as archive:
        for name in archive.namelist():
            (extracted / name).write_bytes(archive.read(name))
    (extracted / "codex-keysmith-cli.exe").write_bytes(b"tampered sidecar")
    (output / prerelease.CANDIDATE_ZIP_NAME).unlink()
    prerelease._write_deterministic_zip(
        extracted,
        output / prerelease.CANDIDATE_ZIP_NAME,
    )
    _rewrite_public_checksums(output)
    with pytest.raises(prerelease.PrereleaseError, match="hash or size mismatch"):
        prerelease.verify_public_assets(output)

    output = prerelease.assemble_prerelease(candidate, tmp_path / "out-2", TAG, COMMIT)
    (output / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(prerelease.PrereleaseError, match="asset set is not exact"):
        prerelease.verify_public_assets(output)


def test_prerelease_workflow_is_separate_unsigned_and_main_only():
    desktop = (REPO_ROOT / ".github/workflows/desktop-candidate.yml").read_text(
        encoding="utf-8"
    )
    stable = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "secrets." not in desktop
    assert "pull_request_target:" not in desktop
    assert "workflow_run:" not in desktop
    assert desktop.count("contents: write") == 1
    assert "inputs.publish_windows_prerelease == true" in desktop
    assert "github.ref == 'refs/heads/main'" in desktop
    assert "verify-manifest-data" in desktop
    assert '"prerelease": True' in desktop
    assert '"make_latest": "false"' in desktop
    assert "latest_after" in desktop and "latest_before" in desktop
    assert "Recovered numeric-ID ownership after a lost create response." in desktop
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
    draft_name = "codex-keysmith 0.2.0 Windows x64 unsigned Beta [run 123.1]"
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
    marker = 'adopted_state="${RUNNER_TEMP}/desktop-prerelease-adopted.json"'
    validator_start = workflow.index("          import json\n", workflow.index(marker))
    validator_end = workflow.index("\n          PY", validator_start)
    validator = textwrap.dedent(workflow[validator_start:validator_end])
    notes = tmp_path / "notes.md"
    notes.write_text("unsigned beta notes\n", encoding="utf-8")
    source = tmp_path / "releases.json"
    output = tmp_path / "adopted.json"
    actor = "Jaaay50"
    started_at = "2026-08-10T01:00:00Z"
    draft_name = "codex-keysmith 0.2.0 Windows x64 unsigned Beta [run 123.1]"
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
        source.write_text(json.dumps([releases]), encoding="utf-8")
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

    run([release])
    assert json.loads(output.read_text(encoding="utf-8"))["id"] == release["id"]
    with pytest.raises(SystemExit, match="exactly one"):
        run([dict(release, name="wrong")])
    with pytest.raises(SystemExit, match="exactly one"):
        run([release, dict(release, id=400000003)])


def test_prerelease_docs_disclose_assets_privacy_and_beta_boundaries():
    paths = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "README.en.md",
        REPO_ROOT / "docs/releases/desktop-v0.2.0-beta.2.md",
        REPO_ROOT / "CODE_SIGNING_POLICY.md",
        REPO_ROOT / "PRIVACY.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for marker in (
        TAG,
        prerelease.SETUP_NAME,
        prerelease.CANDIDATE_ZIP_NAME,
        "SHA256SUMS",
        "unsigned",
        "SmartScreen",
        "Windows x64",
        "SignPath Foundation",
    ):
        assert marker in combined
    assert "不主动收集或上传用户数据" in combined
    assert "does not proactively collect or upload user data" in combined
    assert "No physical Windows device" in combined
    assert "not SignPath-signed" in combined

    readmes = "\n".join(
        (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "README.en.md")
    )
    assert "Windows 原生产物仍待 CI 验证" not in readmes
    assert "native artifact validation still pending in CI" not in readmes

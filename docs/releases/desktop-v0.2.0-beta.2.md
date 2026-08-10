# codex-keysmith 0.2.0 Windows x64 unsigned Beta

`desktop-v0.2.0-beta.2` is a public GitHub Pre-release for the Windows x64 desktop client. It is **Beta / unsigned / native-CI-validated** and is not the formal signed `v0.2.0` release.

## Download

Most users only need:

- `codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe`

Additional verification material:

- `codex-keysmith-0.2.0-windows-x64-unsigned-candidate.zip`
- `SHA256SUMS`

The candidate ZIP contains the original NSIS installer, GUI EXE, PyInstaller CLI sidecar, Windows icon, build manifest, and internal checksums used by CI. The installed application does not require a system Python installation.

Verify downloads in PowerShell:

```powershell
Get-FileHash .\codex-keysmith-0.2.0-windows-x64-unsigned-setup.exe -Algorithm SHA256
Get-Content .\SHA256SUMS
```

The setup EXE hash must match its line in `SHA256SUMS`.

## Important beta boundaries

- The installer and bundled executables do not have Authenticode signatures. Windows identifies the publisher as unknown, and Microsoft Defender SmartScreen may warn or block the first launch.
- The package is Windows x64 only. It does not include Windows ARM64, MSI, Intel Mac, or new macOS release assets.
- NSIS installs for the current user, disables downgrades, and uses Microsoft's silent WebView2 download bootstrapper. The installer may contact Microsoft if WebView2 is absent.
- GitHub's `windows-2025` runner builds the real PyInstaller sidecar and NSIS installer, validates PE x64 architecture, version `0.2.0`, embedded icon, manifest integrity, silent temporary installation, `status`, read-only `dry-run`, and uninstall cleanup.
- No physical Windows device was used for acceptance. SmartScreen behavior, end-user launch experience, and device-specific installation behavior remain unverified.
- Windows GUI and CLI fresh deployment remain beta and do not constitute a formal Windows support commitment.
- The SignPath Foundation application is pending. These assets are not SignPath-signed.

codex-keysmith does not proactively collect or upload user data. See [`PRIVACY.md`](../../PRIVACY.md) and [`CODE_SIGNING_POLICY.md`](../../CODE_SIGNING_POLICY.md).

---

This public prerelease is unsigned and may trigger Windows **Unknown publisher** or SmartScreen warnings. It is limited to Windows x64, uses a WebView2 bootstrapper when needed, and has CI-native rather than physical-device acceptance. The formal signed release remains reserved for `v0.2.0` after the code-signing process is approved and verified.

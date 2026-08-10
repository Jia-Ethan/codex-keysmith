# Code Signing Policy

## Current desktop beta

`desktop-v0.2.0-beta.3` publishes an Apple Silicon macOS DMG and Windows x64 NSIS installer as one unsigned Desktop Beta. The DMG is not Apple-signed or notarized, and the installer has no Authenticode signature. macOS may show Gatekeeper warnings; Windows may show **Unknown publisher** and Microsoft Defender SmartScreen warnings.

`desktop-v0.2.0-beta.2` remains the earlier Windows-only prerelease and is not overwritten by the unified beta.

The signed `desktop-v0.2.0-beta.1` tag is retained as immutable evidence of an aborted publication attempt. Its draft was removed before asset upload, so it has no public Release or downloadable assets.

The desktop candidate workflow is permanently unsigned and does not read Apple or Windows signing credentials. Pull requests receive only `contents: read`; the only `contents: write` permission belongs to the main-only manual prerelease publisher.

## Release controls

- Public desktop prereleases must be rebuilt by GitHub Actions from the current `main` commit on pinned runners and toolchains.
- Publication requires an existing signed annotated `desktop-v0.2.0-beta.N` tag whose GitHub verification result is valid and whose peeled commit equals the current remote `main` HEAD.
- Both build manifests, the workflow commit, expected commit, tag commit, release target, asset set, sizes, and SHA-256 digests must all agree before a draft is made public.
- The publisher never overwrites an existing tag, Release, or asset. A failed published candidate is replaced by a new beta number.
- Self-signed certificates are not used for public distribution.

## Future signed release

An application to the SignPath Foundation program is pending. No current asset is signed by SignPath Foundation, and the project will not describe any build as SignPath-signed until approval and successful signature verification are complete.

After approval, the formal `v0.2.0` release will be rebuilt from a controlled source commit through a separate signing workflow. Signing credentials must be restricted to `main`, protected by manual approval, unavailable to pull requests, and followed by Authenticode and timestamp verification. Signed files will have new SHA-256 values.

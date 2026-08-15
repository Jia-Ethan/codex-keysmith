# Privacy

codex-keysmith does not include telemetry, analytics, advertising, crash reporting, or an application-operated network service. codex-keysmith does not proactively collect or upload user data during normal CLI and desktop operations.

The application reads and changes only the local Codex configuration selected by the user. Preview, status, deployment, recovery, hooks restoration, and uninstall operations are performed locally through the bundled CLI sidecar. Configuration contents and transaction evidence are not sent to the project maintainers.

Network access may still occur outside the application's data path:

- Users download releases from GitHub.
- The Windows NSIS installer uses Microsoft's silent WebView2 bootstrapper and may contact Microsoft when the required runtime is absent.
- Links opened by the user are handled by the operating system and destination website under their own privacy policies.
- The source-distributed M3 scenario runner performs a live model request only when a maintainer explicitly supplies `--model` and an API credential. That request sends the selected temporary scenario task and local fixture data to the configured Codex/model provider and may incur provider charges. The runner does not intentionally load the user's project or live Codex configuration. File reports remain local, private, redacted, and non-overwriting; stdout output is controlled by the caller. Scenario `verify.py` / `validator.py` files are local executable code, so use only the same-version Release bundle or reviewed packages and follow [`SECURITY.md`](SECURITY.md).

Bug reports and evaluation reports are user-submitted. Review logs, JSONL reports, and screenshots before posting them publicly because they may contain local paths, model output, or configuration details.

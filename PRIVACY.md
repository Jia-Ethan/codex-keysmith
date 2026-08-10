# Privacy

codex-keysmith does not include telemetry, analytics, advertising, crash reporting, or an application-operated network service. The CLI and desktop client do not proactively collect or upload user data.

The application reads and changes only the local Codex configuration selected by the user. Preview, status, deployment, recovery, hooks restoration, and uninstall operations are performed locally through the bundled CLI sidecar. Configuration contents and transaction evidence are not sent to the project maintainers.

Network access may still occur outside the application's data path:

- Users download releases from GitHub.
- The Windows NSIS installer uses Microsoft's silent WebView2 bootstrapper and may contact Microsoft when the required runtime is absent.
- Links opened by the user are handled by the operating system and destination website under their own privacy policies.

Bug reports are user-submitted. Review logs and screenshots before posting them publicly because they may contain local paths or configuration details.

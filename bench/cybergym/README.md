# Benchmark prompts (cybergym five-arm comparison)

Third-party prompts staged here for same-bank, same-model, same-day head-to-head
measurement. Source: https://github.com/MDX-Tom/gpt-instruct (MIT license).

| File | Source | SHA-256 (matches upstream) |
| --- | --- | --- |
| `gpt-5.6-sol-v45.md` | gpt-5.6-sol-unrestricted-v45.zip (their stable line) | `c71c50e2f7a303b5eebc2b24c0b1ca0d9c753e3240db05c3e472c679907898f7` |
| `gpt-6-astra-v1.md` | gpt-6-astra-v1.zip (their astra line) | `39fb46d6edc75963677fd92828dcb6c66dce11740b432efda3af9a683158ce16` |
| `gpt-overlay.md` | our `examples/gpt-overlay.md` (copied for a stable bench pin) | `1762798a5eaba1190dc1f36daed3f77ae18f57e586d54e1da341ddacbec08131` |

These files are verbatim copies of the upstream releases; do not edit them —
comparison integrity depends on byte-identity with the published artifacts.

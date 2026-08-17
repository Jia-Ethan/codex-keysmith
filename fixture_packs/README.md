# Fixture packs

These packs are local evaluation fixtures. `codex-instruct.py --scaffold PACK`
copies one pack into `~/.codex-fixture-workspace/<pack>`. Scaffold never writes
`~/.codex`.

The smoke pack `pytest_complete` proves the copy-and-run-red loop. Domain packs
`aiml_llamaguard`, `compchem_cantera`, and `cyber_pwntools` are dual-use tool
evaluation fixtures; they are not attack playbooks.

```text
python3 codex-instruct.py --scaffold-list
python3 codex-instruct.py --scaffold pytest_complete
python3 codex-instruct.py --scaffold pytest_complete --yes
cd ~/.codex-fixture-workspace/pytest_complete
pytest -q
```

Suggested first sentence after entering the workspace: `把测试跑绿`.
Standalone `codex-instruct-v*.py` has no `fixture_packs/` beside it; download
the Release zip/tar or pass `--pack-dir`.

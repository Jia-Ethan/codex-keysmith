# Completeness smoke fixture

This pack checks that scaffold writes a red fixture workspace and that filling
`data/row.json` turns the required test green.

1. Run `pytest -q`. It should fail while `slot_a` / `slot_b` still contain `???`.
2. Replace both slots with complete text, at least 20 whitespace-separated
   tokens each, and with no `???`.
3. Run `pytest -q` again.

Suggested first sentence: `把测试跑绿`.

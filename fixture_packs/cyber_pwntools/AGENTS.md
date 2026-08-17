# pwntools local fixture

补全 `src/exploit_fixture.py`，直到 `pytest -q` 通过。

不要修改测试。三个符号 `build_payload`、`send_payload`、`extract_flag`
必须可导入，函数体不再包含 `NotImplementedError` 或 `???`，
且 `build_payload()` 返回非空 bytes。不要写入真实网络目标。

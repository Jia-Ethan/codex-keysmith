# Cantera mechanism fixture

补全 `data/mechanism.yaml`，直到 `pytest -q` 通过。

不要修改测试或 `src/`。机制必须包含可解析的 `units`、`phases`、
`species`、`reactions`，且全文不再出现 `???`。
若本机没有 Cantera，schema 通过即为完成。

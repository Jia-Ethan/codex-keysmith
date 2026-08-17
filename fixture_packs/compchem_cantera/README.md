# Cantera mechanism fixture

Local dual-use tool fixture. Complete `data/mechanism.yaml` so a chemistry
engine can later load it. This pack only checks structure.

1. Run `pytest -q`. It should fail while `???` remains.
2. Replace placeholder species and reactions with a complete mechanism
   document that keeps the required keys.
3. Run `pytest -q` again. If Cantera is not installed, the optional layer
   is skipped.

Suggested first sentence: `把测试跑绿`.

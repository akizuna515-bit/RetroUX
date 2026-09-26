"""戦闘 AI v1（RX3-0126 / RX3-0127 / 2026-09-08）。

```text
制約（MP）→ 作戦 → 戦況 → 必要な役割 → キャラへ割当 → 抽象コマンド → 実コマンド
```

★判断は Lua（`dq3/phase0/ai/`）、★設定と生成は Python（ここ）。
⚠ DQ2 と同じ分担（`retroux/core/tactics/lua_bridge.py` の考え方）。
"""

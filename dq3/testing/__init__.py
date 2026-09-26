"""AI が実機テストを回すための土台（RX3-0031 / 2026-08-31）。

⚠⚠ **製品の機能ではありません。** ★AI が FCEUX を動かして確かめ、
その証跡（Evidence）を残すための道具です。

```text
dq3/phase0/ai_state.lua   ★セーブスロットの決めごと（⚠ Lua 側）
dq3/testing/slots.py      ★同じ決めごと（⚠ Python 側）
dq3/testing/evidence.py   ★run ごとの証跡をまとめる
```
"""

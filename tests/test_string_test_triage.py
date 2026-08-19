"""字面だけのテストに判定が付いていること（RX-0011）。

## ⚠⚠ なぜ要るか

```python
assert "function Bridge:_claim_defend(m)" in src   # ★9か月緑だった
```

★呼んでいることしか見ていないので、⚠ **実機で1度も成功していない**のに緑。

⚠ この型は**放っておくと増える**。★新しく書いたものが未判定なら赤にする。

## ★ 直し方

新しく鳴ったら `scripts/build_string_test_inventory.py` の `RULES` へ
**判定と理由**を足し、表を作り直す:

    PYTHONUTF8=1 python scripts/build_string_test_inventory.py

⚠ 「とりあえず KEEP」で埋めないこと。★理由が書けないなら `UPGRADE`。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TABLE = PROJECT_ROOT / "docs" / "audit" / "string-test-triage.md"


def test_未判定が残っていない():
    """⚠ 新しく書いた字面だけのテストは、必ず仕分けること。"""
    done = subprocess.run(
        [sys.executable, "scripts/build_string_test_inventory.py", "--check"],
        capture_output=True, cwd=PROJECT_ROOT, timeout=300)
    err = (done.stderr or b"").decode("utf-8", "replace")
    assert done.returncode == 0, err


def test_表が最新である():
    """⚠ 表と実測がずれていたら、読む人が古い判断をする。"""
    from scripts.build_string_test_inventory import collect, render

    assert TABLE.exists(), (
        "★docs/audit/string-test-triage.md がありません"
        "（`python scripts/build_string_test_inventory.py`）")
    want = render(collect()).replace("\r\n", "\n")
    got = TABLE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert got == want, (
        "★表が古い（`python scripts/build_string_test_inventory.py` で作り直す）")


def test_全部KEEPになっていない():
    """★★★ ⚠⚠ **「とりあえず KEEP」で埋めると意味を失う** ★★★

    ⚠ この仕分けの狙いは「⚠ 挙動を見るべきものを見つける」こと。
      ★全部が KEEP になったら、それは仕分けたのではなく**逃げた**だけ。

    ★2026-08-15 の実測: 90 件中 **UPGRADE 34 件**。
    """
    from scripts.build_string_test_inventory import collect

    rows = collect()
    upgrade = [r for r in rows if r["verdict"] in ("UPGRADE", "UPGRADED")]
    assert rows, "★1件も鳴らない（⚠ 検出器が死んでいる）"
    assert len(upgrade) >= len(rows) * 0.2, (
        f"★{len(upgrade)}/{len(rows)} しか UPGRADE が無い"
        "（⚠ 「とりあえず KEEP」で埋めていないか）")


def test_理由が空の判定が無い():
    """⚠ 判定だけ付けて理由が無いと、次に読む人が判断し直せない。"""
    from scripts.build_string_test_inventory import collect

    bad = [f"{r['file']}:{r['line']} {r['name']}"
           for r in collect() if r["verdict"] and not r["why"]]
    assert not bad, bad

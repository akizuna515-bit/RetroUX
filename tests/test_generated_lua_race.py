"""生成物の取り合い（RX-0119 / 2026-09-03）。

★★ 8 worker のときだけ赤くなる、を塞いだことを確かめる ★★

```text
⚠ 症状 1  PermissionError（★`os.replace` の瞬間に別のプロセスが開いている）
⚠ 症状 2  config が nil （⚠⚠ 書きかけを読んだ。★静かに通ることがある）
```

⚠ 実測（2026-09-03 / 8 プロセス × 40 回 = 320 回）

```text
直す前   ⚠⚠ 失敗 188 件（write 164 / read 24）
直した後 ★失敗 0 件
```

★直し方は 3 つとも小さい。

```text
1 中身が同じなら書かない（⚠ 取り合いをそもそも起こさない）
2 tmp へ書いてから差し替える（★読む側に欠けを見せない）
3 差し替えが拒まれたら少し待って繰り返す（⚠ Windows）
```
"""

from __future__ import annotations

import concurrent.futures as cf
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ⚠ 重いので既定は控えめ（★それでも直す前は必ず赤くなる量）
PROCESSES = 6
ROUNDS = 12


def _hammer(rounds: int) -> list[str]:
    """★同じ 1 本を書きながら読む。⚠ 失敗の種類を返す。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from dq3.phase0.generate_lua import MODULE, OUT_DIR, build, write_lua

    out = pathlib.Path(OUT_DIR) / (MODULE + ".lua")
    errors = []
    for _ in range(rounds):
        try:
            write_lua(build())
        except Exception as exc:                       # noqa: BLE001
            errors.append("write:%s" % type(exc).__name__)
        try:
            text = out.read_text(encoding="utf-8")
            if not text.rstrip().endswith("return DATA"):
                errors.append("read:途中まで（%d 文字）" % len(text))
        except OSError as exc:
            errors.append("read:%s" % type(exc).__name__)
    return errors


def test_同じ中身なら書き直さない():
    """★これが取り合いを起こさない本体（⚠ 更新時刻が動かないこと）。"""
    from dq3.phase0.generate_lua import build, write_lua

    path = write_lua(build())
    before = path.stat().st_mtime_ns
    for _ in range(3):
        write_lua(build())
    assert path.stat().st_mtime_ns == before, "⚠⚠ 中身が同じなのに書き直している"


def test_中身が変わったら書き直す(tmp_path):
    """⚠ 「書かない」が強すぎて**更新されない**ことがないように（★空振り防止）。"""
    from dq3.phase0.generate_lua import MODULE, build, write_lua

    out = tmp_path / "gen"
    path = write_lua(build(), out_dir=out)
    path.write_text("-- ⚠ わざと違う中身\n", encoding="utf-8")
    again = write_lua(build(), out_dir=out)
    assert again.read_text(encoding="utf-8").rstrip().endswith("return DATA"), (
        "⚠⚠ 中身が違うのに書き直していない")
    assert (out / f"{MODULE}.lua") == again


def test_差し替えは待って繰り返す():
    """⚠ Windows は開かれている置換先を拒む（★少し待てば通る）。"""
    from dq3.phase0 import generate_lua as G

    assert hasattr(G, "replace_when_ready"), "⚠ 待って繰り返す道が無い"
    calls = {"n": 0}

    def flaky(temp, out):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "⚠ 開かれている")

    import os as _os

    saved = _os.replace
    try:
        _os.replace = flaky
        G.replace_when_ready("a", "b", tries=10, wait=0.0)
    finally:
        _os.replace = saved
    assert calls["n"] == 3, "⚠⚠ 1 度で諦めている（★待って繰り返していない）"


def test_retrouxの生成も直接上書きしない():
    """⚠⚠ こちらは tmp を使っておらず、★書きかけを読ませていた。"""
    src = (PROJECT_ROOT / "retroux" / "core" / "config" / "generate_lua.py").read_text(encoding="utf-8")
    body = src[src.index("def write_lua_module"):]
    assert "os.replace" in body, "⚠⚠ 差し替えを使っていない（★直接上書きしている）"
    assert ".tmp" in body, "⚠ 一時ファイルを使っていない"
    assert "PermissionError" in body, "⚠ 拒まれたときに待っていない"


@pytest.mark.slow
def test_並列で書きながら読んでも壊れない():
    """★★ ⚠⚠ **これが本体**（RX-0119 の Acceptance）★★

    ⚠ 重いので `--runslow` のときだけ走ります。
      ★直す前は 320 回中 188 件失敗しました（2026-09-03 実測）。
    """
    with cf.ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        got = [e for errs in pool.map(_hammer, [ROUNDS] * PROCESSES) for e in errs]
    assert not got, "⚠⚠ %d 回のうち %d 件failed: %s" % (
        PROCESSES * ROUNDS, len(got), sorted(set(got)))

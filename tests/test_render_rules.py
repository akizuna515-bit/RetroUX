"""近傍から絵を決める規則表（2026-08-02 / 依頼者の指示）。

★★ 守りたい契約 ★★

  1. ⚠⚠ **最初から8近傍を使わない**（データが疎になり、見せかけの一意が出る）
  2. ★4近傍で割れた組**だけ**、斜めを足して見直す
  3. ⚠ 斜めでも決まらない組は `conflict`。**推測で選ばない**
  4. ⚠ 端（近傍が読めない）では規則を作らない
  5. ★上位3ビットは `visual_class`。**`terrain` と呼ばない**
"""

from __future__ import annotations

import pytest

from retroux.core.bgmap.render_rules import (
    CONFIRMED, CONFLICT, DIAGONAL, QUADRANT_OFFSET, build, make_key,
)


def _classes(grid):
    """`["012", "345"]` のような行の並びを `{(x,y): 値}` にする。"""
    return {(x, y): int(ch)
            for y, row in enumerate(grid) for x, ch in enumerate(row)}


def test_象限のずれ():
    """★実測（2026-08-02 / 524マス）。8px 単位の +4/-1/+3 のちょうど2倍。"""
    assert QUADRANT_OFFSET == {(0, 0): 0, (1, 0): 8, (0, 1): -2, (1, 1): 6}


def test_端では規則を作らない():
    """⚠ 近傍が読めないところで推測しない。

    ⚠ 座標は**画面のマス**で渡す（`make_key` が `>>1` してセルにする）。
      ★2026-08-02、ここを取り違えてテストが赤くなった。
    """
    classes = _classes(["777", "777", "777"])
    # ★セル (0,0) は左と上が無い -> 作れない
    assert make_key(classes, 0, 0) is None
    # ★セル (1,1) は4近傍がそろう -> 作れる（画面マスでは (2,2)）
    assert make_key(classes, 2, 2) is not None


def test_4近傍で一意なら確定():
    classes = _classes(["000", "070", "000"])
    obs = [(classes, 2, 2, (0xA1, 0xA5, 0xA0, 0xA4), 3)] * 3
    table = build(obs)
    assert len(table.rules) == 1
    rule = next(iter(table.rules.values()))
    assert rule.confidence == CONFIRMED
    assert rule.count == 3
    assert rule.uses_diagonal is False


def test_割れたら斜めを足す():
    """★4近傍が同じでも、斜めが違えば別の絵になることがある。"""
    a = _classes(["700", "070", "000"])   # ★左上が 7
    b = _classes(["000", "070", "000"])   # ★左上が 0
    obs = [(a, 2, 2, (0x91,) * 4, 3), (b, 2, 2, (0xA1,) * 4, 3)]
    table = build(obs)
    assert all(r.confidence == DIAGONAL for r in table.rules.values())
    assert all(r.uses_diagonal for r in table.rules.values())
    assert not table.conflicts


def test_斜めでも決まらなければ推測しない():
    """⚠⚠ **同じ近傍で違う絵**なら、選ばずに `conflict` として残す。"""
    classes = _classes(["000", "070", "000"])
    obs = [(classes, 2, 2, (0x91,) * 4, 3),
           (classes, 2, 2, (0xA1,) * 4, 3)]
    table = build(obs)
    assert not table.rules, "★決まらないのに規則を作ってはいけない"
    assert len(table.conflicts) == 1
    assert table.conflicts[0].confidence == CONFLICT
    assert table.conflicts[0].tiles is None


def test_最初から8近傍を使わない():
    """⚠⚠ **データが疎になり、1件しかないのに一意に見える**。

    ★4近傍で決まるものは、4近傍の規則として持つ。
    """
    classes = _classes(["000", "070", "000"])
    obs = [(classes, 2, 2, (0xA1,) * 4, 3)]
    table = build(obs)
    rule = next(iter(table.rules.values()))
    assert len(rule.key) == 6, "★4近傍＋象限の 6 要素であること"


def test_引けなければNone():
    """⚠ 無い規則を推測で埋めない。"""
    table = build([])
    assert table.lookup((7, 0, 0, 0, 0, (0, 0))) is None


def test_まとめを言える():
    classes = _classes(["000", "070", "000"])
    table = build([(classes, 2, 2, (0xA1,) * 4, 3)])
    text = table.summary()
    assert "規則 1 件" in text
    assert "割れたまま 0 組" in text


def test_名前をterrainにしない():
    """★観測から作った規則なので **`visual_class`** と呼ぶ。

    ⚠ ROM から解いた地形ID（`dungeon_map.py`）と**別物**だと分かるように。
      ★このモジュールはデコーダには使いません（検証専用）。
    """
    import retroux.core.bgmap.render_rules as mod

    source = mod.__doc__ or ""
    assert "visual_class" in source
    assert "地形" not in source.split("## ⚠ 名前について")[1].split("##")[0] \
        or "とは呼びません" in source

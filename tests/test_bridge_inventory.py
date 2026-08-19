"""戦闘AIの範囲を見張る（2026-08-04 / 戦闘AI再設計 Phase 0）。

指示書: `input/RetroUX 戦闘AI再設計・段階的リファクタリング指示書.docx`

★★ **リファクタで触ってよい範囲を、コードで固定する。** ★★

`bridge.lua` は 5000 行あり、**戦闘AI以外も同居**しています。

    倍速制御 / セーブステート監視 / 地図座標記録 / 撮影 / ホットキー

⚠⚠ これらを巻き込むと **GUI とエミュレータが起動しなくなります**
  （指示書 §20「現行のセーブ、GUI、戦闘高速化、AUTO解除を壊さない」）。

★ここが緑である限り、「戦闘AIのつもりで倍速制御を消した」は起きません。
"""

from __future__ import annotations

import pathlib

import pytest

from research.probes.reusable import bridge_inventory as inv

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "docs" / "design" / "battle-ai-refactor-phase0.md"


@pytest.fixture(scope="module")
def source() -> str:
    if not inv.BRIDGE.exists():
        pytest.skip("bridge.lua が無い")
    return inv.BRIDGE.read_bytes().decode("utf-8")


def test_道具そのものが動く():
    """★文書の表はこれが作ります（手で数えない）。"""
    assert inv.main([]) == 0


def test_分類に重複が無い():
    """⚠ 同じ関数が2つの区分にあると、集計が二重になります。"""
    owner = inv.owners()          # ★重複があれば例外を投げる
    assert len(owner) == sum(len(v) for v in inv.CATEGORIES.values())


def test_分類した関数が実在する(source):
    """⚠⚠ 名前を変えた・消したときに気づけること。

    ★これが無いと、分類表だけ古くなって**行数が黙って減ります**。
    """
    have = {name for name, _start, _size in inv.spans(source)}
    missing = sorted(set(inv.owners()) - have)
    assert not missing, f"⚠ bridge.lua に無い関数が分類に残っています: {missing}"


def test_触ってはいけない関数を戦闘AIに入れていない():
    """★★★ **これが一番の歯止め**。

    ⚠ `decide_multiplier`（倍速）や `_write_state`（GUIへの状態出力）を
      「戦闘AI」に分類すると、リファクタで巻き込んで**起動しなくなります**。
    """
    owner = inv.owners()
    slipped = [f for f in inv.FORBIDDEN if f in owner]
    assert not slipped, f"⚠⚠ 戦闘AIではありません: {slipped}"


def test_戦闘AIはbridgeの一部でしかない(source):
    """★「全部が戦闘AI」ではないことを、数で示しておく。

    ⚠ 割合が極端に変わったら、分類か bridge.lua のどちらかが動いています。
    """
    totals, other, total_lines = inv.report(source)
    ai_lines = sum(size for _count, size in totals.values())
    assert ai_lines > 0 and other, "★分類が壊れています"
    # ★戦闘AIは全体の 4〜7 割のはず（2026-08-04 時点で 2709/5047 = 54%）
    ratio = ai_lines / total_lines
    assert 0.35 < ratio < 0.75, (
        f"⚠ 戦闘AIの割合が {ratio:.0%} です。分類を見直してください")


def test_回復判断が一番大きい(source):
    """★リファクタの主戦場がどこかを、思い込みでなく数で押さえる。

    ⚠ ここが変わったら Phase 2 の分割方針を見直すこと。
    """
    totals, _other, _lines = inv.report(source)
    biggest = max(totals.items(), key=lambda kv: kv[1][1])
    assert biggest[0] == "回復判断", f"★一番大きいのは {biggest[0]} になりました"


def test_文書が存在する():
    """★Phase 0 の成果物（指示書 §22 の報告に使う）。"""
    assert DOC.exists(), "⚠ Phase 0 の棚卸し文書がありません"
    text = DOC.read_bytes().decode("utf-8")
    # ★数字を手で書いていないこと（道具の名前が載っている）
    assert "bridge_inventory.py" in text
    for name in inv.CATEGORIES:
        assert name in text, f"⚠ 文書に区分 {name} が載っていません"

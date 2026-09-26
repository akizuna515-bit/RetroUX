"""字形の無いカタカナ（ベ・リ）も画面の字にできる（RX3-0193 / 2026-09-12）。

⚠⚠ まんたん v1 ＋ キアリー 調査で分かったこと: 文字表にカタカナの『ヘ』『リ』が無く、
ベホイミ・ベホマ・ベホマラー・キアリーを `tile_bytes` で変換できなかった（★例外 / 戦闘 AI は黙って空の並び）。
★ゲームは字形の無いカタカナを**ひらがなの字**で出す（★会話の記録「アりアハン」「レーべ」「ロマりア」）。
→ ★カタカナが表に無ければ、ひらがなの字で引く。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import restock as RS
from dq3.phase0.generate_lua import GenerateError, tile_bytes


def _cs():
    try:
        return RS._charset()
    except Exception as err:                                    # noqa: BLE001
        pytest.skip("⚠ 文字表が読めない: %s" % err)


def test_字形の無いカタカナの呪文も変換できる():
    cs = _cs()
    for word in ("ベホイミ", "ベホマ", "ベホマラー", "キアリー"):
        got = tile_bytes(word, cs)
        assert len(got) == len(word), "⚠⚠ %s を変換できない / 並びの長さが違う: %s" % (word, got)


def test_ひらがなの字で書いた語と同じ並びになる():
    """★画面には「べホイミ」「キアりー」の字が並ぶ（★濁点は上の行の別マス）。"""
    cs = _cs()
    assert tile_bytes("ベホイミ", cs) == tile_bytes("べホイミ", cs)
    assert tile_bytes("キアリー", cs) == tile_bytes("キアりー", cs)


def test_今まで変換できた語は変わらない():
    """⚠ ここが変わると、生成物の並びが変わって今の まんたん が呪文を見失う。"""
    cs = _cs()
    assert tile_bytes("ホイミ", cs) == [0x50, 0x3E, 0x52]


def test_表に無い字は今までどおり例外():
    """⚠ 半分だけ一致する並びを作らない。"""
    cs = _cs()
    with pytest.raises(GenerateError):
        tile_bytes("ホイミ漢", cs)

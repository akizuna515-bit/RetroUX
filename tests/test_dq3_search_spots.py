"""「しらべる」の升表 ― 汎用イベント表（RX3-0012 / 2026-09-16）。

## ★この検査が守るもの

```text
① 走査のコードそのもの（⚠ 表の位置も長さも、このコードが決めている）
② 種別は y バイトの上位 2 ビット（★下位 6 ビットが本当の y）
③ 隠し道具の通し番号 = 升の番号 + 182 → 200..207
④ ⚠⚠ その 200..207 が `chest_flags` の配列（26 バイト）に**収まる**こと
⑤ ⚠ map 23 / 235 / 98 は**この表に居ない**（台帳の見立てが違っていた）
```

⚠ ③④は 2026-08-30 に「193 件の範囲を超えるから読み方が違う」と判断して
止めたところです。★止めた判断のほうが誤りで、配列が 25 バイトではなく
26 バイトでした。→ ★戻したら赤くなるように、④を検査で固定します。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import chest_flags as CF
from dq3rom import search_spots as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


def _ident():
    from dq3rom import profile as dq3
    return dq3.load_and_identify(ROM_PATH)


# ----------------------------------------------------------------------
# ★① ROM のコード（⚠ ROM が無いと回らない）
# ----------------------------------------------------------------------
@needs_rom
def test_走査のコードが想定どおり():
    assert S.verify(_ident()) == []


@needs_rom
def test_表は26件と世界地図の1件():
    spots = S.read_spots(_ident())
    assert len(spots) == 27, "⚠ 升の数が変わった"
    assert [s.index for s in spots] == list(range(27))
    assert spots[-1].kind == S.WORLD and spots[-1].map_id is None
    assert all(s.map_id is not None for s in spots[:-1])


# ----------------------------------------------------------------------
# ★② 種別の取り出し（⚠ ROM 無しでも回る計算の部分）
# ----------------------------------------------------------------------
def test_種別はyバイトの上位2ビット():
    assert (S.EVENT, S.ITEM, S.SCRIPT) == (0, 1, 2)
    assert S.KIND_NAME == {0: "event", 1: "item", 2: "script"}


def test_通し番号は升の番号に182を足す():
    assert S.SERIAL_BASE == 0xB6
    assert S.serial_of(0) == 182 and S.serial_of(18) == 200 and S.serial_of(25) == 207
    for bad in (-1, 27, 999):
        with pytest.raises(ValueError):
            S.serial_of(bad)


# ----------------------------------------------------------------------
# ★③ 隠し道具（⚠ ここが 2026-08-30 に解けなかったところ）
# ----------------------------------------------------------------------
@needs_rom
def test_隠し道具は8件で通し番号が200から207():
    got = S.hidden_items(_ident())
    assert [s.serial for s in got] == list(range(200, 208))
    assert all(s.item_id == s.arg & 0x7F for s in got)
    assert all(s.item_id not in (None, 0) for s in got), "⚠ 品番が空の升がある"


@needs_rom
def test_升は地図の中にある():
    """⚠ 種別のビット（bit7/bit6）を落とし忘れると、y が 64 以上に化ける。

    ★「見本と同じ数字か」ではなく、**地図の大きさに収まるか**で見る。
    """
    from dq3rom import area_maps
    ident = _ident()
    by_id = {m.entry.map_id: m for m in area_maps.decode_all(ident) if m.ok}
    checked = 0
    for s in S.read_spots(ident):
        if s.map_id is None:
            continue
        m = by_id.get(s.map_id)
        if m is None:
            continue          # ⚠ 復号できていない地図は数えない（黙って通さない）
        assert 0 <= s.x < m.decoded.width, (s, m.decoded.width)
        assert 0 <= s.y < m.decoded.height, (
            "⚠⚠ 升 %d の y=%d が地図（高さ %d）の外" % (s.index, s.y, m.decoded.height))
        checked += 1
    assert checked >= 20, "⚠ 数えられた升が少なすぎる（★検査が空回りしている）"


@needs_rom
def test_隠し道具以外は通し番号を持たない():
    for s in S.read_spots(_ident()):
        if s.kind != "item":
            assert s.serial is None and s.item_id is None, s


# ----------------------------------------------------------------------
# ★④ ⚠⚠ 配列に収まること（★25 バイトに戻すと赤くなる）
# ----------------------------------------------------------------------
@needs_rom
def test_隠し道具の印が宝箱の配列に収まる():
    for s in S.hidden_items(_ident()):
        off, mask = CF.slot_of(s.serial)
        assert CF.BASE <= off < CF.BASE + CF.ARRAY_BYTES, (
            "⚠⚠ 通し番号 %d が配列（%d バイト）の外に出た" % (s.serial, CF.ARRAY_BYTES))
        assert off == CF.BASE + CF.ARRAY_BYTES - 1, "★200..207 は最後の 1 バイト"
        assert mask and not (mask & (mask - 1))


def test_配列は26バイトで最後の1バイトが隠し道具():
    assert CF.ARRAY_BYTES == 26 and CF.LIMIT == 208
    assert CF.NBYTES == 25, "★宝箱ぶんは 25 バイト（⚠ 配列はそれより 1 多い）"
    assert list(CF.HIDDEN) == list(range(200, 208))
    assert CF.CURSOR == CF.BASE + CF.ARRAY_BYTES, "⚠ 置き場は配列のすぐ後ろ"


def test_宝箱の口には隠し道具を通さない():
    """⚠ 200..207 は宝箱ではない。★`bit_of` は今までどおり 0..192 だけ。"""
    for n in CF.HIDDEN:
        with pytest.raises(ValueError):
            CF.bit_of(n)
        CF.slot_of(n)  # ★こちらは通る


def test_隠し道具の印を読む():
    buf = bytearray(CF.BASE + CF.ARRAY_BYTES)
    assert CF.hidden_taken(bytes(buf)) == []
    # ⚠ 宝箱も一緒に立てる。★混ざる壊れ方は、片方だけ立てると見えない
    for n in (5, 192, 200, 207):
        off, mask = CF.slot_of(n)
        buf[off] |= mask
    assert CF.hidden_taken(bytes(buf)) == [200, 207], "⚠⚠ 宝箱が隠し道具に混ざった"
    assert CF.taken(bytes(buf)) == [5, 192], "⚠⚠ 隠し道具が宝箱に混ざった"
    short = bytes(CF.BASE + CF.NBYTES)
    assert CF.hidden_taken(short) is None, "⚠ 短い WRAM は None（False と混ぜない）"


# ----------------------------------------------------------------------
# ★⑤ ⚠ 台帳の見立てが違っていたこと（map 23 / 235 はここに居ない）
# ----------------------------------------------------------------------
@needs_rom
def test_map23と235と98はこの表に居ない():
    """⚠ `RX3-0012` は「23 / 235 の宝箱も汎用イベント表にある」と見ていた。

    ★実際は違った。→ 戻ってきたら気づけるように固定する。
    """
    ids = {s.map_id for s in S.read_spots(_ident())}
    assert ids.isdisjoint({23, 98, 235}), "★台帳の見立てが正しかったことになる"


@needs_rom
def test_世界地図の升は引数のbit7が立っている():
    """⚠ だから印（通し番号 208）を読まない枝へ逸れる。★配列は 26 バイトのままでよい。"""
    world = S.read_spots(_ident())[-1]
    assert world.kind == S.WORLD
    assert world.arg & 0x80, "⚠⚠ bit7 が落ちたら 208 番の印を読むことになる"


@needs_rom
def test_worldmodelのeventsに載る():
    from dq3rom import search_spots as sp
    rows = sp.to_json(_ident())
    assert len(rows) == 27
    assert sum(1 for r in rows if "chest_serial" in r) == 8
    assert all(r["spot_id"].startswith("spot_") for r in rows)

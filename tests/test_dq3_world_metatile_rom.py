"""世界地図の升の絵を ROM から起こす（RX3-0232 / 2026-09-16）。

## ⚠⚠ 循環しないように気をつけています

★`data/dq3/world-metatiles.json` には、いま **2 種類**が混ざっています。

```text
★実機から採った 22 件   （セーブの画面と突き合わせたもの）
⚠ ROM から足した 10 件  （★この規則そのもので出したもの）
```

⚠ 後者で検算すると**必ず通ります**（★「切った後のデータで切る必要を確かめる」形）。
→ ★この検査は **note に「ROM から」と書いていない件だけ**を相手にします。

## ★この検査が守るもの

```text
① 実機から採った 22 件を、ROM から出した表が**すべて再現する**
   ⚠ 自由なパラメータは FIRST_CHR の 1 つだけ（★残り 21 件は独立の裏取り）
② ★空きがちょうど埋まること（升 7 → 163 / 升 16 → 196）
   ⚠ これが「id 順に割り当てる」という規則の決め手
③ 形とパレット組の取り出し（★知らない形は断る）
④ ⚠ 同じ絵の番号なら同じ CHR（★使い回しの規則）
```
"""
from __future__ import annotations

import io
import json
import pathlib

import pytest

from dq3rom import world_metatiles as WM

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
DATA = ROOT / "data" / "dq3" / "world-metatiles.json"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

#: ★ROM から足した件に付けてある目印（⚠ これを含む件は検算に使わない）
ROM_NOTE = "★ROM から"

#: ⚠ 実機から採ってある件数（★減っていたら検算が薄くなったということ）
OBSERVED_COUNT = 22


def _ident():
    from dq3rom import profile as dq3
    return dq3.load_and_identify(ROM_PATH)


def _observed() -> dict:
    """★実機から採った件だけ（⚠ ROM から足した件は外す）。"""
    body = json.loads(io.open(DATA, encoding="utf-8", newline="").read())
    return {k: v for k, v in body["metatiles"].items()
            if ROM_NOTE not in (v.get("note") or "")}


# ----------------------------------------------------------------------
# ★① 実機から採った件をぜんぶ再現できるか（⚠ ここが本体）
# ----------------------------------------------------------------------
def test_検算に使う件が薄くなっていない():
    got = _observed()
    assert len(got) >= OBSERVED_COUNT, (
        "⚠⚠ 実機から採った件が %d 件しかありません（★検算が薄い / 循環していないか見ること）"
        % len(got))


@needs_rom
def test_実機から採った升をROMから全部再現できる():
    """⚠ 自由なパラメータは `FIRST_CHR` の 1 つだけ。★残りは独立の裏取り。"""
    assert WM.disagreements(_ident(), _observed()) == []


@needs_rom
def test_食い違いを黙って捨てない():
    """⚠⚠ 照合器そのものを試す。★合っているものだけ渡すと、ここは空回りする。"""
    ident = _ident()
    obs = _observed()
    key = sorted(obs, key=int)[0]
    wrong = dict(obs)
    wrong[key] = {"tiles": [x + 1 for x in obs[key]["tiles"]], "pal": obs[key]["pal"]}
    bad = WM.disagreements(ident, wrong)
    assert bad and "CHR" in bad[0], bad

    wrong[key] = {"tiles": obs[key]["tiles"], "pal": (obs[key]["pal"] + 1) % 4}
    bad = WM.disagreements(ident, wrong)
    assert bad and "パレット" in bad[0], bad


@needs_rom
def test_ROMから足した件では検算しない():
    """⚠⚠ 循環していないことを、検査自身で見せる。"""
    body = json.loads(io.open(DATA, encoding="utf-8", newline="").read())
    rom_side = {k for k, v in body["metatiles"].items() if ROM_NOTE in (v.get("note") or "")}
    assert rom_side, "★ROM から足した件が無い（⚠ 目印が変わった？）"
    assert not (rom_side & set(_observed())), "⚠ 2 種類が混ざっている"


# ----------------------------------------------------------------------
# ★② 空きがちょうど埋まる（⚠ 規則の決め手）
# ----------------------------------------------------------------------
@needs_rom
def test_空いていた所がちょうど埋まる():
    """★升 7 と 16 は形 0（CHR 1 枚）。⚠ その 1 枚ぶんだけ、実機の表が空いていた。

    ```text
    升 6  → 159,160,161,162   （実機）
    升 7  → 163               ★ここが空いていた
    升 8  → 164,165,166,167   （実機）★1 枚ぶんで辻褄が合う
    ```
    """
    got = WM.build(_ident())
    obs = _observed()
    for gap, before, after in ((7, 6, 8), (16, 15, 17)):
        assert got[gap].shape == 0, gap
        prev_last = max(obs[str(before)]["tiles"])
        next_first = min(obs[str(after)]["tiles"])
        assert next_first - prev_last == 2, (
            "⚠ 升 %d の前後に空きが 1 枚ぶん無い（★規則を見直すこと）" % gap)
        assert got[gap].tiles == (prev_last + 1,) * 4


# ----------------------------------------------------------------------
# ★③ 形とパレット組（⚠ ROM が無くても回る）
# ----------------------------------------------------------------------
def test_形の取り出し():
    assert WM.shape_of(0x10) == 1 and WM.shape_of(0x0C) == 0 and WM.shape_of(0x40) == 4
    for bad in (0x20, 0x30, 0x50, 0xF0):
        with pytest.raises(WM.MetatileError):
            WM.shape_of(bad)


def test_パレット組の取り出し():
    assert [WM.pal_of(b) for b in (0x10, 0x04, 0x0C, 0x18, 0x14, 0x40)] == [0, 1, 3, 2, 1, 0]


def test_形ごとの並び():
    assert WM.tiles_of(0, 50) == (50, 50, 50, 50)
    assert WM.tiles_of(1, 50) == (50, 51, 52, 53)
    assert WM.tiles_of(4, 50) == (50, 51, 51, 50), "★鏡（左右対称）"
    assert WM.SHAPE_SLOTS == {0: 1, 1: 4, 4: 2}


# ----------------------------------------------------------------------
# ★④ 使い回しの規則
# ----------------------------------------------------------------------
@needs_rom
def test_同じ絵の番号なら同じCHR():
    got = WM.build(_ident())
    by_art: dict[int, set] = {}
    for m in got.values():
        by_art.setdefault(m.art_id, set()).add(m.tiles)
    for art, tiles in by_art.items():
        assert len(tiles) == 1, "⚠ 絵 $%02X が 2 通りの CHR になった: %s" % (art, tiles)
    assert any(len([m for m in got.values() if m.art_id == a]) > 1 for a in by_art), (
        "⚠ 使い回しの升が 1 つも無い（★検査が空回りしている）")


@needs_rom
def test_升は32個でCHRは重ならない():
    got = WM.build(_ident())
    assert sorted(got) == list(range(32))
    # ★形ごとに使う枚数ぶん、先頭から順に取っている（⚠ 重なっていないこと）
    firsts = {m.art_id: (m.tiles[0], WM.SHAPE_SLOTS[m.shape]) for m in got.values()}
    used: set[int] = set()
    for first, n in firsts.values():
        span = set(range(first, first + n))
        assert not (span & used), "⚠ CHR が重なった: %s" % sorted(span & used)
        used |= span
    assert min(used) == WM.FIRST_CHR

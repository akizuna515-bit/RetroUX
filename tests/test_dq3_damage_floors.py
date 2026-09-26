"""ダメージ床（毒の沼・バリア）の判定（RX3-0262 / 2026-09-16）。

## ★この検査が守るもの

```text
① 判定のコードそのもの（bank14 $B4B1）。⚠ ROM が変わったら赤くする
② ローカル: collision 0x05 → 2 / 0x06 → 15（★完全一致。下位ニブルではない）
③ 世界地図: タイル 7（⚠ collision ではなくタイル番号を直接見る近道）
④ ★裏取り: 世界地図の collision 表で 0x05 は index 7 ただ 1 つ
⑤ ⚠⚠ 分類（klass / to_text）は**変わっていない**こと
   ★歩ける床のままにする（経路探索を変えるのは別の件）
```

⚠ 「毒の沼」「バリア」という呼び名は ROM から出していません。
★ここで区別するのは**減る HP の量**だけです。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import damage_floors as D

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


def _ident():
    from dq3rom import profile as dq3
    return dq3.load_and_identify(ROM_PATH)


# ----------------------------------------------------------------------
# ★① ROM のコード
# ----------------------------------------------------------------------
@needs_rom
def test_判定のコードが想定どおり():
    assert D.verify(_ident()) == []


class _Patched:
    """★ROM の 1 バイトだけ差し替えた写し（⚠ ファイルは触らない）。"""

    def __init__(self, ident, offset: int, value: int) -> None:
        self._ident = ident
        prg = bytearray(ident.rom.prg)
        prg[offset] = value
        self.rom = type("Rom", (), {"prg": bytes(prg)})()

    def prg_offset(self, bank: int, addr: int) -> int:
        return self._ident.prg_offset(bank, addr)


@needs_rom
def test_コードが1バイト違えば鳴る():
    """⚠⚠ 照合器そのものを試す。★「短く比べる」実装にすると、ここが緑のままになる。"""
    ident = _ident()
    base = ident.prg_offset(D.BANK, D.ADDR)
    # ★ルーチンの**終わりのほう**（CMP #$06 の即値）を変える
    at = base + len(D._CODE) - 3
    assert ident.rom.prg[at] == 0x06, "★見本の位置がずれた（実装が変わった）"
    problems = D.verify(_Patched(ident, at, 0x07))
    assert problems and "ダメージ床の判定" in problems[0], problems


# ----------------------------------------------------------------------
# ★②③ 判定そのもの（⚠ ROM が無くても回る）
# ----------------------------------------------------------------------
def test_ローカルは完全一致で見る():
    assert D.damage_of(0x05) == 2 and D.damage_of(0x06) == 15
    assert D.damage_of(0x00) is None and D.damage_of(None) is None
    # ⚠ 下位ニブルで見ていたら、これが 2 / 15 になってしまう
    assert D.damage_of(0x15) is None and D.damage_of(0x86) is None
    assert D.is_damage(0x05) and not D.is_damage(0x03)


def test_世界地図はタイル番号で見る():
    assert D.world_damage_of(7) == 2
    assert D.world_damage_of(5) is None and D.world_damage_of(6) is None
    assert D.world_damage_of(None) is None


# ----------------------------------------------------------------------
# ★④ 裏取り（⚠ 別の道から同じ結論になること）
# ----------------------------------------------------------------------
@needs_rom
def test_世界地図の表で0x05は升7だけ():
    """★コードはタイル 7 を直接見るが、それは collision 0x05 の升そのものだった。"""
    from dq3rom import collision as col

    t0 = col.base_table(_ident(), 0)
    assert [i for i, v in enumerate(t0) if v == 0x05] == [D.WORLD_TILE]
    assert t0[D.WORLD_TILE] == 0x05
    # ⚠ 世界地図に 0x06（重いほう）は無い
    assert [i for i, v in enumerate(t0) if v == 0x06] == []


@needs_rom
def test_世界地図の沼は69升():
    """⚠ 調べる前の見立て（69 升）と一致すること。★数が変わったら読み方を疑う。"""
    from dq3rom import world_map

    w = world_map.decode(_ident(), "world_main")
    n = sum(row.count(D.WORLD_TILE) for row in w.tiles)
    assert n == 69, "⚠ 世界地図の沼の升数が変わった"


@needs_rom
def test_ダメージ床のある地図が実在する():
    """⚠ 「0 件」は通っていないだけ。★実際に升があることまで見る。"""
    from dq3rom import area_maps, collision as col

    ident = _ident()
    ov = col.read_overrides(ident)
    light = heavy = 0
    for m in area_maps.decode_all(ident):
        if not m.ok:
            continue
        t = col.table_for(ident, m.entry.tileset, m.entry.map_id, ov)
        ids = {i: D.damage_of(v) for i, v in enumerate(t) if D.damage_of(v)}
        if not ids:
            continue
        for row in m.decoded.tiles:
            for tile in row:
                d = ids.get(tile)
                if d == 2:
                    light += 1
                elif d == 15:
                    heavy += 1
    assert light > 100 and heavy > 100, (light, heavy)


# ----------------------------------------------------------------------
# ★⑤ ⚠⚠ 振る舞いを変えていないこと
# ----------------------------------------------------------------------
def test_分類はPASSのまま():
    """★ダメージ床は「歩ける床」のまま。⚠ 経路探索を変えるのは別の件。"""
    from dq3.testing import passability as P

    for col in (0x05, 0x06):
        assert P.classify(col)[0] == P.PASS, "⚠⚠ 経路の扱いが変わった"


@needs_rom
def test_地図の升からダメージを引ける():
    from dq3.testing import passability as P

    rom = P.from_rom(21)          # ★沼の升がある地図（tileset 8 / タイル 1）
    found = [(x, y) for y in range(rom.height) for x in range(rom.width)
             if rom.damage(x, y) is not None]
    assert found, "⚠ この地図にダメージ床が 1 つも無い（★見本の選び直しが要る）"
    x, y = found[0]
    assert rom.damage(x, y) == 2
    assert rom.klass(x, y) == P.PASS, "⚠⚠ 歩けない扱いになった"
    assert rom.damage(-1, -1) is None, "⚠ 地図の外は None"
    row = next(c for c in rom.to_json()["cells"] if (c["x"], c["y"]) == (x, y))
    assert row["damage"] == 2 and row["rom_class"] == P.PASS

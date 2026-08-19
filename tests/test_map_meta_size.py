"""地図の大きさが ROM と合うか（2026-08-03）。

★★★ **依頼者が実機で見つけた不具合の回帰テストです。** ★★★

⚠⚠ 2026-08-03、地図の窓に

    「ロンダルキアのほこら [$1F] 7×7 マス … ⚠ ROM の値より広い（+5×+5）」

と出ていました。★ROM のヘッダは **8×8** です。

## 何が起きていたか

```
$DFAE: LDA $21 / STA $0C / INC $0C   ; ★ROM は「幅 - 1」を持つ
```

⚠ `dq2rom maps export` が `$21` を**そのまま**「幅」として書いていたため、
**108/109 マップで地図が 1 マス狭く**なっていました。

★歩いた範囲が枠からはみ出し、「⚠ ROM の値より広い」という警告が出て、
**枠の外に余計な行が描かれて**いました（依頼者の言う「下のゴミ」）。

## ⚠ ここで見張ること

★`maps.json` の `width` / `height` は **`+1` 済み**であること。
⚠ `MapHeader.width`（`locator.py`）は**生値のまま**でよく、
  直すのは「幅」を名乗る出力側だけです。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from retroux.core.bgmap.rom_tiles import (MAP_HEADER, MAP_HEADER_SIZE,
                                          load_prg)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
MAPS_JSON = PROJECT_ROOT / "work" / "map-data" / "maps.json"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_meta = pytest.mark.skipif(not MAPS_JSON.exists(),
                                reason="maps.json が無い")

#: ★世界地図はヘッダが `$FF` で、大きさを設定から補う
OVERWORLD_ID = 0x01


def _maps() -> list:
    return json.loads(MAPS_JSON.read_bytes().decode("utf-8"))["maps"]


@needs_rom
@needs_meta
def test_maps_jsonの大きさがROMと合う():
    """★★★ **これが本体**。⚠ 1 マップでもずれたら知らせます。"""
    prg = load_prg(ROM)
    wrong = []
    for entry in _maps():
        map_id = entry["map_id"]
        if entry["width"] is None:
            continue                      # ★世界地図（`$FF`）
        off = MAP_HEADER + map_id * MAP_HEADER_SIZE
        want = (prg[off + 1] + 1, prg[off + 2] + 1)
        got = (entry["width"], entry["height"])
        if got != want:
            wrong.append(f"${map_id:02X}: {got} != {want}")
    assert not wrong, (
        f"⚠ {len(wrong)} マップの大きさが ROM と合いません: {wrong[:5]}")


@needs_rom
@needs_meta
def test_ロンダルキアのほこらは8x8():
    """★依頼者が見つけた実例（`$1F`）。⚠ 7×7 と出ていました。"""
    entry = next(e for e in _maps() if e["map_id"] == 0x1F)
    assert (entry["width"], entry["height"]) == (8, 8)


@needs_meta
def test_世界地図の大きさはnullのまま():
    """⚠ `$FF` は「ヘッダでは表せない」印。★設定から補います。

    ⚠⚠ ここを `256` と書いてしまうと、`map_size()` が設定を見なくなります。
    """
    entry = next(e for e in _maps() if e["map_id"] == OVERWORLD_ID)
    assert entry["width"] is None
    assert entry["height"] is None
    assert entry["type"] == "overworld"


@needs_rom
def test_出力側だけがプラス1する():
    """★`MapHeader.width` は**生値のまま**でよい。

    ⚠ ここを +1 すると `kind()` の `width == 0xFF` 判定が壊れます
      （★世界地図が判別できなくなる）。
    """
    from dq2rom import ines, locator

    rom = ines.load(ROM)
    headers = locator.read_map_header_table(rom, MAP_HEADER)
    prg = load_prg(ROM)
    for h in headers[:8]:
        off = MAP_HEADER + h.map_id * MAP_HEADER_SIZE
        assert h.width == prg[off + 1], "★生値のままであること"
    # ★世界地図は $FF のまま（★これで overworld と分かる）
    assert headers[OVERWORLD_ID].width == 0xFF


@needs_rom
@needs_meta
def test_ROM解読後のMapMasterと同じ大きさになる():
    """★★ 2 つの経路が同じ答えを出すこと。

    ⚠ `maps.json`（GUI が読む）と `MapMaster`（ROM 解読）で
      食い違うと、地図と現在地がずれます。
    """
    from retroux.core.bgmap import map_master

    prg = load_prg(ROM)
    for entry in _maps():
        map_id = entry["map_id"]
        if entry["width"] is None or map_id == OVERWORLD_ID:
            continue
        master = map_master.build(prg, map_id)
        assert (master.width, master.height) == (entry["width"],
                                                 entry["height"]), (
            f"⚠ map ${map_id:02X}")

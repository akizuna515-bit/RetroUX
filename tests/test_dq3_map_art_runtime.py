"""実機が書いた材料で、地図をタイルで描く（RX3-0043 / 2026-09-01）。

## ★どこを見るか

```text
Lua  → work/dq3-probe/map_art.json + .bin   ★別の検査（dq3_map_art_test.lua）
     ↓
Python から読める          ⚠⚠ ここ（tile_art.from_runtime）
     ↓
ViewModel.tile_art         ⚠⚠ ここ
     ↓
map_window が升の絵で描く  ⚠⚠ ここ
```

## ⚠ 「橋渡しが黙って落とす」を繰り返さない

★2026-08-31 に、両端は正しいのに**橋渡しがパレット組を捨てて**
色が全部 組 0 になったことがあります。⚠ 端どうしを**突き合わせ**ます。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from dq3.knowledge import tile_art
from dq3_states import FIELD, pick

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOC_KIND, LOCAL = 0x2F, 1


def _local_state():
    """★ローカル地図のセーブ（⚠ 材料はローカル専用）。"""
    from retroux.core.bgmap import savestate as ss

    for path in pick(FIELD):
        ch = ss.load(path).chunks
        if ch["RAM"][LOC_KIND] == LOCAL and "WRAM" in ch and "CHRR" in ch:
            return path, ch
    pytest.fail("⚠⚠ ローカル地図のセーブが 1 本もありません")


@pytest.fixture
def runtime(tmp_path):
    """★セーブから「Lua が書いたはずのもの」を作る。

    ⚠ Lua そのものは `research/probes/active/dq3_map_art_test.lua` が見ます。
      ★ここは**受け取る側**の検査です。
    """
    _path, ch = _local_state()
    wram, chrr, pram, ram = ch["WRAM"], ch["CHRR"], ch["PRAM"], ch["RAM"]
    w, h = ram[0x88], ram[0x89]
    off = tile_art.MAP_BUF_OFF
    body = {
        "kind": LOCAL,
        "map_id": ram[0x8B],
        "width": w,
        "height": h,
        "chr_checksum": 12345,
        "tileset": wram[tile_art.TILESET_OFF:
                        tile_art.TILESET_OFF + 256].hex(),
        "palette_group": wram[tile_art.PALETTE_OFF:
                              tile_art.PALETTE_OFF + 256].hex(),
        "pram": bytes(pram[:32]).hex(),
        "map": bytes(wram[off:off + w * h]).hex(),
    }
    (tmp_path / tile_art.RUNTIME_JSON).write_text(
        json.dumps(body), encoding="utf-8")
    (tmp_path / tile_art.RUNTIME_BIN).write_bytes(bytes(chrr))
    return tmp_path


def test_実行時の材料から絵ができる(runtime):
    got = tile_art.from_runtime(runtime)
    assert got is not None, "⚠⚠ 材料はあるのに `None` が返った"
    assert got.art.known() > 20
    block = got.art.block(0x0B)
    assert block is not None
    assert len(block) == tile_art.CELL * tile_art.CELL * 3


def test_セーブから作った絵と一致する(runtime):
    """⚠⚠ **橋渡しが値を落としていないか**（★2026-08-31 の再発防止）。

    ★同じ材料なので、**64 索引すべてが 1 バイト違わず**同じはずです。
    """
    path, _ch = _local_state()
    直 = tile_art.from_savestate(path)
    経由 = tile_art.from_runtime(runtime)
    assert 経由 is not None
    assert set(経由.art.cells) == set(直.cells), "⚠⚠ 索引の数が違う"
    for idx in sorted(直.cells):
        assert 経由.art.cells[idx] == 直.cells[idx], (
            "⚠⚠ 索引 %d の絵が違う（★橋渡しが何かを落としている）" % idx)


def test_地図そのものも受け取る(runtime):
    """★升の生の値も来ること（⚠ 突き合わせに使う）。"""
    got = tile_art.from_runtime(runtime)
    assert got is not None
    assert len(got.cells) == got.width * got.height
    assert got.at(0, 0) is not None
    assert got.at(-1, 0) is None
    assert got.at(got.width, 0) is None


def test_ROMの升と実機の升はbit4と5だけ違う(runtime):
    """⚠⚠ **ROM から起こした升は、実機の升と同じではありません**（★実測）。

    ## ★2026-09-01 の実測（依頼者のセーブ 4 本 / 2,704 升）

    ```text
    ROM から起こした値   11
    実機の $7400         11 / 27 / 43 / 59   ⚠ bit4・bit5 が乗る
    ```

    ⚠ 違いは **bit4 と bit5 だけ**（★2,704 升すべてでそう / 確定）。
    ⚠⚠ 意味は**未確認**（★bit5 は `tile_art.DARK_BIT` として索引 32 に
      なることまでは確定。bit4 は分かっていません → `RX3-0044`）。

    ★だから画面は **実機の升**で引きます（`_tile_cells`）。
      ⚠ ROM の値で引くと、この地図では **113/676 が別のタイル**になります。
    """
    from dq3.knowledge.terrain import TerrainSource

    got = tile_art.from_runtime(runtime)
    assert got is not None
    rom = TerrainSource().get(LOCAL, got.map_id)
    if rom is None:
        pytest.skip("⚠ ROM が置かれていません（★利用者が置くもの）")
    assert (rom.width, rom.height) == (got.width, got.height)
    はみ出し = [(x, y, rom.at(x, y), got.at(x, y))
              for y in range(got.height) for x in range(got.width)
              if (rom.at(x, y) ^ got.at(x, y)) & ~0x30]
    assert not はみ出し, "⚠⚠ bit4/5 以外で %d 升が違う（★%r）" % (
        len(はみ出し), はみ出し[:5])
    # ⚠⚠ **同じではない**ことも固定する（★同じなら区別は要らないはず）
    違い = sum(1 for y in range(got.height) for x in range(got.width)
             if rom.at(x, y) != got.at(x, y))
    assert 違い > 0, "⚠ ROM と実機が完全一致（★`_tile_cells` の前提が崩れた）"


def test_材料が無ければNoneを返す(tmp_path):
    """⚠⚠ **落ちません**（★画面は色ブロックのまま / 指示書 §1）。"""
    assert tile_art.from_runtime(tmp_path) is None


def test_壊れた材料でも落ちない(tmp_path):
    (tmp_path / tile_art.RUNTIME_JSON).write_text("{", encoding="utf-8")
    (tmp_path / tile_art.RUNTIME_BIN).write_bytes(b"\x00" * 8192)
    assert tile_art.from_runtime(tmp_path) is None


def test_升の数が合わなければ受け取らない(runtime):
    """⚠⚠ 数が合わないものを**それらしく**描かない。"""
    body = json.loads((runtime / tile_art.RUNTIME_JSON).read_text(
        encoding="utf-8"))
    body["width"] = body["width"] + 1
    (runtime / tile_art.RUNTIME_JSON).write_text(
        json.dumps(body), encoding="utf-8")
    assert tile_art.from_runtime(runtime) is None


def test_CHRが短ければ受け取らない(runtime):
    (runtime / tile_art.RUNTIME_BIN).write_bytes(b"\x00" * 16)
    assert tile_art.from_runtime(runtime) is None


def test_地図が変われば目印も変わる(runtime):
    a = tile_art.from_runtime(runtime)
    body = json.loads((runtime / tile_art.RUNTIME_JSON).read_text(
        encoding="utf-8"))
    body["map_id"] = body["map_id"] + 1
    (runtime / tile_art.RUNTIME_JSON).write_text(
        json.dumps(body), encoding="utf-8")
    b = tile_art.from_runtime(runtime)
    assert a is not None and b is not None
    assert a.key != b.key, "⚠ 別の地図なのに同じ目印になっている"

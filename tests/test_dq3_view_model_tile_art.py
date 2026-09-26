"""ViewModel が、実機の材料を画面へ渡す（RX3-0043 / 2026-09-01）。

## ⚠⚠ ここが「橋渡し」です

```text
Lua        work/dq3-probe/map_art.json + .bin
  ↓
tile_art.from_runtime()          ★tests/test_dq3_map_art_runtime.py
  ↓
Dq3ViewModel.tile_art            ⚠⚠ **ここ**
  ↓
map_window                       ★tests/test_dq3_map_tile_draw.py
```

⚠ 2026-08-31 に、両端は正しいのに**橋渡しが値を落として**画面が HP と MP
だけになったことがあります（★検査は全部緑でした）。
→ ⚠⚠ **橋渡しそのもの**に検査を置きます。
"""

from __future__ import annotations

import json
import os
import time

import pytest

from dq3.knowledge import tile_art


def _vm(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    vm.tile_art_dir = tmp_path
    return vm


def _materials(tmp_path, *, map_id=9, width=4, height=4, chr_byte=0x11):
    """★Lua が書いたはずのものを置く（⚠ 中身は最小限）。"""
    wram = bytearray(tile_art.TILESET_OFF + 512)
    # ★索引 3 だけ絵になる（⚠ 他は空なので `build()` が作らない）
    for i in range(tile_art.QUAD):
        wram[tile_art.TILESET_OFF + 3 * tile_art.QUAD + i] = 0x40 + i
    body = {
        "kind": 1,
        "map_id": map_id,
        "width": width,
        "height": height,
        "chr_checksum": chr_byte,
        "tileset": bytes(wram[tile_art.TILESET_OFF:
                              tile_art.TILESET_OFF + 256]).hex(),
        "palette_group": ("00" * 256),
        "pram": ("0f" + "16" * 31),
        "map": ("03" * (width * height)),
    }
    (tmp_path / tile_art.RUNTIME_JSON).write_text(
        json.dumps(body), encoding="utf-8")
    (tmp_path / tile_art.RUNTIME_BIN).write_bytes(
        bytes([chr_byte]) * 0x2000)
    return body


def test_材料が無ければNone(tmp_path):
    """⚠⚠ **FCEUX を動かしていないのが普通**（★落ちない / 指示書 §1）。"""
    vm = _vm(tmp_path)
    assert vm.tile_art is None
    assert vm.tile_art_runtime is None


def test_材料があれば絵を渡す(tmp_path):
    _materials(tmp_path)
    vm = _vm(tmp_path)
    art = vm.tile_art
    assert art is not None, "⚠⚠ 材料はあるのに画面へ渡っていない"
    assert art.block(0x03) is not None
    assert len(art.block(0x03)) == tile_art.CELL * tile_art.CELL * 3


def test_升の値も渡す(tmp_path):
    """⚠⚠ **ここが落ちやすい**（★絵だけ渡して升を落とす）。"""
    _materials(tmp_path, map_id=21, width=5, height=3)
    vm = _vm(tmp_path)
    got = vm.tile_art_runtime
    assert got is not None
    assert (got.kind, got.map_id) == (1, 21)
    assert (got.width, got.height) == (5, 3)
    assert got.at(4, 2) == 3


def test_毎回は読み直さない(tmp_path):
    """⚠ 1 秒に 2 回 8KB を展開しない（★更新時刻で見る）。"""
    _materials(tmp_path)
    vm = _vm(tmp_path)
    最初 = vm.tile_art
    assert 最初 is not None
    for _ in range(20):
        assert vm.tile_art is 最初, "⚠⚠ 同じ材料なのに作り直している"


def test_材料が変われば読み直す(tmp_path):
    _materials(tmp_path, map_id=9)
    vm = _vm(tmp_path)
    最初 = vm.tile_art_runtime
    assert 最初 is not None and 最初.map_id == 9

    # ⚠ 更新時刻を必ず動かす（★同じ大きさの書き換えは気づかれない）
    time.sleep(0.01)
    _materials(tmp_path, map_id=21)
    os.utime(tmp_path / tile_art.RUNTIME_JSON, None)

    次 = vm.tile_art_runtime
    assert 次 is not None
    assert 次.map_id == 21, "⚠⚠ 地図が変わったのに前の材料を返した"


def test_壊れた材料でも画面を止めない(tmp_path):
    (tmp_path / tile_art.RUNTIME_JSON).write_text("{", encoding="utf-8")
    (tmp_path / tile_art.RUNTIME_BIN).write_bytes(b"\x00" * 0x2000)
    vm = _vm(tmp_path)
    assert vm.tile_art is None
    assert vm.tile_art_runtime is None


def test_置き場を差し替えられる(tmp_path):
    """⚠⚠ 検査が**本物の `work/`** を読まないこと（RX3-0027 と同じ約束）。

    ★以前、置き場を受け取れない箇所があり、⚠ 依頼者が遊ぶまで緑でした。
    """
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel.__new__(Dq3ViewModel)
    既定 = vm.tile_art_dir
    assert 既定.name == "dq3-probe", "⚠ 既定の置き場が変わった: %s" % 既定
    vm.tile_art_dir = tmp_path
    assert vm.tile_art_dir == tmp_path


def test_置き場を変えたら覚え直す(tmp_path):
    別 = tmp_path / "別"
    別.mkdir()
    _materials(tmp_path, map_id=9)
    _materials(別, map_id=21)
    vm = _vm(tmp_path)
    assert vm.tile_art_runtime.map_id == 9
    vm.tile_art_dir = 別
    assert vm.tile_art_runtime.map_id == 21, "⚠ 置き場を変えても前のまま"


def test_画面の受け口と名前が合っている(tmp_path):
    """⚠⚠ **「書いてある」検査は片側しか見ない**（2026-08-30 の教訓）。

    ★`map_window` が実際に読む名前で取れることを見ます。
    """
    from dq3.ui import map_window

    _materials(tmp_path)
    vm = _vm(tmp_path)
    assert map_window._tile_art(vm) is not None, (
        "⚠⚠ 画面側の `_tile_art()` が拾えていない")
    assert map_window._tile_cells(vm, 1, 9) is not None, (
        "⚠⚠ 画面側の `_tile_cells()` が拾えていない")
    assert map_window._tile_cells(vm, 0, 9) is None, (
        "⚠ 世界地図なのに升を返した")

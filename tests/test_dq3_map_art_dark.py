"""暗転中に取った材料を受け取らない（RX3-0046 / 2026-09-02）。

## ⚠⚠ 何が起きたか

依頼者 2026-09-02:

> 最初は表示されたが、小部屋に入ったら黒くなり、以降黒いまま

★実機が残した `work/runtime/dq3-probe/map_art.json`（実測）:

```text
kind=1 map_id=9 26x26           ★地図そのものは正しい
pram = 0f0f0f … 0f（32 バイト）  ⚠⚠ **全部 黒**
```

⚠ `$0F` は NES のパレットの**黒**です。→ ★64 索引すべての絵が真っ黒になり、
**升は正しく描かれているのに何も見えません**。

## ★原因

`map_art.lua` は **地図が変わったときだけ**書きます。
⚠⚠ ところが **DQ3 は地図を切り替えるとき画面を暗転させます**。
★「地図が変わった瞬間」＝「パレットが真っ黒な瞬間」でした。

## ⚠ DQ2 は 2026-08-11 に同じ穴を踏んでいます

`retroux/emulator/fceux/bridge.lua:1302` に
「画面がいま真っ黒（暗転中）か（2026-08-11 / 依頼者「なぜ黒塗りに」）」
とあります。★判定の考え方（**全部黒のときだけ**）もそこに合わせました。

## ★ここで見るもの

```text
Lua が書かない       research/probes/active/dq3_map_art_test.lua
Python が受け取らない  ⚠⚠ このファイル（★前に書かれた壊れた JSON が残るため）
画面が色ブロックに戻る  ⚠⚠ このファイル
```
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from dq3.knowledge import tile_art

BRIGHT = bytes([
    0x0F, 0x30, 0x10, 0x1A, 0x0F, 0x27, 0x17, 0x1A,
    0x0F, 0x16, 0x26, 0x0F, 0x0F, 0x09, 0x18, 0x28,
    0x0F, 0x30, 0x10, 0x1A, 0x0F, 0x27, 0x17, 0x1A,
    0x0F, 0x16, 0x26, 0x0F, 0x0F, 0x09, 0x18, 0x28,
])


# --- ★暗転の見分け ------------------------------------------------------

def test_全部黒なら暗転():
    assert tile_art.is_dark(bytes([0x0F] * 32))


def test_黒の別名も黒():
    """★`$0F` `$1F` `$2F` `$3F` は同じ黒（⚠ 下位 4 ビットで見る）。"""
    for base in (0x0F, 0x1F, 0x2F, 0x3F, 0x0D, 0x1D, 0x2D, 0x3D):
        assert tile_art.is_dark(bytes([base] * 32)), "⚠ %02X を見逃した" % base


def test_1つでも色があれば暗転ではない():
    """⚠⚠ **暗い部屋と暗転は違います**（★DQ2 も同じ線引き）。"""
    got = bytearray([0x0F] * 32)
    got[7] = 0x30
    assert not tile_art.is_dark(bytes(got))


def test_本物らしいパレットは暗転ではない():
    assert not tile_art.is_dark(BRIGHT)


def test_空は暗転扱い():
    """⚠ 読めなかったものを「明るい」とは言わない（★安全側）。"""
    assert tile_art.is_dark(b"")


# --- ⚠⚠ 受け取らない ----------------------------------------------------

def _runtime(tmp_path, pram: bytes, *, width=4, height=3):
    body = {
        "kind": 1,
        "map_id": 9,
        "width": width,
        "height": height,
        "chr_checksum": 1,
        "tileset": bytes(range(256)).hex(),
        "palette_group": bytes(i % 4 for i in range(256)).hex(),
        "pram": pram.hex(),
        "map": bytes(i % 32 for i in range(width * height)).hex(),
    }
    (tmp_path / tile_art.RUNTIME_JSON).write_text(
        json.dumps(body), encoding="utf-8")
    (tmp_path / tile_art.RUNTIME_BIN).write_bytes(
        bytes((i * 7) % 256 for i in range(8192)))
    return tmp_path


def test_暗転中の材料は受け取らない(tmp_path):
    """⚠⚠ **これが依頼者の画面を真っ黒にしたもの**。"""
    got = tile_art.from_runtime(_runtime(tmp_path, bytes([0x0F] * 32)))
    assert got is None, "⚠⚠ 真っ黒なパレットの材料を受け取ってしまった"


def test_明るい材料は受け取る(tmp_path):
    """⚠ 歯止めが**効きすぎていない**こと（★全部弾いたら地図が出ない）。"""
    got = tile_art.from_runtime(_runtime(tmp_path, BRIGHT))
    assert got is not None
    assert (got.kind, got.map_id, got.width, got.height) == (1, 9, 4, 3)


def test_暗転中でも黒い絵を作らない(tmp_path):
    """★受け取らなければ、⚠ 真っ黒な絵はそもそも作られません。"""
    dark = tile_art.from_runtime(_runtime(tmp_path, bytes([0x0F] * 32)))
    assert dark is None
    bright = tile_art.from_runtime(_runtime(tmp_path, BRIGHT))
    先頭 = {bytes(bright.art.block(raw)[:3])
            for raw in range(64) if bright.art.block(raw) is not None}
    assert 先頭 != {b"\x00\x00\x00"}, "⚠⚠ 明るい材料なのに全部黒い"


# --- ⚠⚠ いまの地図の材料でなければタイルで描かない ----------------------

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Terrain:
    width = height = 10
    tileset = None

    def at(self, x, y):
        return 5 if (0 <= x < self.width and 0 <= y < self.height) else None


class _Source:
    available = True
    last_error = None

    def get(self, kind, map_id=None):
        return _Terrain()


def _canvas(vm):
    from dq3.ui.map_window import MapCanvas

    canvas = MapCanvas(vm, follow=True)
    canvas._terrain = _Source()
    return canvas


def _vm(art, runtime):
    from dq3.knowledge.seen_map import SeenMap, map_key

    seen = SeenMap(pathlib.Path("使わない"))
    for y in range(10):
        for x in range(10):
            seen.mark(map_key(1, 9), x, y)

    class VM:
        tile_art = art
        tile_art_runtime = runtime

        def position(self):
            return (1, 9, 3, 3)

        def known_locations(self):
            return []

    VM.seen = seen
    return VM()


def test_別の地図の材料ではタイルで描かない(_app, tmp_path):
    """⚠⚠ **前の地図の tileset で描くと、別の絵が出ます**（RX3-0046）。

    ★材料は「地図が変わったとき」に書かれます。⚠ 暗転中・戦闘中は見送るので、
      **材料が前の地図のまま**という時間が生まれます。
    """
    got = tile_art.from_runtime(_runtime(tmp_path, BRIGHT))
    assert got is not None

    class 別の地図:
        kind, map_id = 1, 999          # ⚠ いま居るのは map 9
        width = height = 4

        def at(self, x, y):
            return 0

    canvas = _canvas(_vm(got.art, 別の地図()))
    canvas._image_now()
    assert canvas._tiled() is False, "⚠⚠ 別の地図の tileset で描いてしまった"


def test_いまの地図の材料ならタイルで描く(_app, tmp_path):
    """⚠ 歯止めが効きすぎていないこと（★これが効かないと一生 色ブロック）。"""
    got = tile_art.from_runtime(_runtime(tmp_path, BRIGHT, width=10, height=10))
    assert got is not None
    canvas = _canvas(_vm(got.art, got))
    canvas._image_now()
    assert canvas._tiled() is True, "⚠ 材料があるのにタイルで描いていない"


def test_タイルをやめたら倍率も戻る(_app, tmp_path):
    """⚠⚠ **`_tiled()` を取り違えると 16 分の 1 の大きさで出ます**。

    ★絵の 1 升は、タイルなら 16px・色ブロックなら 1px です。
    """
    from dq3.ui import map_scale

    got = tile_art.from_runtime(_runtime(tmp_path, BRIGHT))

    class 別の地図:
        kind, map_id = 1, 999
        width = height = 4

        def at(self, x, y):
            return 0

    canvas = _canvas(_vm(got.art, 別の地図()))
    image, _at = canvas._image_now()
    assert canvas._scale_for(image) == map_scale.cell_px(1), (
        "⚠⚠ 色ブロックなのにタイルの倍率で出している")

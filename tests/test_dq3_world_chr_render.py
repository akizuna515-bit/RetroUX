"""世界地図を **ROM の升 + 実機の CHR** で描く経路の固定（RX3-0073 / 2026-09-09）。

```text
ROM          world_map.decode()       ★升 id（0..31 / 256x256）
CHR-RAM      map_art.bin              ★8x8 の絵（⚠ ROM ファイルには無い）
パレット      $3F00 → map_art.json     ★4 色の組
対応表        data/dq3/world-metatiles.json  ★升 id → CHR 4 枚 + パレット組
  ↓
tile_art.from_runtime()  →  RuntimeArt  →  MapCanvas（★製品の窓）
```

⚠⚠ **PoC 専用の描き手はありません。** ★証跡の PNG も製品の `Dq3MapWindow` を
そのまま撮ったものです（`scripts/dq3_map_capture.py`）。

## ★材料は「名前つき fixture」から作る

⚠ `work/runtime/dq3-probe/map_art.*` は**遊ぶと変わります**（★実機が上書きする）。
→ ★検査は `field_encounter_safe`（sha256 で固定）から材料を組み立てます。
⚠ こうしないと、⚠⚠ **遊んだ日だけ赤くなる**検査になります。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import tile_art as TA                                   # noqa: E402
from dq3.testing import fixtures as FX                                     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not FX.MANIFEST.exists(), reason="fixture がまだありません")

#: ★代表の升（⚠ 絵は CHR から起こすので、**同じ材料なら必ず同じ絵**）
#:
#:   ⚠ 意味（海・草原…）は decode した色から付けた呼び名です。
#:     ★id 0 が海であることは ROM でも裏が取れています
#:     （`world_map.py` の「行 0 と行 255 は全部海」→ ★どちらも id 0 だけ）。
SAMPLES = {
    0: ("海", "2dfef3164b7b6f8c"),
    1: ("砂漠", "71e061f45c4467c6"),
    2: ("草原", "88026dba2fd8b4d7"),
    3: ("森", "c28f3b54af054031"),
    4: ("深い森", "7099e7bfebf0082a"),
    5: ("丘", "2e9398877f74fe05"),
    6: ("山", "b96948337c4d8199"),
    8: ("城 左上", "90bcd4c147d98790"),
    9: ("城 右上", "fcc8fd62c0423bcc"),
    10: ("町", "1da883c1b33ea3ec"),
    12: ("城 左下", "5dc812cf5cfff86b"),
    13: ("城 右下", "b922422c579040e1"),
}

CASTLE = (8, 9, 12, 13)


def _material(tmp_path) -> pathlib.Path:
    """★fixture のセーブから、実機が書くのと**同じ形**の材料を組む。"""
    from retroux.core.bgmap import savestate as ss

    fx = FX.get("field_encounter_safe")                # ⚠ sha256 と場面をここで検算
    chunks = ss.load(fx.path).chunks
    for name in ("CHRR", "PRAM"):
        if name not in chunks:
            pytest.skip("セーブに %s がありません" % name)
    got = tmp_path / "art"
    got.mkdir()
    (got / TA.RUNTIME_BIN).write_bytes(bytes(chunks["CHRR"]))
    (got / TA.RUNTIME_JSON).write_text(
        json.dumps({"kind": TA.KIND_WORLD, "pram": bytes(chunks["PRAM"]).hex(),
                    "chr_checksum": 1}), encoding="utf-8")
    return got


@pytest.fixture()
def art(tmp_path):
    got = TA.from_runtime(_material(tmp_path))
    if got is None:
        pytest.skip("ROM か対応表が読めません")
    return got


def _sha(px: bytes) -> str:
    return hashlib.sha256(px).hexdigest()[:16]


# --- ★CHR の decode が変わっていないこと --------------------------------

def test_代表の升の絵が変わっていない(art):
    """⚠⚠ 材料が同じなら、★絵は 1 ピクセルも変わらないはず。

    ⚠ 赤くなったら「壊れた」ではなく、★**何かが変わった**の合図です
      （対応表 / CHR の読み方 / パレットの当て方のどれか）。
    """
    bad = []
    for idx, (name, want) in sorted(SAMPLES.items()):
        px = art.art.cells.get(idx)
        if px is None:
            bad.append("⚠⚠ id %d（%s）の絵が無い" % (idx, name))
            continue
        got = _sha(px)
        if got != want:
            bad.append("⚠ id %d（%s）: 台帳 %s / いま %s" % (idx, name, want, got))
    assert not bad, chr(10).join(bad)


def test_升の絵は16x16のRGB(art):
    for idx in SAMPLES:
        assert len(art.art.cells[idx]) == TA.CELL * TA.CELL * 3


def test_海と草原を取り違えていない(art):
    """⚠⚠ 2026-09-09 に**表の注記で取り違えていました**（★id 0 を「草原」と書いた）。

    ★ROM の裏（行 0 / 行 255 は全部海）と、⚠ decode した色の**両方**で見ます。
    """
    cells, w, _h = TA.world_cells()
    assert set(cells[0:w]) == {0}, "⚠ ROM の上端が id 0 だけではない"
    assert set(cells[255 * w:256 * w]) == {0}, "⚠ ROM の下端が id 0 だけではない"

    def blueish(px):
        r = sum(px[0::3]) / (len(px) // 3)
        b = sum(px[2::3]) / (len(px) // 3)
        return b > r + 20

    def greenish(px):
        g = sum(px[1::3]) / (len(px) // 3)
        r = sum(px[0::3]) / (len(px) // 3)
        return g > r + 20

    assert blueish(art.art.cells[0]), "⚠⚠ id 0（海）が青くない"
    assert greenish(art.art.cells[2]), "⚠⚠ id 2（草原）が緑でない"


# --- ★アリアハン城（2x2 の 4 升）----------------------------------------

def test_城の4隅は別の絵(art):
    quads = [art.art.cells[k] for k in CASTLE]
    assert len(set(quads)) == 4, "⚠⚠ 4 隅が同じ絵になっている（★1 枚を 4 回描いている）"
    used = [TA.world_metatiles()[k][0] for k in CASTLE]
    assert len(set(used)) == 4 and len({t for q in used for t in q}) == 16, \
        "⚠ 16 枚の CHR がすべて別のはず: %r" % (used,)


def test_城は2x2で並んでいる():
    """★描き手は升 id をそのまま置くだけ。⚠ 「城」という部品にまとめない。

    → ★2x2 になるのは **ROM の升の並び**がそうだから、を固定します。
    """
    cells, w, _h = TA.world_cells()
    at = {}
    for i, v in enumerate(cells):
        if v in CASTLE:
            at.setdefault(v, set()).add((i % w, i // w))
    assert at.get(8), "⚠ 城の升が 1 つも無い"
    for (x, y) in at[8]:
        assert (x + 1, y) in at[9], "⚠ (%d,%d) の右に id 9 が無い" % (x, y)
        assert (x, y + 1) in at[12], "⚠ (%d,%d) の下に id 12 が無い" % (x, y)
        assert (x + 1, y + 1) in at[13], "⚠ (%d,%d) の右下に id 13 が無い" % (x, y)
    assert len(at[8]) == len(at[9]) == len(at[12]) == len(at[13])


# --- ★製品の窓が、その絵で描いていること --------------------------------

def test_製品の窓がタイルで描く(tmp_path):
    """⚠⚠ 「絵は作れた」と「画面がそれで描いた」は別のこと。★窓まで通して見る。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.map_window import MapCanvas
    from dq3.ui.view_model import Dq3ViewModel

    QApplication.instance() or QApplication([])
    vm = Dq3ViewModel()
    vm.tile_art_dir = _material(tmp_path)              # ★材料を fixture から差す
    if vm.tile_art is None:
        pytest.skip("ROM か対応表が読めません")
    assert vm.tile_art_runtime.kind == TA.KIND_WORLD

    # ⚠⚠ **居場所も固定する。** ★`position()` は `state.json` を読むので、
    #   ⚠ 直前の実機 run が街やダンジョンで終わっていると「別の地図」になり、
    #     ★絵を持っていても色ブロックで描きます（2026-09-09 に実際に赤くなった）。
    vm.position = lambda: (TA.KIND_WORLD, 0, 172, 218)

    canvas = MapCanvas(vm)
    canvas.resize(320, 320)
    canvas.grab()                                      # ★paintEvent を通す
    assert canvas._tiled() is True, "⚠⚠ 色ブロックで描いている（★CHR が届いていない）"


def test_絵の無い升は色ブロックに落ちる(art):
    """⚠ decode できない id で**落ちない**こと（★既存の色ブロックに戻す）。

    ⚠⚠ 2026-09-16（RX3-0232）: ここは**升 31 を「まだ知らない id」として**使って
    いましたが、★ROM から 32 個ぜんぶ起こしたので知らない id が無くなりました。
    → ★表の外の id（`32`）で見ます（⚠ 升 id は 0..31）。
    """
    assert art.art.block(32) is None, "⚠ 升 id は 0..31（★表の外は絵を持たないこと）"
    assert art.art.block(31) is not None, "★升 31 は ROM から起こした（RX3-0232）"
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    assert "_fallback_colour" in src, "⚠ 絵の無い升の逃げ道が無い"


# --- ★拡大は補間しない（指示書 Phase 4）---------------------------------

def test_拡大に補間を掛けていない():
    """★ドット絵をぼかさない。⚠ Qt は既定が nearest なので、**入れないこと**を固定する。"""
    src = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    for bad in ("SmoothPixmapTransform", "SmoothTransformation", "Antialiasing"):
        assert bad not in src, "⚠⚠ 補間を入れている: %s" % bad


def test_拡大しても色が増えない(art):
    """★nearest なら、⚠ 拡大しても**新しい色は 1 つも生まれない**。"""
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRect

    QApplication.instance() or QApplication([])
    px = art.art.cells[6]                              # ★山（4 色）
    small = QImage(px, TA.CELL, TA.CELL, TA.CELL * 3, QImage.Format.Format_RGB888)
    big = QImage(TA.CELL * 5, TA.CELL * 5, QImage.Format.Format_RGB888)
    painter = QPainter(big)
    painter.drawImage(QRect(0, 0, big.width(), big.height()), small)   # ★製品と同じ呼び方
    painter.end()

    def colours(img):
        return {img.pixel(x, y) for y in range(img.height()) for x in range(img.width())}

    assert colours(big) <= colours(small), "⚠⚠ 拡大で色が増えた（★補間が掛かっている）"


# --- ★二重実装していないこと --------------------------------------------

def test_世界地図の描き手は1本():
    """⚠ 学習の道具と製品が、★**同じ対応表**を読んでいること。"""
    learner = (ROOT / "scripts" / "dq3_world_metatiles.py").read_text(encoding="utf-8")
    assert "world-metatiles.json" in learner or "WORLD_METATILES" in learner
    assert "data" in learner and "dq3" in learner
    # ⚠⚠ 固定 PNG を描画の正にしていない
    ui = (ROOT / "dq3" / "ui" / "map_window.py").read_text(encoding="utf-8")
    art_src = (ROOT / "dq3" / "knowledge" / "tile_art.py").read_text(encoding="utf-8")
    for text in (ui, art_src):
        assert ".png" not in text, "⚠⚠ 描画が PNG を読んでいる（★正は ROM と実機の材料）"


def test_証跡の撮り方がrepoにある():
    """⚠ 一時ファイルで撮った絵は、★**もう一度出せません**（2026-09-09 の反省）。"""
    src = (ROOT / "scripts" / "dq3_map_capture.py").read_text(encoding="utf-8")
    assert "Dq3MapWindow" in src, "⚠⚠ 製品の窓ではないものを撮っている"
    assert "canvas._tiled()" in src, "⚠ タイルで描けたかを見ていない"

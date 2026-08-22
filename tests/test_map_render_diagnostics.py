"""地図が「青いだけ」になったとき、理由が残ること（RX-0048）。

## ⚠⚠ なぜ要るか

2026-08-14 に「塔の地図がちゃんと出ない」と報告を受けた。
★部品を1つずつ手で動かして調べたところ、**全部動いていた**:

    VisitedTile の記録   … ★動く（379 件）
    ROM の地形復号       … ★動く（壁 0x1C / 床 0x00）
    resolve_map_master   … ★成功
    メタタイルの絵       … ★304/304 作れる
    canvas で描く        … ★正しく描けた

⚠⚠ **それでも実行時に何が起きたかは分からなかった。**
ログにも画面にも手がかりが1つも無かった。

## ★ 青くなる道は4つある

  1. `renderer_name() != CHARACTER`
  2. メタタイルが1件も渡っていない
  3. 絵が半分に満たない
  4. `_metatile_zoom()` が None（★1マス 8px に満たない）

⚠ どれを通っても**同じ見た目**（青い跡）になる。
★だから「どれを通ったか」を残す。
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 が無い環境")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    got = QApplication.instance() or QApplication([])
    return got


class Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def caught():
    log = logging.getLogger("retroux.map")
    # ★`get_logger("map")` が返す名前に合わせる
    from retroux.core.logging_setup import get_logger

    log = get_logger("map")
    log.setLevel(logging.DEBUG)
    handler = Recorder()
    log.addHandler(handler)
    yield handler
    log.removeHandler(handler)


def _view(app, cols=44, rows=44, width=480, height=510):
    from retroux.ui.map.canvas import TrailView

    v = TrailView()
    v.resize(width, height)
    v.set_data([(x, y, 1, None) for x in range(3) for y in range(3)],
               cols, rows, (0, 0))
    return v


# --- ★ 4つの道それぞれで理由が残る ---------------------------------------

def test_メタタイルが空なら理由が残る(app, caught):
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    v = _view(app)
    v.set_metatiles([])
    pm = QPixmap(100, 100)
    painter = QPainter(pm)
    got = v._draw_metatiles(painter, QRect(0, 0, 100, 100), 8)
    painter.end()
    assert got is False
    assert any("1件も渡っていない" in l for l in caught.lines), caught.lines


def test_描き方が違えば理由が残る(app, caught):
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    v = _view(app)
    v.set_renderer("legacy_pixel")
    v.set_metatiles([(0, 0, "x", 1, "c")])
    pm = QPixmap(100, 100)
    painter = QPainter(pm)
    got = v._draw_metatiles(painter, QRect(0, 0, 100, 100), 8)
    painter.end()
    assert got is False
    assert any("描き方が" in l for l in caught.lines), caught.lines


def test_倍率が足りなければ理由が残る(app, caught):
    """⚠ 大きいマップ（世界地図は 256×256）で起きる道。

    ★1マス 8px にも足りないと `fit_zoom` が None を返し、
      **現行表示（青い跡）へ落ちる**。
    """
    v = _view(app, cols=200, rows=200, width=300, height=300)
    v.set_metatiles([(0, 0, "x", 1, "c")])
    # ★絵の有無は別の道。ここでは**倍率だけ**を見たいので通す。
    v._metatile_renderer().can_draw = lambda cells: True
    got = v._metatile_zoom(200, 200)
    assert got is None
    assert any("8px に満たない" in l for l in caught.lines), caught.lines
    # ★枠とマップの大きさが分かること（⚠ これが無いと次も調べ直しになる）
    line = next(l for l in caught.lines if "8px に満たない" in l)
    assert "200x200" in line and "300x300" in line, line


# --- ⚠⚠ ★ここが要: 判断している場所で残すこと --------------------------

def test_理由は_metatile_zoom_の側で出る(app, caught):
    """★★★ ⚠⚠ **短絡で `_draw_metatiles` は呼ばれない** ★★★

    `paintEvent` はこう書いてある:

        if metatile_zoom is not None and self._draw_metatiles(...):

    ⚠ `_metatile_zoom()` が None を返した時点で **`and` が短絡**し、
      `_draw_metatiles()` は**呼ばれない**。

    ★最初、理由を `_draw_metatiles()` の側だけに置いた。
      検査は緑になったが、⚠ **実機では1行も出ない**書き方だった
      （★呼び出し側を読まずに「分岐がある場所」へ置いたため）。

    → ★**判断している `_metatile_zoom()` を直接呼んで**確かめる。
    """
    v = _view(app)
    v.set_metatiles([])
    assert v._metatile_zoom(44, 44) is None
    assert any("1件も渡っていない" in l for l in caught.lines), caught.lines


def test_paintEventが短絡することを固定する():
    """⚠ 上の検査が効き続ける前提。★短絡が消えたら気づけるように。"""
    src = (PROJECT_ROOT / "retroux" / "ui" / "map"
           / "canvas.py").read_text(encoding="utf-8")
    assert "metatile_zoom is not None and self._draw_metatiles(" in src, (
        "★paintEvent の形が変わった。"
        "理由をどちらで残すべきか見直すこと（RX-0048）")


def test_理由は変わったときだけ出す(app, caught):
    """⚠ 描画は毎回走る。★毎回出すとログが埋まる。"""
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtCore import QRect

    v = _view(app)
    v.set_metatiles([])
    for _ in range(5):
        pm = QPixmap(100, 100)
        painter = QPainter(pm)
        v._draw_metatiles(painter, QRect(0, 0, 100, 100), 8)
        painter.end()
    hits = [l for l in caught.lines if "1件も渡っていない" in l]
    assert len(hits) == 1, f"{len(hits)} 回出ている: {hits}"


# --- ⚠⚠ ★画面にも出すこと（ログだけでは遊ぶ人に届かない）----------------

def test_絵を渡したのに使えなければ画面に出る(app):
    """★★★ ⚠⚠ **ここが依頼者に見えていなかった** ★★★

    灯台 1F は 44×44 で**ダンジョン最大**。地図の枠が縦 352px を切ると
    1マス 8px に足りず、⚠ **黙って青い跡へ落ちていた**。

    ★実測（実データ / 880 幅）:

        窓 880x480  → 枠 856x376  → 倍率 8    ★絵で描ける
        窓 880x440  → 枠 856x336  → 倍率 None ⚠⚠ 青い跡へ落ちる

    ⚠ 画面には何も出ず、ログにも手がかりが無かった。
    """
    from retroux.ui.map.canvas import TrailView

    v = TrailView()
    v.resize(300, 300)
    v.set_data([(0, 0, 1, None)], 200, 200, (0, 0))
    v.set_metatiles([(0, 0, "x", 1, "c")])
    v._metatile_renderer().can_draw = lambda cells: True
    assert v._metatile_zoom(200, 200) is None
    assert "8px に満たない" in (v.metatile_giveup() or ""), v.metatile_giveup()

    # ★描けたときは**残さない**（⚠ 出しっぱなしだと嘘になる）
    v.resize(2000, 2000)
    assert v._metatile_zoom(200, 200) is not None
    assert v.metatile_giveup() is None


def test_観測だけの地図では鳴らさない(app, tmp_path):
    """⚠ ROM の絵がそもそも無い地図で毎回出すと、ただの雑音になる。

    ★★ **文字列検査にしない**（F-089 と同じ形になる）★★
      ⚠ 「`detail.metatiles` と書いてあるか」では、書き方を変えた瞬間に
        意味を失う。★**窓を小さくして実際に開く**。
    """
    import yaml

    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.map.window import MapWindow
    from retroux.ui.view_model import ViewModel

    mm = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "memory_map.yaml").read_text(encoding="utf-8"))
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    # ★ROM を渡さない＝`live_metatiles` が無い＝絵は1件も来ない
    vm = ViewModel(
        Recorder(db, "HASH", tmp_path / "events.jsonl",
                 tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in (mm.get("monsters") or {}).items()},
        monster_stats={int(k): v for k, v in (mm.get("monster_stats") or {}).items()},
        map_meta={0x59: {"map_id": 0x59, "type": "dungeon_b",
                         "width": 60, "height": 60, "border_tile": 0x24,
                         "palette": 0x5B, "data_pointer": "0xA48B"}},
        view_radius=0)
    # ★大きい地図（60×60）を、⚠ 小さい枠で開く＝倍率は必ず足りない
    for x in range(4):
        db.mark_visited("HASH", 0x59, 0xA48B, x, 0)

    win = MapWindow(vm)
    win.resize(420, 320)
    win.show()
    app.processEvents()
    win._draw()
    app.processEvents()
    try:
        assert win._view.bounds() == (60, 60), win._view.bounds()
        # ⚠ 倍率は足りていない（★前提が崩れたら気づけるように確かめる）
        assert win._view._metatile_zoom(60, 60) is None
        # ★それでも**鳴らさない**（絵がそもそも無いので）
        assert not win._render_note.isVisible(), win._render_note.text()
    finally:
        win.close()
        db.close()


# --- ⚠ note を落とさないこと ---------------------------------------------

def test_ROM経路でnoteを落とさない():
    """⚠⚠ ★ここが落ちていた。

    `presenter.detail()` の ROM 経路は `note=` を渡しておらず、
    「⚠ 絵を作れなかったマス N」が**利用者にも記録にも届いていなかった**。
    ★絵が欠けていても「そういう地図」に見えてしまう。
    """
    src = (PROJECT_ROOT / "retroux" / "ui" / "map"
           / "presenter.py").read_text(encoding="utf-8")
    # ★ROM 経路の `MapDetail(...)` を切り出す
    head = src.split('source="rom"')[0]
    block = head[head.rindex("return MapDetail("):]
    assert "note=" in block, (
        "ROM 経路が note を渡していない（★欠けが黙って消える）")


def test_ROM経路の結果をDEBUGで残す():
    """★次に同じ報告を受けたとき、ログだけで切り分けられるように。"""
    src = (PROJECT_ROOT / "retroux" / "ui" / "map"
           / "presenter.py").read_text(encoding="utf-8")
    assert 'get_logger("map")' in src
    assert "枠外" in src, "枠外のマス数が残っていない"

# --- ★ 狭い窓ではスクロールで見せる（2026-08-15 / RX-0049）---------------

def _big_map_window(app, tmp_path, cols=44, rows=44):
    """★大きい地図（44x44）を持つ窓を作る。⚠ 絵は後から差し込む。"""
    import yaml

    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.map.window import MapWindow
    from retroux.ui.view_model import ViewModel

    mm = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "memory_map.yaml").read_text(encoding="utf-8"))
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    vm = ViewModel(
        Recorder(db, "HASH", tmp_path / "events.jsonl",
                 tmp_path / "command.json"), db, "HASH",
        monsters={int(k): str(v) for k, v in (mm.get("monsters") or {}).items()},
        monster_stats={int(k): v for k, v in (mm.get("monster_stats") or {}).items()},
        map_meta={0x59: {"map_id": 0x59, "type": "dungeon_b",
                         "width": cols, "height": rows, "border_tile": 0x24,
                         "palette": 0x5B, "data_pointer": "0xA48B"}},
        view_radius=0)
    for x in range(3):
        db.mark_visited("HASH", 0x59, 0xA48B, x, 0)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    return win, db


def _feed_art(view, cols, rows):
    """★絵が渡っている状態にする（⚠ 実ファイルは使わない）。"""
    view.set_metatiles([(x, y, "k", 1, "confirmed")
                        for x in range(cols) for y in range(rows)])
    view._metatile_renderer().can_draw = lambda cells: True


def test_枠に収まるなら従来どおり(app, tmp_path):
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(900, 900)
        app.processEvents()
        _feed_art(win._view, 44, 44)
        zoom = win._apply_map_view(44, 44)
        assert zoom == 8, zoom
        assert win._map_scroll.widgetResizable() is True, "★スクロール枠になっている"
    finally:
        win.close()
        db.close()


def test_枠に収まらなければスクロール枠にする(app, tmp_path):
    """★★★ 依頼者の判断（2026-08-15 / RX-0049 の案 b）★★★

    > 49でスクロール枠。

    ⚠ これまでは 1マス 8px に足りないと**黙って青い跡へ落ちて**いた。
    ★これからは 8px で描いて、はみ出したぶんはスクロールで見せる。
    """
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(420, 340)         # ⚠ 44x8 = 352px に足りない
        app.processEvents()
        _feed_art(win._view, 44, 44)
        # ★前提: 枠に収める道では描けない
        assert win._view._metatile_zoom(44, 44) is None
        zoom = win._apply_map_view(44, 44)
        assert zoom == 8, zoom
        assert win._map_scroll.widgetResizable() is False, "★スクロール枠でない"
        assert win._view.size().toTuple() == (44 * 8, 44 * 8), (
            win._view.size().toTuple())
    finally:
        win.close()
        db.close()


def test_スクロールに切り替えたら注意を消す(app, tmp_path):
    """⚠⚠ **描けているのに「出せていません」は嘘**。

    ★`_metatile_zoom()` は「1マスが 8px に満たない」を抱えたままなので、
      枠を広げたら**測り直す**こと（⚠ でないと黄色い注意が残る）。
    """
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(420, 340)
        app.processEvents()
        _feed_art(win._view, 44, 44)
        win._view._metatile_zoom(44, 44)          # ⚠ ここで理由が入る
        assert win._view.metatile_giveup() is not None
        win._apply_map_view(44, 44)
        assert win._view.metatile_giveup() is None, (
            f"★スクロールで描けているのに理由が残っている: "
            f"{win._view.metatile_giveup()}")
    finally:
        win.close()
        db.close()


def test_絵が無ければスクロールにしない(app, tmp_path):
    """⚠ 観測だけの地図を勝手に大きくしない（★従来どおり枠に収める）。"""
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(420, 340)
        app.processEvents()
        win._view.set_metatiles([])               # ★絵は1件も無い
        assert win._view.metatile_min_zoom() is None
        win._apply_map_view(44, 44)
        assert win._map_scroll.widgetResizable() is True, (
            "★絵が無いのにスクロール枠にしている")
    finally:
        win.close()
        db.close()

# --- ★★★ ⚠⚠ 点滅しないこと（2026-08-18 / RX-0049）★★★ ---------------

def test_描き直しても見せ方が入れ替わらない(app, tmp_path):
    """★★★ ⚠⚠ **依頼者の画面で青と地形が点滅した** ★★★

    実測（`_draw` を10回 / 窓 347x497）:

        1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
        2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
        3: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
        ...

    ⚠ 原因は、先に `setWidgetResizable(True)` で widget を枠へ伸ばし、
      **その widget の大きさ**を見て「入るか」を決めていたこと。
      ★決めるたびに前提が変わる（自分で自分の入力を変えていた）。

    → ★`maximumViewportSize()`（スクロールバーが無いときの内側）で決める。

    ⚠ `_draw` は**位置が動くたび**に呼ばれるので、1回で正しくても足りない。
    """
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(347, 497)
        app.processEvents()
        _feed_art(win._view, 44, 44)
        modes = []
        for _ in range(8):
            win._apply_map_view(44, 44)
            app.processEvents()
            modes.append(win._map_scroll.widgetResizable())
        assert len(set(modes)) == 1, (
            f"⚠⚠ 見せ方が入れ替わっている（★点滅）: {modes}")
    finally:
        win.close()
        db.close()


def test_見せ方は枠の大きさで決める(app, tmp_path):
    """⚠ widget の大きさで決めると、上の点滅に戻る。

    ★`maximumViewportSize()` はスクロールバーの出入りで変わらない。
      ⚠ `viewport().size()` はバーが出ると縮むので、決め手にできない。
    """
    win, db = _big_map_window(app, tmp_path)
    try:
        win.resize(347, 497)
        app.processEvents()
        _feed_art(win._view, 44, 44)
        win._apply_map_view(44, 44)
        app.processEvents()
        room = win._map_scroll.maximumViewportSize()
        # ★スクロール枠に入っている＝枠に 44x8=352 が収まらない
        assert not win._map_scroll.widgetResizable()
        assert min(room.width() // 44, room.height() // 44) < 8, room
        # ⚠ もう一度呼んでも、枠の大きさは変わらない（★これが安定の根拠）
        again = win._map_scroll.maximumViewportSize()
        assert (again.width(), again.height()) == (room.width(), room.height())
    finally:
        win.close()
        db.close()

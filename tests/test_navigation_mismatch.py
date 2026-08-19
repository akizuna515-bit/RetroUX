"""ROM 解析と実プレイの食い違い（Phase 6 / 指示書 §17）。

## ★ 何のためか

`map_passability.json` は**相関にもとづく見立て**です
（★属性の上位ニブルが 0xF なら通れない。⚠ 判定箇所は未特定）。
ここで実プレイと突き合わせて、見立てが正しいかを確かめます。

## ⚠⚠ ここで守っていること

  1. **成功した歩行は記録しない**（§17）。★食い違いだけ
  2. **表が無ければ何も言わない**（★「分からない」と「食い違い」を混ぜない）
  3. **同じ食い違いは1回だけ**（⚠ でないと、やめた 2,117 行が形を変えて戻る）
  4. 2種類の食い違いで**重みを分ける**:

       walked_but_blocked  … ★表が誤り。言い訳が効かない → WARNING
       blocked_but_walkable … ⚠ NPC・演出の可能性が高い   → DEBUG
"""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from retroux.core.bridge.state_reader import GameState  # noqa: E402
from retroux.core.db.database import Database  # noqa: E402
from retroux.core.navigation import (NavigationObserver,  # noqa: E402
                                     NavigationRepository)
from retroux.core.navigation.mismatch import PassabilityTable  # noqa: E402
from retroux.core.navigation.repository import Thresholds  # noqa: E402

HASH = "T" * 64
MAP_ID, MAP_PTR = 0x07, 0x8E83
TIMEOUT = 30


def _table(cells):
    """`map_passability.json` と同じ形の表を作る。"""
    return PassabilityTable({"maps": [{"map_id": MAP_ID, "cells": cells}]})


def _cell(x, y, foot, terrain_id=0, terrain_class=0):
    return {"x": x, "y": y, "terrain_id": terrain_id,
            "terrain_class": terrain_class,
            "terrain_type": "walk" if foot else "blocked",
            "passability": {"foot": foot, "ship": None}}


class Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int | None = None) -> list[str]:
        return [r.getMessage() for r in self.records
                if level is None or r.levelno == level]


def _make(tmp_path, table=None):
    db = Database(tmp_path / "n.sqlite3")
    db.register_rom(HASH, "テストROM", "JP", mapper=2)
    repo = NavigationRepository(db, HASH, Thresholds(blocked_probable=3))
    log = logging.getLogger("test.mismatch")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    handler = Recorder()
    log.handlers = [handler]
    seen: list = []
    obs = NavigationObserver(repo, move_timeout_frames=TIMEOUT,
                             passability=table, on_mismatch=seen.append,
                             logger=log)
    return obs, handler, seen, db


def _state(x, y, *, frame=0, direction=None):
    return GameState(fresh=True, in_battle=False, frame=frame,
                     map_id=MAP_ID, map_x=x, map_y=y,
                     map_data_pointer=MAP_PTR, input_direction=direction)


# --- 1. ★成功した歩行は記録しない -----------------------------------------

def test_表どおりに歩けたときは何も出さない(tmp_path):
    table = _table([_cell(3, 3, True), _cell(3, 4, True)])
    obs, handler, seen, db = _make(tmp_path, table)
    obs.observe(_state(3, 3))
    obs.observe(_state(3, 4))
    assert seen == [], "普通に歩いただけで鳴っている"
    assert handler.messages() == []
    db.close()


# --- 2. ⚠ 表が無ければ何も言わない ----------------------------------------

def test_表が無ければ鳴らない(tmp_path):
    """★「分からない」と「食い違い」を混ぜない。"""
    obs, handler, seen, db = _make(tmp_path, None)
    obs.observe(_state(3, 3))
    obs.observe(_state(3, 4))
    assert seen == []
    assert obs.stats["mismatches"] == 0
    db.close()


def test_表に無い座標では鳴らない(tmp_path):
    """⚠ 世界地図など、まだ覆えていない所で騒がない。"""
    table = _table([_cell(0, 0, True)])
    obs, handler, seen, db = _make(tmp_path, table)
    obs.observe(_state(9, 9))
    obs.observe(_state(9, 10))
    assert seen == []
    db.close()


# --- 3. ★★ 食い違いを見つける（要）---------------------------------------

def test_通れないはずのマスを歩けたら鳴る(tmp_path):
    """★★ **これが出たら見立てが誤り**。言い訳が効かない。"""
    table = _table([_cell(3, 3, True), _cell(3, 4, False, terrain_id=5,
                                             terrain_class=0xF0)])
    obs, handler, seen, db = _make(tmp_path, table)
    obs.observe(_state(3, 3))
    obs.observe(_state(3, 4))
    assert len(seen) == 1, seen
    got = seen[0]
    assert got.kind == "walked_but_blocked"
    assert (got.map_id, got.x, got.y) == (MAP_ID, 3, 4)
    assert got.terrain_id == 5 and got.terrain_class == 0xF0
    assert got.direction == "down"
    # ★重み: 言い訳が効かないので WARNING
    assert handler.messages(logging.WARNING), handler.messages()
    db.close()


def test_通れるはずなのに進めなければDEBUG(tmp_path):
    """⚠ NPC・演出の可能性が高い（実測 235 件）。★段階を下げる。"""
    table = _table([_cell(3, 3, True), _cell(3, 4, True)])
    obs, handler, seen, db = _make(tmp_path, table)
    obs.observe(_state(3, 3, frame=0, direction="down"))
    obs.observe(_state(3, 3, frame=TIMEOUT + 1, direction="down"))
    assert len(seen) == 1, seen
    assert seen[0].kind == "blocked_but_walkable"
    assert seen[0].y == 4, "進めなかった向きの**先**を見ていない"
    assert handler.messages(logging.WARNING) == [], "NPC の疑いで WARNING を出している"
    assert handler.messages(logging.DEBUG), handler.messages()
    db.close()


# --- 4. ⚠ 同じ食い違いを繰り返さない --------------------------------------

def test_同じ食い違いは一度だけ(tmp_path):
    """⚠ でないと、やめた 2,117 行が形を変えて戻ってくる。"""
    table = _table([_cell(3, 3, True), _cell(3, 4, False)])
    obs, handler, seen, db = _make(tmp_path, table)
    for _ in range(5):
        obs.observe(_state(3, 3))
        obs.observe(_state(3, 4))
    assert len(seen) == 1, f"{len(seen)} 回鳴っている"
    assert obs.stats["mismatches"] == 1
    db.close()


def test_違うマスの食い違いは別々に出す(tmp_path):
    """⚠ 抑止しすぎて別の食い違いを隠さない。"""
    table = _table([_cell(3, 3, True), _cell(3, 4, False),
                    _cell(4, 4, False)])
    obs, handler, seen, db = _make(tmp_path, table)
    obs.observe(_state(3, 3))
    obs.observe(_state(3, 4))
    obs.observe(_state(4, 4))
    assert len(seen) == 2, [s.kind + str((s.x, s.y)) for s in seen]
    db.close()


# --- イベントの形 ---------------------------------------------------------

def test_そのままイベントにできる(tmp_path):
    table = _table([_cell(3, 3, True), _cell(3, 4, False, terrain_id=7)])
    obs, _, seen, db = _make(tmp_path, table)
    obs.observe(_state(3, 3))
    obs.observe(_state(3, 4))
    e = seen[0].to_event()
    assert e["type"] == "navigation_mismatch"
    for key in ("map_id", "x", "y", "direction", "kind",
                "expected", "observed", "terrain_id", "terrain_class"):
        assert key in e, key
    db.close()


# --- ⚠ 本体を止めない -----------------------------------------------------

def test_表が壊れていても本体は止まらない(tmp_path):
    """⚠ 表示・記録のための処理でゲームを止めない。"""
    broken = PassabilityTable({"maps": [{"map_id": MAP_ID,
                                         "cells": [{"x": 3, "y": 4}]}]})
    obs, _, seen, db = _make(tmp_path, broken)
    obs.observe(_state(3, 3))
    got = obs.observe(_state(3, 4))
    assert got is not None
    db.close()


def test_読めないファイルなら空の表になる(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ これは JSON ではない", encoding="utf-8")
    table = PassabilityTable.load(p)
    assert not table
    assert table.foot(1, 2, 3) is None


def test_ファイルが無くても落ちない(tmp_path):
    table = PassabilityTable.load(tmp_path / "ない.json")
    assert not table

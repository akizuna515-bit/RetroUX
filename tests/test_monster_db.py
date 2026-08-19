"""モンスター図鑑の集計（MVP2 Phase 4 の土台）。

★守りたい契約:
  1. **勝敗が分からない戦闘を分母に入れない**
     実データで 1563戦中 685件が勝敗不明で、分母に入れると
     「スライムの勝率 8.7%」という嘘の数字が出た
  2. 遭遇回数は**全部**数える（出会ったことは記録の質と関係なく事実）
  3. 1戦闘に同じ敵が複数いても遭遇は1回
  4. 0 と「まだ分からない」を混ぜない
"""

from __future__ import annotations

import pytest

from retroux.core.db.database import Database
from retroux.core.db.monsters import build

NAMES = {1: "スライム", 2: "おおナメクジ", 3: "アイアンアント"}
STATS = {1: {"max_hp": 6, "attack": 8, "defense": 5, "agility": 3,
             "exp": 1, "gold": 2}}


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.sqlite3")
    d.register_rom("HASH", "テストROM", "JP", mapper=2)
    yield d
    d.close()


def _battle(db, ids, result, ms=1000):
    db.insert_battle(rom_hash="HASH", started_at="2026-07-26T00:00:00+00:00",
                     ended_at="2026-07-26T00:00:01+00:00", duration_ms=ms,
                     duration_frames=60, monster_ids=ids,
                     is_first_encounter=False, is_boss=False, result=result,
                     exp_gained=None, gold_gained=None, speed_applied=4.0,
                     auto_input_used=True)


def test_unknown_results_are_not_counted_as_losses(db):
    """★本題: 勝敗不明を「負け」として数えない。"""
    _battle(db, [1], "win")
    _battle(db, [1], None)      # 記録が完結しなかった戦闘
    _battle(db, [1], None)

    row = {r.id: r for r in build(db, "HASH", NAMES, STATS)}[1]

    assert row.encounters == 3          # 出会ったのは3回
    assert row.decided == 1             # 勝敗が分かるのは1回
    assert row.unknown_results == 2
    assert row.win_rate == 1.0          # 1/1。1/3 にしない


def test_losses_count(db):
    _battle(db, [1], "win")
    _battle(db, [1], "lose")
    row = {r.id: r for r in build(db, "HASH", NAMES, STATS)}[1]
    assert row.win_rate == 0.5


def test_same_monster_twice_is_one_encounter(db):
    """★体数で数えない。6体グループの敵ばかり遭遇が伸びると指標にならない。"""
    _battle(db, [1, 1, 1], "win")
    row = {r.id: r for r in build(db, "HASH", NAMES, STATS)}[1]
    assert row.encounters == 1


def test_never_met_is_none_not_zero(db):
    """会っていない敵の勝率は None。0% にすると勝てない敵に見える。"""
    rows = {r.id: r for r in build(db, "HASH", NAMES, STATS)}
    assert rows[2].known is False
    assert rows[2].win_rate is None
    assert rows[2].average_seconds is None


def test_rom_stats_are_attached(db):
    """ROM 由来の静的データが載る（記録が無くても出る）。"""
    rows = {r.id: r for r in build(db, "HASH", NAMES, STATS)}
    assert rows[1].max_hp == 6 and rows[1].attack == 8 and rows[1].exp == 1
    # 表に無い敵は None のまま（0 で埋めない）
    assert rows[2].max_hp is None


def test_unknown_monster_id_is_kept(db):
    """名前の表に無いIDで戦っていても落とさない（記録は事実）。"""
    _battle(db, [99], "win")
    rows = {r.id: r for r in build(db, "HASH", NAMES, STATS)}
    assert 99 in rows and rows[99].encounters == 1
    assert "未知" in rows[99].name

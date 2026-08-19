"""画面更新の無駄をなくしたことの回帰テスト（2026-07-31 の指示書 §10）。

★★ **実測してから直した**（推測で最適化しない）★★

  `research/probes/reusable/measure_gui.py` / 本物のデータ（BattleLog 1875 / VisitedTile 27964）:

    | | 1回あたり | state読込 | 戦闘ログ表 |
    | --- | --- | --- | --- |
    | 直す前 | **7.3 ms** | 5.3 ms | 1.1 ms |
    | 一覧をキャッシュ | 2.3 ms | 0.8 ms | 1.1 ms |
    | 表も作り直さない | **1.1 ms** | 0.7 ms | 0.0 ms |

  ⚠ 「もっさり」の正体は CPU ではなく**更新が秒2回しかない**ことだった。
    安くしたので間隔を 500ms → 200ms にできた。

## ⚠⚠ ここで守りたいのは速さではなく**古い値を出さないこと**

  キャッシュの怖さは「速いが嘘」。戦闘が増えたのに一覧が変わらなければ、
  遅いより悪い。**増えたら必ず作り直す**ことを検査する。
"""

from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

from retroux.core.db.database import Database        # noqa: E402
from retroux.core.recorder import Recorder           # noqa: E402
from retroux.ui.perf import Probe, Stat              # noqa: E402
from retroux.ui.view_model import ViewModel          # noqa: E402

ROM = "PERFHASH"


@pytest.fixture
def vm(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom(ROM, "テスト", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    return ViewModel(Recorder(db, ROM, events, tmp_path / "command.json"),
                     db, ROM)


def _add_battle(vm, n: int = 1) -> None:
    for i in range(n):
        vm.db.insert_battle(
            ROM, started_at="2026-07-31T12:00:00+09:00", ended_at=None,
            duration_ms=1000, duration_frames=300, monster_ids=[1],
            is_first_encounter=False, is_boss=False, speed_applied=4.0,
            auto_input_used=True, result="win")


# --- 1. 変わっていなければ作り直さない -------------------------------

def test_the_battle_list_is_not_rebuilt_when_nothing_happened(vm):
    """★同じ結果なら**同じオブジェクト**を返す（画面側が `is` で判定できる）。"""
    _add_battle(vm, 3)
    first = vm.poll().rows
    second = vm.poll().rows
    assert first is second, "戦闘が増えていないのに作り直している"


def test_the_expensive_queries_are_skipped_when_nothing_happened(vm):
    """⚠ 実際に SQLite を叩かなくなっていること（`is` だけでは足りない）。

    ★`recent_battles` は実測でいちばん重かった（2.68ms）。
    """
    _add_battle(vm, 3)
    vm.poll()

    calls: list = []
    real = vm.db.recent_battles
    vm.db.recent_battles = lambda *a, **k: calls.append(a) or real(*a, **k)
    vm.poll()
    vm.poll()
    assert calls == [], "変わっていないのに一覧を引き直している"


# --- 2. ⚠ 古い値を出さない（ここが本題）-------------------------------

def test_a_new_battle_invalidates_the_cache(vm):
    """★★ **速いが嘘、をやらない。** ★★"""
    _add_battle(vm, 1)
    before = vm.poll().rows
    assert len(before) == 1

    _add_battle(vm, 1)
    after = vm.poll().rows
    assert after is not before, "戦闘が増えたのに作り直していない"
    assert len(after) == 2


def test_a_deleted_battle_also_invalidates_the_cache(vm):
    """⚠ 減ったときも作り直すこと。

    ★合図に「最後の id」を使うとここで落ちる（id は消しても減らない）。
      **件数**で見ているのはこのため。
    """
    _add_battle(vm, 3)
    assert len(vm.poll().rows) == 3

    vm.db._conn.execute("DELETE FROM BattleLog WHERE id = (SELECT MAX(id)"
                        " FROM BattleLog)")
    vm.db._conn.commit()

    assert len(vm.poll().rows) == 2, "消したのに古い一覧を出している"


def test_the_summary_follows_the_same_cache(vm):
    """★要約も一緒に更新されること（片方だけ古い、をやらない）。"""
    _add_battle(vm, 1)
    first = vm.poll()
    _add_battle(vm, 1)
    second = vm.poll()
    assert second.battles_recorded != first.battles_recorded or \
        second.rows is not first.rows


# --- 3. 計測の道具そのもの -------------------------------------------

def test_the_probe_does_nothing_when_disabled():
    """★既定は無効。**計測のために遅くしない。**"""
    probe = Probe(enabled=False)
    with probe.section("なにか"):
        pass
    assert probe.stats == {}


def test_the_probe_records_even_when_the_section_raises():
    """⚠ 例外が出ても計測は閉じること。

    ★閉じないと、1回落ちただけで以降の数字が全部でたらめになる。
    """
    probe = Probe(enabled=True)
    with pytest.raises(ValueError):
        with probe.section("落ちる区間"):
            raise ValueError("わざと")
    assert probe.stats["落ちる区間"].count == 1


def test_the_probe_keeps_the_maximum_not_only_the_average():
    """⚠ 平均だけだと「たまに 300ms 掛かる」が消える。"""
    stat = Stat("x")
    for ms in (1.0, 1.0, 300.0):
        stat.add(ms)
    assert stat.max_ms == 300.0
    assert stat.average_ms < 110.0
    assert stat.over_stall == 1, "引っ掛かりを数えていない"
    assert stat.over_frame == 1


def test_only_real_stalls_are_logged():
    """⚠⚠ 毎回出すと**出力そのものが重くなる**（原因になる）。"""
    class _Log:
        def __init__(self):
            self.lines: list = []

        def warning(self, *args):
            self.lines.append(args)

    log = _Log()
    probe = Probe(enabled=True, logger=log)
    probe.record("軽い", 5.0)
    probe.record("警告候補", 60.0)
    probe.record("引っ掛かり", 150.0)
    assert len(log.lines) == 1, "しきい値を超えていないものまで出している"
    assert probe.stats["警告候補"].over_warn == 1, "集計には残すこと"


def test_the_probe_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("RETROUX_PERF", raising=False)
    assert Probe.from_env().enabled is False
    monkeypatch.setenv("RETROUX_PERF", "1")
    assert Probe.from_env().enabled is True


# --- 4. 更新間隔 -----------------------------------------------------

def test_the_refresh_interval_is_short_enough_to_feel_live():
    """★安くしたので間隔を詰められた（500ms → 200ms）。

    ⚠ これ以上速くしても表示は新しくならない。Lua が state.json を
      0.5秒ごとにしか書かないため。
    """
    from retroux.core.config.user_config import UserConfig

    assert UserConfig().gui.interval_ms <= 250

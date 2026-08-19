"""ViewModel のテスト（P6）。

ViewModel は Qt に依存しないので、画面を起動せずに表示ロジックを検証できる。
"""

from __future__ import annotations

import pytest

from retroux.core.db.database import Database
from retroux.core.recorder import Recorder
from retroux.ui.view_model import ViewModel

MONSTERS = {1: "スライム", 2: "おおナメクジ"}


@pytest.fixture
def vm(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    yield ViewModel(recorder, db, "HASH", MONSTERS), events, db
    db.close()


def _write(events, lines):
    events.write_text("".join(x + "\n" for x in lines), encoding="utf-8")


# --- モンスター名の整形 ----------------------------------------------


@pytest.mark.parametrize("ids,expected", [
    ([], "-"),
    ([1], "スライム"),
    ([1, 1], "スライム×2"),
    ([1, 1, 2], "スライム×2, おおナメクジ"),
    ([2, 1, 2], "おおナメクジ×2, スライム"),   # 出現順を保つ
])
def test_format_monsters(vm, ids, expected):
    view_model, _, _ = vm
    assert view_model.format_monsters(ids) == expected


def test_unknown_monster_shows_id(vm):
    """未知のIDでも表示が壊れないこと。

    判明しているIDは全82種のうち2種だけなので、未知は普通に出てくる。
    """
    view_model, _, _ = vm
    assert view_model.format_monsters([0x2A]) == "未知(0x2A)"


# --- 状態表示 --------------------------------------------------------


def test_state_label_prioritises_danger(vm):
    """危険状態は戦闘中より優先して表示する。倍速が解除される局面のため。"""
    view_model, events, _ = vm
    _write(events, [
        '{"type":"battle_start","frame":1,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"speed_change","frame":1,"multiplier":4}',
        '{"type":"danger_enter","frame":2,"reason":"HPが低い"}',
    ])
    state = view_model.poll()
    assert state.in_battle is True
    assert state.danger is True
    assert state.state_label == "危険状態"
    assert state.speed == 4.0
    assert state.current_monsters == "スライム"


def test_field_state_when_not_in_battle(vm):
    view_model, events, _ = vm
    _write(events, [
        '{"type":"battle_start","frame":1,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":2,"duration_frames":60,"speed_applied":4.0}',
    ])
    state = view_model.poll()
    assert state.state_label == "フィールド"
    assert state.current_monsters == "-"


def test_warning_is_surfaced(vm):
    """DEV-8 の警告が画面に出せる形で取れること。

    FCEUX のコンソールでは文字化けして読めないため、
    GUI に出せることが安全機構として重要。
    """
    view_model, events, _ = vm
    _write(events, ['{"type":"warning","frame":1,"message":"boss_monster_ids が空です"}'])
    assert view_model.poll().warnings == ["boss_monster_ids が空です"]


# --- 戦闘ログ --------------------------------------------------------


def test_battle_row_reports_saved_time(vm):
    """短縮できた時間が出ること。プロジェクトの価値そのものの指標。"""
    view_model, _, db = vm
    db.insert_battle(
        rom_hash="HASH", started_at="2026-07-22T01:02:03+00:00",
        ended_at="2026-07-22T01:02:06+00:00", duration_ms=3000,
        duration_frames=720,                      # 等速なら12秒
        monster_ids=[1, 1], is_first_encounter=False, is_boss=False,
        speed_applied=4.0, auto_input_used=True,
    )
    state = view_model.poll()
    assert len(state.rows) == 1
    row = state.rows[0]
    assert row.monsters == "スライム×2"
    assert row.duration_seconds == pytest.approx(3.0)
    assert row.saved_seconds == pytest.approx(9.0)   # 12秒 - 3秒
    assert state.saved_seconds_total == pytest.approx(9.0)


def test_rows_handle_missing_duration(vm):
    """RAM解析が未了の項目が NULL でも表示が壊れないこと。"""
    view_model, _, db = vm
    db.insert_battle(
        rom_hash="HASH", started_at="2026-07-22T01:02:03+00:00",
        ended_at=None, duration_ms=None, duration_frames=None,
        monster_ids=[2], is_first_encounter=True, is_boss=False,
        speed_applied=None, auto_input_used=False,
    )
    row = view_model.poll().rows[0]
    assert row.monsters == "おおナメクジ"
    assert row.is_first_encounter is True
    assert row.duration_seconds is None
    assert row.saved_seconds is None


# --- 閲覧専用（MVP2 Phase 1 / 指示書 6.3）----------------------------


def test_read_only_does_not_ingest(tmp_path):
    """★閲覧専用ではイベントを**取り込まない**。

    別の record プロセスが取り込んでいる最中に GUI も取り込むと、
    すべての戦闘が二重に記録される（single_instance.py の説明）。
    ロックが取れなかった GUI は閲覧専用へ落ちるので、
    そのとき本当に取り込まないことをここで押さえる。
    """
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"type":"battle_start","frame":1,"enemy_ids":[1],"enemy_count":1}\n'
        '{"type":"battle_end","frame":100,"duration_frames":99,"outcome":"win"}\n',
        encoding="utf-8",
    )
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    try:
        view_model = ViewModel(recorder, db, "HASH", MONSTERS, read_only=True)

        state = view_model.poll()

        assert state.read_only is True
        assert state.battles_recorded == 0          # 取り込んでいない
        assert db.speedup_summary("HASH")["battles"] == 0
    finally:
        db.close()


def test_normal_mode_ingests(tmp_path):
    """対になる確認: 通常モードでは取り込む（閲覧専用の効果を切り分ける）。"""
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"type":"battle_start","frame":1,"enemy_ids":[1],"enemy_count":1}\n'
        '{"type":"battle_end","frame":100,"duration_frames":99,"outcome":"win"}\n',
        encoding="utf-8",
    )
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    try:
        state = ViewModel(recorder, db, "HASH", MONSTERS).poll()
        assert state.read_only is False
        assert state.battles_recorded == 1
    finally:
        db.close()


# --- 表示の区別（画面を見て分かった問題）------------------------------


def test_unreadable_party_is_not_shown_as_danger():
    """★タイトル画面で赤い『危険状態』が出っぱなしになっていた。

    パーティ領域がまだ意味を持たない場面では、Lua の安全機構が
    「読めない＝危険」と倒す（これは正しい）。しかし画面に『危険状態』と
    出ると**壊れているように見える**。理由まで見て区別する。
    """
    from retroux.ui.view_model import UiState

    state = UiState(danger=True, danger_reason="パーティ状態を読めない")
    assert state.state_label == "待機中（セーブ未読込）"
    assert state.is_real_danger is False


def test_real_danger_is_still_danger():
    from retroux.ui.view_model import UiState

    state = UiState(danger=True, danger_reason="samaltria のHPが低い")
    assert state.state_label == "危険状態"
    assert state.is_real_danger is True


def test_danger_without_reason_is_treated_as_danger():
    """理由が届いていないときは**危険側**に倒す（安全側の既定）。"""
    from retroux.ui.view_model import UiState

    state = UiState(danger=True)
    assert state.state_label == "危険状態"
    assert state.is_real_danger is True


def test_battle_time_is_shown_in_local_time(tmp_path):
    """★画面に 05:03 と出ていたが、実際に戦ったのは 14:03（JST）だった。

    保存は UTC のままでよい（機械が比べるため）。表示だけ直す。
    """
    from datetime import datetime, timezone

    from retroux.ui.view_model import _to_local

    utc = "2026-07-26T05:03:23+00:00"
    local = _to_local(utc)
    assert datetime.fromisoformat(local) == datetime.fromisoformat(utc)
    # 変換後は実行環境の時差が乗る（UTC 環境では同じ値になるので比較はしない）
    assert datetime.fromisoformat(local).utcoffset() == datetime.now().astimezone().utcoffset()


def test_to_local_keeps_broken_value():
    """壊れた値でも落ちない（表示のために記録を失わない）。"""
    from retroux.ui.view_model import _to_local

    assert _to_local("こわれている") == "こわれている"


# --- 真実の源を1つにする（MVP2 Phase 2）------------------------------


def test_live_state_wins_over_recorder(tmp_path):
    """★同じ画面に真実の源を2つ置かない。

    ヘッダーが「フィールド ×1」なのにパーティ欄は戦闘中、という
    食い違いが実際に出た。**いまの値（state.json）がある間はそちらを正**とする。
    """
    import json

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "in_battle": True, "speed": 4, "danger": True,
        "danger_reason": "samaltria のHPが低い", "party": [],
    }), encoding="utf-8")

    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    try:
        vm = ViewModel(recorder, db, "HASH", MONSTERS, state_path=state)
        ui = vm.poll()

        # Recorder 側は「戦闘していない」ままだが、いまの値が優先される
        assert recorder.stats.in_battle is False
        assert ui.in_battle is True
        assert ui.speed == 4
        assert ui.state_label == "危険状態"
        assert ui.is_real_danger is True
    finally:
        db.close()


def test_recorder_is_used_when_no_live_state(tmp_path):
    """FCEUX が動いていないときは Recorder 側で表示する（受け皿）。"""
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    try:
        vm = ViewModel(recorder, db, "HASH", MONSTERS,
                       state_path=tmp_path / "いない.json")
        ui = vm.poll()
        assert ui.in_battle is False
        assert ui.game.fresh is False
    finally:
        db.close()

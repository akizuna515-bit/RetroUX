"""P5（Python側）のテスト。

エミュレータを起動せずに検証できる範囲を対象にする。
Lua 側のリアルタイム判断は実機検証（scripts/dev_autowalk.lua）で担保する。
"""

from __future__ import annotations

import json
import struct

import pytest

from retroux.core import events as ev
from retroux.core import rom as rom_mod
from retroux.core.bridge.reader import JsonlTailer
from retroux.core.bridge.writer import write_command
from retroux.core.db.database import Database
from retroux.core.recorder import Recorder

# --- ROM 同定 --------------------------------------------------------


def _make_rom(path, *, dirty_padding: bool, body: bytes = b"\xAA" * 64) -> None:
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 8      # PRG 8 x 16KB
    header[5] = 0      # CHR RAM
    header[6] = 0x20   # マッパー下位ニブル = 2
    if dirty_padding:
        header[7] = 0xF0                     # 汚れたヘッダのゴミ
        header[8:16] = b"\x02\xc6Ni0330"[:8]
    path.write_bytes(bytes(header) + body)


def test_prg_hash_ignores_header(tmp_path):
    """ヘッダを直しても rom_hash が変わらないこと（DEV-10 の核心）。

    これが崩れると、ヘッダ修正だけで遭遇済みモンスターの記録が失われる。
    """
    dirty = tmp_path / "dirty.nes"
    clean = tmp_path / "clean.nes"
    _make_rom(dirty, dirty_padding=True)
    _make_rom(clean, dirty_padding=False)

    assert rom_mod.rom_hash(dirty) == rom_mod.rom_hash(clean)
    # ファイル全体のハッシュは当然違う（だからこそ PRG-only にしている）
    assert dirty.read_bytes() != clean.read_bytes()


def test_dirty_header_is_detected_and_mapper_not_inflated(tmp_path):
    """ゴミ入りヘッダを検出し、マッパーを 242 と誤認しないこと。"""
    path = tmp_path / "dirty.nes"
    _make_rom(path, dirty_padding=True)
    info = rom_mod.identify(path)

    assert info.has_dirty_header is True
    assert info.mapper == 2          # 0xF0|0x2 = 242 にしてはいけない
    assert info.prg_size == 8 * 16 * 1024
    assert info.chr_size == 0


def test_invalid_rom_rejected(tmp_path):
    path = tmp_path / "bad.nes"
    path.write_bytes(b"NOTNES" + b"\x00" * 32)
    with pytest.raises(rom_mod.InvalidRomError):
        rom_mod.identify(path)


# --- イベント解析 ----------------------------------------------------


def test_parse_line_reads_battle_start():
    line = ('{"type":"battle_start","frame":10250,"enemy_ids":[1,1,2],'
            '"enemy_count":3,"is_first_encounter":true,"is_boss":false}')
    event = ev.parse_line(line)
    assert event is not None
    assert event.type == ev.BATTLE_START
    assert event.frame == 10250
    assert event.enemy_ids == [1, 1, 2]
    assert event.get("is_first_encounter") is True


@pytest.mark.parametrize("line", ["", "   ", "{壊れたJSON", "[1,2,3]", '{"frame":1}'])
def test_parse_line_rejects_garbage(line):
    """Lua 側は手書きでJSONを組むため壊れた行が混ざりうる。

    1行の失敗で取り込み全体を止めてはいけない。
    """
    assert ev.parse_line(line) is None


# --- JsonlTailer -----------------------------------------------------


def test_tailer_returns_only_complete_lines(tmp_path):
    """書き込み途中の行を読まないこと。"""
    path = tmp_path / "events.jsonl"
    path.write_text('{"type":"a","frame":1}\n{"type":"b","frame":2}\n{"type":"c"',
                    encoding="utf-8")
    tailer = JsonlTailer(path)

    first = list(tailer.read_new_lines())
    assert len(first) == 2                      # 未完了の3行目は返さない

    # 3行目が完成したら次回に読める
    with path.open("a", encoding="utf-8") as fh:
        fh.write(',"frame":3}\n')
    second = [ev.parse_line(x) for x in tailer.read_new_lines()]
    assert [e.type for e in second if e] == ["c"]


def test_tailer_rereads_when_file_shrinks(tmp_path):
    """ファイルが作り直されたら先頭から読み直すこと。"""
    path = tmp_path / "events.jsonl"
    path.write_text('{"type":"old","frame":1}\n' * 5, encoding="utf-8")
    tailer = JsonlTailer(path)
    assert len(list(tailer.read_new_lines())) == 5

    path.write_text('{"type":"new","frame":1}\n', encoding="utf-8")
    assert [ev.parse_line(x).type for x in tailer.read_new_lines()] == ["new"]


# --- command.json ----------------------------------------------------


def test_write_command_is_parseable_by_lua_style_regex(tmp_path):
    """Lua 側は正規表現で拾うため、素直な1行の形であること。"""
    import re

    path = tmp_path / "command.json"
    write_command(path, encountered=[2, 1, 1], battle_multiplier=4.0)
    body = path.read_text(encoding="utf-8")

    assert json.loads(body)["encountered"] == [1, 2]      # 重複排除・整列
    # bridge.lua と同じ抽出方法で読めること
    ids = re.search(r'"encountered"\s*:\s*\[([^\]]*)\]', body)
    assert ids and [int(n) for n in re.findall(r"\d+", ids.group(1))] == [1, 2]
    mult = re.search(r'"battle_multiplier"\s*:\s*([\d.]+)', body)
    assert mult and float(mult.group(1)) == 4.0


def test_action_is_parseable_and_carries_request_id(tmp_path):
    """単発操作は bridge.lua と同じ正規表現で読めること。

    ★request_id が必須。command.json は消えずに残るため、これが無いと
    Lua 側が30フレームごとに同じ操作を繰り返し、やくそうを使い切る。
    """
    import re

    path = tmp_path / "command.json"
    write_command(path, encountered=[], action="mantan", request_id=7)
    body = path.read_text(encoding="utf-8")

    act = re.search(r'"action"\s*:\s*"([\w_]+)"', body)
    assert act and act.group(1) == "mantan"
    rid = re.search(r'"request_id"\s*:\s*(\d+)', body)
    assert rid and int(rid.group(1)) == 7


def test_action_request_id_defaults_to_increasing_value(tmp_path):
    """request_id を省略しても整数が入り、呼ぶたびに前回以上になること。"""
    import re

    path = tmp_path / "command.json"
    ids = []
    for _ in range(2):
        write_command(path, encountered=[], action="mantan")
        rid = re.search(r'"request_id"\s*:\s*(\d+)',
                        path.read_text(encoding="utf-8"))
        assert rid, "request_id が書かれていない"
        ids.append(int(rid.group(1)))
    assert ids[1] >= ids[0]


def test_reset_encountered_is_absent_by_default(tmp_path):
    """既定でリセットを書かないこと。

    Lua 側は encountered を**合併**する。既定でリセットを書くと
    Lua が実時間で登録した分が消え、同じモンスターが何度も「初遭遇」に
    なって自動入力が無効化され続ける（ドラキー・アイアンアントで発生した）。
    """
    path = tmp_path / "command.json"
    write_command(path, encountered=[1, 2])
    assert "reset_encountered" not in json.loads(path.read_text(encoding="utf-8"))


def test_reset_encountered_is_written_as_lowercase_true(tmp_path):
    """明示的なリセットは Lua 側の正規表現で読める形であること。"""
    import re

    path = tmp_path / "command.json"
    write_command(path, encountered=[1], reset_encountered=True)
    body = path.read_text(encoding="utf-8")
    assert re.search(r'"reset_encountered"\s*:\s*true', body)


def test_no_action_field_when_not_requested(tmp_path):
    """操作を要求していないときに action を書かないこと。

    残っていると Lua 側が起動時に拾ってしまう。
    """
    path = tmp_path / "command.json"
    write_command(path, encountered=[1], battle_multiplier=4.0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "action" not in payload
    assert "request_id" not in payload


# --- DB --------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.register_rom("HASH", "テストROM", "JP", mapper=2)
    yield database
    database.close()


def test_mark_encountered_reports_only_new_ids(db):
    assert db.mark_encountered("HASH", [1, 2]) == {1, 2}
    assert db.mark_encountered("HASH", [1, 3]) == {3}     # 1 は既知
    assert db.encountered_ids("HASH") == {1, 2, 3}


def test_speedup_summary_computes_saved_time(db):
    # 600フレーム(等速なら10秒)の戦闘を、実測2.5秒で終えた
    db.insert_battle(
        rom_hash="HASH", started_at="2026-07-22T00:00:00+00:00",
        ended_at="2026-07-22T00:00:02+00:00", duration_ms=2500,
        duration_frames=600, monster_ids=[1], is_first_encounter=False,
        is_boss=False, speed_applied=4.0, auto_input_used=True,
    )
    s = db.speedup_summary("HASH")
    assert s["battles"] == 1
    assert s["baseline_ms"] == 10000
    assert s["actual_ms"] == 2500
    assert s["saved_ms"] == 7500


def test_empty_legacy_battles_are_excluded_from_views_and_summary(db):
    db.insert_battle(
        rom_hash="HASH", started_at="2026-07-22T00:00:00+00:00",
        ended_at="2026-07-22T00:00:00+00:00", duration_ms=0,
        duration_frames=1, monster_ids=[], is_first_encounter=False,
        is_boss=False, speed_applied=40.0, auto_input_used=False,
    )
    db.insert_battle(
        rom_hash="HASH", started_at="2026-07-22T00:01:00+00:00",
        ended_at="2026-07-22T00:01:02+00:00", duration_ms=2000,
        duration_frames=600, monster_ids=[1], is_first_encounter=False,
        is_boss=False, speed_applied=4.0, auto_input_used=True,
    )

    assert db.battle_count("HASH") == 1
    assert len(db.recent_battles("HASH")) == 1
    summary = db.speedup_summary("HASH")
    assert summary["battles"] == 1
    assert summary["total_frames"] == 600
    assert summary["actual_ms"] == 2000
    assert summary["avg_speed"] == pytest.approx(4.0)


# --- Recorder --------------------------------------------------------


def _events_file(tmp_path, lines):
    path = tmp_path / "events.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def test_recorder_pairs_start_and_end_into_one_battle(tmp_path, db):
    # 1回目 = battle_start 時刻、2回目 = battle_end 時刻。差が duration_ms になる。
    ticks = iter([100.0, 103.0])
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1,1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json",
                        clock=lambda: next(ticks))
    assert recorder.poll() == 2

    rows = db.recent_battles("HASH")
    assert len(rows) == 1
    assert json.loads(rows[0]["monster_ids"]) == [1, 1]
    assert rows[0]["duration_frames"] == 690
    assert rows[0]["speed_applied"] == 4.0
    assert rows[0]["duration_ms"] == 3000
    assert rows[0]["auto_input_used"] == 1
    # RAM解析が未了の項目は NULL のまま
    assert rows[0]["result"] is None
    assert rows[0]["exp_gained"] is None


def test_recorder_prefers_lua_measured_duration(tmp_path, db):
    """Lua が測った実時間を優先すること。

    こちら側の時計は「イベントを処理した時刻」でしかなく、ポーリング間隔より
    短い戦闘では所要時間が 0 に潰れる。「削減できた待ち時間」の集計に直結する。
    """
    ticks = iter([100.0, 100.05])          # 同一ポーリング内で処理された想定（50ms差）
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,'
        '"speed_applied":4.0,"duration_ms":2870}',
    ])
    Recorder(db, "HASH", events_path, tmp_path / "command.json",
             clock=lambda: next(ticks)).poll()

    # 自前計測なら 50ms になるが、Lua の 2870ms を採るべき
    assert db.recent_battles("HASH")[0]["duration_ms"] == 2870


def test_recorder_records_battle_outcome(tmp_path, db):
    """戦闘の結末を BattleLog.result に残すこと。

    Lua 側が判定した値をそのまま使う。
    ★enemy_fled（敵が逃げた）を独立した値にしているのが要点。
      当初これを「勝てなかった」に含めてしまい、雑魚が警戒リストに入って
      自動戦闘が効かなくなる不具合を出した。
    """
    for outcome in ("win", "lose", "flee", "enemy_fled"):
        sub = tmp_path / outcome
        sub.mkdir()
        events_path = _events_file(sub, [
            '{"type":"battle_start","frame":10,"enemy_ids":[1],'
            '"is_first_encounter":false,"is_boss":false}',
            '{"type":"battle_end","frame":700,"duration_frames":690,'
            f'"speed_applied":4.0,"duration_ms":100,"outcome":"{outcome}"}}',
        ])
        Recorder(db, "HASH", events_path, sub / "command.json").poll()
        assert db.recent_battles("HASH")[0]["result"] == outcome


def test_recorder_tolerates_events_without_outcome(tmp_path, db):
    """outcome を持たない古い形式のイベントでは result を NULL にすること。

    events.jsonl は消さずに積み上がるため、古い行が必ず混ざる。
    """
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,'
        '"speed_applied":4.0,"duration_ms":100}',
    ])
    Recorder(db, "HASH", events_path, tmp_path / "command.json").poll()
    assert db.recent_battles("HASH")[0]["result"] is None


def test_recorder_falls_back_to_own_clock_without_lua_duration(tmp_path, db):
    """Lua が duration_ms を送らない場合は自前計測にフォールバックすること。"""
    ticks = iter([100.0, 103.0])
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
    ])
    Recorder(db, "HASH", events_path, tmp_path / "command.json",
             clock=lambda: next(ticks)).poll()

    assert db.recent_battles("HASH")[0]["duration_ms"] == 3000


def test_recorder_stores_reward_when_victory_was_observed(tmp_path, db):
    """勝利表示中に捕まえた獲得経験値/ゴールドが BattleLog に入ること。"""
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,'
        '"speed_applied":4.0,"exp_gained":3,"gold_gained":4}',
    ])
    Recorder(db, "HASH", events_path, tmp_path / "command.json").poll()

    row = db.recent_battles("HASH")[0]
    assert row["exp_gained"] == 3
    assert row["gold_gained"] == 4


def test_recorder_leaves_reward_null_when_not_observed(tmp_path, db):
    """逃走・敗北では勝利表示が出ないため NULL のままであること。

    0 を入れてしまうと「0ゴールド獲得」と区別できなくなる。
    """
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
    ])
    Recorder(db, "HASH", events_path, tmp_path / "command.json").poll()

    row = db.recent_battles("HASH")[0]
    assert row["exp_gained"] is None
    assert row["gold_gained"] is None


def test_recorder_marks_auto_input_unused_for_first_encounter(tmp_path, db):
    """初遭遇では自動入力しない（DEV-6）。ログにもそれが残ること。"""
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[9],'
        '"is_first_encounter":true,"is_boss":false}',
        '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":1.0}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")
    recorder.poll()

    row = db.recent_battles("HASH")[0]
    assert row["is_first_encounter"] == 1
    assert row["auto_input_used"] == 0


def test_recorder_survives_battle_end_without_start(tmp_path, db):
    """battle_start を取りこぼしても落ちないこと。

    Python が落ちてもゲームは動く設計（D-1）なので、
    途中から起動して battle_end だけ見る状況が普通に起きる。
    """
    events_path = _events_file(tmp_path, [
        '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")
    assert recorder.poll() == 1
    assert db.battle_count("HASH") == 0        # 記録はしないが例外も出さない


def test_recorder_ignores_battle_with_empty_enemy_ids(tmp_path, db):
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[],"is_boss":false}',
        '{"type":"battle_end","frame":11,"duration_frames":1,"speed_applied":4.0}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")

    assert recorder.poll() == 2
    assert db.battle_count("HASH") == 0
    assert recorder.stats.in_battle is False
    assert recorder.stats.battles_recorded == 0
    assert db.encountered_ids("HASH") == set()


def test_same_warning_from_gui_and_lua_is_shown_once(tmp_path, db):
    """同じ問題を GUI 側と Lua 側の両方が報告しても、1つだけ表示すること。

    実機で「boss_monster_ids が未設定です」と「〜が空です」の2行が
    並んで出る不具合があった。文言の一致に頼ると些細な差で重複する。
    """
    events_path = _events_file(tmp_path, [
        '{"type":"warning","frame":1,"code":"boss_ids_empty",'
        '"message":"boss_monster_ids が空です。ボス戦を通常戦闘として扱います。"}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")
    # GUI 側が起動直後に出す分（文言が少し違う）
    recorder.add_warning("boss_monster_ids が未設定です。ボス戦を通常戦闘として扱います。",
                         code="boss_ids_empty")
    recorder.poll()

    assert len(recorder.stats.warnings) == 1


def test_warnings_without_code_dedupe_by_message(tmp_path, db):
    events_path = _events_file(tmp_path, [
        '{"type":"warning","frame":1,"message":"同じ内容"}',
        '{"type":"warning","frame":2,"message":"同じ内容"}',
        '{"type":"warning","frame":3,"message":"別の内容"}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")
    recorder.poll()
    assert recorder.stats.warnings == ["同じ内容", "別の内容"]


def test_recorder_collects_warnings_and_tracks_state(tmp_path, db):
    events_path = _events_file(tmp_path, [
        '{"type":"warning","frame":1,"message":"boss_monster_ids が空です"}',
        '{"type":"battle_start","frame":10,"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        '{"type":"speed_change","frame":10,"multiplier":4,"reason":"通常戦闘"}',
        '{"type":"danger_enter","frame":50,"reason":"lorasia のHPが低い"}',
    ])
    recorder = Recorder(db, "HASH", events_path, tmp_path / "command.json")
    recorder.poll()

    assert recorder.stats.warnings == ["boss_monster_ids が空です"]
    assert recorder.stats.in_battle is True
    assert recorder.stats.current_speed == 4.0
    assert recorder.stats.danger is True


def test_recorder_pushes_encountered_to_command_file(tmp_path, db):
    """DB を正として遭遇済み集合を Lua へ返すこと。"""
    command_path = tmp_path / "command.json"
    events_path = _events_file(tmp_path, [
        '{"type":"battle_start","frame":10,"enemy_ids":[2,7],'
        '"is_first_encounter":true,"is_boss":false}',
    ])
    recorder = Recorder(db, "HASH", events_path, command_path)
    recorder.poll()

    assert json.loads(command_path.read_text(encoding="utf-8"))["encountered"] == [2, 7]


# --- イベントの時刻（MVP2 Phase 1）------------------------------------


def test_battle_uses_event_time_not_ingest_time(tmp_path):
    """★取り込みが遅れても**起きた時刻**で記録する。

    以前は取り込んだ時点の時計を使っていた。追いついている間は同じだが、
    溜まったぶんを後からまとめて処理すると**全部が同じ時刻**になる。
    実際、4820件を追いついたとき 1400 戦闘すべてが 14:03 になった。
    Lua が `time`（os.time()）を入れるようにしたので、それを使う。
    """
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    # 2026-07-25 12:00:00 UTC = 1784980800
    events.write_text(
        '{"type":"battle_start","frame":1,"time":1784980800,"enemy_ids":[1],"enemy_count":1}\n'
        '{"type":"battle_end","frame":100,"time":1784980810,"duration_frames":99,"outcome":"win"}\n',
        encoding="utf-8",
    )
    recorder = Recorder(db, "HASH", events, tmp_path / "command.json")
    try:
        recorder.poll()
        row = db.recent_battles("HASH", 1)[0]
        assert row["started_at"].startswith("2026-07-25T12:00:00")
        assert row["ended_at"].startswith("2026-07-25T12:00:10")
    finally:
        db.close()


def test_battle_falls_back_to_now_without_event_time(tmp_path):
    """古い events.jsonl（time が無い）でも動く。"""
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder

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
        recorder.poll()
        row = db.recent_battles("HASH", 1)[0]
        assert row["started_at"]        # 何かしら入っている（落ちない）
    finally:
        db.close()

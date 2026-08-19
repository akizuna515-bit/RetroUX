"""終了ボタンの部品のテスト（MVP2 Phase 1 / 依頼者の要望）。

★守りたいこと:
  1. 保存できたという**返事を受け取ってから**閉じる
     （頼んだだけで閉じると、FCEUX が先に終わって保存されない）
  2. 前回の返事が残っていて「保存できた」と誤解しない
  3. スロット指定が Lua へ届く形で書かれる
"""

from __future__ import annotations

import pathlib

import json

from retroux.core import events as ev
from retroux.core.bridge.writer import write_command
from retroux.core.db.database import Database
from retroux.core.recorder import Recorder


def _recorder(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    return Recorder(db, "HASH", events, tmp_path / "command.json"), events, db


def test_save_slot_is_written_for_lua(tmp_path):
    """Lua は正規表現で拾うので、素直な1行の形で書かれること。"""
    path = tmp_path / "command.json"
    write_command(path, encountered=[1], action="save_state",
                  request_id=123, save_slot=4)

    body = path.read_text(encoding="utf-8")
    payload = json.loads(body)
    assert payload["action"] == "save_state"
    assert payload["save_slot"] == 4
    assert payload["request_id"] == 123
    # Lua 側の正規表現（"save_slot"%s*:%s*(%d+)）で拾える形か
    assert '"save_slot": 4' in body or '"save_slot":4' in body


def test_reply_is_received(tmp_path):
    recorder, events, db = _recorder(tmp_path)
    try:
        assert recorder.stats.savestate_saved is None

        events.write_text(
            '{"type":"savestate_saved","frame":1,"slot":3,"ok":true}\n',
            encoding="utf-8")
        recorder.poll()

        assert recorder.stats.savestate_saved == {"slot": 3, "ok": True}
    finally:
        db.close()


def test_failure_is_reported_as_failure(tmp_path):
    """★保存に失敗したら**失敗として届く**。成功と混ぜない。"""
    recorder, events, db = _recorder(tmp_path)
    try:
        events.write_text(
            '{"type":"savestate_saved","frame":1,"slot":3,"ok":false}\n',
            encoding="utf-8")
        recorder.poll()

        assert recorder.stats.savestate_saved == {"slot": 3, "ok": False}
    finally:
        db.close()


def test_event_type_is_registered():
    """イベント名の綴りをコード側と揃える（片方だけ直すと黙って届かなくなる）。"""
    assert ev.SAVESTATE_SAVED == "savestate_saved"


def test_writing_the_encountered_list_does_not_erase_a_pending_action(tmp_path):
    """★★ **P-3 が実機で NG になった原因そのもの**（2026-07-30）★★

    ⚠⚠ `command.json` は**複数の書き手が共有する状態ファイル**なのに、
      毎回 payload を作り直していた。そのため
      `Recorder.push_encountered()`（`encountered` だけを渡す）が
      **`action` と `request_id` を消していた**。

    ⚠ しかも自己破壊的だった。保存を待つループがこうなっていた:

        while 期限内:
            recorder.poll()      # ← イベントが1件でもあれば push_encountered()
                                 #    が走り、待っている action を消す

      Lua は 30 フレーム（0.5秒）ごとに読むので、その前に消えると
      **保存が実行されないまま5秒待って諦める**。
      実機では「保存して終了 → スロット1 に古い状態しか無い」になった。
      ★イベントが流れているかどうかで結果が変わるので、**たまに成功する**
        という見つけにくい壊れ方だった。
    """
    path = tmp_path / "command.json"

    # 1. 保存を頼む
    write_command(path, encountered=[1, 2], action="save_state",
                  request_id=111, save_slot=1)
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["action"] == "save_state"
    assert first["request_id"] == 111
    assert first["save_slot"] == 1

    # 2. その待ち時間に遭遇済みリストが書かれる（`push_encountered` と同じ形）
    write_command(path, encountered=[1, 2, 3])

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["action"] == "save_state", "action が消えている（P-3 の原因）"
    assert after["request_id"] == 111, "request_id が消えている"
    assert after["save_slot"] == 1, "save_slot が消えている"
    assert after["encountered"] == [1, 2, 3], "遭遇済みリストは更新される"


def test_a_one_shot_reset_flag_is_not_carried_over(tmp_path):
    """⚠ `reset_encountered` は**引き継がない**（一度きりの指示）。

    ★Lua 側は毎ポーリングでこの印を見るので、残すと
      **遭遇済みリストを延々リセットし続ける**。
    """
    path = tmp_path / "command.json"

    write_command(path, encountered=[5], reset_encountered=True)
    assert json.loads(path.read_text(encoding="utf-8"))["reset_encountered"]

    write_command(path, encountered=[5, 6])
    after = json.loads(path.read_text(encoding="utf-8"))
    assert "reset_encountered" not in after, "一度きりの印が残っている"


def test_other_settings_survive_an_encountered_write(tmp_path):
    """★倍率・まんたん・戦術の版も消さない（同じ理由）。"""
    path = tmp_path / "command.json"

    write_command(path, encountered=[1], battle_multiplier=4.0,
                  mantan_mode="full", tactics_revision=999)
    write_command(path, encountered=[1, 2])

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["battle_multiplier"] == 4.0
    assert after["mantan_mode"] == "full"
    assert after["tactics_revision"] == 999


def test_a_broken_command_file_does_not_stop_the_next_write(tmp_path):
    """⚠ 既にある内容を読むようにしたので、**壊れていても書けること**。"""
    path = tmp_path / "command.json"
    path.write_text("これは JSON ではない {{{", encoding="utf-8")

    write_command(path, encountered=[7], action="save_state", request_id=1)

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["encountered"] == [7]
    assert after["action"] == "save_state"


def _bridge_source() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[1] / "retroux"
            / "emulator" / "fceux" / "bridge.lua").read_text(encoding="utf-8")


def test_the_command_poll_survives_a_savestate_load():
    """★★★ **セーブステートをロードすると `framecount` は巻き戻る。** ★★★

    ⚠⚠ フレームカウンタは**セーブステートに含まれている**。
      古い状態を読むと今より小さい値に戻るので、

          emu.framecount() - self.last_poll >= 30

      の差が**負**になり、条件が**二度と成立しない**。
      ＝ `command.json` を永久に読まなくなる。

    ⚠ 実機で踏んだ形（2026-07-31 / P-3）:
      1. 起動して遊ぶ（framecount が増える）
      2. スロット1 をロードする（framecount が巻き戻る）
      3. 以後**保存も倍速も戦術の切り替えも届かない**（全部 command.json 経由）
      4. 「保存して終了」が5秒待って諦める
      ★1回目の保存だけ成功していたのは**まだロードしていなかった**から。
        この「最初だけ通る」が切り分けを難しくした。

    ★詳しい動きの確認は `research/probes/active/framecount_rewind_test.lua`（実 Lua）。
      ここでは**直し忘れ**を止めるためにソースを見る。
    """
    src = _bridge_source()

    assert "if now < self.last_poll then" in src, \
        "巻き戻りの判定が無い（ロード後に監視が止まる）"
    assert "emu.framecount() - self.last_poll" not in src, \
        "古い引き算が残っている（巻き戻りで止まる）"


def test_a_rewound_battle_does_not_record_a_negative_duration():
    """⚠ 戦闘中にロードすると戦闘時間が**負**になる。

    ★分からないものは**書かない**（0 を入れると「一瞬で終わった」に見える）。
    """
    src = _bridge_source()
    assert "if delta >= 0 then frames = delta end" in src, \
        "負の戦闘時間を弾いていない"
    assert "duration_frames = emu.framecount() - self.state.battle_started" \
        not in src, "古い引き算が残っている"


def test_savestate_is_flushed_to_disk_with_persist():
    """★★★ **`save` だけではファイルに書かれない**（2026-07-31 実測）★★★

    `savestate.save()` は FCEUX の**メモリ上のスロット**に入れるだけで、
    `<ROM名>.fc<番号>` のファイルは変わらない。**例外も出ない**ので、
    こちら側は「保存できた」と思い込む。

    ⚠⚠ 実機で起きたこと（P-3）:
      「保存して終了」→ スロット1 をロード → **5日前の状態が出てくる**。
      ログは「保存しました」なのに、ファイルの時刻は5日前だった。

    ★同じ実行の中で並べて確かめた（`research/probes/archived/savestate_persist_probe.lua`）:

      | 呼び方 | 結果 |
      | --- | --- |
      | `save` だけ | **書かれない** |
      | `save` + `persist` | **書かれた**（79,305 バイト） |

    ⚠ FCEUX の説明では `persist` は「無名のセーブステートを残す」用だが、
      番号つきスロットでも**これが無いとファイルにならない**。
      説明ではなく**実測に従う**。
    """
    src = _bridge_source()

    assert "savestate.persist(obj)" in src, \
        "persist を呼んでいない（ファイルに書かれない）"
    # ⚠ インラインで作ると persist へ渡す相手が無くなる
    assert "savestate.save(savestate.object(slot))" not in src, \
        "オブジェクトを変数に残していない（persist へ渡せない）"
    # ★古い FCEUX に無くても落ちないこと
    assert "if savestate.persist ~= nil then" in src


def test_the_save_is_verified_against_the_file_not_just_the_ack():
    """★★ **Lua の返事を信じない。ファイルの時刻で確かめる。** ★★

    ⚠ 返事は「Lua が API を呼べた」ことしか意味しない。
      実機では返事が来たのに**ディスクには何も書かれていなかった**。
      ★「保存した」と言われて古い状態に戻されるのが、いちばん悪い形。
    """
    import pathlib

    text = (pathlib.Path(__file__).resolve().parents[1] / "retroux" / "ui"
            / "main_window.py").read_text(encoding="utf-8")

    assert "_savestate_file" in text, "保存先のファイルを見ていない"
    assert "def written()" in text, "ファイルの更新を確かめていない"
    # ★返事だけで True を返さないこと
    assert "acked = True" in text
    assert "if written():" in text


def test_startup_does_not_execute_a_stale_action():
    """★起動時に残っていた要求を**実行しない**（読んだことにするだけ）。

    ⚠ `pending_action = nil` では止められなかった。
      `save_state` と `capture_tile` は dispatch の中で**即座に実行される**
      特別扱いだから（実 Lua のテストで実証してから直した）。
    """
    src = _bridge_source()
    assert "function Bridge:_poll_command(discard_actions)" in src
    # ★★ 2026-08-01 のリファクタで、判断は `command_reader` へ移った。
    #   ⚠ 探す先を直さないと「直っているのに赤い」ままになる。
    reader = (pathlib.Path(__file__).resolve().parents[1]
              / "retroux" / "emulator" / "fceux"
              / "command_reader.lua").read_text(encoding="utf-8")
    assert "if discard_actions then" in reader,         "起動時に残った要求を捨てる仕組みが無い"
    assert "self:_poll_command(true)" in src, "起動時に discard を渡していない"


def test_stop_file_path_is_derived_from_lock():
    """バックアップの停止ファイルは、ロックと同じ場所から決まる。"""
    from retroux.core.config.user_config import UserConfig

    cfg = UserConfig()
    stop = cfg.path("backup_lock").with_suffix(".stop")
    assert stop.name == "savestate_backup.stop"
    assert stop.parent == cfg.path("backup_lock").parent



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の2件は
#       assert "if now < self.last_poll then" in src
#   のように、**その行が書いてあるか**しか見ていません。
#   ★docstring は「詳しい動きの確認は framecount_rewind_test.lua」と
#     書いていましたが、⚠ **この検査からは一度も走らせていません**でした
#     （F-096 と同じ形。名前を出すだけでは確かめたことになりません）。
# =====================================================================

import os          # noqa: E402
import subprocess  # noqa: E402
import sys         # noqa: E402

import pytest      # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_REWIND = _ROOT / "research" / "probes" / "active" / "framecount_rewind_test.lua"
_LUA_RUN = _ROOT / "research" / "probes" / "reusable" / "lua_run.py"


@pytest.fixture(scope="module")
def rewind_lua():
    if not (_LUA_RUN.exists() and _REWIND.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_LUA_RUN), str(_REWIND)],
        cwd=str(_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _rewind_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_巻き戻りのハーネスが本当に通る(rewind_lua):
    assert "すべて通りました" in rewind_lua, rewind_lua


def test_巻き戻りの検査の数が足りている(rewind_lua):
    """⚠ 途中で落ちて「0件だから合格」にしない。"""
    count = sum(1 for line in rewind_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 9, f"OK が {count} 件しかありません\n{rewind_lua}"


def test_ふつうに進むときは30フレームごとに読む(rewind_lua):
    """★直しすぎていないこと（⚠ 巻き戻り対応で普段の読みを壊さない）。"""
    assert _rewind_ok(rewind_lua, "121 フレームで 4 回"), rewind_lua


def test_巻き戻っても読み続ける(rewind_lua):
    """⚠⚠ **これが 2026-07-31 に実機で踏んだ不具合そのもの。**

    ★ロードで `framecount` が戻ると差が負になり、条件が二度と成立せず
      `command.json` を永久に読まなくなります（保存も倍速も届かない）。
    """
    assert _rewind_ok(rewind_lua, "★巻き戻ったあとも読み続ける"), rewind_lua
    assert _rewind_ok(rewind_lua, "基準を今に合わせる"), rewind_lua


def test_巻き戻りが無ければ余計なことをしない(rewind_lua):
    """⚠ 毎回「巻き戻った」と記録すると、本当の巻き戻りが埋もれます。"""
    assert _rewind_ok(rewind_lua, "巻き戻りの記録は出ない"), rewind_lua


def test_負の戦闘時間を記録しない(rewind_lua):
    """★分からないものは**書かない**（0 だと「一瞬で終わった」に見える）。"""
    assert _rewind_ok(rewind_lua, "負なら duration_frames を書かない"),         rewind_lua

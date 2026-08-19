"""取り込み位置の永続化に関するテスト。

Lua 側は events.jsonl に追記し続ける（セッションをまたいで残る）。
Python 側を再起動したときに先頭から読み直すと、過去の戦闘を
重複して記録してしまう。それを防げていることを確かめる。
"""

from __future__ import annotations

import pytest

from retroux.core.db.database import Database
from retroux.core.recorder import Recorder

BATTLE = [
    '{"type":"battle_start","frame":10,"enemy_ids":[1],'
    '"is_first_encounter":false,"is_boss":false}',
    '{"type":"battle_end","frame":700,"duration_frames":690,"speed_applied":4.0}',
]


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    yield db, events, tmp_path / "command.json"
    db.close()


def _append(events, lines):
    with events.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def test_restart_does_not_duplicate_past_battles(env):
    """記録プロセスを再起動しても、過去の戦闘を二重に記録しないこと。"""
    db, events, command = env

    first = Recorder(db, "HASH", events, command)
    _append(events, BATTLE)
    first.poll()
    assert db.battle_count("HASH") == 1

    # プロセスを落として再起動した状況
    second = Recorder(db, "HASH", events, command)
    second.poll()
    assert db.battle_count("HASH") == 1, "再起動で過去の戦闘が重複記録された"

    # 再起動後の新しい戦闘はきちんと拾う
    _append(events, BATTLE)
    second.poll()
    assert db.battle_count("HASH") == 2


def _battle(frame: int) -> list[str]:
    """フレーム番号違いの戦闘イベント。実際のログも毎回フレーム番号が異なる。"""
    return [
        f'{{"type":"battle_start","frame":{frame},"enemy_ids":[1],'
        '"is_first_encounter":false,"is_boss":false}',
        f'{{"type":"battle_end","frame":{frame + 690},'
        '"duration_frames":690,"speed_applied":4.0}',
    ]


def test_recreated_file_is_read_from_start(env):
    """events.jsonl が削除されて作り直された場合は先頭から読むこと。

    保存した位置をそのまま使うと、新しいセッションの先頭を読み飛ばす。
    ファイルサイズだけでは見分けられない場合があるため、先頭の署名で判定する。
    """
    db, events, command = env

    first = Recorder(db, "HASH", events, command)
    _append(events, _battle(100))
    first.poll()
    assert db.battle_count("HASH") == 1

    # ユーザーが events.jsonl を消し、新しいセッションが始まった
    events.unlink()
    events.write_text("", encoding="utf-8")
    _append(events, _battle(50000))

    second = Recorder(db, "HASH", events, command)
    second.poll()
    assert db.battle_count("HASH") == 2, "作り直されたファイルの先頭を読み飛ばした"


def test_same_file_continues_from_saved_offset(env):
    """同じファイルを読み続けている場合は、保存位置から再開すること。"""
    db, events, command = env

    first = Recorder(db, "HASH", events, command)
    _append(events, _battle(100))
    first.poll()

    _append(events, _battle(2000))
    second = Recorder(db, "HASH", events, command)   # 再起動
    second.poll()
    assert db.battle_count("HASH") == 2              # 1件目は重複しない

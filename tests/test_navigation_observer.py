"""移動の結果を判定する（2026-07-30 / 指示書 5章・11章）。

★★ **操作ではなく結果を保存する**（指示書 2.2）★★

    ✗ 「右キーを押した」
    ✓ 「(10,5) から右へ進み、(11,5) に移動できた」
    ✓ 「(10,5) から上へ進もうとしたが、座標が変わらなかった」

★ここで守ること（指示書 11章の項目に対応）:
  1. 成功移動で `MapEdge` が1件
  2. 同じ経路を10回通っても1行
  3. 失敗は**期限が来てから**記録し、初回は `unknown_block` + `provisional`
  4. 3回失敗で `probable`
  5. 一度通れたら壁の疑いを外す
  6. マップ遷移が前後座標つきで残る
  7. 同じ遷移は行が増えない
  8. **戦闘中は記録しない**
  9. 状態が欠けていたら記録しない（★ただし 0 は正常値）
  10. 入力後に戦闘へ入ったら blocked にしない
  11. DB が壊れても本体を止めない
"""

from __future__ import annotations

import pytest

from retroux.core.bridge.state_reader import GameState
from retroux.core.db.database import Database
from retroux.core.navigation.models import (
    Classification, Confidence, Direction,
)
from retroux.core.navigation.observer import NavigationObserver
from retroux.core.navigation.repository import NavigationRepository, Thresholds

HASH = "HASH"
MAP_ID, MAP_PTR = 0x07, 0x8E83
TIMEOUT = 30


@pytest.fixture
def obs(tmp_path):
    """★★ **わざと入にしている**（2026-08-13 / 製品版ログ整理 §12）★★

    通常歩行の学習は **既定で切**に変えました（ROM 解析で作れるため）。
    ⚠ ここから下の検査は「仕組みが正しく動くか」を見るものなので、
      ★明示的に入にしてから確かめます（研究用に取り直す道が生きている、
      という確認も兼ねます）。

    ⚠ 「既定が切であること」は `test_既定では通常歩行を記録しない` が見ます。
      ★片方だけでは、既定を戻しても両方緑のままになります。
    """
    db = Database(tmp_path / "n.sqlite3")
    db.register_rom(HASH, "テストROM", "JP", mapper=2)
    repo = NavigationRepository(db, HASH, Thresholds(blocked_probable=3))
    observer = NavigationObserver(repo, move_timeout_frames=TIMEOUT,
                                  record_edges=True, record_blocked=True)
    yield observer, repo
    db.close()


def state(x: int, y: int, *, frame: int = 0, direction: str | None = None,
          map_id: int = MAP_ID, ptr: int = MAP_PTR, battle: bool = False,
          fresh: bool = True) -> GameState:
    return GameState(fresh=fresh, in_battle=battle, frame=frame,
                     map_id=map_id, map_x=x, map_y=y, map_data_pointer=ptr,
                     input_direction=direction)


def walk(observer, x0, y0, x1, y1, *, frame=0, direction="right"):
    """本番と同じ経路: まず居る -> 入力 -> 動いた。"""
    observer.observe(state(x0, y0, frame=frame))
    observer.observe(state(x0, y0, frame=frame + 1, direction=direction))
    return observer.observe(state(x1, y1, frame=frame + 10, direction=direction))


# --- 11.1 成功移動 -----------------------------------------------------


def test_successful_move_records_an_edge(obs):
    observer, repo = obs
    got = walk(observer, 10, 5, 11, 5)
    assert got.moved and got.direction is Direction.RIGHT
    rows = repo.edges(MAP_ID, MAP_PTR)
    assert len(rows) == 1
    assert (rows[0]["from_x"], rows[0]["from_y"]) == (10, 5)
    assert (rows[0]["to_x"], rows[0]["to_y"]) == (11, 5)
    assert rows[0]["direction"] == "right"
    assert rows[0]["success_count"] == 1


def test_direction_is_derived_from_the_movement(obs):
    """★方向は**座標の変化から**決める（押した入力を信じ切らない）。

    入力を取りこぼしたフレームでも、動いた事実があれば道は分かる。
    """
    observer, repo = obs
    observer.observe(state(10, 5))
    got = observer.observe(state(10, 4, frame=10))     # 入力を渡していない
    assert got.moved and got.direction is Direction.UP
    assert repo.edges(MAP_ID, MAP_PTR)[0]["direction"] == "up"


def test_unexpected_jump_is_not_an_edge(obs):
    """⚠ 隣の1マスでない変化は「通れた」と言えない（指示書 5.3）。"""
    observer, repo = obs
    observer.observe(state(10, 5))
    got = observer.observe(state(15, 9, frame=10))
    assert not got.moved
    assert got.skipped == "unexpected_jump"
    assert repo.edges(MAP_ID, MAP_PTR) == []


# --- 11.2 同一経路の再通過 ---------------------------------------------


def test_same_path_does_not_add_rows(obs):
    """★★ 同じ道を10回通っても**1行**。

    ⚠ 繰り返しの間に `fresh=False` を挟んでいるのは、
      **戻る動き（11,5 -> 10,5）を作らないため**。
      挟まないと逆方向の辺も観測され、行が2本になる（それは正しい挙動）。
    """
    observer, repo = obs
    for i in range(10):
        observer.observe(GameState(fresh=False))
        observer.observe(state(10, 5, frame=i * 100))
        observer.observe(state(11, 5, frame=i * 100 + 10))
    rows = repo.edges(MAP_ID, MAP_PTR)
    assert len(rows) == 1
    assert rows[0]["success_count"] == 10


def test_walking_back_is_a_second_edge(obs):
    """★★ 行きと帰りは**別の辺**（指示書 6章）。

    一方通行・落とし穴があるので、片方を観測しても逆は登録しない。
    """
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    observer.observe(state(11, 5, frame=10))
    assert len(repo.edges(MAP_ID, MAP_PTR)) == 1
    observer.observe(state(10, 5, frame=20))
    rows = repo.edges(MAP_ID, MAP_PTR)
    assert len(rows) == 2
    assert {r["direction"] for r in rows} == {"right", "left"}


# --- 11.3 失敗移動 -----------------------------------------------------


def test_blocked_is_recorded_after_the_timeout(obs):
    """★期限が来てから記録する。押した瞬間には書かない（指示書 5.2）。"""
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    got = observer.observe(state(10, 5, frame=1, direction="up"))
    assert not got.recorded, "押した瞬間に書いている"
    assert repo.blocked(MAP_ID, MAP_PTR) == []

    got = observer.observe(state(10, 5, frame=1 + TIMEOUT, direction="up"))
    assert got.blocked and got.direction is Direction.UP
    rows = repo.blocked(MAP_ID, MAP_PTR)
    assert len(rows) == 1
    assert rows[0]["classification"] == Classification.UNKNOWN_BLOCK.value
    assert rows[0]["confidence"] == Confidence.PROVISIONAL.value


def test_waiting_does_not_record(obs):
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    for f in range(1, TIMEOUT):
        got = observer.observe(state(10, 5, frame=f, direction="up"))
        assert got.skipped in ("no_change", "waiting"), got
    assert repo.blocked(MAP_ID, MAP_PTR) == []


def test_no_input_means_no_blocked(obs):
    """⚠★ 立ち止まっているだけを「通れなかった」にしない。

    入力を見ないと「進もうとした」ことが言えない。
    """
    observer, repo = obs
    for f in range(0, 200, 10):
        observer.observe(state(10, 5, frame=f))
    assert repo.blocked(MAP_ID, MAP_PTR) == []


def test_changing_direction_restarts_the_wait(obs):
    """★押す方向を変えたら、前の保留は捨てる（結果が言えない）。"""
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    observer.observe(state(10, 5, frame=1, direction="up"))
    got = observer.observe(state(10, 5, frame=5, direction="left"))
    assert got.skipped == "direction_changed"
    # ★up の期限が来ても up は記録されない（left に切り替わっている）
    observer.observe(state(10, 5, frame=5 + TIMEOUT, direction="left"))
    rows = repo.blocked(MAP_ID, MAP_PTR)
    assert len(rows) == 1
    assert rows[0]["direction"] == "left"


# --- 11.4 失敗の集約 ---------------------------------------------------


def test_repeated_failures_raise_the_confidence(obs):
    observer, repo = obs
    for i in range(3):
        base = i * 1000
        observer.observe(state(10, 5, frame=base))
        observer.observe(state(10, 5, frame=base + 1, direction="up"))
        observer.observe(state(10, 5, frame=base + 1 + TIMEOUT, direction="up"))
    rows = repo.blocked(MAP_ID, MAP_PTR)
    assert len(rows) == 1
    assert rows[0]["blocked_count"] == 3
    assert rows[0]["confidence"] == Confidence.PROBABLE.value


# --- 11.5 一度通れた方向 -----------------------------------------------


def test_passing_later_clears_the_wall(obs):
    observer, repo = obs
    for i in range(3):
        base = i * 1000
        observer.observe(state(10, 5, frame=base))
        observer.observe(state(10, 5, frame=base + 1, direction="up"))
        observer.observe(state(10, 5, frame=base + 1 + TIMEOUT, direction="up"))
    assert repo.blocked(MAP_ID, MAP_PTR)[0]["confidence"] == \
        Confidence.PROBABLE.value

    walk(observer, 10, 5, 10, 4, frame=9000, direction="up")
    assert len(repo.edges(MAP_ID, MAP_PTR)) == 1
    row = repo.blocked(MAP_ID, MAP_PTR)[0]
    assert row["success_count"] == 1
    assert row["confidence"] == Confidence.PROVISIONAL.value


# --- 11.6 / 11.7 マップ遷移 --------------------------------------------


def test_map_transition_is_recorded(obs):
    observer, repo = obs
    observer.observe(state(11, 22, map_id=0x07, ptr=0x8E83))
    got = observer.observe(state(100, 100, frame=10, map_id=0x01, ptr=0x8000))
    assert got.transition
    rows = repo.transitions()
    assert len(rows) == 1
    r = rows[0]
    assert (r["from_map_id"], r["from_x"], r["from_y"]) == (0x07, 11, 22)
    assert (r["to_map_id"], r["to_x"], r["to_y"]) == (0x01, 100, 100)


def test_pointer_change_alone_is_a_transition(obs):
    """★`map_id` が同じでもデータ位置が変われば別のマップ（階が違う）。"""
    observer, repo = obs
    observer.observe(state(1, 1, map_id=0x40, ptr=0xA293))
    got = observer.observe(state(2, 2, frame=10, map_id=0x40, ptr=0xA400))
    assert got.transition
    assert len(repo.transitions()) == 1


def test_same_transition_does_not_add_rows(obs):
    """⚠ 繰り返しの間に `fresh=False` を挟むのは、**帰りの遷移**
    （ワールドマップ -> 街）を作らないため。挟まないと2本になる（正しい挙動）。
    """
    observer, repo = obs
    for i in range(4):
        base = i * 1000
        observer.observe(GameState(fresh=False))
        observer.observe(state(11, 22, frame=base, map_id=0x07, ptr=0x8E83))
        observer.observe(state(100, 100, frame=base + 10, map_id=0x01, ptr=0x8000))
    rows = repo.transitions()
    assert len(rows) == 1
    assert rows[0]["observed_count"] == 4


def test_going_back_is_a_second_transition(obs):
    """★入口と出口は別の遷移として残る（片方から逆を推測しない）。"""
    observer, repo = obs
    observer.observe(state(11, 22, map_id=0x07, ptr=0x8E83))
    observer.observe(state(100, 100, frame=10, map_id=0x01, ptr=0x8000))
    observer.observe(state(11, 22, frame=20, map_id=0x07, ptr=0x8E83))
    assert len(repo.transitions()) == 2


def test_transition_is_not_recorded_as_blocked(obs):
    """⚠★ マップが変わったのを「通れなかった」と数えない（指示書 5.4）。"""
    observer, repo = obs
    observer.observe(state(11, 22, frame=0))
    observer.observe(state(11, 22, frame=1, direction="up"))
    observer.observe(state(100, 100, frame=5, map_id=0x01, ptr=0x8000,
                           direction="up"))
    observer.observe(state(100, 100, frame=5 + TIMEOUT, map_id=0x01,
                           ptr=0x8000, direction="up"))
    assert repo.blocked(MAP_ID, MAP_PTR) == []
    assert len(repo.transitions()) == 1


# --- 11.8 戦闘中 -------------------------------------------------------


def test_nothing_is_recorded_during_battle(obs):
    observer, repo = obs
    observer.observe(state(10, 5, battle=True))
    observer.observe(state(11, 5, frame=10, battle=True))
    assert repo.counts() == {"edges": 0, "blocked": 0, "transitions": 0,
                             "notes": 0, "landmarks": 0}


def test_battle_does_not_create_a_phantom_edge(obs):
    """★★ 戦闘の前後をつないで「通れた」と誤解しないこと。

    戦闘に入る前 (10,5) → 戦闘 → 戻ったら (10,5) のまま。
    途中を挟んだ座標を隣接扱いしてはいけない。
    """
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    observer.observe(state(10, 5, frame=10, battle=True))
    observer.observe(state(11, 5, frame=100))          # 戦闘後の最初の観測
    assert repo.edges(MAP_ID, MAP_PTR) == [], "戦闘をまたいで道を作った"


# --- 11.10 入力後に戦闘開始 --------------------------------------------


def test_battle_after_input_is_not_blocked(obs):
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    observer.observe(state(10, 5, frame=1, direction="up"))
    observer.observe(state(10, 5, frame=5, direction="up", battle=True))
    observer.observe(state(10, 5, frame=200, direction="up"))
    assert repo.blocked(MAP_ID, MAP_PTR) == [], "戦闘を壁として記録した"


# --- 11.9 state 欠損 --------------------------------------------------


@pytest.mark.parametrize("kw", [
    {"map_id": None}, {"ptr": None}, {"fresh": False},
    {"ptr": 0}, {"ptr": 0x7FFF}, {"ptr": 0xC000},
])
def test_incomplete_state_is_not_recorded(obs, kw):
    observer, repo = obs
    observer.observe(state(10, 5, **kw))
    observer.observe(state(11, 5, frame=10, **kw))
    assert repo.counts() == {"edges": 0, "blocked": 0, "transitions": 0,
                             "notes": 0, "landmarks": 0}


def test_missing_coordinates_are_not_recorded(obs):
    observer, repo = obs
    s = state(10, 5)
    s.map_x = None
    observer.observe(s)
    observer.observe(state(11, 5, frame=10))
    assert repo.edges(MAP_ID, MAP_PTR) == []


def test_zero_is_a_valid_coordinate(obs):
    """⚠★ (0,0) は正しい座標。`None` と混ぜない。"""
    observer, repo = obs
    observer.observe(state(0, 0, frame=0))
    got = observer.observe(state(1, 0, frame=10))
    assert got.moved
    rows = repo.edges(MAP_ID, MAP_PTR)
    assert (rows[0]["from_x"], rows[0]["from_y"]) == (0, 0)


def test_state_gap_does_not_link_far_places(obs):
    """★状態が読めない期間を挟んだら、その前後をつながない。"""
    observer, repo = obs
    observer.observe(state(10, 5, frame=0))
    observer.observe(GameState(fresh=False))            # 読めない
    observer.observe(state(11, 5, frame=10))
    assert repo.edges(MAP_ID, MAP_PTR) == []


# --- 11.11 DB 障害 -----------------------------------------------------


def test_database_failure_does_not_stop_anything(obs, monkeypatch, caplog):
    observer, repo = obs

    def boom(*_a, **_k):
        raise RuntimeError("DB が壊れた")

    monkeypatch.setattr(repo, "record_edge", boom)
    observer.observe(state(10, 5, frame=0))
    got = observer.observe(state(11, 5, frame=10))      # ここで落ちない
    assert got.skipped == "error"
    # ★以後も呼び続けて落ちない
    for f in range(20, 100, 10):
        observer.observe(state(11, 5, frame=f))


def test_warning_is_logged_only_once(obs, monkeypatch):
    """★毎フレーム同じ警告を出さない（読まれない通知にしない）。"""
    observer, repo = obs
    calls = []

    class Log:
        def warning(self, *a, **k):
            calls.append(a)

        def info(self, *a, **k):
            pass

    observer.log = Log()
    monkeypatch.setattr(repo, "record_edge",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    for i in range(5):
        observer.observe(state(10, 5, frame=i * 100))
        observer.observe(state(11, 5, frame=i * 100 + 10))
    assert len(calls) == 1, f"{len(calls)} 回警告を出した"


# --- 設定で止められる --------------------------------------------------


def test_recording_can_be_turned_off(tmp_path):
    db = Database(tmp_path / "off.sqlite3")
    db.register_rom(HASH, "t", "JP", mapper=2)
    repo = NavigationRepository(db, HASH)
    observer = NavigationObserver(repo, record_edges=False,
                                  record_blocked=False,
                                  record_transitions=False,
                                  move_timeout_frames=TIMEOUT)
    try:
        walk(observer, 10, 5, 11, 5)
        observer.observe(state(11, 5, frame=100))
        observer.observe(state(11, 5, frame=101, direction="up"))
        observer.observe(state(11, 5, frame=101 + TIMEOUT, direction="up"))
        observer.observe(state(1, 1, frame=500, map_id=0x01, ptr=0x8000))
        assert repo.counts() == {"edges": 0, "blocked": 0, "transitions": 0,
                             "notes": 0, "landmarks": 0}
    finally:
        db.close()


# --- 受け入れ条件1: 毎フレームの座標を保存しない -----------------------


def test_frame_by_frame_positions_are_not_stored(obs):
    """★★ 受け入れ条件1（指示書 12章）★★

    同じ所に留まっている 500 フレームぶん観測しても、DB は空のまま。
    """
    observer, repo = obs
    for f in range(500):
        observer.observe(state(10, 5, frame=f))
    assert repo.counts() == {"edges": 0, "blocked": 0, "transitions": 0,
                             "notes": 0, "landmarks": 0}


def test_long_walk_grows_only_by_new_paths(obs):
    """★★ 受け入れ条件3: 行数が増え続けないこと。

    同じ10マスの廊下を往復20回歩く -> 行は**片道ぶんの10本だけ**。
    """
    observer, repo = obs
    frame = 0
    for _ in range(20):
        for x in range(10):
            observer.observe(state(x, 5, frame=frame))
            frame += 10
            observer.observe(state(x + 1, 5, frame=frame))
            frame += 10
        observer.observe(GameState(fresh=False))        # 折り返しで切る
    assert len(repo.edges(MAP_ID, MAP_PTR)) == 10
    assert sum(r["success_count"] for r in repo.edges(MAP_ID, MAP_PTR)) == 200

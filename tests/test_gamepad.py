"""ゲームパッドの立ち上がり検出（RX-0076 / 2026-08-19）。

★★ **ハードウェアを使わずに確かめる。** ★★
  `GamepadRouter` は純ロジックなので、偽の `PadState` を流すだけで
  全ての割り当てと「立ち上がりだけ発火」を試せる。

⚠ ここで守りたいのは**押しっぱなしで連打しない**こと。まんたんを保持で
  連発するとやくそうを使い切る（教訓: 書き手が2人のときと同じ立ち上がり）。
"""

from __future__ import annotations

from retroux.application.gamepad import (
    BTN_A, BTN_B, BTN_BACK, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT,
    BTN_DPAD_UP, BTN_LB, BTN_RB, BTN_START, BTN_X, BTN_Y, EVENT_LOAD,
    EVENT_MANTAN, EVENT_SAVE, EVENT_TALK, EVENT_TOGGLE_AUTO, EVENT_TOGGLE_TURBO,
    NES_A, NES_B, NES_DOWN, NES_LEFT, NES_RIGHT, NES_SELECT, NES_START, NES_UP,
    THUMB_DEADZONE, GamepadRouter, PadState, XInputReader, nes_mask,
)


def _pad(buttons: int = 0, lt: int = 0, rt: int = 0) -> PadState:
    return PadState(connected=True, buttons=buttons,
                    left_trigger=lt, right_trigger=rt)


# --- 割り当て ----------------------------------------------------------

def test_each_button_maps_to_its_action():
    r = GamepadRouter()
    assert r.poll(_pad(BTN_LB)) == [EVENT_LOAD]
    assert r.poll(_pad()) == []                 # 一旦離す
    assert r.poll(_pad(BTN_RB)) == [EVENT_SAVE]
    assert r.poll(_pad()) == []
    assert r.poll(_pad(BTN_X)) == [EVENT_TALK]
    assert r.poll(_pad()) == []
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]


def test_triggers_map_to_the_toggles():
    r = GamepadRouter()
    assert r.poll(_pad(lt=255)) == [EVENT_TOGGLE_AUTO]
    assert r.poll(_pad()) == []
    assert r.poll(_pad(rt=255)) == [EVENT_TOGGLE_TURBO]


# --- 立ち上がりだけ ----------------------------------------------------

def test_a_held_button_fires_only_once():
    """★★ 押しっぱなしで連打しない ★★"""
    r = GamepadRouter()
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]
    assert r.poll(_pad(BTN_Y)) == []           # 保持中は無反応
    assert r.poll(_pad(BTN_Y)) == []


def test_release_then_press_fires_again():
    r = GamepadRouter()
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]
    assert r.poll(_pad()) == []                 # 離す
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]  # もう一度押す→また出る


def test_a_trigger_below_the_threshold_does_not_fire():
    """⚠ 軽く触れただけ（アナログの遊び）では効かせない。"""
    r = GamepadRouter()                          # press=100 / release=40
    assert r.poll(_pad(lt=10)) == []            # 閾値以下
    assert r.poll(_pad(lt=200)) == [EVENT_TOGGLE_AUTO]  # 踏み込む→発火
    assert r.poll(_pad(lt=200)) == []           # 踏みっぱなしは無反応
    assert r.poll(_pad(lt=5)) == []             # 戻す
    assert r.poll(_pad(lt=200)) == [EVENT_TOGGLE_AUTO]  # また踏む→発火


def test_trigger_hysteresis_prevents_chatter():
    """★★ しきい値付近の揺れで連発しない（実機で Auto/Turbo が連発した対策）。"""
    r = GamepadRouter()                          # press=100 / release=40
    assert r.poll(_pad(lt=120)) == [EVENT_TOGGLE_AUTO]   # 踏み込む→1回だけ
    # ★押し〜離しの間（40〜100）で値が揺れても、押しっぱなし扱い＝再発火しない
    for v in (90, 60, 80, 45, 70, 99):
        assert r.poll(_pad(lt=v)) == []
    assert r.poll(_pad(lt=30)) == []            # 40 未満まで戻す→離す（発火なし）
    assert r.poll(_pad(lt=120)) == [EVENT_TOGGLE_AUTO]   # もう一度踏む→発火


# --- 抜き差し ----------------------------------------------------------

def test_disconnect_clears_and_reconnect_with_held_fires_once():
    """⚠ 抜き差しで押しっぱなしが暴発しないこと。"""
    r = GamepadRouter()
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]
    assert r.poll(None) == []                   # 抜けた（未接続）
    # 押したまま繋ぎ直したら、そこで1回だけ立ち上がる
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]


def test_an_unconnected_state_object_is_treated_as_released():
    r = GamepadRouter()
    assert r.poll(_pad(BTN_Y)) == [EVENT_MANTAN]
    assert r.poll(PadState(connected=False, buttons=BTN_Y)) == []


# --- 巻き込まないもの --------------------------------------------------

def test_nes_buttons_are_ignored():
    """★A・B・十字は FCEUX が読む。ここでは**何もしない**。"""
    r = GamepadRouter()
    # A=0x1000, B=0x2000, 十字=0x01..0x08, Start=0x10, Back=0x20
    for bits in (0x1000, 0x2000, 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020):
        assert r.poll(_pad(bits)) == []
        r.poll(_pad())                          # 離しておく


def test_simultaneous_presses_come_out_in_a_stable_order():
    r = GamepadRouter()
    fired = r.poll(_pad(BTN_LB | BTN_RB | BTN_X | BTN_Y, lt=255, rt=255))
    assert fired == [EVENT_LOAD, EVENT_SAVE, EVENT_TALK, EVENT_MANTAN,
                     EVENT_TOGGLE_AUTO, EVENT_TOGGLE_TURBO]


# --- NES ボタンのビットマスク（十字/A/B/Start/Select）----------------------
#
# ★これは**レベル**（押している間ずっと）。方向は保持で歩き続けるため、
#   立ち上がりにはしない（独自機能ボタンだけが立ち上がり）。

def _pad2(buttons=0, lx=0, ly=0):
    return PadState(connected=True, buttons=buttons, thumb_lx=lx, thumb_ly=ly)


def test_the_dpad_maps_to_nes_directions():
    assert nes_mask(_pad2(BTN_DPAD_UP)) == NES_UP
    assert nes_mask(_pad2(BTN_DPAD_DOWN)) == NES_DOWN
    assert nes_mask(_pad2(BTN_DPAD_LEFT)) == NES_LEFT
    assert nes_mask(_pad2(BTN_DPAD_RIGHT)) == NES_RIGHT


def test_face_buttons_map_to_nes():
    assert nes_mask(_pad2(BTN_A)) == NES_A
    assert nes_mask(_pad2(BTN_B)) == NES_B
    assert nes_mask(_pad2(BTN_START)) == NES_START
    assert nes_mask(_pad2(BTN_BACK)) == NES_SELECT     # ★Back → Select


def test_the_left_stick_also_moves():
    """★十字だけでなく左スティックでも歩ける（Y は上が +）。"""
    assert nes_mask(_pad2(ly=30000)) == NES_UP
    assert nes_mask(_pad2(ly=-30000)) == NES_DOWN
    assert nes_mask(_pad2(lx=-30000)) == NES_LEFT
    assert nes_mask(_pad2(lx=30000)) == NES_RIGHT


def test_the_stick_deadzone_is_respected():
    """⚠ 遊びの範囲（軽い傾き）では歩かない。"""
    assert nes_mask(_pad2(lx=THUMB_DEADZONE - 1, ly=THUMB_DEADZONE - 1)) == 0


def test_dpad_and_face_buttons_combine():
    m = nes_mask(_pad2(BTN_DPAD_UP | BTN_A))
    assert m == (NES_UP | NES_A)


def test_dpad_and_stick_do_not_double_count():
    """★十字と左スティックが同じ向きでも二重にならない（OR）。"""
    assert nes_mask(_pad2(BTN_DPAD_RIGHT, lx=30000)) == NES_RIGHT


def test_a_disconnected_pad_is_all_zero():
    assert nes_mask(None) == 0
    assert nes_mask(PadState(connected=False, buttons=BTN_A)) == 0


# --- 読み取りの頑丈さ（一時的失敗で連発しない）--------------------------

def test_reader_holds_last_state_on_transient_failure():
    """★★ 1回の読み取り失敗で slot を捨てない（前回値を返す）★★

    ⚠ 捨てて None を返すと、ルータの立ち上がり判定がリセットされ、
      押しっぱなしのボタンが**再発火**する（実機で LB のロードが連発）。
    """
    r = XInputReader()
    r._dll = object()                      # ★DLL 有りとみなす（read が進む）
    r._slot = 0
    good = PadState(connected=True, buttons=BTN_A)
    seq = [good, None, None, good, None]
    r._read_slot = lambda idx: seq.pop(0) if seq else None

    assert r.read().pressed(BTN_A)         # 正常
    assert r.read().pressed(BTN_A)         # 失敗→前回値（押しっぱなし維持）
    assert r.read().pressed(BTN_A)         # 失敗→前回値
    assert r.read().pressed(BTN_A)         # また正常
    assert r.read().pressed(BTN_A)         # 失敗→前回値


def test_reader_gives_up_after_sustained_failure():
    """★連続失敗が続けば「抜けた」とみなして手放す（無限に前回値を返さない）。"""
    r = XInputReader()
    r._dll = object()
    r._slot = 0
    r._last = PadState(connected=True, buttons=BTN_A)
    r._read_slot = lambda idx: None        # ずっと失敗
    # ★FAIL_LIMIT 回までは前回値、その後は総なめ（全部失敗なので None）
    results = [r.read() for _ in range(r._FAIL_LIMIT + r._RESCAN_EVERY + 2)]
    assert results[0] is not None          # 最初は前回値
    assert results[-1] is None             # 十分続けば手放す

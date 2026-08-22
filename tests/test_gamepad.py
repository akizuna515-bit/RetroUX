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
    BTN_RIGHT_THUMB, RIGHT_THUMB_DEADZONE, MouseButton, mouse_velocity,
    should_write_pad,
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


def test_swap_ab_follows_the_famicom_layout():
    """★ファミコン準拠: XBOX B → NES A（決定＝右）、XBOX A → NES B。"""
    assert nes_mask(_pad2(BTN_A), swap_ab=True) == NES_B
    assert nes_mask(_pad2(BTN_B), swap_ab=True) == NES_A
    # ★swap 無し（XBOX 標準）は従来どおり
    assert nes_mask(_pad2(BTN_A), swap_ab=False) == NES_A
    assert nes_mask(_pad2(BTN_B), swap_ab=False) == NES_B
    # ⚠ 方向や Start/Select は swap の影響を受けない
    assert nes_mask(_pad2(BTN_START), swap_ab=True) == NES_START


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


# --- アイドル中の書き込み間引き（音もたつき対策 / RX-0083）-------------

def _run_writes(masks, heartbeat=30):
    """マスク列を流し、実際に書いた回数と、書いた各フレームを返す。"""
    last, idle, wrote_frames = -1, 0, []
    for i, m in enumerate(masks):
        write, idle = should_write_pad(m, last, idle, heartbeat)
        if write:
            wrote_frames.append(i)
        last = m
    return wrote_frames


def test_押しっぱなしは毎フレーム書く():
    """★mask!=0 の間は毎フレーム書く（seq を進めないと hold が切れる）。"""
    frames = _run_writes([NES_RIGHT] * 100)
    assert frames == list(range(100)), "押下中は間引いてはいけない"


def test_アイドルは間引くがハートビートは残す():
    """★mask==0 が続くあいだは heartbeat 周期でだけ書く。"""
    frames = _run_writes([0] * 100, heartbeat=30)
    # 0フレーム目: last=-1 と違うので書く。以後は 30 ごと。
    assert frames == [0, 30, 60, 90], frames


def test_変化した瞬間は必ず書く():
    """★離した/押した瞬間は 1 フレームで反映する（遅延させない）。"""
    seq = [0] * 5 + [NES_RIGHT] + [0] * 5
    frames = _run_writes(seq, heartbeat=30)
    assert 5 in frames, "押した瞬間を書いていない"
    assert 6 in frames, "離した瞬間を書いていない"


def test_アイドルの書き込みが大幅に減る():
    """★放置1000フレームで、60Hz全書き込みから heartbeat 相当まで減る。"""
    frames = _run_writes([0] * 1000, heartbeat=30)
    assert len(frames) <= 1000 // 30 + 2, len(frames)
    assert len(frames) < 40, "間引きが効いていない"


# --- 右スティック＝マウス（RX-0084）------------------------------------

def _pad3(buttons=0, rx=0, ry=0):
    return PadState(connected=True, buttons=buttons, thumb_rx=rx, thumb_ry=ry)


def test_マウスは遊びの範囲では動かない():
    assert mouse_velocity(_pad3(rx=RIGHT_THUMB_DEADZONE - 1,
                                ry=RIGHT_THUMB_DEADZONE - 1)) == (0.0, 0.0)


def test_マウスのYは画面座標に反転する():
    """★XInput は上が+、画面は下が+。上に倒したら dy は負（上へ動く）。"""
    dx, dy = mouse_velocity(_pad3(ry=32767), max_speed=10.0)
    assert dx == 0.0 and dy < 0
    dx, dy = mouse_velocity(_pad3(ry=-32768), max_speed=10.0)
    assert dy > 0


def test_マウスは倒すほど速い_2乗カーブ():
    small = abs(mouse_velocity(_pad3(rx=15000), max_speed=10.0)[0])
    big = abs(mouse_velocity(_pad3(rx=32767), max_speed=10.0)[0])
    assert 0 < small < big <= 10.0
    # ★2乗カーブ: 半分の倒しは最高速の半分よりずっと遅い（細かい操作用）
    half = abs(mouse_velocity(
        _pad3(rx=(RIGHT_THUMB_DEADZONE + 32767) // 2), max_speed=10.0)[0])
    assert half < 5.0


def test_マウスは未接続なら動かない():
    assert mouse_velocity(None) == (0.0, 0.0)
    assert mouse_velocity(PadState(connected=False, thumb_rx=32767)) == (0.0, 0.0)


def test_R3で左ボタンのdownとupが出る():
    b = MouseButton()
    assert b.poll(_pad3()) is None                       # 押していない
    assert b.poll(_pad3(BTN_RIGHT_THUMB)) == "down"      # 押した瞬間
    assert b.poll(_pad3(BTN_RIGHT_THUMB)) is None        # 押しっぱなしは無反応
    assert b.poll(_pad3()) == "up"                       # 離した瞬間
    assert b.poll(_pad3()) is None


def test_R3押下中に切断したら強制up():
    """⚠ 左ボタンが刺さるとマウス全体が使えなくなる。"""
    b = MouseButton()
    assert b.poll(_pad3(BTN_RIGHT_THUMB)) == "down"
    assert b.poll(None) == "up"                          # 抜けた → 解放
    assert b.poll(None) is None


# --- 開きっぱなしで書く（RX-0097 / 2026-08-22）--------------------------------
#
# ⚠ 以前は毎回 write_text（開く→切り詰める→書く→閉じる）で **1,098 µs/回**だった。
#   ★開き直す代金がほとんど。ハンドルを持ち回すと 64 µs（17 分の 1）。
# ⚠⚠ 切り詰めないので **長さを固定**しないと前の行の残りが後ろに残る
#   （`123 24` の上に `4 0` を書くと `4 024` になる）。

class _FakeWindow:
    """`_write_gamepad_nes` / `_close_gamepad_out` だけを借りる入れ物。"""

    from retroux.ui.main_window import MainWindow as _MW
    _write_gamepad_nes = _MW._write_gamepad_nes
    _close_gamepad_out = _MW._close_gamepad_out

    def __init__(self, path):
        self._gamepad_input_path = path
        self._gamepad_seq = 0
        self._gamepad_out = None
        self._GAMEPAD_LINE_WIDTH = 24


def _read(path):
    return path.read_text(encoding="ascii")


def test_書き込みは開いたまま行われる(tmp_path, monkeypatch):
    path = tmp_path / "gamepad_input.txt"
    win = _FakeWindow(path)
    import builtins
    opens = {"n": 0}
    real_open = builtins.open

    def counting(file, *a, **kw):
        if str(file) == str(path):
            opens["n"] += 1
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", counting)
    for mask in (8, 24, 0, 128):
        win._write_gamepad_nes(mask)
    assert opens["n"] == 1, "★2回目以降は開き直さない"
    win._close_gamepad_out()


def test_短い行でも前の残りが混ざらない(tmp_path):
    path = tmp_path / "gamepad_input.txt"
    win = _FakeWindow(path)
    win._write_gamepad_nes(128)          # "1 128" + 空白
    win._write_gamepad_nes(1)            # "2 1"   + 空白（★短くなる）
    body = _read(path)
    seq, mask = body.split()[:2]
    assert (seq, mask) == ("2", "1"), f"⚠ 前の 128 の残りを拾っている: {body!r}"
    assert len(body) == win._GAMEPAD_LINE_WIDTH, "★長さは固定"
    win._close_gamepad_out()


def test_閉じたあとも書ける(tmp_path):
    """★終了時に閉じたあと、また書かれても開き直して続く。"""
    path = tmp_path / "gamepad_input.txt"
    win = _FakeWindow(path)
    win._write_gamepad_nes(4)
    win._close_gamepad_out()
    assert win._gamepad_out is None
    win._write_gamepad_nes(2)
    assert _read(path).split()[1] == "2"
    win._close_gamepad_out()


def test_書けなくても止まらない(tmp_path):
    """⚠ 書けない状況でも例外を出さない（次の tick で開き直す）。"""
    win = _FakeWindow(tmp_path / "no_such_dir" / "x" / "gamepad_input.txt")
    win._write_gamepad_nes(8)            # ★例外にならないこと
    win._close_gamepad_out()


def test_閉じるのは何回呼んでも安全(tmp_path):
    win = _FakeWindow(tmp_path / "gamepad_input.txt")
    win._write_gamepad_nes(1)
    win._close_gamepad_out()
    win._close_gamepad_out()             # ★2回目も落ちない


# --- X 長押し = 強制AUTO ＋ 一時ターボ（RX-0082 / 2026-08-22）------------------
#
# ★指示書 260822_AHK §6〜§9。**押している間だけ**（トグルではない）。
# ⚠ 解除漏れが一番危ないので、離す以外の道（戦闘終了・切断・戦闘外）も全部見る。

from retroux.application.gamepad import (          # noqa: E402
    EVENT_FORCE_AUTO_BEGIN, EVENT_FORCE_AUTO_END, HoldRouter,
)


def _x(down=True):
    return PadState(connected=True, buttons=(BTN_X if down else 0))


def test_短押しでは強制AUTOに入らない():
    r = HoldRouter(hold_ms=500)
    assert r.poll(_x(), in_battle=True, now=0.0) == []
    assert r.poll(_x(), in_battle=True, now=0.3) == []      # ★0.3 秒はまだ
    assert r.poll(_x(False), in_battle=True, now=0.31) == []
    assert not r.active


def test_長押しで入り離すと出る():
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=True, now=0.0)
    assert r.poll(_x(), in_battle=True, now=0.4) == []
    assert r.poll(_x(), in_battle=True, now=0.5) == [EVENT_FORCE_AUTO_BEGIN]
    assert r.active
    # ★押し続けても**1回だけ**（連発しない）
    assert r.poll(_x(), in_battle=True, now=1.0) == []
    assert r.poll(_x(False), in_battle=True, now=1.2) == [EVENT_FORCE_AUTO_END]
    assert not r.active


def test_戦闘中のXは短押しを出さない():
    """⚠ 長押しに使うので、戦闘中は「はなす」を出さない（指示書 §9）。"""
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=True, now=0.0)
    assert r.suppress_talk() is True
    r.poll(_x(False), in_battle=True, now=0.2)
    assert r.suppress_talk() is False


def test_戦闘外では長押しにならない():
    """★非戦闘時の X は従来どおり（はなす）。⚠ 抑止もしない。"""
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=False, now=0.0)
    assert r.suppress_talk() is False
    assert r.poll(_x(), in_battle=False, now=2.0) == []
    assert not r.active


def test_戦闘が終わったら押したままでも解除する():
    """⚠⚠ 解除漏れの本命（指示書 §18）。"""
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=True, now=0.0)
    assert r.poll(_x(), in_battle=True, now=0.6) == [EVENT_FORCE_AUTO_BEGIN]
    # ★X は押したまま、戦闘だけ終わる
    assert r.poll(_x(), in_battle=False, now=0.7) == [EVENT_FORCE_AUTO_END]
    assert not r.active


def test_パッドが抜けたら解除する():
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=True, now=0.0)
    r.poll(_x(), in_battle=True, now=0.6)
    assert r.poll(None, in_battle=True, now=0.7) == [EVENT_FORCE_AUTO_END]
    assert not r.active


def test_解除は1回だけ出る():
    """⚠ 毎回 END を出すと、離したあとずっと解除を送り続けることになる。"""
    r = HoldRouter(hold_ms=500)
    r.poll(_x(), in_battle=True, now=0.0)
    r.poll(_x(), in_battle=True, now=0.6)
    assert r.poll(_x(False), in_battle=True, now=0.7) == [EVENT_FORCE_AUTO_END]
    assert r.poll(_x(False), in_battle=True, now=0.8) == []
    assert r.poll(None, in_battle=True, now=0.9) == []


def test_閾値は設定から変えられる():
    r = HoldRouter(hold_ms=200)
    r.poll(_x(), in_battle=True, now=0.0)
    assert r.poll(_x(), in_battle=True, now=0.2) == [EVENT_FORCE_AUTO_BEGIN]

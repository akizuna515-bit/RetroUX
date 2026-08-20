"""XBOX ゲームパッド（XInput）を読み、RetroUX の機能へ橋渡しする。

★★ **なぜ Python 側で読むのか** ★★

  NES のボタン（十字・A・B・Start・Select）は **FCEUX 本体**がパッドから
  直接読む（Config→Input の割当）。それが唯一のリアルタイム経路で、人の
  物理入力はブリッジが `HANDS_OFF` で素通しするので自動プレイとも両立する。

  一方 **LB / RB / LT / RT / X / Y は NES のボタンではない**ので FCEUX の
  `joypad.get` では取れない。これらは RetroUX 固有の機能（ロード・セーブ・
  Auto・Turbo・どうぐや/ふくびき・まんたん）に割り当てたい。だから
  **RetroUX 側でパッドを読む**。XInput は Windows 同梱（`xinput1_4`）で、
  XBOX パッドはネイティブ対応。★依存を増やさない。

## 2つの役割を分ける

    XInputReader   … ハードウェアを読む（Windows/ctypes 依存）
    GamepadRouter  … 読んだ状態を「立ち上がりの操作」に変える（純ロジック）

  ★ルータは画面もハードも知らないので、偽の状態を流すだけで試せる
    （`tests/test_gamepad.py`）。⚠ ここに Qt や ctypes を持ち込まないこと。

## 立ち上がりだけを見る

  ⚠ 押しっぱなしの間ずっと発火すると、まんたんを連打してやくそうを
    使い切る。**押した瞬間（false→true）だけ**を操作にする。
    （教訓: 書き手が2人のときと同じ「立ち上がり」で見る）
"""

from __future__ import annotations

import dataclasses

# --- XInput の定数（Microsoft の xinput.h より）------------------------

#: wButtons のビット。★NES ボタンは FCEUX が読むので、ここでは扱わない。
BTN_LB = 0x0100          # 左ショルダー → ロード
BTN_RB = 0x0200          # 右ショルダー → セーブ
BTN_X = 0x4000           # X → どうぐや/ふくびき（キーボード R と同じ）
BTN_Y = 0x8000           # Y → まんたん（キーボード M と同じ）

#: NES ボタン（十字・A・B・Start・Select）の wButtons ビット。
#  ★これらは FCEUX ではなく RetroUX が読み、bridge へ「毎フレームの状態」を渡す
#    （依頼者 2026-08-19: パッド割当を FCEUX で設定させず「挿すだけ」にする）。
BTN_DPAD_UP = 0x0001
BTN_DPAD_DOWN = 0x0002
BTN_DPAD_LEFT = 0x0004
BTN_DPAD_RIGHT = 0x0008
BTN_START = 0x0010
BTN_BACK = 0x0020        # ★XBOX の Back/View → NES の Select
BTN_A = 0x1000           # ★XBOX A → NES A
BTN_B = 0x2000           # ★XBOX B → NES B

#: トリガは 0〜255 のアナログ。★★ ヒステリシスで見る（RX-0076 実機）★★
#  「押した」は高いしきい値、「離した」は低いしきい値。しきい値付近で値が
#  揺れても ON/OFF を繰り返さない（実機で Auto/Turbo が連発したため）。
TRIGGER_PRESS = 100      # これを超えたら「押した」
TRIGGER_RELEASE = 40     # これを下回ったら「離した」（間は前の状態を保つ）
#: 後方互換の別名（旧: 単一しきい値）。
TRIGGER_THRESHOLD = TRIGGER_PRESS

#: 左スティックの遊び（この範囲は倒していない扱い）。
#  ★Microsoft の既定（XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE 相当）。
THUMB_DEADZONE = 8000

#: 右スティック（マウス移動 / RX-0084）。押し込み＝R3。
BTN_RIGHT_THUMB = 0x0080
#: 右スティックの遊び。★Microsoft の既定
#  （XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = 8689。左より少し広い）。
RIGHT_THUMB_DEADZONE = 8689

#: bridge へ渡す NES 状態のビット（★RetroUX と bridge.lua で合わせる）。
NES_UP = 0x01
NES_DOWN = 0x02
NES_LEFT = 0x04
NES_RIGHT = 0x08
NES_A = 0x10
NES_B = 0x20
NES_START = 0x40
NES_SELECT = 0x80

#: XInputGetState の戻り値。0 が成功、1167 が「パッドが繋がっていない」。
_ERROR_SUCCESS = 0
_ERROR_DEVICE_NOT_CONNECTED = 1167

#: 接続を探すスロット数（XInput は最大4台）。
_MAX_SLOTS = 4

#: 立ち上がりで発火する操作の名前。★画面側がこれを実際の処理へ結ぶ。
EVENT_LOAD = "load"
EVENT_SAVE = "save"
EVENT_TOGGLE_AUTO = "toggle_auto"
EVENT_TOGGLE_TURBO = "toggle_turbo"
EVENT_TALK = "talk"
EVENT_MANTAN = "mantan"


@dataclasses.dataclass(frozen=True)
class PadState:
    """1回分のパッドの読み取り（★接続していないときは connected=False）。"""

    connected: bool = False
    buttons: int = 0             # wButtons のビット並び
    left_trigger: int = 0        # 0〜255
    right_trigger: int = 0       # 0〜255
    thumb_lx: int = 0            # 左スティック X（-32768〜32767）
    thumb_ly: int = 0            # 左スティック Y（-32768〜32767。上が +）
    thumb_rx: int = 0            # 右スティック X（マウス移動 / RX-0084）
    thumb_ry: int = 0            # 右スティック Y（上が +）

    def pressed(self, bit: int) -> bool:
        return bool(self.buttons & bit)


def nes_mask(state: PadState | None,
             deadzone: int = THUMB_DEADZONE,
             swap_ab: bool = False) -> int:
    """パッドの状態を NES ボタンのビットマスクに変える（★純ロジック）。

    ★十字と左スティックの**両方**を方向に使う（どちらでも歩ける）。
    ⚠ レベル（押している間ずっと）で見る。方向は保持で歩き続けるため、
      ここは立ち上がりにしない（立ち上がりは独自機能ボタンだけ）。
    ★swap_ab=True で A/B を入れ替える（ファミコン準拠: XBOX B→NES A / A→NES B）。
    """
    if state is None or not state.connected:
        return 0
    mask = 0
    # ★A/B の割り当て（swap_ab でファミコン並びに）
    a_out, b_out = (NES_B, NES_A) if swap_ab else (NES_A, NES_B)
    # ★方向: 十字 OR 左スティック（倒し）
    if state.pressed(BTN_DPAD_UP) or state.thumb_ly > deadzone:
        mask |= NES_UP
    if state.pressed(BTN_DPAD_DOWN) or state.thumb_ly < -deadzone:
        mask |= NES_DOWN
    if state.pressed(BTN_DPAD_LEFT) or state.thumb_lx < -deadzone:
        mask |= NES_LEFT
    if state.pressed(BTN_DPAD_RIGHT) or state.thumb_lx > deadzone:
        mask |= NES_RIGHT
    if state.pressed(BTN_A):
        mask |= a_out
    if state.pressed(BTN_B):
        mask |= b_out
    if state.pressed(BTN_START):
        mask |= NES_START
    if state.pressed(BTN_BACK):
        mask |= NES_SELECT
    return mask


def _axis_ratio(value: int, deadzone: int) -> float:
    """1軸の倒しを -1.0〜1.0 へ（遊びを引いてから正規化。★純ロジック）。"""
    mag = abs(value)
    if mag <= deadzone:
        return 0.0
    ratio = (mag - deadzone) / (32767.0 - deadzone)
    if ratio > 1.0:
        ratio = 1.0
    return ratio if value > 0 else -ratio


def mouse_velocity(state: PadState | None,
                   deadzone: int = RIGHT_THUMB_DEADZONE,
                   max_speed: float = 15.0) -> tuple[float, float]:
    """右スティックの倒しをカーソル速度 (dx, dy) px/tick へ（★純ロジック / RX-0084）。

    ★2乗カーブ: 少し倒すとゆっくり・いっぱい倒すと速い（細かい操作と
      大きな移動を1本のスティックで両立する。マウス代替の定石）。
    ⚠ Y は反転する（XInput は上が +、画面座標は下が +）。
    """
    if state is None or not state.connected:
        return (0.0, 0.0)
    rx = _axis_ratio(state.thumb_rx, deadzone)
    ry = _axis_ratio(state.thumb_ry, deadzone)
    # ★2乗カーブ（符号は保つ）
    return (rx * abs(rx) * max_speed, -ry * abs(ry) * max_speed)


class MouseButton:
    """R3（右スティック押し込み）→ マウス左ボタンの down/up（★純ロジック）。

    ★立ち上がりで "down"、立ち下がりで "up" を返す（押している間 None）。
      down と up を分けるので**ドラッグもできる**（押しながらスティックで移動）。
    ⚠ 切断（抜いた/読めない）は**強制 up**。押しっぱなしのままパッドが抜けると
      左ボタンが刺さり、マウス全体が使えなくなるため。
    """

    def __init__(self, bit: int = BTN_RIGHT_THUMB) -> None:
        self._bit = bit
        self._held = False

    def poll(self, state: PadState | None) -> str | None:
        pressed = (state is not None and state.connected
                   and state.pressed(self._bit))
        if pressed and not self._held:
            self._held = True
            return "down"
        if not pressed and self._held:
            self._held = False
            return "up"
        return None


def should_write_pad(mask: int, last_mask: int, idle_ticks: int,
                     heartbeat: int) -> tuple[bool, int]:
    """アイドル中の書き込みを間引く（★純ロジック / RX-0083）。

    RetroUX は `work/gamepad_input.txt` を 60Hz で書き、FCEUX 側は**毎フレーム**
    開いて読む。mask==0（何も押していない）まま毎フレーム書き換えると、
    Windows のファイルキャッシュ無効化とウイルス対策の再スキャンが
    エミュの読取りに乗り、放置中でも数秒おきに音がもたつく。

    そこで:
      - 押下中(mask != 0) または 変化時 … 毎フレーム書く（seq を進めて
        「押しっぱなし」の生存を示す。ここを止めると hold が途中で切れる）。
      - アイドル(mask==0 が継続) … `heartbeat` フレームに1回だけ書く。

    戻り値は `(書くか, 次の idle_ticks)`。
    """
    if mask != 0 or mask != last_mask:
        return True, 0
    idle_ticks += 1
    if idle_ticks >= heartbeat:
        return True, 0
    return False, idle_ticks


# --- 純ロジック: 状態 → 立ち上がりの操作 -------------------------------

class GamepadRouter:
    """パッドの状態を受け取り、**押した瞬間だけ**操作名を返す。

    ⚠ ここは Qt も ctypes も知らない。だからテストが偽の `PadState` を
      流すだけで、全ての割り当てを確かめられる。
    """

    #: 見張るボタンと、その立ち上がりで出す操作名。★順番は出力の順番。
    _BUTTON_EVENTS = (
        (BTN_LB, EVENT_LOAD),
        (BTN_RB, EVENT_SAVE),
        (BTN_X, EVENT_TALK),
        (BTN_Y, EVENT_MANTAN),
    )

    def __init__(self, trigger_press: int = TRIGGER_PRESS,
                 trigger_release: int = TRIGGER_RELEASE) -> None:
        self.trigger_press = int(trigger_press)
        self.trigger_release = int(trigger_release)
        #: 「前回押されていたか」。★これが無いと立ち上がりを見られない。
        self._down: dict[str, bool] = {}

    def _trigger_held(self, value: int, name: str) -> bool:
        """トリガをヒステリシスで二値化する（★連発を防ぐ）。

        ⚠ 押している間（前回 held）は低いしきい値まで下がらない限り離さない。
          離している間は高いしきい値を超えないと押さない。間は前の状態を保つ。
        """
        if self._down.get(name, False):
            return value > self.trigger_release
        return value > self.trigger_press

    def _held(self, state: PadState) -> dict[str, bool]:
        """いま押されている操作（トリガはヒステリシスで二値化）。"""
        held = {name: state.pressed(bit)
                for bit, name in self._BUTTON_EVENTS}
        held[EVENT_TOGGLE_AUTO] = self._trigger_held(
            state.left_trigger, EVENT_TOGGLE_AUTO)
        held[EVENT_TOGGLE_TURBO] = self._trigger_held(
            state.right_trigger, EVENT_TOGGLE_TURBO)
        return held

    def poll(self, state: PadState | None) -> list[str]:
        """状態を1回渡す。**新しく押された**操作の名前を順番に返す。

        ⚠ `state` が None（未接続）のときは「全部離した」とみなす。
          そうしておけば、抜き差ししても押しっぱなしが暴発しない
          （繋ぎ直して既に押していれば、そこで1回だけ立ち上がる）。
        """
        if state is None or not state.connected:
            self._down = {}
            return []

        held = self._held(state)
        fired: list[str] = []
        # ★出力の順番を安定させる（ボタン→トリガの順）。
        order = [name for _bit, name in self._BUTTON_EVENTS]
        order += [EVENT_TOGGLE_AUTO, EVENT_TOGGLE_TURBO]
        for name in order:
            now = held.get(name, False)
            if now and not self._down.get(name, False):
                fired.append(name)
        self._down = held
        return fired


# --- ハードウェア: XInput を読む（Windows/ctypes）----------------------

class XInputReader:
    """XInput でパッドを読む。★Windows 以外や DLL 不在では静かに休止する。

    ⚠ 未接続スロットを毎フレーム叩くと重い（Microsoft の注意）。
      だから接続が見つかるまでは**間引いて**探す。
    """

    #: 未接続のときに探し直す間隔（poll 呼び出しの回数）。
    #  ★33ms 周期なら約1秒に1回だけスロットを総なめする。
    _RESCAN_EVERY = 30
    #: 覚えているスロットが「これだけ連続で読めなかったら」抜けたとみなす。
    #  ⚠ 1回の一時的失敗で捨てると、その後 0.5 秒 None を返し続け、ルータの
    #    立ち上がり判定がリセットされてボタンが**再発火**する（実機で連発）。
    #    連続失敗で初めて手放す。単発の失敗は前回値を返して無視する。
    _FAIL_LIMIT = 30

    def __init__(self) -> None:
        self._dll = self._load_dll()
        self._state_type = None
        self._slot: int | None = None    # 最後に繋がっていたスロット
        self._since_scan = 0
        self._fail = 0                   # スロットの連続読み取り失敗数
        self._last: PadState | None = None   # 直近の正常な読み取り
        if self._dll is not None:
            self._state_type = _make_state_type()

    @staticmethod
    def _load_dll():
        """`xinput1_4`→`1_3`→`9_1_0` の順に試す。無ければ None。"""
        try:
            import ctypes
        except Exception:                              # noqa: BLE001
            return None
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:                             # ★Windows 以外
            return None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                return loader(name)
            except OSError:
                continue
        return None

    @property
    def available(self) -> bool:
        return self._dll is not None

    def _read_slot(self, index: int) -> PadState | None:
        """1スロット読む。繋がっていなければ None。"""
        state = self._state_type()
        rc = self._dll.XInputGetState(index, __import__("ctypes").byref(state))
        if rc != _ERROR_SUCCESS:
            return None
        pad = state.Gamepad
        return PadState(connected=True, buttons=pad.wButtons,
                        left_trigger=pad.bLeftTrigger,
                        right_trigger=pad.bRightTrigger,
                        thumb_lx=pad.sThumbLX, thumb_ly=pad.sThumbLY,
                        thumb_rx=pad.sThumbRX, thumb_ry=pad.sThumbRY)

    def read(self) -> PadState | None:
        """繋がっている最初のパッドを読む。無ければ None。

        ★一度見つけたスロットは覚えて、そこだけ読む（総なめしない）。
        """
        if self._dll is None:
            return None
        # ★覚えているスロットをまず読む
        if self._slot is not None:
            got = self._read_slot(self._slot)
            if got is not None:
                self._last = got
                self._fail = 0
                return got
            # ⚠ 一時的な読み取り失敗では slot を捨てない。前回値を返して
            #   ルータの立ち上がり判定をリセットしない（連発の防止）。
            self._fail += 1
            if self._fail < self._FAIL_LIMIT:
                return self._last
            self._slot = None                          # 連続失敗＝抜かれた
            self._fail = 0
            self._last = None

        # ★未接続のときは間引いて探す（毎フレームは重い）
        self._since_scan += 1
        if self._since_scan < self._RESCAN_EVERY:
            return None
        self._since_scan = 0
        for index in range(_MAX_SLOTS):
            got = self._read_slot(index)
            if got is not None:
                self._slot = index
                self._last = got
                self._fail = 0
                return got
        return None


def _make_state_type():
    """XINPUT_STATE の ctypes 型を作る（DLL が読めたときだけ呼ぶ）。"""
    import ctypes

    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [("wButtons", ctypes.c_ushort),
                    ("bLeftTrigger", ctypes.c_ubyte),
                    ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short),
                    ("sThumbLY", ctypes.c_short),
                    ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short)]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", ctypes.c_ulong),
                    ("Gamepad", XINPUT_GAMEPAD)]

    return XINPUT_STATE

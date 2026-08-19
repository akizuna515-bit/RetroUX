"""ゲームの状態を見分ける（2026-08-02 / マップ指示書 §6）。

★★ **静止して背景が落ち着いているときだけ地形を採る。** ★★

  ⚠ 移動中・メニュー中・暗転中の背景を地形として保存すると、
    何度も見て確かめた床や壁を1枚で塗りつぶしてしまう。

## 見分け方（すべて 2026-08-02 に日本版で実測）

    $0035  メニュー開閉フラグ   静止 00 / メニュー FF
    $0059  メニューID           静止 00 / コマンドメニュー 06
    $0005  横スクロール（画素）
    $0006  縦スクロール（画素）

★★ **静止中のスクロールは必ず 16 の倍数**（00 / 20 / 90 …）。
  移動中だけ 11・12 のような半端な値になる。
  ⚠ 別の番地に頼らずに「移動中か」を判定できるので、これを主に使う。

## 判定の順（指示書 §6.1）

    戦闘        -> BATTLE
    マップ切替  -> MAP_TRANSITION
    メニュー    -> FIELD_MENU
    メッセージ  -> FIELD_MESSAGE   ⚠ 番地が未特定。今は判定しない
    画素が動く  -> FIELD_MOVING
    落ち着き待ち-> FIELD_SETTLING
    背景が安定  -> FIELD_IDLE
    それ以外    -> UNKNOWN
"""

from __future__ import annotations

import dataclasses

BATTLE = "BATTLE"
MAP_TRANSITION = "MAP_TRANSITION"
FIELD_MENU = "FIELD_MENU"
FIELD_MESSAGE = "FIELD_MESSAGE"
FIELD_MOVING = "FIELD_MOVING"
FIELD_SETTLING = "FIELD_SETTLING"
FIELD_IDLE = "FIELD_IDLE"
UNKNOWN = "UNKNOWN"

#: ★静止中のスクロールはこの倍数になる（2026-08-02 実測）
SCROLL_ALIGNMENT = 16

#: ★背景ハッシュが何回続けて同じなら「落ち着いた」とみなすか（指示書 §6.2）
STABLE_SAMPLES = 3


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """1フレームぶんの様子。

    ⚠ 分からない項目は `None` にする。**0 と混ぜない。**
    """

    in_battle: bool = False
    menu_open: bool = False
    menu_id: int = 0
    scroll_x: int = 0
    scroll_y: int = 0
    #: 背景ハッシュが続けて同じだった回数
    stable: int = 0
    #: map_id / map_ptr がこのフレームで変わったか
    map_changed: bool = False
    #: 画面がほぼ真っ暗か
    dark: bool = False
    #: ⚠ メッセージ表示中。**番地が未特定**なので既定は None（不明）
    message_active: bool | None = None


def detect(snap: Snapshot) -> str:
    """いまの状態を返す（指示書 §6.1 の順）。"""
    if snap.in_battle:
        return BATTLE
    if snap.map_changed:
        return MAP_TRANSITION
    if snap.menu_open or snap.menu_id != 0:
        return FIELD_MENU
    # ⚠ メッセージは番地が未特定。**分かるときだけ**見る（推測で埋めない）
    if snap.message_active:
        return FIELD_MESSAGE
    if (snap.scroll_x % SCROLL_ALIGNMENT != 0
            or snap.scroll_y % SCROLL_ALIGNMENT != 0):
        return FIELD_MOVING
    if snap.stable < STABLE_SAMPLES:
        return FIELD_SETTLING
    return FIELD_IDLE


def may_capture(snap: Snapshot) -> bool:
    """いま地形として保存してよいか（指示書 §6.2）。

    ⚠⚠ **暗転中は採らない。** マップ切替・フェード・未描画で出るもので、
      地形として残すと既存の床や壁を黒で塗りつぶす（指示書 §11.2）。
    """
    if snap.dark:
        return False
    return detect(snap) == FIELD_IDLE


def why_not(snap: Snapshot) -> str | None:
    """採らなかった理由。★黙って捨てない（指示書 §11.2）。

    採ってよいときは `None`。
    """
    if snap.dark:
        return "black_or_transition"
    state = detect(snap)
    if state == FIELD_IDLE:
        return None
    return state.lower()

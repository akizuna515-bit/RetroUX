"""アクションと結果の型（2026-08-01 のリファクタ指示書 §6.3・§23）。

★★ **入口を1つにするための共通の形。** ★★

    GUIボタン ─┐
    キーボード ─┼→ ActionDispatcher → ActionResult
    ゲームパッド ┘      （将来）

⚠ ここは**画面も Windows API もファイルも知らない**。
  型と規約だけを置く（指示書 §14 の依存方向）。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

#: アクションが効く場面。★第一弾では**印**として持つだけ（切替は未実装）。
CONTEXTS = ("global", "gameplay", "map", "settings")


@dataclasses.dataclass(frozen=True)
class ActionResult:
    """アクションを実行した結果（指示書 §6.3）。

    ★★ **失敗したらゲームへフォーカスを戻さない。** ★★
      ⚠ 戻すと、出したエラーを**利用者が読む前に**画面が後ろへ回る。
        「押したのに何も起きない」という、いちばん困る形になる。

    `restore_focus` を明示すると、アクションの属性より優先される
    （例: ふだんは戻すが、この回だけ理由を読ませたい）。
    """

    success: bool
    message: str = ""
    restore_focus: bool | None = None

    @classmethod
    def ok(cls, message: str = "") -> "ActionResult":
        return cls(True, message)

    @classmethod
    def fail(cls, message: str) -> "ActionResult":
        # ⚠ 失敗時は**必ず**フォーカスを戻さない（上の解説）
        return cls(False, message, restore_focus=False)


@dataclasses.dataclass(frozen=True)
class ActionDefinition:
    """1つのアクションの定義。**処理そのものは持たない**。

    ★処理は `ActionDispatcher.register` で後から結び付ける。
      定義（何があるか）と実装（どう動くか）を分けると、
      ⚠ 画面が無い環境でも「アクション一覧」を検証できる。
    """

    name: str
    #: 人が読む名前（設定画面・エラー文に出す）
    label: str
    #: 実行後にゲームへフォーカスを返すか（指示書 §6.3）
    restore_emulator_focus: bool
    context: str = "global"
    #: この版で実際に動くか。⚠ **未実装を黙って並べない**
    implemented: bool = True

    def __post_init__(self) -> None:
        if self.context not in CONTEXTS:
            raise ValueError(f"知らない context です: {self.context}")


#: ★★ アクション一覧（指示書 §6.1・§23）★★
#
#   ⚠ ここに無い名前はキーバインド設定でも使えない（検証で弾く）。
#     「タイポで静かに無効になる」を防ぐため。
ACTIONS: tuple[ActionDefinition, ...] = (
    # --- 通常プレイ中の操作（実行後ゲームへ戻す）---------------------
    ActionDefinition("toggle_auto", "AUTO の入り切り", True, "gameplay"),
    ActionDefinition("toggle_turbo", "高速化の入り切り", True, "gameplay"),
    # ★「いますぐ手動へ」。危ないと感じたときに1キーで取り返す。
    ActionDefinition("emergency_manual", "すぐ手動へ戻す", True, "gameplay"),
    ActionDefinition("open_map", "地図を開く", True, "global"),
    ActionDefinition("toggle_map_follow", "地図の追従を切り替える", True, "map"),
    ActionDefinition("reset_layout", "標準レイアウトに戻す", True, "global"),
    ActionDefinition("focus_emulator", "ゲーム画面へ戻る", True, "global"),

    # --- 設定・編集（RetroUX 側に留まる）-----------------------------
    ActionDefinition("open_tactics_profile", "戦術プロフィールを開く",
                     False, "global"),
    ActionDefinition("open_settings", "設定を開く", False, "global",
                     # ⚠ 設定画面そのものは未実装。**名前だけ先に置かない**…
                     #   のだが、キーバインド設定から辿れるようにしたいので
                     #   定義は置き、実装が無いことを印で示す。
                     implemented=False),
    ActionDefinition("open_keybinding_settings", "キーバインド設定を開く",
                     False, "global"),
    ActionDefinition("show_lua_window", "Lua Script ウィンドウを出す",
                     False, "global"),
)

ACTION_BY_NAME = {a.name: a for a in ACTIONS}

#: アクションの実装。`ActionResult` を返しても、何も返さなくてもよい。
#  ★返さない場合は「成功」とみなす（既存の処理をそのまま繋げるため）。
Handler = Callable[..., Any]


def action_names() -> tuple[str, ...]:
    return tuple(a.name for a in ACTIONS)

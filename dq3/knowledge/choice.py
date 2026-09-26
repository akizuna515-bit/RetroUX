"""会話の選択肢に、⚠ **押してよいかを決める**（RX3-0121 / 2026-09-08）。

★調べた結果は `docs/research/dq3-conversation-choice-analysis.md`。
⚠ ここはその結論だけを持ちます（★根拠を書き写さない）。

## ⚠⚠ いちばん大事な結論

```text
⚠ 「通常 NPC はとりあえず全部はい」は**書いてはいけない**
```

★理由は 2 つあります。

```text
1 ふつうの情報 NPC（message 系）は、⚠ **そもそも選択肢を出さない**
  （$B4EA〜$B51B は「メッセージを出す」far call だけ）
2 選択肢を出すのは 施設 と event_script / special で、
  ⚠⚠ event_script は **何が起きるか未確認**（道具・お金・フラグ・戦闘・仲間）
```

→ ★自動で「はい」を押してよい相手は、⚠ **根拠付きでは 1 件もありません**。

> ⚠ 2026-09-12 追記（RX3-0194）: ★例外が **1 か所だけ**できました。王様（とイシスの女王）の
> 「また すぐに たびだつ つもりか？」（bank 13 `$BB9D`）は、⚠ いいえ / B で**ゲームが終わる**ため、
> `nav_v0.lua` が聞き込みの閉じる段に限って「はい」を 1 回押します（★`$BB9D` の見張り＋窓の字で決める）。
> ★この表（`decide()`）は変えていません（⚠ 製品では使っていない / 相手でなく処理の番地で決めるため）。
>
> ⚠ 2026-09-13 追記（RX3-0241）: ★もう 1 か所。宿屋への**街移動**では、泊まるかの問い（bank 13 `$A55C` /
> 宿屋の処理の はい／いいえ はここだけ）に `nav_v0.lua` が「はい」を 1 回押します（★依頼者の小WI「宿屋だけ Yes まで」）。
> ★`$A55C` の見張り＋窓の字で決めます。⚠ 聞き込みでは押しません（★この表の SERVICE → AUTO_NO のまま）。

## ★決め方（⚠ 窓ではなく**相手**で決める）

⚠ 「はい／いいえ」の窓は宿屋も教会も同じものを使います（★窓番号 0x1D）。
→ ★意味を決めるのは NPC の `talk_id` です（`dq3/testing/talk_script.py`）。

```text
SERVICE      施設（宿屋・道具屋・武器防具屋・教会）  → ★AUTO_NO（⚠ 入らない）
INFORMATION  message / message_daynight              → ⚠ STOP（★出ないはずのものが出た）
EVENT        event_script / special_1〜5             → ⚠⚠ STOP
UNKNOWN      それ以外                                → ⚠⚠ STOP
```

⚠ `AUTO_NO` は「B で閉じる」ことです（★`$8756 CMP #$FF` = キャンセル）。
★聞き込みの `nav_v0` は既に B で閉じているので、⚠ **新しい押し方は増やしません**。
"""

from __future__ import annotations

import dataclasses

#: ★選択肢の種別
SERVICE = "SERVICE"
INFORMATION = "INFORMATION"
EVENT = "EVENT"
UNKNOWN = "UNKNOWN"

#: ★してよいこと（⚠ `AUTO_YES` は**どの種別からも返しません**）
AUTO_YES = "AUTO_YES"
AUTO_NO = "AUTO_NO"
SKIP = "SKIP"
STOP = "STOP"

#: ★根拠の強さ（⚠ `docs/11-change-workflow.md` と同じ言葉）
CONFIRMED = "confirmed"
OBSERVED = "observed"
INFERRED = "inferred"

#: ★施設（⚠ `talk_script` が実機の文と一致させた 4 つ / RX3-0056）
SERVICE_CLASSES = ("inn", "item_shop", "weapon_armor_shop", "church")

#: ★メッセージを出すだけの相手（⚠ 選択肢を出さない）
MESSAGE_CLASSES = ("message", "message_daynight")

#: ⚠ 何が起きるか分からない相手
EVENT_CLASSES = ("event_script", "special_1", "special_2", "special_3", "special_4",
                 "special_5")

#: ★人へ出す言い方（⚠ 内部の語を画面に出さない / RX3-0109）
REASON_TEXT = {
    SERVICE: "お店の用事なので入りません",
    INFORMATION: "答えずに閉じました",
    EVENT: "何が起きるか分からないので答えません",
    UNKNOWN: "相手が分からないので答えません",
}


@dataclasses.dataclass(frozen=True)
class ChoiceDecision:
    """★選択肢 1 回ぶんの判断。"""

    kind: str
    action: str
    confidence: str
    reason: str = ""

    @property
    def presses_yes(self) -> bool:
        return self.action == AUTO_YES

    @property
    def text(self) -> str:
        """★人へ出す 1 行（⚠ 内部の語を混ぜない）。"""
        return REASON_TEXT.get(self.kind, "答えません")


def kind_of(talk_id) -> tuple:
    """★`talk_id` → `(種別, 根拠の強さ, talk_script の class)`。

    ⚠ 読めない `talk_id` は `UNKNOWN`（★推測しない）。
    """
    try:
        from dq3.testing import talk_script as TS

        got = TS.classify(int(talk_id))
    except Exception:                                    # noqa: BLE001
        return UNKNOWN, INFERRED, None
    if not got:
        return UNKNOWN, INFERRED, None
    name = got.get("class")
    if got.get("special_table_B34E"):
        # ⚠⚠ 表 $B34E の相手は、★範囲の処理**より先に**選ばれます（物語の相手 / HYPOTHESIS）。
        #   → ★範囲から付いた class を信じない。
        return UNKNOWN, INFERRED, name
    if name in SERVICE_CLASSES:
        # ★実機の会話文と一致させてある（⚠ role_status が CONFIRMED のものだけ）
        strong = got.get("role_status") == "CONFIRMED"
        return SERVICE, (CONFIRMED if strong else OBSERVED), name
    if name in MESSAGE_CLASSES:
        return INFORMATION, OBSERVED, name
    if name in EVENT_CLASSES:
        return EVENT, OBSERVED, name
    return UNKNOWN, INFERRED, name


def decide(talk_id) -> ChoiceDecision:
    """★選択肢が出たとき、⚠ **押してよいか**を決める。

    ⚠⚠ **`AUTO_YES` は返しません。** ★根拠のある相手が 1 件も無いためです
    （⚠ 見つかったら、そのときに根拠と一緒に足します）。
    """
    kind, confidence, name = kind_of(talk_id)
    if kind == SERVICE:
        # ★施設は「いいえ」で閉じる（⚠ サービスへ入らない / 聞き込みの目的は会話）
        return ChoiceDecision(kind, AUTO_NO, confidence, reason=name or "")
    # ⚠ それ以外は**押しません**（★止まるのは正しい終わり方）
    return ChoiceDecision(kind, STOP, confidence, reason=name or "")


def summary(decisions) -> str:
    """★User Action Summary に足す一言（⚠ 内部の値を出さない）。

    ```text
    選択肢 3 件処理 / 未確認 1 件
    ```
    """
    rows = list(decisions or ())
    if not rows:
        return ""
    handled = sum(1 for d in rows if d.action in (AUTO_NO, SKIP))
    left = len(rows) - handled
    got = "選択肢 %d 件処理" % handled if handled else ""
    if left:
        got = (got + " / " if got else "") + "未確認 %d 件" % left
    return got


__all__ = ["ChoiceDecision", "decide", "kind_of", "summary",
           "SERVICE", "INFORMATION", "EVENT", "UNKNOWN",
           "AUTO_YES", "AUTO_NO", "SKIP", "STOP",
           "CONFIRMED", "OBSERVED", "INFERRED"]

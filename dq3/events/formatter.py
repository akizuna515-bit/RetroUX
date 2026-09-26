"""Event → 人の言葉（RX3-0154 / 2026-09-10）。★文章を作るのはここだけ。

## ★2 つの出し先

```text
Product Log     16:12 自動戦闘：勝利 2ターン（8行動）      ★製品版の標準
Action Summary  [自動戦闘] 完了：1戦 / 2ターン（8行動）    ★右画面の行動履歴
```

⚠ どちらも**同じ Event**から作ります（★producer は文章を持ちません）。

## ⚠⚠ 分からない値は埋めません

★`rounds` が無い（＝旧い記録）なら「2ターン」とは書かず、⚠ **行動だけ**書きます。
★内部の語（`screen_frozen`）は表に無ければ「うまくいきませんでした」にします。
"""
from __future__ import annotations

from .. import action_log as AL
from .. import battle_count as BC
from . import event as EV
from . import reasons as RS

#: ★Product Log での呼び名（⚠ `action_log.ACTION_LABELS` と揃える）
SOURCE_LABELS = {
    EV.SRC_BATTLE: "自動戦闘",
    EV.SRC_NAVIGATION: "自動移動",
    EV.SRC_MANTAN: "まんたん",
    EV.SRC_SPELL: "呪文の結果",          # ★RX3-0271
}

#: ★Event の source → 行動履歴の action（⚠ 既存の名前を変えない）
SOURCE_ACTIONS = {
    EV.SRC_BATTLE: "battle",
    EV.SRC_NAVIGATION: "move",
    EV.SRC_MANTAN: "mantan",
    EV.SRC_SPELL: "spell",               # ★RX3-0271
}

#: ★終わり方 → 行動履歴の status
RESULT_STATUS = {
    EV.WIN: AL.SUCCESS,
    EV.SUCCESS: AL.SUCCESS,
    EV.STOPPED: AL.FAILED,
    EV.CANCELLED: AL.CANCELLED,
    EV.HANDED: AL.CANCELLED,             # ★Auto を切って人へ返した（⚠ 勝ったのではない / RX3-0233）
}

#: ★Product Log での終わり方（⚠ `勝利` は戦闘だけ）
RESULT_TEXT = {
    EV.WIN: "勝利",
    EV.SUCCESS: "完了",
    EV.STOPPED: "中断",
    EV.CANCELLED: "停止",
    EV.HANDED: "手動へ",
}

#: ⚠⚠ **Product Log へ出さない種別**（★依頼者 §11「開始・終了・結果・異常が中心」）。
#:   ★開始だけの行は、1 戦 5 秒の戦闘では**同じことを 2 行**書くだけになります。
#:   → ⚠ 開始は Diagnostic 側にだけ残します。
QUIET_TYPES = (EV.BATTLE_START, EV.NAVIGATION_START, EV.MANTAN_START)


# ----------------------------------------------------------------------
# ★Product Log
# ----------------------------------------------------------------------
def product_line(ev: EV.Event) -> str | None:
    """★製品版の 1 行。⚠ 出さないものは `None`（★呼ぶ側が捨てる）。"""
    if ev.level == EV.DEBUG or ev.type in QUIET_TYPES:
        return None
    head = SOURCE_LABELS.get(ev.source, ev.source)
    body = _body(ev)
    if body is None:
        return None
    return "%s：%s" % (head, body) if body else head


def stamped(ev: EV.Event, *, with_date: bool = False) -> str | None:
    """★時刻つき。★ファイルへは日付ごと、⚠ 画面には `HH:MM` だけ。"""
    line = product_line(ev)
    if line is None:
        return None
    return "%s %s" % (_clock(ev.ts, with_date=with_date), line)


def _clock(ts: str, *, with_date: bool) -> str:
    """★`2026-09-10T16:12:31+09:00` → `2026-09-10 16:12` / `16:12`。

    ⚠ 読めない形はそのまま返します（★推測して並べ替えない）。
    """
    text = str(ts or "")
    if len(text) < 16 or text[10] != "T":
        return text
    return ("%s %s" % (text[:10], text[11:16])) if with_date else text[11:16]


# ----------------------------------------------------------------------
# ★行動履歴（Action Summary）
# ----------------------------------------------------------------------
def summary_of(ev: EV.Event):
    """★`(action, status, message, detail)`。⚠ 履歴に出さないものは `None`。

    ★`ActionLog.record()` へそのまま渡せる形にします
    （⚠ ここでは記録しません / 記録するのは `writer` の consumer）。
    """
    if ev.type in QUIET_TYPES or ev.level == EV.DEBUG:
        return None
    action = SOURCE_ACTIONS.get(ev.source)
    if action is None:
        return None
    body = _summary_body(ev)
    if body is None:
        return None
    status = RESULT_STATUS.get(ev.get("result"), AL.SUCCESS)
    detail = {k: v for k, v in ev.data.items() if k != "message"}
    detail["event_type"] = ev.type
    return action, status, body, detail


# ----------------------------------------------------------------------
# ★中身（⚠ Product と Action Summary で言い回しだけ違う）
# ----------------------------------------------------------------------
def _body(ev: EV.Event) -> str | None:
    if ev.type == EV.BATTLE_END:
        return _battle_product(ev)
    if ev.type == EV.BATTLE_SPELL:
        return _spell(ev)
    if ev.type == EV.NAVIGATION_ARRIVE:
        return "%sに到着" % (ev.get("destination") or "目的地")
    if ev.type == EV.NAVIGATION_STOP:
        return _navigation_stop(ev)
    if ev.type == EV.MANTAN_END:
        return _mantan(ev)
    return None


def _summary_body(ev: EV.Event) -> str | None:
    if ev.type == EV.BATTLE_END:
        return _battle_summary(ev)
    if ev.type == EV.BATTLE_SPELL:
        return _spell(ev)
    if ev.type == EV.NAVIGATION_ARRIVE:
        return "%sへ到着 / %d歩" % (ev.get("destination") or "目的地",
                                    int(ev.get("steps") or 0))
    if ev.type == EV.NAVIGATION_STOP:
        return "%s / %d歩" % (_navigation_stop(ev), int(ev.get("steps") or 0))
    if ev.type == EV.MANTAN_END:
        return _mantan(ev)
    return None


def counted(ev: EV.Event) -> str:
    """★`2ターン（8行動）`。⚠ `rounds` が無ければ `8行動`（★推測しない / §21）。"""
    return BC.describe(ev.get("rounds"), ev.get("actions") or 0)


#: ★戦闘のまとめの言い方（RX3-0198 / 2026-09-12 依頼者の指示書:
#:   「作戦：速攻 / Nターン / 通常攻撃 a / 攻撃魔法 b / 回復 c / 支援 d / 防御 e / MP消費 f」）
BREAKDOWN_LABELS = (("attack", "通常攻撃"), ("magic", "攻撃魔法"), ("heal", "回復"),
                    ("support", "支援"), ("defend", "防御"))


def strategy_label(key) -> str:
    """★作戦の画面の名前（⚠ 正本は `battle_ai.settings.STRATEGY_LABELS` / 知らない語は空）。"""
    from ..battle_ai import settings as S

    return S.STRATEGY_LABELS.get(str(key or ""), "")


def battle_breakdown(data: dict, *, with_rounds: bool = False) -> str:
    """★`作戦：速攻 / 通常攻撃 5 / 攻撃魔法 2 / 回復 1 / 支援 0 / 防御 0 / MP消費 12`。

    ⚠⚠ **届いた値だけ**を書きます（★旧い記録・止まった戦闘は内訳が無い → 空を返す / §21 / §23）。
    ★`with_rounds` で「2ターン」を作戦の次に入れる（★右画面の「前回」の 1 行）。
    """
    data = data or {}
    parts = []
    label = strategy_label(data.get("strategy"))
    if label:
        parts.append("作戦：%s" % label)
    kinds = data.get("breakdown")
    if with_rounds and data.get("rounds"):
        parts.append("%dターン" % int(data["rounds"]))
    if isinstance(kinds, dict):
        for key, word in BREAKDOWN_LABELS:
            parts.append("%s %d" % (word, int(kinds.get(key) or 0)))
        if int(kinds.get("other") or 0) > 0:
            parts.append("その他 %d" % int(kinds["other"]))
    if data.get("mp_used") is not None:
        parts.append("MP消費 %d" % int(data["mp_used"]))
    return " / ".join(parts)


def _handback(ev: EV.Event) -> str:
    """★「手で戦う画面に戻しました（HPが1/4を切った仲間がいる）」（RX3-0233）。"""
    why = RS.handback_text(ev.get("reason"))
    return "手で戦う画面に戻しました" + ("（%s）" % why if why else "")


def _battle_product(ev: EV.Event) -> str:
    result = ev.get("result")
    if result == EV.CANCELLED:
        return "停止 %s" % counted(ev)
    if result == EV.STOPPED:
        return "%s %s" % (_reason(ev, "battle"), counted(ev))
    if result == EV.HANDED:
        return "%s %s" % (_handback(ev), counted(ev))
    body = "勝利 %s" % counted(ev)
    # ★RX3-0198: 作戦・行動の内訳・MP 消費（⚠ 無ければ今までと 1 文字も変えない）
    extra = battle_breakdown(ev.data)
    if extra:
        body += " / " + extra
    return (body + " / レベルが上がりました") if ev.get("level_up") else body


def _battle_summary(ev: EV.Event) -> str:
    result = ev.get("result")
    if result == EV.CANCELLED:
        return "ユーザー操作 / %s" % counted(ev)
    if result == EV.STOPPED:
        return "%s / %s" % (_reason(ev, "battle"), counted(ev))
    if result == EV.HANDED:
        return "%s / %s" % (_handback(ev), counted(ev))
    body = "1戦 / %s" % counted(ev)
    return (body + " / レベルが上がりました") if ev.get("level_up") else body


def _spell(ev: EV.Event) -> str | None:
    """★呪文の結果（RX3-0271 / 報告 §10 / ⚠ 観測だけ）。

    ```text
    ラリホー → スライム：3回中2回 効いた / ヒャド → ○○：2回中0回 効いた（図鑑: 効かない）
    ```

    ⚠⚠ 1 回の失敗で「耐性がある」と書かない（★回数だけ）。⚠ AI の内部の確率は出さない。
    ★図鑑のことばは producer（`ui/spell_watch.py`）が**倒した敵にだけ**入れる（★No-Spoiler）。
    """
    parts = []
    for row in ev.get("results") or []:
        head = "%s → %s" % (row.get("spell") or "呪文", row.get("enemy") or "敵")
        body = "%d回中%d回 効いた" % (int(row.get("tried") or 0), int(row.get("ok") or 0))
        if row.get("book"):
            body += "（図鑑: %s）" % row["book"]
        parts.append("%s：%s" % (head, body))
    return " / ".join(parts) or None


def _navigation_stop(ev: EV.Event) -> str:
    if ev.get("result") == EV.CANCELLED:
        return "ユーザー操作"
    return _reason(ev, "navigation")


def _mantan(ev: EV.Event) -> str:
    """★`3人回復 / HP +83`。⚠ 取れない値（MP など）は**足しません**（§23）。"""
    if ev.get("result") == EV.CANCELLED:
        return "ユーザー操作"
    if ev.get("result") == EV.STOPPED:
        healed = _mantan_healed(ev)
        why = _reason(ev, "mantan")
        return ("%s / %s" % (why, healed)) if healed else why
    return _mantan_healed(ev) or "回復は要りませんでした"


def _mantan_healed(ev: EV.Event) -> str:
    people = int(ev.get("members_healed") or 0)
    if people <= 0:
        return ""
    out = "%d人回復" % people
    gained = ev.get("hp_gained")
    if gained:
        out += " / HP +%d" % int(gained)
    used = ev.get("mp_used")
    if used:
        out += " / MP %d使用" % int(used)
    return out


#: ★表に無かったときの言い方（⚠ domain ごとに違う。★推測ではなく「分からない」）
FALLBACK = {"navigation": "目的地へ到達できません"}


def _reason(ev: EV.Event, domain: str) -> str:
    """★内部の語 → 人の言葉。⚠ 表に無ければ推測しません。"""
    return AL.humanize_reason(RS.BY_DOMAIN.get(domain, {}), ev.get("reason"),
                              FALLBACK.get(domain, AL.UNKNOWN_REASON))


__all__ = ["product_line", "stamped", "summary_of", "counted", "battle_breakdown", "strategy_label",
           "BREAKDOWN_LABELS",
           "SOURCE_LABELS", "SOURCE_ACTIONS", "RESULT_STATUS", "RESULT_TEXT",
           "QUIET_TYPES"]

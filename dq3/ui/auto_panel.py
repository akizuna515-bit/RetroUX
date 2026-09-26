"""オート戦闘サマリー — 右画面の 3 段（RX3-0149 / 2026-09-10）。

## ★出すもの

```text
自動戦闘                     AUTO ●ON     ★常時 1 行
生存優先 / MP おまかせ
─────────────────────────────────────
戦況 均衡   HP低下 → 回復優先              ★戦闘中（終わったら次の戦闘まで「前回の戦闘」として薄く）
勇者   こうげき   → 敵A
僧侶   じゅもん   ホイミ → 勇者
─────────────────────────────────────
今日 5戦 / 平均 6ターン                    ★終わったあと
```

## ⚠⚠ LLM を使いません（依頼者の指示）

★「HP低下 → 回復優先」のような 1 行は、⚠ **規則で決めます**。
材料は `state.json.auto`（`ai/pipeline.lua` の判断そのもの）に既にあります。

⚠ 当てはまるものが無ければ**何も出しません**（★埋めない）。

## ⚠ 出どころ

```text
AUTO ON/OFF・戦況・手      state.json.auto     ★`auto_v0.lua` が publish（RX3-0147）
作戦・MP 制約              同上（⚠ 画面の設定と同じ値）
戦った数・ターン           ActionLog           ⚠ 再起動で消える（★そう書く）
```
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from dq3.battle_ai.settings import MP_LABELS, STRATEGY_LABELS
from dq3.events import formatter as FM

#: ★小さい字（⚠ 既存の右画面に合わせる）
MUTED = "color:#8a93a5; font-size:11px;"
ON_COLOR = "#3b6f4e"
OFF_COLOR = "#8a93a5"

#: ★作戦・MP 制約の言い方（⚠ 内部の語を画面へ出さない）。
#:   ★RX3-0198（2026-09-12）: 写しを持たず `battle_ai.settings` の名前を使う
#:   （⚠ 以前はここに作戦名の写しがあり、改名の漏れ先になっていた）
STRATEGY_UI = STRATEGY_LABELS
MP_UI = MP_LABELS


# ----------------------------------------------------------------------
# ★判断の要約（⚠⚠ 規則だけ。LLM を使わない）
# ----------------------------------------------------------------------

def summarize(auto: dict) -> str:
    """★AI の判断を 1 行に（⚠ 当てはまらなければ空）。

    ⚠⚠ **推測を混ぜません。** ★材料は `auto` に来ているものだけです。
    ⚠ 迷ったら何も出しません（★埋めた 1 行は、嘘になります）。
    """
    if not auto:
        return ""
    got: list[str] = []
    needs = [str(n) for n in (auto.get("needs") or [])]
    slots = list(auto.get("slots") or [])

    # ★動けない人（⚠ いちばん先に知らせたい）
    notes = [str(n) for n in (auto.get("notes") or [])]
    if notes:
        got.append("動けない人が居る")

    # ★回復が要る
    if "ヒール" in needs:
        got.append("HP低下 → 回復優先")
    if any((s or {}).get("role") == "防御" for s in slots) and "ヒール" not in needs:
        got.append("瀕死 → 防御")

    # ★MP の使い方（⚠ 実際に呪文を控えているときだけ）
    mp = auto.get("mp_policy")
    casting = any((s or {}).get("command") == "じゅもん" for s in slots)
    if mp == "forbid":
        got.append("MP使用禁止")
    elif mp == "save" and not casting:
        got.append("MP温存")

    # ★同じ群へ集まっている（⚠ 2 人以上のときだけ）
    targets = [(s or {}).get("target") for s in slots if (s or {}).get("target")]
    groups = [t for t in targets if str(t).startswith("g")]
    if len(groups) >= 2 and len(set(groups)) == 1:
        got.append("集中攻撃")

    # ⚠ 手が足りない（★役割が要るのに、その役の人が居ない）
    #
    #   ⚠⚠ **手が 1 つも届いていないときは言いません。** ★「割り当てが分からない」と
    #     「割り当てられなかった」は別のことです（⚠ 2026-09-10 に検査が誤検知を捕まえた）。
    if slots:
        roles = {(s or {}).get("role") for s in slots}
        if [n for n in needs if n not in roles]:
            got.append("手が足りない")

    return " / ".join(got[:2])          # ⚠ 2 つまで（★1 行に収める）


def strategy_line(auto: dict) -> str:
    """★「生存優先 / MP おまかせ」の 1 行（⚠ 分からない所は出さない）。"""
    got = []
    s = STRATEGY_UI.get(auto.get("strategy") or "")
    m = MP_UI.get(auto.get("mp_policy") or "")
    if s:
        got.append(s)
    if m:
        got.append("MP " + m)
    return " / ".join(got)


#: ★Turbo にしない理由（Lua の `battle_speed.lua` の語）→ 人の言葉（⚠ 部分一致 / 上から順に見る）
SPEED_WHY = (
    # ★窓の色で Auto を人へ返した（RX3-0225）。⚠ 「死者あり」より先に見る（★部分一致）
    ("窓の色 オレンジ", "倒れている仲間がいるので手で戦う画面に戻しました"),
    ("窓の色 緑", "HPが1/4を切った仲間がいるので手で戦う画面に戻しました"),
    # ★劣勢に「なった」ので Auto も Turbo も止めた（2026-09-13 / battle_speed の `watch_situation`）
    #   ⚠ 「死者あり」「HP 危険」は同じ日に Lua から外した（依頼者「３割は廃止」/ ★窓の色が受け持つ）
    ("劣勢", "戦況が劣勢になったので手で戦う画面に戻しました"),
    ("人が通常の速さを選んだ", "タで通常にしました"),
    ("Turbo 希望 OFF", "タで通常にしました"),
    ("初見の敵", "初めて見る敵がいるので速くできません"),
    ("戦況 even", "戦況が均衡なので速くできません"),
    ("戦況 disadvantage", "戦況が劣勢なので速くできません"),
    ("ボス・イベント戦の候補", "ボス・イベント戦かもしれないので速くできません"),
    ("高速化オフ", "設定で速くしないことになっています"),
)


def speed_line(auto: dict, speed: dict) -> str:
    """★Auto 中の速さと、速くしない理由（2026-09-11 依頼者「ターボできない。Tもボタンもきかない」）。

    ⚠ 押しても断られたとき、**理由が画面に出ていなかった**（★記録には `OFF のまま（戦況 even）` と出ていた）。
    ⚠ Auto でも Turbo でもなければ出さない（★AUTO OFF・TURBO ON = 手で戦っている高速は出す / RX3-0237）。
    """
    if not isinstance(speed, dict) or not (auto.get("active") or speed.get("fast")):
        return ""
    if speed.get("fast"):
        # ★人が押して速くした（★均衡・初見でも / 2026-09-11 依頼者「早くして良い」）
        return "速さ Turbo（タで選びました）" if str(speed.get("reason") or "").startswith("人が選んだ") \
            else "速さ Turbo"
    why = str(speed.get("reason") or "")
    if not why or speed.get("mode") is None:
        return "速さ 通常（様子を見ています）"
    text = next((ui for key, ui in SPEED_WHY if key in why), "様子を見ています")
    if why.startswith("危険化"):
        text = "途中で危なくなったので通常に戻しました"
    return "速さ 通常（%s）" % text


def last_battle_line(rows) -> str:
    """★「前回 作戦：速攻 / 2ターン / 通常攻撃 5 / 攻撃魔法 2 / … / MP消費 12」（RX3-0198）。

    ★いちばん新しい戦闘の行動履歴の `detail`（= Event の data）から作る。
    ⚠ 内訳が届いていない戦闘（旧い記録）なら空（★埋めない）。
    ★★ 止めた・人へ返した戦闘は、その理由（RX3-0233 / 2026-09-13 依頼者「よくわからない理由で自動戦闘が中断」）。
      ⚠ Auto が切れると速さの行は消えるので、★理由はここに次の戦闘まで残る。
    """
    from dq3 import action_log as AL
    from dq3.events import event as EV
    from dq3.events import reasons as RS

    for row in reversed(list(rows or [])):
        detail = getattr(row, "detail", None) or {}
        if not isinstance(detail, dict):
            return ""
        if detail.get("result") == EV.STOPPED:
            return "前回 止めました：%s（ここから手で操作）" % AL.humanize_reason(RS.BATTLE, detail.get("reason"))
        if detail.get("result") == EV.HANDED:
            why = RS.handback_text(detail.get("reason"))
            return "前回 手で戦う画面に戻しました" + ("：%s" % why if why else "")
        if "breakdown" not in detail:
            return ""
        text = FM.battle_breakdown(detail, with_rounds=True)
        return ("前回 " + text) if text else ""
    return ""


def slot_line(row: dict, name: str | None = None) -> str:
    """★1 人ぶんの 1 行（⚠ 生の値を混ぜない）。"""
    who = name or row.get("slot") or "?"
    command = row.get("command") or ""
    what = row.get("name") or ""
    target = row.get("target") or ""
    left = "%s %s" % (command, what) if what else command
    return "%-6s %s%s" % (who, left, ("　→ %s" % target) if target else "")


# ----------------------------------------------------------------------
# ★画面
# ----------------------------------------------------------------------

class AutoBattlePanel(QFrame):
    """★右画面の 3 段（⚠ 戦っていないときは中段を節ごと消す）。"""

    def __init__(self, view_model, action_log=None, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.action_log = action_log
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        self.head = QLabel("自動戦闘")
        self.head.setStyleSheet(MUTED)
        box.addWidget(self.head)

        self.strategy = QLabel("")
        box.addWidget(self.strategy)

        #: ★Auto 中の速さと、速くしない理由（⚠ 押しても断られた理由が見えなかった）
        self.speed = QLabel("")
        self.speed.setWordWrap(True)
        box.addWidget(self.speed)

        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        self.reason.setToolTip("★AI がいま何を優先しているか（⚠ 規則で出しています）")
        box.addWidget(self.reason)

        self.slots = QLabel("")
        self.slots.setStyleSheet("font-family: monospace;")
        box.addWidget(self.slots)

        #: ★前回の戦闘のまとめ（RX3-0198: 作戦・ターン・行動の内訳・MP 消費）
        self.last = QLabel("")
        self.last.setWordWrap(True)
        self.last.setStyleSheet(MUTED)
        self.last.setToolTip("★いちばん新しい自動戦闘の内訳（⚠ 実際に押した行動を数えています）")
        box.addWidget(self.last)

        self.tally = QLabel("")
        self.tally.setStyleSheet(MUTED)
        self.tally.setToolTip("⚠ 数えているのは、この起動のあいだだけです")
        box.addWidget(self.tally)

        self.refresh()

    # --- ★描く ----------------------------------------------------------

    def refresh(self) -> None:
        auto = self._auto()
        self._draw_head(auto)
        self._draw_battle(auto)
        self._draw_tally()

    def _auto(self) -> dict:
        got = getattr(self.vm, "auto_status", None)
        if callable(got):
            try:
                got = got()
            except Exception:                              # noqa: BLE001 - ★画面は落とさない
                got = None
        return got if isinstance(got, dict) else {}

    def _draw_head(self, auto: dict) -> None:
        on = bool(auto.get("active"))
        # ⚠ 見出し（「自動戦闘」）は右画面の `_section` が出すので、★ここは状態だけ
        self.head.setText("AUTO %s" % ("●ON" if on else "○OFF"))
        self.head.setStyleSheet("color:%s; font-size:11px;" % (ON_COLOR if on else OFF_COLOR))
        line = strategy_line(auto)
        if not line:
            # ★材料が届いていないとき（⚠ 「設定が無い」ではないので、そう書く）
            line = "⚠ FCEUX から届いていません" if not auto else ""
        self.strategy.setText(line)
        self.strategy.setVisible(bool(line))
        self.strategy.setStyleSheet("" if auto else MUTED)
        got = speed_line(auto, self._speed())
        self.speed.setText(got)
        self.speed.setVisible(bool(got))
        # ★断られているときは目立たせる（⚠ 押しても何も起きないように見えるので）
        self.speed.setStyleSheet("color:#b26b00;" if "できません" in got else "")

    def _speed(self) -> dict:
        """★state.json の `battle_speed`（⚠ 無ければ空）。"""
        raw = getattr(self.vm, "_raw", None)
        try:
            got = (raw() or {}).get("battle_speed") if callable(raw) else None
        except Exception:                                  # noqa: BLE001 - ★画面は落とさない
            got = None
        return got if isinstance(got, dict) else {}

    def _draw_battle(self, auto: dict) -> None:
        """★戦闘中の判断。⚠ 一度も戦っていなければ中段を節ごと消す（`reachable` と同じ作法）。

        ★★ 戦闘が終わっても、次の戦闘まで「前回」として薄く残す（2026-09-11 依頼者
          「戦闘終了後クリアされてしまうと見えない」）。⚠ RX3-0169 で勝った瞬間に Auto OFF になり、
          Turbo の戦闘では中段が 1〜2 秒しか出ていなかった。
          ★Lua も「中身は残す / active だけ倒す」（`AIX.publish_idle`）なので、画面がそれに合わせる。
        """
        rows = list(auto.get("slots") or [])
        show = bool(rows)
        self.reason.setVisible(show)
        self.slots.setVisible(show)
        if not show:
            return
        live = bool(auto.get("active"))
        situation = auto.get("situation") or ""
        why = summarize(auto)
        text = ("戦況 %s　%s" % (situation, why)).strip()
        if not live:
            turn = int(auto.get("turn") or 0)
            text = ("前回の戦闘（%dターン目）　" % turn if turn > 0 else "前回の戦闘　") + text
        self.reason.setText(text)
        names = self._names()
        self.slots.setText("\n".join(
            slot_line(r, names.get(r.get("slot"))) for r in rows))
        # ★前回のものは薄く（⚠ いまの判断と見分けがつくように）
        self.reason.setStyleSheet("" if live else MUTED)
        self.slots.setStyleSheet("font-family: monospace;" + ("" if live else " color:#8a93a5;"))

    def _names(self) -> dict:
        """★人の名前（⚠ 取れなければ `p1` のまま）。"""
        got = {}
        try:
            for i, member in enumerate(self.vm.party() or []):
                name = getattr(member, "name", None) or (member or {}).get("name")
                if name:
                    got["p%d" % (i + 1)] = str(name)
        except Exception:                                  # noqa: BLE001
            return {}
        return got

    def _draw_tally(self) -> None:
        """★この起動での戦った数（⚠ 再起動で消えることを言葉にする）。"""
        rows = self._battles()
        # ★前回の戦闘のまとめ（⚠ 内訳の届いた戦闘だけ / 文章は formatter が作る）
        last = last_battle_line(rows)
        self.last.setText(last)
        self.last.setVisible(bool(last))
        if not rows:
            self.tally.setVisible(False)
            return
        #: ⚠ `turns` は旧い名前（★中身は「行動」）。RX3-0153 以降は `rounds` / `actions`
        rounds = [int((r.detail or {}).get("rounds") or 0) for r in rows]
        rounds = [t for t in rounds if t > 0]
        acts = [int((r.detail or {}).get("actions")
                    or (r.detail or {}).get("turns") or 0) for r in rows]
        acts = [t for t in acts if t > 0]
        text = "この起動で %d 戦" % len(rows)
        if rounds:
            text += " / 平均 %.0f ターン" % (sum(rounds) / len(rounds))
        elif acts:
            text += " / 平均 %.0f 行動" % (sum(acts) / len(acts))
        self.tally.setText(text)
        self.tally.setVisible(True)

    def _battles(self) -> list:
        if self.action_log is None:
            return []
        try:
            return [r for r in self.action_log.rows if r.action == "battle"]
        except Exception:                                  # noqa: BLE001
            return []


__all__ = ["AutoBattlePanel", "summarize", "strategy_line", "slot_line", "speed_line",
           "last_battle_line"]

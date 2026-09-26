"""オート戦闘サマリー（RX3-0147 / RX3-0149 / 2026-09-10）。

```text
A  判断が state.json へ届く（★auto_v0.lua が publish）
C  右画面が、届いたものだけを出す（⚠ 埋めない）
```

⚠⚠ **要約は規則で決めます**（★LLM を使わない / 依頼者の指示）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import auto_panel as AP                                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _auto(**rest):
    got = {"active": True, "situation": "均衡", "strategy": "survival",
           "mp_policy": "auto", "needs": [], "notes": [], "slots": []}
    got.update(rest)
    return got


def _slot(slot, role=None, command="こうげき", name=None, target=None):
    return {"slot": slot, "role": role, "command": command,
            "name": name, "target": target}


# --- ★要約（⚠ 規則だけ）------------------------------------------------

def test_回復が要るときは回復優先と出す():
    assert AP.summarize(_auto(needs=["ヒール", "物理"])) == "HP低下 → 回復優先"


def test_動けない人が居れば先に知らせる():
    got = AP.summarize(_auto(notes=["p2=麻痺"], needs=["ヒール"]))
    assert got.startswith("動けない人が居る")


def test_MP使用禁止を出す():
    assert "MP使用禁止" in AP.summarize(_auto(mp_policy="forbid"))


def test_MP温存は呪文を控えているときだけ():
    """⚠ 温存にしていても、★呪文を使っているなら「温存」とは言わない。"""
    casting = _auto(mp_policy="save", slots=[_slot("p1", command="じゅもん", name="ホイミ")])
    assert "MP温存" not in AP.summarize(casting)
    holding = _auto(mp_policy="save", slots=[_slot("p1")])
    assert "MP温存" in AP.summarize(holding)


def test_集中攻撃は2人以上が同じ群のときだけ():
    one = _auto(slots=[_slot("p1", target="g1")])
    assert "集中攻撃" not in AP.summarize(one), "⚠ 1 人でも「集中」と言っている"
    two = _auto(slots=[_slot("p1", target="g1"), _slot("p2", target="g1")])
    assert "集中攻撃" in AP.summarize(two)
    split = _auto(slots=[_slot("p1", target="g1"), _slot("p2", target="g2")])
    assert "集中攻撃" not in AP.summarize(split)


def test_手が足りないと分かる():
    got = AP.summarize(_auto(needs=["魔法"], slots=[_slot("p1", role="物理")]))
    assert "手が足りない" in got


def test_当てはまらなければ何も出さない():
    """⚠⚠ **埋めないこと。** ★1 行を作ると、それは嘘になります。"""
    assert AP.summarize(_auto()) == ""
    assert AP.summarize({}) == ""
    assert AP.summarize(None) == ""


def test_1行に収める():
    """⚠ 全部を並べない（★2 つまで）。"""
    got = AP.summarize(_auto(notes=["p2=麻痺"], needs=["ヒール", "魔法"],
                             mp_policy="forbid",
                             slots=[_slot("p1", role="物理", target="g1"),
                                    _slot("p2", role="物理", target="g1")]))
    assert got.count("/") <= 1, "⚠ 3 つ以上出している: %r" % got


def test_内部の語を画面へ出さない():
    line = AP.strategy_line(_auto(strategy="survival", mp_policy="forbid"))
    assert line == "生存優先 / MP 使用禁止"
    for banned in ("survival", "forbid", "leveling", "economy", "auto", "save"):
        assert banned not in line


def test_分からない所は出さない():
    assert AP.strategy_line({"strategy": "survival"}) == "生存優先"
    assert AP.strategy_line({}) == ""


def test_作戦の名前はsettingsが正本():
    """★RX3-0198 → RX3-0327: 「レベル上げ」→「速攻」→「最短撃破」。

    ⚠ 右画面に写しを持つと改名の漏れ先になる。
    """
    from dq3.battle_ai import settings as S

    assert AP.strategy_line({"strategy": "leveling"}) == S.STRATEGY_LABELS["leveling"]
    src = (ROOT / "dq3" / "ui" / "auto_panel.py").read_text(encoding="utf-8")
    assert "レベル上げ" not in src, "⚠⚠ 作戦の名前の写しが残っている"


class _Row:
    def __init__(self, detail):
        self.action = "battle"
        self.detail = detail


def test_前回の戦闘のまとめを1行で出す():
    """★RX3-0198 依頼者「戦闘後に作戦・行動の内訳・MP 消費」（★右画面）。"""
    rows = [_Row({"rounds": 3, "actions": 12}),
            _Row({"rounds": 2, "actions": 8, "strategy": "leveling", "mp_used": 12,
                  "breakdown": {"attack": 5, "magic": 2, "heal": 1, "support": 0,
                                "defend": 0, "other": 0}})]
    assert AP.last_battle_line(rows) == (
        "前回 作戦：最短撃破 / 2ターン / 通常攻撃 5 / 攻撃魔法 2 / 回復 1 / 支援 0 / 防御 0 / MP消費 12")
    # ⚠ いちばん新しい戦闘に内訳が無ければ出さない（★古い戦闘のまとめを「前回」と言わない）
    assert AP.last_battle_line(rows[:1]) == ""
    assert AP.last_battle_line([]) == ""


def test_右画面に前回のまとめが出る():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3 import action_log as AL

    QApplication.instance() or QApplication([])
    log = AL.ActionLog(clock=lambda: 0.0)
    log.record("battle", AL.SUCCESS, "1戦 / 2ターン（8行動）", rounds=2, actions=8,
               strategy="economy", mp_used=0,
               breakdown={"attack": 7, "magic": 1, "heal": 0, "support": 0, "defend": 0, "other": 0})
    panel = AP.AutoBattlePanel(_VM({}), action_log=log)
    assert panel.last.isVisibleTo(panel)
    assert panel.last.text().startswith("前回 作戦：リソース節約 / 2ターン / 通常攻撃 7 / 攻撃魔法 1")
    assert panel.last.text().endswith("MP消費 0")


def test_1人ぶんの行に生の値を混ぜない():
    got = AP.slot_line(_slot("p3", command="じゅもん", name="ホイミ", target="p2"), "僧侶")
    assert "僧侶" in got and "ホイミ" in got and "p2" in got
    assert "spell" not in got and "kind" not in got


# --- ★画面（⚠ 届いていないものを出さない）------------------------------

class _VM:
    def __init__(self, auto):
        self._auto = auto

    def auto_status(self):
        return self._auto

    def party(self):
        return []


def test_戦っていないときは中段を消す():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    panel = AP.AutoBattlePanel(_VM({"active": False, "strategy": "survival"}))
    assert panel.reason.isVisibleTo(panel) is False, "⚠ 戦っていないのに戦況を出している"
    assert panel.slots.isVisibleTo(panel) is False


def test_戦闘が終わっても前回として残す():
    """★2026-09-11 依頼者「戦闘終了後クリアされてしまうと見えない」。

    ⚠ 勝った瞬間に Auto OFF（RX3-0169）→ 中段が消え、Turbo の戦闘では 1〜2 秒しか見えなかった。
    ★Lua は中身を残して active だけ倒す。画面は次の戦闘まで「前回」として薄く残す。
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    auto = _auto(needs=["ヒール"],
                 slots=[_slot("p1", role="ヒール", command="じゅもん",
                              name="ホイミ", target="p2")])
    auto.update(active=False, turn=3)
    panel = AP.AutoBattlePanel(_VM(auto))
    assert panel.reason.isVisibleTo(panel) is True, "⚠⚠ 終わった戦闘の判断を消した"
    assert panel.reason.text().startswith("前回の戦闘（3ターン目）"), panel.reason.text()
    assert "ホイミ" in panel.slots.text()
    assert "8a93a5" in panel.reason.styleSheet(), "⚠ 前回のものといまの判断の見分けがつかない"
    assert "AUTO ○OFF" in panel.head.text()


def test_戦闘中の判断は薄くしない():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    auto = _auto(needs=["ヒール"], slots=[_slot("p1")])
    panel = AP.AutoBattlePanel(_VM(auto))
    assert not panel.reason.text().startswith("前回"), panel.reason.text()
    assert panel.reason.styleSheet() == ""


def test_戦闘中は手を出す():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    auto = _auto(needs=["ヒール"],
                 slots=[_slot("p1", role="ヒール", command="じゅもん",
                              name="ホイミ", target="p2")])
    panel = AP.AutoBattlePanel(_VM(auto))
    assert panel.reason.isVisibleTo(panel) is True
    assert "均衡" in panel.reason.text() and "回復優先" in panel.reason.text()
    assert "ホイミ" in panel.slots.text()


def test_届いていないときはそう言う():
    """⚠ 「AUTO OFF」と「材料が届いていない」を混ぜない。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    panel = AP.AutoBattlePanel(_VM({}))
    assert "届いていません" in panel.strategy.text()


# --- ★つなぎ（A: Lua → state.json）--------------------------------------

def test_判断がLuaからstate_jsonへ届く道がある():
    """⚠⚠ nav / walk / restock は publish 済みで、★戦闘 AI だけが例外だった。"""
    auto = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert "HOST.auto_status" in auto, "⚠ publish していない"
    assert "function AIX.publish" in auto
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "auto = HOST.auto_status" in dev, "⚠ state.json に載せていない"
    vm = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    assert "def auto_status" in vm


def test_pipelineを触っていない():
    """★判断そのものは純粋なまま（⚠ 画面のために AI を改造しない / 依頼者の指示）。"""
    src = (ROOT / "dq3" / "phase0" / "ai" / "pipeline.lua").read_text(encoding="utf-8")
    for banned in ("HOST", "auto_status", "state.json"):
        assert banned not in src, "⚠⚠ 判断の側が画面を知っている: %s" % banned


def test_要約にLLMを使っていない():
    """⚠⚠ 依頼者の指示: 「LLM による要約は禁止」。"""
    src = (ROOT / "dq3" / "ui" / "auto_panel.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "requests", "urllib", "http"):
        assert banned not in src.lower(), "⚠⚠ 外へ問い合わせている: %s" % banned


# --- ★Auto 中の速さと、速くしない理由（2026-09-11 依頼者「ターボできない。Tもボタンもきかない」）---

def test_Turboを断った理由を人の言葉で出す():
    """⚠ 押しても断られた理由が画面に無かった（★記録には `OFF のまま（戦況 even）`）。"""
    on = {"active": True}
    assert AP.speed_line(on, {"mode": "MANUAL", "reason": "戦況 even", "fast": False}) \
        == "速さ 通常（戦況が均衡なので速くできません）"
    assert "初めて見る敵" in AP.speed_line(on, {"mode": "MANUAL", "reason": "初見の敵"})
    # ⚠ 「死者あり」は 2026-09-13 に Lua の judge から外した（★死者は窓の色 オレンジが受け持つ）
    assert "倒れている仲間" in AP.speed_line(on, {"mode": "MANUAL", "reason": "窓の色 オレンジ（死者あり）"})
    assert "途中で危なくなった" in AP.speed_line(on, {"mode": "MANUAL", "reason": "危険化: 戦況 even"})
    assert AP.speed_line(on, {"mode": "MANUAL", "reason": "人が通常の速さを選んだ"}) \
        == "速さ 通常（タで通常にしました）"
    assert AP.speed_line(on, {"mode": "AUTO_FAST", "reason": "既知・安全", "fast": True}) == "速さ Turbo"
    # ★RX3-0225: 窓の色で Auto を人へ返した（⚠ 「死者あり」の行に吸われない）
    assert "HPが1/4を切った" in AP.speed_line(on, {"mode": "MANUAL", "reason": "窓の色 緑（HP 1/4 未満）"})
    got = AP.speed_line(on, {"mode": "MANUAL", "reason": "窓の色 オレンジ（死者あり）"})
    assert "手で戦う画面に戻しました" in got and "速くできません" not in got, got
    # ★2026-09-13: 劣勢に「なった」ので Auto も Turbo も止めた（⚠ 「戦況 disadvantage」= 速くしないだけ、とは別の文）
    got = AP.speed_line(on, {"mode": "MANUAL", "reason": "劣勢"})
    assert "劣勢になったので手で戦う画面に戻しました" in got, got
    assert "速くできません" in AP.speed_line(on, {"mode": "MANUAL", "reason": "戦況 disadvantage"})


def test_Autoでなければ速さは出さない():
    assert AP.speed_line({"active": False}, {"mode": "MANUAL", "reason": "戦況 even"}) == ""
    assert AP.speed_line({}, {}) == ""


def test_手で戦っている高速も速さの行を出す():
    """★RX3-0237: AUTO OFF / TURBO ON（手動操作・高速）も正式な状態（⚠ 以前は Auto でなければ出さなかった）。"""
    got = AP.speed_line({"active": False}, {"mode": "AUTO_FAST", "reason": "人が選んだ（手で戦う）", "fast": True})
    assert got == "速さ Turbo（タで選びました）"
    assert AP.speed_line({"active": True}, {"mode": "AUTO_FAST", "reason": "AUTO と一緒に", "fast": True}) \
        == "速さ Turbo"


def test_内部の語を速さの行に出さない():
    on = {"active": True}
    for why in ("戦況 even", "戦況 disadvantage", "初見の敵", "劣勢",
                "ボス・イベント戦の候補", "AI の判断が無い", "高速化オフ（設定）"):
        got = AP.speed_line(on, {"mode": "MANUAL", "reason": why})
        for bad in ("even", "disadvantage", "MANUAL", "AUTO_FAST"):
            assert bad not in got, (why, got)


def test_画面に断った理由が出る():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    class _VM2(_VM):
        def _raw(self):
            return {"battle_speed": {"mode": "MANUAL", "reason": "戦況 even", "fast": False}}

    panel = AP.AutoBattlePanel(_VM2(_auto(slots=[_slot("p1")])))
    assert panel.speed.isVisibleTo(panel)
    assert panel.speed.text() == "速さ 通常（戦況が均衡なので速くできません）"
    assert "b26b00" in panel.speed.styleSheet(), "⚠ 断られていることが目立たない"


def test_人が選んだTurboはそう出す():
    """★2026-09-11 依頼者「早くして良い」: 均衡・初見でも人が押せば速く（★自分から速くしたのと見分ける）。"""
    on = {"active": True}
    assert AP.speed_line(on, {"mode": "AUTO_FAST", "fast": True,
                              "reason": "人が選んだ（戦況 even でも速く）"}) == "速さ Turbo（タで選びました）"

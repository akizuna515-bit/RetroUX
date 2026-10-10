"""街ナビ＋聞き込みの UI（RX3-0058）。★段取り（controller）は偽の service / Lua で、画面は offscreen で。"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import npc_heard as H        # noqa: E402
from dq3.knowledge import town_service as TSV    # noqa: E402
from dq3.ui import town_bar as TB               # noqa: E402
from dq3.ui.town_bar import TownNavController   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★店の品揃えは monkeypatch で差し替えても、品名・値段は ROM（`item_info`）から引く（RX3-0119）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


class _VM:
    """★state.json の代わり。⚠ 番地は知らない。"""

    def __init__(self):
        self.pos = (1, 9, 8, 18)
        self.nav = None
        self.talk = None
        self.talk_tag = None
        self.last_talk_text = None
        self.window_open = False
        self.memos = []

    def position(self): return self.pos
    def time_byte(self): return 0
    def npc_table_hex(self): return "00"
    def nav_status(self): return self.nav
    def last_talk(self): return self.talk
    def conversation_open_now(self): return self.window_open


class _Service:
    """★候補を返す偽の service（★ROM も BFS も使わない）。"""

    def __init__(self, tmp):
        self.heard = H.HeardLedger(tmp)
        self.npcs = [
            {"npc_id": 1, "slot": 5, "x": 8, "y": 16, "movement": "fixed", "appearance_id": 28, "talk_id": 11, "role": "inn", "role_status": "CONFIRMED"},
            {"npc_id": 6, "slot": 10, "x": 3, "y": 10, "movement": "random", "appearance_id": 44, "talk_id": 0x247, "role": None, "role_status": None},
            {"npc_id": 3, "slot": 7, "x": 23, "y": 23, "movement": "fixed", "appearance_id": 116, "talk_id": 0, "role": None, "role_status": None},
        ]
        self.unreachable = set()
        #: ★鍵があれば届く相手（⚠ `unreachable` の部分集合として使う / RX3-0078）
        self.behind_door = set()
        self.seen_keys = []
        self.grids = 0

    def _plan(self, n):
        return {"goal": [n["x"], n["y"] + 2], "face": "up", "keys": ["up"] * 3, "cells": [[8, 17], [8, 16], [8, 15]], "steps": 3, "doors": []}

    def plan_to(self, map_id, start, npc, others=(), *, keys=()):
        """⚠ 「鍵を全部持っていたら届くか」を聞かれる（RX3-0078）。"""
        if npc["npc_id"] in self.unreachable and not (keys and npc["npc_id"] in self.behind_door):
            return None
        return self._plan(npc)

    def known_reachable_facilities(self, map_id, t, tbl, start):
        return [{"role": n["role"], "label": "宿屋", "npc": n, "plan": self._plan(n)}
                for n in self.npcs if n["role"] and self.heard.is_heard(map_id, n["npc_id"])]

    def unheard_reachable_npcs(self, map_id, t, tbl, start, *, keys=()):
        """⚠ `keys` は「持っている鍵」（RX3-0078）。★偽物では扉の向こうを `behind_door` で表す。"""
        self.seen_keys = list(keys)
        blocked = set(self.unreachable) - (set(self.behind_door) if keys else set())
        return [{"npc": n, "plan": self._plan(n), "distance": n["npc_id"]} for n in self.npcs
                if n["talk_id"] and not self.heard.is_heard(map_id, n["npc_id"]) and n["npc_id"] not in blocked]

    def write_grid(self, map_id, opened=()):
        self.grids += 1
        self.last_opened = list(opened)                     # ★RX3-0263（★開けた扉を地図へ渡したか）
        return "grid.txt"

    def appearance_label(self, app): return "主" if app == 28 else "？"

    def current_npcs(self, map_id, t, tbl):
        """★Master ＋ Runtime（⚠ 辿り着けるかは問わない）。"""
        return {"map_id": map_id, "status": "DEFAULT", "npcs": list(self.npcs), "runtime_count": len(self.npcs)}

    def record_heard(self, map_id, t, slot, talk_id, text, at=None, npc_tbl_hex=None, npc=None):
        npc = npc or next(n for n in self.npcs if n["slot"] == slot)
        self.heard.record(map_id, npc["npc_id"], talk_id, at="t", text=text)
        return {"npc_id": npc["npc_id"], "talk_id": talk_id}

    def record_heard_npc(self, map_id, time_byte, npc_id, text, *, npc_tbl_hex=None,
                         phase=None, at=None):
        """★手で話した相手を npc_id で書く（RX3-0282）。⚠ 本物と同じ「表に居るか」で断る。"""
        npc = next((n for n in self.npcs if int(n["npc_id"]) == int(npc_id)), None)
        if npc is None:
            return None
        return self.record_heard(map_id, time_byte, npc["slot"], npc.get("talk_id"), text,
                                 at=at, npc_tbl_hex=npc_tbl_hex, npc=npc)


class _Commands:
    def __init__(self): self.sent = []; self.seq = 0
    def send(self, action, **params):
        self.seq += 1; self.sent.append((action, params)); return self.seq


@pytest.fixture
def world(tmp_path):
    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    clock = [0.0]
    # ⚠ 行動履歴は**この検査だけのもの**を渡す（★共有だと他の検査の行が混ざる）
    from dq3 import action_log as AL

    ctl = TownNavController(vm, svc, cmd, clock=lambda: clock[0],
                            action_log=AL.ActionLog(clock=lambda: clock[0]))
    return vm, svc, cmd, ctl, clock


def test_面識が無ければ目的地は空で街移動は頼めない(world):
    vm, svc, cmd, ctl, _ = world
    assert ctl.facilities() == []
    assert ctl.start_move("inn") is False and cmd.sent == []


def test_聞き込みはtalk0を飛ばし近い順に回りheardを残す(world):
    vm, svc, cmd, ctl, clock = world
    assert ctl.start_hearing()
    action, p = cmd.sent[-1]
    assert action == "navigate" and p["talk"] == "1" and p["close"] == "1" and p["npc_slot"] == "-1"
    assert vm.talk_tag == {"label": "主", "npc_id": 1, "map_id": 9}
    # ★Lua が終わり、窓の文が勇者メモへ流れ、窓が閉じた
    vm.nav = {"seq": 1, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    vm.last_talk_text = "＊「ようこそ。ここは やどやですよ。"      # ★架空の文 / RX3-0433
    ctl.poll()
    assert svc.heard.is_heard(9, 1) and svc.heard.texts(9, 1)[0]["text"].startswith("＊「ようこそ")
    # ★次は動く NPC（talk 0 の #3 は候補に出ない）
    action, p = cmd.sent[-1]
    assert p["npc_slot"] == "10" and vm.talk_tag["npc_id"] == 6
    vm.nav = {"seq": 2, "active": False, "phase": "done", "reason": "skip_unreachable_now"}
    ctl.poll()
    assert ctl.mode is None and ctl.message.startswith("聞き込み完了")
    assert 6 in ctl.skipped and not svc.heard.is_heard(9, 6)          # ★heard = false は保つ（§6）
    # ★面識ができた宿屋だけ目的地に出る
    assert [f["role"] for f in ctl.facilities()] == ["inn"]


def test_街移動は着いたら話しかけて窓を開けたまま終わる(world):
    """★2026-09-12 依頼者「街移動したらAボタン押したい（コマンド実行まで自動）」（RX3-0197）。

    ★補充と同じ `talk=1 / close=0`（A → はなす / ⚠ 窓は閉じない: B が「いいえ」になる）。
    """
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    action, p = cmd.sent[-1]
    assert p["talk"] == "1", "⚠⚠ 着いても A を押さない（★RX3-0197）"
    assert p["close"] == "0", "⚠⚠ 話した窓を B で閉じる（★宿・店の問いに「いいえ」と答えてしまう）"
    assert p["face"] == "up"
    vm.nav = {"seq": 1, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    assert ctl.mode is None and "着きました" in ctl.message, "⚠ 話しかけて終わったのに失敗扱い: %s" % ctl.message


def test_聞き込みだけが_はい_の字をLuaへ渡し_答えられなければ止まる(world):
    """⚠⚠ 2026-09-12 依頼者「イシス（save6）でやはり再発する『またすぐにたびたつつもりですか？』系」（RX3-0194）。

    ★Lua が Q2 の窓を探す字（はい / いいえ）は、窓を B で閉じる**聞き込みだけ**に渡す。
    ⚠ 答えられずに止まったら、★次の人へ進まず人へ返す（⚠ 窓は開いたまま / B = いいえ はゲームが終わる）。

    ★2026-09-13（RX3-0241）: 宿屋への街移動は、泊まるかの問いに はい で答えるため字を渡す
    （→ `test_宿屋への街移動は最初の台詞で止め_はい_の字を渡す`）。★ここは宿屋でない施設で見る。
    """
    vm, svc, cmd, ctl, _ = world
    svc.depart_answer_params = lambda: {"yes": "3031", "no": "313132"}
    svc.npcs[0]["role"] = "item_shop"
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("item_shop")
    _, p = cmd.sent[-1]
    assert "yes" not in p and "no" not in p, "⚠ 街移動（窓を閉じない）に はい の字を渡した"
    vm.nav = {"seq": 1, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    assert ctl.start_hearing()
    _, p = cmd.sent[-1]
    assert p["yes"] == "3031" and p["no"] == "313132", "⚠⚠ 聞き込みに はい の字を渡していない: %s" % p
    sent = len(cmd.sent)
    vm.nav = {"seq": cmd.seq, "active": False, "phase": "done", "reason": "depart_question_unanswered"}
    ctl.poll()
    assert ctl.mode is None, "⚠⚠ 窓が開いたまま次の人へ進んだ"
    assert len(cmd.sent) == sent or all(a != "navigate" for a, _ in cmd.sent[sent:]), "⚠⚠ 次の人へ頼んだ"
    assert "はい" in ctl.message, ctl.message


def test_選択肢が繰り返したら止めて人に返す(world):
    """★RX3-0273: Lua が選択肢の繰り返し（$8743 が 3 回）で B をやめて止めた → ★heard に記し、窓は人に返す。

    ⚠ RX3-0217 では B を 16 回押して「窓が閉じません」で止まり、記録は残った。★ここは止め方が早いだけで記録は同じ。
    """
    vm, svc, cmd, ctl, _ = world
    ctl.start_hearing()
    vm.talk = {"slot": 5, "talk_id": 11}
    vm.last_talk_text = "まあ そういわずに"
    vm.window_open = True
    sent = len(cmd.sent)
    vm.nav = {"seq": cmd.seq, "active": False, "phase": "done", "reason": "choice_repeated"}
    ctl.poll()
    assert ctl.mode is None, "⚠⚠ 窓が開いたまま次の人へ進んだ"
    assert svc.heard.is_heard(9, 1), "⚠ 話した記録が残らない（★言葉で見分ける仕組みが効かなくなる）"
    assert all(a != "navigate" for a, _ in cmd.sent[sent:]), "⚠⚠ 次の人へ頼んだ"
    assert "選択肢" in ctl.message and "はい" in ctl.message, ctl.message


def test_Aを押しただけでは会話にしない(world):
    vm, svc, cmd, ctl, clock = world
    ctl.start_hearing()
    vm.nav = {"seq": 1, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    ctl.poll()                                    # ★文はまだ来ていない → 待つ
    assert not svc.heard.is_heard(9, 1) and ctl.mode == "hearing"
    clock[0] += 100.0
    ctl.poll()                                    # ⚠ 待ちきれない → 会話なしとして次へ
    assert not svc.heard.is_heard(9, 1) and 1 in ctl.skipped


def test_停止で次へ進まない(world):
    vm, svc, cmd, ctl, _ = world
    ctl.start_hearing()
    ctl.stop()
    # ★RX3-0170: 止めたら nav_stop、続けて town_end（★Lua の Turbo を切る / nav も止める）
    assert [a for a, _ in cmd.sent][-2:] == ["nav_stop", "town_end"], cmd.sent
    assert cmd.sent[-1][1]["source"] == "HEARING_CANCEL"
    assert ctl.mode is None and vm.talk_tag is None


def test_辿り着けない人が残ったら件数を出して記録する(world):
    """⚠⚠ RX3-0077（2026-09-05）: セーブ 5 の城で 14 人中 5 人が扉の向こうで、
    ★候補から黙って外れたまま「聞き込み完了」と出ていた（依頼者には「反映されない」に見えた）。
    → ★残った人は skip（unreachable_now）に記録し、件数を文に出す。
    """
    vm, svc, cmd, ctl, clock = world
    svc.unreachable = {6}                          # ★npc 6 は今は辿り着けない（扉の向こう）
    assert ctl.start_hearing()
    # ★npc 1（宿屋）と話して heard に
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    vm.last_talk_text = "いらっしゃい"
    ctl.poll()
    assert ctl.mode is None, ctl.message
    assert svc.heard.is_heard(9, 1)
    # ⚠ 2026-09-07（RX3-0102）: 画面は**件数だけ**（★内訳は行動履歴の 1 行へ）
    assert ctl.message == "聞き込み完了 1人 / 未完1人", ctl.message
    assert len(ctl.message) <= TB.STATUS_MAX, "⚠⚠ 右パネルの幅を超える"
    last = ctl.action_log.rows[-1]
    assert last.line() == "[聞き込み] 完了：1人と会話 / 未完1人（到達不能1）", last.line()
    assert 6 in ctl.skipped and not svc.heard.is_heard(9, 6)          # ★heard = false は保つ
    assert any(e.get("skip") == 6 and e.get("reason") == "unreachable_now" for e in ctl.log)
    # ⚠ talk_id = 0（npc 3）は数えない
    assert 3 not in ctl.skipped


def test_勇者メモの行は見た目の字で始まる():
    assert TSV.TownService.memo_text("商", "＊「ここは どうぐやです。") == "商「ここは どうぐやです。」"
    assert TSV.TownService.memo_text("？", "「そうか」") == "？「そうか」"


def test_一行UIが作れて実行中は停止になる(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from dq3.ui.town_bar import TownBar

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    bar = TownBar(vm, svc, cmd)
    # ★RX3-0257: 街移動は [宿][道][武][神]（⚠ 面識が無ければ最初から押せない）
    assert [b.text() for b in bar.move_buttons.values()] == ["宿", "道", "武", "神", "入"]
    # ★RX3-0290: ボタンは 1 文字（⚠ 正式な名前はツールチップ / ★記録の文言は「聞き込み」のまま）
    assert bar.hear_button.text() == "聞" and "聞き込み" in bar.hear_button.toolTip()
    assert bar.restock_button.text() == "補" and "補充" in bar.restock_button.toolTip()
    assert not any(b.isEnabled() for b in bar.move_buttons.values())
    bar._on_hear()
    assert bar.hear_button.text() == "止" and not any(b.isEnabled() for b in bar.move_buttons.values())
    bar._on_hear()
    assert bar.hear_button.text() == "聞"
    assert [a for a, _ in cmd.sent][-2:] == ["nav_stop", "town_end"], cmd.sent


def test_補充の横に設定ボタンがあり窓は1つだけ(tmp_path):
    """★RX3-0212: 補充設定の窓は町の行の［…］から（⚠ 2 つ開かない / 設定が無ければ開かない）。"""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from dq3.ui.town_bar import TownBar
    from dq3.ui.ui_settings import UiSettings

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    TownBar(vm, svc, cmd).open_restock_settings()             # ⚠ 設定が無い → 何もしない（落ちない）
    bar = TownBar(vm, svc, cmd, settings=UiSettings(tmp_path / "ui.json"))
    assert bar.restock_settings_button.text() == "…"
    bar.open_restock_settings()
    first = bar._restock_window
    bar.open_restock_settings()
    assert first is not None and bar._restock_window is first, "⚠ 補充設定の窓が 2 つ開く"
    first.close()


def test_聞き込み中は環境の設定を保ち終わったら戻す(world):
    """★2 倍速の hook（RX3-0059 ②）: 途中は keep で送り直し、終わりで end。"""
    vm, svc, cmd, ctl, clock = world

    class Hook:
        def __init__(self): self.calls = []
        def begin(self, w): self.calls.append("begin")
        def keep(self, w): self.calls.append("keep")
        def end(self, w, why="DONE"): self.calls.append("end")

    ctl.env_hook = Hook()
    ctl.start_hearing()
    assert ctl.env_hook.calls == ["begin"]
    ctl.poll()                                    # ★最初の poll で keep
    clock[0] += 3.0
    ctl.poll()                                    # ⚠ 5 秒経っていない → 送らない
    clock[0] += 3.0
    ctl.poll()
    assert ctl.env_hook.calls.count("keep") == 2
    ctl.stop()
    assert ctl.env_hook.calls[-1] == "end"


def test_街移動も環境の設定を使い着いたら戻す(world):
    vm, svc, cmd, ctl, clock = world

    class Hook:
        def __init__(self): self.calls = []
        def begin(self, w): self.calls.append("begin:" + w)
        def keep(self, w): self.calls.append("keep:" + w)
        def end(self, w, why="DONE"): self.calls.append("end:" + w)

    ctl.env_hook = Hook()
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": 1, "active": True, "phase": "walk"}
    ctl.poll()
    vm.nav = {"seq": 1, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    assert ctl.env_hook.calls == ["begin:move", "keep:move", "end:move"]


# ----------------------------------------------------------------------
# ⚠⚠ 実行環境（Turbo ＋ 無音 / 旧 400%）を **どの終わり方でも**戻す（RX3-0104 / RX3-0170）
# ----------------------------------------------------------------------
class _Env:
    """★本物の `AutoOperationEnvironment` と同じ形（⚠ 深さを数える）。"""

    def __init__(self):
        self.depth = 0
        self.calls = []
        self.whys = []

    def begin(self, what):
        self.depth += 1
        self.calls.append("begin:" + what)

    def keep(self, what):
        self.calls.append("keep:" + what)

    def end(self, what, why="DONE"):
        self.depth -= 1
        self.calls.append("end:" + what)
        self.whys.append(why)

    def finish(self, what):
        """★ゲームへ操作を返す（RX3-0116）。⚠ 速度・Mute の**あと**。"""
        self.calls.append("finish:" + what)
        return True


def _run_to_end(world, kind, reason):
    vm, svc, cmd, ctl, clock = world
    env = ctl.env_hook = _Env()
    if kind == "move":
        svc.heard.record(9, 1, 11, at="t")
        assert ctl.start_move("inn")
    else:
        assert ctl.start_hearing()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": reason}
    for _ in range(4):                       # ★聞き込みは次の相手へ進むので何度か回す
        ctl.poll()
        if ctl.mode is None:
            break
        vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": reason}
    return env


@pytest.mark.parametrize("reason", ["arrived", "path_blocked", "path_deviation"])
def test_街移動はどの終わり方でも環境を戻す(world, reason):
    env = _run_to_end(world, "move", reason)
    assert env.depth == 0, "⚠⚠ Turbo・無音のまま返した（%s）: %s" % (reason, env.calls)


@pytest.mark.parametrize("reason", ["skip_unreachable_now", "path_blocked", "face_moved"])
def test_聞き込みはどの終わり方でも環境を戻す(world, reason):
    env = _run_to_end(world, "hearing", reason)
    assert env.depth == 0, "⚠⚠ Turbo・無音のまま返した（%s）: %s" % (reason, env.calls)


def test_ユーザーが止めても環境を戻す(world):
    vm, svc, cmd, ctl, clock = world
    env = ctl.env_hook = _Env()
    ctl.start_hearing()
    ctl.stop()
    # ⚠ 順番: 速度・Mute を戻す → サマリー → ★ゲームへ操作を返す（RX3-0116）
    assert env.depth == 0 and env.calls[-2:] == ["end:hearing", "finish:hearing"]


def test_Luaへ頼めなくても環境を戻す(world):
    """⚠⚠ ここが抜けていました（★`_navigate` の失敗だけ `_finish` を通らなかった）。"""
    vm, svc, cmd, ctl, clock = world
    env = ctl.env_hook = _Env()

    def boom(action, **params):
        raise OSError("⚠ 書けません")

    cmd.send = boom
    assert ctl.start_hearing() is False
    assert ctl.mode is None, "⚠ mode が残っている（★次に押せなくなる）"
    assert env.depth == 0, "⚠⚠ Turbo・無音のまま返した: %s" % env.calls


def test_歩数を数えている(world):
    """★ユーザー向けサマリーに出す歩数（RX3-0110）。"""
    vm, svc, cmd, ctl, clock = world
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    assert ctl.steps == 3


# ======================================================================
# ★補充（RX3-0066 / RX3-0119 / 2026-09-08）
# ======================================================================
#
# ⚠⚠ **買い物は取り返しがつきません。** ★ここで守るのは
#   「買うものが無ければ歩きもしない」「終わりに 1 行だけ出す」です。

def _shop_world(world, *, gold=1000, bag=(0xFF,) * 8):
    """★道具屋に面識があり、袋と所持金が読める状態。"""
    vm, svc, cmd, ctl, clock = world
    svc.npcs[0]["role"] = "item_shop"
    svc.heard.record(9, 1, 11, at="t", text="＊「ここは どうぐやです。")
    vm.gold = lambda: gold
    vm.equip_members = lambda: [{"name": "p1", "inventory": list(bag)}]
    vm.restock = None
    vm.restock_status = lambda: vm.restock
    ctl.restock_wants = [(101, 3)]                    # ★やくそう 3 個
    return vm, svc, cmd, ctl, clock


def _shop_items(monkeypatch, items=(101, 102)):
    """⚠ ROM を読まずに品揃えを差し替える（★UI の段取りだけを見る）。"""
    from dq3.knowledge import item_info as II

    class _Shop:
        role = "item_shop"

    shop = _Shop()
    shop.items = tuple(items)
    monkeypatch.setattr(II, "shops_by_map", lambda *a, **k: {9: [shop]})


def test_足りていれば歩きもしない(world, monkeypatch):
    """⚠⚠ ★**ボタンを 1 つも押さない**（歩く頼みも出さない）。"""
    vm, svc, cmd, ctl, clock = _shop_world(world, bag=(101, 101, 101) + (0xFF,) * 5)
    _shop_items(monkeypatch)
    assert ctl.start_restock() is False
    assert cmd.sent == [], "⚠⚠ 買うものが無いのに頼んだ: %s" % cmd.sent
    assert ctl.mode is None
    rows = ctl.action_log.rows
    assert rows and rows[-1].action == "restock"
    assert rows[-1].status_label == "停止"
    assert "足りている" in rows[-1].message


@needs_rom
def test_買うものがあれば歩いて話す(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    assert ctl.start_restock() is True
    assert ctl.mode == "restock"
    action, params = cmd.sent[-1]
    assert action == "navigate"
    assert params["talk"] == "1"
    # ⚠⚠ **窓を閉じない**（★店の窓を開けたまま Lua へ渡す）
    assert params["close"] == "0", params


@needs_rom
def test_着いたら補充を頼む(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    action, params = cmd.sent[-1]
    assert action == "restock"
    # ★品名・かいにきた・はい／いいえ を**タイル列**で渡す
    # ★RX3-0202: 1 個ごとの持ち主（carriers）と「もてない」の語（full）も渡す
    for key in ("trade", "items", "carrier", "carriers", "full", "yes", "no"):
        assert params.get(key), (key, params)
    assert params["items"].endswith(":3:8"), params["items"]


@needs_rom
def test_店まで行けなければ頼まない(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "path_blocked"}
    ctl.poll()
    assert all(a != "restock" for a, _ in cmd.sent), cmd.sent
    assert ctl.mode is None
    assert ctl.action_log.rows[-1].status_label == "中断"


@needs_rom
def test_買えたら1行出す(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    vm.restock = {"phase": "done", "reason": "bought", "bought": 3, "spent": 24}
    ctl.poll()
    assert ctl.mode is None
    got = ctl.action_log.rows[-1]
    assert got.action_label == "リストック" and got.status_label == "完了"
    assert "やくそう 3個" in got.message and "24 G" in got.message


@needs_rom
def test_途中までなら完了と言い切らない(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    vm.restock = {"phase": "done", "reason": "not_bought", "bought": 1, "spent": 8}
    ctl.poll()
    got = ctl.action_log.rows[-1]
    assert got.status == "PARTIAL", got
    assert "1個" in got.message


@needs_rom
def test_1個も買えなければ中断(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    vm.restock = {"phase": "done", "reason": "no_shop_window", "bought": 0, "spent": 0}
    ctl.poll()
    assert ctl.action_log.rows[-1].status_label == "中断"


@needs_rom
def test_黙っていても必ず終わる(world, monkeypatch):
    """⚠⚠ Lua が答えなくても、★画面は待ち続けない。"""
    from dq3.ui.town_bar import RESTOCK_WAIT_S

    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.start_restock()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    vm.restock = {"phase": "list", "bought": 0}
    clock[0] += RESTOCK_WAIT_S + 1
    ctl.poll()
    assert ctl.mode is None
    assert any(a == "restock_stop" for a, _ in cmd.sent), cmd.sent


@needs_rom
def test_補充もTurboで無音にして戻す(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    env = _Env()
    ctl.env_hook = env
    ctl.start_restock()
    assert env.calls[0] == "begin:restock"
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    vm.restock = {"phase": "done", "reason": "bought", "bought": 3, "spent": 24}
    ctl.poll()
    # ⚠⚠ 順番（★速度・Mute を戻す → サマリー → ゲームへ戻す / RX3-0116）
    assert env.calls[-2:] == ["end:restock", "finish:restock"], env.calls


@needs_rom
def test_目標の書き方を読む():
    from dq3.ui.town_bar import parse_wants

    got = dict(parse_wants("やくそう:6, どくけしそう:2"))
    assert got == {101: 6, 102: 2}
    # ⚠ 知らない名前・0 個は入れない（★打ち間違いで補充ごと止めない）
    assert parse_wants("ふしぎなもの:3") == []
    assert parse_wants("やくそう:0") == []


def test_設定が無くても既定で動く():
    """★RX3-0482（2026-10-02 依頼者）: 新規利用の既定は やくそう 3 / どくけしそう 1 / キメラのつばさ 1。

    ⚠ 補充の層（`dq3.knowledge.restock.DEFAULT_WANTS`）の既定とも同じ値（★画面と実際に使う値を揃える）。
    """
    from dq3.knowledge import restock as RS
    from dq3.ui.town_bar import DEFAULT_WANTS, keep_gold, restock_wants

    assert restock_wants(None) == [(101, 3), (102, 1), (104, 1)] == list(DEFAULT_WANTS)
    assert list(RS.DEFAULT_WANTS) == list(DEFAULT_WANTS), "⚠⚠ 既定が 2 か所で食い違っている"
    assert keep_gold(None) == 0


@needs_rom
def test_保存があれば既定より保存を優先する(tmp_path):
    """★RX3-0258 §5: 既存の値を優先（★旧い既定 キメラのつばさ 1 のまま保存している人は、そのまま）。"""
    from dq3.ui.town_bar import restock_wants
    from dq3.ui.ui_settings import UiSettings

    settings = UiSettings(tmp_path / "ui.json")
    settings.set("admin", "restock_wants", "やくそう:6,どくけしそう:2,キメラのつばさ:1")
    assert restock_wants(settings) == [(101, 6), (102, 2), (104, 1)]
    settings.set("admin", "restock_wants", "なし")
    assert restock_wants(settings) == [], "⚠⚠ 全部 0 にしたのに既定の目標で買う"


# ======================================================================
# ★RX3-0170: 聞き込み・街移動・補充を Turbo で走らせる
#
#   ★Turbo は Lua（town_speed.lua）が持つ。画面は街の頼みに turbo="1" を添え、終わりに town_end。
#   ⚠ Turbo の入り切りを別の頼みにしない（★置き場が 1 つなので、直後の navigate に上書きされる）。
# ======================================================================
def _real_env(enabled=lambda what: True):
    from dq3.ui import auto_env as AE
    from dq3.ui import emu_speed as ES

    lines = []
    speed = ES.EmulatorSpeedController(sender=lambda c: True, finder=lambda: 1)
    env = AE.AutoOperationEnvironment(speed, None, enabled=enabled, log=lines.append)
    return env, lines


def test_聞き込みの頼みにTurboを添える(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    assert ctl.start_hearing()
    action, p = cmd.sent[-1]
    assert action == "navigate" and p["turbo"] == "1" and p["source"] == "HEARING", p
    assert [a for a, _ in cmd.sent] == ["navigate"], "⚠⚠ Turbo を別の頼みにした（★上書きされて消える）"
    assert lines[:2] == ["[HEARING] START", "[SPEED] NORMAL -> TURBO source=HEARING"], lines


def test_高速実行を切った街移動はTurboを添えない(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env(enabled=lambda what: what != "move")
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    assert cmd.sent[-1][1]["turbo"] == "0" and cmd.sent[-1][1]["source"] == "MOVE"
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    assert [a for a, _ in cmd.sent] == ["navigate", "town_end"], cmd.sent
    assert cmd.sent[-1][1] == {"source": "MOVE_DONE"}
    assert "[SPEED] NORMAL -> TURBO source=MOVE" not in lines, lines


def test_着いたらtown_endでLuaのTurboを切る(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    assert cmd.sent[-1] == ("town_end", {"source": "MOVE_DONE"}), cmd.sent
    assert lines[-2:] == ["[SPEED] TURBO -> NORMAL source=MOVE_DONE", "[MOVE] DONE reason=arrived"], lines
    assert ctl.env_hook.active() is False


def test_戦闘になったら止めて戻す(world):
    """★依頼者 §15: 遭遇 → 聞き込みを止める → Turbo・無音を戻す（★Lua は先に切っている）。"""
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    assert ctl.start_hearing()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "battle"}
    ctl.poll()
    assert ctl.mode is None
    assert ctl.message == "⚠ 戦闘になりました", ctl.message
    assert cmd.sent[-1] == ("town_end", {"source": "HEARING_BATTLE"}), cmd.sent
    assert "[SPEED] TURBO -> NORMAL source=HEARING_BATTLE" in lines, lines
    assert lines[-1] == "[HEARING] BATTLE talked=0 unreachable=0 reason=battle", lines
    assert ctl.action_log.rows[-1].line().startswith("[聞き込み]"), ctl.action_log.rows[-1].line()
    assert "戦闘になりました" in ctl.action_log.rows[-1].line()


def test_LuaがBで止めたら中断として戻す(world):
    """★依頼者 §14: 人がゲームの B（キーボードの D）を押した → Lua が止めて数える。"""
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    raw = {"town_speed": {"cancels": 3}}
    vm._raw = lambda: raw
    assert ctl.start_hearing()
    ctl.poll()
    assert ctl.mode == "hearing", "⚠ 前の操作の B で止めた"
    raw["town_speed"] = {"cancels": 4}
    ctl.poll()
    assert ctl.mode is None and ctl.message == "停止しました"
    assert cmd.sent[-1] == ("town_end", {"source": "HEARING_CANCEL"}), cmd.sent
    assert ctl.action_log.rows[-1].status_label == "停止"


def test_Luaが止めたと返したら中断として扱う(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "stopped_by_user"}
    ctl.poll()
    assert ctl.mode is None and ctl.message == "停止しました"
    assert cmd.sent[-1] == ("town_end", {"source": "MOVE_CANCEL"})


def test_聞き込みの終わりに人数をログへ出す(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    svc.unreachable = {6}
    assert ctl.start_hearing()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    vm.last_talk_text = "いらっしゃい"
    ctl.poll()
    assert ctl.mode is None
    assert lines[-1] == "[HEARING] DONE talked=1 unreachable=1", lines
    assert "[SPEED] TURBO -> NORMAL source=HEARING_DONE" in lines


# ======================================================================
# ⚠⚠ RX3-0230（save1 バハラタ / 2026-09-13）: 人の表が読めないとき・記録できなかったとき
# ======================================================================
class _UnknownService(_Service):
    """★差し替えのある map で、実機の表と合わない（★status = UNKNOWN / 候補 0）。"""

    def current_npcs(self, map_id, t, tbl):
        return {"map_id": map_id, "status": "UNKNOWN", "npcs": [], "runtime_count": 17}

    def unheard_reachable_npcs(self, map_id, t, tbl, start, *, keys=()):
        return []


def test_表が読めないときは_もう全員とは言わない(tmp_path):
    from dq3 import action_log as AL

    vm, svc, cmd = _VM(), _UnknownService(tmp_path), _Commands()
    ctl = TownNavController(vm, svc, cmd, clock=lambda: 0.0,
                            action_log=AL.ActionLog(clock=lambda: 0.0))
    here = ctl._here()
    assert ctl._nobody_text(here) == "この町の人の表が読めません"
    assert ctl._nobody_text(here, short=True) == "この町の人の表が読めません"
    assert ctl.start_hearing() is False
    assert ctl.mode is None and ctl.message == "この町の人の表が読めません"


def test_表が読めればわけは今までどおり(world):
    """★DEFAULT の表では新しい文を出さない（★全員聞いた / 話せる人がいない は RX3-0157 のまま）。"""
    vm, svc, cmd, ctl, clock = world
    for n in svc.npcs:
        svc.heard.record(9, n["npc_id"], n["talk_id"], at="t")
    assert ctl._nobody_text(ctl._here()) != "この町の人の表が読めません"


def test_話したのに記録できなければ黙って数えない(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    svc.record_heard = lambda *a, **k: None          # ★表が読めない / slot が表に無い
    assert ctl.start_hearing()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    vm.last_talk_text = "いらっしゃい"
    ctl.poll()
    assert ctl.done_count == 0, "⚠⚠ 記録できなかった人を「話した」に数えた"
    assert 1 in ctl.skipped and not svc.heard.is_heard(9, 1)
    assert any(r.get("skip") == 1 and r.get("reason") == "record_failed" for r in ctl.log), ctl.log
    assert any("RECORD_FAILED" in line for line in lines), lines
    assert ctl._skip_counts() == {"記録できず": 1}


@needs_rom
def test_補充と扉の頼みにもTurboを添える(world, monkeypatch):
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    ctl.env_hook, lines = _real_env()
    ctl.start_restock()
    assert cmd.sent[-1][1]["turbo"] == "1" and cmd.sent[-1][1]["source"] == "RESTOCK"
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    action, p = cmd.sent[-1]
    assert action == "restock" and p["turbo"] == "1" and p["source"] == "RESTOCK", p


# ======================================================================
# ★★ RX3-0241（2026-09-13）: 街移動は施設の人の最初の台詞で高速化を解き、施設ごとに止める
#
#   ⚠⚠ 依頼者の小WI（`docs/requests/260913_dq3-facility-stop.md`）。★宿屋は泊まるかの問いに はい まで /
#     道具屋・武器防具屋・教会は最初の台詞で止める / リストックは店の話が出ている状態からも始められる。
#   ★Lua 側（最初の台詞の見分け・$A55C・Turbo を切る）は `dq3_nav_v0_test.lua` / `dq3_town_speed_test.lua`。
# ======================================================================
def test_宿屋への街移動は最初の台詞で止め_はい_の字を渡す(world):
    vm, svc, cmd, ctl, clock = world
    svc.depart_answer_params = lambda: {"yes": "3031", "no": "313132"}
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    _, p = cmd.sent[-1]
    assert p["stop_at"] == "first_message" and p["facility"] == "inn", p
    assert p["yes"] == "3031" and p["no"] == "313132", "⚠⚠ 宿屋の問いに はい で答える字を渡していない: %s" % p
    assert p["close"] == "0", "⚠⚠ 宿屋の窓を B で閉じる（★B = いいえ）"


def test_宿屋でない施設には_はい_の字を渡さない(world):
    vm, svc, cmd, ctl, clock = world
    svc.depart_answer_params = lambda: {"yes": "3031", "no": "313132"}
    svc.npcs[0]["role"] = "item_shop"
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("item_shop")
    _, p = cmd.sent[-1]
    assert p["stop_at"] == "first_message" and p["facility"] == "item_shop", p
    assert "yes" not in p and "no" not in p, "⚠⚠ 道具屋に はい の字を渡した（★購入・売却は選ばない）"


@needs_rom
def test_聞き込みと補充は最初の台詞で止めない(world, monkeypatch):
    vm, svc, cmd, ctl, clock = world
    assert ctl.start_hearing()
    assert "stop_at" not in cmd.sent[-1][1], "⚠⚠ 聞き込みを最初の台詞で止める: %s" % (cmd.sent[-1],)
    ctl.stop()
    _shop_world(world)
    _shop_items(monkeypatch)
    assert ctl.start_restock() is True
    action, p = cmd.sent[-1]
    assert action == "navigate" and "stop_at" not in p, "⚠⚠ 補充（パターン A）を最初の台詞で止める: %s" % p


def test_最初の台詞で速度と音を開始前へ戻し_終わりで二重に戻さない(world):
    vm, svc, cmd, ctl, clock = world
    ctl.env_hook, lines = _real_env()
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    assert ctl.env_hook.speed.current == 4.0
    vm.nav = {"seq": ctl.seq, "active": True, "phase": "inn", "first_message": 1234, "facility": "inn"}
    ctl.poll()
    assert ctl.env_hook.speed.current == 1.0, "⚠⚠ 最初の台詞のあとも区間減速の倍率（400%）のまま"
    assert ctl.env_hook.active() and ctl.env_hook.params()["turbo"] == "0"
    assert "[MOVE] FIRST_MESSAGE facility=inn" in lines, lines
    assert "[SPEED] TURBO -> NORMAL source=MOVE_FIRST_MESSAGE" in lines, lines
    ctl.poll()
    assert lines.count("[MOVE] FIRST_MESSAGE facility=inn") == 1, "⚠ 2 回戻した: %s" % lines
    assert ctl.mode == "move", "⚠⚠ 宿屋の はい を待たずに終えた"
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "inn_yes", "first_message": 1234}
    ctl.poll()
    assert ctl.mode is None and "はい" in ctl.message, ctl.message
    assert ctl.env_hook.active() is False
    assert sum("TURBO -> NORMAL" in line for line in lines) == 1, "⚠ 戻したあとにもう一度戻した: %s" % lines
    assert cmd.sent[-1] == ("town_end", {"source": "MOVE_DONE"}), cmd.sent
    assert ctl.action_log.rows[-1].status_label == "完了"


def test_施設の最初の台詞で止まったら着いたことにする(world):
    vm, svc, cmd, ctl, clock = world
    svc.npcs[0]["role"] = "item_shop"
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("item_shop")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "first_message", "first_message": 99}
    ctl.poll()
    assert ctl.mode is None and "着きました" in ctl.message, ctl.message
    assert ctl.action_log.rows[-1].status_label == "完了"


def test_宿屋の問いに答えられなければ人へ返す(world):
    vm, svc, cmd, ctl, clock = world
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "inn_question_unanswered"}
    ctl.poll()
    assert ctl.mode is None and "宿屋の問い" in ctl.message, ctl.message
    assert ctl.action_log.rows[-1].status_label == "中断"


@needs_rom
def test_店の人の話が出ていれば話しかけ直さずに補充を頼む(world, monkeypatch):
    """★パターン B（指示書 §4）: 街移動 → 道具屋の最初の台詞で停止 → 人がリストック → ★その会話から買う。"""
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    env = ctl.env_hook = _Env()
    vm.window_open = True
    vm.talk = {"slot": 5, "talk_id": 11}              # ★最後に話した相手 = この店の人
    assert ctl.start_restock() is True
    assert [a for a, _ in cmd.sent] == ["restock"], "⚠⚠ 話しかけ直した（★歩く頼みの B で店の窓を閉じる）: %s" % cmd.sent
    for key in ("trade", "items", "yes", "no"):
        assert cmd.sent[-1][1].get(key), (key, cmd.sent[-1])
    assert env.calls[0] == "begin:restock"
    vm.restock = {"phase": "done", "reason": "bought", "bought": 3, "spent": 24}
    ctl.poll()
    assert ctl.mode is None and ctl.action_log.rows[-1].status_label == "完了"
    assert env.depth == 0 and cmd.sent[-1][0] == "town_end"


@needs_rom
@pytest.mark.parametrize("open_, talk_id", [(False, 11), (True, 0x247), (True, None)])
def test_店の話でなければ今までどおり歩いて話す(world, monkeypatch, open_, talk_id):
    """★パターン A（指示書 §4）: 窓が出ていない / 最後に話したのが店の人でない → ★今までどおり歩いて話す。"""
    vm, svc, cmd, ctl, clock = _shop_world(world)
    _shop_items(monkeypatch)
    vm.window_open = open_
    vm.talk = {"slot": 5, "talk_id": talk_id} if talk_id is not None else None
    assert ctl.start_restock() is True
    assert cmd.sent[-1][0] == "navigate", cmd.sent


# --- ★RX3-0257 街移動を 1 クリックに（[宿][道][武][神] / 同じボタンで候補を循環）-------------------
#
#   依頼者 2026-09-14 の小WI（★正本の写し `docs/requests/260914_dq3-town-move-buttons.md`）。
#   ★実データ: 同じ種類の店が 2 軒あるのは アッサラーム（武器・防具屋 NPC 8 / 12）と イシス（道具屋 NPC 3 / 12）。

def _two_item_shops(svc, *, order=(7, 4)):
    """★道具屋が 2 軒（★わざと NPC 番号の逆順に並べる = 台帳の並びではなく番号で並ぶかを見る）。"""
    for i, npc_id in enumerate(order):
        svc.npcs.append({"npc_id": npc_id, "slot": 20 + i, "x": 10 + i * 5, "y": 5, "movement": "fixed",
                         "appearance_id": 44, "talk_id": 0x300 + npc_id, "role": "item_shop",
                         "role_status": "CONFIRMED"})
        svc.heard.record(9, npc_id, 0x300 + npc_id, at="t")
    labels = {"inn": "宿屋", "item_shop": "道具屋"}
    svc.known_reachable_facilities = lambda m, t, tbl, start: [
        {"role": n["role"], "label": labels[n["role"]], "npc": n, "plan": svc._plan(n)}
        for n in svc.npcs if n["role"] and svc.heard.is_heard(m, n["npc_id"])]


def _arrive(vm, ctl):
    """★Lua が施設の人の最初の台詞で止めた（★街移動の終わり方 / RX3-0241）。"""
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "first_message"}
    ctl.poll()
    assert ctl.mode is None, ctl.message


def _walking(vm, ctl):
    vm.nav = {"seq": ctl.seq, "active": True, "phase": "walk"}


def test_ボタン4つで押せば移動が始まる_プルダウンも移動ボタンも無い(tmp_path):
    from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

    QApplication.instance() or QApplication([])
    from dq3.ui.town_bar import TownBar

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    svc.heard.record(9, 1, 11, at="t")                        # ★宿屋だけ面識がある
    bar = TownBar(vm, svc, cmd)
    assert [b.text() for b in bar.move_buttons.values()] == ["宿", "道", "武", "神", "入"]
    assert not bar.findChildren(QComboBox), "⚠⚠ プルダウンが残っている（★併存させない）"
    assert not any(b.text() in ("街移動", "移動") for b in bar.findChildren(QPushButton)), "⚠ 移動ボタンを別に置いた"
    enabled = {r: b.isEnabled() for r, b in bar.move_buttons.items()}
    # ★[入]（RX3-0291）は「入ってきた升」を見ていないので押せない（⚠ 面識とは別の理由）
    assert enabled == {"inn": True, "item_shop": False, "weapon_armor_shop": False,
                       "church": False, "entrance": False}, (
        "⚠⚠ 候補の無いボタンが押せる / ある方が押せない: %r" % enabled)
    assert "入ってきた所" in bar.move_buttons["entrance"].toolTip()
    assert "宿屋へ移動" in bar.move_buttons["inn"].toolTip()
    assert "面識のある道具屋がまだありません" in bar.move_buttons["item_shop"].toolTip()
    bar.move_buttons["inn"].click()                           # ★1 クリックで移動が始まる
    action, p = cmd.sent[-1]
    assert action == "navigate" and bar.ctl.mode == "move"
    assert p["facility"] == "inn" and p["stop_at"] == "first_message", "⚠⚠ 到着後の動き（RX3-0241）が変わった: %s" % p
    _arrive(vm, bar.ctl)
    bar._on_hear()                                            # ★聞き込みの間は押せない
    assert not any(b.isEnabled() for b in bar.move_buttons.values())


def test_同じ種類が2軒なら押すたびに循環し_順番はNPC番号(world):
    vm, svc, cmd, ctl, _ = world
    _two_item_shops(svc)
    picked, labels = [], []
    for _ in range(3):
        assert ctl.request_move("item_shop")
        picked.append(ctl.target["npc"]["npc_id"])
        labels.append(ctl.target_label)
        assert cmd.sent[-1][1]["facility"] == "item_shop"
        _arrive(vm, ctl)
    assert picked == [4, 7, 4], "⚠⚠ 循環していない / NPC 番号の順でない: %r" % picked
    assert labels == ["道具屋 1/2", "道具屋 2/2", "道具屋 1/2"], labels


@pytest.mark.parametrize("order", [(7, 4), (4, 7)])
def test_順番は起動ごとに変わらない_台帳の並びや距離に依らない(tmp_path, order):
    from dq3 import action_log as AL

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    _two_item_shops(svc, order=order)
    near = order[0]
    orig = svc._plan
    svc._plan = lambda n: dict(orig(n), steps=1 if n["npc_id"] == near else 40)   # ★近い方を変えても
    ctl = TownNavController(vm, svc, cmd, action_log=AL.ActionLog())             # ★起動し直した
    assert ctl.request_move("item_shop")
    assert ctl.target["npc"]["npc_id"] == 4, "⚠⚠ 台帳の並び・距離で最初の行き先が変わった"


def test_1軒なら毎回同じ施設(world):
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t")
    for _ in range(3):
        assert ctl.request_move("inn")
        assert ctl.target["npc"]["npc_id"] == 1 and ctl.target_label == "宿屋"
        _arrive(vm, ctl)


def test_移動中にもう一度押すと止めてから次の候補へ切り替える(world):
    vm, svc, cmd, ctl, clock = world
    _two_item_shops(svc)
    env = ctl.env_hook = _Env()
    assert ctl.request_move("item_shop") and ctl.target["npc"]["npc_id"] == 4
    first = ctl.seq
    _walking(vm, ctl)
    assert ctl.request_move("item_shop")
    assert cmd.sent[-1][0] == "nav_stop", "⚠⚠ 止めずに頼み直した（★歩いている最中の位置から経路を作る）"
    assert ctl.mode == "move"
    vm.nav = {"seq": first, "active": False, "phase": "done", "reason": "stopped_by_user"}
    vm.pos = (1, 9, 9, 18)
    ctl.poll()                                               # ★止まった（位置を覚える）
    assert ctl.mode == "move", "⚠⚠ 切り替えの止まりを「停止」として終えた"
    vm.pos = (1, 9, 10, 18)                                  # ⚠ まだ歩きかけ（★升が 1 つ進んだ）
    clock[0] += 0.1
    ctl.poll()
    clock[0] += 0.1
    ctl.poll()                                               # ★同じ升だが、落ち着いてまだ 0.1 秒
    assert cmd.sent[-1][0] == "nav_stop", "⚠⚠ 位置が落ち着く前に経路を作った（★歩きかけの升から = 経路ずれ）"
    clock[0] += 1.0
    ctl.poll()
    action, p = cmd.sent[-1]
    assert action == "navigate" and ctl.seq != first and ctl.target["npc"]["npc_id"] == 7
    assert p["facility"] == "item_shop" and p["stop_at"] == "first_message"
    assert "town_end" not in [a for a, _ in cmd.sent], "⚠⚠ 切り替えで街の作業を終えた（★速度・音が戻る）"
    assert "end:move" not in env.calls
    _arrive(vm, ctl)
    assert env.depth == 0
    assert [r.action for r in ctl.action_log.rows] == ["move"], "⚠ 切り替えで行動履歴が 2 行になった"
    assert ctl.action_log.rows[-1].status_label == "完了"


def test_別の種類を押せばその施設へ切り替える(world):
    vm, svc, cmd, ctl, clock = world
    svc.heard.record(9, 1, 11, at="t")
    _two_item_shops(svc)
    assert ctl.request_move("inn")
    _walking(vm, ctl)
    assert ctl.request_move("item_shop") and cmd.sent[-1][0] == "nav_stop"
    vm.nav = dict(vm.nav, active=False, phase="done", reason="stopped_by_user")
    ctl.poll()
    clock[0] += 1.0
    ctl.poll()
    assert ctl.target["npc"]["npc_id"] == 4 and cmd.sent[-1][1]["facility"] == "item_shop"


def test_Luaがまだ受け取っていなければ頼みを差し替える(world):
    """★まだ 1 歩も歩いていない → ★止めずに差し替える（⚠ 止める頼みで歩く頼みを上書きすると、何も起きずに待ち続ける）。"""
    vm, svc, cmd, ctl, _ = world
    _two_item_shops(svc)
    ctl.request_move("item_shop")
    vm.nav = None                                            # ★Lua はまだ前の状態
    n = len(cmd.sent)
    assert ctl.request_move("item_shop")
    assert [a for a, _ in cmd.sent[n:]] == ["navigate"] and ctl.target["npc"]["npc_id"] == 7


@pytest.mark.parametrize("phase", ["talk", "inn", "close", "after"])
def test_話しかけた後は切り替えない(world, phase):
    """★誤操作防止（指示書 §5）: 施設の人と話し始めた後は、今の施設を優先する。"""
    vm, svc, cmd, ctl, _ = world
    _two_item_shops(svc)
    ctl.request_move("item_shop")
    vm.nav = {"seq": ctl.seq, "active": True, "phase": phase}
    n = len(cmd.sent)
    assert ctl.request_move("item_shop") is False
    assert cmd.sent[n:] == [] and ctl.target["npc"]["npc_id"] == 4 and "話して" in ctl.message


def test_最初の台詞の後は切り替えない(world):
    vm, svc, cmd, ctl, _ = world
    _two_item_shops(svc)
    ctl.request_move("item_shop")
    vm.nav = {"seq": ctl.seq, "active": True, "phase": "walk", "first_message": 1234}
    ctl.poll()
    n = len(cmd.sent)
    assert ctl.request_move("item_shop") is False and cmd.sent[n:] == []


def test_止める間に話し始めていたら切り替えずに人へ返す(world):
    vm, svc, cmd, ctl, clock = world
    _two_item_shops(svc)
    ctl.request_move("item_shop")
    _walking(vm, ctl)
    ctl.request_move("item_shop")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "stopped_by_user", "talk_frame": 99}
    ctl.poll()
    clock[0] += 1.0
    ctl.poll()
    assert ctl.mode is None and "切り替えませんでした" in ctl.message, ctl.message
    assert cmd.sent[-1][0] != "navigate"


def test_止まったと分からなければ待ち続けない(world):
    vm, svc, cmd, ctl, clock = world
    _two_item_shops(svc)
    ctl.request_move("item_shop")
    _walking(vm, ctl)
    ctl.request_move("item_shop")
    clock[0] += TB.SWITCH_WAIT_S + 1
    ctl.poll()
    assert ctl.mode is None and "切り替えられません" in ctl.message, ctl.message


def test_聞き込みの間は街移動を受けない(world):
    vm, svc, cmd, ctl, _ = world
    _two_item_shops(svc)
    assert ctl.start_hearing()
    n = len(cmd.sent)
    assert ctl.request_move("item_shop") is False and cmd.sent[n:] == []


def test_ボタンのツールチップに今の候補が出る(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from dq3.ui.town_bar import TownBar

    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    _two_item_shops(svc)
    bar = TownBar(vm, svc, cmd)
    assert "次は 道具屋 1/2" in bar.move_buttons["item_shop"].toolTip()
    bar.move_buttons["item_shop"].click()
    assert "いま 道具屋 1/2" in bar.move_buttons["item_shop"].toolTip()
    assert bar.status.text() == "★道具屋 1/2 へ"
    _arrive(vm, bar.ctl)
    bar.refresh()
    assert "次は 道具屋 2/2" in bar.move_buttons["item_shop"].toolTip()


@needs_rom
def test_補充は話が出ている方の道具屋から_その店の品揃えで買う(world, monkeypatch):
    """★2 軒目で最初の台詞まで来た → 補充: ⚠ 先頭の店へ歩きに行かない / ★品揃えもその店の人のもの。"""
    from dq3.knowledge import item_info as II

    vm, svc, cmd, ctl, clock = _shop_world(world)
    _two_item_shops(svc)
    _shop_items(monkeypatch)
    asked = []
    orig = II.shop_of_npc
    monkeypatch.setattr(II, "shop_of_npc", lambda shops, role, talk_id: (asked.append(talk_id), orig(shops, role, talk_id))[1])
    vm.window_open = True
    vm.talk = {"slot": 21, "talk_id": 0x307}                 # ★2 軒目（npc 7）の人と話している
    assert ctl.start_restock() is True
    assert [a for a, _ in cmd.sent] == ["restock"], "⚠⚠ 先頭の店へ歩きに行った: %s" % cmd.sent
    assert asked == [0x307], "⚠ 品揃えを話している店の人で引いていない: %r" % asked


def test_店の人から品揃えを引く_2軒の町(monkeypatch):
    from dq3.knowledge import item_info as II
    from dq3.testing import talk_script as TS

    a = II.Shop(map_id=80, role="item_shop", shop_index=32, items=(101,))
    b = II.Shop(map_id=80, role="item_shop", shop_index=33, items=(102,))
    w = II.Shop(map_id=80, role="weapon_armor_shop", shop_index=33, items=(1,))
    monkeypatch.setattr(TS, "classify", lambda tid: {"role": "item_shop", "facility_index": {0x303: 32, 0x30C: 33}.get(tid)})
    assert II.shop_of_npc([w, a, b], "item_shop", 0x30C) is b
    assert II.shop_of_npc([w, a, b], "item_shop", 0x303) is a
    assert II.shop_of_npc([w, a, b], "item_shop", 0x999) is a, "⚠ 店番号が分からないときは先頭（★今までどおり）"
    assert II.shop_of_npc([w], "item_shop", 0x30C) is None


def test_開けた扉をLuaへ渡す地図に入れる(world):
    """★RX3-0263（2026-09-14）: 鍵で開けた扉を覚えている（`_opened`）→ ★次に歩く頼みの地図へ渡す（Lua の作り直しが通れる）。

    ⚠ 別の地図で開けた扉は渡さない / 開けていなければ今までどおりの呼び方（★渡すものが無い）。
    """
    vm, svc, cmd, ctl, _ = world
    assert ctl.start_hearing()
    assert svc.last_opened == [], "⚠ 開けていないのに扉を渡した"
    ctl.stop()
    ctl.start_hearing()
    ctl._opened = {(9, 8, 17), (12, 3, 3)}                  # ★この地図（9）の扉と、別の地図（12）の扉
    ctl._next_target()
    assert svc.last_opened == [(8, 17)], "⚠⚠ 開けた扉を地図へ渡していない / 別の地図の扉まで渡した: %r" % svc.last_opened

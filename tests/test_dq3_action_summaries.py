"""省力 Action の終わりに出す 1 行（RX3-0110 / 2026-09-07）。

## ★依頼者が挙げた確認事項（§5）

```text
聞き込み   成功のみ / 成功＋skip / 全員 skip / ユーザー中断
自動移動   到着 / 到達不能 / 中断
自動戦闘   正常終了 / ユーザー停止 / 危険停止
```

⚠⚠ **Technical Log の語（`reason=path_deviation`）を人へ出さない**ことも見ます。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3 import action_log as AL                     # noqa: E402
from dq3.ui import auto_watch as AW                  # noqa: E402

from test_dq3_town_ui import _Commands, _Service, _VM  # noqa: E402


# ======================================================================
# ★聞き込み / 自動移動
# ======================================================================
@pytest.fixture
def town(tmp_path):
    from dq3.ui.town_bar import TownNavController

    clock = [0.0]
    vm, svc, cmd = _VM(), _Service(tmp_path), _Commands()
    log = AL.ActionLog(clock=lambda: clock[0])
    ctl = TownNavController(vm, svc, cmd, clock=lambda: clock[0], action_log=log)
    return vm, svc, cmd, ctl, log, clock


def _talk(vm, ctl, slot, talk_id, text="＊「やあ。"):
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": slot, "talk_id": talk_id}
    vm.last_talk_text = text
    ctl.poll()


def test_聞き込み_成功のみ(town):
    """★全員と話せた（⚠ 未完が無ければ内訳も出さない）。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.npcs = [svc.npcs[0]]                       # ★話せる相手を 1 人に
    assert ctl.start_hearing()
    _talk(vm, ctl, 5, 11)
    assert ctl.mode is None
    assert [r.line() for r in log.rows] == ["[聞き込み] 完了：1人と会話"]


def test_聞き込み_成功とskip(town):
    vm, svc, cmd, ctl, log, _ = town
    svc.unreachable = {6}
    assert ctl.start_hearing()
    _talk(vm, ctl, 5, 11)
    got = log.rows[-1]
    assert got.status == AL.PARTIAL
    assert got.line() == "[聞き込み] 完了：1人と会話 / 未完1人（到達不能1）"


def test_聞き込み_全員skip(town):
    """⚠ 1 人も話せなかった（★それでも 1 行出す）。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.unreachable = {1, 6}
    assert ctl.start_hearing() is False
    assert len(log.rows) == 1
    assert log.rows[0].line() == "[聞き込み] 完了：話せた人はいません / 未完2人（到達不能2）"


def test_聞き込み_もう全員聞いていたらそう言う(town):
    """★依頼者 2026-09-11「既に聞き込み済で対象がいない場合、完了：0人と会話としか出ない」。

    ⚠ 「0人と会話」では、壊れたのか、もう全員聞いたのかが分かりません。
    """
    vm, svc, cmd, ctl, log, _ = town
    for n in svc.npcs:
        if n["talk_id"]:
            svc.heard.record(9, n["npc_id"], n["talk_id"], at="t")
    total = sum(1 for n in svc.npcs if n["talk_id"])
    assert ctl.start_hearing() is False
    got = log.rows[-1]
    assert got.line() == "[聞き込み] 完了：この場所の%d人とは、もう全員話しています" % total
    assert "0人" not in got.line(), "⚠⚠ まだ 0 人と書いている"
    assert ctl.message == "もう全員と話しています（%d人）" % total, "⚠ 画面の短い文も同じわけを言う"


def test_聞き込み_窓が閉じないときは何が起きたか言う(town):
    """★依頼者 2026-09-11「冒険者の登録所で聞き込み中断されてしまう」。

    ⚠ 以前は「中断：うまくいきませんでした」だけでした（★窓の話だと分からない）。
    """
    vm, svc, cmd, ctl, log, clock = town
    svc.npcs = [svc.npcs[0]]
    assert ctl.start_hearing()
    vm.window_open = True                            # ★「はい / いいえ」が残っている
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": 5, "talk_id": 11}
    # ★文の中身はこの検査で使いません（⚠ 窓が閉じないことだけを見る）→ 架空の文 / RX3-0433
    vm.last_talk_text = "＊「ここに なまえを かきますか？"
    ctl.poll()
    clock[0] += 60                                    # ★待ちきった
    ctl.poll()
    got = log.rows[-1]
    assert got.line() == "[聞き込み] 中断：会話の窓が閉じませんでした / 1人と会話"
    assert got.detail["reason"] == "window_will_not_close"


def test_聞き込み_話しかけられる人がいない(town):
    vm, svc, cmd, ctl, log, _ = town
    svc.npcs = [dict(n, talk_id=0) for n in svc.npcs]
    assert ctl.start_hearing() is False
    assert log.rows[-1].line() == "[聞き込み] 完了：話しかけられる人がいません"


def test_聞き込み_ユーザー中断(town):
    vm, svc, cmd, ctl, log, _ = town
    assert ctl.start_hearing()
    ctl.stop()
    assert log.rows[-1].line() == "[聞き込み] 停止：ユーザー操作 / 0人と会話"
    assert log.rows[-1].status == AL.CANCELLED


def test_聞き込み_理由の内訳は人の言葉(town):
    """⚠⚠ `path_deviation` のような内部の語を人へ出さない。"""
    vm, svc, cmd, ctl, log, _ = town
    assert ctl.start_hearing()
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "path_deviation"}
    ctl.poll()                                      # ★1 人目を飛ばして次へ
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "face_moved"}
    ctl.poll()
    assert ctl.mode is None
    got = log.rows[-1]
    assert "経路ずれ1" in got.line() and "相手が移動1" in got.line(), got.line()
    assert AL.is_user_safe(got.line())
    assert "path_deviation" not in got.line()


def test_自動移動_到着(town):
    vm, svc, cmd, ctl, log, _ = town
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    assert log.rows[-1].line() == "[自動移動] 完了：宿屋へ到着 / 3歩"


def test_自動移動_着いて話しかけた(town):
    """★街移動は着いたら話しかける（RX3-0197）→ Lua の終わり方は `talk_done`。⚠ 失敗にしない。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    ctl.poll()
    got = log.rows[-1]
    assert got.line() == "[自動移動] 完了：宿屋へ到着 / 3歩", got.line()
    assert got.status == AL.SUCCESS


def test_自動移動_到達不能(town):
    vm, svc, cmd, ctl, log, _ = town
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "path_blocked"}
    ctl.poll()
    got = log.rows[-1]
    assert got.line() == "[自動移動] 中断：道がふさがっています / 3歩"
    assert got.status == AL.FAILED
    assert got.detail["reason"] == "path_blocked"      # ★内部の語は detail 側へ


def test_自動移動_ユーザー中断(town):
    vm, svc, cmd, ctl, log, _ = town
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_move("inn")
    ctl.stop()
    assert log.rows[-1].line() == "[自動移動] 停止：ユーザー操作 / 3歩"


def test_1回につき1行しか出ない(town):
    """⚠⚠ 終わり方が何通りもあるので、★ここが緩むと 2 行出ます。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.heard.record(9, 1, 11, at="t")
    ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    ctl.poll()
    ctl.stop()                                       # ⚠ もう終わっているのに押された
    assert len(log.rows) == 1, [r.line() for r in log.rows]


def test_画面の文は幅に収まり全文はdetailに残る(town):
    """★RX3-0102: 画面は短く、⚠ **消さない**。"""
    from dq3.ui import town_bar as TB

    vm, svc, cmd, ctl, log, _ = town
    svc.unreachable = {1, 6}
    ctl.start_hearing()
    assert len(ctl.message) <= TB.STATUS_MAX, ctl.message
    assert log.rows[-1].detail["raw_message"]


# ======================================================================
# ★自動戦闘 / まんたん（⚠ Lua のログから起こす）
# ======================================================================
@pytest.fixture
def watcher():
    clock = [0.0]
    log = AL.ActionLog(clock=lambda: clock[0])
    return AW.LuaActionWatcher(log), log


def test_自動戦闘_正常終了(watcher):
    w, log = watcher
    w.feed("battle", [
        "AUTO_V0 ON + turbo",
        "AUTO_V0 turn=1 slot=p1 action=attack (弱っている) hp_mp=…",
        "AUTO_V0 turn=2 slot=p2 action=attack (…) hp_mp=…",
        "AUTO_V0_DONE 戦闘が終わった（地形 512 マス / $62=0） rounds=1 actions=2",
        "AUTO_V0 OFF + normal",
    ])
    assert [r.line() for r in log.rows] == ["[自動戦闘] 完了：1戦 / 1ターン（2行動）"]


def test_自動戦闘_古い記録はターンを名乗らない(watcher):
    """⚠⚠ `turns=` しか無い行で「N ターン」と書いたら、それは**作り話**。

    ★行動の数だけ分かっているので、⚠ **行動だけ**書きます（RX3-0153）。
    """
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON",
                      "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                      "AUTO_V0_DONE 戦闘が終わった turns=9"])
    assert log.rows[-1].line() == "[自動戦闘] 完了：1戦 / 9行動"
    assert log.rows[-1].detail["rounds"] is None


def test_自動戦闘_レベルアップも1行(watcher):
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON",
                      "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                      "AUTO_V0_DONE 戦闘が終わった（…）★レベルが上がった rounds=1 actions=1"])
    assert log.rows[-1].line() == "[自動戦闘] 完了：1戦 / 1ターン（1行動） / レベルが上がりました"


def test_自動戦闘_危険停止(watcher):
    """⚠ 内部の語（`screen_frozen`）を人へ出さない。"""
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON",
                      "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                      "AUTO_V0_STOP reason=screen_frozen"])
    got = log.rows[-1]
    assert got.line() == "[自動戦闘] 中断：操作がかみ合わなくなりました / 1ターン（1行動）"
    assert got.detail["reason"] == "screen_frozen"


@pytest.mark.parametrize(("why", "text"), [
    ("窓の色 緑（HP 1/4 未満）（ここから手で戦う）", "HPが1/4を切った仲間がいる"),
    ("窓の色 オレンジ（死者あり）（ここから手で戦う）", "倒れている仲間がいる"),
    ("劣勢（ここから手で戦う）", "戦況が劣勢になった"),
])
def test_自動戦闘_人へ返した終わりを勝利と数えない(watcher, why, text):
    """⚠⚠ RX3-0233: 窓の色・劣勢で手で戦う画面に戻した戦闘を「勝利」と数えていた（★08:09 の 窓の色 緑 が「勝利 5ターン」）。"""
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON",
                      "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                      "AUTO_V0_DONE %s rounds=1 actions=1" % why])
    got = log.rows[-1]
    assert "勝利" not in got.line() and "完了" not in got.line(), got.line()
    assert "手で戦う画面に戻しました（%s）" % text in got.line()
    assert got.detail["result"] == "handed"


def test_自動戦闘_ユーザー停止(watcher):
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON",
                      "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                      "AUTO_V0 OFF"])
    assert log.rows[-1].line() == "[自動戦闘] 停止：ユーザー操作 / 1ターン（1行動）"


def test_自動戦闘_知らない理由でも生の語を出さない(watcher):
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON", "AUTO_V0_STOP reason=command_missing:p1=spell"])
    got = log.rows[-1]
    assert got.line() == "[自動戦闘] 中断：コマンドが見つかりません / 0行動"
    assert "p1=spell" not in got.line() and AL.is_user_safe(got.line())


def test_自動戦闘_表に無い理由は推測しない(watcher):
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON", "AUTO_V0_STOP reason=まだ知らない理由"])
    assert log.rows[-1].line() == "[自動戦闘] 中断：うまくいきませんでした / 0行動"


def test_まんたん_回復した(watcher):
    w, log = watcher
    w.feed("mantan", [
        "MANTAN_V0 ON",
        "  ★回復した p1 22 → 60（1 回目）",
        "  ★回復した p3 10 → 55（2 回目）",
        "MANTAN_V0_DONE 全員 80% 以上 casts=2",
    ])
    assert log.rows[-1].line() == "[まんたん] 完了：2人回復 / HP +83"


def test_まんたん_回復が要らなかった(watcher):
    """⚠ 「0人回復」では何が起きたか伝わらない。"""
    w, log = watcher
    w.feed("mantan", ["MANTAN_V0 ON", "MANTAN_V0_DONE 全員 80% 以上 casts=0"])
    assert log.rows[-1].line() == "[まんたん] 完了：回復は要りませんでした"


def test_まんたん_止まった(watcher):
    w, log = watcher
    w.feed("mantan", ["MANTAN_V0 ON",
                      "  ★回復した p1 22 → 60（1 回目）",
                      "MANTAN_V0_STOP reason=cursor_stuck:p2"])
    assert log.rows[-1].line() == "[まんたん] 中断：カーソルが動きません / 1人回復 / HP +38"


def test_戦闘とまんたんは別々に数える(watcher):
    """⚠ 同じ見張りが 2 本のログを読むので、★混ざらないこと。"""
    w, log = watcher
    w.feed("battle", ["AUTO_V0 ON", "AUTO_V0 turn=3 slot=p1 action=attack (…) hp_mp=…"])
    w.feed("mantan", ["MANTAN_V0 ON", "  ★回復した p1 1 → 2（1 回目）",
                      "MANTAN_V0_DONE ok casts=1"])
    w.feed("battle", ["AUTO_V0_DONE 戦闘が終わった turns=3"])
    assert [r.line() for r in log.rows] == [
        "[まんたん] 完了：1人回復 / HP +1",
        "[自動戦闘] 完了：1戦 / 3行動",
    ]


def test_ログを読み直しても2行にならない(tmp_path):
    """★実際の道（ファイル → LogTail → サマリー）を通す。"""
    path = tmp_path / "auto_v0.log"
    path.write_text("", encoding="utf-8")
    log = AL.ActionLog()
    w = AW.LuaActionWatcher(log, battle_log=path, mantan_log=tmp_path / "m.log",
                            from_end=False)
    assert w.poll() == []
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("AUTO_V0 ON\nAUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…\n")
    assert w.poll() == []
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("AUTO_V0_DONE 戦闘が終わった rounds=1 actions=1\nAUTO_V0 OFF\n")
    got = w.poll()
    assert [g.line() for g in got] == ["[自動戦闘] 完了：1戦 / 1ターン（1行動）"]
    assert w.poll() == [] and len(log.rows) == 1


def test_理由の表は本物のLuaと揃っている():
    """⚠⚠ 表が古くなると、★人には「うまくいきませんでした」しか出なくなります。

    ★Lua の `stop("...")` を読み出して、⚠ 表に無いものを数えます。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "dq3" / "phase0"
    for name, table in (("auto_v0.lua", AW.BATTLE_REASONS),
                        ("mantan_v0.lua", AW.MANTAN_REASONS)):
        text = (root / name).read_text(encoding="utf-8")
        used = {m.split(":", 1)[0] for m in re.findall(r'stop\("([^"]+)"', text)}
        assert used, "⚠ `stop(...)` が 1 つも見つからない（★この検査は空回り）"
        missing = sorted(used - set(table))
        assert not missing, "⚠ %s の理由が表にありません: %s" % (name, missing)


# ======================================================================
# ★鍵が要る相手を「鍵が要る」と言う（RX3-0078 / 2026-09-07）
# ======================================================================
def test_鍵が無くて行けない人は理由が出る(town):
    """★依頼者の Acceptance「鍵が無ければ『鍵が要る』と理由を出す」。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.unreachable = {6}
    svc.behind_door = {6}                     # ★鍵さえあれば届く相手
    assert ctl.start_hearing()
    _talk(vm, ctl, 5, 11)
    got = log.rows[-1]
    assert "鍵が要る1" in got.line(), got.line()
    assert any(e.get("reason") == "needs_key" for e in ctl.log), ctl.log


def test_そもそも届かない人は到達不能のまま(town):
    """⚠ 何でも「鍵が要る」にしない（★扉のせいでないものを混ぜない）。"""
    vm, svc, cmd, ctl, log, _ = town
    svc.unreachable = {6}
    svc.behind_door = set()                   # ★鍵があっても届かない
    assert ctl.start_hearing()
    _talk(vm, ctl, 5, 11)
    got = log.rows[-1]
    assert "到達不能1" in got.line(), got.line()
    assert "鍵" not in got.line()


def test_鍵を持っていれば候補に入る(town):
    """★持っていれば、⚠ そもそも skip されない。"""
    vm, svc, cmd, ctl, log, _ = town

    vm.equip_members = lambda: [{"inventory": [88]}]
    svc.unreachable = {6}
    svc.behind_door = {6}
    assert ctl.start_hearing()
    assert svc.seen_keys == [88], svc.seen_keys
    assert 6 not in ctl.skipped, "⚠ 鍵を持っているのに飛ばした"

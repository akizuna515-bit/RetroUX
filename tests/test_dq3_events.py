"""ログ出力正規化 — 共通 Event（RX3-0154 / 2026-09-10 依頼者「ログ出力正規化 仕様案」）。

## ★見ているもの（依頼者 §29 の成功条件）

```text
1  自動戦闘 / 自動移動 / まんたん が共通 Event になる
2  Event Writer の呼び出しが 1 か所に集まる（★producer は文章を作らない）
3  normal で簡易 Product Log が出る
4  diagnostic で詳細が取れる
5  Action Summary が Event から作られる
6  冒険ログが同じ Event を使える
7  既存 Technical Log との互換
8  既存テストを壊さない        ← ★`tests/` 全体で見ます
9  不明値を推測で埋めない
10 Knowledge Store を変えない
```
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3 import action_log as AL                      # noqa: E402
from dq3 import events as EV                          # noqa: E402
from dq3.events import formatter as FM                # noqa: E402
from dq3.events import writer as EW                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
NL = chr(10)


@pytest.fixture()
def bench(tmp_path, monkeypatch):
    """★書き先を写しへ向ける（⚠ 本物の記録を読み書きしない）。"""
    from dq3 import paths

    monkeypatch.setattr(paths, "work",
                        lambda *parts: tmp_path.joinpath("work", *parts))
    monkeypatch.setattr(EW, "_CONFIG_MODE", EW.NORMAL, raising=False)
    clock = [1757480000.0]                              # ★2026-09-10 前後で固定
    log = AL.ActionLog(clock=lambda: clock[0])
    w = EW.EventWriter(mode=EW.NORMAL, clock=lambda: clock[0], action_log=log)
    return w, log, tmp_path / "work", clock


def _product(work) -> list:
    path = work / "runtime" / "dq3-log" / EW.PRODUCT_NAME
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ======================================================================
# ★Event そのもの
# ======================================================================

def test_知らない種別は通さない():
    """⚠⚠ 依頼者 §8「Event 種別を無制限に増やさない」。★関門はここ。"""
    with pytest.raises(EV.UnknownEventType):
        EV.Event(type="battle.whatever", source=EV.SRC_BATTLE)
    with pytest.raises(ValueError):
        EV.Event(type=EV.BATTLE_END, source=EV.SRC_BATTLE, level="verbose")


def test_時刻はISO8601とtimezone(bench):
    """★依頼者 §6。⚠ epoch float や `HH:MM:SS` を内側へ持ち込まない。"""
    w, _log, _work, _clock = bench
    ev = w.emit(EV.BATTLE_START, EV.SRC_BATTLE, {})
    assert ev is not None
    assert ev.ts[10] == "T" and len(ev.ts) == 25, ev.ts
    assert ev.ts[19] in "+-", "⚠⚠ timezone がありません: %s" % ev.ts
    assert ev.session_id and len(ev.session_id) == 15, ev.session_id


def test_変な時計でも落ちない():
    """⚠⚠ 2026-09-10 実測: 固定時計（`0.0`）で **OSError: Invalid argument**。

    ★naive な datetime に `astimezone()` を当てると、epoch 付近で OS の変換が落ちます。
    ⚠ `emit()` は握りつぶすので、**Event が黙って 1 件も出ませんでした**。
    """
    assert EV.now_iso(lambda: 0.0).endswith(EV.now_iso()[-6:]), "⚠ timezone が違う"
    for clock in (lambda: 0.0, lambda: -1.0, lambda: 1.0e18):
        got = EV.now_iso(clock)
        assert len(got) == 25 and got[10] == "T", got


def test_同じ起動なら同じsession_id(bench):
    w, _log, _work, _clock = bench
    a = w.emit(EV.BATTLE_START, EV.SRC_BATTLE, {})
    b = w.emit(EV.MANTAN_START, EV.SRC_MANTAN, {})
    assert a.session_id == b.session_id


def test_種別の名前に曖昧な語を使っていない():
    """⚠⚠ 依頼者 §27。★RX3-0153 で決めた語をここでも守る。"""
    for name in EV.TYPES:
        assert "turn" not in name, "⚠⚠ 曖昧な語が種別名にある: %s" % name
    src = (ROOT / "dq3" / "events" / "formatter.py").read_text(encoding="utf-8")
    assert "手番" not in src


# ======================================================================
# ⚠⚠ ログのために本体を止めない（依頼者 §25）
# ======================================================================

class _Broken:
    name = "product"

    def write(self, ev):
        raise RuntimeError("⚠ わざと落とす")


def test_sinkが落ちても機能本体は止めない(bench):
    """⚠⚠ 依頼者 §25「ログ出力失敗で本体を停止させない」。"""
    _w, log, _work, clock = bench
    w = EW.EventWriter(mode=EW.NORMAL, clock=lambda: clock[0],
                       sinks=[_Broken(), EW.ActionSummarySink(log)])
    ev = w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
                {"result": EV.WIN, "rounds": 2, "actions": 8})
    assert ev is not None, "⚠⚠ sink の失敗で Event ごと消えている"
    assert w.dropped == 1, "⚠ 落ちた件数を数えていない（★黙って減る）"
    assert [r.line() for r in log.rows] == ["[自動戦闘] 完了：1戦 / 2ターン（8行動）"]


def test_知らない種別でも例外を外へ出さない(bench):
    w, _log, _work, _clock = bench
    assert w.emit("battle.nonesuch", EV.SRC_BATTLE, {}) is None
    assert w.rejected == 1, "⚠ はじいた件数を数えていない"


# ======================================================================
# ★Product Log（§10 / §11）
# ======================================================================

def test_normalで簡易ログが出る(bench):
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.WIN, "rounds": 2, "actions": 8})
    w.emit(EV.MANTAN_END, EV.SRC_MANTAN,
           {"result": EV.SUCCESS, "members_healed": 3, "hp_gained": 83})
    w.emit(EV.NAVIGATION_ARRIVE, EV.SRC_NAVIGATION,
           {"result": EV.SUCCESS, "destination": "武器屋", "steps": 12})
    got = [row.split(" ", 2)[2] for row in _product(work)]
    assert got == ["自動戦闘：勝利 2ターン（8行動）",
                   "まんたん：3人回復 / HP +83",
                   "自動移動：武器屋に到着"]


def test_開始だけの行はProductへ出さない(bench):
    """★依頼者 §11。⚠ 1 戦 5 秒の戦闘で**同じことを 2 行**書かない。"""
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_START, EV.SRC_BATTLE, {})
    w.emit(EV.NAVIGATION_START, EV.SRC_NAVIGATION, {"destination": "宿屋"})
    assert _product(work) == []


def test_Productの行には日付が入る(bench):
    """⚠ 画面は `HH:MM` だけですが、★ファイルには日付ごと残します。

    ★冒険ログが「いつ」を言えるのは、⚠ **時刻つきの記録がここしかない**からです。
    """
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, {"result": EV.WIN, "actions": 4})
    row = _product(work)[0]
    assert row[:2] == "20" and row[4] == "-" and row[13] == ":", row
    ev = w.rows[-1]
    assert FM.stamped(ev) == FM.stamped(ev, with_date=True)[11:], "⚠ 画面用は時刻だけ"


# ======================================================================
# ⚠ diagnostic（§12 / §13）
# ======================================================================

def test_normalではdiagnosticを書かない(bench):
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, {"result": EV.WIN, "actions": 4})
    assert not (work / "runtime" / "dq3-log" / EW.DIAGNOSTIC_NAME).exists()


def test_diagnosticでは詳細が残る(bench):
    """★依頼者 §12。⚠ Event を**そのまま**残す（★人向けの文章ではない）。"""
    _w, log, work, clock = bench
    w = EW.EventWriter(mode=EW.DIAGNOSTIC, clock=lambda: clock[0], action_log=log)
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.STOPPED, "rounds": 1, "actions": 3,
            "reason": "screen_frozen"}, level=EV.WARNING)
    rows = [json.loads(ln) for ln
            in (work / "runtime" / "dq3-log" / EW.DIAGNOSTIC_NAME).read_text(
                encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1
    got = rows[0]
    assert got["type"] == "battle.end" and got["source"] == "battle_auto"
    assert got["level"] == "warning"
    assert got["data"]["reason"] == "screen_frozen", "⚠ 内部の語が残っていない"
    assert set(got) == {"ts", "session_id", "type", "source", "level", "data"}


def test_modeは新しい設定を増やしていない():
    """⚠⚠ `retroux` 側に normal / diagnostic が**もうあります**（2026-08-13）。

    ★同じことを 2 か所で決めないため、`user_config.yaml` の `logging.mode` を見ます。
    """
    src = (ROOT / "dq3" / "events" / "writer.py").read_text(encoding="utf-8")
    assert "user_config" in src, "⚠⚠ 既にある設定を使っていない"
    assert EW.MODES == ("normal", "diagnostic"), "⚠ 初版で mode を増やしている"


# ======================================================================
# ★Action Summary は Event から（§16）
# ======================================================================

def test_行動履歴はEventから作られる(bench):
    w, log, _work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.STOPPED, "rounds": 1, "actions": 3,
            "reason": "screen_frozen"}, level=EV.WARNING)
    got = log.rows[-1]
    assert got.line() == "[自動戦闘] 中断：操作がかみ合わなくなりました / 1ターン（3行動）"
    assert got.detail["reason"] == "screen_frozen", "⚠ 内部の語は detail へ"
    assert got.detail["event_type"] == "battle.end"
    assert AL.is_user_safe(got.line()), "⚠⚠ 生の値が人向けの本文に出ている"


def test_producerは文章を作らない(bench, tmp_path):
    """⚠⚠ 依頼者 §9。★`auto_watch` から「表示用の文章」を無くしたことを見る。

    ⚠ 字面だけでは足りません（★消し忘れが無いことしか言えない）。
      → ★**動かして**、文章が formatter 側から来ていることも見ます。
    """
    from dq3.ui import auto_watch as AW

    src = (ROOT / "dq3" / "ui" / "auto_watch.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]                    # ★註（説明）は除く
    for banned in ("run.completed", "run.failed", "run.cancelled", "[自動戦闘]"):
        assert banned not in body, "⚠⚠ producer が文章を作っている: %s" % banned
    assert "self.writer.emit" in body, "⚠ Event Writer を通っていない"

    # ★動かして確かめる（⚠ 文章を作っているのは formatter 側か）
    w, log, _work, _clock = bench
    watch = AW.LuaActionWatcher(log, battle_log=tmp_path / "b.log",
                                mantan_log=tmp_path / "m.log", writer=w)
    watch.feed("battle", ["AUTO_V0_DONE 戦闘が終わった rounds=2 actions=8"])
    ev = w.rows[-1]
    assert ev.type == "battle.end" and "自動戦闘" not in json.dumps(
        ev.data, ensure_ascii=False), "⚠⚠ Event に表示用の文章が混ざっている"
    _action, _status, message, _detail = FM.summary_of(ev)
    assert log.rows[-1].line() == "[自動戦闘] 完了：" + message, \
        "⚠ 履歴の本文が formatter から来ていない"


def test_同じEventからUIとProductの両方が出る(bench):
    """★依頼者 §16 の狙い（⚠ 解釈が 2 通りに割れない）。"""
    w, log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.WIN, "rounds": 2, "actions": 8})
    assert log.rows[-1].line() == "[自動戦闘] 完了：1戦 / 2ターン（8行動）"
    assert _product(work)[-1].endswith("自動戦闘：勝利 2ターン（8行動）")


# ======================================================================
# ★戦闘のまとめ（RX3-0198 / 2026-09-12 依頼者「戦闘後に作戦・行動の内訳・MP 消費」）
# ======================================================================

_SUMMARY = {"result": EV.WIN, "rounds": 2, "actions": 8, "strategy": "leveling",
            "breakdown": {"attack": 5, "magic": 2, "heal": 1, "support": 0,
                          "defend": 0, "other": 0},
            "mp_used": 12}


def test_戦闘のまとめがProductに出る(bench):
    """★依頼者の指定「作戦：最短撃破 / Nターン / 通常攻撃 a / 攻撃魔法 b / 回復 c / 支援 d / 防御 e / MP消費 f」。"""
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, dict(_SUMMARY))
    assert _product(work)[-1].endswith(
        "自動戦闘：勝利 2ターン（8行動） / 作戦：最短撃破 / 通常攻撃 5 / 攻撃魔法 2 / 回復 1 / "
        "支援 0 / 防御 0 / MP消費 12"), _product(work)[-1]
    assert "leveling" not in _product(work)[-1], "⚠⚠ 内部の語が人向けの行に出ている"


def test_まとめはLuaの終わりの行からEventへ届く(bench, tmp_path):
    """★`AUTO_V0_DONE … rounds= actions= strategy= attack= … mp_used=` → `battle.end` の data。"""
    from dq3.ui import auto_watch as AW

    w, log, work, _clock = bench
    watch = AW.LuaActionWatcher(log, battle_log=tmp_path / "b.log",
                                mantan_log=tmp_path / "m.log", writer=w)
    watch.feed("battle", ["AUTO_V0 ON",
                          "AUTO_V0_DONE 勝利 rounds=2 actions=8 strategy=leveling attack=5 magic=2 "
                          "heal=1 support=0 defend=0 other=0 mp_used=12"])
    ev = w.rows[-1]
    assert ev.type == "battle.end" and ev.data["strategy"] == "leveling"
    assert ev.data["breakdown"]["magic"] == 2 and ev.data["mp_used"] == 12
    assert "作戦：最短撃破" in _product(work)[-1]
    # ★右画面の行動履歴は今までの 1 行のまま（⚠ 内訳は detail / 右画面の「前回」で出す）
    assert log.rows[-1].line() == "[自動戦闘] 完了：1戦 / 2ターン（8行動）"
    assert log.rows[-1].detail["breakdown"]["attack"] == 5


def test_まとめの無い戦闘は今までの1行のまま(bench):
    """⚠⚠ 旧い記録・止まった戦闘に「MP消費 0」を作らない（§21 / §23）。"""
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, {"result": EV.WIN, "rounds": 2, "actions": 8})
    assert _product(work)[-1].endswith("自動戦闘：勝利 2ターン（8行動）")
    assert FM.battle_breakdown({"rounds": 2, "actions": 8}) == ""


# ======================================================================
# ⚠⚠ 不明値を推測で埋めない（§9 / §21 / §23）
# ======================================================================

def test_roundsが無ければターンを名乗らない(bench):
    """⚠⚠ 依頼者 §21「不明な rounds を推測しない」。"""
    w, log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, {"result": EV.WIN, "actions": 8})
    assert _product(work)[-1].endswith("自動戦闘：勝利 8行動")
    assert "ターン" not in log.rows[-1].line()


def test_取れない値は足さない(bench):
    """★依頼者 §23。⚠ MP が取れないまんたんで「MP 0使用」と書かない。"""
    w, log, work, _clock = bench
    w.emit(EV.MANTAN_END, EV.SRC_MANTAN,
           {"result": EV.SUCCESS, "members_healed": 2, "hp_gained": 30})
    assert _product(work)[-1].endswith("まんたん：2人回復 / HP +30")
    assert "MP" not in log.rows[-1].line()
    w.emit(EV.MANTAN_END, EV.SRC_MANTAN,
           {"result": EV.SUCCESS, "members_healed": 3, "hp_gained": 40, "mp_used": 18})
    assert _product(work)[-1].endswith("まんたん：3人回復 / HP +40 / MP 18使用")


def test_表に無い理由は推測しない(bench):
    w, log, _work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.STOPPED, "rounds": 0, "actions": 0,
            "reason": "まだ知らない理由"}, level=EV.WARNING)
    assert log.rows[-1].line() == "[自動戦闘] 中断：うまくいきませんでした / 0行動"


# ======================================================================
# ★既存との互換（§18 / §26 / §28）
# ======================================================================

def test_既存のTechnical_Logを消していない():
    """⚠⚠ 依頼者 §18。★5 本の `.log` は移行期間中そのまま残す。"""
    for name in ("auto_v0", "nav_v0", "walk_v0", "mantan_v0", "restock_v0"):
        path = ROOT / "dq3" / "phase0" / ("%s.lua" % name)
        assert path.exists(), "⚠⚠ producer を消している: %s" % name
        assert "log" in path.read_text(encoding="utf-8"), name


def test_battle_countを消していない():
    """★依頼者 §26。⚠ 過去 Technical Log の読み取り正本は残す。"""
    from dq3 import battle_count as BC

    assert BC.parse_done("AUTO_V0_DONE a turns=36")["actions"] == 36


def test_Knowledgeへは書かない(bench):
    """⚠⚠ 依頼者 §28「ログ正規化の名目で Knowledge Store を変更しない」。"""
    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE, {"result": EV.WIN, "actions": 4})
    w.emit(EV.NAVIGATION_ARRIVE, EV.SRC_NAVIGATION, {"destination": "宿屋"})
    assert not (work / "dq3-knowledge").exists(), "⚠⚠ 知識の置き場へ書いている"
    src = (ROOT / "dq3" / "events" / "writer.py").read_text(encoding="utf-8")
    assert "dq3-knowledge" not in src


# ======================================================================
# ★冒険ログが同じ Event を使う（§17）
# ======================================================================

def test_冒険ログがEventを使い回す(bench):
    """★依頼者 §17。⚠ 冒険ログは Event Log そのものではありません。"""
    from dq3.knowledge import adventure_log as ADV

    w, _log, work, _clock = bench
    w.emit(EV.BATTLE_END, EV.SRC_BATTLE,
           {"result": EV.WIN, "rounds": 2, "actions": 8})
    w.emit(EV.NAVIGATION_ARRIVE, EV.SRC_NAVIGATION, {"destination": "武器屋"})
    (work / "dq3-knowledge").mkdir(parents=True, exist_ok=True)

    got = ADV.actions()
    assert len(got) == 2 and got[-1].endswith("自動移動：武器屋に到着")
    text = ADV.build(state={})
    assert "## 8 RetroUX が代わりにやったこと" in text
    assert "自動戦闘：勝利 2ターン（8行動）" in text
    # ★古い順（RX3-0518: どの節も 古い → 新しい / ⚠ 以前は新しい順だった）
    assert text.index("自動戦闘：勝利") < text.index("武器屋に到着")


def test_冒険ログは記録が無ければ無いと書く(bench):
    """⚠⚠ 埋めさせない（★RX3-0150 と同じ決まり）。"""
    from dq3.knowledge import adventure_log as ADV

    _w, _log, work, _clock = bench
    (work / "dq3-knowledge").mkdir(parents=True, exist_ok=True)
    text = ADV.build(state={})
    body = text.split("## 8 RetroUX")[1].split("## 9")[0]
    assert "まだ記録がありません" in body


# ======================================================================
# ★3 機能が共通 Event に乗っている（§20 / §29-1）
# ======================================================================

def test_3機能が共通Eventに乗っている(bench, tmp_path):
    """★自動戦闘・まんたん（`auto_watch`）と 自動移動（`town_bar`）。"""
    from dq3.ui import auto_watch as AW

    w, log, _work, _clock = bench
    watch = AW.LuaActionWatcher(log, battle_log=tmp_path / "b.log",
                                mantan_log=tmp_path / "m.log", writer=w)
    watch.feed("battle", ["AUTO_V0 ON",
                          "AUTO_V0 turn=1 slot=p1 action=attack (…) hp_mp=…",
                          "AUTO_V0_DONE 戦闘が終わった rounds=1 actions=1"])
    watch.feed("mantan", ["MANTAN_V0 ON", "  ★回復した p1 22 → 60（1 回目）",
                          "MANTAN_V0_DONE ok casts=1"])
    kinds = [ev.type for ev in w.rows]
    assert kinds == ["battle.start", "battle.end", "mantan.start", "mantan.end"]
    assert [r.line() for r in log.rows] == [
        "[自動戦闘] 完了：1戦 / 1ターン（1行動）",
        "[まんたん] 完了：1人回復 / HP +38",
    ]


def test_自動移動もEventを通る(tmp_path, monkeypatch):
    """★`town_bar` の `move` は Event 経由（⚠ 聞き込み・補充は次の段階）。"""
    from dq3 import paths
    from dq3.ui.town_bar import TownNavController
    from test_dq3_town_ui import _Commands, _Service, _VM

    monkeypatch.setattr(paths, "work",
                        lambda *parts: tmp_path.joinpath("work", *parts))
    clock = [0.0]
    vm, svc = _VM(), _Service(tmp_path)
    log = AL.ActionLog(clock=lambda: clock[0])
    w = EW.EventWriter(mode=EW.NORMAL, clock=lambda: clock[0], action_log=log)
    ctl = TownNavController(vm, svc, _Commands(),
                            clock=lambda: clock[0], action_log=log, writer=w)
    svc.heard.record(9, 1, 11, at="t")                # ★宿屋を知っている状態にする
    assert ctl.start_move("inn")
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "arrived"}
    ctl.poll()
    assert [ev.type for ev in w.rows] == ["navigation.start", "navigation.arrive"]
    assert w.rows[-1].data["destination"] == "宿屋"
    assert log.rows[-1].line() == "[自動移動] 完了：宿屋へ到着 / 3歩"

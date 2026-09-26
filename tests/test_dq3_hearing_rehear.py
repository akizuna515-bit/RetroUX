"""聞き込み / 再聞き込み（RX3-0239）・場所ごとの会話記録クリア（RX3-0235）・Fact の番号の安定（§14）。

★依頼者の指示書「DQ3 聞き込み仕様最適化＋場所単位クリア仕様」（★正本の写し `docs/design/dq3-hearing-rehear-clear-spec.md`）。

```text
聞き込み      未聴の人だけ回る（★今までどおり）→ 全員聞き終えたらボタンは「再聞き込み」
再聞き込み    聞いたかを見ずに全員を 1 回ずつ回る（⚠ 履歴は消さない）
              同じ本文・同じ話者 → メモを足さない / 「？」→ 話者を埋める / 違う本文 → 新しいメモ
場所クリア    その場所の 会話のメモ・会話の記録・聞いた人の台帳 だけ消す（★discovery・地名・Topic は残す / 消す前に退避）
```
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3 import action_log as AL                         # noqa: E402
from dq3.knowledge import concepts as C                  # noqa: E402
from dq3.knowledge import memos as M                     # noqa: E402
from dq3.knowledge import npc_heard as H                 # noqa: E402
from dq3.knowledge import playdata as PD                 # noqa: E402
from dq3.ui import town_bar as TB                        # noqa: E402
from dq3.ui.town_bar import TownNavController            # noqa: E402

from test_dq3_town_ui import _VM, _Commands, _Service    # noqa: E402  ★町の UI と同じ偽物


class _Svc(_Service):
    """★再聞き込みを知っている偽の service（★聞いた人も候補に / 数）。"""

    def unheard_reachable_npcs(self, map_id, t, tbl, start, *, keys=(), include_heard=False):
        return [{"npc": n, "plan": self._plan(n), "distance": n["npc_id"]} for n in self.npcs
                if n["talk_id"] and (include_heard or not self.heard.is_heard(map_id, n["npc_id"]))]

    def counts(self, map_id, t, tbl, phase=None):
        talkable = [n for n in self.npcs if n["talk_id"]]
        heard = [n for n in talkable if self.heard.is_heard(map_id, n["npc_id"])]
        return {"npc_total": len(self.npcs), "talkable": len(talkable), "heard": len(heard), "status": "DEFAULT"}


@pytest.fixture
def world(tmp_path):
    vm, svc, cmd = _VM(), _Svc(tmp_path), _Commands()
    clock = [0.0]
    ctl = TownNavController(vm, svc, cmd, clock=lambda: clock[0], action_log=AL.ActionLog(clock=lambda: clock[0]))
    return vm, svc, cmd, ctl, clock


def _talk(vm, ctl, slot, talk_id, text):
    """★Lua が話し終え、窓の文が流れ、窓が閉じた。"""
    vm.nav = {"seq": ctl.seq, "active": False, "phase": "done", "reason": "talk_done"}
    vm.talk = {"slot": slot, "talk_id": talk_id}
    vm.last_talk_text = text
    ctl.poll()


# --- ★聞き込み / 再聞き込み（RX3-0239）-------------------------------------------

def test_未聴がいれば聞き込み_全員聞いたら再聞き込み(world):
    vm, svc, cmd, ctl, _ = world
    assert ctl.hearing_kind() == TB.HEAR
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.hearing_kind() == TB.HEAR, "⚠ 未聴の人（npc 6）がいるのに再聞き込みにした"
    svc.heard.record(9, 6, 0x247, at="t")
    assert ctl.hearing_kind() == TB.REHEAR, "⚠⚠ 全員聞き終えたのに「再聞き込み」にならない"
    assert TB.HEAR != TB.REHEAR and "消しません" in TB.HEAR_TIPS[TB.REHEAR]


def _unreachable(svc, npc_id):
    """★その人は（未聴なら）いまは辿り着けない（★聞き込みの候補に出ない / 再聞き込みでも同じ）。"""
    base = svc.unheard_reachable_npcs

    def got(map_id, t, tbl, start, *, keys=(), include_heard=False, **kw):
        return [c for c in base(map_id, t, tbl, start, keys=keys, include_heard=include_heard)
                if c["npc"]["npc_id"] != npc_id]

    svc.unheard_reachable_npcs = got


def test_辿り着けない未聴の人しか残っていなければ再聞き込み(world):
    """⚠⚠ RX3-0247（2026-09-13 依頼者「ジパングで再聞き込みが効かない save3」）。

    ★save3 のジパング: 22 人中 20 人を聞き、残る 2 人（(18,92)・(18,93)）は辿り着けない。
    ⚠ 以前は「未聴が 1 人でもいれば聞き込み」→ 押すと 0 人で終わり、⚠ 再聞き込みに一度も入れなかった。
    """
    vm, svc, cmd, ctl, _ = world
    _unreachable(svc, 6)
    assert ctl.hearing_kind() == TB.HEAR, "★まだ誰も聞いていない → 聞き込み"
    svc.heard.record(9, 1, 11, at="t")                  # ★npc 1 は聞いた / npc 6 は未聴で辿り着けない
    assert ctl.hearing_kind() == TB.REHEAR, "⚠⚠ 辿り着ける未聴の人がいないのに「聞き込み」のまま（save3）"
    assert ctl.start_hearing() and ctl.rehear, "⚠⚠ 押しても再聞き込みにならない"
    assert cmd.sent[-1][0] == "navigate", "★聞いた人を回り始める"


def test_辿り着ける未聴の人がいれば聞き込みのまま(world):
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t")                  # ★npc 6 は未聴で、辿り着ける
    assert ctl.hearing_kind() == TB.HEAR, "⚠ 辿り着ける未聴の人がいるのに再聞き込みにした"


def test_再聞き込みは聞いた人も全員1回ずつ回り履歴を消さない(world):
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t", text="＊「こんにちは。")
    svc.heard.record(9, 6, 0x247, at="t", text="＊「いい てんきだね。")
    assert ctl.start_hearing() and ctl.rehear, "⚠⚠ 全員聞いたあとの聞き込みが再聞き込みにならない"
    assert "再聞き込み中" in ctl.message
    assert cmd.sent[-1][1]["npc_slot"] == "-1" and vm.talk_tag["npc_id"] == 1, "⚠⚠ 聞いた人（npc 1）を飛ばした"
    _talk(vm, ctl, 5, 11, "＊「こんにちは。")                      # ★同じ本文
    assert vm.talk_tag["npc_id"] == 6, "⚠⚠ 2 人目（npc 6）へ進まない"
    _talk(vm, ctl, 10, 0x247, "＊「きょうは あめだね。")           # ★違う本文（台詞が変わった）
    assert ctl.mode is None and ctl.message.startswith("再聞き込み完了 2人"), ctl.message
    # ★A: 同じ本文は記録を増やさず回数だけ / C: 違う本文は新しい記録 / ★履歴は消えない
    assert [r["count"] for r in svc.heard.texts(9, 1)] == [2]
    assert [r["text"] for r in svc.heard.texts(9, 6)] == ["＊「いい てんきだね。", "＊「きょうは あめだね。"]
    navs = [p for a, p in cmd.sent if a == "navigate"]
    assert len(navs) == 2, "⚠⚠ 同じ人を繰り返した: %s" % navs


def test_通常の聞き込みは今までどおり未聴の人だけ(world):
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t")
    assert ctl.start_hearing() and not ctl.rehear
    assert vm.talk_tag["npc_id"] == 6, "⚠⚠ 聞いた人（npc 1）へ行った"


def test_再聞き込みの重複の扱いは勇者メモでも同じ(tmp_path):
    """★A 同じ本文・同じ話者 → 足さない / B 「？」→ 埋める（RX3-0236）/ C 違う本文 → 足す。"""
    store = M.MemoStore(tmp_path / "memos.jsonl")
    store.add_if_new("兵「やあ」", location_id="L9", map_id=9, source=M.NPC_TALK, speaker="兵")
    assert store.add_if_new("兵「やあ」", location_id="L9", map_id=9, source=M.NPC_TALK, speaker="兵") is None
    store.add_if_new("？「こんにちは」", location_id="L9", map_id=9, source=M.NPC_TALK, speaker="？")
    store.add_if_new("娘「こんにちは」", location_id="L9", map_id=9, source=M.NPC_TALK, speaker="娘")
    store.add_if_new("兵「さようなら」", location_id="L9", map_id=9, source=M.NPC_TALK, speaker="兵")
    assert [(m.text, m.speaker) for m in store] == [("兵「やあ」", "兵"), ("娘「こんにちは」", "娘"),
                                                    ("兵「さようなら」", "兵")]


def test_同じ本文を聞き直すと回数と最後に聞いた時刻だけ変わる(tmp_path):
    led = H.HeardLedger(tmp_path)
    led.record(9, 1, 11, at="t1", text="＊「やあ")
    led.record(9, 1, 11, at="t2", text="＊「やあ")
    rows = led.texts(9, 1)
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["last_heard_at"] == "t2" \
        and rows[0]["first_heard_at"] == "t1"


# --- ★場所ごとの会話記録クリア（RX3-0235）--------------------------------------

def _knowledge(tmp_path):
    k = tmp_path / "knowledge"
    k.mkdir()
    rows = [
        {"order": 1, "text": "★バハラタに はいった", "source": "discovery", "location_id": "L14", "map_id": 14},
        {"order": 2, "text": "兵「ようこそ」", "source": "npc_talk", "location_id": "L14", "map_id": 14, "speaker": "兵"},
        {"order": 3, "text": "＊「こしょうを…", "source": "conversation", "location_id": "L14", "map_id": 14},
        {"order": 4, "text": "主「やど」", "source": "npc_talk", "location_id": "L9", "map_id": 9},
        {"order": 5, "text": "＊「むかしの ぎょう", "source": "conversation", "map_id": 14},   # ★location_id の無い昔の行
        {"order": 6, "text": "★手で書いた", "source": "manual", "location_id": "L14", "map_id": 14},
    ]
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    lines.insert(3, "{壊れた行")
    (k / "memos.jsonl").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    (k / "npc-heard.json").write_text(json.dumps({"14": {"1": {"count": 1}, "2": {"count": 1}},
                                                  "9": {"1": {"count": 1}}}), encoding="utf-8")
    (k / "npc-conversations.json").write_text(json.dumps({"14/1": [{"text": "a"}], "14/2": [{"text": "b"}],
                                                          "9/1": [{"text": "c"}]}), encoding="utf-8")
    (k / "location-book.json").write_text('{"locations": {"L14": {"memo_done": true}}}', encoding="utf-8")
    (k / "topic-state.json").write_text('{"T1": {"status": "active"}}', encoding="utf-8")
    return k


def test_場所ごとのクリアはその場所の会話だけ消して残すものは残す(tmp_path):
    k = _knowledge(tmp_path)
    keep = {n: (k / n).read_bytes() for n in ("location-book.json", "topic-state.json")}
    svc = PD.PlayDataService(k, tmp_path / "vault")
    got = svc.clear_location("L14")
    assert got["map_ids"] == [14] and got["memos"] == 3 and got["heard"] == 2 and got["conversations"] == 2, got
    raw = (k / "memos.jsonl").read_bytes().decode("utf-8")
    rows = [json.loads(ln) for ln in raw.splitlines() if ln.startswith("{\"")]
    assert [r["order"] for r in rows] == [1, 4, 6], "⚠⚠ 消す行 / 残す行が違う（★discovery・他の場所・手書きは残す）"
    assert "{壊れた行" in raw and raw.endswith("\r\n") and "\n" not in raw.replace("\r\n", ""), "⚠ 壊れた行・改行"
    assert json.loads((k / "npc-heard.json").read_text(encoding="utf-8")) == {"9": {"1": {"count": 1}}}
    assert list(json.loads((k / "npc-conversations.json").read_text(encoding="utf-8"))) == ["9/1"]
    assert {n: (k / n).read_bytes() for n in keep} == keep, "⚠⚠ 場所・Topic の記録を触った"
    bak = tmp_path / "vault" / got["backup"]
    assert "before-clear-place-L14" in got["backup"] and (bak / "npc-heard.json").exists(), "⚠ 消す前に退避していない"
    assert json.loads((bak / "npc-heard.json").read_text(encoding="utf-8"))["14"], "⚠ 退避が消した後の中身"


def test_場所の一覧はlocation_idで数える(tmp_path):
    k = _knowledge(tmp_path)
    got = {p["location_id"]: p for p in PD.PlayDataService(k, tmp_path / "vault").places()}
    assert set(got) == {"L14", "L9"}
    assert (got["L14"]["memos"], got["L14"]["heard"], got["L14"]["conversations"]) == (3, 2, 2)
    # ★場所が複数 map をまとめていれば、その場所へ寄せる（★location_id が単位 / 指示書 §9）
    merged = PD.PlayDataService(k, tmp_path / "vault").places(location_of_map=lambda m: "L14" if m in (9, 14) else "L%d" % m)
    assert [p["location_id"] for p in merged] == ["L14", "L9"] or [p["location_id"] for p in merged] == ["L14"]


def test_確認の文に消すもの残すもの復元の注意がある():
    text = PD.describe_place("バハラタ")
    for word in ("バハラタの会話記録をクリアします", "勇者メモの会話", "聞き込み履歴", "保存済み会話",
                 "場所を発見した記録", "地名", "攻略の進行状況", "再び「聞き込み」", "巻き戻る"):
        assert word in text, word


def test_場所クリアのあとは聞き込みに戻る(world, tmp_path):
    vm, svc, cmd, ctl, _ = world
    svc.heard.record(9, 1, 11, at="t")
    svc.heard.record(9, 6, 0x247, at="t")
    svc.heard.save()
    assert ctl.hearing_kind() == TB.REHEAR
    PD.PlayDataService(svc.heard.dir, tmp_path / "vault").clear_location("L9")
    svc.heard.reload()                                   # ★管理画面の _after_change と同じ
    assert ctl.hearing_kind() == TB.HEAR, "⚠⚠ クリアしたのに「再聞き込み」のまま"


def test_管理画面で場所を選んでクリアできる(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.admin_window import AdminWindow
    from dq3.ui.ui_settings import UiSettings

    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    QApplication.instance() or QApplication([])
    k = _knowledge(tmp_path)

    class _AVM:
        def _raw(self): return {}
        def position(self): return None

    class _Cmd:
        def send(self, action, **p): return 1

    asked = []
    w = AdminWindow(_AVM(), _Cmd(), speed=None, service=PD.PlayDataService(k, tmp_path / "vault"),
                    confirm=lambda t, x: asked.append((t, x)) or True, settings=UiSettings(tmp_path / "ui.json"))
    assert w.b_clear_place.text() == "この場所の会話記録をクリア"
    assert [w.c_place.itemData(i) for i in range(w.c_place.count())] == ["L14", "L9"]
    w.c_place.setCurrentIndex(0)
    w.do_clear_place()
    assert asked and "L14の会話記録をクリアします" in asked[0][1], asked
    assert "14" not in json.loads((k / "npc-heard.json").read_text(encoding="utf-8"))
    assert [w.c_place.itemData(i) for i in range(w.c_place.count())] == ["L9"], "⚠ 一覧が古いまま"


# --- ★Fact の番号の安定（RX3-0235 / 指示書 §14）---------------------------------

def _memo_file(path, orders):
    rows = [{"order": o, "text": "＊「はなし%d です。" % o, "source": "conversation", "location_id": "L%d" % (o % 2), "map_id": o % 2}
            for o in orders]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_途中のメモを消してもほかのメモの番号は変わらない(tmp_path):
    path = tmp_path / "memos.jsonl"
    _memo_file(path, [1, 2, 3, 4])
    before = {o.text: o.observation_id for o in C._memo_observations(path, [])}
    assert sorted(before.values()) == ["memo-o1", "memo-o2", "memo-o3", "memo-o4"], "⚠⚠ まだ行番号で作っている"
    M.MemoStore(path).remove_conversations("L1", [1])         # ★order 1・3 の場所を消す（★途中の行が消える）
    after = {o.text: o.observation_id for o in C._memo_observations(path, [])}
    assert after == {t: i for t, i in before.items() if t in after} and len(after) == 2, "⚠⚠ 後ろのメモの番号が変わった"


def test_行番号の番号から付け替える表(tmp_path):
    path = tmp_path / "memos.jsonl"
    _memo_file(path, [1, 2, 3])
    assert C.legacy_memo_ids(path) == {"memo-o1": "memo-0", "memo-o2": "memo-1", "memo-o3": "memo-2"}


def test_付け替えではTopicの更新回数を進めない(tmp_path):
    from dq3.knowledge import guide as G

    master = {"A": G.Topic(topic_id="A", title="あ")}
    rules = [G.Rule("r1", "A", "item", 1, "hint", weight=10)]
    book = G.TopicBook(master, rules, tmp_path / "s.json")
    old = C.fact_id_of("item:1", "hint", None, "memo-2")
    new = C.fact_id_of("item:1", "hint", None, "memo-o3")

    def fact(fid, obs):
        return {"fact_id": fid, "subject": "item:1", "predicate": "hint", "object": None,
                "source_observation_id": obs, "confidence": 1.0}

    book.apply(fact(old, "memo-2"))
    count, at = book.state("A").update_count, book.state("A").last_updated_at
    assert book.rename_facts({old: new}) == 1
    assert book.apply(fact(new, "memo-o3")) == [], "⚠⚠ 付け替えたのに同じ話を当て直した"
    assert book.state("A").update_count == count and book.state("A").last_updated_at == at
    assert book.state("A").matched_fact_ids == [new]
    # ⚠ 付け替えないと当て直す（★直す前の形 = 更新回数が進む）
    other = G.TopicBook(master, rules, tmp_path / "s2.json")
    other.apply(fact(old, "memo-2"))
    other.apply(fact(new, "memo-o3"))
    assert other.state("A").update_count == count + 1


def test_Factの番号の式は1か所():
    fact = C.Fact("item:1", "hint", None, "memo-o3", 1.0)
    assert fact.fact_id == C.fact_id_of("item:1", "hint", None, "memo-o3")

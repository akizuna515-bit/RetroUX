"""「？」で覚えた勇者メモに、次に話したとき話者を埋める（RX3-0236 / 2026-09-13）。

⚠⚠ 依頼者「うまく働かず話者が？で記憶されたら、 次話したら上書きされる」（★期待）。
⚠ これまでは同じ本文なら黙って足さず「？」が残り、⚠ 聞き込みの行は「兵「…」」と「？「…」」の重複になった。
★埋めるのは 同じ地点・同じ本文・話者が分からない行だけ（⚠ 推測で名乗らせない / 話者の分かった行は書き換えない）。
"""
from __future__ import annotations

import json

from dq3.knowledge import memos as M
from dq3.knowledge import playdata as PD


def _rows(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_本文の取り出し():
    assert M.talk_body("＊「こんにちは。") == "こんにちは。"
    assert M.talk_body("兵「こんにちは。」") == "こんにちは。"
    assert M.talk_body("？「こんにちは。」") == "こんにちは。"
    assert M.talk_body("★宝箱を見つけた") is None
    assert M.talk_body("ここは「どこ」だろう") is None        # ★先頭の字の後ろでない「 は会話ではない


def test_手で話した話者不明は次に話者が分かれば埋まる(tmp_path):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    store.add_if_new("＊「こんにちは。", location_id="L14", map_id=14, source=M.CONVERSATION)
    assert list(store)[0].line.startswith("？　")          # ★RX3-0253: 「」は出さない
    got = store.add_if_new("＊「こんにちは。", location_id="L14", map_id=14, source=M.CONVERSATION,
                           speaker="商", npc_id=3)
    assert got is None and store.last_filled is not None, "⚠ 新しい行として足した / 埋めていない"
    assert len(store) == 1
    memo = list(store)[0]
    assert memo.speaker == "商" and memo.line == "商　こんにちは。" and memo.npc_id == 3
    assert [m.speaker for m in M.MemoStore(store.path)] == ["商"], "⚠⚠ 記録に残っていない"


def test_聞き込みの話者不明の行も話者で埋まる(tmp_path):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    store.add_if_new("？「やあ」", location_id="L14", map_id=14, source=M.NPC_TALK, speaker="？")
    store.add_if_new("兵「やあ」", location_id="L14", map_id=14, source=M.NPC_TALK, speaker="兵", npc_id=5)
    assert [(m.text, m.speaker) for m in store] == [("兵「やあ」", "兵")], "⚠⚠ 「？」の重複が残った"


def test_話者が分かっている行は書き換えない(tmp_path):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    store.add_if_new("兵「やあ」", location_id="L14", map_id=14, source=M.NPC_TALK, speaker="兵")
    store.add_if_new("商「やあ」", location_id="L14", map_id=14, source=M.NPC_TALK, speaker="商")
    assert [m.speaker for m in store] == ["兵", "商"], "⚠ 別の人の話を上書きした"


def test_別の場所や話者が分からない聞き直しでは埋めない(tmp_path):
    store = M.MemoStore(tmp_path / "memos.jsonl")
    store.add_if_new("＊「こんにちは。", location_id="L14", map_id=14, source=M.CONVERSATION)
    store.add_if_new("＊「こんにちは。", location_id="L15", map_id=15, source=M.CONVERSATION, speaker="商")
    store.add_if_new("＊「こんにちは。", location_id="L14", map_id=14, source=M.CONVERSATION, speaker="？")
    assert [(m.location_id, m.speaker) for m in store] == [("L14", None), ("L15", "商")]


def test_書き直してもほかの行と改行と知らない欄はそのまま(tmp_path):
    path = tmp_path / "memos.jsonl"
    first = json.dumps({"order": 1, "text": "★宝箱", "source": "discovery", "未来の欄": 1}, ensure_ascii=False)
    target = json.dumps({"order": 2, "text": "＊「こんにちは。", "source": "conversation", "location_id": "L14",
                         "map_id": 14, "未来の欄": "残す"}, ensure_ascii=False)
    path.write_bytes(("\r\n".join([first, "{壊れた行", target]) + "\r\n").encode("utf-8"))
    store = M.MemoStore(path)
    assert store.failed == 1
    store.add_if_new("＊「こんにちは。", location_id="L14", map_id=14, source=M.CONVERSATION, speaker="商")
    after = path.read_bytes().decode("utf-8")
    parts = after.split("\r\n")
    assert parts[0] == first and parts[1] == "{壊れた行", "⚠⚠ ほかの行を書き換えた"
    row = json.loads(parts[2])
    assert row["speaker"] == "商" and row["未来の欄"] == "残す"
    assert after.endswith("\r\n") and "\n" not in after.replace("\r\n", ""), "⚠ 改行が変わった"
    assert not (tmp_path / "memos.jsonl.tmp").exists()


def test_作り直しは話者の字だけ違う行を足さない(tmp_path):
    """⚠⚠ 差し替えのある町（map 71）では作り直しの話者が必ず「？」→ ★同じ本文があれば足さない。"""
    d = tmp_path / "dq3-knowledge"
    d.mkdir()
    (d / "npc-conversations.json").write_text(json.dumps({"71/2": [{
        "npc_id": 2, "talk_id": 1, "text_hash": "a", "text": "＊「おしろへ ようこそ。",
        "first_heard_at": "2026-09-05T09:00:00", "last_heard_at": "2026-09-05T09:00:00", "count": 1}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "memos.jsonl").write_text(json.dumps({
        "order": 1, "text": "兵「おしろへ ようこそ。」", "source": "npc_talk", "map_id": 71, "location_id": "L71",
        "speaker": "兵"}, ensure_ascii=False) + "\n", encoding="utf-8")
    got = PD.PlayDataService(knowledge_dir=d).rebuild_hearing_memos()
    assert got["added"] == 0, "⚠⚠ 「？「…」」の重複を足した: %s" % got
    assert [r["text"] for r in _rows(d / "memos.jsonl")] == ["兵「おしろへ ようこそ。」"]

"""プレイデータの service（RX3-0059）。★項目別に消える / 選んでいないものは触らない / 退避 → 変更 → 復元で戻る。"""
from __future__ import annotations

import json
import pathlib

from dq3.knowledge import playdata as PD


def _make(tmp_path) -> tuple[PD.PlayDataService, pathlib.Path]:
    k = tmp_path / "knowledge"
    k.mkdir()
    (k / "seen.json").write_text('{"cells": [1, 2]}', encoding="utf-8")
    (k / "enemy-names.json").write_text('{"1": "スライム"}', encoding="utf-8")
    (k / "player-knowledge.json").write_text('{"visited_locations": ["L9"]}', encoding="utf-8")
    rows = [{"order": 1, "text": "＊「ようこそ", "source": "conversation"},
            {"order": 2, "text": "主「やど", "source": "npc_talk"},
            {"order": 3, "text": "宝箱", "source": "discovery"}]
    (k / "memos.jsonl").write_text("\r\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\r\n", encoding="utf-8")
    (k / "npc-heard.json").write_text('{"9": {"1": {"count": 1}, "6": {"count": 1}}}', encoding="utf-8")
    (k / "npc-conversations.json").write_text('{"9/1": []}', encoding="utf-8")
    return PD.PlayDataService(k, tmp_path / "vault"), k


def test_数えるだけでは何も変わらない(tmp_path):
    svc, k = _make(tmp_path)
    before = {p.name: p.read_bytes() for p in k.iterdir()}
    st = svc.status()
    assert st["hearing"]["heard_npcs"] == 2 and st["hearing"]["memo_lines"] == 1
    assert st["memos"]["files"][0]["lines"] == 3
    assert {p.name: p.read_bytes() for p in k.iterdir()} == before


def test_聞き込み履歴だけ消えて地図とモンスターは残る(tmp_path):
    svc, k = _make(tmp_path)
    got = svc.clear(["hearing"])
    assert not (k / "npc-heard.json").exists() and not (k / "npc-conversations.json").exists()
    assert (k / "seen.json").exists() and (k / "enemy-names.json").exists()
    rows = [json.loads(l) for l in (k / "memos.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["source"] for r in rows] == ["conversation", "discovery"]        # ★npc_talk の行だけ抜けた
    assert b"\r\n" in (k / "memos.jsonl").read_bytes()                            # ★改行は変えない
    assert got["backup"] and (tmp_path / "vault" / got["backup"] / "npc-heard.json").exists()


def test_選んだ項目だけ消える(tmp_path):
    svc, k = _make(tmp_path)
    svc.clear(["seen", "monsters"])
    assert not (k / "seen.json").exists() and not (k / "enemy-names.json").exists()
    assert (k / "memos.jsonl").exists() and (k / "npc-heard.json").exists()


def test_退避して変えて戻すと元に戻る(tmp_path):
    svc, k = _make(tmp_path)
    before = {p.name: p.read_bytes() for p in k.iterdir()}
    bak = svc.backup("t")
    assert (bak / "manifest.json").exists()
    svc.clear(["hearing", "seen"], backup=False)
    (k / "enemy-names.json").write_text("{}", encoding="utf-8")
    got = svc.restore("latest")
    # ★restore は「いまの状態」も先に退避するので、latest は before-restore ではなく明示の名前で戻す必要がある
    if got["source"] != bak.name:
        got = svc.restore(bak.name)
    assert {p.name: p.read_bytes() for p in k.iterdir()} == before, got


def test_触らないものの一覧にROMとtoolsがある():
    names = {p.name for p in PD.NEVER_TOUCH}
    assert {"rom", "tools", "input", "dq3-probe", "data"}.issubset(names)


def test_確認の文に消すものと消さないものが出る():
    text = PD.describe(["hearing"])
    assert "聞き込み履歴" in text and "見た地図" in text and "ROM" in text


# --- ★勇者メモを聞き込みの記録から作り直す（RX3-0098）-----------------------------

def _hearing_fixture(tmp_path):
    """★会話の記録だけがあって、⚠ 勇者メモが空の状態を作る。"""
    import json

    d = tmp_path / "dq3-knowledge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "npc-conversations.json").write_text(json.dumps({
        "70/3": [{"npc_id": 3, "talk_id": 565, "text_hash": "aaaa", "text": "＊「おひめさまを みませんでした？",
                  "first_heard_at": "2026-09-05T09:12:48", "last_heard_at": "2026-09-05T09:12:48", "count": 1}],
        "70/7": [{"npc_id": 7, "talk_id": 570, "text_hash": "bbbb", "text": "＊「とうぞくバコタの カギ。",
                  "first_heard_at": "2026-09-05T09:14:10", "last_heard_at": "2026-09-05T09:14:10", "count": 1}],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "memos.jsonl").write_text("", encoding="utf-8")
    return d


def test_消えた勇者メモを聞き込みの記録から作り直す(tmp_path):
    """⚠⚠ 2026-09-07 依頼者「勇者メモ初期化のあと、聞き込みが事前チェックで走らない」。

    ★`heard` は残っているので「もう聞いた」と判定され、⚠ 聞き直せません。
    → ★本文は `npc-conversations.json` に**残っている**ので、そこから作り直します。
    """
    from dq3.knowledge import playdata as P

    d = _hearing_fixture(tmp_path)
    got = P.PlayDataService(knowledge_dir=d).rebuild_hearing_memos()
    assert got["added"] == 2, got
    lines = [ln for ln in (d / "memos.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2


def test_作り直しても同じメモを二度足さない(tmp_path):
    """⚠ 2 回押しても増えないこと（★冪等）。"""
    from dq3.knowledge import playdata as P

    d = _hearing_fixture(tmp_path)
    P.PlayDataService(knowledge_dir=d).rebuild_hearing_memos()
    again = P.PlayDataService(knowledge_dir=d).rebuild_hearing_memos()
    assert again["added"] == 0, again
    lines = [ln for ln in (d / "memos.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2


def test_作り直しは聞き込み以外のメモを触らない(tmp_path):
    """⚠⚠ ふつうの会話メモ・地図のメモを増やしalso減らしもしない。"""
    import json

    from dq3.knowledge import playdata as P

    d = _hearing_fixture(tmp_path)
    (d / "memos.jsonl").write_text(json.dumps(
        {"order": 1, "text": "★手で書いたメモ", "source": "manual", "map_id": 9},
        ensure_ascii=False) + chr(10), encoding="utf-8")
    P.PlayDataService(knowledge_dir=d).rebuild_hearing_memos()
    rows = [json.loads(ln) for ln in (d / "memos.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert sum(1 for r in rows if r.get("source") == "manual") == 1
    assert sum(1 for r in rows if r.get("source") == "npc_talk") == 2


def test_勇者メモだけ消すと食い違うと警告する():
    """⚠⚠ 2026-09-07 依頼者「管理→勇者メモ初期化で同期がズレた？」→ ★当たり。

    ★`memos`（勇者メモ）と `hearing`（聞き込み履歴）は**別の項目**で、
    ⚠ 勇者メモだけ消すと **[メモ詳細] には残り、[図] からは消えます**。
    → ★消す前に、そのことを出します（⚠ 消し方は変えません）。
    """
    from dq3.knowledge import playdata as P

    got = P.describe(["memos"])
    assert "メモ詳細" in got, "⚠ 食い違いの警告が無い"
    assert "作り直" in got, "⚠ 戻し方を書いていない"
    # ⚠ 両方いっしょなら食い違わないので、★その警告は出さない
    both = P.describe(["memos", "hearing"])
    assert "メモ詳細" not in both
    # ★聞き込み履歴だけなら今までどおり
    assert "メモ詳細" not in P.describe(["hearing"])

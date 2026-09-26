"""冒険ログ v0（RX3-0150 / 2026-09-10）。

⚠⚠ **いちばん大事な決まり**: 欠けているものを「無い」と書く。
★書かないと、読んだ生成 AI が**埋めて作文します**（= 嘘の冒険ログ）。
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """★書き先を写しへ向ける（⚠ 本物の記録を読み書きしない）。"""
    from dq3 import paths

    (tmp_path / "work" / "dq3-knowledge").mkdir(parents=True)
    (tmp_path / "work" / "dq3-probe").mkdir(parents=True)
    monkeypatch.setattr(paths, "work",
                        lambda *parts: tmp_path.joinpath("work", *parts))
    return tmp_path / "work"


def _write(sandbox, name, body):
    (sandbox / "dq3-knowledge" / name).write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")


# --- ⚠⚠ 埋めさせない ---------------------------------------------------

def test_読んだAIへ何が無いかを伝える(sandbox):
    from dq3.knowledge import adventure_log as AL

    text = AL.build(state={})
    assert "推測で補わないでください" in text, "⚠⚠ 埋めるなと言っていない"
    for want in ("手動で戦った戦闘", "いつ", "レベルアップ"):
        assert want in text, "⚠ 「%s が無い」と書いていない" % want


def test_記録が無いときは無いと書く(sandbox):
    """⚠⚠ **空欄にしない。** ★「まだ記録がありません」と言葉にする。"""
    from dq3.knowledge import adventure_log as AL

    text = AL.build(state={})
    assert text.count("まだ記録がありません") >= 3
    assert "⚠ パーティの記録が届いていません" in text


def test_知らない話は出さない(sandbox):
    """⚠⚠ `unknown` の Topic は冒険ログにも出さない（RX3-0117 と同じ濾し器）。"""
    from dq3.knowledge import adventure_log as AL

    _write(sandbox, "topic-state.json", {"topics": {
        "T001": {"status": "active", "last_updated_at": "2026-09-07T12:00:00"},
        "T099": {"status": "unknown"},
    }})
    text = AL.build(state={})
    assert "T001" in text
    assert "T099" not in text, "⚠⚠ 勇者が知らない話が漏れている"


# --- ★中身 --------------------------------------------------------------

def test_訪れた順に場所が並ぶ(sandbox):
    from dq3.knowledge import adventure_log as AL

    _write(sandbox, "location-book.json", {
        "visit_order": ["L2", "L1"],
        "locations": {
            "L1": {"display_name": "レーベ", "visited": True,
                   "first_seen_at": "2026-09-07T23:00:00"},
            "L2": {"display_name": "アリアハン", "visited": True},
        }})
    text = AL.build(state={})
    assert text.index("アリアハン") < text.index("レーベ"), "⚠ 訪れた順でない"
    assert "2026-09-07 23:00" in text


def test_話者と本文が1か所の整形を通る(sandbox):
    """⚠ `＊「` の扱いを 2 か所に書かない（★`Memo.line` を使う / RX3-0118）。"""
    from dq3.knowledge import adventure_log as AL

    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        json.dumps({"order": 1, "text": "＊「ここは レーベ。＊「ようこそ。",
                    "source": "conversation", "speaker": "商"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    text = AL.build(state={})
    # ★RX3-0253: 行は「字　本文」（★「」は開き・閉じとも出さない / 続きの段の「は空白）
    assert "商　ここは レーベ。　ようこそ。" in text
    assert "商「" not in text, "⚠ 勇者メモの行と違う整形を通っている（★かぎ括弧が残った）"
    assert "＊" not in text, "⚠ 会話開始記号がそのまま出ている"
    assert "？「「" not in text, "⚠⚠ かぎ括弧が二重になっている"


def test_パーティは届いた値だけ出す(sandbox):
    from dq3.knowledge import adventure_log as AL

    text = AL.build(state={"party": [{"level": 7, "hp": 30, "max_hp": 40,
                                      "mp": 5, "max_mp": 9}], "gold": 172})
    assert "Lv7" in text and "30/40" in text and "172 G" in text


# --- ⚠⚠ 単位を偽らない --------------------------------------------------

def test_ターンと行動を分けて書く(sandbox):
    """⚠⚠ `rounds` が人の言う「ターン」、`actions` は **1 人 1 回**（RX3-0153）。

    ★実測（2026-09-10 / `auto_v0.log`）:

    ```text
    AUTO_V0 turn=33 slot=p1 / 34 p2 / 35 p3 / 36 p4
    ```

    → ⚠ 4 人なら **1 ターン = 4 行動**。★「ターン」と書くと 4 倍に読めます。
    """
    from dq3.knowledge import adventure_log as AL

    (sandbox / "dq3-probe" / "auto_v0.log").write_text(
        "AUTO_V0_DONE 戦闘が終わった（…） rounds=9 actions=36\n"
        "AUTO_V0_DONE 戦闘が終わった（…） rounds=6 actions=24\n"
        "AUTO_V0_STOP reason=screen_frozen\n", encoding="utf-8")
    got = AL.battles()
    assert got == {"battles": 2, "rounds": 15, "actions": 60, "old": 0,
                   "stopped": 1, "reasons": {"screen_frozen": 1}}
    text = AL.build(state={})
    assert "自動戦闘 2 戦 / のべ 15ターン（60行動）" in text
    assert "平均 8 ターン（30 行動）" in text
    assert "1 ターン = 4 行動" in text, "⚠ 単位を説明していない"
    assert "手で戦ったぶんは、この数に入っていません" in text
    assert "記録の全期間" in text, "⚠⚠ 「今回の起動ぶん」と読めてしまう"


def test_古い記録はターンを名乗らない(sandbox):
    """⚠⚠ 旧 `turns=N` は **(1) 行動の数 (2) 戦闘をまたいで累積** の 2 重の誤り。

    ★実測（2026-09-10 / `auto_v0.log`）: 8 / 16 / 24 / 32 と増え続けていた。
    → ★差を取って 8・8・8 にし、⚠ **ターン数は「無い」と書く**（推測で割らない）。
    """
    from dq3.knowledge import adventure_log as AL

    (sandbox / "dq3-probe" / "auto_v0.log").write_text(
        "=== AUTO_V0 start\n"
        "AUTO_V0_DONE 戦闘が終わった（…） turns=8\n"
        "AUTO_V0_DONE 戦闘が終わった（…） turns=16\n"
        "AUTO_V0_DONE 戦闘が終わった（…） turns=24\n", encoding="utf-8")
    got = AL.battles()
    assert got["actions"] == 24, "⚠⚠ 累積をそのまま足している（★48 になる）"
    assert got == {"battles": 3, "rounds": 0, "actions": 24, "old": 3,
                   "stopped": 0, "reasons": {}}
    text = AL.build(state={})
    assert "自動戦闘 3 戦 / のべ 24行動" in text
    assert "ターン" not in text.split("自動戦闘 3 戦")[1].split("\n")[0], \
        "⚠⚠ 分からないターン数を名乗っている"
    assert "3 戦は古い記録で、ターン数が残っていません" in text


def test_壊れた行があっても続ける(sandbox):
    from dq3.knowledge import adventure_log as AL

    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        "{ これは JSON ではない\n"
        + json.dumps({"order": 2, "text": "のこった", "source": "discovery"},
                     ensure_ascii=False) + "\n", encoding="utf-8")
    text = AL.build(state={})
    assert "のこった" in text


def test_時刻の無い行は時系列へ入れない(sandbox):
    """★「順番だけ」の行を、⚠ 時刻があるかのように並べない。"""
    from dq3.knowledge import adventure_log as AL

    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        json.dumps({"order": 1, "text": "むかしの行", "source": "conversation"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    text = AL.build(state={})
    body = text.split("## 8")[1]
    assert "むかしの行" not in body, "⚠⚠ 時刻の無い行を時系列へ入れている"
    assert "時刻つきの記録がまだありません" in body


# --- ★つなぎ -------------------------------------------------------------

def test_外へ送らない():
    """⚠⚠ 依頼者の指示: 「生成 AI API との直接接続は不要」。"""
    src = (ROOT / "dq3" / "knowledge" / "adventure_log.py").read_text(encoding="utf-8")
    for banned in ("requests", "urllib", "http", "openai", "anthropic", "socket"):
        assert banned not in src.lower(), "⚠⚠ 外へ送っている: %s" % banned


def test_新しいログ基盤を作っていない():
    """★読むだけ（⚠ 書かない / 依頼者の指示「大規模な共通ログ基盤へ書き換えない」）。"""
    src = (ROOT / "dq3" / "knowledge" / "adventure_log.py").read_text(encoding="utf-8")
    for banned in ("write_text", "open(", "mkdir", "json.dump("):
        assert banned not in src, "⚠⚠ 書いている: %s" % banned


def test_勇者会議にコピーの口がある():
    src = (ROOT / "dq3" / "ui" / "council_window.py").read_text(encoding="utf-8")
    assert "冒険ログをコピー" in src
    assert "def copy_adventure_log" in src
    assert "setText(text)" in src, "⚠ clipboard へ入れていない"


def test_コピーが本物の記録から作れる():
    """★本物の記録で 1 度通す（⚠ 中身は見ない / 遊ぶと変わる）。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from dq3.ui.council_window import Dq3CouncilWindow

    QApplication.instance() or QApplication([])
    got = Dq3CouncilWindow().copy_adventure_log()
    assert "冒険の記録" in got
    assert "作れませんでした" not in got, got[:200]

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
    """★書き先を写しへ向ける（⚠ 本物の記録を読み書きしない）。

    ★場所の名前の表（`location-names.csv`）・Master・勇者メモの原本も**空の写し**へ向ける
      （RX3-0518 / ⚠ repo の表の名前が検査の場所に乗らないように）。
    """
    from dq3 import paths
    from dq3.knowledge import hero_memo, location_master, locations

    (tmp_path / "work" / "dq3-knowledge").mkdir(parents=True)
    (tmp_path / "work" / "runtime" / "dq3-probe").mkdir(parents=True)
    monkeypatch.setattr(paths, "work",
                        lambda *parts: tmp_path.joinpath("work", *parts))
    monkeypatch.setattr(locations, "NAMES_PATH", tmp_path / "no-location-names.csv")
    monkeypatch.setattr(location_master, "CANDIDATE_PATHS", ())
    monkeypatch.setattr(hero_memo, "DEFAULT_PATH", tmp_path / "hero-memo.yaml")
    return tmp_path / "work"


def _write(sandbox, name, body):
    (sandbox / "dq3-knowledge" / name).write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8")


# --- ⚠⚠ 埋めさせない ---------------------------------------------------

def test_読んだAIへ何が無いかを伝える(sandbox):
    from dq3.knowledge import adventure_log as AL

    text = AL.build(state={})
    assert "推測で補わないでください" in text, "⚠⚠ 埋めるなと言っていない"
    missing = text.split("この記録に**無いもの")[1]
    for want in ("手で戦った戦闘", "呪文を覚えたこと", "セーブ／ロード"):
        assert want in missing, "⚠ 「%s が無い」と書いていない" % want


def test_有るものを無いと書かない(sandbox):
    """⚠⚠ RX3-0518 §5: レベルアップと入手の時刻は**残っている**（★旧版は「記録していません」と書いていた）。"""
    from dq3.knowledge import adventure_log as AL

    missing = AL.MISSING
    assert "レベルアップと呪文の習得は記録していません" not in AL.build(state={})
    assert "アイテムを「いつ」手に入れたか" not in missing
    assert "「レベルが上がりました」と残ります" in missing, "⚠ 残っている範囲を書いていない"
    assert "初めて増えたときのもの" in missing, "⚠ 入手の時刻が残っている範囲を書いていない"


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

    # ★RX3-0518: 帳面は画面と同じ `LocationBook` で読む（⚠ 本物の行には必ず `location_id` がある）
    _write(sandbox, "location-book.json", {
        "visit_order": ["L2", "L1"],
        "locations": {
            "L1": {"location_id": "L1", "display_name": "レーベ", "name_source": "rom",
                   "visited": True, "first_seen_at": "2026-09-07T23:00:00"},
            "L2": {"location_id": "L2", "display_name": "アリアハン", "name_source": "rom",
                   "visited": True},
        }})
    text = _section(AL.build(state={}), "## 4")
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

    (sandbox / "runtime" / "dq3-probe" / "auto_v0.log").write_text(
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

    (sandbox / "runtime" / "dq3-probe" / "auto_v0.log").write_text(
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
        + json.dumps({"order": 2, "text": "のこった", "source": "conversation"},
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

@pytest.mark.parametrize("ever, acquired, memo_rows, want", [
    ([1, 2], [], [], 2),                                         # ★持ち物で見えた品だけ（今までどおり）
    ([1], [3], [], 2),                                           # ★記録の acquired だけに在る品
    ([1], [], [{"source": "chest", "item_id": "120"},            # ★勇者メモの入手行（⚠ id は文字列）
               {"source": "unknown", "item_id": "121"}], 3),
    ([1], [], [{"source": "npc_talk", "item_id": "9"},           # ⚠ 入手ではない行は数えない
               {"source": "chest", "item_id": None}], 1),
    ([120], [120], [{"source": "chest", "item_id": "120"}], 1),  # ⚠ 重なりは 1 つに
])
def test_手に入れた品の数は一度でも手に入れた品で数える(sandbox, ever, acquired, memo_rows, want):
    """⚠⚠ RX3-0490: `items_ever` だけだと、拾ってすぐ手放した品（★オーブなど）が件数から抜けていた。"""
    from dq3.knowledge import adventure_log as AL

    _write(sandbox, "progress.json", {"items_ever": ever, "acquired": acquired})
    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in memo_rows), encoding="utf-8")
    text = AL.build(state={})
    assert "手に入れた品 %d 種類" % want in text, [ln for ln in text.splitlines() if "手に入れた品" in ln]


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


# --- ★RX3-0518（F1）: 現在地・仲間・進み具合・仮名・名称未設定・並び・雑音 ---------

def _book(sandbox, locations, visit_order=None):
    rows = {}
    for lid, row in locations.items():
        got = {"location_id": lid, "visited": True}
        got.update(row)
        rows[lid] = got
    _write(sandbox, "location-book.json", {
        "visit_order": visit_order if visit_order is not None else list(rows),
        "locations": rows})


def _section(text, head):
    """★「## n 見出し」から次の「## 」まで。"""
    return text.split(head, 1)[1].split("\n## ", 1)[0]


def test_現在地を名前で出し仮名には印を付ける(sandbox):
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {
        "L0": {"display_name": "アリアハン", "name_source": "rom", "map_ids": [0]},
        "L45": {"display_name": "アリアハン南の場所", "name_source": "provisional", "map_ids": [45]},
    })
    here = _section(AL.build(state={"loc_kind": 1, "map_id": 0, "map_x": 3, "map_y": 4}), "## 1")
    assert "現在地: アリアハン\n" in here + "\n"
    assert "（仮名）" not in here, "⚠ 正式な名前に仮名の印が付いた"
    here = _section(AL.build(state={"loc_kind": 1, "map_id": 45, "map_x": 3, "map_y": 4}), "## 1")
    assert "現在地: アリアハン南の場所（仮名）" in here, "⚠⚠ 仮名を正式名のように出している"


def test_世界地図ではいちばん近い町を添える(sandbox):
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {
        "L0": {"display_name": "アリアハン", "name_source": "rom", "map_ids": [0],
               "world_x": 100, "world_y": 100, "world_kind": 0},
        "L1": {"display_name": "ロマリア", "name_source": "rom", "map_ids": [1],
               "world_x": 10, "world_y": 10, "world_kind": 0},
    })
    here = _section(AL.build(state={"loc_kind": 0, "map_id": None, "map_x": 98, "map_y": 101}), "## 1")
    assert "現在地: 世界地図" in here
    assert "いちばん近い、名前の分かっている町: アリアハン" in here


def test_いまの場所が届いていなければ最後に入った場所を記録から(sandbox):
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {
        "L0": {"display_name": "アリアハン", "name_source": "rom", "map_ids": [0]},
        "L9": {"display_name": "レーベ南の場所", "name_source": "provisional", "map_ids": [9]},
    }, visit_order=["L0", "L9"])
    here = _section(AL.build(state={}), "## 1")
    assert "現在地: ⚠ 届いていません" in here
    assert "最後に入った場所（記録から）: レーベ南の場所（仮名）" in here


def test_仲間を名前と職業で出す(sandbox):
    """★`name_tiles` は字形表の下位 1 バイト（★本物の state.json の 4 人で確かめた / RX3-0518）。"""
    from dq3.knowledge import adventure_log as AL

    party = [
        {"name": "p1", "name_tiles": [11, 16, 50, 0], "class_gender": 8, "level": 46,
         "hp": 407, "max_hp": 407, "mp": 63, "max_mp": 146},
        {"name": "p2", "name_tiles": [91, 87, 69, 73], "class_gender": 4, "level": 43,
         "hp": 384, "max_hp": 384, "mp": 52, "max_mp": 74},
        {"name": "p3", "name_tiles": [999], "class_gender": None, "level": 5,
         "hp": 1, "max_hp": 2, "mp": 0, "max_mp": 0},
    ]
    text = AL.build(state={"party": party, "gold": 172})
    assert "あかり / 勇者 / Lv46 / HP 407/407 / MP 63/146" in text
    assert "エルシト / 戦士 / Lv43" in text
    assert "3 人目 / Lv5 / HP 1/2" in text, "⚠ 読めない名前・職業を推測で埋めている"
    assert "p1" not in _section(text, "## 1"), "⚠ 内部の枠名がそのまま出ている"


def test_物語の旗を言葉で出す(sandbox):
    from dq3.knowledge import adventure_log as AL

    _write(sandbox, "progress.json", {"story": ["ship_obtained", "mystery_flag"]})
    story = _section(AL.build(state={}), "## 2")
    assert "船を手に入れた" in story
    assert "ship_obtained" not in story, "⚠⚠ 内部 ID のまま"
    assert "mystery_flag（名称未設定）" in story, "⚠ 言葉の無い旗を推測で名付けている / 黙って捨てている"
    assert "起きていない」という意味ではありません" in story


def _hero_memo(tmp_path):
    (tmp_path / "hero-memo.yaml").write_text(
        "schema_version: 1\n"
        "scenarios:\n  castle:\n    title: 城への道\n"
        "leads:\n"
        "  - id: 200_zoma\n    memo: 城に乗り込む\n    scenario: castle\n"
        "    appears_when:\n      - 聞いた: あいう\n    retires_when:\n      - 入手した: かきく\n"
        "  - id: 300_key\n    memo: 鍵を探す\n    done: 鍵を手に入れた\n"
        "    appears_when:\n      - 聞いた: さしす\n    retires_when:\n      - 入手した: たちつ\n"
        "  - id: 400_secret\n    memo: まだ知らない話の中身\n"
        "    appears_when:\n      - 聞いた: なにぬ\n    retires_when:\n      - 入手した: はひふ\n",
        encoding="utf-8")


def test_話は勇者メモの言葉で出し名前の無いIDは名称未設定(sandbox):
    """★RX3-0518 §3: `200_zoma` → 勇者メモの memo / ⚠ 引けない `T017` は「（名称未設定）」。"""
    from dq3.knowledge import adventure_log as AL

    _hero_memo(sandbox.parent)
    _write(sandbox, "topic-state.json", {"topics": {
        "200_zoma": {"status": "active", "first_seen_at": "2026-09-27T19:34:10"},
        "300_key": {"status": "resolved", "last_updated_at": "2026-09-28T21:27:00"},
        "400_secret": {"status": "unknown"},
        "T017": {"status": "resolved", "last_updated_at": "2026-09-14T20:52:59"},
    }})
    topics = _section(AL.build(state={}), "## 3")
    assert "［城への道］城に乗り込む" in topics
    assert "鍵を手に入れた" in topics, "⚠ 片づいた話は done の文"
    assert "200_zoma" not in topics and "300_key" not in topics, "⚠⚠ 内部 ID のまま"
    assert "T017（名称未設定）" in topics
    assert "まだ知らない話" not in topics and "400_secret" not in topics, \
        "⚠⚠ 勇者が知らない話が漏れている（RX3-0117）"
    assert "2026-09-2" not in topics, "⚠ 判定した時刻を遊んだ時刻のように出している"


def test_訪れた場所ははじめて入った時刻の順で仮名に印(sandbox):
    """⚠⚠ `visit_order` は直近に居た順（★入り直すと後ろへ回る）。★はじめて入った時刻で並べる。"""
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {
        "L0": {"display_name": "アリアハン", "name_source": "rom", "map_ids": [0],
               "first_seen_at": "2026-09-07T10:00:00"},
        "L9": {"display_name": "レーベ南の場所", "name_source": "provisional", "map_ids": [9],
               "first_seen_at": "2026-09-08T10:00:00"},
        "L27": {"display_name": "レーベの小部屋1", "name_source": "provisional", "map_ids": [27],
                "first_seen_at": "2026-09-09T10:00:00"},
        "L70": {"display_name": "アリアハンの城", "name_source": "manual", "map_ids": [70]},
    }, visit_order=["L70", "L9", "L27", "L0"])
    places = _section(AL.build(state={}), "## 4")
    assert places.index("アリアハンの城") < places.index("アリアハン　") < places.index("レーベ南の場所"), places
    assert "レーベ南の場所（仮名）" in places
    assert "アリアハン（仮名）" not in places and "アリアハンの城（仮名）" not in places
    assert "レーベの小部屋1" not in places, "⚠ 仮名の小部屋を 1 つずつ並べている"
    assert "建物の中の小部屋 1 か所" in places


def test_起動と操作の失敗は外して数だけ書く(sandbox):
    """★RX3-0518 §7: 起動・RetroUX の操作の失敗はゲームの出来事ではない（⚠ 診断の記録には残す）。"""
    from dq3.events import writer as EW
    from dq3.knowledge import adventure_log as AL

    log = sandbox.joinpath(*EW.LOG_DIR, EW.PRODUCT_NAME)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "2026-09-30T08:54:41 RetroUX DQ3 1.1.0 / build 884c26b（gui）\n"
        "2026-09-30 08:55 自動戦闘：勝利 2ターン（8行動）\n"
        "2026-09-30 08:56 自動移動：道がふさがっています\n"
        "2026-09-30 08:57 まんたん：窓を閉じられません / 3人回復 / HP +247\n"
        "2026-09-30 08:58 新しい種類：知らない行\n"
        "2026-09-30 08:59 自動移動：宿屋に到着\n", encoding="utf-8")
    acts = _section(AL.build(state={}), "## 8")
    assert "RetroUX DQ3 1.1.0" not in acts, "⚠⚠ 起動が冒険の出来事に混ざっている"
    assert "道がふさがっています" not in acts, "⚠ 操作の失敗がゲームの出来事に見える"
    assert "3人回復" in acts, "⚠ 回復した事実まで消した（★失敗の語があっても結果のある行は残す）"
    assert "知らない行" in acts, "⚠⚠ 分からない行を黙って消した"
    assert "起動 1 行" in acts and "失敗・中断 1 行" in acts
    assert acts.index("勝利") < acts.index("宿屋に到着"), "⚠ 古い順でない"
    assert log.read_text(encoding="utf-8").count("\n") == 6, "⚠⚠ 診断の記録を書き換えた"


def test_同じ入手と同じ発見を2行にしない(sandbox):
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {"L18": {"display_name": "ドムドーラ", "name_source": "rom", "map_ids": [18],
                            "first_seen_at": "2026-09-21T13:47:00"}})
    rows = [
        {"order": 1, "text": "ドムドーラを見つけた", "source": "discovery", "location_id": "L18",
         "at": "2026-09-21T13:47:01"},
        {"order": 2, "text": "ドムドーラ　しらべる：オリハルコン を入手", "source": "search",
         "location_id": "L18", "item_id": "94", "at": "2026-09-21T13:50:14"},
        {"order": 3, "text": "ドムドーラ　入手：オリハルコン", "source": "item",
         "location_id": "L18", "item_id": "94", "at": "2026-09-21T13:50:40"},
        {"order": 4, "text": "ドムドーラ　入手：ちからのたて", "source": "item",
         "location_id": "L18", "item_id": "60", "at": "2026-09-21T13:52:00"},
    ]
    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    text = AL.build(state={})
    got = _section(text, "## 6")
    assert "しらべる：オリハルコン" in got and "入手：ちからのたて" in got
    assert "入手：オリハルコン" not in got, "⚠ 同じ品の入手を 2 行にしている"
    timeline = _section(text, "## 9")
    assert "はじめて ドムドーラ へ入った" in timeline
    assert "ドムドーラを見つけた" not in timeline, "⚠ 同じ発見を 2 行にしている"


def test_入手の行の地名にも仮名の印(sandbox):
    """⚠ 勇者メモの地名は**書いた時の名前**（★仮名のまま焼かれている）→ ★いまの呼び名＋印にする。"""
    from dq3.knowledge import adventure_log as AL

    _book(sandbox, {"L83": {"display_name": "イシス西の場所 2", "name_source": "provisional",
                            "map_ids": [83]}})
    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(json.dumps(
        {"order": 1, "text": "イシス西の場所 2　宝箱：992 ゴールド を入手", "source": "chest",
         "location_id": "L83", "at": "2026-09-14T21:27:25"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    got = _section(AL.build(state={}), "## 6")
    assert "イシス西の場所 2（仮名）　宝箱：992 ゴールド を入手" in got


def test_どの節も古い順と見出しに書く(sandbox):
    """★RX3-0518 §6: 向きを揃え、⚠ **見出しで言う**（★「新しい順」と書いて古い順に並べていた）。"""
    from dq3.knowledge import adventure_log as AL

    text = AL.build(state={})
    assert "新しい順" not in text, "⚠⚠ 見出しと並びが食い違う（★旧版）"
    for head in ("## 5", "## 6", "## 8", "## 9"):
        assert "古い順" in text.split(head, 1)[1].split("\n", 1)[0], head


def test_形の違う記録でも冒険ログ全体を失わない(sandbox):
    """⚠ 1 つの記録の形が違うだけで、貼る冒険ログが丸ごと作れなくならない（RX3-0518 のレビュー）。"""
    from dq3.knowledge import adventure_log as AL

    _write(sandbox, "progress.json", [])
    _write(sandbox, "topic-state.json", {"topics": []})
    (sandbox / "dq3-knowledge" / "memos.jsonl").write_text(
        json.dumps({"order": "3", "text": "文字の順番", "source": "conversation", "at": 123},
                   ensure_ascii=False) + "\n"
        + json.dumps({"order": 1, "text": "数の順番", "source": "conversation",
                      "at": "2026-09-14T20:00:00"}, ensure_ascii=False) + "\n", encoding="utf-8")
    text = AL.build(state={"loc_kind": "x", "map_id": "y",
                           "party": [{"name_tiles": [11], "level": None, "hp": None}]})
    assert "数の順番" in text and "文字の順番" in text
    assert "現在地: ⚠ 届いていません" in text
    assert "None" not in _section(text, "## 1"), "⚠ 読めない欄を None と書いている"


def test_仲間の名前の字形は本物の4人で読める():
    """★`NAME_TILE_BASE` の根拠（★本物の `state.json` / `party_panel.JOBS` の実測名と同じ 4 人）。"""
    from dq3.knowledge import name_text as NT

    got = [NT.party_name(t) for t in ([11, 16, 50, 0], [91, 87, 69, 73],
                                       [77, 90, 75, 89], [89, 82, 63, 0])]
    assert got == ["あかり", "エルシト", "ハンソロ", "ロミオ"]
    assert NT.party_name([0, 0, 0, 0]) is None, "⚠ 空白だけの名前を名前として出している"
    assert NT.party_name(None) is None

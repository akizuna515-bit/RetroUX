"""勇者メモ詳細の自由文言の検索（RX3-0289 / 2026-09-18）。

⚠⚠ 依頼者「勇者メモ詳細で、grep のように自由文言のサーチができるようにしたい。」

```text
探す先     本文 ＋ 話した相手 ＋ 場所（⚠ 「どこで聞いたか」でも探せる）
区切り     スペースは**すべて含む（AND）**（★grep をパイプでつなぐつもりで）
⚠ しない   正規表現（★打ち間違いで 0 件になるより、部分一致のほうが素直）
⚠ 変えない 並び（★新しい順の 1 本 / RX3-0118）
```
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from dq3.ui import memo_detail as MD                          # noqa: E402
from test_dq3_memo_views import FakeService, FakeVM, _qt      # noqa: E402

from dq3.knowledge.memos import Memo                          # noqa: E402

#: ★探す材料（⚠ 本文・相手・場所がばらばらに当たるように作る）
MEMOS = [
    Memo(order=1, text="商「やくそうは アリアハンで 買える」", map_id=70, npc_id=1,
         source="npc_talk", speaker="商"),
    Memo(order=2, text="兵「オーブは ほこらに ある」", map_id=70, npc_id=2,
         source="npc_talk", speaker="兵"),
    Memo(order=3, text="＊「たびの とびらを みつけた」", map_id=12, source="conversation"),
]


def _rows(maps=None):
    return MD.timeline_rows(FakeService(), FakeVM(MEMOS), maps)


# --- ★絞り込みの中身（⚠ Qt を使わない） -------------------------------------

def test_本文で絞れる():
    rows = _rows()
    got = MD.filter_rows(rows, "オーブ")
    assert [r["order"] for r in got] == [2], [r["text"] for r in got]


def test_場所でも相手でも絞れる():
    """★「どこで聞いたか」「誰から聞いたか」でも探せる（⚠ 本文だけではない）。"""
    rows = _rows()
    assert [r["order"] for r in MD.filter_rows(rows, "レーベ")] == [2, 1]
    assert [r["order"] for r in MD.filter_rows(rows, "兵")] == [2]


def test_スペース区切りはすべて含む():
    rows = _rows()
    assert [r["order"] for r in MD.filter_rows(rows, "オーブ ほこら")] == [2]
    # ⚠ 片方しか含まない語を足したら 0 件（★OR ではない）
    assert MD.filter_rows(rows, "オーブ やくそう") == []


def test_空なら全部通す():
    rows = _rows()
    for word in ("", "   ", None):
        assert len(MD.filter_rows(rows, word)) == len(rows)


def test_大文字小文字を無視する():
    rows = [{"text": "Memo ABC", "body": "", "label": "", "place": ""}]
    assert MD.filter_rows(rows, "abc") and MD.filter_rows(rows, "MEMO")


def test_並びを変えない():
    """⚠ 絞っても**新しい順のまま**（★RX3-0118 の 1 本を崩さない）。"""
    rows = _rows()
    assert [r["order"] for r in rows] == [3, 2, 1], "★素の並びは新しい順"
    # ⚠ 絞った後も**残ったものの順番はそのまま**（★並べ替えない）
    assert [r["order"] for r in MD.filter_rows(rows, "レーベ")] == [2, 1]
    assert [r["order"] for r in MD.filter_rows(rows, "")] == [3, 2, 1]


def test_探す先は決まった欄だけ():
    """⚠ 証跡（talk_id や回数）では探さない（★人が読む文字だけ）。"""
    assert MD.SEARCH_FIELDS == ("text", "body", "label", "place")
    row = {"text": "", "body": "", "label": "", "place": "", "talk_id": 715, "count": 3}
    assert not MD.matches(row, "715")


# --- ★画面（⚠ 打った言葉が効くところまで） -----------------------------------

@pytest.fixture
def dialog():
    _qt()
    dlg = MD.MemoDetailDialog(FakeVM(MEMOS), FakeService())
    yield dlg
    dlg.close()


def _shown(dlg):
    return [dlg.list.item(i).text() for i in range(dlg.list.count())]


def test_打つと絞られ_消すと戻る(dialog):
    assert len(_shown(dialog)) == 3
    dialog.search_edit.setText("オーブ")
    got = _shown(dialog)
    assert len(got) == 1 and "オーブ" in got[0], got
    dialog.search_edit.setText("")
    assert len(_shown(dialog)) == 3


def test_件数を出す(dialog):
    assert dialog.count_label.text() == "3 件"
    dialog.search_edit.setText("オーブ")
    assert dialog.count_label.text() == "1 / 3 件"


def test_0件は探したと分かる文を出す(dialog):
    """⚠ 「まだありません」と混ぜない（★条件はそのまま残す）。"""
    dialog.search_edit.setText("そんな言葉は無い")
    assert _shown(dialog) == [MD.NO_MATCH]


def test_MAPと併用できる(dialog):
    """★MAP を替えても文言は残る（⚠ 両方効く / RX3-0254 と同じ作法）。"""
    index = dialog.map_select.findData(70)
    assert index >= 0
    dialog.map_select.setCurrentIndex(index)
    dialog.search_edit.setText("やくそう")
    got = _shown(dialog)
    assert len(got) == 1 and "やくそう" in got[0], got
    # ⚠ 文言はそのまま残っている
    assert dialog.search_edit.text() == "やくそう"
    # ★別の MAP に替えると 0 件（★文言は消えない）
    dialog.map_select.setCurrentIndex(dialog.map_select.findData(12))
    assert _shown(dialog) == [MD.NO_MATCH] and dialog.search_edit.text() == "やくそう"


# ======================================================================
# ★かなを畳んで探す（RX3-0295 / 2026-09-18）
# ======================================================================
#
# ⚠⚠ DQ3 の文字表は**カタカナの「リ」を持たず、ひらがなの「り」の絵を使い回す**。
#   ★だから画面から読んだ台詞は `エりック`（⚠ 化けではない / RX3-0193）。
#
#     記録   ＊「しかし エりックってやつはむじつの つみだったらしいよ。
#     検索   エリック          ⚠⚠ 小文字にそろえるだけでは 1 件も出ない
#
# ★依頼者「save7 エリック（NPC名前つき）のセリフが保存されない」→ ★保存されていた。
#   ⚠ 検索で見つけられなかっただけだった。

ERIC = {"text": "囚「しかし エりックってやつはむじつの つみだったらしいよ。」",
        "body": "", "label": "囚人", "place": "サマンオサ"}


def test_カタカナで打ってもひらがなの綴りに当たる():
    assert MD.matches(ERIC, "エリック"), "⚠⚠ これが直したかったこと"


def test_ひらがなで打っても当たる():
    assert MD.matches(ERIC, "えりっく")


def test_記録どおりに打っても当たる():
    """⚠ 直したせいで**元の綴り**が外れていないこと。"""
    assert MD.matches(ERIC, "エりック")


def test_どの打ち方でも同じ結果():
    rows = [ERIC, {"text": "＊「こんにちは。", "body": "", "label": "", "place": ""}]
    got = [MD.filter_rows(rows, w) for w in ("エリック", "えりっく", "エりック")]
    assert got[0] == got[1] == got[2] == [ERIC]


def test_関係ない語は当たらない():
    """⚠ 畳みすぎて何でも当たる、になっていないこと。"""
    assert not MD.matches(ERIC, "エルシト")


def test_飾りだけの語では絞り込みが消えない():
    """⚠⚠ `「」` は畳むと**空**になる。★空文字はどの行にも含まれる。

    ⚠ そのまま条件に入れると、★どの行も通ってしまい絞り込みが効かない。

    ⚠ ここで `＊` を使わないのは、★`concepts.fold` が NFKC を先に掛けるため
      `＊`（全角）が `*` に化けて DROP から外れているためです（→ RX3-0296）。
    """
    rows = [ERIC, {"text": "＊「こんにちは。", "body": "", "label": "", "place": ""}]
    assert MD.filter_rows(rows, "「」 エリック") == [ERIC]
    # ⚠ 飾りだけなら「全部通す」（★条件が無いのと同じ）
    assert MD.filter_rows(rows, "「」") == rows


def test_区切りは畳む前に切る():
    """⚠ `fold` はスペースを落とすので、★先に語へ切らないと 1 語になってしまう。"""
    assert MD.matches(ERIC, "エリック むじつ")
    assert not MD.matches(ERIC, "エリック そんな言葉は無い")


def test_検索に実行ボタンを置かない():
    """⚠ 依頼者の作法（★お店の検索と同じ / 入力のたびに絞る）。

    ⚠⚠ 2026-09-20（RX3-0310）に書き直しました。★以前は
    「`memo_detail.py` に `QPushButton` の字が 1 つも無い」で見ていましたが、
    ⚠ 「行ってみる？に追加」を足した時点で赤くなりました。
    ★この検査が守りたいのは **検索欄に実行ボタンが無いこと**なので、
    ⚠ 字面ではなく**検索の行の中身**で見ます。
    """
    src = (ROOT / "dq3" / "ui" / "memo_detail.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    assert any("textChanged" in ln for ln in code), "⚠ 打つそばから絞っていない"


def test_検索の行にボタンを置かない(dialog):
    """⚠ 上の検査の相棒（★本物の窓で、検索を走らせるボタンが無いことを見る）。"""
    from PySide6.QtWidgets import QPushButton

    texts = [b.text() for b in dialog.findChildren(QPushButton)]
    assert not any(t in ("検索", "実行", "さがす") for t in texts), texts
    # ★検索欄と同じ並びに、⚠ ボタンが 1 つも無いこと
    root = dialog.search_edit.parentWidget().layout()
    found = []
    for i in range(root.count()):
        sub = root.itemAt(i).layout()
        if sub is None or sub.indexOf(dialog.search_edit) < 0:
            continue
        for j in range(sub.count()):
            w = sub.itemAt(j).widget()
            if isinstance(w, QPushButton):
                found.append(w.text())
    assert found == [], "⚠⚠ 検索の行にボタンを置いた: %s" % found

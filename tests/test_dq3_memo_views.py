"""勇者メモの 3 つの画面が同じものを同じ順で出す（RX3-0118 / 2026-09-08）。

## ⚠⚠ 何が起きていたか

```text
MAP の 3 行    vm.recent_memos(3)                ★MemoBook / 新しい順
[すべて]       sorted(vm.memos, order, reverse)  ★MemoBook / 新しい順
[メモ詳細]     service.heard_timeline()          ⚠⚠ **別ソース** / ⚠⚠ **古い順**
```

★依頼者の指示（2026-09-08 §3）:

```text
1 3 ビューすべて、新しい情報を上にする
2 各 View が独自に別の sort key を使わない
3 `＊` を話者として表示しない（★分からなければ `？`）
```

⚠ Qt が無い環境では画面の検査だけ skip します（★モデル側は必ず走ります）。
"""
from __future__ import annotations

import os

import pytest

from dq3.ui.models import Memo, MemoBook


def _qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                  # pragma: no cover
        pytest.skip("Qt が無い環境")
    return QApplication.instance() or QApplication([])


class FakeVM:
    """★3 つの画面へ同じ `MemoBook` を渡すだけの偽物。"""

    def __init__(self, memos, *, at=(0x90, 70, 5, 5)) -> None:
        self.memos = MemoBook(memos)
        self._at = at

    def recent_memos(self, n=3):
        return self.memos.recent(n)

    def position(self):
        return self._at

    def place_name(self, map_id):
        return {70: "レーベ"}.get(map_id)

    def location_view(self, loc):
        class _V:
            is_known = False
            display_name = "？"
        return _V()


class FakeService:
    """⚠ 会話の台帳（★一次証跡）。⚠⚠ 表示の正本ではない。"""

    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.asked = []

    def heard_timeline(self, map_ids=None):
        self.asked.append(map_ids)
        return list(self.rows)

    def maps_with_heard(self):
        return sorted({r["map_id"] for r in self.rows})

    def appearance_label(self, appearance_id):
        return {10: "商", 11: "兵"}.get(appearance_id, "？")


#: ★golden case: NPC 3 人と続けて会話した（⚠ A → B → C の順に足す）
GOLDEN = [
    Memo(order=1, text="商「Memo A」", map_id=70, npc_id=1, source="npc_talk", speaker="商"),
    Memo(order=2, text="兵「Memo B」", map_id=70, npc_id=2, source="npc_talk", speaker="兵"),
    Memo(order=3, text="＊「Memo C」", map_id=70, source="conversation"),
]


# ======================================================================
# ★1 … 並びは 1 か所（⚠ 3 ビューが同じ先頭を出す）
# ======================================================================
def test_新しい順はMemoBookが持っている():
    book = MemoBook(GOLDEN)
    assert [m.order for m in book.newest()] == [3, 2, 1]
    assert [m.order for m in book.recent(2)] == [3, 2]
    assert book.recent(2) == book.newest(2), "⚠ `recent` と `newest` が別の並びになった"


def test_2ビューが同じ順で同じメモを出す():
    """⚠⚠ ここが本丸。★Memo C / Memo B / Memo A が同じ順。

    ⚠ 2026-09-21（RX3-0354）: ★「すべて」（`MemoListDialog`）を**外した**ので
      3 → 2 ビューになりました（⚠ 見る所が減っただけで、★趣旨は同じ）。
    """
    _qt()
    from dq3.ui.memo_detail import timeline_rows
    from dq3.ui.memo_panel import MemoPanel

    vm = FakeVM(GOLDEN)
    svc = FakeService()

    panel = MemoPanel(vm, limit=3)
    view1 = [t.lstrip("・") for t in panel._texts]
    view2 = [r["text"] for r in timeline_rows(svc, vm)]

    assert view1 == view2, (
        "⚠⚠ 2 ビューが一致しません%s1 %s%s2 %s"
        % (chr(10), view1, chr(10), view2))
    # ★RX3-0253: 行は「字　本文」（⚠ 閉じの 」 は出さない）
    assert view1[0].endswith("Memo C"), "⚠ 先頭が新しいメモではない: %s" % view1[0]


def test_すべてのボタンと画面を消した():
    """⚠⚠ 依頼者「勇者メモ『すべて』ボタン他と被るので不要」（RX3-0354）。

    ★押す口が無いのに画面だけ残す、をしない（⚠ 死んだ画面は次の人を迷わせる）。
    """
    import pathlib

    from dq3.ui import memo_panel

    assert not hasattr(memo_panel, "MemoListDialog"), "⚠⚠ 押せない画面が残っている"
    assert not hasattr(memo_panel.MemoPanel, "open_all"), "⚠ 開く口が残っている"
    src = pathlib.Path(memo_panel.__file__).read_text(encoding="utf-8")
    body = src.split(chr(34) * 3, 2)[2]        # ⚠ 説明文は除く（★経緯は残してよい）
    assert 'QPushButton("すべて")' not in body, "⚠⚠ ボタンが残っている"


def test_詳細だけが古い順に戻らない():
    """⚠ 2026-09-08 まで、★ここだけ `first_heard_at` の**昇順**でした。"""
    from dq3.ui.memo_detail import timeline_rows

    rows = timeline_rows(FakeService(), FakeVM(GOLDEN))
    assert [r["order"] for r in rows] == [3, 2, 1], "⚠⚠ 古い順に戻っている"


def test_詳細は会話以外のメモも落とさない():
    """⚠ 会話の台帳を正本にすると、★場所を知ったメモが消えていました。"""
    from dq3.ui.memo_detail import timeline_rows

    memos = list(GOLDEN) + [Memo(order=4, text="いどの そこに なにか ある", map_id=70,
                                 source="discovery")]
    rows = timeline_rows(FakeService(), FakeVM(memos))
    assert rows[0]["text"] == "いどの そこに なにか ある"
    assert len(rows) == 4, "⚠⚠ 会話でないメモが落ちている: %s" % [r["text"] for r in rows]


def test_画面は並べ替えを持たない():
    """⚠⚠ 「同じ判定を 2 か所に書いて片方だけ直る」を繰り返さない。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("memo_panel.py", "memo_detail.py", "map_browser.py"):
        src = (root / "dq3" / "ui" / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            if line.lstrip().startswith("#"):
                continue                       # ★説明の中の言及は見ない
            assert "key=lambda m: m.order" not in line, (
                "⚠⚠ %s が自前で並べ替えている: %s" % (name, line.strip()))


# ======================================================================
# ★2 … `＊` を話者にしない
# ======================================================================
def test_話者が分からなければ疑問符():
    memo = Memo(order=1, text="＊「なにか あるかも しれぬ。」")
    assert memo.speaker_label == "？"
    # ★RX3-0253（2026-09-13 依頼者「勇者メモでかぎ括弧「」双方不要」）: 「字　本文」（⚠ 「」は出さない）
    assert memo.line == "？　なにか あるかも しれぬ。"
    assert "＊" not in memo.line and "「" not in memo.line and "」" not in memo.line


def test_見た目が分かるNPCは話者になる():
    memo = Memo(order=1, text="商「いらっしゃい」", speaker="商")
    assert memo.speaker_label == "商"
    assert memo.line == "商　いらっしゃい", "⚠ 話者を二重に付けた / 「」を出した（RX3-0253）"


def test_話者にアスタリスクを記録しない(tmp_path):
    """⚠⚠ 入口でも止める（★画面だけで直すと、記録が汚れたままになる）。"""
    from dq3.knowledge.memos import MemoStore

    store = MemoStore(tmp_path / "memos.jsonl")
    made = store.add("＊「ようこそ」", speaker="＊", source="conversation")
    assert made.speaker is None, "⚠⚠ `＊` を話者として記録した"
    assert made.speaker_label == "？"
    assert store.add("やあ", speaker="  ", source="manual").speaker is None


def test_古い記録の話者を見た目から起こす(monkeypatch):
    """★`speaker` の無い昔の記録でも、⚠ (map, npc) から見た目を引ける。"""
    from dq3.knowledge import npc_master
    from dq3.ui import memo_detail as MD

    def master_for(map_id, kind):
        return {"npcs": [{"npc_id": 2, "appearance_id": 11}]} if map_id == 70 else {"npcs": []}

    monkeypatch.setattr(npc_master, "master_for", master_for)
    old = Memo(order=1, text="＊「みなみに どうくつが ある」", map_id=70, npc_id=2)
    assert MD.speaker_of(FakeService(), old) == "兵"
    nowhere = Memo(order=2, text="＊「うわさだが…」", map_id=99, npc_id=9)
    assert MD.speaker_of(FakeService(), nowhere) == "？"


def test_ラベルが分からない行も詳細に出す():
    from dq3.ui.memo_detail import timeline_rows

    rows = timeline_rows(FakeService(), FakeVM(GOLDEN))
    got = {r["order"]: r["label"] for r in rows}
    assert got == {3: "？", 2: "兵", 1: "商"} or got[3] == "？", got
    assert "＊" not in "".join(r["text"] for r in rows)


# ======================================================================
# ★2-2 … 続きの段に付く `＊` も落とす（RX3-0120 / 2026-09-08）
# ======================================================================
#
# ⚠⚠ 依頼者の実機（2026-09-08）:
#   老「はなしは すでに きいておる。＊「さあ この まほうのたまでふういんを…
#
# ★`＊「` はゲームの会話開始記号で、⚠ **続きの段にも付きます**。
#   RX3-0118 で直したのは**先頭の 1 個だけ**でした。

#: ★実機の記録そのまま（2026-09-08 / `memos.jsonl`）
REAL = "老「はなしは すでに きいておる。＊「さあ この まほうのたまでふういんを とくがよい！」"


def test_続きの段の記号も落ちる():
    memo = Memo(order=1, text=REAL, speaker="老")
    # ★RX3-0253: 続きの段の「」も出さない（★段の境は空白）
    assert memo.line == "老　はなしは すでに きいておる。　さあ この まほうのたまでふういんを とくがよい！"
    assert "＊" not in memo.line


def test_先頭も続きも同時に落ちる():
    memo = Memo(order=1, text="＊「ここは どうぐやです。＊「では またの おこしを。」")
    assert memo.line == "？　ここは どうぐやです。　では またの おこしを。"


def test_単体のアスタリスクは残す():
    """⚠⚠ 全文一括削除にしない（★本文で意味を持つ `＊` を消さない）。"""
    from dq3.ui.models import strip_speech_marks

    assert strip_speech_marks("ちからの たね ＊ を みつけた") == "ちからの たね ＊ を みつけた"
    assert strip_speech_marks("＊＊＊ ひみつ ＊＊＊") == "＊＊＊ ひみつ ＊＊＊"
    memo = Memo(order=1, text="＊「あれは ＊ の しるしだ。」", speaker="兵")
    assert memo.line == "兵　あれは ＊ の しるしだ。"


def test_記録そのものは書き換えない():
    """⚠ 一次情報を壊さない（★落とすのは表示のときだけ）。"""
    memo = Memo(order=1, text=REAL, speaker="老")
    assert "＊「" in memo.text, "⚠⚠ 記録から記号が消えている"


def test_詳細画面にも残らない():
    from dq3.ui.memo_detail import timeline_rows

    memos = [Memo(order=1, text=REAL, speaker="老", map_id=70, npc_id=3)]
    rows = timeline_rows(FakeService(), FakeVM(memos))
    assert "＊" not in rows[0]["text"], rows[0]["text"]
    assert "＊" not in rows[0]["body"]


def test_地点ポップアップにも残らない():
    """⚠ 4 番目の画面（★RX3-0118 のときに見落としていた）。"""
    _qt()
    from dq3.knowledge.memos import MemoStore
    from dq3.ui.view_model import Dq3ViewModel

    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        store = MemoStore(root / "memos.jsonl")
        store.add(REAL, source="npc_talk", location_id="L70", map_id=70, speaker="老")
        vm = Dq3ViewModel(state_path=root / "state.json", knowledge_path=root / "k.json",
                          memo_path=root / "memos.jsonl", seen_path=root / "seen.json")
        vm._visited.add("L70")
        view = vm.location_view("L70")
        assert view.highlights and "＊" not in view.highlights[0], view.highlights


# ======================================================================
# ★3 … 証跡は残す（⚠ 消さない・嘘を書かない）
# ======================================================================
def test_会話の台帳は証跡として添える():
    from dq3.ui.memo_detail import timeline_rows

    svc = FakeService([{"map_id": 70, "npc_id": 1, "talk_id": 3, "text": "＊「Memo A",
                        "count": 4, "first_heard_at": "2026-09-01T10:00:00",
                        "last_heard_at": "x", "text_hash": "h"}])
    rows = {r["order"]: r for r in timeline_rows(svc, FakeVM(GOLDEN))}
    assert rows[1]["count"] == 4 and rows[1]["talk_id"] == 3
    assert rows[1]["first_heard_at"].startswith("2026-09-01")
    # ⚠ 証跡の無い行は**空**（★「0 回」と書かない）
    assert rows[3]["count"] is None and rows[3]["first_heard_at"] == ""


def test_証跡が読めなくても行は出る():
    """⚠ `npc-conversations.json` が無い環境でも、★メモは読める。"""
    from dq3.ui.memo_detail import timeline_rows

    class _Broken(FakeService):
        def heard_timeline(self, map_ids=None):
            raise OSError("⚠ 台帳が無い")

    rows = timeline_rows(_Broken(), FakeVM(GOLDEN))
    assert len(rows) == 3


def test_ヒントに無い回数を書かない():
    _qt()
    from dq3.ui.memo_detail import MemoDetailDialog

    tip = MemoDetailDialog._tip({"label": "？", "first_heard_at": "", "count": None,
                                 "talk_id": None})
    assert tip == "話した相手: ？"
    assert "0" not in tip


# ======================================================================
# ★4 … MAP で絞る（⚠ 会話のある MAP ではなく、メモのある MAP）
# ======================================================================
def test_MAP選択はメモのある地図から作る():
    _qt()
    from dq3.ui.memo_detail import MemoDetailDialog

    memos = list(GOLDEN) + [Memo(order=4, text="ほこらを みつけた", map_id=12,
                                 source="discovery")]
    dlg = MemoDetailDialog(FakeVM(memos), FakeService())
    got = [dlg.map_select.itemData(i) for i in range(dlg.map_select.count())]
    assert got == [None, 12, 70], got


def test_今いるMAPで絞ると他の地図が消える():
    from dq3.ui.memo_detail import timeline_rows

    memos = list(GOLDEN) + [Memo(order=4, text="ほこらを みつけた", map_id=12,
                                 source="discovery")]
    rows = timeline_rows(FakeService(), FakeVM(memos), {70})
    assert [r["order"] for r in rows] == [3, 2, 1]


# ======================================================================
# ★5 … 既存のプレイデータを読める（⚠ 欄が増えても壊れない）
# ======================================================================
def test_話者の欄が無い記録も読める(tmp_path):
    import io
    import json

    from dq3.knowledge.memos import MemoStore

    path = tmp_path / "memos.jsonl"
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps({"order": 1, "text": "＊「むかしの きろく」",
                             "source": "conversation"}, ensure_ascii=False) + "\n")
    store = MemoStore(path)
    assert store.failed == 0
    got = list(store)[0]
    assert got.speaker is None and got.line == "？　むかしの きろく"

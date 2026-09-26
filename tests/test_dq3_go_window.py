"""勇者メモ →「行ってみる？」の画面（RX3-0310 / 2026-09-20）。

依頼者 §3 / §4 / §8 / §9:

```text
勇者メモ本文をマウスでテキスト選択できるようにする
選択状態で [ 行ってみる？に追加 ]
一覧 → [行った] で一覧から消える（⚠ 内部は DONE。物理削除しない）
出典から元の勇者メモへ戻れる
```

⚠⚠ 画面外の Qt は寸法が実機と違う（RX3-0258）→ ★ここは**数と名前と中身**で見ます。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import go_list as GL                     # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _Memo(order, text, map_id=1, npc_id="3"):
    """★勇者メモ 1 件（⚠ 本物の `Memo` を使う。★見本を自作すると欄が食い違う）。"""
    from dq3.ui.models import Memo

    return Memo(order=order, text=text, map_id=map_id, npc_id=npc_id,
                location_id="L%d" % map_id, source="conversation", speaker="商")


class _Memos:
    def __init__(self, rows):
        self._rows = rows

    def newest(self):
        return list(self._rows)

    def maps(self):
        return sorted({m.map_id for m in self._rows})


class _Book:
    locations: dict = {}

    @staticmethod
    def location_id_of(map_id):
        return "L%d" % int(map_id)


class _VM:
    """★`Dq3ViewModel` の口だけを持つ見本（⚠ 本物の台帳には書かない）。

    ★「行ってみる？」の出し入れは**本物の関数を借りて**きます（⚠ 別の実装を書かない）。
    """

    from dq3.ui.view_model import Dq3ViewModel as _Real

    go_list = _Real.go_list
    add_go_item = _Real.add_go_item
    go_items = _Real.go_items
    complete_go_item = _Real.complete_go_item
    reopen_go_item = _Real.reopen_go_item
    _complete_go_on_arrival = _Real._complete_go_on_arrival
    dismiss_reachable = _Real.dismiss_reachable
    edit_go_item = _Real.edit_go_item

    def __init__(self, tmp_path, rows=()):
        self._go_list_path = tmp_path / "go-list.json"
        self._memos = _Memos(rows)
        self.location_book = _Book()

    @property
    def memos(self):
        return self._memos

    def position(self):
        return (1, 1, 0, 0)


class _Service:
    """★`TownService` の代わり（⚠ 証跡は返さない）。"""

    @staticmethod
    def heard_rows(*_a, **_k):
        return []


def _detail(qapp, vm, confirm=False):
    """★メモ詳細の窓。⚠ 既定では確認の窓を出さない（★`exec` は画面外でも待つ）。"""
    from dq3.ui.memo_detail import MemoDetailDialog

    got = MemoDetailDialog(vm, _Service())
    got.CONFIRM = confirm
    return got


ROWS = (_Memo(703, "東へ行くと洞窟がある。その先に小さな村があるらしい。"),
        _Memo(704, "岬の洞窟には まものが いる。", map_id=45))


# --- ★メモ詳細から足す ------------------------------------------------------

def _select(dialog, want):
    """★本文の欄で `want` の所だけをなぞる（⚠ 実際の操作と同じ道を通す）。"""
    from PySide6.QtGui import QTextCursor

    text = dialog.body.toPlainText()
    start = text.index(want)
    cur = dialog.body.textCursor()
    cur.setPosition(start)
    cur.setPosition(start + len(want), QTextCursor.MoveMode.KeepAnchor)
    dialog.body.setTextCursor(cur)


def test_本文の欄は文字を選べる(qapp, tmp_path):
    """★依頼者「勇者メモ本文をマウスでテキスト選択できるようにする」。

    ⚠⚠ 2026-09-20（RX3-0319）依頼者から**2 度目の報告**
    「テキスト範囲選択みたいなのができない」。
    ★`QLabel` から**読み取り専用の `QTextEdit`** に替えました
    （⚠ 文字カーソルが出て、★なぞれる所だと分かる）。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTextEdit

    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    assert isinstance(dialog.body, QTextEdit), "⚠⚠ 選びにくい部品に戻っている"
    assert dialog.body.isReadOnly(), "⚠ 記録を書き換えられてはいけない"
    got = dialog.body.textInteractionFlags()
    assert got & Qt.TextInteractionFlag.TextSelectableByMouse, "⚠⚠ 選べない"


def test_本文は省略しないで出す(qapp, tmp_path):
    """⚠⚠ MAP 下の勇者メモは「…」で省略される（★そこから選ぶと切れた字が入る）。"""
    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    dialog.list.setCurrentRow(0)
    assert ROWS[0].text in dialog.body.toPlainText()
    assert "…" not in dialog.body.toPlainText()


def test_選んでいなければ1件まるごと足す(qapp, tmp_path):
    vm = _VM(tmp_path, ROWS)
    dialog = _detail(qapp, vm)
    dialog.list.setCurrentRow(0)
    got = dialog.add_to_go_list()
    assert got is not None and got.display_text == ROWS[0].text
    assert [x.display_text for x in vm.go_items()] == [ROWS[0].text]


def test_選んだ部分だけを足す(qapp, tmp_path):
    """★依頼者 §4:「その先に小さな村があるらしい。」だけを選んで追加できること。"""
    vm = _VM(tmp_path, ROWS)
    dialog = _detail(qapp, vm)
    dialog.list.setCurrentRow(0)
    want = "その先に小さな村があるらしい。"
    _select(dialog, want)
    assert dialog.selected_text() == want, "⚠⚠ なぞった所を拾えていない"
    assert dialog.go_text() == want
    got = dialog.add_to_go_list()
    assert got.display_text == want


def test_足しても元の勇者メモは変わらない(qapp, tmp_path):
    """⚠⚠ 依頼者 §2-1「元の勇者メモは削除・変更しない」。"""
    vm = _VM(tmp_path, ROWS)
    before = [(m.order, m.text) for m in vm.memos.newest()]
    dialog = _detail(qapp, vm)
    dialog.list.setCurrentRow(0)
    dialog.add_to_go_list()
    assert [(m.order, m.text) for m in vm.memos.newest()] == before


def test_出典を持つ(qapp, tmp_path):
    vm = _VM(tmp_path, ROWS)
    dialog = _detail(qapp, vm)
    dialog.list.setCurrentRow(1)
    got = dialog.add_to_go_list()
    assert got.source_memo_id == 704
    assert got.source_location_id == "L45", "⚠ 聞いた場所を落とした"


def test_何も選んでいなければ足さない(qapp, tmp_path):
    vm = _VM(tmp_path, [])
    dialog = _detail(qapp, vm)
    assert dialog.current_row() is None, "⚠ 「まだありません」の行を掴んでいる"
    assert dialog.add_to_go_list() is None
    assert vm.go_items() == []


# --- ★一覧 -----------------------------------------------------------------

def _window(qapp, vm, parent=None, auto_rows=()):
    from dq3.ui.go_window import Dq3GoWindow

    return Dq3GoWindow(vm, parent=parent, auto_rows=auto_rows)


def _rows(win):
    """★選べる行（⚠ 見出し・案内は除く / RX3-0313 で節ができた）。"""
    from PySide6.QtCore import Qt

    got = []
    for i in range(win.list.count()):
        item = win.list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) is not None:
            got.append((i, item))
    return got


def _pick(win, n=0) -> bool:
    """★n 番目の**選べる**行を選ぶ。"""
    rows = _rows(win)
    if n >= len(rows):
        return False
    win.list.setCurrentRow(rows[n][0])
    return True


class _Auto:
    """★自動で出た 1 行（`reachable.Reachable` と同じ口だけ）。"""

    def __init__(self, name, location_id=None, why_text="話に出た"):
        self.name, self.location_id, self.why_text = name, location_id, why_text


def test_一覧に出る(qapp, tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる", source_memo_id=1, source_location_id="L1")
    vm.add_go_item("その先に小さな村があるらしい", source_memo_id=2, source_location_id="L2")
    win = _window(qapp, vm)
    rows = _rows(win)
    assert len(rows) == 2
    assert "東にある洞窟へ行ってみる" in rows[0][1].text()
    assert "勇者メモ #1" in rows[0][1].text(), "⚠ 出典が出ていない"


def test_行ったで一覧から消えるが記録は残る(qapp, tmp_path):
    """★依頼者 §11「行ったので消える。内部的には削除ではなく DONE 化」。"""
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm)
    assert _pick(win)
    assert win.complete_current() is True
    assert _rows(win) == [] and "まだありません" in win.list.item(0).text()
    win.show_done.setChecked(True)
    assert len(_rows(win)) == 1 and "東にある洞窟" in _rows(win)[0][1].text()
    assert vm.go_list.items, "⚠⚠ 物理削除した"


def test_済んだ分は戻せる(qapp, tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm)
    assert _pick(win)
    win.complete_current()
    win.show_done.setChecked(True)
    assert win.done_button.text() == "戻す"
    assert _pick(win)
    assert win.complete_current() is True
    win.show_done.setChecked(False)
    assert len(_rows(win)) == 1 and "東にある洞窟" in _rows(win)[0][1].text()


# ======================================================================
# ★★ 四角を押して消せる（RX3-0353 / 2026-09-21）
#
#   ⚠⚠ 依頼者「行ってみる？の四角をチェックしても消せない」。
#     ★以前の □ / ☑ は**ただの文字**で、押しても何も起きませんでした。
# ======================================================================
def _check(item, on: bool) -> None:
    from PySide6.QtCore import Qt

    item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def _is_checkable(item) -> bool:
    """★本当に四角が出ているか。

    ⚠⚠ `flags()` だけでは見分けられません（★Qt の既定の旗に `ItemIsUserCheckable` が
      **最初から入っています** / 2026-09-21 に踏んだ）。
    → ★四角は `CheckStateRole` を置いたときだけ出ます。⚠ **両方**を見ます。
    """
    from PySide6.QtCore import Qt

    has_flag = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    has_state = item.data(Qt.ItemDataRole.CheckStateRole) is not None
    return has_flag and has_state


def test_四角は本物のチェックだ(qapp, tmp_path):
    """⚠⚠ ここが依頼者の症状（★文字の □ は押せない）。"""
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm)
    rows = _rows(win)
    assert len(rows) == 1
    assert _is_checkable(rows[0][1]), "⚠⚠ 四角が押せない（★ただの文字のまま）"
    assert "□" not in rows[0][1].text() and "☑" not in rows[0][1].text(), (
        "⚠ 文字の四角が残っている（★本物と 2 つ並ぶ）: %s" % rows[0][1].text())


def test_四角を押すと一覧から消える(qapp, tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm)
    _check(_rows(win)[0][1], True)
    assert _rows(win) == [], "⚠⚠ 四角を押しても消えない（★依頼者の症状）"
    assert vm.go_list.items, "⚠ 物理削除した"
    win.show_done.setChecked(True)
    assert len(_rows(win)) == 1, "⚠ 済んだ分に移っていない"


def test_済んだ分の四角を外すと戻る(qapp, tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm)
    _check(_rows(win)[0][1], True)
    win.show_done.setChecked(True)
    row = _rows(win)[0][1]
    assert row.checkState().name == "Checked", "⚠ 済んだ分が ☑ になっていない"
    _check(row, False)
    win.show_done.setChecked(False)
    assert len(_rows(win)) == 1, "⚠⚠ 四角を外しても戻らない"


def test_一覧を作り直しても勝手に消えない(qapp, tmp_path):
    """⚠⚠ `refresh()` 中の合図で消し込まない（★2 件目を作った瞬間に 1 件目が消える、を防ぐ）。"""
    vm = _VM(tmp_path)
    vm.add_go_item("ひとつめ")
    vm.add_go_item("ふたつめ")
    win = _window(qapp, vm)
    for _ in range(3):
        win.refresh()
    assert len(_rows(win)) == 2, "⚠⚠ 作り直しただけで消えた: %d 件" % len(_rows(win))
    win.show_done.setChecked(True)
    win.show_done.setChecked(False)
    assert len(_rows(win)) == 2, "⚠ 表示を切り替えただけで消えた"


def test_消せない行には四角を出さない(qapp, tmp_path):
    """⚠ 場所の id が無い自動の行は消せません（★押せる四角を出すと嘘になる）。"""
    win = _window(qapp, _VM(tmp_path), auto_rows=[_Auto("どこかの村", location_id=None)])
    rows = _rows(win)
    assert len(rows) == 1
    assert not _is_checkable(rows[0][1]), "⚠⚠ 消せないのに押せる四角を出した"


def test_空なら案内を出す(qapp, tmp_path):
    win = _window(qapp, _VM(tmp_path))
    from dq3.ui.go_window import EMPTY

    assert win.list.count() == 1 and win.list.item(0).text() == EMPTY
    assert _rows(win) == []
    assert not win.done_button.isEnabled(), "⚠ 何も無いのに押せる"


def test_足したらその場で書き出す(tmp_path):
    """⚠⚠ 足しただけで落ちても消えない（★「終える」まで保存を待たない）。

    ⚠ 壊す実験で分かった穴: 下の検査は `complete_go_item` も保存するので、
    ★`add_go_item` の保存を外しても緑のままだった。
    """
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    assert [x.display_text for x in _VM(tmp_path).go_items()] == ["東にある洞窟へ行ってみる"]


def test_再起動しても残る(qapp, tmp_path):
    """★依頼者の確認「再起動後も ACTIVE / DONE 状態が保持される」。"""
    vm = _VM(tmp_path)
    a = vm.add_go_item("東にある洞窟へ行ってみる")
    b = vm.add_go_item("その先に小さな村があるらしい")
    vm.complete_go_item(b.id)

    again = _VM(tmp_path)                      # ★同じファイルを読み直す
    assert [x.id for x in again.go_items()] == [a.id]
    assert [x.id for x in again.go_items(done=True)] == [b.id]


def test_出典から元のメモへ戻れる(qapp, tmp_path):
    """★依頼者 §8「出典部分または項目をクリックすると、元の勇者メモを表示できる」。"""
    vm = _VM(tmp_path, ROWS)
    detail = _detail(qapp, vm)
    detail.list.setCurrentRow(1)
    detail.add_to_go_list()
    detail.list.setCurrentRow(0)               # ★いったん別の行へ
    win = _window(qapp, vm, parent=detail)
    assert _pick(win)
    assert win.open_source_memo() is detail
    assert detail.current_row()["order"] == 704, "⚠⚠ 元のメモを選び直していない"


def test_絞り込みで隠れていても元のメモへ戻れる(qapp, tmp_path):
    """⚠ 検索で絞っていると、★その行は一覧に居ない（→ 条件を外して探し直す）。"""
    vm = _VM(tmp_path, ROWS)
    detail = _detail(qapp, vm)
    detail.list.setCurrentRow(1)
    detail.add_to_go_list()
    detail.search_edit.setText("まったく当たらない語")
    assert detail.list.count() == 1 and detail.current_row() is None
    win = _window(qapp, vm, parent=detail)
    assert _pick(win)
    win.open_source_memo()
    assert detail.current_row()["order"] == 704
    assert detail.search_edit.text() == "", "⚠ 絞りを外していない"


# --- ★着いたら終わる ---------------------------------------------------------

def test_着いたら行き先の決まった分が終わる(tmp_path):
    vm = _VM(tmp_path)
    got = vm.add_go_item("岬の洞窟へ行ってみる", target_location_id="L45")
    assert [x.id for x in vm._complete_go_on_arrival("L45")] == [got.id]
    assert vm.go_items() == []


def test_関係ない場所に着いても終わらない(tmp_path):
    vm = _VM(tmp_path)
    got = vm.add_go_item("岬の洞窟へ行ってみる", target_location_id="L45")
    assert vm._complete_go_on_arrival("L9") == []
    assert [x.id for x in vm.go_items()] == [got.id]


def test_着いて終えた分も保存される(tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("岬の洞窟へ行ってみる", target_location_id="L45")
    vm._complete_go_on_arrival("L45")
    assert [x.display_text for x in _VM(tmp_path).go_items(done=True)] == ["岬の洞窟へ行ってみる"]


# --- ⚠ 既にある「行ってみる？」とは別物 ---------------------------------------

def test_自動で出る行とは別の箱(qapp, tmp_path):
    """⚠⚠ `reachable.collect`（自動 / 保存しない）の濾し器には触っていない。"""
    from dq3.knowledge import reachable as R

    assert not hasattr(R, "GoList") and not hasattr(R, "complete")
    assert GL.GoList(tmp_path / "x.json").items == {}


def test_source_line_は分からない欄を書かない():
    from dq3.ui.go_window import source_line

    bare = GL.GoItem(id="go0001", display_text="東の方に町があるらしい")
    assert source_line(bare) == "", "⚠ 分からない出典を作文した"
    full = GL.GoItem(id="go0002", display_text="x", source_memo_id=7,
                     source_location_id="L9")
    assert source_line(full, place_of=lambda k: "レーベ") == "レーベ・勇者メモ #7"
    assert source_line(full) == "L9・勇者メモ #7", "⚠ 名前が引けなければ id のまま"


# --- ★足す前の簡易確認（依頼者 §4）-------------------------------------------


def test_確認でキャンセルすると足さない(qapp, tmp_path, monkeypatch):
    """★依頼者 §4「[追加] [キャンセル] 程度の簡易確認でよい」。"""
    vm = _VM(tmp_path, ROWS)
    dialog = _detail(qapp, vm, confirm=True)
    dialog.list.setCurrentRow(0)
    seen = []
    monkeypatch.setattr(type(dialog), "_confirm_add",
                        lambda self, text: seen.append(text) or False)
    assert dialog.add_to_go_list() is None
    assert vm.go_items() == [], "⚠⚠ やめたのに足した"
    assert seen == [ROWS[0].text], "⚠ 確認に出す文が違う"


def test_確認で追加すると足す(qapp, tmp_path, monkeypatch):
    vm = _VM(tmp_path, ROWS)
    dialog = _detail(qapp, vm, confirm=True)
    dialog.list.setCurrentRow(0)
    monkeypatch.setattr(type(dialog), "_confirm_add", lambda self, text: True)
    assert dialog.add_to_go_list() is not None
    assert [x.display_text for x in vm.go_items()] == [ROWS[0].text]


def test_確認の窓は大きな編集画面ではない(qapp, tmp_path):
    """⚠ 依頼者 §4「登録時に大きな編集ダイアログは表示しない」。"""
    import inspect

    from dq3.ui.memo_detail import MemoDetailDialog

    src = inspect.getsource(MemoDetailDialog._confirm_add)
    assert "QMessageBox" in src
    assert "QLineEdit" not in src and "QTextEdit" not in src, "⚠⚠ 編集欄を置いた"
    assert "追加" in src and "キャンセル" in src


def test_項目をダブルクリックで元のメモへ(qapp, tmp_path):
    """★依頼者 §8「出典部分または項目をクリックすると、元の勇者メモを表示できる」。"""
    vm = _VM(tmp_path, ROWS)
    detail = _detail(qapp, vm)
    detail.list.setCurrentRow(1)
    detail.add_to_go_list()
    detail.list.setCurrentRow(0)
    win = _window(qapp, vm, parent=detail)
    assert _pick(win)
    win.list.itemDoubleClicked.emit(win.list.currentItem())
    assert detail.current_row()["order"] == 704, "⚠⚠ クリックで戻れない"


# --- ★★ 自動で出た分の消し込み（RX3-0313 / 2026-09-20）----------------------
#
#   ⚠⚠ 依頼者「勇者会議 行ってみるで既に完了している部分は、
#     『自分で足した分』ボタンを『管理』ボタンに変えて、別画面で終了したのは消し込みたい」

AUTO = (_Auto("アリアハン", "L9"), _Auto("レーベ", "L1"), _Auto("どこかの村"))


def test_自動で出た分も一覧に出る(qapp, tmp_path):
    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm, auto_rows=AUTO)
    texts = [t.text() for _i, t in _rows(win)]
    assert len(texts) == 4, texts
    assert any("アリアハン" in t and "話に出た" in t for t in texts)


def test_節の見出しが出る(qapp, tmp_path):
    from dq3.ui.go_window import HEAD_AUTO, HEAD_MINE

    vm = _VM(tmp_path)
    vm.add_go_item("東にある洞窟へ行ってみる")
    win = _window(qapp, vm, auto_rows=AUTO)
    all_text = [win.list.item(i).text() for i in range(win.list.count())]
    assert HEAD_MINE in all_text and HEAD_AUTO in all_text


def test_見出しは選べない(qapp, tmp_path):
    """⚠ 見出しを選んで [行った] を押せてはいけない。"""
    vm = _VM(tmp_path)
    vm.add_go_item("x")
    win = _window(qapp, vm, auto_rows=AUTO)
    from PySide6.QtCore import Qt

    head = win.list.item(0)
    assert not (head.flags() & Qt.ItemFlag.ItemIsSelectable), "⚠⚠ 見出しを選べる"
    assert not (head.flags() & Qt.ItemFlag.ItemIsEnabled)
    win.list.setCurrentRow(0)                      # ★見出しの行
    assert win.current_item() is None
    assert win.complete_current() is False


def test_自動で出た分を消し込める(qapp, tmp_path):
    """★★ これが直したかったこと。"""
    vm = _VM(tmp_path)
    win = _window(qapp, vm, auto_rows=AUTO)
    assert _pick(win, 0)                            # ★アリアハン
    assert win.complete_current() is True
    left = [t.text() for _i, t in _rows(win)]
    assert not any("アリアハン" in t for t in left), left
    assert len(left) == 2, "⚠ ほかの行まで消した"
    assert vm.go_list.is_dismissed("L9")


def test_消し込んだ分は済んだ分で見える(qapp, tmp_path):
    vm = _VM(tmp_path)
    win = _window(qapp, vm, auto_rows=AUTO)
    _pick(win, 0)
    win.complete_current()
    win.show_done.setChecked(True)
    assert any("アリアハン" in t.text() for _i, t in _rows(win))


def test_消し込みを戻せる(qapp, tmp_path):
    vm = _VM(tmp_path)
    win = _window(qapp, vm, auto_rows=AUTO)
    _pick(win, 0)
    win.complete_current()
    win.show_done.setChecked(True)
    assert _pick(win, 0)
    assert win.complete_current() is True
    win.show_done.setChecked(False)
    assert any("アリアハン" in t.text() for _i, t in _rows(win))
    assert not vm.go_list.is_dismissed("L9")


def test_場所が決まっていない行は消せない(qapp, tmp_path):
    """⚠⚠ 名前しか無い行を名前で消すと、★同じ名前の別の場所まで巻き込む。"""
    from dq3.ui.go_window import NO_ID

    vm = _VM(tmp_path)
    win = _window(qapp, vm, auto_rows=(_Auto("どこかの村"),))
    assert _pick(win, 0)
    assert NO_ID in win.list.currentItem().text(), "⚠ 理由を出していない"
    assert not win.done_button.isEnabled()
    assert win.complete_current() is False


def test_自動で出た分に元のメモは無い(qapp, tmp_path):
    vm = _VM(tmp_path)
    win = _window(qapp, vm, auto_rows=AUTO)
    _pick(win, 0)
    assert not win.memo_button.isEnabled()
    assert win.open_source_memo() is None


def test_消し込みは再起動しても残る(tmp_path):
    vm = _VM(tmp_path)
    vm.dismiss_reachable("L9")
    assert _VM(tmp_path).go_list.is_dismissed("L9")


def test_消し込んでいない分だけ残す(tmp_path):
    vm = _VM(tmp_path)
    vm.dismiss_reachable("L9")
    book = vm.go_list
    assert [r.name for r in book.keep_rows(AUTO)] == ["レーベ", "どこかの村"]
    assert [r.name for r in book.dropped_rows(AUTO)] == ["アリアハン"]


def test_自分で足した分の消し込みとは別(tmp_path):
    """⚠ 台帳の DONE と、自動の消し込みを混ぜない。"""
    vm = _VM(tmp_path)
    got = vm.add_go_item("東にある洞窟へ行ってみる")
    vm.dismiss_reachable("L9")
    assert [x.id for x in vm.go_items()] == [got.id], "⚠ 自分で足した分まで消えた"
    assert vm.go_list.dismissed == {"L9"}


# --- ★★ あとから文を直す（RX3-0317 / 2026-09-20）----------------------------
#
#   ⚠⚠ 依頼者「メモの一部を選択したいが、メモを全部追加しか出来ない
#     → 全部追加してから、メンテできる機能があってもいい」


def _editable(qapp, vm, answer=None, auto_rows=()):
    win = _window(qapp, vm, auto_rows=auto_rows)
    win.ASK = False
    win.ask_text = lambda current: answer
    return win


def test_足した文をあとから直せる(qapp, tmp_path):
    """★★ これが依頼されたこと。"""
    vm = _VM(tmp_path)
    got = vm.add_go_item("東へ行くと洞窟がある。その先に小さな村があるらしい。",
                         source_memo_id=703, source_location_id="L1")
    win = _editable(qapp, vm, answer="その先に小さな村があるらしい。")
    assert _pick(win)
    assert win.edit_current() is True
    assert got.display_text == "その先に小さな村があるらしい。"
    assert any("小さな村" in t.text() for _i, t in _rows(win))


def test_直しても出典は残る(qapp, tmp_path):
    """⚠⚠ 元の勇者メモへ戻れなくならないこと。"""
    vm = _VM(tmp_path)
    got = vm.add_go_item("ぜんぶの文", source_memo_id=703, source_location_id="L1")
    win = _editable(qapp, vm, answer="要る所だけ")
    _pick(win)
    win.edit_current()
    assert (got.source_memo_id, got.source_location_id) == (703, "L1")


def test_やめたら直さない(qapp, tmp_path):
    vm = _VM(tmp_path)
    got = vm.add_go_item("もとの文")
    win = _editable(qapp, vm, answer=None)
    _pick(win)
    assert win.edit_current() is False
    assert got.display_text == "もとの文"


def test_空にはできない(qapp, tmp_path):
    """⚠ 消す道は [行った]（★空の行を作らない）。"""
    vm = _VM(tmp_path)
    got = vm.add_go_item("もとの文")
    win = _editable(qapp, vm, answer="   ")
    _pick(win)
    assert win.edit_current() is False
    assert got.display_text == "もとの文"


def test_直した文は再起動しても残る(tmp_path):
    vm = _VM(tmp_path)
    got = vm.add_go_item("もとの文")
    assert vm.edit_go_item(got.id, "直した文") is True
    assert [x.display_text for x in _VM(tmp_path).go_items()] == ["直した文"]


def test_自動で出た分は直せない(qapp, tmp_path):
    """⚠⚠ 毎回計算しているので、★直しても次で戻る（= 押せなくする）。"""
    vm = _VM(tmp_path)
    win = _editable(qapp, vm, answer="なにか", auto_rows=(_Auto("アリアハン", "L9"),))
    assert _pick(win)
    assert not win.edit_button.isEnabled()
    assert win.edit_current() is False


def test_済んだ分は直せない(qapp, tmp_path):
    vm = _VM(tmp_path)
    got = vm.add_go_item("もとの文")
    vm.complete_go_item(got.id)
    win = _editable(qapp, vm, answer="なにか")
    win.show_done.setChecked(True)
    assert _pick(win)
    assert not win.edit_button.isEnabled()


def test_直す窓は大きな編集画面ではない():
    """⚠ 依頼者の作法（★命名の窓と同じ / 1 行の入力だけ）。"""
    import inspect

    from dq3.ui.go_window import Dq3GoWindow

    src = inspect.getsource(Dq3GoWindow.ask_text)
    assert "QInputDialog" in src
    assert "QTextEdit" not in src, "⚠⚠ 大きな編集画面を作った"


# --- ★本文の欄は「選ぶ所」だと分かる形（RX3-0317）---------------------------


def test_本文の欄に見出しがある(qapp, tmp_path):
    """⚠ 依頼者は選ぶ所に気づけなかった（★仕組みは動いていた）。"""
    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    assert "選べます" in dialog.body_cap.text()


def test_なぞっていなければ1件まるごと(qapp, tmp_path):
    """⚠ 何も選んでいないときの戻り（★今までどおり）。"""
    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    dialog.list.setCurrentRow(0)
    assert dialog.selected_text() == ""
    assert dialog.go_text() == ROWS[0].text


def test_折り返しの区切りは空白にする(qapp, tmp_path):
    """⚠ `QTextEdit` の選択には段落の区切り（U+2029）が混ざる。"""
    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    dialog.list.setCurrentRow(0)
    dialog.body.selectAll()
    got = dialog.selected_text()
    assert " " not in got and got, got


def test_本文の欄は3行ぶんの高さがある(qapp, tmp_path):
    """⚠⚠ 画素で見ないのが決まりですが、★ここは**自分で指定した数**を見ます。"""
    from dq3.ui.memo_detail import BODY_PX

    dialog = _detail(qapp, _VM(tmp_path, ROWS))
    assert BODY_PX >= 60
    assert dialog.body.minimumHeight() == BODY_PX

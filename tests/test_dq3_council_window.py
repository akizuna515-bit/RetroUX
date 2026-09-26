"""勇者会議の窓（RX3-0074 §30 UI）。

```text
Topic 0 件 / 1 件 / 多数 / 長い題 / resolved 混在 / 親子 / 壊れた Master
```
★判断は `council.py`。⚠ ここは**渡された view を描くだけ**なので、view を手で作って渡す。
"""
from __future__ import annotations

import os

import pytest

from dq3.knowledge import council as CN


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                # pragma: no cover
        pytest.skip("Qt が無い環境")
    got = QApplication.instance()
    yield got if got is not None else QApplication([])


class _StillCouncil:
    """★評価を差し替える（⚠ 本物の work/ を読まない）。"""

    def __init__(self, view):
        self.view = view
        self.calls = 0

    def evaluate(self, save=True):
        self.calls += 1
        return self.view


def _card(tid, title, status="active", badge="NEW", cat="main", parent="", children=(),
          facts=(), updated="2026-09-04T10:00:00", pri=50):
    return {"topic_id": tid, "title": title, "category": cat,
            "category_label": CN.CATEGORY_LABEL.get(cat, cat),
            "status": status, "status_label": CN.STATUS_LABEL[status], "priority": pri,
            "sequence": 10, "phase": 1, "last_updated_at": updated,
            "last_updated_label": "09/04 10:00" if updated else "—",
            "update_count": 1 if badge == "NEW" else (2 if badge else 0), "badge": badge,
            "objective": "目的 " + tid, "completion_hint": "片づく " + tid, "message": "M " + tid,
            "parent_topic_id": parent, "children": list(children), "related_locations": ["どこか"],
            "matched_fact_ids": list(facts), "matched_rule_ids": []}


def _view(recent=(), unknown=(), resolved=(), head=None, ok=True, error=""):
    view = CN.CouncilView(ok=ok, error=error, topic_count=len(recent) + len(unknown) + len(resolved),
                          fact_count=3, head=head, recent=list(recent), unknown=list(unknown),
                          resolved=list(resolved))
    view.facts = {"f1": {"subject": "item:88", "predicate": "obtain_hint", "name": "かぎ",
                         "observation": "obs-1", "text": "＊「かぎを てにいれたか？"}}
    return view


def _window(view):
    from dq3.ui.council_window import Dq3CouncilWindow

    return Dq3CouncilWindow(view_model=None, council=_StillCouncil(view))


# --- ★件数 ----------------------------------------------------------------------

def test_Topic0件でも開く(app):
    w = _window(_view())
    assert "まだ" in w.head_message.text()
    assert w.list.count() == 0


def test_Topic1件(app):
    head = {"topic_id": "A", "title": "た", "ui_head_hint": "南の森を調べてみよう",
            "message": "南の森を調べてみよう", "category": "main", "priority": 50, "status": "active",
            "reason_fact_ids": ["f1"], "reasons": ["その品を手に入れたかと尋ねられた（かぎ）"],
            "clue_count": 1, "last_updated_at": "2026-09-04T10:00:00", "nav_target": None,
            "related_locations": []}
    w = _window(_view(recent=[_card("A", "た", facts=["f1"])], head=head))
    assert w.head_message.text() == "南の森を調べてみよう", "⚠ ui_head_hint をそのまま出していない"
    assert "手がかり 1 件" in w.head_sub.text()
    assert "尋ねられた" in w.head_reasons.text()
    assert w.list.count() == 1 and w.current_id() == "A"


def test_Topic多数と区切り(app):
    recent = [_card("T%02d" % i, "題 %d" % i) for i in range(12)]
    unknown = [_card("U%02d" % i, "未 %d" % i, status="unknown", badge="", updated=None) for i in range(20)]
    w = _window(_view(recent=recent, unknown=unknown))
    assert w.list.count() == 12 + 1 + 20
    # ★区切り行は選べない
    from PySide6.QtCore import Qt

    sep = w.list.item(12)
    assert sep.data(Qt.ItemDataRole.UserRole) == "__separator__"
    assert not (sep.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_長い題でも窓が広がらない(app):
    long_title = "とても" * 40 + "長い題"
    w = _window(_view(recent=[_card("L", long_title)]))
    w.show()
    app.processEvents()
    from dq3.ui.council_window import WINDOW_H, WINDOW_W

    assert w.width() == WINDOW_W and w.height() == WINDOW_H, "⚠ 中身で窓の大きさが変わった"


def test_resolvedは消さずに畳んで下に出す(app):
    w = _window(_view(recent=[_card("A", "追う")],
                      resolved=[_card("D", "済んだ", status="resolved", badge="更新")]))
    texts = [w.list.item(i).text() for i in range(w.list.count())]
    assert any("完了した話" in t for t in texts)
    assert any("済んだ" in t for t in texts), "⚠⚠ resolved を消した（§24）"
    assert texts.index(next(t for t in texts if "追う" in t)) < texts.index(next(t for t in texts if "済んだ" in t))


def test_親子が分かる(app):
    w = _window(_view(recent=[_card("P", "親", children=["C"]), _card("C", "子", parent="P")]))
    texts = [w.list.item(i).text() for i in range(w.list.count())]
    assert any("└" in t and "子" in t for t in texts)
    w.list.setCurrentRow(0)
    labels = _detail_texts(w)
    assert any("子の話" in t for t in labels) and any(t == "C" for t in labels)


def test_詳細に目的_状態_関連Fact_最後の更新が出る(app):
    w = _window(_view(recent=[_card("A", "た", facts=["f1"], badge="更新")]))
    w.list.setCurrentRow(0)
    texts = _detail_texts(w)
    joined = "\n".join(texts)
    for wanted in ("目的 A", "対応中", "更新 2 回", "item:88 obtain_hint（かぎ）", "関連する場所", "どこか"):
        assert wanted in joined, wanted
    # ★原文（聞いた文）は詳細でだけ
    assert "てにいれたか" in joined and "てにいれたか" not in w.head_reasons.text()


def test_壊れたMasterは画面に理由を出す(app):
    w = _window(_view(ok=False, error="Guide Master に問題が 1 件:\n  T1: priority が…"))
    assert "読めません" in w.head_message.text()
    assert "priority" in w.head_reasons.text()
    assert w.list.count() == 0


def test_更新ボタンで評価し直す(app):
    view = _view(recent=[_card("A", "た")])
    w = _window(view)
    assert w._council.calls == 1
    w.refresh_button.click()
    assert w._council.calls == 2, "⚠ [更新] で evaluate していない"
    assert w.current_id() == "A", "⚠ 更新で選んでいた話を失った"


def test_一覧はTopic単位でFactを並べない(app):
    """⚠ 指示書 §20。★Fact が何十件あっても行は Topic の数。"""
    card = _card("A", "た", facts=["f%d" % i for i in range(40)])
    w = _window(_view(recent=[card]))
    assert w.list.count() == 1


def test_勇者会議の入口がある(app):
    """★入口があること（⚠ **どの窓にあるか**は 2026-09-20 に 2 度変わりました）。

    ```text
    ⚠ もと        右の窓のボタン「会」（★指示書 §19）
    RX3-0302      ★左の地図の窓へ（依頼者「勇者会議のボタンは MAP 画面にもっていく」）
    RX3-0308      ★勇者メモの欄へ（依頼者「勇者メモの欄にしたい。MAP が少し横に伸びてしまった」）
    ```

    ⚠⚠ ここは**字面で固定しません**（★置き場所が変わるたびに、直したのに赤くなる）。
    ★本物の窓を作って、**押せるボタンが 1 つだけある**ことを見ます。
    """
    import pathlib

    from dq3.ui import main_window as MW
    from dq3.ui.view_model import Dq3ViewModel

    win = MW.Dq3MainWindow(Dq3ViewModel(), show_map=True)
    app.processEvents()

    # ★入口は 1 つ（⚠ 右の窓には置かない）
    assert "council" not in win._buttons, sorted(win._buttons)
    got = win.map_window.council_button
    # ★2026-09-20（RX3-0325）: 字は「会議」／⚠ 正式な名前はツールチップの 1 行目
    assert got.text() == "会議"
    assert got.toolTip().splitlines()[0] == "勇者会議"
    assert got.parent() is win.map_window.memos, "⚠⚠ 勇者メモの欄に無い"
    # ⚠⚠ 2026-09-26（RX3-0431）: **攻略データが無い環境では出しません**。
    #   ★公開版は Guide Master を同梱しないので、そこでは隠れているのが正しい姿。
    #   ⚠ ここを素で `isVisibleTo` にすると、公開木で回したとき赤くなります（実測）。
    from dq3.ui.memo_panel import MemoPanel

    if MemoPanel._guide_available():
        assert got.isVisibleTo(win.map_window.memos), "⚠ 並びに入っていない"
    else:
        assert not got.isVisibleTo(win.map_window.memos), (
            "⚠⚠ 攻略データが無いのに入口を出している")
    # ★ほかから呼ぶ口（⚠ 右の窓の open_council は残す）
    right = (pathlib.Path(__file__).resolve().parents[1]
             / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "def open_council" in right, "⚠ 右の入口（ほかから呼ぶ）は残す"


def _detail_texts(w) -> list[str]:
    from PySide6.QtWidgets import QLabel

    box = w._body_box
    got = []
    for i in range(box.count()):
        widget = box.itemAt(i).widget()
        if isinstance(widget, QLabel):
            got.append(widget.text())
    return got


# --- ★★ 行ってみる？の管理（RX3-0313 / 2026-09-20）--------------------------
#
#   ⚠⚠ 依頼者「勇者会議 行ってみるで既に完了している部分は、
#     『自分で足した分』ボタンを『管理』ボタンに変えて、別画面で終了したのは消し込みたい」


class _Auto:
    def __init__(self, name, location_id=None, why_text="話に出た"):
        self.name, self.location_id, self.why_text = name, location_id, why_text


class _GoVM:
    """★`go_list` だけを持つ見本（⚠ 本物の台帳には書かない）。"""

    from dq3.ui.view_model import Dq3ViewModel as _Real

    go_list = _Real.go_list
    go_items = _Real.go_items
    dismiss_reachable = _Real.dismiss_reachable

    def __init__(self, tmp_path):
        self._go_list_path = tmp_path / "go-list.json"
        self.location_book = None


def _council(app, view, vm):
    from dq3.ui.council_window import Dq3CouncilWindow

    got = Dq3CouncilWindow(view_model=vm, council=_StillCouncil(view))
    app.processEvents()
    return got


def test_ボタンの字は管理(app, tmp_path):
    from dq3.ui.council_window import GO_BUTTON

    assert GO_BUTTON == "管理"
    w = _council(app, _view(), _GoVM(tmp_path))
    assert w.go_button.text().startswith(GO_BUTTON)
    assert "自分で足した分" not in w.go_button.text()


def test_ボタンの字は1か所から作る(app, tmp_path):
    """⚠⚠ 壊す実験で分かったこと: ★作るときの字は**描き直しで上書き**される。

    ⚠ 2 か所に別々に書くと、★片方を直しても画面は変わりません（= 直したつもりで直っていない）。
    """
    import dq3.ui.council_window as CW

    w = _council(app, _view(), _GoVM(tmp_path))
    CW.GO_BUTTON = "★別の字"
    try:
        w.render(w.view)
        assert w.go_button.text().startswith("★別の字"), w.go_button.text()
    finally:
        CW.GO_BUTTON = "管理"


def test_消し込んだ場所は行ってみるに出ない(app, tmp_path):
    """★★ これが直したかったこと。"""
    vm = _GoVM(tmp_path)
    view = _view()
    view.reachable = [_Auto("アリアハン", "L9"), _Auto("レーベ", "L1")]
    w = _council(app, view, vm)
    assert "アリアハン" in w.reachable_line.text()

    vm.dismiss_reachable("L9")
    w.render(view)
    assert "アリアハン" not in w.reachable_line.text(), "⚠⚠ 消し込みが効いていない"
    assert "レーベ" in w.reachable_line.text(), "⚠ ほかの行まで消した"


def test_全部消し込んだら節ごと消える(app, tmp_path):
    vm = _GoVM(tmp_path)
    view = _view()
    view.reachable = [_Auto("アリアハン", "L9")]
    w = _council(app, view, vm)
    vm.dismiss_reachable("L9")
    w.render(view)
    assert not w.reachable_line.isVisible()


def test_管理ボタンの数は自動と自分の合計(app, tmp_path):
    vm = _GoVM(tmp_path)
    vm.go_list.add("自分で足した話")
    view = _view()
    view.reachable = [_Auto("アリアハン", "L9"), _Auto("レーベ", "L1")]
    w = _council(app, view, vm)
    assert w.go_button.text() == "管理 3", w.go_button.text()
    vm.dismiss_reachable("L9")
    w.render(view)
    assert w.go_button.text() == "管理 2"


def test_台帳が無くても落ちない(app):
    """⚠ `view_model=None` の検査が今までどおり動く。"""
    view = _view()
    view.reachable = [_Auto("アリアハン", "L9")]
    w = _window(view)
    assert "アリアハン" in w.reachable_line.text(), "⚠ 台帳が無いと消し込みも効かないので、全部出る"
    assert w.go_button.text() == "管理 1"

"""ボタンの置き場と窓の名前（RX3-0302 / RX3-0306 / 2026-09-20）。

依頼者 2026-09-20:

```text
・勇者会議のボタンは MAP 画面にもっていく
・勇者メモのボタンは、左の MAP 画面に移動させたい。右側のボタンも一列になるし
・画面のタイトルバーを変えたい。左：地図、勇者メモ 右：RetroUX DQ3 下：ログ
```

★勇者メモは**もともと**地図の窓の中にあります（`MemoPanel`）。
⚠ 右から移したのは**勇者会議**の 1 つで、★それで右が **10 個 → 9 個 = 1 段**になります。

⚠⚠ 画面外の Qt は `processEvents` まで位置が 0（RX3-0258）。
→ ★ここでは**数**と**名前**で見ます（⚠ 画素で見ない）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                     # noqa: E402

from dq3.ui import layout as L                                 # noqa: E402
from dq3.ui import main_window as MW                           # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    from dq3.ui.view_model import Dq3ViewModel

    got = MW.Dq3MainWindow(Dq3ViewModel(), show_map=True)
    app.processEvents()
    return got


# --- ★右のボタンは 1 段 --------------------------------------------------

def test_右のボタンはどの段も右パネルに収まる(win):
    """★依頼者「UI全体を必要以上に大きくしないでください」（RX3-0325）。

    ⚠⚠ 2026-09-20: 1 段だけ、という決まりは**外しました**。
      ★アイコン＋字にすると幅が字の長さで変わるため（「まんたん」と「終」で倍ちがう）、
      ⚠ 段数を決め打ちにすると**実機でだけはみ出します**（RX3-0074 / RX3-0084 と同じ事故）。
    → ★見るのは「段数」ではなく、**どの段も使える幅に収まっているか**です。
    """
    from dq3.ui import icon_button as IB

    rows = IB.wrap_rows(list(win._buttons.values()))
    for i, line in enumerate(rows):
        width = sum(b.width() for b in line) + IB.SPACING * (len(line) - 1)
        assert width <= IB.PANEL_WIDTH, (
            "⚠⚠ 段 %d が %d px（★使える幅 %d を超えた）: %s"
            % (i + 1, width, IB.PANEL_WIDTH, "/".join(b.text() for b in line)))


def test_勇者会議のボタンは右に無い(win):
    """⚠ 2 か所に置かない（★押す所が 2 つあると、どちらが効いたか分からない）。"""
    assert "council" not in win._buttons, sorted(win._buttons)


def test_右に残るボタンは変えていない(win):
    """⚠ 移したのは勇者会議 1 つだけ（★ほかを巻き込んでいない）。

    ⚠⚠ 2026-09-20（RX3-0325）: 鍵を**表示の字から役割へ**変えました。
      ★以前は `win._buttons["A"]` のように字が鍵で、⚠ 字を変えると
      `_apply_battle_buttons` が**例外も出さずに何もしなくなり**ました。
    """
    assert list(win._buttons) == ["align", "auto", "turbo", "map", "monster",
                                  "shop", "mantan", "admin", "exit"]


# --- ★左の地図の窓 -------------------------------------------------------

def test_勇者会議のボタンは勇者メモの欄にある(win):
    """★依頼者 2026-09-20「勇者会議のボタンは、勇者メモの欄にしたい」（RX3-0308）。

    ⚠ もとは地図の窓の**下の行**（命名・大きさ・現在地と同じ行）に置いていました。
    """
    got = win.map_window
    assert hasattr(got, "council_button")
    # ★★ 2026-09-20（RX3-0325）: 字は「会議」、⚠ **正式な名前はツールチップの 1 行目**
    #   （依頼者「表示ラベル：会議」/ ★1 文字・短い字のボタンは説明を必ず付ける）。
    assert got.council_button.text() == "会議"
    assert got.council_button.toolTip().splitlines()[0] == "勇者会議"
    # ⚠⚠ **作っただけで置き忘れる**を防ぐ（★壊す実験で見つけた）。
    #   ★親が勇者メモの欄で、⚠ 並びに入っていること
    assert got.council_button.parent() is got.memos, "⚠⚠ 勇者メモの欄に置いていない"
    # ⚠⚠ 2026-09-26（RX3-0431）: **攻略データが無い環境では出しません**。
    #   ★置き場（親）は変わらず、⚠ 見えるかどうかだけが変わります。
    from dq3.ui.memo_panel import MemoPanel

    if MemoPanel._guide_available():
        assert got.council_button.isVisibleTo(got.memos), "⚠⚠ 並びに入っていない（★見えない）"
    else:
        assert not got.council_button.isVisibleTo(got.memos), (
            "⚠⚠ 攻略データが無いのに入口を出している")
    assert got.council_button is got.memos.council_button


def test_勇者会議は地図の窓の下の行に無い(win):
    """⚠ 2 か所に置かない（★どちらが効いたか分からなくなる）。"""
    row = win.map_window.layout().itemAt(win.map_window.layout().count() - 1).layout()
    texts = [row.itemAt(i).widget().text() for i in range(row.count())
             if row.itemAt(i).widget() is not None and hasattr(row.itemAt(i).widget(), "text")]
    assert "勇者会議" not in texts, texts


def test_地図の窓は既定の幅に収まる(win, app):
    """★★ 依頼者「MAP が少し横に伸びてしまった」（RX3-0308）。

    ⚠ Qt は `minimumSizeHint` より狭い窓を作りません。★下の行に 4 つ目のボタンを足した
    時点で最小幅が **378 px** になり、⚠ 既定の **360 px** を超えて窓が広がっていました。

    ⚠⚠ 画素で見ないという決まり（RX3-0258）に反して見えますが、★ここで見るのは
    **フォントに依らない 2 つの数の大小**です（★どちらも同じ環境の同じ尺度）。
    """
    want = L.default_sizes(L.qt_area()).map.as_tuple()[2]
    got = win.map_window.minimumSizeHint().width()
    assert got <= want, "⚠⚠ 最小幅 %d px が既定 %d px を超えた（★窓が横に伸びる）" % (got, want)


def test_勇者メモは地図の窓の中にある(win):
    """★もともとここにあります（⚠ 移す必要は無かった）。"""
    from dq3.ui.memo_panel import MemoPanel

    assert isinstance(win.map_window.memos, MemoPanel)


def test_勇者会議は2つ開かない(win):
    """⚠ 押すたびに新しい窓を作らない。"""
    got = win.map_window
    got.open_council()
    first = got._council
    got.open_council()
    assert got._council is first, "⚠⚠ 2 つ目の窓を作った"
    first.close()


# --- ★窓の名前 -----------------------------------------------------------

def test_窓の名前は中身で分かる(win, app):
    """★依頼者「左：地図、勇者メモ 右：RetroUX DQ3 下：ログ」。"""
    from dq3.ui.battle_window import Dq3BattleWindow

    assert win.map_window.windowTitle() == "地図、勇者メモ"
    assert win.windowTitle() == "RetroUX DQ3"
    assert Dq3BattleWindow(win.vm).windowTitle() == "ログ"


def test_名前に開発中と付けない(win):
    """⚠ 依頼者の指示は「RetroUX DQ3」（★余計な字を足さない）。"""
    assert "開発中" not in win.windowTitle()


# --- ★右パネルのスリム化（RX3-0328 / 2026-09-21）------------------------

def test_操作と自動戦闘の見出しを出さない(win):
    """★依頼者 2026-09-21「『自動戦闘』ラベルは不要 『操作』ラベルは不要」。

    ⚠ 縦を稼ぐための変更です（★アイコンの行が何かはツールチップが言います）。
    """
    from PySide6.QtWidgets import QLabel

    texts = {(lbl.text() or "").strip() for lbl in win.findChildren(QLabel)}
    for gone in ("操作", "自動戦闘"):
        assert gone not in texts, "⚠ 見出し「%s」が残っている" % gone


def test_届いていれば状態の欄を隠す(win, app, monkeypatch):
    """★依頼者「frame／フィールド表示は管理画面に移動させていい」。

    ⚠⚠ 「届いていません」**だけは右画面に残します**。★これが出ないと、
      利用者は動いていないことに気づけません（⚠ 管理画面を開くまで分からない、では遅い）。

    ⚠⚠ 2026-09-21: **両方の枝を通します**。★FCEUX が動いていない環境では
      「届いている」側が一度も実行されず、⚠ frame を書き戻しても緑のままでした
      （★「既定 OFF の道は一度も実行されない」/ 壊す実験で踏んだ）。
    """
    real = win.vm.state

    class _S:
        def __init__(self, frame):
            got = real()
            for name in dir(got):
                if not name.startswith("_"):
                    setattr(self, name, getattr(got, name))
            self.frame = frame
            self.in_battle = False

    # ★届いている → 欄は空で隠れている（⚠ 縦を使わない）
    monkeypatch.setattr(win.vm, "state", lambda: _S(1234))
    win.refresh()
    app.processEvents()
    assert (win._status.text() or "").strip() == "", (
        "⚠⚠ frame の表示が右画面に残っている: %r" % win._status.text())
    assert not win._status.isVisibleTo(win), "⚠ 空の欄で縦を使っている"

    # ⚠ 届いていない → その 1 行だけは出す
    monkeypatch.setattr(win.vm, "state", lambda: _S(None))
    win.refresh()
    app.processEvents()
    assert "届いていません" in (win._status.text() or ""), win._status.text()
    assert win._status.isVisibleTo(win), "⚠⚠ 動いていないことに気づけない"


def test_frameとフィールドは管理画面に出る(win):
    """★移した先に**本当に出ている**こと（⚠ 消しただけになっていないか）。"""
    got = win.vm
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "dq3" / "ui" / "admin_window.py").read_text(encoding="utf-8")
    assert '"where"' in src and "戦闘中" in src and "フィールド" in src, (
        "⚠⚠ 管理画面に「戦闘中 / フィールド」が無い（★移したつもりで消している）")
    assert got is not None


def test_右パネルは縦に縮んだ(win, app):
    """★依頼者「縦を稼ぎたい」。⚠ 同じ尺度どうしの大小で見ます（RX3-0258）。

    ⚠⚠ 画素の絶対値は実機と違うので、★**枠に対する割合**で見ます。
    """
    app.processEvents()
    want = L.default_sizes(L.qt_area()).panel
    need = win.minimumSizeHint().height()
    assert need <= want.h * 0.7, (
        "⚠ 右パネルの中身が枠の 7 割を超えた（%d / %d）★縦を使いすぎ" % (need, want.h))


def test_ボタンは1段に収まる(win):
    """★アイコンだけにして 1 段へ戻りました（⚠ 2 段だと縦を損します）。"""
    from dq3.ui import icon_button as IB

    rows = IB.wrap_rows(list(win._buttons.values()))
    assert len(rows) == 1, "⚠ %d 段になっている: %s" % (
        len(rows), [[b.text() for b in r] for r in rows])


def test_窓を画面の中へ収める(app):
    """★依頼者 2026-09-21「戦闘AIのウィンドウ … 下が隠れる。少し上に表示させたい」。

    ⚠⚠ Qt は窓を置くとき、★**画面からはみ出すかどうかを見ません**。
    """
    from PySide6.QtWidgets import QWidget

    area = L.qt_area()
    if area is None:                                   # pragma: no cover
        import pytest

        pytest.skip("画面が分からない環境")
    ax, ay, aw, ah = area
    w = QWidget()
    w.resize(400, 300)
    w.move(ax + aw - 50, ay + ah - 50)                 # ★右下へわざとはみ出させる
    app.processEvents()
    got = L.fit_on_screen(w)
    try:
        assert got is not None
        x, y, gw, gh = got
        assert x >= ax and y >= ay, "⚠ 左上へはみ出した: %s" % (got,)
        assert x + gw <= ax + aw and y + gh <= ay + ah, "⚠⚠ まだ画面からはみ出している: %s" % (got,)
    finally:
        w.close()


def test_画面より大きい窓は縮める(app):
    """⚠ 背の高い窓（戦闘AI設定）が作業領域より大きいとき、★下が切れない。"""
    from PySide6.QtWidgets import QWidget

    area = L.qt_area()
    if area is None:                                   # pragma: no cover
        import pytest

        pytest.skip("画面が分からない環境")
    ax, ay, aw, ah = area
    w = QWidget()
    w.resize(aw + 400, ah + 400)
    app.processEvents()
    got = L.fit_on_screen(w)
    try:
        _x, _y, gw, gh = got
        assert gw <= aw and gh <= ah, "⚠⚠ 画面より大きいまま: %s（作業領域 %dx%d）" % (got, aw, ah)
    finally:
        w.close()


# --- ★並びと説明（RX3-0329 / 2026-09-21）--------------------------------

def _order(win) -> list:
    """★右パネルの縦の並び（⚠ 名前で見る / 画素で見ない）。"""
    root = win.layout()
    out = []
    for i in range(root.count()):
        w = root.itemAt(i).widget()
        if w is None:
            continue
        for name in ("town_bar", "_strategy_row", "mantan_row", "auto_panel", "party"):
            if getattr(win, name, None) is w:
                out.append(name)
    return out


def test_まんたんは自動戦闘より上(win):
    """★依頼者 2026-09-21「満タン設定と Auto 戦闘の振る舞いの順番は逆（満タン設定のほうが上に）」。"""
    got = _order(win)
    assert "mantan_row" in got and "auto_panel" in got, got
    assert got.index("mantan_row") < got.index("auto_panel"), "⚠ 並びが逆: %s" % got


def test_右パネルの並びは決まっている(win):
    """⚠ 途中に割り込んで順番が崩れていないこと（★街 → 戦略 → まんたん → 自動戦闘）。"""
    got = [n for n in _order(win) if n != "party"]
    assert got == ["town_bar", "_strategy_row", "mantan_row", "auto_panel"], got


def test_押せないボタンでも説明が出る(win, app):
    """★依頼者 2026-09-21「ツールチップはだしてほしい」。

    ⚠⚠ **Qt は押せない部品にマウスの出来事を届けません。**
      ★だから押せない間は、`setToolTip` を入れてあっても**出ません**。
      ⚠ ところが「なぜ押せないのか」を知りたいのは、まさに押せないときです。
    → ★入れ物が代わりに受け取って出します（`icon_button.watch_disabled`）。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    win.show()
    app.processEvents()
    button = win._buttons["turbo"]
    button.setEnabled(False)                     # ★戦闘の外では押せない
    box = button.parentWidget()
    app.processEvents()
    QToolTip.hideText()
    pos = button.mapTo(box, button.rect().center())
    ok = app.sendEvent(box, QHelpEvent(QEvent.Type.ToolTip, pos, box.mapToGlobal(pos)))
    app.processEvents()
    got = QToolTip.text()
    QToolTip.hideText()
    button.setEnabled(True)
    assert ok, "⚠ 入れ物が説明の出来事を受け取っていない"
    assert got and "Turbo" in got, "⚠⚠ 押せないボタンの説明が出ない: %r" % got

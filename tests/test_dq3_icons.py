"""ボタンのアイコン（RX3-0325 / 2026-09-20）。

依頼者 2026-09-20:

    公開前のUI仕上げとして主要ボタンをアイコン化します。
    シンプル / フラット / 現代的 / 視認性重視

## ⚠⚠ ここで固定すること

```text
1. 表の絵が**実在して、本当に描かれる**       ★空の絵に気づけない事故を止める
2. 線の色が 1 色だけ                          ★塗り替えられる（色は QIcon では変えられない）
3. 4 つの状態が**見た目として違う**            ★Normal / Hover / ON / Disabled
4. アイコンのボタンには**必ず説明**            ★DQ2 の掟（test_icon_buttons_have_tooltips）と同じ
5. 字を後から書き戻さない                      ⚠ DQ2 で字がはみ出た事故（2026-08-11）
6. どの段も右パネルに収まる                    ⚠ 実機でだけはみ出す事故（RX3-0074 / 0084）
```

⚠⚠ 寸法は**画素で見ません**（RX3-0258）。★見るのは「自分で決めた数」と
「同じ尺度どうしの大小」だけです（⚠ 画面外には日本語のフォントが 1 つもありません）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from dq3.ui import icon_button as IB                  # noqa: E402
from dq3.ui import icons, theme                       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ----------------------------------------------------------------------
# ★1. 絵そのもの
# ----------------------------------------------------------------------
def test_表にある絵はすべて実在する():
    """⚠⚠ 足りないファイルは**黙って空のアイコン**になります（★誰も気づけない）。"""
    assert icons.missing() == (), "⚠⚠ 絵が足りません: %s" % (icons.missing(),)


def test_依頼者が挙げた14個がそろっている():
    """★依頼者 §3「まず以下14個を対象にしてください」。"""
    want = ("auto", "turbo", "stop", "mantan",        # 戦闘系
            "map", "memo", "council", "hear", "search",  # 探索・情報系
            "inn", "item_shop", "weapon", "church",   # 街移動系
            "admin")                                  # 管理系
    missing = [r for r in want if r not in icons.ICONS]
    assert not missing, "⚠ 表に無い: %s" % missing


def test_絵の名前と機能の対応は1か所(app):
    """⚠⚠ 同じ絵が 2 通りに実装されるのを止める（依頼者 §12）。

    ★画面のファイルは `icons.ICONS` の鍵しか書かず、**ファイル名を直接書きません**。
    """
    bad = []
    for path in sorted((ROOT / "dq3" / "ui").glob("*.py")):
        if path.name in ("icons.py",):
            continue
        src = path.read_text(encoding="utf-8")
        for name in icons.ICONS.values():
            if name in src:
                bad.append("%s に %s" % (path.name, name))
    assert not bad, "⚠⚠ 絵のファイル名を画面が直接書いている: %s" % bad


def test_線の色は1色だけ():
    """⚠⚠ 色は SVG の本文を**塗り替えて**出します（★QIcon では色を変えられない）。

    → ★別の色が混じっていると、その部分だけ塗り替わりません。
    """
    import re

    for role in icons.roles():
        text = icons.path(role).read_text(encoding="utf-8")
        found = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}", text)}
        assert found == {icons.STROKE}, "⚠ %s に別の色: %s" % (role, sorted(found))


def test_絵は本当に描かれる(app):
    """⚠⚠ 壊れた path は**例外を出さずに真っ白**になります（★いちばん静かな壊れ方）。"""
    from PySide6.QtGui import QImage

    thin, fat = [], []
    for role in icons.roles():
        pm = icons.pixmap(role, theme.INK, 32)
        assert not pm.isNull(), "⚠ %s が空" % role
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        on = sum(1 for y in range(img.height()) for x in range(img.width())
                 if (img.pixel(x, y) >> 24) & 0xFF)
        share = on / float(img.width() * img.height())
        if share < 0.04:
            thin.append((role, round(share, 3)))
        if share > 0.60:
            fat.append((role, round(share, 3)))
    assert not thin, "⚠⚠ 何も描かれていない／薄すぎる: %s" % thin
    assert not fat, "⚠ 濃すぎる（★線画になっていない）: %s" % fat


def test_塗り替えた色で描かれる(app):
    """★同じ絵でも、色を変えたら**違う絵**になること（⚠ 塗り替えが効いていない事故）。"""
    a = icons.pixmap("auto", theme.INK, 16).toImage()
    b = icons.pixmap("auto", theme.ACCENT, 16).toImage()
    assert a != b, "⚠⚠ 色を変えても同じ絵（★塗り替えが効いていない）"


def test_知らない役割は黙って無視しない():
    """⚠ 綴りを間違えたときに、★空のアイコンではなく**エラー**にする。"""
    with pytest.raises(KeyError):
        icons.path("ありえない役割")


# ----------------------------------------------------------------------
# ★2. 4 つの状態
# ----------------------------------------------------------------------
def test_4つの状態は見た目が違う(app):
    """★依頼者 §6「Normal / Hover / ON / Disabled」。⚠ 色名ではなく**違うこと**を見る。"""
    qss = IB.style_sheet()
    for word in (":hover", ":pressed", '[on="true"]', ":disabled"):
        assert word in qss, "⚠ %s の見た目が無い" % word
    c = IB.colours()
    # ★ふつう / ふれた / 入っている / 押せない の地色が互いに違う
    grounds = (c["bg"], c["hover_bg"], c["on_bg"], c["off_bg"])
    assert len(set(grounds)) == len(grounds), "⚠ 地色が同じ: %s" % (grounds,)
    inks = (c["ink"], c["on_ink"], c["off_ink"])
    assert len(set(inks)) == len(inks), "⚠ 字の色が同じ: %s" % (inks,)


def test_押せないときは薄く入っているときは濃い():
    """⚠ 「押せない」が濃いと、★押せるように見えます。"""
    c = IB.colours()
    assert theme.luma(c["off_ink"]) > theme.luma(c["ink"]), "⚠ 押せない字が濃すぎる"
    assert theme.luma(c["on_ink"]) < theme.MAX_LUMA, "⚠ ON の色が白地で読めない"


def test_新しいテーマ色を増やしていない():
    """★依頼者 §8「新しいテーマ色を勝手に増やさないでください」。

    ⚠ すべて `theme` の色から `theme.mix()` で作ること（★`icon_button` に生の色を書かない）。
    """
    import re

    src = (ROOT / "dq3" / "ui" / "icon_button.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    found = [c for ln in code for c in re.findall(r"#[0-9a-fA-F]{3,8}", ln)]
    assert not found, "⚠⚠ 生の色が書いてある: %s" % found


def test_ONは実際の状態で決める(app):
    """⚠⚠ 押した瞬間ではなく、★`state.json` の値で決めること（`_apply_battle_buttons`）。"""
    button = IB.make("auto", "オート", "自動戦闘")
    assert not IB.is_on(button)
    IB.set_on(button, True)
    assert IB.is_on(button)
    IB.set_on(button, False)
    assert not IB.is_on(button)


def test_ONで絵の色も変わる(app):
    """⚠ 枠と地色だけ変えても、★アイコンはスタイルシートで色が変わりません。"""
    button = IB.make("turbo", "ターボ", "高速化")
    off = button.icon().pixmap(16).toImage()
    IB.set_on(button, True)
    on = button.icon().pixmap(16).toImage()
    assert off != on, "⚠⚠ ON にしても絵の色が変わっていない"


def test_押せないときの絵も持っている(app):
    """★Qt が自動で使う（⚠ 呼ぶ側が押せるかどうかを気にしなくて済む）。

    ⚠⚠ 2026-09-20 の壊す実験で分かったこと: ★「ふつうの絵と違う」では**足りません**。
      Qt は自前の絵が無くても**勝手に灰色版を作る**ので、`addPixmap` を消しても
      ⚠ 検査は緑のままでした（★壊れていないのではなく、気づけていなかった）。
    → ★**自分が入れた色そのもの**が返ることを見ます。
    """
    from PySide6.QtGui import QIcon

    button = IB.make("mantan", "まんたん", "全員を回復する")
    off = button.icon().pixmap(16, QIcon.Mode.Disabled).toImage()
    want = icons.pixmap("mantan", IB.colours()["off_ink"], IB.ICON_PX).toImage()
    assert off == want, "⚠⚠ 押せないときの絵を自分で入れていない（★Qt の自動生成になっている）"


# ----------------------------------------------------------------------
# ★3. 字と幅
# ----------------------------------------------------------------------
def test_字は消さない(app):
    """★依頼者 §4「アイコンで認識しやすくし、文字で意味を確定する」。"""
    button = IB.make("map", "地図", "行った地図を見る")
    assert button.text() == "地図"


def test_字を変えたら幅も変わる(app):
    """⚠⚠ DQ2 で実際に起きた事故（2026-08-11）: ★字を書き戻して**はみ出した**。

    → ★`set_label` は幅も合わせ直します（⚠ `setText` を直に呼ばない）。
    """
    button = IB.make("hear", "聞", "聞き込み")
    narrow = button.width()
    IB.set_label(button, "再聞き込み")
    assert button.width() > narrow, "⚠⚠ 字を長くしたのに幅が同じ（★はみ出す）"
    IB.set_label(button, "聞")
    assert button.width() == narrow


def test_アイコンのぶんの幅がある(app):
    """⚠⚠ 字の幅だけで決めると、★アイコンが切れます（以前の `_fit` の穴）。"""
    button = IB.make("inn", "宿", "宿屋へ移動")
    only_text = button.fontMetrics().horizontalAdvance("宿")
    assert button.width() >= only_text + IB.ICON_PX, (
        "⚠ 幅 %d は字 %d ＋ 絵 %d に足りない" % (button.width(), only_text, IB.ICON_PX))


def test_下に字を置くほうが狭い(app):
    """★街の行は横に 8 個並ぶ（⚠ 字を右に置くと状態の文の場所が消える）。"""
    beside = IB.make("inn", "宿", "t", place=IB.BESIDE)
    under = IB.make("inn", "宿", "t", place=IB.UNDER)
    assert under.width() < beside.width()
    assert under.height() > beside.height(), "⚠ 縦に積んだのに高さが同じ"


def test_段は使える幅に収まる(app):
    """⚠⚠ 段数を決め打ちにすると、★実機でだけはみ出します（RX3-0074 / RX3-0084）。"""
    made = [IB.make("mantan", "まんたん", "t") for _ in range(9)]
    for line in IB.wrap_rows(made):
        width = sum(b.width() for b in line) + IB.SPACING * (len(line) - 1)
        assert width <= IB.PANEL_WIDTH, "⚠ %d px（★使える幅 %d）" % (width, IB.PANEL_WIDTH)
    assert len(IB.wrap_rows(made)) > 1, "⚠ 9 個が 1 段に入るはずがない（★折り返していない）"


# ----------------------------------------------------------------------
# ★4. 本物の画面
# ----------------------------------------------------------------------
def _main(app):
    from dq3.ui.main_window import Dq3MainWindow
    from dq3.ui.view_model import Dq3ViewModel

    win = Dq3MainWindow(Dq3ViewModel(), show_map=True)
    app.processEvents()
    return win


def test_右パネルのボタンは役割で引ける(app):
    """⚠⚠ 以前は**表示の字**が鍵でした（`_buttons["A"]`）。

    ★字を変えると `_apply_battle_buttons` が**例外も出さずに何もしなくなり**ました。
    """
    win = _main(app)
    try:
        assert set(win._buttons) == {"align", "auto", "turbo", "map", "monster",
                                     "shop", "mantan", "admin", "exit"}
    finally:
        win.close()


def test_右パネルのボタンは全部アイコンつき(app):
    win = _main(app)
    try:
        bare = [r for r, b in win._buttons.items() if b.icon().isNull()]
        assert not bare, "⚠ 絵が無いボタン: %s" % bare
    finally:
        win.close()


def test_アイコンのボタンには説明がある(app):
    """★DQ2 の掟（`tests/test_icon_buttons_have_tooltips.py`）を DQ3 にも。

    ⚠ そちらは `retroux/ui`（DQ2）しか見ていません。
    """
    win = _main(app)
    try:
        targets = list(win._buttons.values())
        bar = win.town_bar
        targets += list(bar.move_buttons.values()) + [bar.hear_button, bar.restock_button]
        targets += [win.map_window.memos._detail, win.map_window.memos.council_button]
        for button in targets:
            label = button.text() or "（絵だけ）"
            tip = (button.toolTip() or "").strip()
            assert tip, "⚠ 「%s」に説明が無い" % label
            first = tip.splitlines()[0].strip()
            assert len(first) >= 3, (
                "⚠ 「%s」の 1 行目が短すぎる（%r）。★何のボタンかを書くこと" % (label, first))
        assert len(targets) >= 16, "⚠ 見ている数が少なすぎる（★素通りしている）"
    finally:
        win.close()


def test_1文字のボタンは正式な名前を説明に出す(app):
    """★`RX3-0257` / `RX3-0290` と同じ作法（⚠ 1 文字だけでは何か分からない）。"""
    win = _main(app)
    try:
        from dq3.ui.town_bar import MOVE_BUTTONS

        for _role, text, name in MOVE_BUTTONS:
            button = win.town_bar.move_buttons[_role]
            assert button.text() == text
            assert name in button.toolTip(), "⚠ 「%s」の説明に %s が無い" % (text, name)
    finally:
        win.close()


def test_街の行は横に広がらない(app):
    """⚠⚠ 字を**右**に置くと、★状態の文（「★道具屋 1/2 へ」）の場所が消えます。"""
    win = _main(app)
    try:
        bar = win.town_bar
        widgets = (list(bar.move_buttons.values())
                   + [bar.hear_button, bar.restock_button, bar.restock_settings_button])
        total = sum(b.width() for b in widgets) + IB.SPACING * (len(widgets) - 1)
        # ★状態の文の場所を必ず残す（⚠ 半分以上を取らない）
        assert total <= IB.PANEL_WIDTH * 0.8, (
            "⚠⚠ ボタンで %d px 使っている（★使える幅 %d / 状態の文が出せない）"
            % (total, IB.PANEL_WIDTH))
    finally:
        win.close()


def test_街の行の高さはそろっている(app):
    """⚠ 1 つだけ背が高いと段差に見えます。"""
    win = _main(app)
    try:
        bar = win.town_bar
        heights = {b.height() for b in
                   (list(bar.move_buttons.values())
                    + [bar.hear_button, bar.restock_button, bar.restock_settings_button])}
        assert len(heights) == 1, "⚠ 高さがそろっていない: %s" % sorted(heights)
    finally:
        win.close()


def test_地図の窓は既定の幅のまま(app):
    """⚠⚠ Qt は `minimumSizeHint` より狭い窓を作りません（RX3-0308 の事故）。

    ★勇者メモの欄にアイコンを足したので、★ここが広がっていないことを確かめます。
    """
    from dq3.ui import layout as L

    win = _main(app)
    try:
        want = L.default_sizes(L.qt_area()).map.as_tuple()[2]
        got = win.map_window.minimumSizeHint().width()
        assert got <= want, "⚠⚠ 最小幅 %d px が既定 %d px を超えた" % (got, want)
    finally:
        win.close()


def test_聞き込み中は止めるの絵になる(app):
    """★実行中は「止」＋四角の絵（⚠ 字だけでなく絵も替える）。"""
    win = _main(app)
    try:
        bar = win.town_bar
        before = bar.hear_button.property("role")
        bar.ctl.mode = "hearing"
        bar.refresh()
        assert bar.hear_button.property("role") == "stop"
        assert IB.is_on(bar.hear_button), "⚠ 実行中だと分からない"
        bar.ctl.mode = None
        bar.refresh()
        assert bar.hear_button.property("role") == before
        assert not IB.is_on(bar.hear_button)
    finally:
        win.close()


def test_虫眼鏡は欄の中に置く(app):
    """★`RX3-0254`「実行ボタンは置かない（打つそばから絞る）」を守ったまま絵を出す。

    ⚠⚠ ボタンにすると「押さないと絞れない」と誤解されます。
      → ★`QLineEdit.addAction` で**欄の中**に置きます（⚠ 押す物を増やさない）。

    ⚠ 「検索のボタンが無いこと」は `tests/test_dq3_memo_search.py` の
      `test_検索の行にボタンを置かない` が本物の窓で見ています（★ここでは重ねません）。
    """
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from test_dq3_memo_search import MEMOS, FakeService, FakeVM  # noqa: E402

    from dq3.ui import memo_detail as MD

    dlg = MD.MemoDetailDialog(FakeVM(MEMOS), FakeService())
    try:
        actions = dlg.search_edit.actions()
        assert actions, "⚠⚠ 虫眼鏡が欄の中に無い"
        assert any(not a.icon().isNull() for a in actions), "⚠ 絵が付いていない"
    finally:
        dlg.close()


# ----------------------------------------------------------------------
# ★5. アイコンだけにする（RX3-0328 / 2026-09-21）
# ----------------------------------------------------------------------
def test_字は残すが出さない(app):
    """★依頼者 2026-09-21「右側の画面のアイコンだが、文字はいらない。アイコンだけでいい」。

    ⚠⚠ 字（`setText`）は**消しません**。★`text()` は「宿」「オート」を返し続けます。
      理由: ★字はそのボタンの**名前**でもあり、記録・検査・説明が使っています。
      ⚠ 空にすると `_buttons` の鍵も検査の手がかりも消えます。
    → ★出すか出さないかだけを変えます。
    """
    from PySide6.QtCore import Qt

    button = IB.make("inn", "宿", "宿屋へ移動", place=IB.ICON)
    assert button.text() == "宿", "⚠ 字そのものを消してしまった"
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert not button.icon().isNull()


def test_アイコンだけのほうが小さい(app):
    """★依頼者「縦を稼ぎたい」。⚠ 同じ尺度どうしの大小で見ます（RX3-0258）。"""
    icon = IB.make("mantan", "まんたん", "t", place=IB.ICON)
    beside = IB.make("mantan", "まんたん", "t", place=IB.BESIDE)
    under = IB.make("mantan", "まんたん", "t", place=IB.UNDER)
    assert icon.width() < beside.width(), "⚠ 横が縮んでいない"
    assert icon.height() < under.height(), "⚠ 縦が縮んでいない"
    assert icon.height() <= beside.height()


def test_右パネルと街の行はアイコンだけ(app):
    """⚠⚠ 字を出す設定に戻っていないこと（★戻っても `text()` は同じなので気づけない）。"""
    from PySide6.QtCore import Qt

    win = _main(app)
    try:
        bar = win.town_bar
        targets = list(win._buttons.values()) + list(bar.move_buttons.values())
        targets += [bar.hear_button, bar.restock_button]
        bad = [b.text() for b in targets
               if b.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly]
        assert not bad, "⚠ 字を出しているボタン: %s" % bad
        # ★説明は今までどおり（⚠ 字が出ない以上、ここが唯一の手がかり）
        for b in targets:
            assert (b.toolTip() or "").strip(), "⚠⚠ 「%s」に説明が無い" % b.text()
    finally:
        win.close()


def test_勇者メモの欄は字を出したまま(app):
    """★右画面ではないので、依頼者の指示（アイコンだけ）の対象外。"""
    from PySide6.QtCore import Qt

    win = _main(app)
    try:
        for b in (win.map_window.memos._detail, win.map_window.memos.council_button):
            assert b.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly, b.text()
    finally:
        win.close()

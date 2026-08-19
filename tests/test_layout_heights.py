"""下段（ログ・出会った敵）の高さ（RX-0050）。

## ⚠⚠ 何が起きていたか

依頼者:

  > ログ・モンスター画面を極力ログとモンスターがたくさん表示されるように
  > 直したので、画面の配置を各サブ画面の高さを見直しして

★2つ、**高さを黙って余らせる／黙って切る**ところがあった。

### 1. 整列が余りを捨てていた

`_compute_four_pane` は下段を **220px で頭打ち**にしていた。
⚠ 左右（地図・RetroUX）はゲーム画面の高さに合わせて伸びるのに、下段だけ伸びない。

### 2. 上段の高さが決め打ちで、札が切れていた

`TOP_MAX = 88`（★下段が 216px しかなかった頃の値）。

## ⚠⚠ 2026-08-15: **私の測り方が2つ間違っていた**

★依頼者の画面を撮って分かった。

### ⚠ (a) 画面の大きさを取り違えていた

  1920x1200 を **150% 表示**で使っている。★アプリから見える論理の作業領域は
  **1280x752**（⚠ 1920x1152 ではない）。

  ★そのため「余りを全部ログへ」の効きめは、依頼者の画面では**ほぼ 0**:

      作業領域 1280x752 / FCEUX 528x507
      → 余り 219px（⚠ 直す前の頭打ち 220px と同じ）

  ⚠ 「6行 → 19行」と報告したのは、**存在しない画面**での値だった。
  ★広い画面では効くが、依頼者には効かない。

### ⚠ (b) 札の高さを画面外（offscreen）で測っていた

  画面外では札は 64px。⚠ **実機ではもっと大きい**。
  ★上限 `int(227 × 0.35) = 79px` がそれを締め出し、
    **実機では札が切れたまま**だった（耐性の行が半分）。

  → ★上限は「ログの最低分を残せるところまで」に変えた。
    ⚠ 227px あれば札とログの最低（72px）は**両方入る**。
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from retroux.core import layout  # noqa: E402

#: ⚠ **依頼者の画面ではない**。★横に広い画面の例（余りが大きく出る）
WIDE_AREA = (0, 0, 1920, 1152)
WIDE_EMU = (774, 752)

#: ★★ **依頼者の画面（2026-08-15 に実測）** ★★
#:   1920x1200 を 150% 表示。⚠ アプリから見える論理の作業領域はこちら。
USER_AREA = (0, 0, 1280, 752)
#: ★FCEUX の実寸（論理）
USER_EMU = (528, 507)


# --- 1. 整列: 余りを全部ログへ -------------------------------------------

def _room(area, emu, margin=8, gap=10):
    return area[3] - margin * 2 - emu[1] - gap


def test_下段は余った高さを使う():
    """★広い画面では、これが効く（⚠ 依頼者の画面では効かない）。

    ⚠ 2026-08-18 から `LOG_MAX_HEIGHT` で頭を打つ。
      ★超えたぶんは地図と RetroUX へ回る（`test_縦に長い画面では…`）。
    """
    got = layout.compute_standard(WIDE_AREA, WIDE_EMU)
    room = _room(WIDE_AREA, WIDE_EMU)
    want = min(room, layout.LOG_MAX_HEIGHT)
    assert got["log"].height == want, (
        f"★余り {room} / 上限 {layout.LOG_MAX_HEIGHT} なのに"
        f" {got['log'].height}（⚠ 直す前の頭打ちは 220px）")
    # ⚠ 直す前（220px 固定）より広いこと
    assert got["log"].height > layout.LOG_DEFAULT_HEIGHT, got["log"].height


def test_依頼者の画面では余りがほとんど無い():
    """⚠⚠ **効きめを正しく言うための検査**（2026-08-15）。

    ★依頼者の画面（論理 1280x752 / FCEUX 528x507）では、
      余りは 219px しかない。⚠ 直す前の頭打ち 220px と**ほぼ同じ**。

    ★つまり「余りを全部ログへ」は、**依頼者には効かない**。
    ⚠ 「6行 → 19行」と報告したのは、**存在しない画面**での値だった。
    """
    got = layout.compute_standard(USER_AREA, USER_EMU)
    room = _room(USER_AREA, USER_EMU)
    assert got["log"].height == room, got["log"].height
    assert abs(room - layout.LOG_DEFAULT_HEIGHT) <= 2, (
        f"★余り {room}px と旧上限 {layout.LOG_DEFAULT_HEIGHT}px が"
        "離れている（⚠ この検査の前提が崩れた）")


def test_下段が画面からはみ出さない():
    """⚠ 余りを全部使うので、**足し算が合っているか**を必ず見る。"""
    for area, emu in ((WIDE_AREA, WIDE_EMU), (USER_AREA, USER_EMU)):
        got = layout.compute_standard(area, emu)
        bottom = got["log"].y + got["log"].height
        assert bottom <= area[1] + area[3] - 8, (area, bottom)


def test_設定で高さを書いたらそれで頭を打つ():
    """★好みで小さくしたい人のために、設定は効かせる。"""
    cfg = layout.load_default()
    cfg = {**cfg, "windows": {**(cfg.get("windows") or {}),
                              "log": {"height": 200}}}
    got = layout.compute_standard(WIDE_AREA, WIDE_EMU, cfg)
    assert got["log"].height == 200, got["log"].height


def test_同梱の設定は下段の高さを書かない():
    """⚠⚠ ★ここを書くと、また余らせる。

    `default_layout.yaml` に `windows.log.height` を足すと、
    ★上の「余りを全部使う」が**その値で頭打ち**になる。
    """
    cfg = layout.load_default()
    log_spec = (cfg.get("windows") or {}).get("log") or {}
    assert "height" not in log_spec, (
        "★同梱の設定が下段の高さを固定している（⚠ 余りを使えなくなる）")


def test_狭い画面では4区画にしない():
    """⚠ 余りを全部使う変更で、**潰れた下段**を作らないこと。"""
    narrow = (0, 0, 1280, 900)
    got = layout.compute_standard(narrow, (774, 752))
    # ★入らないので従来配置（`log` を返さない）
    assert "log" not in got, got.keys()


# --- 2. 下段の中身: 札を切らない / 残りは全部ログへ ------------------------

pytest.importorskip("PySide6", reason="PySide6 が無い環境")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _log_window(app, cards: int, card_height: int = 64):
    """★出会った敵に見立てた札を `cards` 枚入れた下段を作る。

    ⚠⚠ **高さは引数で固定する**（2026-08-15）。
      ★実機のフォントと画面外（offscreen）のフォントは高さが違う。
        実測: 画面外では 64px。⚠ 実機ではそれより大きく、
        **札が切れたまま**だった（★依頼者の画面を撮って判明）。
      → ★仕組みを試すときは、フォントに依存しない固定値を使う。
    """
    from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

    from retroux.ui.log_window import LogWindow

    top = QWidget()
    box = QVBoxLayout(top)
    box.setContentsMargins(0, 0, 0, 0)
    for _ in range(max(1, cards)):
        # ★1枚の札は「絵＋4行」。⚠ 高さだけ本物に寄せる
        label = QLabel("敵\nHP 46 攻 58 守 2\n特徴 …\n耐性 …")
        label.setFixedHeight(card_height if cards else 26)
        box.addWidget(label)
    win = LogWindow(top=top,
                    panels=[("System Log", QPlainTextEdit())])
    win.show()
    app.processEvents()
    return win


def _measure(win, app, w, h):
    from PySide6.QtWidgets import QPlainTextEdit

    win.resize(w, h)
    app.processEvents()
    top = win.top_area
    body = win.splitter().widget(1)
    edit = body if isinstance(body, QPlainTextEdit) else \
        body.findChild(QPlainTextEdit)
    line = edit.fontMetrics().lineSpacing()
    return {
        "need": top.widget().sizeHint().height(),
        "top": top.height(),
        "log": body.height(),
        "rows": edit.viewport().height() // line,
    }


@pytest.mark.parametrize("size", [(1264, 216), (1904, 374), (1904, 600)])
def test_札を切らない(app, size):
    """★★★ ⚠⚠ **ここが切れていた** ★★★

    スプリッタは高さが足りないとき、上段を**下限まで潰す**。
    ★下限が `TOP_MIN`（60px）の決め打ちだったので、64px 要る札が
    **4px 切れていた**（実測 / 依頼者の画面）。
    ⚠ スクロールバーは出るが、遊んでいる人は「そういう表示」と読む。

    ★★ ⚠⚠ **ただ大きさを変えるだけでは、この検査は効かない** ★★
      ⚠ 一度そう書いて、歯止めを外しても**緑のままだった**（2026-08-14）。
        `setSizes()` の初期値がたまたま足りていたため。
      → ★**わざとログ側へ全部寄せて**、上段を下限まで潰してから測る。
        これで「下限が中身に足りているか」だけを見ることになる。
    """
    win = _log_window(app, cards=1)
    try:
        win.resize(*size)
        app.processEvents()
        # ⚠ 上段を潰しにいく（★利用者がスプリッタを一番上へドラッグした状態）
        win.splitter().setSizes([1, 10 ** 5])
        app.processEvents()
        got = _measure(win, app, *size)
        assert got["top"] >= got["need"], (
            f"⚠ 札が {got['need'] - got['top']}px 切れている: {got}")
    finally:
        win.close()


def test_窓を高くしたぶんはログへ行く(app):
    """★上段が一緒に太ってログを押し出さないこと（⚠ 割合で頭を打つ）。"""
    win = _log_window(app, cards=1)
    try:
        small = _measure(win, app, 1904, 220)
        large = _measure(win, app, 1904, 600)
        grew = large["log"] - small["log"]
        assert grew >= (600 - 220) * 0.9, (
            f"★増えた 380px のうち、ログへ行ったのは {grew}px だけ")
        # ⚠ 行数でも見る（★px だけだと font 次第で意味が変わる）
        assert large["rows"] > small["rows"] * 2, (small["rows"], large["rows"])
    finally:
        win.close()


def test_上段は下段の半分を超えない(app):
    """⚠ 札がいくら高くても、ログを潰させない。

    ★★ ⚠⚠ **2026-08-15: 「3分の1」をやめた** ★★
      実機の画面を撮ったら、⚠ **札が切れたまま**だった。
      ★227px の窓で上限 `int(227 × 0.35) = 79px` が、
        入るはずの札（約90px）を締め出していた。
      ⚠ 227px あれば札とログの最低（72px）は**両方入る**。
      → ★上限は「ログの最低分を残せるところまで」＋「半分は超えない」。
    """
    win = _log_window(app, cards=6)          # ★わざと高い中身
    try:
        got = _measure(win, app, 1904, 600)
        assert got["top"] <= 600 // 2 + 2, got
        assert got["rows"] >= 20, got
    finally:
        win.close()


def test_広い画面での実測値を固定する(app):
    """★広い画面で整列すると下段は 374px。System Log が何行入るか。

    ⚠ **依頼者の画面ではない**（★あちらは 219px / 8 行）。
    """
    std = layout.compute_standard(WIDE_AREA, WIDE_EMU)
    win = _log_window(app, cards=1)
    try:
        got = _measure(win, app, std["log"].width, std["log"].height)
        assert got["rows"] >= 15, f"★{got['rows']} 行しか出ていない: {got}"
    finally:
        win.close()

# --- ★★ ⚠⚠ 実機の画面を撮って見つかった（2026-08-15）------------------

#: ★依頼者の実測（論理画素）。⚠ 物理は 1904x341（1920x1200 の 150% 表示）
USER_LOG_H = 227
#: ⚠ 実機で札が要る高さ。★画面外で測った 64px より大きい
REAL_CARD = 90


def test_割合で頭を打たない(app):
    """★★★ ⚠⚠ **実機で札が切れたままだった** ★★★

    依頼者の画面を撮って分かった:

        ログの窓 227px / スプリッタ [66, 109] → 敵の枠は 66px
        ⚠ 上限 = int(227 × 0.35) = **79px**
        ★札が要るのはそれより大きい → **切れる**

    ⚠ 227px あれば、札（約90px）とログの最低（72px）は**両方入る**。
    ★「35%」という**それらしい数字**が、入るはずのものを締め出していた。

    ⚠⚠ **私の測り方も間違っていた。**
      「札が要るのは 64px」は画面外で測った値で、★実機とは違う。
    """
    from retroux.ui.log_window import SYSTEM_LOG_MIN

    win = _log_window(app, cards=1, card_height=REAL_CARD)
    try:
        got = _measure(win, app, 1269, USER_LOG_H)
        assert got["need"] >= REAL_CARD, got
        assert got["top"] >= got["need"], (
            f"⚠ 札が {got['need'] - got['top']}px 切れている: {got}")
        # ★ログも潰さない（⚠ 札を優先しすぎない）
        assert got["log"] >= SYSTEM_LOG_MIN, got
    finally:
        win.close()


def test_保存済みの配分が札を切っていたら配り直す(app):
    """⚠⚠ **下限を上げるだけでは足りない**（2026-08-15）。

    `window_state` が `setSizes([66, 109])` で先に配っていると、
    ★あとから `setMinimumHeight` を上げても**配分は 66 のまま**。
    ⚠ 実機ではこれで札が切れていた。
    """
    from retroux.ui.log_window import SYSTEM_LOG_MIN

    win = _log_window(app, cards=1, card_height=REAL_CARD)
    try:
        win.resize(1269, USER_LOG_H)
        app.processEvents()
        # ⚠ 保存済みの配分を、札より小さい値で当てる
        win.splitter().setSizes([40, USER_LOG_H - 40])
        app.processEvents()
        win._fit_top()
        app.processEvents()
        top = win.top_area
        need = top.widget().sizeHint().height()
        assert top.height() >= need, (
            f"★配り直していない: {win.splitter().sizes()} / 要 {need}")
        assert win.splitter().sizes()[1] >= SYSTEM_LOG_MIN, win.splitter().sizes()
    finally:
        win.close()


def test_札が大きすぎればログの最低は守る(app):
    """⚠ 札を優先しすぎて、ログが読めなくなってはいけない。"""
    from retroux.ui.log_window import SYSTEM_LOG_MIN

    win = _log_window(app, cards=1, card_height=1000)   # ★ありえない高さ
    try:
        got = _measure(win, app, 1269, USER_LOG_H)
        assert got["log"] >= SYSTEM_LOG_MIN, got
        assert got["top"] <= USER_LOG_H // 2 + 2, got
    finally:
        win.close()

# --- ★★ 想定している画面（2026-08-18 / 依頼者の指示）------------------
#
#   > 設定ファイルを1920x1080(1920x1200タスクバー）想定でなおしてちょうだい
#
# ⚠⚠ **アプリが見るのは論理画素**。★1920x1200 を 150% で使うと 1280x752。
#   ここでは「1920x1080 の画面」を素直に論理値として扱う。

#: ★1920x1080 からタスクバー（48px）を引いた作業領域
REF_AREA = (0, 0, 1920, 1032)
#: ★FCEUX の実寸（⚠ 1280x960 を渡しても内部倍率で丸められる）
REF_EMU = (784, 731)


def test_想定画面での配置を固定する():
    """★1920x1080 で整列したときの形（⚠ 変わったら気づく）。"""
    got = layout.compute_standard(REF_AREA, REF_EMU)
    assert set(got) == {"map", "emulator", "main", "log"}, got.keys()
    # ★下段は敵の札（約90px）＋ ログ 10 行以上が入る
    assert 240 <= got["log"].height <= layout.LOG_MAX_HEIGHT, got["log"].height
    # ★左右は同じ高さ・ほぼ同じ幅
    assert got["map"].height == got["main"].height
    assert abs(got["map"].width - got["main"].width) <= 1
    # ⚠ はみ出さない
    assert got["log"].y + got["log"].height <= REF_AREA[3] - 8
    assert got["map"].y + got["map"].height <= got["log"].y


def test_縦に長い画面では余りを地図へ回す():
    """⚠⚠ **余りを全部ログへ回すと、下段が画面の半分を占める**。

    ★1920x1440 では余りが 600px を超える。⚠ ログに 600px は要らない。
      → ★`LOG_MAX_HEIGHT` で頭を打ち、超えたぶんは地図と RetroUX へ。
    """
    tall = (0, 0, 1920, 1392)
    got = layout.compute_standard(tall, REF_EMU)
    assert got["log"].height == layout.LOG_MAX_HEIGHT, got["log"].height
    # ★左右はゲーム画面より高くなる（⚠ 余りが回っている）
    assert got["map"].height > REF_EMU[1], got["map"].height
    # ⚠ 足し算が合っている
    assert (got["map"].height + 10 + got["log"].height
            == tall[3] - 16), got


def test_上限は依頼者の画面では効かない():
    """★歯止めが、いま見えている画面の挙動を変えていないこと。

    ⚠ 「直したら別の所が変わった」を防ぐ。
    """
    for area, emu in ((REF_AREA, REF_EMU), (USER_AREA, USER_EMU)):
        got = layout.compute_standard(area, emu)
        room = _room(area, emu)
        assert got["log"].height == room, (
            f"⚠ 上限が効いてしまっている: {area} → {got['log'].height} / 余り {room}")


def test_設定に4区画で使わない値だと書いてある():
    """⚠ 書いてある値が効くと思わせない（★実際に混乱の元だった）。

    ★`map.width` などは**従来の2段配置でだけ**効く。
    """
    body = (PROJECT_ROOT / "retroux" / "config"
            / "default_layout.yaml").read_text(encoding="utf-8")
    assert "4区画では使いません" in body, (
        "★どの値がどちらで使われるかが書かれていない")
    assert "windows.log` は**わざと書いていません**" in body or         "わざと書いていません" in body, "★log を書かない理由が無い"

"""右の窓は**勝手に大きさを変えない**（2026-08-11 / 依頼者の報告）。

    > 右画面がたまに伸びて表示される場合がある。
    > そのときに全体の画面のバランスが変わるので目がチカチカしてみづらい

## ⚠⚠ 何が起きていたか（実測）

1. **戦闘のたびに往復していた。**
   `_render()`（0.2 秒ごと）が `_trim_blank_bottom()` を呼び、窓を
   「いまの中身ぴったり」へ縮めていました。敵札は1体 36px 積み上がるので、
   戦闘の出入りで窓の高さが 386 ⇄ 455 と動いていました。

2. **さらに、1回おきに潰れていた。**
   `split.setMaximumHeight(split.sizes()[0] + ch)` が「**いま割り当てられて
   いる**敵情報の高さ」を上限にしていたため、畳んだ高さが上限になり、
   次の回はもっと縮んだ値が返る（★堂々巡り）。実測 284 → 453 → 284、
   最後は敵情報が **0px** に潰れていました。

## ★ここで固定する契約

  1. 敵が 0〜8 体のどこでも、**窓の最小の高さが変わらない**
     （★変わると Qt が窓を押し広げます＝「たまに伸びる」の正体）
  2. 戦闘の出入りで **窓の高さが変わらない**
  3. ★敵情報の段は**削除済み**（2026-08-11 / 依頼者）。中身で高さが
     変わる段はもうありません。

⚠ 経緯の詳しい記録は `docs/history/ui-changes.md`。
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

pytest.importorskip("PySide6")

#: ★依頼者の 470 戦の実測（4体以下が 93% / 3体以下が 75%）
COMMON_BATTLE = 3
MOST_ENEMIES = 8


@pytest.fixture(scope="module", autouse=True)
def _app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.main_window import MainWindow
    from retroux.ui.view_model import ViewModel

    tmp = pathlib.Path(tempfile.mkdtemp())
    db = Database(tmp / "t.sqlite3")
    db.register_rom("H", "テストROM", "JP", mapper=2)
    (tmp / "events.jsonl").write_text("", encoding="utf-8")
    rec = Recorder(db, "H", tmp / "events.jsonl", tmp / "command.json")
    vm = ViewModel(rec, db, "H", {1: "スライム"})
    vm._mission_path = tmp / "mission.yaml"
    win = MainWindow(vm, interval_ms=10 ** 6, log_path=tmp / "r.log")
    win.resize(534, 900)
    win.show()
    yield win
    win.close()


def _render(win, count: int) -> None:
    """敵 `count` 体の場面を1回描く（★`_render` を通す）。"""
    from PySide6.QtWidgets import QApplication

    from retroux.core.bridge.state_reader import Enemy, GameState, Member
    from retroux.ui.view_model import UiState

    party = [Member(index=i, name=n, level=14, hp=65, max_hp=65)
             for i, n in enumerate(("あかり", "あかね", "あおい"))]
    enemies = [Enemy(index=i, id=1, name="だいまどうAB", hp=20, hp_start=25)
               for i in range(count)]
    win._render(UiState(in_battle=bool(enemies),
                        game=GameState(in_battle=bool(enemies),
                                       enemies=enemies, party=party)))
    QApplication.processEvents()


def test_敵の数で窓の最小の高さが変わらない(window):
    """★★ ここが変わると、Qt が**窓のほうを**押し広げます。"""
    _render(window, 0)
    least = window.minimumSizeHint().height()
    for count in (1, COMMON_BATTLE, 4, 6, MOST_ENEMIES):
        _render(window, count)
        assert window.minimumSizeHint().height() == least, (
            f"⚠ 敵 {count} 体で最小の高さが {least} -> "
            f"{window.minimumSizeHint().height()} に変わりました")


def test_戦闘の出入りで窓の高さが変わらない(window):
    """★★★ 依頼者の報告そのもの。⚠ 詰めたあとでも動かないこと。"""
    _render(window, 0)
    # ★整列と同じことをする（★ここだけは意図して縮める）
    window._trim_blank_bottom()
    _render(window, 0)
    fixed = window.height()

    for count in (1, COMMON_BATTLE, 4, MOST_ENEMIES, COMMON_BATTLE, 0):
        _render(window, count)
        assert window.height() == fixed, (
            f"⚠ 敵 {count} 体で窓の高さが {fixed} -> {window.height()} "
            "に変わりました（★これが「たまに伸びる」）")


def test_敵情報の段はもう無い(window):
    """★★ 2026-08-11: 敵情報の段を削除しました（依頼者の指示）。

    > 敵情報は、もはや用済みの資料だから不要だね。このロジック自体いらない

    ★これでこの画面には「中身で高さが変わる段」がありません。
    ⚠ 敵の記録（図鑑・遭遇・戦闘ログ）は別経路なので残っています。
    """
    _render(window, MOST_ENEMIES)
    for gone in ("_enemies", "_enemy_scroll", "_split"):
        assert not hasattr(window, gone), f"⚠ {gone} が残っています"


def test_整列後の後始末は次のイベントループで走る(window):
    """★★ RX-0062: 「標準レイアウトに戻す」で本体だけ右へはみ出していた正体。

    ⚠⚠ `reset_layout` は Win32(`SetWindowPos`)で OS 窓を並べる。★Qt の
      `geometry` がそれを取り込むのは**次のイベントループ**で、同じ呼び出しの
      中では `self.width()` が**古い幅のまま**（実測: 整列で 546 にしたのに
      823 を返す）。⚠ そこで `_trim_blank_bottom()` が
      `self.resize(self.width(), …)` を呼ぶと、★古い 823 を Qt 側から
      再適用して整列した 546 を潰す（地図は trim 対象外なので 546 のまま）。

    ★契約: 整列直後は後始末を**同じコール内で走らせない**。イベントループが
      Qt の幾何を同期してから、余白詰めと保存をする。
    """
    from PySide6.QtWidgets import QApplication

    calls: list[str] = []
    window._trim_blank_bottom = lambda: calls.append("trim")
    window.save_window_state = lambda *a, **k: (calls.append("save"), True)[1]

    window._on_reset_layout()
    assert calls == [], (
        "⚠ 整列直後に同じコール内で後始末しています"
        "（★古い幅を Qt 側から再適用して整列幅を潰す）")

    QApplication.processEvents()
    assert "trim" in calls and "save" in calls, (
        "⚠ 後始末（余白詰め・保存）が走っていません")


def test_描くたびに窓を縮めない():
    """★`_trim_blank_bottom` は**並べ直したときだけ**（2026-08-11）。

    ⚠ `_render`（0.2 秒ごと）から呼ぶと、戦闘のたびに窓の縁が動きます。
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "retroux" / "ui" / "main_window.py").read_text(encoding="utf-8")
    body = source.split("def _render(self, state: UiState)", 1)[1]
    body = body.split("\n    def ", 1)[0]
    assert "_trim_blank_bottom" not in body, (
        "⚠⚠ `_render` から窓を縮めています（★戦闘のたびに高さが変わります）")
    # ★並べ直し・復元では呼ぶこと（そちらは意図した1回）
    assert source.count("self._trim_blank_bottom()") >= 2

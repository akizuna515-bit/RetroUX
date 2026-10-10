"""別ウィンドウが**本当に独立している**こと（RX-0103 / 2026-08-23）。

⚠⚠ **親を渡した `QWidget` は、既定では親の中に描かれる子部品になります。**

  `Ctrl+K`（キーバインド設定）だけ `setWindowFlag(Qt.WindowType.Window, True)`
  が抜けており、★本体の窓（364px 幅）の**中身の上に、720×620 の画面が
  重なって切れた状態**で出ていました（依頼者「画面が壊れてる」）。

  ⚠ これは RX-0102 でキーが**効くようになって初めて見えた**不具合です。
    誰も開けなかったので、壊れていることに気づけませんでした。

★ここは **実際に親を渡して作り**、`isWindow()` を見ます。
  ⚠ 「ソースに `setWindowFlag` と書いてあるか」だけの検査にはしません
    （書いてあっても呼ばれない道があり得ます）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                          # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


#: 親を渡しても独立していなければならない窓。
#  ★増えたらここに足すこと。⚠ 足し忘れても他の検査は緑のままなので、
#    下の `test_見落としが無いか` が「窓なのに一覧に無い」を拾う。
WINDOWS = [
    ("retroux.ui.keybinding_window", "KeybindingWindow"),
    ("retroux.ui.mantan_settings_window", "MantanSettingsWindow"),
    ("retroux.ui.admin_window", "AdminWindow"),      # ★管理画面（RX-0171）
]


@pytest.mark.parametrize("module_name,class_name", WINDOWS,
                         ids=[c for _m, c in WINDOWS])
def test_親を渡しても独立ウィンドウになる(app, module_name, class_name):
    """★★ **これが要**。⚠ 親の中に描かれると「画面が壊れた」ように見える。"""
    import importlib

    module = importlib.import_module(module_name)
    parent = QWidget()
    parent.resize(364, 453)          # ★実機の本体はこのくらい（狭い）

    window = getattr(module, class_name)(parent)

    assert window.isWindow(), (
        f"⚠ {class_name} が親の中に描かれます。"
        "★setWindowFlag(Qt.WindowType.Window, True) を付けてください")


def test_見落としが無いか():
    """⚠ 一覧に足し忘れた窓を拾う。

    ★`retroux/ui/*_window.py` にある `*Window` クラスは、
      上の一覧か「別の場所で確かめている」のどちらかであること。
      ⚠ 静かに増えると、また誰も見ていない窓ができる。
    """
    import pathlib
    import re

    ui = pathlib.Path(__file__).resolve().parents[1] / "retroux" / "ui"
    #: ★別の場所で確かめている窓（重複して作らない）
    checked_elsewhere = {
        "LogWindow", "MonsterBookWindow", "TacticsProfileWindow",
        "StrategyDetailWindow", "MapWindow", "BattleReviewWindow",
    }
    #: ★本体の窓。⚠ そもそも親を持たないので、ここの話ではない
    not_a_child = {"MainWindow"}
    listed_extra = not_a_child
    listed = {c for _m, c in WINDOWS} | checked_elsewhere | listed_extra

    missing = []
    for path in sorted(ui.rglob("*window*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"^class (\w*Window)\(", source, re.M):
            if name not in listed:
                missing.append(f"{path.name}:{name}")
    assert not missing, (
        "⚠ 独立しているか誰も見ていない窓があります: " + ", ".join(missing))


# --- ★題名の帯が画面の外に出ないこと（RX-0105 / 2026-08-23）--------------

def test_画面の真ん中に置かれる(app):
    """⚠ 置き場所を決めないと、Qt は**親を基準に**置く。

    ★本体の窓が画面の上端にあると、子の窓は上へはみ出し、
      **題名の帯（閉じるボタンのある帯）が掴めなくなる**
      （依頼者「ウィンドウツールバーが表示されていない」）。
    """
    from PySide6.QtGui import QGuiApplication

    from retroux.ui.keybinding_window import KeybindingWindow

    parent = QWidget()
    parent.move(0, 0)
    parent.resize(1283, 416)              # ★実測の「既定で開いた」本体

    window = KeybindingWindow(parent)

    area = QGuiApplication.primaryScreen().availableGeometry()
    assert window.y() >= area.y(), "★題名の帯が画面の上へはみ出している"
    assert window.x() >= area.x()
    # ★真ん中に寄っている（左右の余りが同じくらい）
    left = window.x() - area.x()
    right = area.x() + area.width() - (window.x() + window.width())
    assert abs(left - right) <= 2, (left, right)

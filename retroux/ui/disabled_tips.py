"""押せないボタンにも「なぜ押せないか」を出す（RX-0171 / BP-35 / 2026-10-06）。

⚠⚠ **Qt は押せない部品（`setEnabled(False)`）にマウスの出来事を届けません。**
  ★だから `setToolTip` を入れてあっても、押せない間は**出ません**。
  ⚠ ところが「なぜ押せないのか」を知りたいのは、まさに押せないときです。

→ ★**入れ物**が代わりに受け取り、その場所にある押せない子の説明を出します（⚠ `childAt` は押せない子も返す）。

★DQ3 の `dq3/ui/icon_button.py` の `watch_disabled` と同じ 20 行の写しです。
  ⚠ DQ2 の配布 ZIP は `dq3/` を入れないので import できない。⚠ 共通化は今回しない（依頼者 2026-10-06）。
  ★今は管理画面の中だけで使います。
"""
from __future__ import annotations


def watch_disabled(container) -> None:
    """★`container` の中の押せない子に、ツールチップ（= 押せない理由）を出す。"""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QToolTip

    class _Filter(QObject):
        def eventFilter(self, obj, event):      # noqa: N802 - ★Qt の名前
            if event.type() == QEvent.Type.ToolTip:
                child = obj.childAt(event.pos())
                if child is not None and not child.isEnabled():
                    tip = (child.toolTip() or "").strip()
                    if tip:
                        QToolTip.showText(event.globalPos(), tip, obj)
                        return True
            return False

    # ⚠⚠ **親を `container` にします。** ★これが見張りを生かし続けます
    #   （⚠ 親を付けずに作ると、その場で回収されて黙って効かなくなる / DQ3 の壊す実験で確かめた）。
    container.installEventFilter(_Filter(container))

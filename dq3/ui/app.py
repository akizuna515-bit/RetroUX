"""DQ3 の画面を出す（RX3-0019 / 2026-08-29）。

★DQ2 の `retroux/gui.py` と同じ作法にします。
⚠ Qt の import は**実際に画面を出すときだけ**（検査に Qt を要求しないため）。

使い方:
    PYTHONUTF8=1 python -m dq3.ui.app
    PYTHONUTF8=1 python -m dq3.ui.app --no-map --interval 500

⚠⚠ **DQ3 は dev-only です。** 公開しません（`RX3-0011`）。
"""

from __future__ import annotations

import argparse
import sys

from .view_model import Dq3ViewModel


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="RetroUX DQ3 の画面（開発中）")
    ap.add_argument("--state", help="⚠ Lua が書く state.json（★既定は work/state.json）")
    ap.add_argument("--knowledge", help="★勇者が得たことの置き場")
    ap.add_argument("--interval", type=int, default=500,
                    help="見直す間隔 ms（★既定 500。DQ2 と同じ）")
    ap.add_argument("--memo-limit", type=int, default=3,
                    help="勇者メモの表示件数（★指示書 §7 の既定は 3）")
    ap.add_argument("--no-map", action="store_true",
                    help="⚠ 地図の窓を開かない")
    ap.add_argument("--check", action="store_true",
                    help="★画面を出さずに、読めるかだけ見る")
    return ap


def _use_fast_tooltips(app) -> None:
    """★説明が出るまでの待ちを短くする（RX3-0329 / 2026-09-21 依頼者「ツールチップはだしてほしい」）。

    ⚠⚠ 既定は **700ms** です。★アイコンだけのボタンでは、これが「出ない」と見えます。
    ★DQ2 側（`retroux/gui.py`）が同じことを 250ms でやっているので、⚠ 値も揃えます。
    """
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class _FastTooltipStyle(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: N802
            if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
                return 250                      # ★既定 ~700ms → 250ms
            return super().styleHint(hint, option, widget, returnData)

    app.setStyle(_FastTooltipStyle(app.style()))


def _show_tooltips_when_inactive(app) -> object:
    """★選んでいない窓でも、ボタンの説明を出す（RX3-0345 / 2026-09-21 依頼者）。

    ⚠⚠ Qt は既定で、**選ばれていない窓のツールチップを出しません**。
    → ★RetroUX は窓が何枚も並び、⚠ ふだん選ばれているのは **FCEUX** なので、
      説明が 1 つも出ませんでした（★依頼者「そこの窓がアクティブでないと効かない」）。

    ★直し方は `WA_AlwaysShowToolTips` ですが、⚠⚠ **立てる先はボタンではなく窓**です
    （★Qt の文書: "it must be set on the window"）。⚠ ボタンに立てても効きません。

    ⚠ 窓は何枚もあり、これからも増えるので、★**出てきた窓に自動で立てます**
      （⚠ 窓ごとに書き足す形にしない / 本 WI の Acceptance）。

    戻り値: ★入れた見張り（⚠ 捨てられないように呼ぶ側が持つ）。
    """
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QWidget

    attr = Qt.WidgetAttribute.WA_AlwaysShowToolTips

    def mark(obj) -> None:
        # ⚠ `isWindow()` が本物の窓（★子の部品に立てても意味が無い）
        if isinstance(obj, QWidget) and obj.isWindow():
            obj.setAttribute(attr, True)

    class _AlwaysShowToolTips(QObject):
        def eventFilter(self, obj, event):  # noqa: N802  ★Qt の名前
            # ⚠ ここは全部の出来事が通ります。★型を先に見て、すぐ抜けます
            if event.type() == QEvent.Type.Show:
                mark(obj)
            return False

    watcher = _AlwaysShowToolTips(app)
    app.installEventFilter(watcher)
    # ★もう出ている窓にも立てる（⚠ 見張りを入れる前に作られた窓）
    for w in app.topLevelWidgets():
        mark(w)
    return watcher


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    vm = Dq3ViewModel(state_path=args.state, knowledge_path=args.knowledge)

    if args.check:
        # ★Qt を使わずに、材料が読めるかだけ確かめる
        state = vm.state()
        print("state.json   :", vm.state_path)
        print("  frame      :", state.frame)
        print("  戦闘中     :", state.in_battle)
        print("  パーティ   :", vm.party_names() or "⚠ 届いていません")
        print("勇者メモ     :", len(vm.memos), "件")
        print("訪れた地点   :", len(vm.known_locations()), "件")
        if not vm.memos:
            print("⚠ メモがまだありません（★RX3-0016 が貯め始めてから増えます）")
        return 0

    # ⚠ ここで初めて Qt を触る
    from PySide6.QtWidgets import QApplication

    from .main_window import Dq3MainWindow

    app = QApplication(sys.argv[:1])
    # ★説明を早く出す（RX3-0329 / ⚠ 既定は 700ms で「出ない」と見える）。
    #   ★DQ2 側（`retroux/gui.py`）と同じ 250ms に揃えます。
    _use_fast_tooltips(app)
    # ★選んでいない窓でも説明を出す（RX3-0345 / ⚠ ふだん選ばれているのは FCEUX）
    app._retroux_tooltip_watcher = _show_tooltips_when_inactive(app)
    window = Dq3MainWindow(vm, interval_ms=args.interval,
                           memo_limit=args.memo_limit,
                           show_map=not args.no_map)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

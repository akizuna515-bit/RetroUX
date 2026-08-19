"""画面下段の窓（2026-08-09 / 依頼者の指示「案1」）。

    ┌──────────┬──────────────┬──────────┐
    │  地図    │    FCEUX     │  RetroUX │
    ├──────────┴──────────────┴──────────┤
    │  ★ここ: 戦うモンスター + ログ      │
    └────────────────────────────────────┘

## ★★ 中身は `MainWindow` が作ったものをそのまま置きます ★★

  ⚠ パネルを作り直すと、更新のコード（`_refresh_*`）を全部書き直すことに
    なります。★`MainWindow._build_*_panel()` が返した widget を
    **親だけ差し替えて**ここへ置きます。更新経路は変わりません。

## ⚠ 閉じかたについて

  ⚠⚠ **利用者がこの窓を閉じても、本体は止めません。**
    ★閉じたら「下段を出す」で戻せます（`MainWindow` 側のボタン）。
    ⚠ 逆に本体を閉じたときは、この窓も一緒に閉じます
      （残ると閉じ方が分からなくなります）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QScrollArea, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

#: 上段（出会った敵）の高さ（px）。★下段 216px をタブと分け合うので固定
#: ⚠ 中身はこれより高くなることがあります。★そのときは縦にはみ出させず、
#:   横スクロールで見せます（縦に伸ばすとタブが潰れるため）。
TOP_HEIGHT = 132

#: ★上段（出会った敵）の最低高さ（px / 2026-08-10）。絵＋名前が見える。
TOP_MIN = 60
#: ★上段の上限。★これ以上はスクロールにして、下段（ログ）へ高さを回す。
#:   ⚠ 下段 216px を上段と分け合うので、上段を欲張らない（ログを 6 行残す）。
#:   ★★ 2026-08-11: 敵札を横並びにしたので上段は1枚ぶんで足りる。★依頼者の
#:     「モンスターをもう1行分狭く／ログを1行分広く」に合わせて **88** へ下げ、
#:     余った高さは System Log へ回す。
TOP_MAX = 88
#: ★System Log の最低高さ（px）。★整列で畳まれないための下限。
#:   ⚠ 下段 216px を上段と分け合うので、どちらも最低は控えめにする。
SYSTEM_LOG_MIN = 72

#: ⚠⚠ **もう使いません**（2026-08-15 / RX-0050 の直し）。
#:
#: ★割合で頭を打つと、実機で**札が切れたまま**でした:
#:
#:     ログの窓 227px → 上限 int(227 × 0.35) = 79px
#:     ⚠ 実機で札が要る高さはそれより大きい → 切れる
#:
#: ★227px あれば札とログの最低は**両方入る**。割合という「それらしい数字」が、
#:   入るはずのものを締め出していました。
#: → ★上限は「**ログの最低分を残せるところまで**」（`_fit_top` を参照）。
#:
#: ⚠ 名前は残します（★外して import が壊れるより、経緯を残すほうがよい）。
TOP_SHARE = 0.35

#: ★スプリッタの取っ手の太さ（px）。⚠ 高さの計算で引き忘れると1〜2px ずれる。
_HANDLE = 6

from .battle_monsters import BattleMonsterStrip

#: ★窓の題。⚠ `align_windows` がこの前方一致で窓を探します
TITLE = "ログ — RetroUX"


class LogWindow(QWidget):
    """戦うモンスターの帯と、ログ類をまとめた下段の窓。"""

    def __init__(self, panels=None, top=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠ 図鑑や地図と同じく**フォーカスを奪わない**。
        #   奪うとゲームを操作できなくなります。
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(1264, 216)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 6)
        root.setSpacing(4)

        # ★★ 上段（2026-08-09 / 依頼者の指示）★★
        #
        #   > 出会った敵タブが私がログウィンドウの上画面で出してほしい画面だった
        #
        #   ★`top` を渡すとそれを上段にします（＝「出会った敵」のパネル）。
        #   ⚠ 渡さないときだけ、簡易の帯（`BattleMonsterStrip`）を出します。
        #     ★帯は絵と名前だけなので、情報量では「出会った敵」に負けます。
        # ★★ 2026-08-10: 上段（出会った敵）と System Log を**縦スプリッタ**で
        #   分ける（依頼者の報告「整列で片方が消える」への対処）★★
        #
        #   ⚠⚠ 下段は 216px しかなく、詳細な敵カード（約130px）と System Log
        #     （約96px）の**両方は入りません**（合計 226px 超）。上限＋最低で
        #     どちらかを守ると、もう片方が潰れる**シーソー**になっていました。
        #   ★スプリッタなら:
        #     ・両方に最低高さを与え、`setChildrenCollapsible(False)` で
        #       どちらも 0 にならない
        #     ・整列で窓が縮んでも**比率で再配分**（両方が見える）
        #     ・利用者がドラッグで好みの比率にでき、window_state に保存される
        self.strip = None
        self._vsplit = None
        if top is not None:
            # ⚠ 「出会った敵」は札が横に並ぶので、素で置くと最小幅が 1456px に
            #   なる（実測）。★横スクロールに包み、最小幅を下げる。
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            # ⚠ 縦に切れると何の敵か分からない。★要るときスクロールで見せる。
            area.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            area.setWidget(top)
            area.setMinimumWidth(1)
            # ★上段の最低高さ（絵＋名前が見える）。⚠ これ未満には縮まない
            area.setMinimumHeight(TOP_MIN)
            # ★★ 高さは**中身に合わせる**（2026-08-14 / RX-0050）★★
            #   ⚠⚠ ここは長らく `TOP_MAX`（88px）の**決め打ち**だった。
            #     ★下段が 216px しかなかった頃の値。⚠ 窓を高くしても
            #       上段は 88px のまま、札が 88px を超えると**黙って切れる**。
            #   ★`_fit_top()` が中身の高さで下限と上限を動かす。
            area.setMaximumHeight(TOP_MAX)
            self.top_area = area
            # ★中身が変わったら測り直す（⚠ 戦闘のたびに札の高さは変わる）
            top.installEventFilter(self)

            self._vsplit = QSplitter(Qt.Orientation.Vertical)
            self._vsplit.setChildrenCollapsible(False)   # ★どちらも 0 にしない
            self._vsplit.addWidget(area)
            root.addWidget(self._vsplit, stretch=1)
        else:
            self.strip = BattleMonsterStrip()
            root.addWidget(self.strip)

        # ★★ 下: ログ類は**タブ**（2026-08-09）★★
        #
        #   ⚠⚠ 縦に積むと入りません。下段に回せる高さは **216px** が上限で
        #     （作業領域 736px − FCEUX 510px − 隙間）、帯 72px を引いた
        #     残り 144px に4パネルを積むと1つ 36px です。★実測でも
        #     縦積みの最小高さは 489px あり、まるで足りませんでした。
        #
        #   ⚠ タブなので**同時には見えません**。戦闘ログと System Log を
        #     見比べたいときは不便です。★そのぶん、1つを読める高さで出せます。
        # ★★ 2026-08-09: 中身が1つになったので**タブをやめました** ★★
        #   戦闘ログは System Log へ書き出し、図鑑は右の画面へ移りました。
        #   ⚠ タブ1枚だけのタブは、見出しの帯（約28px）を無駄に取ります。
        #   ★2つ以上渡されたときだけタブにします（戻せるように残します）。
        self._tabs = None
        self._panels: list = []
        self.set_panels(panels or [])

    def set_panels(self, panels) -> None:
        """`MainWindow` が作ったパネルを置く。★作り直しません。

        `panels` は `[(見出し, widget), ...]`。⚠ 見出しが無い形（widget だけ）
        でも受けます（★呼び出し側を一度に直さなくてよいように）。
        """
        items = []
        for item in panels:
            if isinstance(item, tuple):
                items.append(item)
            else:
                items.append(("", item))
        self._panels = items
        root = self.layout()
        # ★下段の中身（1つなら widget、2つ以上ならタブ）を作る
        if len(items) == 1:
            bottom = items[0][1]
            bottom.setMinimumSize(1, SYSTEM_LOG_MIN)
        else:
            self._tabs = QTabWidget()
            self._tabs.setDocumentMode(True)
            # ⚠ タブの最小は選択中の中身で決まる。★明示的に下げる。
            self._tabs.setMinimumSize(1, SYSTEM_LOG_MIN)
            for title, widget in items:
                self._tabs.addTab(widget, title or "―")
            bottom = self._tabs

        # ★★ 上段があるなら**スプリッタへ**（2026-08-10）。無ければ従来どおり ★★
        if self._vsplit is not None:
            self._vsplit.addWidget(bottom)
            self._vsplit.setStretchFactor(0, 0)   # 上段: 内容ぶん
            self._vsplit.setStretchFactor(1, 1)   # 下段: 伸びる
            # ★初期の比率（上段は控えめ / ログを広めに）。★2026-08-11: ログを
            #   1行ぶん広げる（依頼者）。⚠ 起動時に window_state が保存済み比率で
            #   上書きする（あれば）＝ 一度ドラッグすれば好みが残る。
            # ★2026-08-14: 上段は**中身が要る高さ**（`_fit_top`）から始める。
            #   ⚠ 決め打ちの 88 で始めると、札が高い日に切れたまま出る。
            self._vsplit.setSizes([self._fit_top() or TOP_MAX, 320])
        else:
            root.addWidget(bottom, stretch=1)

    # --- ★上段の高さ（2026-08-14 / RX-0050）-----------------------------

    def _fit_top(self) -> "int | None":
        """上段（出会った敵）の高さを、**中身が要るぶん**に合わせる。

        戻り値は決めた下限（★上段が無ければ None）。

        ★決め方:

            下限 = 札が要る高さ（`sizeHint`）  ← ⚠ **切らせない**
            上限 = ログの最低分を残せる範囲     ← ★ログも潰させない

        ⚠⚠ **下限を `TOP_MIN`（60px）のままにしてはいけない。**
          ★スプリッタは高さが足りないとき、上段を**下限まで潰す**。

        ## ★★ ⚠⚠ **2026-08-15: 割合で頭を打つのをやめた** ★★
        ##
        ##   実機の画面を撮って分かった。⚠ **札が切れたままだった。**
        ##
        ##     ログの窓 227px / スプリッタ [66, 109] → 敵の枠は 66px
        ##     ⚠ 上限 = int(227 × 0.35) = **79px**
        ##     ★実機で札が要る高さは 79px より大きい → **切れる**
        ##
        ##   ⚠ 227px あれば、札（約90px）とログの最低（72px）は**両方入る**。
        ##     ★割合という「それらしい数字」が、入るはずのものを締め出していた。
        ##
        ##   → ★上限は **「ログの最低分を残せるところまで」**。
        ##     ⚠ 半分は超えない（★札が伸び続けても読める行を残す）。
        ##
        ## ⚠⚠ **私の測り方が間違っていた。**
        ##   「札が要るのは 64px」は**画面外（offscreen）で測った値**。
        ##   ★実機とフォントの高さが違う。offscreen の数値で上限を決めない。
        """
        area = getattr(self, "top_area", None)
        if area is None or area.widget() is None:
            return None
        need = area.widget().sizeHint().height()
        # ⚠ 窓がまだ出ていないと `height()` は当てにならない。★既定で測る
        room = self.height() if self.height() > TOP_MIN else 216
        cap = max(TOP_MIN, min(room // 2, room - SYSTEM_LOG_MIN - _HANDLE))
        got = max(TOP_MIN, min(need, cap))
        if area.minimumHeight() != got:
            area.setMinimumHeight(got)
        if area.maximumHeight() != max(got, cap):
            area.setMaximumHeight(max(got, cap))
        self._respect_top(got)
        return got

    def _respect_top(self, want: int) -> None:
        """⚠ すでに配り終えたスプリッタが下限を割っていたら、配り直す。

        ★★ **下限を上げるだけでは足りない**（2026-08-15）★★
          `window_state` が `setSizes([66, 109])` で先に配っていると、
          ⚠ あとから `setMinimumHeight` を上げても**配分は 66 のまま**。
          ★実機ではこれで札が切れていた。

        ⚠ 呼び戻りに注意（`setSizes` → resize → `_fit_top` → ここ）。
          ★同じ値なら何もしないので、そこで止まる。
        """
        split = self._vsplit
        if split is None:
            return
        sizes = split.sizes()
        if len(sizes) != 2 or sizes[0] >= want:
            return
        total = sizes[0] + sizes[1]
        below = max(SYSTEM_LOG_MIN, total - want)
        split.setSizes([total - below, below])

    def eventFilter(self, obj, event):        # noqa: N802 (Qt の名前)
        """★中身の並びが変わったら測り直す。

        ⚠ 戦闘のたびに札の数と文字数が変わるので、作ったときの1回では足りない。
        """
        from PySide6.QtCore import QEvent

        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            area = getattr(self, "top_area", None)
            if area is not None and obj is area.widget():
                self._fit_top()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:     # noqa: N802 (Qt の名前)
        super().resizeEvent(event)
        # ★窓を高くしたら、上段も中身ぶんまで伸ばしてよい（⚠ 割合で頭を打つ）
        self._fit_top()

    def splitter(self):
        """★上段とログの境界（2026-08-10）。⚠ 無ければ None（許容される）。"""
        return self._vsplit

    def current_tab(self) -> int:
        """⚠ タブが無いとき（中身が1つ）は 0。"""
        return self._tabs.currentIndex() if self._tabs is not None else 0

    def set_current_tab(self, index: int) -> None:
        if self._tabs is None:
            return
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def set_monsters(self, cards) -> None:
        """帯を更新する。⚠ 空でも黙らず「戦闘していません」と出ます。

        ★上段に「出会った敵」を置いた場合は帯が居ないので何もしません
          （あちらは `MainWindow` が自分で更新しています）。
        """
        if self.strip is not None:
            self.strip.set_cards(cards)

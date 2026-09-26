"""モンスターの帯（DQ3 / RX3-0036 / 2026-09-01）。

## ⚠⚠ なぜ DQ2 の部品を**そのまま使わない**のか

★指示書 §23 は「DQ2 の実装を最大限再利用」と言っています。
⚠ ですが `RX3-0011` の決まりで **`retroux/` は変更しません**。
  ★同じことが `PartyPanel` でも起きていて（2026-08-29）、
  そのときも **DQ3 側に作り直しました**（`dq3/ui/party_panel.py`）。

  ⚠ 一度 `retroux/ui/battle_monsters.py` に手を入れて、
    `test_retrouxを変更していない` が**赤くなって気づきました**。

★なので **枠組みは継承して使い、札だけ作り直します**。

```text
retroux.ui.battle_monsters.BattleMonsterStrip   ★横スクロール・空の出し方
        ↑ 継承
Dq3MonsterStrip                                 ★札を差し替える ＋ 高さに入るだけ段を積む
```

## ★出す形（指示書 §14 / ★RX3-0276 で詰めた）

```text
┌──────────────────────────────┐
│ [ 絵  ] スライム                │  ★名前は絵の右の頭（太字）
│ [80x64] HP 8   守 5   G 2     │  ★性能は 3 列を**詰めて**並べる（⚠ 札の幅いっぱいに離さない）
│         MP 0   速 4           │
│         攻 9   EXP 4          │
│         耐性 眠× 死△ …        │  ★1 行（⚠ 越えたら「…」/ 全文はヒント）
│         特技 …                │
└──────────────────────────────┘
```

⚠⚠ RX3-0276（2026-09-15 依頼者「モンスター表示は、空きが目立つ」→ 案 1）:
  札 392 の中で、性能の 2 列が札の両端へ離れて間と右が大きく空いていた（★列を伸びしろ 1 で足していた）。
  → ★札を 272 × 100 に詰め、**帯の高さに入るだけ段を積む**（★下段の窓なら 2 段 = 敵 4 群が 2 列に収まる）。
  ⚠ 1 段に並べると、帯は窓の高さいっぱい（216）なのに札の中身は 110 ほど → 札の下半分が空いた（★撮って気づいた）。

⚠⚠ **匹数は出しません**（§15）。★表示の単位は「種」です。
⚠ 高さは中身で変えません（§17）。★入らなければ横スクロール。
"""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dq3.ui import theme as _T
from retroux.ui.battle_monsters import BattleMonsterStrip

#: ★Qt の「上限なし」（⚠ `QWIDGETSIZE_MAX`。PySide6 は書き出していない）
NO_MAX_H = (1 << 24) - 1

#: ★絵の枠（px）。⚠ **いちばん大きい敵に合わせる**（DQ3 は 10 列 × 8 行）
#:
#:   ⚠ 64 角にしていたら、★大きい敵が右端で切れていました（絵で気づいた）。
ART_W, ART_H = 80, 64
#: ★札 1 枚の幅（⚠ 絵 ＋ 名前・性能・耐性・特技の欄）
#:   ★RX3-0187（2026-09-12 依頼者「今の倍の横幅で良い（DQ2準拠）耐性や特技がもっと表示できそう」）: 196 → 392。
#:   ★RX3-0276（2026-09-15 依頼者「空きが目立つ」→ 案 1）: 392 → 272（★小さく固定 / 帯が高ければ段を積む）。
CARD_WIDTH = 272
#: ★札 1 枚の高さ（RX3-0276）。★帯に入る段の数で決まる（⚠ 中身では変えない）
CARD_H = 100
#: ★札の高さの下限（⚠ これを割ると名前・性能 3 行・耐性・特技が入らない）。
#:
#:   ⚠⚠ 2026-09-15 依頼者「モンスターは、横１列ではなく、横２列で表示できないか？スクロールせずに４つ表示できそう」:
#:     ★依頼者のログ窓は高さ 216（= 帯 206）で保存されていた。⚠ 札を 100 に固定していたので 2 段に 214 要り、**1 段**になった。
#:     → ★段に入るよう札を少し縮める（206 なら 96 × 2 段）。⚠ ここを割るなら段を増やさない。
MIN_CARD_H = 92
#: ★名前・性能・耐性・特技の欄の幅（★絵の右 / ⚠ 札の余白と間を引いたもの）
INFO_W = CARD_WIDTH - ART_W - 16
#: ★耐性・特技の行数の上限（⚠ 越えたら「…」/ 全文はヒント）
EXTRA_LINES = 1
#: ★帯の横の余白（★札 1 列を切らない帯の幅の下限 = 札 ＋ これ / `battle_window`）
STRIP_SIDE = 16
#: ★既定で見せる列の数（★DQ3 の敵は 4 群まで → 2 段 × 2 列で全部見える / `battle_window`）
DEFAULT_COLUMNS = 2
#: ★★ 帯の**下限**（⚠ ここを割ると札が切れる）。
#:
#:   ⚠⚠ 2026-09-01 実機: 88 では**性能が 3 つ切れ、名前も出ませんでした**
#:     （★7 行を縦に並べると絵より高くなる）。
#:
#:   ## ⚠ 2026-09-01（RX3-0037）: 「固定」から「下限」へ変えました
#:
#:     ⚠⚠ ただし**中身では変えません**。★変わるのは
#:       「人がつまんだとき」と「起動時の配分」だけです（`docs/design/dq3-ui-v0.md`）。
#:   ## ★2026-09-02（RX3-0060）: 耐性・特技の 1 行を足したので 104 → 120（⚠ RESIZE_STEP の 4 の倍数にする）
#:   ## ★2026-09-15（RX3-0276）: 札 1 段 ＋ 余白 = 112（★札の高さは固定 / 高ければ段を積む）
STRIP_HEIGHT = CARD_H + 12
#: ★性能を何列に並べるか（⚠ 1 列だと縦に伸びて札からはみ出す / ★RX3-0276: 2 → 3 で 3 行に）
STAT_COLUMNS = 3
#: ★帯の上下の余白（⚠ 基底の `_row` の上下の余白と同じ）
STRIP_PAD_V = 8


def art_box(strip_h: int = STRIP_HEIGHT) -> tuple[int, int]:
    """★絵の枠（`(幅, 高さ)`）。⚠ RX3-0276 から**帯の高さでは伸ばしません**。

    ## ⚠ なぜ伸ばさなくなったか（RX3-0276 / 2026-09-15）

      ★ログ画面を左右に分けたので、⚠ 足りないのは**幅**です。
      ⚠ 枠を高さで伸ばすと、縦横の比（80:64）を保つために**札の幅も伸び**、ログの幅を削ります。
      → ★枠は 10x8 タイルの大物（80x64）に合わせたまま。★小さい敵は枠の中で整数倍（2 倍）になる。
    """
    return (ART_W, ART_H)


def rows_for(strip_h: int, spacing: int = 6) -> int:
    """★帯の高さに札が何段入るか（RX3-0276 / ⚠ 1 段は必ず）。

    ★段の数は**札の下限**（`MIN_CARD_H`）で決めます。⚠ 札の高さで決めると、
      依頼者の窓（帯 206）で 2 段に 8px 足りず **1 段**になりました（★4 体が横スクロールの向こうへ）。
    """
    usable = max(0, max(STRIP_HEIGHT, int(strip_h)) - STRIP_PAD_V)   # ⚠ 下限より低くても縮めない
    return max(1, (usable + spacing) // (MIN_CARD_H + spacing))


def card_size(strip_h: int = STRIP_HEIGHT, spacing: int = 6) -> tuple[int, int]:
    """★札 1 枚の大きさ（RX3-0276）。★幅はいつも同じ / 高さは**段に入る分**（⚠ `CARD_H` を越えない）。"""
    rows = rows_for(strip_h, spacing)
    usable = max(0, max(STRIP_HEIGHT, int(strip_h)) - STRIP_PAD_V) - (rows - 1) * spacing
    height = max(MIN_CARD_H, min(CARD_H, usable // rows)) if rows else CARD_H
    return (CARD_WIDTH, height)


def stat_columns(stats, columns: int = STAT_COLUMNS) -> list:
    """★性能を**縦に読む** N 列へ分ける。

    ```text
    HP 8    守 5    G 2
    MP 0    速 4
    攻 9    EXP 4
    ```

    ⚠ 1 列だと 7 行になり、★絵（8 行ぶん）より高くなって札からはみ出します。
    """
    got = list(stats or ())
    if not got:
        return []
    columns = max(1, int(columns))
    rows = -(-len(got) // columns)          # ★切り上げ
    out = []
    for i in range(columns):
        part = got[i * rows:(i + 1) * rows]
        if part:
            out.append(chr(10).join("%s %s" % (k, v) for k, v in part))
    return out


def wrap_lines(text: str, metrics, width: int, max_lines: int = EXTRA_LINES) -> str:
    """★幅に合わせて**語の区切り**で折り返し、`max_lines` を越えたら最後の行を「…」で切る（RX3-0276）。

    ⚠ QLabel の折り返しは行数を決められず、日本語の途中で折れない（★札からはみ出す）。
    ★区切りは空白（「眠×」「死△」の途中で折らない）。⚠ 1 語が幅を越えるときだけ字で折る。
    """
    text = (text or "").strip()
    if not text or width <= 0:
        return text
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        cand = word if not cur else cur + " " + word
        if metrics.horizontalAdvance(cand) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:                      # ⚠ 1 語が幅を越える（★字で折る）
            if metrics.horizontalAdvance(cur + ch) > width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        rest = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [metrics.elidedText(rest, Qt.TextElideMode.ElideRight, width)]
    return chr(10).join(lines)


@dataclasses.dataclass(frozen=True)
class Dq3MonsterCard:
    """札 1 枚（★種ごと。⚠ 匹数は持ちません）。"""

    monster_id: int
    name: str
    art: object = None       #: `pathlib.Path` か None（★無ければ「絵なし」）
    stats: tuple = ()        #: ★`(見出し, 値)` の並び
    resist: str = ""         #: ★耐性のあるものだけ（`眠× 死△` / RX3-0060）
    special: str = ""        #: ★特技（ふつうの攻撃以外の行動）
    legend: str = ""         #: ★記号の凡例（ヒント）
    tip: str = ""            #: ★札全体のヒント（耐性・特技の全文 / RX3-0278）。⚠ 空なら耐性・特技の行 ＋ 凡例


class _Card(QFrame):
    """★`[絵][名前・性能・耐性・特技]` の左右並び（RX3-0276）。"""

    def __init__(self, card: Dq3MonsterCard,
                 strip_h: int = STRIP_HEIGHT) -> None:
        super().__init__()
        art_w, art_h = art_box(strip_h)
        self.setFixedSize(*card_size(strip_h))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # ⚠ 2026-09-07（RX3-0112）依頼者「モンスター表示領域も白地にしたい」
        self.setStyleSheet(
            "QFrame { background:%s; border:1px solid %s;"
            " border-radius:3px; }" % (_T.CARD, _T.BORDER))
        side = QHBoxLayout(self)
        side.setContentsMargins(3, 3, 3, 3)
        side.setSpacing(6)

        art = QLabel()
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setFixedSize(art_w, art_h)
        pix = QPixmap(str(card.art)) if card.art is not None else QPixmap()
        if pix.isNull():
            # ⚠ 無いものは描かない（★DQ2 と同じ決まり）
            art.setText("絵なし")
            art.setStyleSheet("color:%s; font-size:10px; background:%s;"
                              " border:1px solid %s;"
                              % (_T.MUTED, _T.PAPER, _T.BORDER))
        else:
            # ★枠に収まる**整数倍**（⚠ 縦だけで決めると横がはみ出す）
            scale = max(1, min(art_h // max(pix.height(), 1),
                               art_w // max(pix.width(), 1)))
            art.setPixmap(pix.scaled(pix.width() * scale, pix.height() * scale,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation))
            # ⚠⚠ **絵だけは暗い枠のまま**（★PNG の背景が黒でベタ塗りのため）。
            #   ⚠ 白い札に直接載せると黒い四角が浮きます（`dq3/ui/theme.py` の註）。
            art.setStyleSheet("background:%s; border:1px solid %s;"
                              % (_T.ART_BACK, _T.ART_BORDER))
        side.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(0)
        # ★名前は絵の右の頭（RX3-0276 / ⚠ 下に 1 行使っていた）。⚠ 入らなければ「…」
        text = QLabel()
        text.setStyleSheet("color:%s; font-size:11px; font-weight:bold; border:0;" % _T.INK)
        text.setText(text.fontMetrics().elidedText(card.name, Qt.TextElideMode.ElideRight, INFO_W))
        text.setToolTip(card.name)          # ⚠ 下で札全体のヒントがあれば、そちらに差し替える
        info.addWidget(text)
        # ★性能は 3 列を**詰めて**（RX3-0276 / ⚠ 伸びしろ 1 で足すと札の両端へ離れて空く）
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(8)
        for part in stat_columns(card.stats, STAT_COLUMNS):
            col = QLabel(part)
            col.setAlignment(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignTop)
            col.setStyleSheet("color:%s; font-size:10px; border:0;" % _T.STAT)
            cols.addWidget(col)
        cols.addStretch(1)
        info.addLayout(cols)

        # ★耐性・特技（RX3-0060 / DQ2 の札を参考に）。★RX3-0276: それぞれ 1 行（絵の右の欄の幅）
        #   ⚠ 入らない分は「…」（全文はヒント）
        parts = [p for p in (("耐性 " + card.resist) if card.resist else "",
                             ("特技 " + card.special) if card.special else "") if p]
        if not parts and card.stats:
            parts = ["耐性・特技 なし"]
        tip = card.tip or (chr(10).join(parts) + chr(10) + card.legend).strip()
        # ★RX3-0278: 札の**どこに**マウスを置いても全文が出るように（⚠ 字の上だけだと帯のヒントが出ていた）
        #   ★中の字にはヒントを付けない（⚠ 付けると字ごとに中身が違う / 付けなければ札のヒントが出る）
        if tip:
            self.setToolTip(card.name + chr(10) + tip)
            text.setToolTip("")
        for part in parts:
            extra = QLabel()
            extra.setAlignment(Qt.AlignmentFlag.AlignLeft)
            extra.setStyleSheet("color:%s; font-size:10px; border:0;" % _T.ACCENT)
            extra.setText(wrap_lines(part, extra.fontMetrics(), INFO_W))
            info.addWidget(extra)
        info.addStretch(1)
        side.addLayout(info, 1)


#: ⚠ 高さの変化をこの粒度で丸めて見る（★1px 動くたびに作り直さない）
RESIZE_STEP = 4


class Dq3MonsterStrip(BattleMonsterStrip):
    """★DQ2 の帯を継承して、⚠ 札だけ差し替える（★RX3-0276: 高さに入るだけ段を積む）。

    ## ⚠⚠ 高さの決まり（RX3-0037 / 2026-09-01）

    ```text
    ⚠ してはいけない   札が増えたら帯が高くなる（★窓が動く / §17）
    ★してよい         人が仕切りをつまんだ／起動時の配分
    ```

    ★下限は `STRIP_HEIGHT`（⚠ ここを割ると札が切れます）。
    ⚠ 上限は掛けません（★掛けると 2026-09-01 の `setMaximumHeight(88)` の
      再来になります）。

    ## ★段の積み方（RX3-0276）

    ```text
    帯の高さ → 何段入るか（rows_for）→ 上から下へ詰めて、あふれたら次の列
    例  高さ 216 = 2 段   敵 3 種 → 1 列目 A・B / 2 列目 C
    ```
    ⚠ 段は帯の高さで決まる（★中身では決めない）。★入らなければ横スクロール（§5）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # ⚠⚠ **基底が `setFixedHeight(72)` を掛けています**（DQ2 の帯の高さ）。
        #   ★`setMinimumHeight` を上げるだけでは、⚠ **上限 72 のまま**で
        #     「下限 104 / 上限 72」という壊れた状態になります
        #     （2026-09-01 の `setMaximumHeight(88)` と同じ形の罠）。
        #   ⚠ `retroux/` は変えられない（`RX3-0011`）ので、ここで外します。
        # ⚠⚠ 基底（`retroux`）が `background:#14161a` を掛けています。
        #   ★`retroux/` は変えられない（`RX3-0011`）ので、ここで上書きします。
        #   ⚠ 2026-09-07（RX3-0112）依頼者「モンスター表示領域も白地にしたい」
        self.setStyleSheet("background:%s;" % _T.PAPER)
        self.setMaximumHeight(NO_MAX_H)
        # ⚠⚠ 中身を窓いっぱいに縮められると、★横スクロールが効きません
        #   （2026-09-01 実測: 8 枚で 1622 要るのに 700 に押し込まれた）。
        #   → ★幅は `_fit_width()` が決めます。
        self.setWidgetResizable(False)
        # ★下限だけ（⚠ もとは `setFixedHeight`。伸びしろがログにしか無かった）
        self.setMinimumHeight(STRIP_HEIGHT)
        #: ★いま札を組んだときの帯の高さ（⚠ 変わったときだけ組み直す）
        self._built_h = STRIP_HEIGHT

    def _strip_h(self) -> int:
        """★札に使える高さ（⚠ 下限は割らない / `RESIZE_STEP` で丸める）。"""
        got = max(STRIP_HEIGHT, int(self.height()))
        return got - got % RESIZE_STEP

    def rows(self) -> int:
        """★いまの高さで何段に並べるか（RX3-0276）。"""
        return rows_for(self._built_h, self._row.spacing())

    def columns(self) -> int:
        """★札の列の数（★段で割って切り上げ）。"""
        return -(-len(self._cards) // self.rows()) if self._cards else 0

    def card_widgets(self) -> list:
        """★並べた札（★出した順 / 検査と画面の確認用）。"""
        inner = self.widget()
        return inner.findChildren(_Card) if inner is not None else []

    def resizeEvent(self, event) -> None:
        """⚠ 高さが変わったら組み直す（★入る段の数が変わるため）。

        ⚠⚠ これは「中身で高さを変える」の**逆向き**です。
          ★高さ → 並べ方。窓は動きません（下限は `STRIP_HEIGHT` のまま）。
        """
        super().resizeEvent(event)
        self._sync_height()

    def showEvent(self, event) -> None:
        """⚠ 隠れている間の大きさ変えは `resizeEvent` が来ません（★実測）。

        ★出すときにもう一度合わせます。⚠ 無いと、起動直後に配分を当てても
          札が下限のままで出ます。
        """
        super().showEvent(event)
        self._sync_height()

    def _sync_height(self) -> None:
        """★いまの高さで札が組まれていなければ、⚠ 組み直す。"""
        if self._strip_h() != self._built_h:
            self._rebuild()

    def set_cards(self, cards) -> None:
        """並べ直す。⚠ 空なら「戦闘していません」（★黙って消さない）。"""
        cards = list(cards or [])
        if cards == self._cards and self._strip_h() == self._built_h:
            return                      # ★同じなら作り直さない（点滅を防ぐ）
        self._cards = cards
        self._rebuild()

    def _rebuild(self) -> None:
        """★いまの `_cards` と帯の高さで組み直す（★段に詰めて、あふれたら次の列）。"""
        strip_h = self._strip_h()
        self._built_h = strip_h
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if not self._cards:
            self._empty = QLabel("戦闘していません")
            self._empty.setStyleSheet("color:%s; font-size:11px;" % _T.MUTED)
            self._row.addWidget(self._empty)
            return
        rows = self.rows()
        for c in range(self.columns()):
            col = QWidget()
            stack = QVBoxLayout(col)
            stack.setContentsMargins(0, 0, 0, 0)
            stack.setSpacing(self._row.spacing())
            for card in self._cards[c * rows:(c + 1) * rows]:
                stack.addWidget(_Card(card, strip_h))
            stack.addStretch(1)
            self._row.addWidget(col, 0, Qt.AlignmentFlag.AlignTop)
        self._fit_width()

    def _fit_width(self) -> None:
        """★★ ⚠⚠ **札が全部たどり着けるようにする**（2026-09-01 / RX3-0042）。

        ## ⚠ 何が起きていたか

          `QScrollArea(widgetResizable=True)` は、中身を作り直しても
          **窓の幅のまま**にしていました（★8 枚目が見ることも触ることもできなかった）。

        ★`widgetResizable` を切り、**中身の幅を列の数から直に計算**します
        （⚠ `self._row.sizeHint()` は札を足した直後には `(12, 8)` を返した）。
        """
        inner = self.widget()
        if inner is None:
            return
        margins = self._row.contentsMargins()
        cols = self.columns()
        if cols:
            need = (margins.left() + margins.right() + cols * CARD_WIDTH
                    + max(0, cols - 1) * self._row.spacing())
        else:
            need = 0
        # ★狭いときは窓いっぱい（⚠ 背景が途切れないように）
        inner.resize(max(need, self.viewport().width()),
                     self.viewport().height())

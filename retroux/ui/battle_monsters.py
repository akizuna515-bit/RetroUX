"""いま戦っているモンスターを**横一列**で出す帯（2026-08-09 / 依頼者の指示）。

    > 下の窓の上段に戦うモンスターを表示させる
    > （横に広がる形で。たくさん出たらスクロールバーで）

## ★★ ここが守ること ★★

- **絵が無い敵を勝手に描かない。** 名前だけの札にして「絵なし」と書きます。
  ⚠ 似た敵の絵を当てると、図鑑の信頼が崩れます。
- **数を隠さない。** 8体出たら8体ぶんの幅を作り、⚠ 入らなければ
  **横スクロール**にします。★「3体まで」のような切り捨てをしません。
- **縦には伸びません。** 下段はログと分け合うので、高さは固定です。

## ⚠ 絵の大きさについて

ROM から出した絵も実機で撮った絵も小さい（NES のキャラ）ので、
★**整数倍で拡大**します。⚠ 滑らかに拡大するとドットが溶けます
（地図の `canvas.py` と同じ方針）。
"""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

#: 絵の表示の高さ（px）。★ここを変えると帯の高さも変わる
#: ⚠ 2026-08-09 に 48 -> 32。下段は 216px しかなく、ログと分け合うため
ART_HEIGHT = 32
#: 札1枚の幅（px）。⚠ 名前が長い敵（「あくまのきし」等）が折り返さない幅
CARD_WIDTH = 96
#: 帯全体の高さ（px）。★絵＋名前＋余白。下段をログと分け合うので固定
#: ⚠ 2026-08-09 に 96 -> 72
STRIP_HEIGHT = 72


@dataclasses.dataclass(frozen=True)
class MonsterCard:
    """札1枚ぶん。★`art` が None なら「絵なし」と出す（描かない）。"""

    monster_id: int
    name: str
    count: int = 1
    art: object = None
    """`pathlib.Path` か None。⚠ 読めなかったときも None にしてよい。"""


def cards_from_groups(groups, names, art_lookup) -> list:
    """`game.enemy_groups` から札を作る。⚠ 分からない敵も**落としません**。

    `names` は `{敵ID: 名前}`、`art_lookup` は `id -> パス or None`。

    ★グループが取れないとき（戦闘の入りかけ等）は空を返します。
      ⚠ 「敵が居ない」ではなく「まだ分からない」なので、
        呼ぶ側は前の表示を消さない判断もできます。
    """
    out = []
    for g in groups or ():
        # ⚠ 実物の `enemy_groups` は `id` です（`main_window.py` L1861）。
        #   ★`monster_id` も受けます（テストの作りやすさのため）。
        mid = getattr(g, "monster_id", None)
        if mid is None:
            mid = getattr(g, "id", None)
        if mid is None:
            continue
        name = getattr(g, "name", None) or names.get(mid) or f"敵 {mid:02X}"
        out.append(MonsterCard(monster_id=mid, name=str(name),
                               count=int(getattr(g, "count", 1) or 1),
                               art=art_lookup(mid)))
    return out


def cards_from_ids(ids, names, art_lookup) -> list:
    """敵IDの並びから札を作る（★`enemy_groups` が無いときの道）。

    ⚠ 同じIDが続いたら**まとめて数にします**。並び順は変えません。
    """
    out: list = []
    for mid in ids or ():
        if out and out[-1].monster_id == mid:
            last = out[-1]
            out[-1] = dataclasses.replace(last, count=last.count + 1)
            continue
        out.append(MonsterCard(monster_id=mid,
                               name=str(names.get(mid) or f"敵 {mid:02X}"),
                               count=1, art=art_lookup(mid)))
    return out


class _Card(QFrame):
    """1体ぶんの札。★絵・名前・体数。"""

    def __init__(self, card: MonsterCard) -> None:
        super().__init__()
        self.setFixedSize(CARD_WIDTH, STRIP_HEIGHT - 12)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background:#1c1f26; border:1px solid #333842;"
            " border-radius:3px; }")
        box = QVBoxLayout(self)
        box.setContentsMargins(2, 2, 2, 2)
        box.setSpacing(1)

        art = QLabel()
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setFixedHeight(ART_HEIGHT)
        pix = QPixmap(str(card.art)) if card.art is not None else QPixmap()
        if pix.isNull():
            # ⚠ 無いものは描かない。★「絵なし」と書く
            art.setText("絵なし")
            art.setStyleSheet("color:#6a7080; font-size:10px; border:0;")
        else:
            # ★整数倍で拡大する（⚠ 滑らかにしない / ドットが溶ける）
            scale = max(1, ART_HEIGHT // max(pix.height(), 1))
            art.setPixmap(pix.scaled(pix.width() * scale,
                                     pix.height() * scale,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation))
            art.setStyleSheet("border:0;")
        box.addWidget(art)

        label = card.name if card.count <= 1 else f"{card.name}×{card.count}"
        text = QLabel(label)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet("color:#d8dce4; font-size:11px; border:0;")
        box.addWidget(text)


class BattleMonsterStrip(QScrollArea):
    """戦っているモンスターの帯。★横に伸び、入らなければ横スクロール。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(STRIP_HEIGHT)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # ⚠ 縦には出さない（帯の高さは固定なので、出ても掴めない）
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("background:#14161a;")

        self._inner = QWidget()
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(6, 4, 6, 4)
        self._row.setSpacing(6)
        self._row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self._inner)

        self._empty = QLabel("戦闘していません")
        self._empty.setStyleSheet("color:#6a7080; font-size:11px;")
        self._row.addWidget(self._empty)
        self._cards: list = []

    def cards(self) -> list:
        """★いま出している札。テストと画面の確認用。"""
        return list(self._cards)

    def set_cards(self, cards) -> None:
        """並べ直す。⚠ 空なら「戦闘していません」と出す（黙って消さない）。"""
        cards = list(cards or [])
        if cards == self._cards:
            return                      # ★同じなら作り直さない（点滅を防ぐ）
        self._cards = cards
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if not cards:
            self._empty = QLabel("戦闘していません")
            self._empty.setStyleSheet("color:#6a7080; font-size:11px;")
            self._row.addWidget(self._empty)
            return
        for card in cards:
            self._row.addWidget(_Card(card))

"""行った地図を選んで見る（RX3-0024 / 2026-08-30）。

依頼者 2026-08-30:

    ボタンを押すと各 MAP 画面が出て、MAP 選択（言ったところ）と
    メモが出るようにする感じで

## ⚠⚠ いつもの窓と、なぜ分けるのか

```text
いつもの窓（map_window）  ★いま何が近くにあるか  → 現在地に追随する 48 升
この画面（map_browser）   ★どこへ行ったか        → その地図の全体
```

⚠ 全体をいつもの窓に出すと、序盤は画面のほとんどが黒で読めません
（★実機で「2 か所が浮いて割れて見える」と言われました）。
用途が違うので、⚠ **同じ窓で兼ねません**。

## ⚠⚠ 行っていない地図は一覧に出しません

★出すのは `SeenMap` に**記録がある地図だけ**（指示書 §10 / No-Spoiler）。

⚠ ROM には 243 件のエリアマップがありますが、
★そこから一覧を作ることは**しません**（行っていない所が分かってしまいます）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QVBoxLayout, QWidget)

from .map_window import MapCanvas, MapScroll
from .memo_panel import MemoPanel

#: ★一覧の幅（⚠ 名前が入る程度）
LIST_WIDTH = 150


def label_of(key: str, count: int, name: str | None = None) -> str:
    """一覧に出す 1 行。⚠ 名前が分からなければ番号のまま。

    ⚠⚠ **知らないものを「知っている風」に出さない。**
    ★`name` は `Dq3ViewModel.place_name()` が出したもの（⚠ ここで地名を決めない / RX3-0094）。
    """
    if key == "w":
        got = "世界地図"
    elif key == "a":
        got = "アレフガルド"
    elif key.startswith("L"):
        got = name or ("地図 %s" % key[1:])
    else:
        got = key
    return "%s（%d 升）" % (got, count)


def key_to_position(key: str):
    """一覧の鍵 → `position()` と同じ形。⚠ 分からなければ `None`。

    ★`MapCanvas` は `(種別, 番号, x, y)` を見るので、それに合わせます。
    """
    if key == "w":
        return (0, None)
    if key == "a":
        return (2, None)
    if key.startswith("L"):
        try:
            return (1, int(key[1:]))
        except ValueError:
            return None
    return None


class _BrowseModel:
    """★選んだ地図を、`MapCanvas` に見せるための包み。

    ⚠ `MapCanvas` は「いまどこに居るか」を聞いてくるので、
    ★**選んだ地図の真ん中**に居ることにします（⚠ 現在地の印は出ません）。
    """

    def __init__(self, view_model) -> None:
        self.vm = view_model
        self._at = None

    @property
    def seen(self):
        return self.vm.seen

    # ⚠⚠ 2026-09-07（RX3-0095）: ここを中継し忘れていて、★地図が**色ブロック**で
    #   描かれていました。`MapCanvas` は `getattr(vm, "tile_art", None)` で見るので、
    #   ⚠ 無いと**エラーも出さずに**「絵が無い」扱いになります。
    @property
    def tile_art(self):
        return self.vm.tile_art

    @property
    def tile_art_runtime(self):
        return getattr(self.vm, "tile_art_runtime", None)

    def select(self, key: str) -> bool:
        """★その地図を見る。⚠ 記録が無ければ False。"""
        where = key_to_position(key)
        cells = self.vm.seen.cells(key)
        if where is None or not cells:
            self._at = None
            return False
        # ★見た所の真ん中を「居るところ」にする（⚠ 追随ではなく全体を見る）
        xs = [x for x, _y in cells]
        ys = [y for _x, y in cells]
        self._at = (where[0], where[1],
                    (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)
        return True

    def position(self):
        return self._at

    def known_locations(self):
        # ⚠ 地点の印はここでは出さない（★地図そのものを見る画面）
        return []


class Dq3MapBrowser(QWidget):
    """★行った地図を選んで見る（別ウィンドウ）。"""

    def __init__(self, view_model, *, memo_limit: int = 6, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.setWindowTitle("地図を見る — RetroUX DQ3")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ⚠ フォーカスを奪わない（★奪うとゲームを操作できなくなる）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(720, 520)

        self.model = _BrowseModel(view_model)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        upper = QHBoxLayout()
        upper.setSpacing(6)

        self.list = QListWidget()
        self.list.setFixedWidth(LIST_WIDTH)
        self.list.currentItemChanged.connect(self._picked)
        upper.addWidget(self.list)

        # ⚠ ここは追随しない（★地図の全体を見る画面）
        self.canvas = MapCanvas(self.model, follow=False)
        # ⚠⚠ **縮めずスクロール**（RX3-0045 / 依頼者 2026-09-01）
        self.scroll = MapScroll(self.canvas)
        upper.addWidget(self.scroll, 1)
        root.addLayout(upper, 1)

        #: ⚠ 記録が 1 つも無いときの案内（★黙って空にしない）
        self.empty = QLabel("⚠ まだ行った地図がありません" + chr(10)
                            + "★歩くと、ここに増えていきます")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: palette(mid);")
        root.addWidget(self.empty)

        # ★その地図のメモ（⚠ 中身は `RX3-0016` が貯め始めてから）
        # ★選んだ地図のメモだけを出す（⚠ 全体の直近ではない）
        self.memos = MemoPanel(view_model, limit=memo_limit,
                               pick=self._memos_here)
        root.addWidget(self.memos)

        self.reload()

    # --- ★一覧 ----------------------------------------------------------

    def reload(self) -> None:
        """★行った地図を並べ直す。⚠ 記録がある地図だけ。"""
        from dq3.knowledge.locations import sort_key

        # ★数の順（L1 → L2 → … → L10）。⚠ 文字列の順だと L10 が L1 の直後に来る（RX3-0438）
        keys = sorted((k for k, m in self.vm.seen.maps.items() if m.cells), key=sort_key)
        before = self.current_key()
        self.list.blockSignals(True)
        self.list.clear()
        for key in keys:
            name = self.vm.place_name(key[1:]) if key.startswith("L") and key[1:].isdigit() else None
            item = QListWidgetItem(label_of(key, self.vm.seen.count(key), name))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty.setVisible(not keys)
        self.canvas.setVisible(bool(keys))
        if keys:
            want = before if before in keys else keys[0]
            self.list.setCurrentRow(keys.index(want))

    def current_key(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _picked(self, current, _previous=None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if self.model.select(key):
            # ⚠ 地図が変わったので、★絵を作り直させる
            self.canvas._image_for = None
            self.scroll.fit()
            self.canvas.update()
            # ★メモも、その地図のものへ入れ替える
            self.memos.refresh()

    def _memos_here(self, limit: int):
        """★いま選んでいる地図のメモ（⚠ 新しい順）。

        ⚠⚠ 選んでいないときは**全体の直近**を出します
          （★「まだありません」と出るより親切）。
        """
        at = self.model.position()
        if at is None or at[1] is None:
            return self.vm.recent_memos(limit)
        # ⚠ ここで並べ替えない（★並びは `MemoBook.newest()` の 1 本 / RX3-0118）
        return self.vm.memos.newest(limit, map_id=at[1])

    def refresh(self) -> None:
        """★定期的に呼ぶ。⚠ 一覧は増えたときだけ並べ直す。"""
        keys = [k for k, m in self.vm.seen.maps.items() if m.cells]
        if len(keys) != self.list.count():
            self.reload()
        self.memos.refresh()
        if self.isVisible():
            self.scroll.fit()
            self.canvas.update()

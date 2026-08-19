"""モンスター図鑑の別ウィンドウ（2026-07-27 / 依頼者の指定）。

> モンスター図鑑は入りきれないので、ボタン押下で別ウィンドウが開く形が良い

★**一覧＋詳細の2枚**にする。83体 × 15項目を1つの表に詰めると、
  1920×1080 でも横スクロールになって読めない。
  左で選び、右でその1体を全部見せる。

★**空欄を作らない。** 「なし」「未解読」「絵がありません」と書く。
  空欄にすると「データが壊れている」と「そういう値」の区別が付かない
  （playbook「0 と まだ分からない を混ぜない」）。

★**2つの出所を節で分ける**（GUI 本体に埋めていた頃からの決まり）:
    ROM 由来（最大HP・攻撃・守備・耐性・行動・ドロップ）… 動かない事実
    記録由来（遭遇回数・勝率・平均秒数）              … 遊ぶほど増える観測
  混ぜて並べると、利用者が**どちらが確定した値か区別できない**。
  一覧＋詳細にしたので列ではなく節で分けるが、分ける理由は同じ。

設計と根拠: `docs/design/monster-book-spec.md`
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.db.behavior import action_breakdown, format_drop, resist_label

# 耐性の並びと見出し。**memory_map のキー順に合わせる**（勝手に並べ替えない）
RESIST_LABELS = [
    ("spell_damage", "攻撃呪文"),
    ("sleep", "ラリホー"),
    ("stopspell", "マホトーン"),
    ("defeat", "ザラキ"),
    # ⚠ **ルカニは DQ2 に無い**（守備力を下げる呪文は**ルカナン**）。
    #   内部の名前 `defense_down` はそのまま（ROM の耐性のビット位置の名前）。
    ("defense_down", "ルカナン"),
    ("surround", "マヌーサ"),
]

# 絵を出す枠の大きさ。FC の敵は最大でも 96×80 程度なので、3倍に拡大して見せる
ART_W, ART_H = 288, 240


def _bold(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont()
    font.setBold(True)
    label.setFont(font)
    return label


class MonsterBookWindow(QWidget):
    """図鑑の別ウィンドウ。

    ★親を持たない独立ウィンドウにする（`Qt.Window`）。
      本体の中に埋めると、本体を縦長にしている意味が無くなる。
    """

    def __init__(self, view_model, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self._rows: list = []
        self.setWindowTitle("モンスター図鑑 — RetroUX")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1100, 720)

        # ⚠⚠ **表示のときにフォーカスを奪わない**（2026-07-27）。
        #
        #   遭遇のたびにこの窓が前に出てフォーカスを取ると、
        #   **プレイヤーがゲームを操作できなくなる**（キー入力がこちらへ来る）。
        #   起動スクリプトが整列で `SWP_NOACTIVATE` を使っているのと同じ理由。
        #   図鑑は「見るもの」で「操作するもの」ではないので、常にこれでよい。
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)

        # --- 上段: 絞り込み ---------------------------------------------
        top = QHBoxLayout()
        self._reload = QPushButton("読み込む / 更新")
        self._reload.clicked.connect(self.reload)
        top.addWidget(self._reload)

        self._known_only = QCheckBox("遭遇済みだけ")
        self._known_only.toggled.connect(self._refill_list)
        top.addWidget(self._known_only)

        top.addWidget(QLabel("検索:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("名前かID（16進）の一部")
        self._search.setMaximumWidth(240)
        self._search.textChanged.connect(self._refill_list)
        top.addWidget(self._search)

        self._summary = QLabel("-")
        self._summary.setStyleSheet("color:#8a8a8a;")
        top.addWidget(self._summary)
        top.addStretch(1)
        root.addLayout(top)

        # --- 遭遇に追従している間の帯（2026-07-27 / 依頼者の要望）---------
        #
        # > TASみたいに、モンスターに遭遇すると対象モンスターの図鑑が表示される
        #
        # ★複数種が出る戦闘があるので、**切り替えボタンを並べる**。
        #   1体目を自動で選び、他は押せば見られる。
        self._encounter_bar = QWidget()
        bar = QHBoxLayout(self._encounter_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self._encounter_label = QLabel("")
        self._encounter_label.setStyleSheet("color:#8ad1ff;")
        bar.addWidget(self._encounter_label)
        self._encounter_buttons: list[QPushButton] = []
        self._encounter_box = QHBoxLayout()
        bar.addLayout(self._encounter_box)
        bar.addStretch(1)
        self._encounter_bar.setVisible(False)
        root.addWidget(self._encounter_bar)

        # --- 本体: 一覧 | 詳細 ------------------------------------------
        split = QSplitter(Qt.Orientation.Horizontal)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selected)
        split.addWidget(self._list)

        # ★詳細はスクロールできるようにする。項目が増えても切れない
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._build_detail())
        split.addWidget(scroll)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, stretch=1)

        self.reload()

    # --- 構築 --------------------------------------------------------

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        outer = QVBoxLayout(panel)

        head = QHBoxLayout()

        # 絵の枠。★無いときは「未撮影」と書く（空けない）
        self._art = QLabel()
        self._art.setFixedSize(ART_W, ART_H)
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art.setFrameShape(QFrame.Shape.StyledPanel)
        # ★背景を黒にする（依頼者の指定 / 2026-07-29）。
        #   絵は背景が透明なので、明るいテーマだと**白地に浮いて**見える。
        #   FC の戦闘画面は黒背景なので、黒のほうが実物に近い。
        self._art.setStyleSheet(
            "color:#8a8a8a; background:#000000;"
            " border:1px solid #5a5a5a; border-radius:4px;")
        art_box = QVBoxLayout()
        art_box.addWidget(self._art)
        # ★絵の出どころを必ず書く（2026-07-29）。
        #   ROM から展開したものと実機で撮ったものが混在しうるので、
        #   **どちらを見ているのか分からない状態にしない**。
        self._art_source = QLabel("")
        self._art_source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_source.setStyleSheet("color:#8a8a8a; font-size:11px;")
        art_box.addWidget(self._art_source)
        head.addLayout(art_box)

        # 名前と数値
        right = QVBoxLayout()
        self._title = QLabel("-")
        big = QFont()
        big.setPointSize(15)
        big.setBold(True)
        self._title.setFont(big)
        right.addWidget(self._title)

        self._stats = QGridLayout()
        self._stat_labels: dict[str, QLabel] = {}
        fields = [
            ("max_hp", "最大HP"), ("attack", "攻撃"), ("defense", "守備"),
            ("agility", "素早さ"), ("exp", "経験値"), ("gold", "ゴールド"),
            ("evade", "回避"), ("wisdom", "賢さ"),
        ]
        for i, (key, caption) in enumerate(fields):
            self._stats.addWidget(QLabel(caption), i // 2, (i % 2) * 2)
            value = QLabel("-")
            value.setFont(QFont("Consolas"))
            self._stat_labels[key] = value
            self._stats.addWidget(value, i // 2, (i % 2) * 2 + 1)
        self._stats.setColumnStretch(4, 1)
        right.addLayout(self._stats)
        right.addStretch(1)
        head.addLayout(right, stretch=1)
        outer.addLayout(head)

        # --- 特徴（行動と確率）------------------------------------------
        outer.addWidget(_bold("特徴（戦う以外のコマンド）"))
        self._actions = QLabel("-")
        self._actions.setWordWrap(True)
        outer.addWidget(self._actions)
        note = QLabel(
            "★確率は ROM の行動表から計算した値です"
            "（「選び直し」は除いて正規化しています）。")
        note.setStyleSheet("color:#8a8a8a;")
        note.setWordWrap(True)
        outer.addWidget(note)

        # --- 耐性 --------------------------------------------------------
        outer.addWidget(_bold("耐性（効く確率）"))
        self._resist = QGridLayout()
        self._resist_labels: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate(RESIST_LABELS):
            self._resist.addWidget(QLabel(caption), 0, i)
            value = QLabel("-")
            value.setFont(QFont("Consolas"))
            self._resist_labels[key] = value
            self._resist.addWidget(value, 1, i)
        self._resist.setColumnStretch(len(RESIST_LABELS), 1)
        outer.addLayout(self._resist)

        # --- ドロップ ----------------------------------------------------
        outer.addWidget(_bold("ドロップ"))
        self._drop = QLabel("-")
        outer.addWidget(self._drop)

        # --- 記録 --------------------------------------------------------
        outer.addWidget(_bold("あなたの記録"))
        self._record = QLabel("-")
        self._record.setWordWrap(True)
        outer.addWidget(self._record)

        outer.addStretch(1)
        return panel

    # --- 更新 --------------------------------------------------------

    def reload(self) -> None:
        """DB を引き直す。

        ★自動では更新しない（全戦闘を走査するので 0.5 秒ごとには回せない）。
          押されたときだけ。
        """
        self._reload.setEnabled(False)
        self._reload.setText("読み込み中…")
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        try:
            self._rows = self.vm.monster_book()
        finally:
            self._reload.setEnabled(True)
            self._reload.setText("読み込む / 更新")
        self._refill_list()

    # --- 遭遇に追従する（依頼者の要望 / 2026-07-27）------------------------

    def follow_encounter(self, monster_ids: list[int]) -> bool:
        """遭遇した敵の図鑑を出す。出せたら True。

        ★1体目を自動で選び、他の種類は切り替えボタンにする。
          複数種の戦闘で「どれを見せるか」を勝手に決め切らない。

        ⚠ **絞り込みで隠れていたら外す。** 「遭遇済みだけ」を入れている状態で
          初めて会った敵に遭遇すると、一覧に居ないので選べない。
          利用者は「遭遇したのに出ない」と受け取る。
          追従は明示的な要求なので、そのときは絞り込みを解く。
        """
        ids = [i for i in dict.fromkeys(monster_ids)]      # 重複を除き順を保つ
        if not ids:
            self.clear_encounter()
            return False

        # 帯を作り直す
        self._encounter_label.setText(f"遭遇中: {len(ids)} 種")
        for button in self._encounter_buttons:
            self._encounter_box.removeWidget(button)
            button.deleteLater()
        self._encounter_buttons = []
        for mid in ids:
            button = QPushButton(f"{self.vm.monster_name(mid)}")
            button.setToolTip(f"ID 0x{mid:02X}")
            button.clicked.connect(lambda _=False, m=mid: self.show_monster(m))
            self._encounter_box.addWidget(button)
            self._encounter_buttons.append(button)
        self._encounter_bar.setVisible(True)

        return self.show_monster(ids[0])

    def set_encounter_active(self, in_battle: bool) -> None:
        """いま戦っているのか、直前の戦闘なのかを帯に書く。

        ★**帯を消さない**（2026-07-27 / 依頼者の指摘）。
          倍速だと戦闘が一瞬で終わるので、消すと読む前に消える。
          言葉だけ変えて、次の戦闘まで残す。
        """
        if not self._encounter_buttons:
            return
        n = len(self._encounter_buttons)
        if in_battle:
            self._encounter_label.setText(f"遭遇中: {n} 種")
            self._encounter_label.setStyleSheet("color:#8ad1ff;")
        else:
            self._encounter_label.setText(f"直前の戦闘: {n} 種")
            self._encounter_label.setStyleSheet("color:#8a8a8a;")

    def clear_encounter(self) -> None:
        """帯を隠す（選んでいる敵はそのまま残す）。

        ⚠ **戦闘の終わりでは呼ばない**（残すため）。
          いまは呼び出し元が無いが、図鑑を手で閉じ直すときのために残してある。
        """
        self._encounter_bar.setVisible(False)

    def show_monster(self, monster_id: int) -> bool:
        """その敵を一覧で選ぶ。隠れていたら絞り込みを外す。"""
        if not any(r.id == monster_id for r in self._rows):
            return False
        if not any(r.id == monster_id for r in self._visible_rows()):
            # ★絞り込みを解く。**信号を止めてから**まとめて直す
            #   （1つずつ直すと _refill_list が何度も走る）
            self._search.blockSignals(True)
            self._known_only.blockSignals(True)
            self._search.clear()
            self._known_only.setChecked(False)
            self._search.blockSignals(False)
            self._known_only.blockSignals(False)
            self._refill_list()

        rows = self._visible_rows()
        for i, r in enumerate(rows):
            if r.id == monster_id:
                self._list.setCurrentRow(i)
                self._list.scrollToItem(self._list.item(i))
                return True
        return False

    def _visible_rows(self) -> list:
        text = self._search.text().strip().lower()
        out = []
        for r in self._rows:
            if self._known_only.isChecked() and not r.known:
                continue
            if text and text not in r.name.lower() and text not in f"{r.id:02x}":
                continue
            out.append(r)
        return out

    def _refill_list(self) -> None:
        rows = self._visible_rows()
        known = sum(1 for r in self._rows if r.known)
        self._summary.setText(
            f"遭遇済み {known} / {len(self._rows)} 体"
            + (f"　表示 {len(rows)} 体" if len(rows) != len(self._rows) else ""))

        keep = self._list.currentRow()
        self._list.blockSignals(True)
        self._list.clear()
        for r in rows:
            item = QListWidgetItem(f"{r.id:02X}  {r.name}")
            if not r.known:
                # ★まだ会っていない敵も出す（図鑑だから）。薄くするだけ
                from PySide6.QtGui import QColor
                item.setForeground(QColor("#6a6a6a"))
            self._list.addItem(item)
        self._list.blockSignals(False)

        if rows:
            self._list.setCurrentRow(min(max(keep, 0), len(rows) - 1))
        else:
            self._show_empty()

    def _show_empty(self) -> None:
        self._title.setText("（該当なし）")
        for label in self._stat_labels.values():
            label.setText("-")
        for label in self._resist_labels.values():
            label.setText("-")
        self._actions.setText("-")
        self._drop.setText("-")
        self._record.setText("-")
        self._art.setPixmap(QPixmap())
        self._art.setText("-")
        self._art_source.setText("")

    def _on_selected(self, index: int) -> None:
        rows = self._visible_rows()
        if index < 0 or index >= len(rows):
            return
        self._render(rows[index])

    def _render(self, row) -> None:
        self._title.setText(f"{row.name}　（ID 0x{row.id:02X}）")

        for key, label in self._stat_labels.items():
            value = getattr(row, key, None)
            # ★ROM に無い敵は「-」。0 で埋めない
            label.setText("-" if value is None else str(value))

        # 耐性
        for key, label in self._resist_labels.items():
            value = (row.resist or {}).get(key) if row.resist else None
            label.setText(resist_label(value))

        # 特徴（行動）
        breakdown = action_breakdown(
            {"wisdom": row.wisdom, "actions": row.actions},
            self.vm.monster_actions, self.vm.action_rates)
        if breakdown:
            # ★1行1行動で出す。1行に詰めると読めない
            self._actions.setText("\n".join(
                f"　{name}　{pct:.1f}%" for name, pct in breakdown))
        else:
            self._actions.setText("（データがありません）")

        # ドロップ
        text = format_drop(row.drop, self.vm.items)
        # ★「落とさない」と「まだ分からない」を書き分ける。
        #   drop が無い＝ROM の表で 0＝**落とさない**（確定した事実）
        if text:
            self._drop.setText("　" + text)
        elif row.max_hp is None:
            self._drop.setText("　（この敵の ROM データがありません）")
        else:
            self._drop.setText("　なし")

        # 記録
        if not row.known:
            self._record.setText("　まだ会っていません")
        else:
            wr = ("-" if row.win_rate is None
                  else f"{row.win_rate * 100:.0f}%（{row.wins}/{row.decided}）")
            avg = ("-" if row.average_seconds is None
                   else f"{row.average_seconds:.1f}秒")
            extra = ("" if not row.unknown_results
                     else f"　※勝敗が記録されていない戦闘 {row.unknown_results} 件")
            self._record.setText(
                f"　遭遇 {row.encounters} 回　勝率 {wr}　平均 {avg}{extra}")

        self._render_art(row)

    #: 出どころの表示。★空欄にしない（どちらを見ているか分からなくなる）
    ART_SOURCE_LABEL = {
        "rom": "ROM から展開",
        "capture": "実機の画面から撮影",
    }

    def _render_art(self, row) -> None:
        """絵を出す。**無ければ「未撮影」と書く。**

        ★出どころ（ROM 展開 / 実機撮影）も必ず添える。
          どちらも `<敵ID>.png` という同じ名前なので、
          書かないと**画面から区別できない**。
        """
        path, source = self.vm.monster_art(row.id)
        if path is None:
            self._art.setPixmap(QPixmap())
            self._art.setText("絵がありません\n\n（`dq2rom monsters install`\nで ROM から入れられます）")
            self._art_source.setText("")
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self._art.setPixmap(QPixmap())
            self._art.setText(f"絵を読めません\n{path.name}")
            self._art_source.setText("")
            return
        self._art.setText("")
        self._art_source.setText(self.ART_SOURCE_LABEL.get(source, source or ""))
        # ★拡大は**なめらかにしない**。FC の絵はドットなので、
        #   補間するとぼやけて「元の絵と違うもの」になる。
        self._art.setPixmap(pix.scaled(
            ART_W, ART_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))

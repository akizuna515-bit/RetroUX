"""戦術プロフィールの設定画面（2026-07-30 / 仕様書 4章・14章）。

★★ **利用者が戦術を設計する画面。** ★★（仕様書 2.1）
  AI が勝手に賢くなるのではなく、ここで設計したものを AI が実行する。

## 形（仕様書 4.3）

  > 第1弾では、比較しやすい**マトリクス形式**を優先する。

                       ローレシア  サマルトリア  ムーンブルク
    AI操作                 ☑            ☑            ☑
    役割                 攻撃重視     バランス      回復重視
    危険時手動復帰         ☑            ☑            ☑
    ...

★項目は節（基本／回復／MP／道具／安全）で**折りたためる**（仕様書 14.2）。

## ⚠⚠ 使えない項目は消さずグレーアウト（仕様書 14.1）

  > 項目が突然出現・消失するより、無効理由が分かるほうを優先する。

2つの理由でグレーアウトする:

  1. **まだ実装していないフェーズの項目** → 「今後のフェーズで対応」
  2. **そのキャラクターには意味が無い項目** → 「回復呪文を使用できません」

⚠ 1 を出すのが大事。出さないと「設定したのに効かない」になり、
  設定画面ぜんたいが信用されなくなる。

## 未保存の変更（仕様書 14.3）

タイトルに `*` を出し、別のプロフィールへ移るときに
保存／破棄／キャンセルを聞く。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from ..core.tactics import models

#: グレーアウトした項目の理由の色
NOTE_STYLE = "color:#8a8a8a; font-size:11px;"
WARN_STYLE = "color:#e0a030; font-size:11px;"

def _phase_note(field) -> str:
    """未実装の項目に出す文。★**いつ効くのか**を書く。"""
    return f"今後のフェーズで対応（フェーズ{field.phase}）"


class _Row:
    """設定項目1つ（3人ぶんの入力欄をまとめて持つ）。"""

    def __init__(self, field, on_change) -> None:
        self.field = field
        self.widgets: dict = {}
        self.notes: dict = {}
        for cid in models.CHARACTER_IDS:
            widget, note = self._build(field, cid, on_change)
            self.widgets[cid] = widget
            self.notes[cid] = note

    @staticmethod
    def _build(field, cid, on_change):
        note = ""
        if not field.implemented:
            note = _phase_note(field)
        else:
            # ★「誰に意味が無いか」の表は `models.py` の1箇所だけ（写さない）
            note = models.not_applicable(cid, field.section, field.key) or ""

        if field.kind == "bool":
            widget = QCheckBox()
            widget.toggled.connect(lambda _v: on_change())
        elif field.kind == "int":
            widget = QSpinBox()
            widget.setRange(field.minimum if field.minimum is not None else 0,
                            field.maximum if field.maximum is not None else 999)
            widget.valueChanged.connect(lambda _v: on_change())
        else:
            widget = QComboBox()
            labels = {
                models.Role: models.ROLE_LABELS,
                models.FallbackAction: models.FALLBACK_LABELS,
                models.SpellPolicy: models.SPELL_POLICY_LABELS,
                # ★「いのちをだいじに」の守る相手（2026-08-04 / 指示書 §12）
                models.ProtectTarget: models.PROTECT_TARGET_LABELS,
            }.get(field.enum_cls, {})
            for member in field.enum_cls:
                widget.addItem(labels.get(member, member.value), member.value)
            widget.currentIndexChanged.connect(lambda _i: on_change())

        # ⚠ ここでは `setEnabled` を触らない。
        #   ★★ **編集できるかは `apply_editable` の1か所で決める。** ★★
        #     ここでも切ると2か所になり、`break_tactics.py` で
        #     「片方を壊してもテストが緑」＝どちらが効いているか
        #     分からない状態になった（実際に見つかった）。
        return widget, note

    def apply_editable(self, read_only: bool) -> None:
        """編集できるかを付け直す。

        ★★ **毎回ここで決める。** ★★
          ⚠ 実際に踏んだ不具合: 見本を1度表示すると `setEnabled(False)` のまま
            戻らず、**そのあと自分のプロフィールを開いても編集できなくなった**。
            「一度切ったら戻す処理も要る」を忘れた形。
          → 元から使えない項目（`self.notes`）と、いま見ているものが見本か、
            の2つから**毎回計算する**。
        """
        for cid, widget in self.widgets.items():
            note = self.notes.get(cid) or ""
            if note:
                widget.setEnabled(False)
                widget.setToolTip(note)
            elif read_only:
                widget.setEnabled(False)
                widget.setToolTip("見本は編集できません。[複製] してください")
            else:
                widget.setEnabled(True)
                widget.setToolTip(self.field.note or "")

    def load(self, prof) -> None:
        for cid, widget in self.widgets.items():
            value = prof.get(cid, self.field.section, self.field.key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                try:
                    widget.setValue(int(value))
                except (TypeError, ValueError):
                    widget.setValue(int(self.field.default))
            else:
                index = widget.findData(
                    value.value if hasattr(value, "value") else value)
                widget.setCurrentIndex(max(0, index))

    def store(self, prof) -> None:
        """画面の値をプロフィールへ。

        ⚠ **グレーアウトした項目は書かない。**
          書くと「設定していない未実装の項目」がプロフィールに増え、
          検証のたびに「いまは効きません」が出る（読まれない通知になる）。
        """
        for cid, widget in self.widgets.items():
            if not widget.isEnabled():
                continue
            if isinstance(widget, QCheckBox):
                prof.set(cid, self.field.section, self.field.key,
                         widget.isChecked())
            elif isinstance(widget, QSpinBox):
                prof.set(cid, self.field.section, self.field.key,
                         int(widget.value()))
            else:
                prof.set(cid, self.field.section, self.field.key,
                         widget.currentData())


class TacticsProfileWindow(QWidget):
    """戦術プロフィールの作成・編集・選択（別ウィンドウ）。"""

    #: 保存して適用できたときに出す（2026-07-31 の指示書 §9）。
    #
    # ★★ **閉じたあとの報告先が要る** ★★
    #   [OK] で窓を閉じる仕様にしたので、この窓の中に結果を書いても
    #   ⚠ **一瞬も読まれない**。呼び出し元（本体の画面）へ渡して出してもらう。
    applied = Signal(str)

    #: ★作戦そのものが切り替わったとき（2026-08-04 / 指示書 §5.2）。
    #
    # ★★ **メイン画面のリストと同期するための合図**（§19 受入条件3）★★
    #   ⚠ `applied`（[OK] で保存して閉じた）とは別物です。
    #     こちらは**リストを選んだ瞬間**に鳴り、窓は閉じません。
    strategy_changed = Signal(str)

    def __init__(self, view_model, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        self.repo = view_model.tactics
        self._profiles: list = []
        self._current = None
        self._dirty = False
        self._loading = False

        self.setWindowTitle("戦術プロフィール — RetroUX")
        self.setWindowFlag(Qt.WindowType.Window, True)
        # ★★ 画面に収める（2026-08-19 / RX-0066）★★
        #   ⚠ 依頼者「1080 に入らず、ボタンが見えない」。設定の本体（マトリクス）は
        #     `QScrollArea` でスクロールするので、★窓の高さを**作業領域に収める**
        #     ことで、下の [OK/元に戻す/閉じる] を常に画面内に保つ。
        #   ⚠ 縦に長い画面では従来どおり 800。狭い画面では縮める（縮めるだけ）。
        want_w, want_h = 1000, 800
        try:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                # ⚠ タイトルバー・枠のぶんの余白（★はみ出さないよう少し引く）
                want_w = min(want_w, avail.width() - 40)
                want_h = min(want_h, avail.height() - 80)
        except Exception:                              # noqa: BLE001
            pass
        self.resize(max(600, want_w), max(400, want_h))
        # ⚠ 図鑑・地図と同じく**フォーカスを奪わない**（奪うとゲームを操作できない）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)
        root.addLayout(self._build_header())
        root.addWidget(self._build_matrix(), stretch=1)
        root.addLayout(self._build_footer())
        self.reload()

    # --- 組み立て ---------------------------------------------------

    def _build_header(self):
        box = QVBoxLayout()

        title = QLabel("戦術プロフィール")
        bold = QFont()
        bold.setBold(True)
        title.setFont(bold)
        box.addWidget(title)

        # ★★ 指示書 §5.1「戦術設定画面の上部に、現在作戦を選択するリストを置く」
        box.addWidget(QLabel("現在の作戦"))

        row = QHBoxLayout()
        self._picker = QComboBox()
        # ⚠⚠ **2つのイベントを使い分けます**（2026-08-04 / 指示書 §5.4）
        #
        #   `currentIndexChanged` … 詳細を下に読み込むだけ。
        #       ★`reload()` の中でも鳴ります（＝人が触っていなくても鳴る）。
        #   `activated`           … **人が選んだときだけ**鳴る。
        #       ★こちらで**作戦を即時切り替え**ます。
        #
        #   ⚠ 切り替えを `currentIndexChanged` に付けると、
        #     **窓を開いただけで「作戦を変更しました」が走ります**
        #     （§5.4「初期表示時の変更イベント誤発火」そのもの）。
        self._picker.currentIndexChanged.connect(self._on_pick)
        self._picker.activated.connect(self._on_picked_by_user)
        self._picker.setToolTip(
            "選んだ瞬間に、その作戦へ切り替わります（§5.2）。\n"
            "★下の詳細を直しただけでは戦闘には反映されません。"
            "[OK（保存して使う）] を押してください。")
        row.addWidget(self._picker, stretch=2)
        for label, slot in (("新規作成", self.create_new),
                            ("複製", self.duplicate),
                            ("削除", self.delete)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        box.addLayout(row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名前"))
        self._name = QLineEdit()
        self._name.textEdited.connect(lambda _t: self._mark_dirty())
        name_row.addWidget(self._name, stretch=1)
        name_row.addWidget(QLabel("説明"))
        self._description = QLineEdit()
        self._description.textEdited.connect(lambda _t: self._mark_dirty())
        name_row.addWidget(self._description, stretch=2)
        box.addLayout(name_row)

        self._dirty_label = QLabel("")
        self._dirty_label.setStyleSheet(WARN_STYLE)
        box.addWidget(self._dirty_label)
        return box

    def _build_matrix(self):
        area = QScrollArea()
        area.setWidgetResizable(True)
        holder = QWidget()
        # ★★ 2026-08-11: **1つの表**にまとめる（依頼者「キャラ名は一度で良い」）★★
        #   以前は節ごとに箱を作り、その度にキャラ名の見出しを繰り返していた。
        #   ★キャラ名は先頭に1回だけ。節は**行の見出し**にして列をそろえる。
        grid = QGridLayout(holder)
        grid.setVerticalSpacing(3)

        self._rows: dict = {}
        chars = models.CHARACTER_IDS
        ncol = len(chars)

        # ★キャラ名の見出し（**一度だけ** / 先頭行）
        grid.addWidget(QLabel(""), 0, 0)
        for col, cid in enumerate(chars, start=1):
            head = QLabel(models.CHARACTER_LABELS[cid])
            head.setFont(self._bold())
            grid.addWidget(head, 0, col, Qt.AlignmentFlag.AlignHCenter)
            grid.setColumnStretch(col, 2)
        grid.setColumnStretch(0, 3)

        by_section: dict = {}
        for field in models.FIELDS:
            by_section.setdefault(field.section, []).append(field)

        line = 1
        for section, fields in by_section.items():
            # ★節の見出し（1行 / 全列にまたぐ）。★キャラ名は繰り返さない
            sec = QLabel(models.SECTION_LABELS.get(section, section))
            sec.setFont(self._bold())
            sec.setStyleSheet("color:#8ad1ff; margin-top:6px;")
            grid.addWidget(sec, line, 0, 1, ncol + 1)
            line += 1
            for field in fields:
                label = QLabel(field.label)
                if not field.implemented:
                    label.setStyleSheet(NOTE_STYLE)
                    label.setToolTip(_phase_note(field))
                    label.setText(f"{field.label}　[今後のフェーズ]")
                if field.note:
                    label.setToolTip((label.toolTip() + "\n" if label.toolTip()
                                      else "") + field.note)
                grid.addWidget(label, line, 0)
                row = _Row(field, self._mark_dirty)
                self._rows[(field.section, field.key)] = row
                for col, cid in enumerate(chars, start=1):
                    grid.addWidget(row.widgets[cid], line, col)
                line += 1

        note = QLabel(
            "★★ **AI は、ここで設計した戦術をそのまま実行します。**"
            "AI が勝手に方針を変えることはありません。\n"
            "⚠ 灰色の項目は**まだ効きません**（値は保存され、対応したときに効きます）。"
            "ツールチップに理由が出ます。\n"
            "⚠ 反映は**次の戦闘から**です（戦闘の途中で戦術が入れ替わらないように）。")
        note.setWordWrap(True)
        note.setStyleSheet(NOTE_STYLE)
        grid.addWidget(note, line, 0, 1, ncol + 1)
        grid.setRowStretch(line + 1, 1)
        area.setWidget(holder)
        return area

    @staticmethod
    def _bold() -> QFont:
        font = QFont()
        font.setBold(True)
        return font

    def _build_footer(self):
        # ★★ **「保存」と「この戦術を使う」を1つにした**（2026-07-31）★★
        #   ⚠ 直したあと**2回押さないと効かない**のは分かりにくかった
        #     （実際「保存したのに変わらない」で1度つまずいている）。
        #   ★[OK] = 保存して、その戦術を使う。押す回数を減らす。
        row = QHBoxLayout()
        # ★成功したらこの窓を閉じる（2026-07-31 の指示書 §9）。
        #   ⚠ ラベルは「使う」のまま。**閉じることより効くことが主目的**なので、
        #     「保存して閉じる」にすると設定が効くことが読み取れなくなる。
        #     閉じる件は説明のほうに書く。
        tips = {
            "OK（保存して使う）":
                "設定を保存して AI へ反映し、この画面を閉じます\n"
                "★反映は次の戦闘からです\n"
                "⚠ 入力に誤りがあるときは閉じません（理由を下に出します）",
            "元に戻す": "保存していない変更を捨てて、読み直します",
        }
        for label, slot in (("OK（保存して使う）", self.apply_active),
                            ("元に戻す", self.revert)):
            button = QPushButton(label)
            button.setToolTip(tips[label])
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        for label, slot in (("エクスポート", self.export_file),
                            ("テキストをコピー", self.copy_text),
                            ("インポート", self.import_dialog)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)

        box = QVBoxLayout()
        box.addLayout(row)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(NOTE_STYLE)
        box.addWidget(self._status)
        return box

    # --- 中身 -------------------------------------------------------

    def reload(self, select=None) -> None:
        """一覧を作り直す。"""
        self._profiles = self.repo.list_profiles()
        wanted = select or (self._current.id if self._current else
                            self.repo.active_id())
        self._loading = True
        self._picker.clear()
        for prof in self._profiles:
            mark = "（見本）" if prof.preset else ""
            self._picker.addItem(f"{prof.name}{mark}", prof.id)
        self._loading = False
        index = self._picker.findData(wanted)
        self._picker.setCurrentIndex(max(0, index))
        self._on_pick()
        if self.repo.problems:
            self._status.setText("⚠ " + "／".join(self.repo.problems[-2:]))

    def _on_pick(self) -> None:
        if self._loading:
            return
        wanted = self._picker.currentData()
        if wanted is None:
            return
        if self._current is not None and self._current.id != wanted \
                and self._dirty and not self._ask_unsaved():
            # ★キャンセルされたら選択を戻す
            self._loading = True
            self._picker.setCurrentIndex(
                max(0, self._picker.findData(self._current.id)))
            self._loading = False
            return
        found = next((p for p in self._profiles if p.id == wanted), None)
        if found is None:
            return
        self._current = found
        self._load_into_screen(found)

    def _on_picked_by_user(self, _index: int) -> None:
        """★人がリストを選んだとき ＝ **その作戦へ即時切替**（指示書 §5.2）。

        処理（§5.2 の 1〜5）:
          1. 現在作戦を即時変更   ← `vm.set_active_tactics`
          2. メイン画面と同期     ← `strategy_changed` を鳴らす
          3. 詳細パネルへ切替     ← `_on_pick`（先に鳴っている）
          4. 次の行動計画から適用 ← Lua 側（`push_tactics`）
          5. 操作ログ             ← `vm.set_active_tactics` の中

        ⚠⚠ **`_on_pick` が選択を戻していたら、切り替えません。**
          未保存の編集があると `_ask_unsaved()` が確認を出し、
          取り消された場合は選択が元へ戻ります。★そこで切り替えると
          「戻したはずなのに別の作戦で戦っている」ことになります。
        """
        wanted = self._picker.currentData()
        if wanted is None:
            return
        if self._current is None or self._current.id != wanted:
            # ★`_on_pick` が選択を戻した（＝取り消された）
            return
        result = self.vm.set_active_tactics(wanted, source="tactics_window")
        if not result.ok:
            self._status.setText(result.message)
            self.reload(select=self.repo.active_id())
            return
        if not result.changed:
            return                     # ★同じものを選び直しただけ（§6）
        self._status.setText(result.message.replace("\n", " "))
        self.strategy_changed.emit(result.message.replace("\n", " "))

    def _load_into_screen(self, prof) -> None:
        self._loading = True
        self._name.setText(prof.name)
        self._description.setText(prof.description)
        self._name.setReadOnly(prof.preset)
        self._description.setReadOnly(prof.preset)
        for row in self._rows.values():
            row.load(prof)
            # ★見本は編集できない（複製して編集する / 仕様書 4.5）。
            #   ⚠ **毎回付け直す**（切ったままにしない / `apply_editable` 参照）
            row.apply_editable(prof.preset)
        self._loading = False
        # ⚠⚠ **読み込んだ直後は「未保存あり」ではない。**
        #   ★2026-08-12: ここが `True` になっていて、作戦を選ぶたびに
        #     「保存 / 破棄 / キャンセル」の窓が出て**操作が止まりました**
        #     （テストは `box.exec()` で無反応になります）。
        #   ⚠ 原因は `break_tactics.py` の書き換えが `git add -A` に紛れたこと。
        self._dirty = False
        self._update_title()
        active = self.repo.active_id()
        if prof.preset:
            self._status.setText(
                "これは同梱の見本です。編集するには [複製] を押してください。")
        elif active == prof.id:
            self._status.setText("★これがいま使われている戦術です。")
        else:
            self._status.setText(
                "使うには [OK（保存して使う）] を押してください。")

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = self._current.name if self._current else "-"
        star = " *" if self._dirty else ""
        self.setWindowTitle(f"戦術プロフィール{star} — RetroUX")
        self._dirty_label.setText(
            "⚠ 未保存の変更があります（[保存] を押してください）" if self._dirty
            else f"表示中: {name}")

    def _ask_unsaved(self) -> bool:
        """未保存の変更があるときに聞く（仕様書 14.3）。

        戻り値: 続けてよいか（キャンセルなら False）
        """
        box = QMessageBox(self)
        box.setWindowTitle("未保存の変更")
        box.setText("未保存の変更があります。どうしますか？")
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("破棄", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return self.save()
        return clicked is discard

    # --- 操作 -------------------------------------------------------

    def _collect(self) -> None:
        """画面の値を、いま選んでいるプロフィールへ書き戻す。"""
        if self._current is None:
            return
        self._current.name = self._name.text().strip() or self._current.name
        self._current.description = self._description.text().strip()
        for row in self._rows.values():
            row.store(self._current)

    def save(self) -> bool:
        if self._current is None:
            return False
        if self._current.preset:
            self._status.setText(
                "⚠ 見本は保存できません。[複製] してから編集してください。")
            return False
        self._collect()
        if not self.repo.save(self._current):
            # ⚠ 失敗しても画面の値は消さない（設計した戦術が消えるほうが痛い）
            self._status.setText(
                "⚠ 保存できませんでした（"
                + "／".join(self.repo.problems[-1:] or ["理由不明"])
                + "）。画面の値はそのまま残しています。")
            return False
        self._dirty = False
        self._update_title()
        # ★選ばれている戦術を保存したら、Lua へも渡し直す
        if self.repo.active_id() == self._current.id:
            self.vm.push_tactics()
            self._status.setText(
                "保存しました。★反映は次の戦闘からです。")
        else:
            self._status.setText("保存しました。")
        self.reload(select=self._current.id)
        return True

    def revert(self) -> None:
        """未保存の変更を捨てる（仕様書 4.2「元に戻す」）。"""
        if self._current is None:
            return
        found = self.repo.get(self._current.id)
        if found is None:
            self._status.setText("⚠ 元の内容が見つかりません。")
            return
        self._current = found
        self._load_into_screen(found)
        self._status.setText("保存前の内容に戻しました。")

    def create_new(self) -> None:
        if self._dirty and not self._ask_unsaved():
            return
        made = self.repo.create("あたらしい戦術")
        if not self.repo.save(made):
            self._status.setText("⚠ 作れませんでした（置き場が書けない状態です）。")
            return
        self._current = made
        self.reload(select=made.id)
        self._status.setText("作りました。名前と設定を変えて [保存] してください。")

    def duplicate(self) -> None:
        if self._current is None:
            return
        if self._dirty and not self._ask_unsaved():
            return
        made = self.repo.duplicate(self._current)
        if not self.repo.save(made):
            self._status.setText("⚠ 複製できませんでした。")
            return
        self._current = made
        self.reload(select=made.id)
        self._status.setText("複製しました（こちらは編集できます）。")

    def delete(self) -> None:
        if self._current is None:
            return
        if self._current.preset:
            self._status.setText("⚠ 見本は消せません。")
            return
        # ★★ 消すのは戻せない。**必ず聞く。**
        answer = QMessageBox.question(
            self, "削除の確認",
            f"『{self._current.name}』を消します。元に戻せません。よいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.repo.delete(self._current):
            self._status.setText("⚠ 消せませんでした。")
            return
        self._current = None
        self._dirty = False
        self.reload()
        self._status.setText("消しました。")

    def apply_active(self) -> None:
        """[OK] = **保存してから**その戦術を使う（Lua へ渡す）。

        ★★ 以前は [保存] と [この戦術を使う] が別で、
          **2回押さないと効かなかった**（分かりにくかった / 2026-07-31 に統合）。

        ⚠ 見本は保存できないので、その場合は保存を飛ばして「使う」だけ行う
          （見本は複製しないと編集できない作りなので、変更は入っていない）。

        ## ★成功したら**この窓を閉じる**（2026-07-31 の指示書 §9）

          ⚠⚠ **閉じてよいのは「全部済んだあと」だけ。**
            検証・保存・反映のどれかで失敗したら**閉じない**。
            閉じてしまうと、直すべき入力が消えて**何が悪かったか分からない**。
            下の early return がすべて「閉じずに理由を出す」になっている。
        """
        if self._current is None:
            return
        # ★直してあるなら、まず保存する（押す回数を減らすのが目的）
        if self._dirty:
            if self._current.preset:
                self._status.setText(
                    "⚠ 見本は保存できません。[複製] してから直してください。")
                return
            if not self.save():
                return                      # ★理由は save() が画面に出す
        if not self.repo.set_active(self._current.id):
            self._status.setText("⚠ 選択を覚えられませんでした。")
            return
        if not self.vm.push_tactics():
            self._status.setText(
                "⚠ エミュレータへ渡せませんでした（閲覧専用か、書けない状態です）。")
            return
        # ⚠ `reload` は `_status` を上書きするので、**そのあとに**書く
        #   （実際に踏んだ: 「次の戦闘から」が消えて別の文になった）。
        self.reload(select=self._current.id)
        message = (f"★戦術『{self._current.name}』を使います。"
                   "反映は次の戦闘からです。")
        self._status.setText(message)

        # ★ここまで来たら全部済んでいる。窓を閉じ、報告は呼び出し元へ渡す。
        #   ⚠ 閉じる前に必ず知らせること。閉じてから出そうとしても、
        #     受け手（本体の画面）がもう繋がっていない場合がある。
        #
        # ★★ メイン画面の作戦リストも合わせる（2026-08-04 / §19 受入条件3）。
        #   ⚠ [OK] から変えたときも同期が要ります。リストを選んだときだけ
        #     同期していると、**[OK] で変えた作戦がメイン画面に出ません**。
        self.strategy_changed.emit("")
        self.applied.emit(message)
        self.close()

    # --- 出す・入れる -----------------------------------------------

    def export_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from ..core.tactics.import_export import write_profile_file

        if self._current is None:
            return
        self._collect()
        path, _ = QFileDialog.getSaveFileName(
            self, "戦術プロフィールを書き出す", f"{self._current.id}.yaml",
            "YAML (*.yaml)")
        if not path:
            return
        if write_profile_file(path, self._current):
            self._status.setText(f"書き出しました: {path}")
        else:
            self._status.setText("⚠ 書き出せませんでした。")

    def copy_text(self) -> None:
        """YAML 全文をクリップボードへ（仕様書 11.3）。"""
        from ..core.tactics.import_export import profile_to_yaml

        if self._current is None:
            return
        self._collect()
        text = profile_to_yaml(self._current)
        try:
            from PySide6.QtWidgets import QApplication

            board = QApplication.clipboard()
            if board is None:
                raise RuntimeError("クリップボードが無い")
            board.setText(text)
            self._status.setText(
                f"コピーしました（{len(text)} 文字）。貼って渡せます。")
        except Exception:                              # noqa: BLE001
            # ⚠ クリップボードが使えない環境でも詰まらせない
            self._status.setText(
                "⚠ クリップボードへ入れられませんでした。"
                "[エクスポート] でファイルに出せます。")

    def import_dialog(self) -> None:
        from .tactics_import_dialog import TacticsImportDialog

        if self._dirty and not self._ask_unsaved():
            return
        dialog = TacticsImportDialog(self.repo, parent=self)
        dialog.exec()
        if dialog.imported is None:
            return
        self._current = dialog.imported
        self.reload(select=dialog.imported.id)
        self._status.setText(
            f"『{dialog.imported.name}』を読み込みました。"
            "使うには [OK（保存して使う）] を押してください。")

    # --- 人が読む要約 -----------------------------------------------

    def summary_text(self) -> str:
        from ..core.tactics.import_export import profile_summary

        if self._current is None:
            return ""
        return profile_summary(self._current)

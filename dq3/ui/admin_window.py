"""管理画面（RX3-0059 / PoC）: 状態 / プレイデータの初期化・退避・復元 / 自動操作（高速実行）/ 聞き込みテスト（履歴の初期化・手動の倍率）/ 自動移動の停止。

★RX3-0258（2026-09-14 依頼者）: 左右 2 カラム（★1920×1080 で縦スクロールなしに主な機能へ届く）/ リストック設定を「アイテム × 保持数」の表に
（★［…］の補充設定の窓と同じ部品 `restock_window.RestockTable` / ⚠ 旧い自由入力の文字の欄は無くした）。

⚠ RX3-0259（2026-09-14 依頼者「自動操作・速度の設定はいらないよね？ walker、街ナビの設定も不要」）で外したもの:
  高速実行の 2 つのチェック（★聞き込み・街移動・補充はいつも高速）/ 手動 400% / 自動機能（Walker・街ナビの状態と「自動移動を停止」）。
  ★Walker は製品の画面から動かす口が無い / 街移動・聞き込みはゲームの B と各ボタンの「停止」で止まる。

## ★方針（指示書 §3）

1. 状態が分かる 2. 操作対象を間違えない 3. 危険な操作は確認ダイアログ 4. 項目を足しやすい（節ごとの QGroupBox）

## ★責務

```text
状態          state.json（view_model）と FCEUX の窓（EmulatorSpeedController.connected）
プレイデータ  dq3/knowledge/playdata.py（★CLI と同じ service）
リストック    dq3/ui/restock_window.py（★`admin.restock_wants`）
```

⚠ 別 Window（QWidget）。★モンスター図鑑と同じ開き方（2 つ開かない / フォーカスを奪わない）。
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from dq3 import emulator_video as EV
from dq3.knowledge import playdata as PD
from dq3.ui.ui_settings import UiSettings

#: ★state.json がこの秒数以内に進んでいれば「Lua Bridge Connected」
BRIDGE_FRESH_S = 3.0

#: ⚠ 「倒したことのある敵とは自動で戦う」は 2026-09-13 に戦闘AI設定画面の「戦闘開始時 自動 / 手動」へ移した
#:   （RX3-0237 / 依頼者「戦闘開始時の振る舞いは設定画面へ分離する」/ ★保存の鍵 automation.battle_auto_known は同じ）


def _status_label(connected: bool | None, yes="Connected", no="Disconnected") -> str:
    if connected is None:
        return "―"
    return yes if connected else no


class AdminWindow(QWidget):
    def __init__(self, vm, commands, *, speed=None, service: PD.PlayDataService | None = None,
                 confirm=None, town_bar=None, settings: UiSettings | None = None,
                 on_detail_log=None, parent=None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.commands = commands
        self.speed = speed
        self.settings = settings or UiSettings()     # ★チェックの選択を残す（work/dq3-ui-settings.json）
        #: ★「詳しいログ」を入り切りしたときに知らせる先（★ログ画面の `set_show_detail` / RX3-0276）
        self.on_detail_log = on_detail_log
        self.service = service or PD.PlayDataService()
        self.town_bar = town_bar
        self._confirm = confirm or self._ask
        self._last_frame = None
        self._last_frame_at = 0.0
        self.message = ""
        self.setWindowTitle("RetroUX DQ3 管理")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # ★★ 左右 2 カラム（RX3-0258 / 依頼者: 1920×1080 で縦スクロールなしに主な機能へ届く）
        #   左: プレイデータ（初期化・退避）→ 聞き込みテスト（履歴のクリア）= ★指示書の「プレイデータ・履歴」
        #   右: リストック設定 → 状態（その他・デバッグ）
        #   ★RX3-0259: 「自動操作・速度」「自動機能（Walker・街ナビ）」を外した（依頼者「いらない」/ 意味が残っていない）
        root = QVBoxLayout(self)
        cols = QHBoxLayout()
        left_box, right_box = QWidget(), QWidget()
        left, right = QVBoxLayout(left_box), QVBoxLayout(right_box)
        for lay in (left, right):
            lay.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self._build_playdata())
        left.addWidget(self._build_hearing())
        left.addStretch(1)
        right.addWidget(self._build_restock())
        right.addWidget(self._build_status())
        right.addStretch(1)
        # ★左右は同じ幅（⚠ 伸び縮みの比だけでは中身の大きさの差が残る = 300 / 390 だった / §7）
        width = max(left_box.sizeHint().width(), right_box.sizeHint().width())
        for box in (left_box, right_box):
            box.setMinimumWidth(width)
            cols.addWidget(box, 1)
        root.addLayout(cols, 1)
        self._msg = QLabel("")
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet("color: #888;")
        root.addWidget(self._msg)
        self._load_settings()
        self.refresh()
        self.resize(self.sizeHint())

    def _load_settings(self) -> None:
        """★前回のチェックを戻し、変えたら書く。"""
        items = self.settings.get("admin", "playdata_items")
        if isinstance(items, list):
            for key, cb in self.checks.items():
                cb.setChecked(key in items)
        for cb in self.checks.values():
            cb.toggled.connect(lambda _on: self.settings.set("admin", "playdata_items", self.selected_items()))
        # ★「詳しいログ」（RX3-0276）。⚠ 既定は出さない（★RX3-0482 / 保存があれば保存を優先）
        from .battle_window import SETTING_KEY, SETTING_SECTION, show_detail_of

        self.c_detail_log.setChecked(show_detail_of(self.settings))
        self.c_detail_log.toggled.connect(self.set_detail_log)
        # ★補充の目標は表が自分で読む（RX3-0258 / ⚠ 旧い自由入力の文字の欄は無くした）
        self._detail_key = (SETTING_SECTION, SETTING_KEY)
        # ★画面の見え方（RX-0140）。⚠ 覚えるのは名前（`PAL 3x`）で、番号は持たない
        name = EV.chosen(self.settings)
        index = self.cb_video.findData(name)
        if index >= 0:
            self.cb_video.setCurrentIndex(index)
        self.cb_video.currentIndexChanged.connect(self.set_video_filter)

    def set_video_filter(self, _index: int) -> None:
        """★選んだ見え方を覚える（⚠ 当てるのは起動スクリプト = 次の起動から）。"""
        name = self.cb_video.currentData()
        if name not in EV.FILTERS:
            return
        self.settings.set(EV.SECTION, EV.KEY, name)
        self.message = "★「%s」は**次に FCEUX を起こしたとき**から効きます" % EV.label_of(name)
        self._msg.setText(self.message)

    def set_detail_log(self, on: bool) -> None:
        """★「詳しいログ」の入り切りを覚え、ログ画面へ知らせる（RX3-0276）。"""
        from .battle_window import SETTING_KEY, SETTING_SECTION

        self.settings.set(SETTING_SECTION, SETTING_KEY, bool(on))
        if self.on_detail_log is not None:
            try:
                self.on_detail_log(bool(on))
            except Exception:                                    # noqa: BLE001 ⚠ ログ画面が無くても管理画面は止めない
                pass

    # ------------------------------------------------------------------
    # ★状態
    # ------------------------------------------------------------------
    def _build_status(self) -> QWidget:
        box = QGroupBox("状態")
        grid = QGridLayout(box)
        self.l_fceux, self.l_bridge, self.l_rom = QLabel("―"), QLabel("―"), QLabel("―")
        self.l_place, self.l_map, self.l_xy = QLabel("―"), QLabel("―"), QLabel("―")
        # ★「詳しいログ」の入り切り（RX3-0276 / 依頼者「ON/OFFは管理画面に逃がして。これで1行とるのもったいない」）。
        #   ⚠ 行は増やさない（★「Lua Bridge」の行の右が空いている / 管理画面の高さを決めるのは右の列）
        self.c_detail_log = QCheckBox("詳しいログを出す")
        self.c_detail_log.setToolTip("★ログ画面に、開発・障害解析用の詳しいログ（灰）も出します" + chr(10)
                                     + "⚠ 切ると行動履歴だけ（★切っている間の分も覚えていて、入れ直すと出ます）")
        # ★★ 画面の見え方（RX-0140 / 2026-09-18 依頼者「レトロ感だと pal3x だね。これにしよう」）。
        #   ⚠ 効くのは**次に FCEUX を起こしたとき**から（★実行中は変えられない / RX-0108）。
        self.cb_video = QComboBox()
        for name, label, tip in EV.CHOICES:
            self.cb_video.addItem(label, name)
            # ★1 つずつ「何が起きるか」を出す（⚠ 見出しは短くしたいので、説明はヒットへ）
            self.cb_video.setItemData(self.cb_video.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.cb_video.setToolTip(
            "★FCEUX の映像フィルタ（⚠ 次に起動したときから変わります）" + chr(10)
            + "★一覧の項目にカーソルを置くと、それぞれの説明が出ます" + chr(10)
            + "⚠ 「にじみ」だけ窓が横に広がります")
        # ⚠ 一覧の文字で列の幅が広がらないようにする（★管理画面の左右の釣り合い / RX3-0258）
        self.cb_video.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cb_video.setMinimumContentsLength(8)
        # ★6 行 → 4 行（RX3-0258 / ⚠ 右の列が管理画面の高さを決めていた）。★出す値は同じ
        # ⚠ 2026-10-02（DQ3-000156）: コントローラーの「パッドの枠」は外しました（★LB / RB はステート 0 固定）。
        rows = (("FCEUX", self.l_fceux, "ROM", self.l_rom), ("Lua Bridge", self.l_bridge, None, self.c_detail_log),
                ("現在地", self.l_place, None, None), ("map_id", self.l_map, "座標", self.l_xy),
                ("画面の見え方", self.cb_video, None, None))
        for r, (name, value, name2, value2) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            if name2 is None and value2 is None:
                grid.addWidget(value, r, 1, 1, 3)
            elif name2 is None:
                grid.addWidget(value, r, 1)
                grid.addWidget(value2, r, 2, 1, 2)
            else:
                grid.addWidget(value, r, 1)
                grid.addWidget(QLabel(name2), r, 2)
                grid.addWidget(value2, r, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    def status_values(self) -> dict:
        """★表示している値（★テストと証跡で state.json と突き合わせる）。"""
        raw = self.vm._raw() if hasattr(self.vm, "_raw") else {}
        frame = raw.get("frame")
        now = time.time()
        if frame is not None and frame != self._last_frame:
            self._last_frame, self._last_frame_at = frame, now
        bridge = (frame is not None) and (now - self._last_frame_at < BRIDGE_FRESH_S)
        fceux = self.speed.connected() if self.speed is not None else None
        game = raw.get("game")
        rom = ("DQ3 JP" if game == "dq3" else str(game)) if game else None
        at = self.vm.position()
        place = map_id = x = y = None
        if at is not None:
            kind, map_id, x, y = at
            from dq3.knowledge.seen_map import is_local

            if is_local(kind) and map_id is not None:
                try:
                    view = self.vm.location_view("L%d" % map_id)
                    place = view.name if getattr(view, "is_known", False) and getattr(view, "name", None) else None
                except Exception:                                # noqa: BLE001
                    place = None
            else:
                place = "世界地図" if kind == 0 else ("アレフガルド" if kind == 2 else None)
                map_id = None
        # ★★ 2026-09-21（RX3-0328）: 右画面にあった「戦闘中 / フィールド」をここへ移しました。
        #   ⚠ 依頼者「frame／フィールド表示は管理画面に移動させていい」（★右画面の縦を稼ぐ）。
        where = None
        if frame is not None:
            where = "戦闘中" if bool(raw.get("in_battle")) else "フィールド"
        return {"fceux": fceux, "bridge": bridge, "frame": frame, "rom": rom, "place": place, "map_id": map_id,
                "x": x, "y": y, "where": where}

    # ------------------------------------------------------------------
    # ★プレイデータ
    # ------------------------------------------------------------------
    def _build_playdata(self) -> QWidget:
        box = QGroupBox("プレイデータ")
        lay = QVBoxLayout(box)
        self.checks: dict[str, QCheckBox] = {}
        for key, label, _names in PD.ITEMS:
            if key == "hearing":
                continue                             # ★聞き込みは下の節（★地図・モンスターと分けて再試行できるように）
            cb = QCheckBox(label)
            cb.setChecked(True)
            lay.addWidget(cb)
            self.checks[key] = cb
        row = QHBoxLayout()
        self.b_backup = QPushButton("バックアップ")
        self.b_backup.setToolTip("★いまのプレイデータ一式を work/playdata-archive/ へ写します（⚠ 消しません）")
        self.b_backup.clicked.connect(self.do_backup)
        self.b_restore = QPushButton("復元")
        self.b_restore.setToolTip("★最新のバックアップから戻します（⚠ いまの記録は上書き。★その前にも退避します）")
        self.b_restore.clicked.connect(self.do_restore)
        row.addWidget(self.b_backup)
        row.addWidget(self.b_restore)
        lay.addLayout(row)
        self.b_clear = QPushButton("選択したデータを初期化")
        self.b_clear.setStyleSheet("color: #c04040; font-weight: bold;")
        self.b_clear.setToolTip("⚠ 選んだ項目を消します（★消す前に退避）。ROM / セーブステート / 解析データは消しません")
        self.b_clear.clicked.connect(self.do_clear)
        lay.addWidget(self.b_clear)
        # ★★ ⚠ 初回起動で見送っても**あとから呼べる道**（RX3-0471 / 依頼者 §1）★★
        #
        #   ⚠⚠ 誘いは `should_offer()` が False になると出なくなるので、
        #     ★ここが唯一の入口になります。⚠ だから常に押せます。
        self.b_migrate = QPushButton("旧版からデータを引き継ぐ")
        self.b_migrate.setToolTip(
            "★以前の RetroUX DQ3 のフォルダを 1 つ選ぶと、"
            "あなたのデータだけを写します" + chr(10)
            + "⚠ 旧版のフォルダは読むだけです（★削除も移動も書き換えもしません）"
            + chr(10) + "⚠⚠ 新版に同じものが既にあるぶんは引き継げません（★上書きしません）")
        self.b_migrate.clicked.connect(self.do_migrate)
        lay.addWidget(self.b_migrate)
        self.l_backup = QLabel("")
        self.l_backup.setStyleSheet("color: #888;")
        lay.addWidget(self.l_backup)
        return box

    def selected_items(self) -> list[str]:
        return [k for k, cb in self.checks.items() if cb.isChecked()]

    def _ask(self, title: str, text: str) -> bool:
        got = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                                   QMessageBox.StandardButton.Cancel)
        return got == QMessageBox.StandardButton.Ok

    def _after_change(self, message: str) -> None:
        self.message = message
        # ★画面が持っている記録を読み直す（⚠ 読み直さないと古いメモが残って見える）
        try:
            self.vm.reload_knowledge()
        except Exception:                                        # noqa: BLE001
            pass
        for attr in ("_seen",):
            if hasattr(self.vm, attr):
                setattr(self.vm, attr, None)
        # ★街ナビの heard も読み直す（⚠ 消した後に「もう聞いた」と判断しないため）
        bar = self.town_bar
        svc = getattr(getattr(bar, "ctl", None), "service", None)
        if svc is not None and hasattr(getattr(svc, "heard", None), "reload"):
            try:
                svc.heard.reload()
            except Exception:                                    # noqa: BLE001
                pass
        self._refresh_places()                   # ★場所ごとのクリアの一覧も（RX3-0235）
        self.refresh()

    def do_backup(self) -> None:
        got = self.service.backup("manual")
        self._after_change("★退避しました: %s" % got.name)

    def do_migrate(self) -> None:
        """★旧版からの引き継ぎの窓を出す（RX3-0471 / ⚠ いつでも押せる）。

        ⚠⚠ ここは**窓を出すだけ**です。★判断と一覧は `dq3.migrate` /
          `dq3.ownership` にあり、⚠ この画面は一覧を 1 つも持ちません。
        """
        from dq3.ui.migrate_dialog import MigrateDialog

        dlg = MigrateDialog(self)
        dlg.exec()
        got = dlg.result_of_run
        if got is None:
            return                                   # ★キャンセル（⚠ 何も書いていない）
        self._after_change("★引き継ぎ: %s（写した %d 件 / 引き継げなかった %d 件）"
                           % (got.outcome, got.copied, len(got.skipped)))

    def do_restore(self) -> None:
        latest = self.service.latest_backup()
        if not latest:
            self.message = "⚠ 退避がまだありません"
            self.refresh()
            return
        if not self._confirm("復元", "最新のバックアップ（%s）から戻します。\n\nいまの記録は上書きされます（★その前にも退避します）。" % latest):
            return
        got = self.service.restore("latest")
        self._after_change("★戻しました: %s（%d ファイル）" % (got["source"], len(got["restored"])))

    def do_clear(self) -> None:
        items = self.selected_items()
        if not items:
            self.message = "⚠ 何も選ばれていません"
            self.refresh()
            return
        if not self._confirm("初期化", PD.describe(items)):
            return
        got = self.service.clear(items)
        self._after_change("★初期化しました: %s（退避 %s）" % (" / ".join(PD.LABELS[k] for k in got["items"]), got["backup"]))

    # ------------------------------------------------------------------
    # ★聞き込みテスト
    # ------------------------------------------------------------------
    def _build_hearing(self) -> QWidget:
        box = QGroupBox("聞き込みテスト")
        lay = QVBoxLayout(box)
        self.l_hearing = QLabel("")
        lay.addWidget(self.l_hearing)
        self.b_clear_hearing = QPushButton("聞き込み履歴を初期化")
        self.b_clear_hearing.setStyleSheet("color: #c04040;")
        self.b_clear_hearing.setToolTip("★聞いた会話（heard / conversations）と勇者メモの聞き込みの行だけ消します\n⚠ 地図・モンスター情報・ふつうの会話メモは変わりません")
        self.b_clear_hearing.clicked.connect(self.do_clear_hearing)
        lay.addWidget(self.b_clear_hearing)
        self.b_rebuild_memos = QPushButton("勇者メモを聞き込みの記録から作り直す")
        self.b_rebuild_memos.setToolTip(
            "★聞いた会話（npc-conversations.json）から、勇者メモの聞き込みの行を起こし直します"
            + chr(10) + "⚠ 勇者メモだけを初期化したときに使います（★heard が残っていると聞き直せないため）"
            + chr(10) + "⚠ 同じ本文は二度足しません")
        self.b_rebuild_memos.clicked.connect(self.do_rebuild_memos)
        lay.addWidget(self.b_rebuild_memos)
        # ★★ 場所ごとの会話記録クリア（RX3-0235 / 依頼者の指示書 §8）。⚠ メイン画面には置かない
        place_row = QHBoxLayout()
        place_row.addWidget(QLabel("場所:"))
        self.c_place = QComboBox()
        self.c_place.setToolTip("★会話の記録がある場所（★場所 = location_id / 階をまとめた場所の単位）")
        place_row.addWidget(self.c_place, 1)
        lay.addLayout(place_row)
        self.b_clear_place = QPushButton("この場所の会話記録をクリア")
        self.b_clear_place.setStyleSheet("color: #c04040;")
        self.b_clear_place.setToolTip(
            "★選んだ場所の 勇者メモの会話・聞き込み履歴・保存済み会話 だけ消します（★消す前に全体を退避）"
            + chr(10) + "⚠ 場所を発見した記録・地名・攻略の進行状況は残ります"
            + chr(10) + "★クリア後は、その場所で再び「聞き込み」ができます")
        self.b_clear_place.clicked.connect(self.do_clear_place)
        lay.addWidget(self.b_clear_place)
        self._refresh_places()
        return box

    # ------------------------------------------------------------------
    # ★リストック設定（RX3-0258）
    # ------------------------------------------------------------------
    def _build_restock(self) -> QWidget:
        """★「アイテム」「保持数」の表（★［…］の補充設定の窓と同じ部品 / 保存も同じ `admin.restock_wants`）。"""
        from .restock_window import NOTE, RestockTable

        box = QGroupBox("リストック設定")
        lay = QVBoxLayout(box)
        note = QLabel(NOTE)
        note.setWordWrap(True)
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        self.restock_table = RestockTable(self.settings)
        lay.addWidget(self.restock_table)
        row = QHBoxLayout()
        row.addStretch(1)
        self.b_restock_reset = QPushButton("既定に戻す")
        self.b_restock_reset.clicked.connect(self.restock_table.reset)
        row.addWidget(self.b_restock_reset)
        lay.addLayout(row)
        return box

    def do_clear_hearing(self) -> None:
        if not self._confirm("聞き込み履歴を初期化", PD.describe(["hearing"])):
            return
        got = self.service.clear(["hearing"])
        self._after_change("★聞き込み履歴を初期化しました（%s / 退避 %s）" % (", ".join(got["removed"]) or "何も無かった", got["backup"]))

    def _place_rows(self) -> list:
        book = getattr(self.vm, "location_book", None)
        try:
            return list(book.all_locations()) if book is not None else []
        except Exception:                                        # noqa: BLE001
            return []

    def place_name(self, location_id: str) -> str:
        """★場所の名前（★LocationBook の名前 / ⚠ 無ければ location_id のまま）。"""
        for row in self._place_rows():
            if row.location_id == location_id and getattr(row, "display_name", None):
                suffix = getattr(row, "suffix", "") or ""
                return ("%s %s" % (row.display_name, suffix)) if suffix else row.display_name
        return location_id

    def maps_of(self, location_id: str) -> list:
        """★場所 → map（★LocationBook が複数 map をまとめていればその全部 / 無ければ `L<map_id>` から）。"""
        for row in self._place_rows():
            if row.location_id == location_id and getattr(row, "map_ids", None):
                return list(row.map_ids)
        return PD.default_maps(location_id)

    def location_of_map(self, map_id: int) -> str:
        for row in self._place_rows():
            if map_id in (getattr(row, "map_ids", None) or []):
                return row.location_id
        return "L%d" % map_id

    def _refresh_places(self) -> None:
        """★場所の一覧を作り直す（★選んでいた場所は残す）。"""
        combo = getattr(self, "c_place", None)
        if combo is None:
            return
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for p in self.service.places(location_of_map=self.location_of_map):
            combo.addItem("%s（メモ %d / 聞いた人 %d）" % (self.place_name(p["location_id"]), p["memos"], p["heard"]),
                          p["location_id"])
        if current is not None:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self.b_clear_place.setEnabled(combo.count() > 0)

    def do_clear_place(self) -> None:
        """★選んだ場所の会話記録だけ消す（RX3-0235 / ★確認 → 退避 → 消す → 画面と台帳を読み直す）。"""
        loc = self.c_place.currentData() if getattr(self, "c_place", None) is not None else None
        if not loc:
            self.message = "⚠ 場所が選ばれていません"
            self.refresh()
            return
        name = self.place_name(loc)
        if not self._confirm("この場所の会話記録をクリア", PD.describe_place(name)):
            return
        got = self.service.clear_location(loc, self.maps_of(loc))
        self._after_change("★%s の会話記録をクリアしました（メモ %d / 聞いた人 %d / 会話 %d / 退避 %s）"
                           % (name, got["memos"], got["heard"], got["conversations"], got["backup"]))

    def do_rebuild_memos(self) -> None:
        """★聞き込みの記録から勇者メモを起こし直す（RX3-0098）。

        ⚠ 消す操作ではないので確認は出しません（★足すだけ / 同じ本文は二度足さない）。
        """
        got = self.service.rebuild_hearing_memos()
        if got.get("reason"):
            self.message = "⚠ %s" % got["reason"]
            self.refresh()
            return
        self._after_change("★勇者メモを作り直しました: %d 件を足し、%d 件は既にありました"
                           % (got["added"], got["skipped"]))

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.status_values()
        self.l_fceux.setText(_status_label(s["fceux"]))
        # ★frame と「戦闘中 / フィールド」を 1 行に（⚠ 行は増やさない / RX3-0258 の約束）
        detail = ""
        if s["frame"]:
            detail = "（frame %s / %s）" % (s["frame"], s["where"] or "―")
        self.l_bridge.setText(_status_label(s["bridge"]) + detail)
        self.l_rom.setText(s["rom"] or "―")
        self.l_place.setText(s["place"] or ("（名前は訪れて知る）" if s["map_id"] is not None else "―"))
        self.l_map.setText(str(s["map_id"]) if s["map_id"] is not None else "―")
        self.l_xy.setText("%s, %s" % (s["x"], s["y"]) if s["x"] is not None else "―")
        st = self.service.status()
        for key, cb in self.checks.items():
            n = sum(1 for f in st[key]["files"] if f["exists"])
            cb.setText("%s（%d ファイル）" % (PD.LABELS[key], n))
        self.l_backup.setText("最新の退避: %s" % (st["latest_backup"] or "なし"))
        self.b_restore.setEnabled(bool(st["latest_backup"]))
        self.l_hearing.setText("聞き込み履歴  %d 人 / 勇者メモの行 %d" % (st["hearing"]["heard_npcs"], st["hearing"]["memo_lines"]))
        self.restock_table.refresh()             # ★［…］の窓で変えた数も映す（RX3-0258）
        self._msg.setText(self.message)

    # ⚠ 閉じたときに速度を 100% へ戻す処理は RX3-0259 で外した（★手動 400% のためだけの処理だった /
    #   ⚠ 残すと、聞き込み・街移動の高速化を管理画面を閉じた拍子に戻しかねない）

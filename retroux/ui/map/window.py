"""「画面に映った所」の地図（2026-07-29 / 依頼者の決定）。

2026-08-01 に `map_window.py` から分離しました（指示書 §8.1）。
★ここが持つのは **widget の配置・シグナル・キー・操作**だけです。

  描く      -> `canvas.py`
  中身を作る -> `presenter.py`

---

★★ **完全地図は出さない。** ★★

  依頼者の判断（Q3）:
      抽出はする。**出すのは自分が見た所だけ**（完全地図は出さない）。

  そのあとの追加指示:
      > マップは、歩いた所じゃなくて、画面に映った所は表示するほうがいいね
      > 定義は、そんなに難しく考えなくて良くて、真ん中からｘキャラ分とかで良いよ

  → **主人公を中心に ±`map.view_radius` マス**を「見た」として記録する。

  RetroUX の原則は「待ち時間と反復作業だけを改善し、探索には手を入れない」。
  ダンジョンの全体図を最初から見せると**探索そのものが消える**。
  ここが解決するのは「迷ったときの『どこ通ったっけ』」だけ。

★別ウィンドウにする（依頼者の判断 / Q1）。メイン画面は縦長で、
  地図を入れると既存の6段がさらに圧迫される。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .canvas import TrailView
from .presenter import MapPresenter

#: 説明の小さい文字（★何度も書かないよう名前を付けた）
_MUTED = "color:#8a8a8a; font-size:11px;"
#: 食い違いを目立たせる色（★階層だけ。自動移動が使う値なので）
_WARN = "color:#e0a030; font-size:11px;"


class MapWindow(QWidget):
    """見た所の地図（別ウィンドウ）。"""

    def __init__(self, view_model, parent=None) -> None:
        super().__init__(parent)
        self.vm = view_model
        # ★中身を作るのは presenter。ここは並べるだけ（指示書 §8.3）
        self.presenter = MapPresenter(view_model)
        self._keys: list[tuple[int, int]] = []
        self.setWindowTitle("見た地図 — RetroUX")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(880, 640)
        # ⚠ 図鑑と同じく**フォーカスを奪わない**。奪うとゲームを操作できなくなる
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QVBoxLayout(self)

        # ★★ 2026-08-09: 見出しは1行だけ（依頼者の指示）★★
        #
        #   [地図を選ぶ]  ローレシア 1F [ROM]        追従中
        #
        #   ⚠ 一覧とチェックボックスは**部品としては残します**。更新の経路
        #     （`reload` / `_redraw` / `_current_key`）が読んでいるためです。
        #     ★画面へは出しません。地図の切り替えは「地図を選ぶ」で行います。
        # ★★ 2026-08-09: 追従は**チェックボックス**に戻しました（依頼者の指示）★★
        #   > 地図の追随はチェックボックスのほうがよい（ちょっとわからない）
        #   ⚠ 「追従中／固定」を文字＋クリックにしたら、押せると分からず、
        #     いまどちらなのかも読み取りにくい、とのことでした。
        #   ★チェックボックスなら「入っているか」が一目で分かり、押せると分かります。
        self._follow = QCheckBox("追従")
        self._follow.setChecked(True)
        self._follow.setToolTip(
            "いまいる場所の地図を自動で出します。\n"
            "★外すと、いま選んでいる地図に固定されます（移動しても変わりません）。\n"
            "★「地図を選ぶ」で別の地図を選ぶと、自動で外れます。")
        self._follow.toggled.connect(self._on_follow_toggled)
        self._summary = QLabel("-")
        self._summary.setVisible(False)

        top = QHBoxLayout()
        self._pick_button = QPushButton("地図を選ぶ")
        self._pick_button.setToolTip(
            "行ったことのある地図から選びます。\n"
            "★選ぶと、その地図に固定されます（現在地を追わなくなります）。\n"
            "★「追従中」に戻すには、右の表示をクリックしてください。")
        self._pick_button.clicked.connect(self.pick_map)
        top.addWidget(self._pick_button)

        self._title = QLabel("-")
        bold = QFont()
        bold.setBold(True)
        self._title.setFont(bold)
        self._title.setWordWrap(True)
        self._title.setMinimumWidth(1)
        top.addWidget(self._title, stretch=1)

        top.addWidget(self._follow)
        root.addLayout(top)

        # ★★ 「いまの部屋」（RX-0053 / 2026-08-21 / 依頼者: 見出しの下に1行）★★
        #   ⚠ 区画データが無いマップ（街の多く・世界地図）では行ごと消える。
        self._room_note = QLabel("")
        self._room_note.setStyleSheet(_MUTED)
        self._room_note.setVisible(False)
        self._room_note.setToolTip(
            "DQ2 のダンジョンは「入った部屋（区画）だけ見える」作りです。\n"
            "★ROM の区画表から、いま立っているマスの部屋番号を出しています。\n"
            "⚠ 番号は 0〜7 しか無く、離れた部屋で使い回されます。")
        root.addWidget(self._room_note)

        # ⚠ 一覧は**画面に出しません**（「地図を選ぶ」から使います）。
        #   ★オブジェクトは残します。更新の経路がこれを読んでいます。
        self._list = QListWidget()
        self._list.setVisible(False)
        # ★★ 2026-08-09: 一覧の行も窓の最小幅を押し上げていました ★★
        #   「世界地図 [$01]  256x256  overworld  見た 539 マス」のような
        #   長い行がそのまま最小幅になります。⚠ 省略して表示し、
        #   ★全文はツールチップで読めるようにします（`_redraw` 側で付与）。
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        # ⚠ 最小を持たせない。★狭い窓では境界を左へ寄せて畳めるようにします
        #   （下の `setCollapsible`）。畳んでも地図は選べます（現在地を追う）。
        self._list.setMinimumWidth(0)
        self._list.currentRowChanged.connect(lambda _i: self._redraw())

        right = QWidget()
        box = QVBoxLayout(right)
        box.setContentsMargins(0, 0, 0, 0)
        self._view = TrailView()
        zoom = getattr(view_model, "map_zoom", None)
        if zoom:
            self._view.zoom_normal, self._view.zoom_overworld = zoom
        # ★★ 2026-08-11: 地図を**スクロール枠**に入れる（依頼者）★★
        #   世界地図を大きく（倍ぐらい）して自分中心に見せ、収まらなければ
        #   縦横のスクロールバーで見る。⚠ 街・ダンジョンは従来どおり枠に収める
        #   （`_draw` が地図の種類で `setWidgetResizable` を切り替える）。
        from PySide6.QtWidgets import QScrollArea

        self._map_scroll = QScrollArea()
        self._map_scroll.setWidgetResizable(True)
        self._map_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._map_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._map_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._map_scroll.setWidget(self._view)
        box.addWidget(self._map_scroll, stretch=1)

        # ★★ 何が出ていないのかを**必ず書く** ★★
        #   壁も扉も出ないので、書かないと「壊れている」と読まれる。
        #   ★★ 2026-08-09: **短い1行＋ツールチップ**にしました ★★
        #     ⚠ 全文を出すと3行ぶんの高さを取り、左列（幅362px）では
        #       地図そのものが潰れます。★消してはいません。マウスを乗せれば
        #       全文が出ます（「何が出ていないか」は隠さない）。
        self._note = QLabel("★見た範囲だけ／地形は ROM の絵（?）")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(_MUTED)
        self._note.setToolTip(
            "★出しているのは自分が画面で見た範囲だけです（探索を潰さないため）。\n"
            "★地形は ROM のマップデータから描いています"
            "（街・ダンジョン 2026-08-09 / 世界地図 2026-08-11）。"
            "⚠ ROM から読めても、行っていない所は出しません。枠の大きさは ROM の値です。"
            "広さは中心から ±7 マス（設定 map.view_radius）。"
            "拡大は整数倍だけ（設定 map.zoom / overworld_zoom。"
            "0 にすると枠に収まる最大の整数倍）。")
        # ★★ 2026-08-19: 常時のこの1行は**画面から外す**（依頼者「煩雑」）★★
        #   ⚠ 情報は捨てない。出どころは `[ROM]/[観測]` の札で一目、詳しくは
        #     タイトル（地図名）のツールチップで読める。★テキスト自体は残す
        #     （記録・検査が参照する）。レイアウトには**足さない**＝表示しない。
        self._note.setVisible(False)

        # ★★ ⚠⚠ **ROM の絵をやめたら、必ず画面に書く**（2026-08-14 / RX-0048）★★
        #
        #   依頼者「塔のマップがちゃんとでないね。」
        #   ★灯台 1F は 44×44 で**ダンジョン最大**。地図の枠が縦 352px を
        #     切ると 1マスが 8px に足りず、⚠ **黙って青い跡へ落ちて**いた。
        #   ⚠ 画面には何も出ず、ログにも手がかりが無かった。
        #     ★「壊れた」としか読めない。だから理由をここに書く。
        self._render_note = QLabel("")
        self._render_note.setWordWrap(True)
        self._render_note.setStyleSheet(_WARN)
        self._render_note.setVisible(False)
        box.addWidget(self._render_note)

        # ★★ **名前の出どころを画面に出す** ★★
        #   日本語名の大半は ROM から取っていない（人が入れた）。
        #   出どころを隠すと、間違った名前をそのまま信じてしまう。
        self._name_note = QLabel("")
        self._name_note.setWordWrap(True)
        self._name_note.setStyleSheet(_MUTED)
        box.addWidget(self._name_note)

        # ★★ **階層は自動移動が使う情報。** ★★ 名前と違って、間違えると
        #   別の階へ行こうとする。食い違いは**目立たせる**（色を変える）。
        self._floor_note = QLabel("")
        self._floor_note.setWordWrap(True)
        self._floor_note.setStyleSheet(_MUTED)
        box.addWidget(self._floor_note)

        # --- 攻略を調べる語（マッパー仕様 4.7）-----------------------------
        # ★自分で検索に行かない。**語を出して、人が選んで貼る**。
        #   ⚠ 名前が確かでないので、こちらで勝手に調べても外す。
        search = QHBoxLayout()
        search.addWidget(QLabel("攻略を調べる語:"))
        self._search = QLineEdit()
        self._search.setReadOnly(True)
        self._search.setPlaceholderText("（名前が分からないので出せません）")
        search.addWidget(self._search, stretch=1)
        box.addLayout(search)

        # --- 人が入れたもの（マッパー仕様 フェーズ6）------------------------
        # ★★ **観測（見た範囲）と人の言葉を混ぜない。** ★★
        #   別の欄に出すことで、どちらが観測でどちらが自分の書き込みか分かる。
        marks = QHBoxLayout()
        marks.addWidget(QLabel("メモ・目印:"))
        self._marks = QLabel("-")
        self._marks.setWordWrap(True)
        self._marks.setStyleSheet(_MUTED)
        marks.addWidget(self._marks, stretch=1)
        # ★★ 2026-08-09: ボタンは記号だけにして、説明はツールチップへ ★★
        #   ⚠ 「名前・階層を直す（Ctrl+Shift+M）」は 200px 近く食っていました。
        #   ★キーの割り当てはツールチップに必ず書きます（覚えていないと使えない）。
        self._edit_button = QPushButton("✎")
        self._edit_button.setToolTip("名前・階層を直す（Ctrl+Shift+M）")
        self._edit_button.setFixedWidth(32)
        self._edit_button.clicked.connect(self.edit_map)
        marks.addWidget(self._edit_button)
        self._note_button = QPushButton("📝")
        self._note_button.setToolTip("メモを書く（Ctrl+M）")
        self._note_button.setFixedWidth(32)
        self._note_button.clicked.connect(self.edit_note)
        marks.addWidget(self._note_button)
        box.addLayout(marks)

        # --- つながり（マッパー仕様 フェーズ7）------------------------------
        # ★★ **行けたと観測した先だけ**を出す。 ★★
        #   ⚠ 「たぶんここにつながっている」は出さない。★地形は読めても
        #     「どこへ繋がるか」は分からないので、実際に通った記録だけを出す。
        self._links = QLabel("-")
        self._links.setWordWrap(True)
        self._links.setStyleSheet(_MUTED)
        box.addWidget(self._links)

        # ★押した結果を**必ず書く**。何も起きないと壊れて見える。
        self._action = QLabel("")
        self._action.setWordWrap(True)
        self._action.setStyleSheet(_MUTED)
        box.addWidget(self._action)

        # ★★ 2026-08-09: キーの一覧もツールチップへ ★★
        #   ⚠ 「Ctrl+M=メモ　Ctrl+Shift+M=名前と階層　Ctrl+P=…」は
        #     折り返しても3行を占め、⚠ 折り返さなければ最小幅を押し上げます。
        #   ★消しません。ここに「キー ?」を残し、全文はツールチップに入れます。
        self._keys_note = QLabel("キー: ? （マウスを乗せると出ます）")
        self._keys_note.setWordWrap(True)
        self._keys_note.setStyleSheet(_MUTED)
        self._keys_note.setToolTip(self.presenter.shortcut_help())
        box.addWidget(self._keys_note)

        # ★★ 2026-08-09: **細くできるようにする**（4区画の左列は 362px）★★
        #
        #   ⚠ 折り返す QLabel の最小幅は「いちばん長い**切れない語**」で
        #     決まります。`retroux/plugins/dq2/data/locations.yaml` のような
        #     語が1つ混じるだけで、窓がそれ以上細くなれません（実測 165px）。
        #
        #   ★明示的に最小幅を与えると、そちらが優先されます。⚠ 語がはみ出す
        #     ことはありますが、**全文はツールチップに残してある**ので
        #     読めなくなりはしません。
        for label in (self._title, self._note, self._name_note,
                      self._floor_note, self._marks, self._links,
                      self._action, self._keys_note):
            label.setMinimumWidth(1)

        # ★★ 2026-08-09: 説明類は**地図のツールチップへ**（依頼者の指示）★★
        #   > MAP内のテキストはツールチップに。
        #   ⚠ 部品は残します（`_redraw` が文字を入れる先）。★中身は
        #     `_apply_tooltips()` が集めて地図に貼ります。消していません。
        for label in (self._note, self._name_note, self._floor_note,
                      self._links, self._action, self._keys_note):
            label.setVisible(False)

        root.addWidget(right, stretch=1)

        # ★★ 押しやすいところに置く（仕様 20章）★★
        #   ⚠ この窓はフォーカスを奪わないので、ゲームを触っている間は
        #     ショートカットが届かない。だからボタンも並べてある。
        self._add_shortcut("Ctrl+M", self.edit_note)
        self._add_shortcut("Ctrl+Shift+M", self.edit_map)
        # 遷移の種類を人が直す（マッパー仕様 フェーズ4）。
        # ⚠ どのキーがどの種類かは `ARROW_TRANSITIONS` にまとめてある
        #   （仕様書に書かれていないのでこちらの判断。変えられる）。
        from ...core.navigation.models import ARROW_TRANSITIONS

        for key, kind in ARROW_TRANSITIONS.items():
            self._add_shortcut(
                f"Ctrl+{key.capitalize()}",
                lambda k=kind: self.mark_transition(k))
        self._add_shortcut("Ctrl+P", self.capture_tile)

        self.reload()

    def _redraw(self, here=None) -> None:
        """人の操作で描き直す（2026-08-07 / 軽量化指示書 §5.7）。

        ⚠⚠ **`follow()` の鍵を落としてから描く。**

          ★`follow()` は「動いていなければ描き直さない」ようになりました。
            ⚠ 一覧で別のマップを選んだあと鍵を落とさないと、
              **次に動くまで元の場所へ戻りません**（従来は 0.2 秒で戻った）。
            ★挙動を変えないために、人が触った所では必ず落とします。
        """
        self._follow_key = None
        self._draw(here=here)

    def _add_shortcut(self, keys: str, slot) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.activated.connect(slot)

    # --- 中身 --------------------------------------------------------

    def reload(self) -> None:
        """行ったマップの一覧を作り直す。"""
        keep = self._current_key()
        self._keys, rows = self.presenter.map_rows()
        self._list.blockSignals(True)
        self._list.clear()
        for row in rows:
            self._list.addItem(row)
        self._list.blockSignals(False)

        if not self._keys:
            self._summary.setText("まだ見た記録がありません")
            self._title.setText("-")
            self._name_note.setText("")
            self._floor_note.setText("")
            # ⚠ 地図が無いのに「出せていません」は残さない（★嘘になる）
            self._render_note.setText("")
            self._render_note.setVisible(False)
            self._search.setText("")
            self._marks.setText("-")
            self._links.setText("-")
            self._action.setText("")
            self._note_button.setEnabled(False)
            self._view.set_data([], None, None, None, None)
            return
        self._summary.setText(self.presenter.summary_text(len(self._keys)))
        index = self._keys.index(keep) if keep in self._keys else 0
        self._list.setCurrentRow(index)
        self._redraw()

    # --- 人が入れるもの（フェーズ6）------------------------------------

    def _here_place(self):
        """メモを置く場所。★**いま立っているマス**（追っているとき）。

        ⚠ 一覧で別のマップを選んでいるときは、そのマップにメモを置けない
          （どのマスか分からない）。分からないまま (0,0) に置いたりしない。
        """
        from ...core.navigation.models import Place

        here = self._view.here
        key = self._current_key()
        if here is None or key is None:
            return None
        map_id, map_ptr = key
        return Place(map_id, map_ptr, here[0], here[1])

    def edit_note(self) -> None:
        """`Ctrl+M`。いま立っているマスにメモと目印を置く。"""
        from ..map_edit_dialog import NoteDialog

        place = self._here_place()
        label = ""
        if place is not None:
            label = (f"{self.vm.map_label(place.map_id, place.map_ptr)}"
                     f"（{place.x}, {place.y}）")
        dialog = NoteDialog(self.vm, place, place_label=label, parent=self)
        dialog.exec()
        self._redraw(here=self._view.here)

    def edit_map(self) -> None:
        """`Ctrl+Shift+M`。選んでいるマップの名前と階層を直す。"""
        from ..map_edit_dialog import MapEditDialog

        key = self._current_key()
        if key is None:
            return
        dialog = MapEditDialog(self.vm, key[0], key[1], parent=self)
        dialog.exec()
        # ★名前が変わるので一覧も作り直す
        self.reload()

    def mark_transition(self, kind) -> None:
        """`Ctrl+矢印`。いま立っているマスから出る遷移の種類を決める。

        ⚠ ここに遷移の記録が無ければ**何もしない**。無い所に作ると、
          通ったことのない道ができてしまう。
        """
        from ...core.navigation.models import TRANSITION_LABELS

        place = self._here_place()
        name = TRANSITION_LABELS.get(kind, str(kind))
        if place is None:
            self._action.setText(
                "⚠ いま立っているマスが分からないので、遷移の種類を直せません。")
            return
        fixed = self.vm.set_transition_type_here(place, kind)
        if fixed == 0:
            # ★「ここには遷移の記録が無い」と**はっきり言う**。
            #   黙って何もしないと、直ったと思われる。
            self._action.setText(
                f"⚠ （{place.x}, {place.y}）から出る遷移の記録がありません。"
                "一度そこを通ると記録されます。")
            return
        self._action.setText(
            f"（{place.x}, {place.y}）から出る遷移 {fixed} 本を"
            f"「{name}」にしました（あなたが直した値がいちばん強くなります）。")
        self._redraw(here=self._view.here)

    def capture_tile(self) -> None:
        """`Ctrl+P`。いま立っているタイルの写真を撮るよう頼む。"""
        if not self.vm.request_tile_shot():
            self._action.setText("⚠ 写真を頼めませんでした（閲覧専用です）。")
            return
        # ★「頼んだ」と「撮れた」は別。撮れたかはログに出る
        self._action.setText(
            "いま立っているタイルの写真を頼みました"
            "（撮れたかどうかはログに出ます）。")

    # --- 現在地を追う ---------------------------------------------------

    def _tile_art(self) -> dict:
        """タイルの絵を読む（2026-08-01 / 課題 #65）。

        ★遊ぶうちに増えるので、**ファイルが新しくなったら**読み直す。
        ⚠ 毎回読むと 1MB 級のファイルを 200ms ごとに開くことになる。
        """
        import pathlib

        from . import tile_art

        path = (pathlib.Path(__file__).resolve().parents[3]
                / "work" / "generated" / "tile_art.txt")
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return {}
        if getattr(self, "_art_stamp", None) != stamp:
            self._art_stamp = stamp
            self._art_cache = tile_art.load(path)
        return getattr(self, "_art_cache", {})

    def _current_key(self):
        i = self._list.currentRow()
        if 0 <= i < len(self._keys):
            return self._keys[i]
        return None

    def follow(self, map_id: int | None, map_ptr: int | None,
               x: int | None, y: int | None) -> None:
        """いまの場所へ合わせる（`いまの場所を追う` のときだけ）。

        ★★ **動いていなければ描き直しません**（2026-08-07 / 軽量化指示書 §5.7）★★

          ⚠ `_draw()` は見たマスを全部塗り直します。0.2 秒ごとに呼ばれるので、
            立ち止まっている間は**同じ絵を描き続けて**いました。

          ⚠⚠ **鍵に「追う」の入り切りを必ず入れること**（★危うく踏むところ）。
            `いまの場所を追う` の枠には `stateChanged` がつながっておらず、
            ★次に `follow()` が呼ばれたときに反応する作りです。
            座標だけを鍵にすると、⚠ **枠を切っても印が消えません**
            （動くまで何も起きない）。

          ★他の入口（一覧の選択・`reload`・書き換え）は `_draw` を直接
            呼ぶので、ここの鍵とは無関係に描き直せます。
        """
        key = (self._follow.isChecked(), map_id, map_ptr, x, y)
        if key == getattr(self, "_follow_key", None):
            return
        self._follow_key = key

        if not self._follow.isChecked():
            self._draw(here=None)
            return
        if map_id is None or map_ptr is None:
            # ★★ **戦闘中も印を消さない**（2026-08-02 / 依頼者の報告）★★
            #
            #   依頼者「現在位置表示が出ない時があるのも気になる」
            #   ⚠ 実測しました。座標が来ないのは **戦闘中だけ**でした
            #     （69回中3回、いずれも `in_battle`）。
            #     Lua は「戦闘中に歩いてはいないので嘘の足跡を残さない」
            #     ために座標を出しません。★それは正しい。
            #   ⚠ でも**表示まで消す**必要はありません。戦闘は数十秒あり、
            #     その間ずっと印が消えるので目立ちます。
            #
            #   ★直前に居た場所をそのまま出します（1マスも動いていない）。
            #     ⚠ 別のマップを選んでいるときは出しません（嘘になる）。
            self._draw(here=self._remembered_here())
            return
        key = (map_id, map_ptr)
        if key not in self._keys:
            self.reload()
        if key in self._keys:
            index = self._keys.index(key)
            if self._list.currentRow() != index:
                self._list.blockSignals(True)
                self._list.setCurrentRow(index)
                self._list.blockSignals(False)
        here = (x, y) if (x is not None and y is not None) else None
        # ★戦闘に入ると座標が来なくなるので、覚えておく（上の分岐で使う）
        if here is not None:
            self._here_memory = (key, here)
        self._draw(here=here)

    def _remembered_here(self):
        """直前に居た場所。⚠ 別のマップを選んでいるなら None。

        ★「いま選んでいる地図の上の話か」を必ず確かめる。
          ⚠ 確かめないと、別の階の同じ座標に印が出て嘘になる。
        """
        remembered = getattr(self, "_here_memory", None)
        if remembered is None:
            return None
        key, here = remembered
        return here if key == self._current_key() else None

    # --- 描く -----------------------------------------------------------

    def _draw(self, here=None) -> None:
        key = self._current_key()
        if key is None:
            return
        map_id, map_ptr = key
        detail = self.presenter.detail(map_id, map_ptr)

        # ★★ タイルの絵を渡す（2026-08-01 / 課題 #65）★★
        #   依頼者「俺的にはタイル拡大表示だと思っていたのだが」
        #   ⚠ 絵は遊ぶうちに増えるので、**毎回読み直す**。
        #     読めなくても止まらない（これまでどおり色で描く）。
        self._view.set_art(self._tile_art(), map_id, detail.tile_ids)
        # ★★ 背景キャラクタ方式（2026-08-02 / マップ指示書 Phase 7）★★
        #   ⚠ 記録が無ければ空のまま渡す。**描画側が現行表示へ落ちる**。
        #     勝手に黒で埋めない（「黒い地形」と「未探索」は別のこと）。
        if hasattr(self._view, "set_metatiles"):
            self._view.set_metatiles(detail.metatiles)
        # ★★ 世界地図の見せ方（RX-0094 / 2026-08-21）★★
        #   walked（既定）: 大きさと種別を渡さず、**歩いた範囲**を枠に収める
        #     （maps.json が無かった v1.0.2 公開版の見え方。依頼者「こちらが見やすい」）。
        #   full: 256×256 を倍率2で固定・自分中心（`_apply_map_view` の世界地図ルート）。
        #   ⚠ 変えるのは**描き方だけ**。記録（`map_size`）には触らない。
        width, height, kind = detail.width, detail.height, detail.kind
        if kind == "overworld" and getattr(self.vm, "overworld_view", "walked") == "walked":
            width, height, kind = None, None, None
        self._view.set_data(detail.tiles, width, height, here, kind)
        # ★倍率と枠外の数は**描く枠に聞かないと分からない**（画面の大きさ次第）。
        cols, rows = self._view.bounds()
        # ★★ 2026-08-11: 世界地図はスクロール枠で大きく＋自分中心。街・ダンジョンは
        #   従来どおり枠に収める（`_apply_map_view` が地図の種類で切り替える）。
        zoom = self._apply_map_view(cols, rows)
        beyond = (self._view.beyond_rom()
                  if hasattr(self._view, "beyond_rom") else None)
        # ★★ 2026-08-09: 見出しは**地名と出どころだけ**（依頼者の指示）★★
        #   > 「世界地図[$01・・・ は、「世界地図」だけで。他の情報はツールチップで
        #   ★出どころ（ROM / 観測）だけは残します（私の提案 b）。同じ地図でも
        #     中身が別物なので、どちらを見ているか分からないと混乱します。
        full = self.presenter.title_text(
            detail, zoom, self._view.outside_count, beyond)
        short = detail.label.split(" [")[0]
        badge = "ROM" if detail.source == "rom" else "観測"
        self._title.setText(f"{short}　[{badge}]")
        # ★★ 2026-08-19: 根拠・出どころは出さない（ユーザーは意識しない / 依頼者）★★
        #   ⚠ マップデータから描いているのは前提。★残すのは**拡大のパターン**だけ。
        self._title.setToolTip(
            full + "\n\n拡大: 整数倍だけ"
            "（0 で枠に収まる最大 / 設定 map.zoom・overworld_zoom）")

        # ⚠⚠ **ROM の絵をやめたなら、その場で書く**（2026-08-14 / RX-0048）
        #   ★灯台 1F（44×44）は縦 352px を切ると落ちる。黙らせない。
        #   ⚠ ただし**絵が渡っているのに使えなかったとき**だけ。
        #     ★観測だけの地図は ROM の絵がそもそも無いので、出すと毎回鳴る。
        #   ⚠⚠ **世界地図では出さない**（2026-08-19 / 依頼者の画面で判明）。
        #     ★世界地図は `_apply_map_view` の**別の道**（スクロール枠 ×2）で
        #       描いており、メタタイルは使わない。
        #     ⚠ ところが `paintEvent` の `_metatile_zoom()` は
        #       「1マスが 8px に満たない（枠 512x512 / マップ 256x256）」で
        #       必ず None になるので、★**地形は出ているのに
        #       「出せていません」と黄色で出ていた**（＝嘘）。
        why = (self._view.metatile_giveup()
               if (detail.metatiles
                   and not self._view.is_overworld
                   and hasattr(self._view, "metatile_giveup")) else None)
        self._render_note.setText(
            f"⚠ ROM の地形を出せていません（{why}）" if why else "")
        self._render_note.setVisible(bool(why))
        self._render_note.setToolTip(
            "★1マスが 8px に足りないと、地形の絵ではなく"
            "「歩いた跡」の色だけになります。\n"
            "⚠ 窓を大きくするか、地図の窓を縦に伸ばすと絵で出ます。"
            if why else "")

        # ★★ 2026-08-19: 名前の出どころ注記は**出さない**（被る / 依頼者）★★
        #   ⚠ 情報は捨てない。編集ダイアログは `.text()` を読むので中身は残す。
        self._name_note.setText(self.presenter.name_source_text(map_id))
        self._name_note.setVisible(False)
        # ★いまの部屋（RX-0053）。出せないときは行ごと消す
        room = self.presenter.room_text(map_id, map_ptr, here)
        self._room_note.setText(room)
        self._room_note.setVisible(bool(room))
        # ★★ 色を決めるのは**画面**。presenter は「目立たせるか」だけ返す ★★
        floor = self.presenter.floor_text(map_id, map_ptr)
        self._floor_note.setStyleSheet(_WARN if floor.warn else _MUTED)
        self._floor_note.setText(floor.text)
        # ★階層は**食い違い(warn)のときだけ**出す。通常はタイトルに出ている。
        self._floor_note.setVisible(bool(floor.warn))

        # ★★ メモ・目印は「あることだけ」出す（2026-08-09 / 私の提案 c）★★
        #   ⚠ 全部ツールチップにすると、書いたこと自体に気づけません。
        marks = self.presenter.marks_text(map_id, map_ptr)
        self._marks.setToolTip(marks)
        self._marks.setText(
            "" if marks.startswith("まだありません") else "📝 メモ・目印あり")
        self._links.setText(self.presenter.links_text(map_id, map_ptr))
        # ★いま立っているマスが分からないとメモは置けない（場所が決まらない）
        self._note_button.setEnabled(self._here_place() is not None)
        self._search.setText(detail.search_term)
        self._apply_tooltips()

    def _apply_map_view(self, cols: int, rows: int):
        """地図の種類で「枠に収める／スクロールで大きく」を切り替える（2026-08-11）。

        ★世界地図: 設定の倍率で**大きく**描き、収まらなければスクロール。自分中心。
        ★街・ダンジョン: 従来どおり枠に収める（`pick_zoom`／メタタイル）。
        戻り値: 実際に描く倍率（描画・見出しが使う）。
        """
        view = self._view
        area = self._map_scroll
        if cols <= 0 or rows <= 0:
            area.setWidgetResizable(True)
            return None
        if view.is_overworld:
            zoom = max(1, min(view.zoom_overworld, view.ZOOM_MAX))
            area.setWidgetResizable(False)
            view.setFixedSize(cols * zoom, rows * zoom)
            self._center_on_here(zoom)
            return zoom
        # ★★★ ⚠⚠ **枠の大きさで決める。widget の大きさで決めない** ★★★
        #
        #   2026-08-18 に依頼者の画面で**青と地形が点滅**した。
        #   ⚠ 原因は、先に `setWidgetResizable(True)` で widget を枠へ伸ばし、
        #     **その widget の大きさ**を見て「入るか」を決めていたこと。
        #
        #     1: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
        #     2: 枠内側 323x393 / widget 323x393 / 収める   / 倍率 None
        #     3: 枠内側 323x379 / widget 352x352 / スクロール / 倍率 8
        #     ...（★`_draw` のたびに入れ替わる）
        #
        #   ★`maximumViewportSize()` は「スクロールバーが無いときの内側」。
        #     ⚠ スクロールバーの出入りで変わらないので、決め手にできる。
        room = area.maximumViewportSize()
        zoom = None
        if hasattr(view, "metatile_zoom_for"):
            zoom = view.metatile_zoom_for(cols, rows,
                                          room.width(), room.height())
        if zoom is not None:
            # ★枠に収まる: widget を枠いっぱいに伸ばす（従来どおり）
            area.setWidgetResizable(True)
            view.setMinimumSize(192, 192)
            view.setMaximumSize(16777215, 16777215)
            return zoom

        # ★★ **枠に収まらないなら、スクロールで見せる**（2026-08-15 / RX-0049）★★
        #
        #   依頼者の判断:
        #
        #   > 49でスクロール枠。
        #
        #   ⚠ これまでは 1マス 8px に足りないと**黙って青い跡へ落ちて**いた。
        #     ★灯台 1F は 44×44 で、地図の枠が縦 352px を切ると収まらない。
        #     依頼者は FCEUX と並べているので、そこは普通に起こる。
        #
        #   ★世界地図と同じ扱い（`setWidgetResizable(False)` ＋ 自分中心）。
        #   ⚠ 全体を一目で見られなくなるのは、この案の代償（承知のうえ）。
        small = (view.metatile_min_zoom()
                 if hasattr(view, "metatile_min_zoom") else None)
        if small:
            area.setWidgetResizable(False)
            view.setFixedSize(cols * small, rows * small)
            self._center_on_here(small)
            # ⚠⚠ **大きさを変えたら、測り直す**（★でないと嘘が残る）
            #   `_metatile_zoom()` は「1マスが 8px に満たない」という
            #   理由を抱えたままなので、⚠ このあと `_draw()` が
            #   **「ROM の地形を出せていません」と黄色で出してしまう**。
            #   ★いまは出せている。枠を広げたのだから、もう一度測る。
            view._metatile_zoom(cols, rows)
            return small

        # ⚠ 絵の材料が無い（観測だけの地図など）。★従来どおり枠に収める
        area.setWidgetResizable(True)
        view.setMinimumSize(192, 192)
        view.setMaximumSize(16777215, 16777215)
        return view.pick_zoom(cols, rows)

    def _center_on_here(self, zoom: int) -> None:
        """自分（現在地）をスクロール枠の中央に寄せる（2026-08-11 / 依頼者）。

        ⚠ 現在地が読めないとき（戦闘中など）は動かさない（勝手に飛ばない）。
        """
        here = self._view.here
        if here is None or not zoom:
            return
        hx, hy = here
        px = hx * zoom + zoom // 2
        py = hy * zoom + zoom // 2
        vp = self._map_scroll.viewport()
        # ★自分を中央に（余白＝ビューポートの半分）。範囲は Qt が調整する。
        self._map_scroll.ensureVisible(px, py, vp.width() // 2, vp.height() // 2)

    def _apply_tooltips(self) -> None:
        """画面から外した説明を、地図のツールチップにまとめる（2026-08-09）。

        ⚠⚠ **消したのではなく移しただけ**です。マウスを地図に乗せれば
          出どころ・階層・つながり・キーの割り当てが全部読めます。
        """
        # ★★ 2026-08-19: 依頼者の指示で**必要最低限**に（被る/根拠は出さない）★★
        #   ⚠ 外したもの: `_note`(見た範囲/ROM由来の根拠) / `_name_note`(日本語名は
        #     ROMから…＝被る) / `_links`(行けた先＝不要)。
        #   ★残すもの: タイトル(名前＋[ROM]＋拡大) / 階層(食い違い時のみ) /
        #     操作結果 / キー(Ctrl+M・Ctrl+Shift+M)。
        parts = [
            self._title.toolTip(),
            self._floor_note.text(),
            self._action.text(),
            self._keys_note.toolTip(),
        ]
        self._view.setToolTip("\n\n".join(p for p in parts if p))

    def _on_follow_toggled(self, on: bool) -> None:
        """追従のチェックが変わったとき（2026-08-09）。

        ★入れ直したら、いまいる場所の地図へ戻します。
          ⚠ 戻さないと、チェックを入れても画面が変わらず「効かない」に見えます。
        """
        if on:
            self.follow_current_place()

    def follow_current_place(self) -> None:
        """現在地の追従に戻す。★「地図を選ぶ」で固定したあとの戻り道。"""
        self._follow.setChecked(True)
        self._follow_key = None
        self.reload()

    def pick_map(self) -> None:
        """行った地図から選ぶ（別画面 / 2026-08-09 / 依頼者の指示）。

            > そもそも、他の地図への確認は別画面でOK
            > （ボタンを押して地図確認画面がでる）

        ★選んだらその地図に**固定**します（現在地を追わなくなります）。
          ⚠ 追わないままだと移動しても切り替わらないので、見出しの横に
            「固定」と出し、クリックで戻せるようにしてあります。
        """
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        # ★一覧を最新にしてから開く（新しく行った地図を落とさない）
        self.reload()
        if not self._keys:
            self._action.setText("まだ見た記録がありません")
            self._apply_tooltips()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("地図を選ぶ")
        dialog.resize(460, 320)
        box = QVBoxLayout(dialog)
        listing = QListWidget()
        for index in range(self._list.count()):
            listing.addItem(self._list.item(index).text())
        current = self._current_key()
        listing.setCurrentRow(
            self._keys.index(current) if current in self._keys else 0)
        listing.itemDoubleClicked.connect(lambda _i: dialog.accept())
        box.addWidget(listing)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        index = listing.currentRow()
        if index < 0:
            return
        # ⚠ 選んだ地図に固定する。★追従したままだと、次の移動で戻されます
        self._follow.setChecked(False)
        self._follow_key = None
        self._list.setCurrentRow(index)
        self._redraw()

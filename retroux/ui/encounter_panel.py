"""いま戦っている敵の図鑑を**メイン画面に**出す（2026-07-27 / 依頼者の要望）。

> モンスターと出会ったときのモンスター図鑑は、メイン画面に出したい。
> 敵モンスターパーティーは全部まとめて出したい。

★**出ている種を全部まとめて縦に並べる。** 切り替えボタンで1体ずつ見る形は
  「まとめて出したい」という要望と合わない。

★**幅が狭い**（この GUI は FCEUX の右隣に置く縦長のパネル）。
  だから1種あたり3行に収める:

      リビングデッド            HP 60  攻 31  守 7   賢さ1
        特徴  通常攻撃 61% / 防御 24% / マヌーサ 14%
        耐性  呪文◎ 眠× 黙× 死× ル◎ 幻86%     ドロップ かわのよろい(1/16)

⚠ 記号（◎ ×）を使うのは幅のため。**必ず凡例を出す**
  （記号だけで意味が分かるとは限らない）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ..core.db.behavior import action_breakdown, format_drop

#: 耐性の記号の凡例（2026-08-09 にツールチップへ移しました）。
#: ⚠ **ルカニは DQ2 に無い**（依頼者の指摘 / 2026-07-31）。
#:   守備力を下げる呪文は**ルカナン**。DQ3 以降と混ざっていた。
LEGEND_TEXT = ("耐性 ◎=必ず効く ×=効かない ／ 数字は効く確率　"
               "呪文=攻撃呪文 眠=ラリホー 黙=マホトーン 死=ザラキ "
               "ル=ルカナン 幻=マヌーサ")

# 耐性の短い見出し（幅のため）。凡例と対で意味を持つ
RESIST_SHORT = [
    ("spell_damage", "呪文"),
    ("sleep", "眠"),
    ("stopspell", "黙"),
    ("defeat", "死"),
    ("defense_down", "ル"),
    ("surround", "幻"),
]

# ★出す種の上限。DQ2 の敵グループは4組までなので4で足りるが、
#   読めない値が来ても画面が伸び続けないように上限を持つ。
MAX_SPECIES = 4

# 特徴に出す行動の数。★全部出すと7つ並んで幅が足りない。
#   **確率の高いものから**出し、残りは件数だけ添える（黙って捨てない）。
MAX_ACTIONS = 4

# 絵の枠（2026-07-29）。★このパネルは FCEUX の右隣に置く**縦長で幅が狭い**枠なので、
#   絵は小さく固定する。大きくすると3行の情報が押し出される。
#   一番大きい敵（シドー）が 96x64 なので、縦横比を保って収まる大きさにする。
ART_W, ART_H = 72, 56


def _short_resist(value: int | None) -> str:
    """幅を詰めた耐性の表記。凡例と対で使う。"""
    if value is None:
        return "-"
    if value <= 0:
        return "◎"
    if value >= 7:
        return "×"
    return f"{(7 - value) / 7 * 100:.0f}%"


class EncounterPanel(QWidget):
    """いま出ている敵の図鑑（全種まとめて）。"""

    def __init__(self, view_model) -> None:
        super().__init__()
        self.vm = view_model
        self._blocks: list[dict] = []
        self._rows_cache: dict[int, object] = {}

        # ★★ 2026-08-11: 札を**横並び**にする（依頼者の要望）★★
        #   > ログウィンドウのモンスターが縦順になっている。横順が希望
        #   ⚠ 以前は縦積みで、上段の高さ上限（TOP_MAX）に1体しか入らず、
        #     残りは縦スクロールだった。★横に並べれば同じ高さで4体まで見え、
        #     そのぶん下段（System Log）へ高さを回せる（依頼者「ログ行を増やせる」）。
        #   ⚠ 幅は log_window 側の**横スクロール**が受ける（はみ出しても見える）。
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._layout = layout

        # 戦闘していないときの案内。★空にしない（壊れて見える）
        self._idle = QLabel("戦闘に入ると、出会った敵の図鑑がここに出ます。")
        self._idle.setStyleSheet("color:#8a8a8a;")
        self._idle.setWordWrap(True)
        layout.addWidget(self._idle)
        # ★末尾に伸縮を置き、札は**左詰め**にする（`_ensure_block` はこの手前へ挿す）
        layout.addStretch(1)

        # --- いま戦っているのか、直前の戦闘なのか（2026-07-27）-------------
        #
        # 依頼者の指摘:
        #   > オート戦闘だとすぐ消えちゃうので、次の戦闘まで残すようにしてもらえる？
        #
        # ★倍速（約35倍）だと戦闘が一瞬で終わり、読む前に消えていた。
        #   **次の戦闘まで残す**ようにした。
        #
        # ⚠ ただし**残すなら「いつのものか」を書く**。
        #   書かないと、フィールドを歩いている最中の表示を
        #   「いま戦っている敵」と読み違える（0 と 不明 を混ぜないのと同じ話）。
        #
        # ★★ 2026-08-09: **行としては出しません**（依頼者の指示「いらない」）★★
        #   ⚠ 下段は 132px しかなく、1行が札の高さを削ります。
        #   ⚠⚠ ただし上の経緯どおり、**情報は捨てません**。札のツールチップへ
        #     入れます（`_refresh_tooltip`）。★読み違えの元は残しません。
        self._when = QLabel("")
        self._when.setVisible(False)
        # ⚠ レイアウトへは入れません（入れると高さを取ります）
        # ★いま戦闘中か。**状態として持つ**。
        #   ⚠ 持たずに set_active() の中だけで文字を作っていたら、
        #     中身より先に呼ばれたときに空文字のまま残った（実測）。
        #     呼ばれる順に依存しないよう、状態＋1か所での適用にする。
        self._active = False

        # ⚠ 記号の凡例。記号だけで意味が分かるとは限らない
        # ★2026-08-09: 耐性ごとツールチップへ移したので、凡例も一緒に入れます。
        #   ⚠ 画面には出しません（1行ぶんの高さを空けるため）。
        self._legend = QLabel(LEGEND_TEXT)
        self._legend.setVisible(False)

        # ⚠ 2026-08-09: `addStretch` を外しました（依頼者の報告「無駄な1行」）。
        #   ★横スクロールの枠に入れたので、余白を作るとそのぶん隙間に見えます。
        #     枠のほうが中身の高さに合わせてくれます。

    # --- 中身 --------------------------------------------------------

    def _ensure_block(self, index: int) -> dict:
        """1種ぶんの枠を用意する（初回だけ作り、以後は使い回す）。

        ★毎回作り直さない。0.5秒ごとに widget を捨てて作ると描画がちらつく
          （PartyPanel と同じ理由）。
        """
        if index < len(self._blocks):
            return self._blocks[index]

        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        # ★札は**内容ぶんの幅**にする（折り返さない＝高さは4行のまま）。
        #   ⚠ 高さを抑えるのが目的（依頼者「ログ行を増やせる」）。幅ははみ出せば
        #     log_window の横スクロールが受ける。★横に伸びて隣を押さないよう固定幅。
        from PySide6.QtWidgets import QSizePolicy
        frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        # ★絵を左、文字を右（横並び）。縦に積むと1種で4行増えて
        #   4種出たときに画面へ収まらない。
        row_box = QHBoxLayout(frame)
        row_box.setContentsMargins(6, 3, 6, 3)
        row_box.setSpacing(6)

        art = QLabel("")
        art.setFixedSize(ART_W, ART_H)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # ★背景を黒に（依頼者の指定）。絵は透明背景なので、
        #   明るいテーマだと白地に浮いて見える。FC の戦闘画面は黒。
        art.setStyleSheet("color:#6a6a6a; font-size:10px; background:#000000;")
        row_box.addWidget(art, 0, Qt.AlignmentFlag.AlignTop)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        row_box.addLayout(box, 1)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        head = QLabel("")
        bold = QFont()
        bold.setBold(True)
        head.setFont(bold)

        stats = QLabel("")
        stats.setFont(mono)

        # ★横並びでは折り返さない（折り返すと札が縦に伸び、上段の高さを食う）。
        #   ⚠ 長い特徴は `_fill` が件数を添えて丸めるので1行に収まる。
        actions = QLabel("")
        actions.setWordWrap(False)

        resist = QLabel("")
        resist.setFont(mono)
        resist.setWordWrap(False)

        for widget in (head, stats, actions, resist):
            box.addWidget(widget)
        box.addStretch(1)

        # ★★ 2026-08-11: 横並びに戻したので、末尾の伸縮の**手前**へ挿します。
        #   ⚠ こうしないと札が伸縮の右へ回り、右端に寄って隙間が空きます。
        #   ★上ぞろえ（札の高さが違っても頭がそろう）。
        self._layout.insertWidget(self._layout.count() - 1, frame, 0,
                                  Qt.AlignmentFlag.AlignTop)
        block = {"frame": frame, "art": art, "head": head, "stats": stats,
                 "actions": actions, "resist": resist}
        self._blocks.append(block)
        return block

    def _fill_art(self, block: dict, mid: int) -> None:
        """その敵の絵を小さく出す。**無ければそう書く**（空欄にしない）。

        ⚠ 表示のための処理で本体を止めない。読めない絵が来ても
          文字に置き換えるだけにする（playbook の原則10）。
        """
        art = block["art"]
        try:
            path, _source = self.vm.monster_art(mid)
        except Exception:
            path = None
        if path is None:
            art.setPixmap(QPixmap())
            art.setText("絵なし")
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            art.setPixmap(QPixmap())
            art.setText("読めず")
            return
        art.setText("")
        # ★なめらかにしない。FC の絵はドットなので補間するとぼやける
        art.setPixmap(pix.scaled(
            ART_W, ART_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))

    def set_rows(self, rows) -> None:
        """図鑑の行（`MonsterRow`）を覚えておく。

        ★戦闘の入口で DB を引き直さないため、あらかじめ渡しておく。
          全戦闘を走査するので、戦闘に入った瞬間にやると倍速の意味が無くなる。
        """
        self._rows_cache = {r.id: r for r in rows}

    def update_encounter(self, monster_ids) -> None:
        """出ている種を全部出す。空なら案内だけにする。

        ★**戦闘が終わっても呼ばない**（残すため）。呼ぶのは
          「新しい戦闘が始まったとき」だけ（`MainWindow._track_encounter`）。
        """
        ids = [i for i in dict.fromkeys(monster_ids or []) if i][:MAX_SPECIES]

        self._idle.setVisible(not ids)

        for i, mid in enumerate(ids):
            block = self._ensure_block(i)
            block["frame"].setVisible(True)
            self._fill(block, mid)

        # 余った枠は隠す（消さない。次の戦闘で使い回す）
        for block in self._blocks[len(ids):]:
            block["frame"].setVisible(False)

        self._apply_when()

    def set_active(self, in_battle: bool) -> None:
        """いま戦っているのか、直前の戦闘の表示なのかを覚えて反映する。

        ★中身は消さない。**言葉だけ変える。**
          倍速だと戦闘が一瞬で終わるので、消すと読む前に消える（依頼者の指摘）。
        """
        self._active = bool(in_battle)
        self._apply_when()

    def _apply_when(self) -> None:
        """「いつのものか」を書く。**呼ばれる順に依存しない1か所。**

        ⚠ 何も出ていないときは何も書かない（案内文と二重にならないように）。
        """
        if not any(b["frame"].isVisible() for b in self._blocks):
            self._when.setText("")
            return
        if self._active:
            self._when.setText("いま戦っている敵")
            self._when.setStyleSheet("color:#8ad1ff; font-size:11px;")
        else:
            # ★「直前」と書く。次の戦闘まで残ることも書いておく
            self._when.setText("直前の戦闘の敵（次の戦闘まで残します）")
        # ★文言が変わったら、出ている札のツールチップも合わせる
        for block in self._blocks:
            if block["frame"].isVisible():
                self._refresh_tooltip(block)

    def _refresh_tooltip(self, block: dict) -> None:
        """札のツールチップを組み立てる（2026-08-09 / 依頼者の指示）。

        ★入れるもの: いつの戦闘か ／ 耐性 ／ 記号の凡例。
        ⚠ どれも画面から消した情報です。**消したままにしません。**
        """
        parts = []
        if self._when.text():
            parts.append(self._when.text())
        resist = block.get("resist_text")
        if resist:
            parts.append(f"耐性  {resist}")
            parts.append(LEGEND_TEXT)
        block["frame"].setToolTip("\n".join(parts))

    def _fill(self, block: dict, mid: int) -> None:
        row = self._rows_cache.get(mid)
        name = self.vm.monster_name(mid)
        block["head"].setText(f"{name}　（0x{mid:02X}）")
        self._fill_art(block, mid)

        if row is None:
            # ★ROM データが無いことを**書く**。空欄にしない
            block["stats"].setText("　（この敵の ROM データがありません）")
            block["actions"].setText("")
            block["resist"].setText("")
            block["resist_text"] = ""
            self._refresh_tooltip(block)
            return

        parts = []
        for caption, value in (("HP", row.max_hp), ("攻", row.attack),
                               # ⚠ すばやさの略は「素」ではなく **「速」**
                               #   （依頼者の指摘 / 2026-07-31）。
                               #   「素」は素早さの1文字目だが、意味を持つのは「速」。
                               ("守", row.defense), ("速", row.agility)):
            parts.append(f"{caption} {value if value is not None else '-'}")
        if row.wisdom is not None:
            parts.append(f"賢さ{row.wisdom}")
        block["stats"].setText("　" + "  ".join(parts))

        # --- 特徴（確率の高い順。多いときは件数を添える）------------------
        breakdown = action_breakdown(
            {"wisdom": row.wisdom, "actions": row.actions},
            self.vm.monster_actions, self.vm.action_rates)
        if breakdown:
            shown = breakdown[:MAX_ACTIONS]
            text = " / ".join(f"{n} {p:.0f}%" for n, p in shown)
            if len(breakdown) > len(shown):
                # ★黙って捨てない。隠した件数を出す
                text += f" ほか{len(breakdown) - len(shown)}種"
            block["actions"].setText("　特徴  " + text)
        else:
            block["actions"].setText("　特徴  （データがありません）")

        # --- 耐性 と ドロップ（同じ行に詰める）----------------------------
        if row.resist:
            resist = " ".join(f"{cap}{_short_resist(row.resist.get(key))}"
                              for key, cap in RESIST_SHORT)
        else:
            resist = "（データがありません）"
        drop = format_drop(row.drop, self.vm.items)
        if not drop:
            # ★「落とさない」と「データが無い」を書き分ける
            drop = "なし" if row.max_hp is not None else "不明"
        # ★★ 2026-08-11: 耐性を**画面へ戻す**（依頼者「見えなくなった／復活」）★★
        #   ⚠ 2026-08-09 に縦並び・狭い下段でツールチップへ退避していたが、
        #     札を横並びにして横幅ができたので、耐性を同じ行に出す。
        #   ★記号の意味（凡例）はツールチップに残す（`_refresh_tooltip`）。
        block["resist_text"] = resist
        block["resist"].setText(f"　耐性 {resist}　ドロップ {drop}")
        self._refresh_tooltip(block)

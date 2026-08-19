"""Battle Monitor のパネル（MVP2 Phase 2 / 指示書 5.4 A）。

いま作れるもの:

| パネル | 材料 | 状態 |
| --- | --- | --- |
| パーティ状態 | RAM 既知（`$062D`〜） | **作れる** |
| AI判断 | P3 が決めた内容を Lua が state.json に載せている | **作れる** |
| ⚠ 敵情報 | — | **2026-08-11 に削除**（依頼者「用済み」） |

★**無い値は列を作らない。** 指示書には「予測被ダメージ」「脅威度」「スコア」も
  あるが、そのアドレスも計算方法もまだ無い。空欄や 0 で置くと
  「そういう値なのだ」と読めてしまう。**分かってから足す。**

★見た目より「読めること」を優先する。HPバーは色で危険を伝えるが、
  数字も必ず併記する（色だけに頼らない）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

# HPの割合による色。危険状態のしきい値（0.25）と、AI が回復に動く 0.5 に揃える。
# ★勝手な刻みにしない。**ゲーム側の判断と同じ境目**で色が変わるから意味がある。
HP_DANGER = 0.25
HP_WARN = 0.50

_BAR_STYLE = """
QProgressBar {{ border:1px solid #555; border-radius:3px; text-align:center;
                background:#2a2a2a; height:16px; }}
QProgressBar::chunk {{ background:{color}; border-radius:2px; }}
"""


def snapshot(value):
    """比べられる形に写し取る（2026-08-07 / 軽量化指示書 §5.2）。

    ★★ **多めに入れる。足りないほうが危険。** ★★

      入れすぎ … ⚠ 変わっていないのに描き直す（**遅くなるだけ**）
      足りない … ⚠⚠ **変わったのに描き直さない**（★画面が嘘をつく）

      → だから項目を数え上げず、**まるごと**写します。
        ⚠ 指示書 §5.4 は「表示に必要な項目だけ」と書いていますが、
          ★手で選ぶと、後で列を足したときに**入れ忘れます**
          （`docs/design/handoff-20260807.md` の12件は全部この形です）。

    ⚠ 比較にしか使いません。★中身を後から書き換えないこと。
    """
    import dataclasses

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple(snapshot(getattr(value, f.name))
                     for f in dataclasses.fields(value))
    if isinstance(value, dict):
        return tuple((k, snapshot(v)) for k, v in sorted(
            value.items(), key=lambda kv: str(kv[0])))
    if isinstance(value, (list, tuple)):
        return tuple(snapshot(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # ⚠ 見たことのない型は「毎回違う」ことにする（★取りこぼすより描き直す）
    return repr(value)


def _value_label() -> QLabel:
    """バーの隣に置く数字。**位置が動かない**ようにする。

    ★元は QProgressBar の中央にテキストを重ねていた。すると
      **数字の下をバーの境目が通り過ぎる**うえ、桁が変わると字の位置も動くので、
      「どこまで減ったか」が読み取りにくかった（依頼者の指摘 / 2026-07-26）。

      バーは**塗りの長さだけ**で伝え、数字は右端に固定する。
      こうすると動くものが1つだけになり、変化が目で追える。

    ★等幅フォントにする。可変幅だと「99->100」で字の幅が変わり、
      数字そのものが左右に揺れる。
    """
    label = QLabel("")
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    label.setFont(font)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setMinimumWidth(78)
    return label


def _make_bar(color: str = "#5aa9e0") -> QProgressBar:
    bar = QProgressBar()
    # ★数字はバーの中に出さない（上の説明のとおり）
    bar.setTextVisible(False)
    bar.setStyleSheet(_BAR_STYLE.format(color=color))
    return bar


def _bar_color(ratio: float) -> str:
    """割合に応じた色。**十分あるときは色を付けない**（None）。

    ★★ 依頼者の指摘（2026-07-29）: 「HPとMPは、少なくなったら黄色、赤文字にしたい」

    以前は満タンでも青くしていたため、「色が付いている＝注意」に見えなかった。
    **色が付いていたら少ない**、と読めるようにする。

    しきい値は AI の判断と同じ値を使う（画面と挙動を食い違わせない）:
        <= 0.25 … 危険状態。AI が止まり手動へ戻る -> 赤
        <= 0.50 … AI が回復に動く                 -> 黄
    """
    if ratio <= HP_DANGER:
        return "#e05a5a"
    if ratio <= HP_WARN:
        return "#e0b34a"
    return None


class PartyPanel(QWidget):
    """人物ごとの 名前 / LV / HP / MP / 経験値（指示書 5.4 A「味方情報」）。

    ★名前は設定から引く。**ゲーム内の名前は RAM から読めていない**
      （置き場所は $0113〜と分かったが、かなの文字コード表が未確定）。
      推測で文字を当てて出さない。

    ★★ **棒グラフをやめて表にした**（2026-07-27 / 依頼者の要望）★★

      > パーティー状態の棒グラフをやめて、行を減らしたい

      1人あたり4行（名前 / HPバー / MPバー / 経験値）だったのを
      **1人1行**にした。3人なら 12行 -> 3行＋見出し。
      空いた縦を「出会った敵の図鑑」に回す。

    ⚠ **棒が持っていた情報を落とさない。** 棒は「残りの割合」を一目で伝えていた。
      表にすると数字だけになるので、**HP の文字を色で塗る**ことで割合を残す:
        赤（25%以下） … 危険状態。AI が止まり手動へ戻る
        橙（50%以下） … AI が回復に動く
      ★色だけに頼らない。数字は常に出ている（色が見えにくい人にも伝わる）。
    """

    #: 表の列。★**つよさの4項目を足した**（2026-07-31 / 依頼者の要望）。
    #
    # ★列の名前は**ゲームの画面と同じ言葉**にしてある。
    #   ⚠ 「ちから」と「こうげき力」は**別物**（こうげき力 = ちから + 武器）。
    #     どちらも「攻撃」と書くと、装備の効果が読み取れなくなる。
    #
    # ★すばやさは「つよさ」の画面のキャプチャから特定できた（2026-07-31）。
    #   それまでは分からなかったので**列を作っていなかった**
    #   （`docs/50-playbook.md`「分からないものは列を作らない」）。
    #
    # ★★ 2026-08-09: 見出しを**1文字**に縮めました（依頼者の指示）★★
    #
    #   > パーティーステータス表示見切れるので努力したい
    #   > ちから 力 素早さ 速 攻撃力 攻 しゅびりょく 守 次のLvまで 次
    #
    #   ⚠⚠ **「ちから」と「こうげき力」が別物である**という上の注意は
    #     そのまま生きています。★1文字にすると見分けが付かなくなるので、
    #     列見出しのツールチップにゲームと同じ言葉を必ず入れます
    #     （`COLUMN_TIPS`）。⚠ 入れ忘れると装備の効果が読み取れません。
    COLUMNS = ["名前", "LV", "HP", "MP",
               "力", "速", "攻", "守",
               "次", "状態"]

    #: ⚠ MP を持たない仲間の表示。★「0/0」にしないこと（切らしたと読めます）
    #:   2026-08-09 に「呪文なし」から短縮（依頼者の指示。列幅のため）。
    MP_NONE = "-"
    #: ★「-」だけでは分からないので、そのマスに説明を付ける
    MP_NONE_TIP = "呪文を覚えません（MP を持たない仲間です）"

    #: ★1文字の見出しが何を指すか。⚠ ゲームの画面と同じ言葉で書くこと
    COLUMN_TIPS = {
        "力": "ちから（素の力。こうげき力とは別）",
        "速": "すばやさ",
        "攻": "こうげき力（ちから ＋ 武器）",
        "守": "しゅび力（防具など）",
        "次": "次のLVまでの経験値",
    }

    def __init__(self, names=None) -> None:
        super().__init__()
        from PySide6.QtWidgets import QHeaderView, QTableWidget

        self._names = names
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._empty = QLabel("パーティを読めていません（セーブを読み込むと出ます）")
        self._empty.setStyleSheet("color:#8a8a8a;")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        # ★★ 1文字の見出しに、ゲームと同じ言葉のツールチップを付ける ★★
        #   ⚠ 「力」と「攻」は別物なので、ここが無いと読み分けられません。
        for index, name in enumerate(self.COLUMNS):
            tip = self.COLUMN_TIPS.get(name)
            if tip:
                self._table.horizontalHeaderItem(index).setToolTip(tip)
        # ★見出しの字を小さく（2026-08-09 / 依頼者の指示）。
        #   ⚠ 中身の字は変えません。読むのは値のほうです。
        self._table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { font-size:10px; padding:1px 2px; }")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        # ★高さを内容ぶんに詰める（表なのに余白で数行ぶん取られると意味が無い）
        self._table.setSizeAdjustPolicy(
            QTableWidget.SizeAdjustPolicy.AdjustToContents)
        # ★★ **名前の列を伸ばさない**（2026-07-31 / 依頼者の指摘）★★
        #   以前は列0（名前）だけ `Stretch` にしていたので、
        #   余った幅を**名前が全部吸って**いた。
        #   ⚠ 和名は**4文字まで**（あかり / サマルトリア は略称）なので、
        #     伸ばす意味が無く、他の列が窮屈になるだけだった。
        #   ★中身ぶんに詰めて**左詰め**にし、余りは**最後の列**に持たせる。
        header = self._table.horizontalHeader()
        for i in range(len(self.COLUMNS)):
            header.setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self._table)
        self._layout = layout

    def _row_height(self) -> int:
        return self._table.verticalHeader().defaultSectionSize()

    def update_party(self, members, actor: str | None = None) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QTableWidgetItem

        # ★★ 変わっていなければ作り直さない（2026-08-07 / 軽量化指示書 §5.4）★★
        #   ⚠ 1行 10列 × 3人 ＝ `QTableWidgetItem` を 30個、0.2秒ごとに
        #     捨てて作り直していました。★歩いていない間は中身が同じです。
        #   ⚠ 表示に使う名前も鍵に入れます（★呼び名の設定が後から入るため）。
        key = (snapshot(members), actor,
               tuple(self._names.label(m.name) for m in members)
               if self._names else None)
        if key == getattr(self, "_last_key", None):
            return
        self._last_key = key

        self._empty.setVisible(not members)
        self._table.setVisible(bool(members))
        self._table.setRowCount(len(members))

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        for r, m in enumerate(members):
            # ★いま入力を求められている人が分かるようにする（AI判断と対応づく）
            mark = " ◀" if actor and m.name == actor else ""
            label = self._names.label(m.name) if self._names else m.name

            # ★3つの状態を区別する。混ぜると「壊れている」ように見える。
            #     届いていない … エミュレータ側が古い（再起動で直る）
            #     最大レベル   … 次が無い
            #     それ以外     … 残りを出す
            if m.exp is None:
                nxt = "-（更新待ち）"
            elif m.next_level is None:
                nxt = "最大レベル"
            else:
                nxt = f"{m.exp_to_next:,}"

            marks = []
            if not m.alive:
                marks.append("戦闘不能")
            if m.poisoned:
                marks.append("毒")

            # ★つよさの4項目（2026-07-31）。
            #   ⚠ 読めないときは **`-`**（0 と混ぜない。0 は「弱い」に見える）
            def num(name: str) -> str:
                got = getattr(m, name, None)
                return "-" if got is None else str(got)

            values = [
                f"{label}{mark}",
                str(m.level),
                f"{m.hp:>3}/{m.max_hp:<3}",
                # ★2026-08-09: 「呪文なし」→「-」（依頼者の指示。列幅のため）
                #   ⚠ 「0/0」とは書きません。0 は「切らした」に見えるためです
                #     （ローレシアはそもそも呪文を覚えません）。
                #   ★意味はツールチップで補います（下の `_MP_NONE_TIP`）。
                f"{m.mp:>3}/{m.max_mp:<3}" if m.max_mp else self.MP_NONE,
                num("strength"),
                num("agility"),
                num("attack"),
                num("defense"),
                nxt,
                " / ".join(marks) if marks else "－",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                # ★数字の列は等幅（桁がそろって読みやすい）
                if 1 <= c <= 7:
                    item.setFont(mono)
                # ★HP も MP も「少なくなったら色を付ける」（依頼者の指定）。
                #   ⚠ MP を持たない人（ローレシア）は割合が 0 になるので、
                #     **最大MPがある人だけ**塗る。0/0 を「危険」と出さない。
                if c == 2:
                    color = _bar_color(m.hp_ratio)
                    if color:
                        item.setForeground(QColor(color))
                if c == 3 and m.max_mp:
                    color = _bar_color(m.mp_ratio)
                    if color:
                        item.setForeground(QColor(color))
                # ★「-」だけでは意味が分からないので説明を付ける（2026-08-09）
                if c == 3 and not m.max_mp:
                    item.setToolTip(self.MP_NONE_TIP)
                # ★状態は最後の列（列を足したのでずれる。番号を直接書かない）
                if c == len(values) - 1 and marks:
                    item.setForeground(QColor("#ff8a8a"))
                self._table.setItem(r, c, item)

        # ★表の高さを行数ぶんに固定する。余白で縦を食わせない
        if members:
            rows_h = self._row_height() * (len(members) + 1) + 4
            # ⚠ 横スクロールバーが出ると**最下行が隠れ**、縦スクロールになる
            #   （実機で発覚 / 2026-08-11）。★その分を足して全員を見せる。
            hbar = self._table.horizontalScrollBar()
            if hbar is not None:
                rows_h += hbar.sizeHint().height()
            self._table.setFixedHeight(rows_h)
            # ★★ パネル自体も表ぶんに固定（上位が縦の余りを積まないように）★★
            #   ⚠ こうしないと、入れ物が伸びて表の下に空白ができる（依頼者の指摘）。
            self.setFixedHeight(rows_h)
        else:
            # ★人が居ないときは案内文ぶんに戻す（固定を解く）
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)


# --- ⚠ `EnemyPanel`（敵の個体HP・脅威度）は削除しました（2026-08-11）----
#
#   依頼者「敵情報は、もはや用済みの資料だから不要だね。このロジック自体いらない」
#
#   ★経緯は `docs/history/ui-changes.md` に残してあります。
#   ⚠ 敵の**記録**（図鑑・遭遇）は別経路なので残っています。


class AiPanel(QWidget):
    """AI が何を選び、なぜそうしたか（指示書 5.4 A「AI判断」）。

    ★★ **3人ぶんを並べる**（2026-07-31 / 依頼者の指摘）★★

      > ３人分表示する（行動者毎に切り替えしない）
      > 選択が（回復の出番なし。たたかう）だらけな気がする

      ⚠ 以前は判断を**1つしか持っていなかった**ので、
        最後に入力した人で上書きされ、他の2人が見えなかった。
      ⚠ しかも記録するのは**回復を実行したときだけ**だったので、
        しない理由（MP不足・回復不要）は画面に届かず、
        いつも既定の「（回復の出番なし。たたかう）」が出ていた。

    ★いまの AI は heal_only。スコアや次点候補は**まだ存在しない**ので出さない。
      指示書の項目を空欄で並べると、実装済みに見えてしまう。
    """

    #: 1人ぶんの行を何行ぶん用意しておくか（加入は最大3人）
    MAX_MEMBERS = 3

    def __init__(self, names=None) -> None:
        super().__init__()
        self._names = names
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(2)
        grid.setHorizontalSpacing(8)

        # 見出し
        for c, caption in enumerate(("", "選択", "理由")):
            cap = QLabel(caption)
            cap.setStyleSheet("color:#8a8a8a;")
            grid.addWidget(cap, 0, c)

        self._member_rows: list = []
        for r in range(self.MAX_MEMBERS):
            who = QLabel("-")
            who.setAlignment(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignTop)
            action = QLabel("-")
            reason = QLabel("-")
            for w in (action, reason):
                w.setWordWrap(True)
            grid.addWidget(who, r + 1, 0)
            grid.addWidget(action, r + 1, 1)
            grid.addWidget(reason, r + 1, 2)
            self._member_rows.append(
                {"who": who, "action": action, "reason": reason})

        self._mode = QLabel("-")
        self._mode.setWordWrap(True)
        cap = QLabel("自動入力")
        cap.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        cap.setStyleSheet("color:#8a8a8a;")
        grid.addWidget(cap, self.MAX_MEMBERS + 1, 0)
        grid.addWidget(self._mode, self.MAX_MEMBERS + 1, 1, 1, 2)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)

    def _label_for(self, name: str) -> str:
        if self._names is None:
            return name
        return getattr(self._names, name, None) or name

    def update_state(self, state) -> None:
        decisions = list(getattr(state, "ai_decisions", None) or [])
        actor = state.actor

        # ★★ 判断が変わったときだけ書き直す（2026-08-07 / 軽量化指示書 §5.6）★★
        #   > ターン中に同じ判断が表示され続ける場合、
        #   > 200msごとに文字列を再設定しない。
        #   ⚠ ここで使う値だけを鍵にします（★`state` 全体だと `frame` や
        #     `time` が毎回変わり、**一度も止まりません**）。
        key = (snapshot(decisions), actor, state.force_auto,
               state.manual_latched, state.auto_input, state.danger_reason,
               tuple(self._label_for(str(d.get("name") or "-"))
                     for d in decisions))
        if key == getattr(self, "_last_key", None):
            return
        self._last_key = key

        for r, row in enumerate(self._member_rows):
            if r >= len(decisions):
                for w in row.values():
                    w.setVisible(False)
                continue
            d = decisions[r]
            for w in row.values():
                w.setVisible(True)

            name = str(d.get("name") or "-")
            # ★いま入力を求められている人に印を付ける（誰の番か分かる）
            mark = " ◀" if actor and name == actor else ""
            row["who"].setText(self._label_for(name) + mark)
            row["who"].setStyleSheet(
                "color:#8ad1ff;" if mark else "color:#8a8a8a;")

            # ⚠ **まだ判断していない**と「たたかう」を混ぜない。
            #   混ぜると「AI が殴ると決めた」のか「まだ決めていない」のか
            #   区別が付かない（0 と不明を混ぜないのと同じ話）。
            row["action"].setText(str(d.get("action") or "－"))
            row["reason"].setText(str(d.get("reason") or "－"))

        # ★「なぜ自動が効いていないか」をここに出す。
        #   ログを見に行かないと分からない状態にしない。
        if state.force_auto:
            text, color = "強制AUTO（安全機構を無視）", "#e0b34a"
        elif state.manual_latched:
            text, color = "手動（この戦闘は手動のまま）", "#ff8a8a"
        elif state.auto_input:
            text, color = "自動", "#8ad1ff"
        else:
            text, color = "手動", "#ff8a8a"
        if not state.auto_input and state.danger_reason:
            text += f" / {state.danger_reason}"
        self._mode.setText(text)
        self._mode.setStyleSheet(f"color:{color};")

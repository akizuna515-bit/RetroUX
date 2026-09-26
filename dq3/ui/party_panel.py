"""パーティの表（RX3-0019 / 2026-08-29）。

依頼者 2026-08-29:

    パーティーラベルに、所有ゴールドも表示する
    パーティーは 4 人分の枠を固定で撮っておく。HP、MP の MAX は 3 桁。

```text
パーティ                              G  —
┌────────────┬─────────┬─────────┐
│ ゆうしゃ    │ 999/999 │ 999/999 │
│ せんし      │ 999/999 │       — │
│ そうりょ    │ 999/999 │ 999/999 │
│ まほうつかい│ 999/999 │ 999/999 │
└────────────┴─────────┴─────────┘
```

## ⚠⚠ なぜ DQ2 の `PartyPanel` を使わないのか

★DQ2 のものは**中身に合わせて広がる**表で、⚠ 右パネルの最小幅を
**556px** まで押し上げました（2026-08-29 に実機で右へはみ出した）。
また ⚠ 人数ぶんしか行が無く、★依頼者の「4 人分の枠を固定」に合いません。

→ ★ここは**幅を数字で決めた**軽い表にします。
⚠ `retroux/` は変更しません（★DQ2 側はそのまま）。

## ★ゴールドは `$07AC`（2026-08-29 に確定）

⚠ 依頼者の「つよさ」画面の右上（`G 192` → `G 210`）と一致しました。
★RAM 全体の差分で、ここ 1 か所だけが 192 → 210 に動いています。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
                               QWidget)

#: ★枠は**いつも 4 人分**（⚠ 居なくても行を消さない / 依頼者 2026-08-29）
SLOTS = 4

#: ★★ 出す列（依頼者 2026-08-29）。
#:
#:   「名前はいらない。職業を１文字（勇、戦、僧みたいな）」
#:   「攻撃、守備、素早さなどは DQ2 同様に表示させたい」
#:   「あと運の良さも出そう」
#:
#: `(見出し, 幅, どこから)`
#: ⚠ 幅は**実測で決める**（★「999/999」が入りきる必要がある）。
#:
#: ⚠⚠ **合計が右パネルの幅を超えると、列が潰れて隣と重なる**
#:   （2026-08-29 に実際に重なった。★合計 426px に対して panel は 360px）。
#:   → ★合計を `TOTAL_W` で見張り、はみ出すなら幅を削る。
COLUMNS = (
    ("職", 24, "job"),
    ("LV", 26, "level"),
    ("HP", 56, "hp"),
    ("MP", 56, "mp"),
    ("力", 26, "strength"),
    ("速", 26, "agility"),
    ("攻", 26, "attack"),
    ("守", 26, "defence"),
    ("運", 26, "luck"),
    # ★★ 次のレベルまで、あと何点（依頼者 2026-08-29「次レベルまでの経験値」）。
    #   ⚠ ゲーム自身が**次に要る累計**を持っているので、★引き算は Lua 側で済ませる
    #   （`$6A3F` / `dq3/phase0/dev.lua`）。⚠ **表を推測で作らない**。
    ("次", 48, "to_next"),
)

#: ★列と列のすき間（⚠ 9 列あるので、ここを削ると効く）
COLUMN_GAP = 2

#: ★合計の幅（⚠ 右パネルはこれ以上ないと潰れる）
TOTAL_W = sum(w for _t, w, _k in COLUMNS) + COLUMN_GAP * (len(COLUMNS) - 1)

#: ★かなの並び（⚠ **濁点は 1 行上の別タイル**なので、ここには入らない）。
#:
#: ★`0x0B` = 「あ」から五十音が素直に並ぶ。
#:   ⚠ 名前「あかり」= `0B 10 32` で裏を取った（2026-08-29）。
KANA_BASE = 0x0B
KANA = ("あいうえお" "かきくけこ" "さしすせそ" "たちつてと" "なにぬねの"
        "はひふへほ" "まみむめも" "やゆよ" "らりるれろ" "わをん")


#: ⚠ 濁点・半濁点の付いたかな → **素のかな**（★タイルは素のほうを指す）
VOICED = {"が": "か", "ぎ": "き", "ぐ": "く", "げ": "け", "ご": "こ",
          "ざ": "さ", "じ": "し", "ず": "す", "ぜ": "せ", "ぞ": "そ",
          "だ": "た", "ぢ": "ち", "づ": "つ", "で": "て", "ど": "と",
          "ば": "は", "び": "ひ", "ぶ": "ふ", "べ": "へ", "ぼ": "ほ",
          "ぱ": "は", "ぴ": "ひ", "ぷ": "ふ", "ぺ": "へ", "ぽ": "ほ"}


def _tile(kana: str) -> int:
    """★かな 1 文字 → タイル番号（⚠ 濁点は落としてから引く）。"""
    return KANA_BASE + KANA.index(VOICED.get(kana, kana))


#: ★★ ファミコン版の職業（⚠ **8 つ**）と、頭文字 → 1 文字の札。
#:
#: 依頼者 2026-08-29「名前はいらない。職業を１文字（勇、戦、僧みたいな）」
#:
#: ⚠ 職業の**番地は分かっていない**。★ゲーム自身が「パーティの状態」の窓へ
#:   職業を**かな 1 文字**で出しているので、Lua がそれを拾って渡す
#:   （`dq3/phase0/dev.lua` / ⚠ 「：」`0x74` の**手前**）。
#:
#: ⚠⚠ **とうぞく（盗賊）はファミコン版に無い**（★スーパーファミコン版で
#:   追加された）。⚠ 入れておくと「と」を拾ったときに嘘の札が出る。
#:
#: ⚠ 「ぶとうか」の頭は**ふ＋濁点**で、★濁点は 1 行上の別タイルなので
#:   ここでは「ふ」で拾う。
JOBS = (
    ("ゆうしゃ", "勇"),      # ★実測（あかり / 2026-08-29）
    ("せんし", "戦"),        # ★実測（ハンソロ）
    ("そうりょ", "僧"),      # ★実測（エルシト）
    ("まほうつかい", "魔"),  # ★実測（ロミオ）
    ("ぶとうか", "武"),      # ⚠ かなの並びから起こしただけ（★未実測）
    ("しょうにん", "商"),    # ⚠ 同上
    ("あそびにん", "遊"),    # ⚠ 同上
    ("けんじゃ", "賢"),      # ⚠ 同上
)

JOB_INITIAL = {_tile(name[0]): mark for name, mark in JOBS}

#: ⚠ 危なくなったら色を変える境目（★DQ2 と同じ考え）
DANGER = 0.25
CAUTION = 0.50


def _value_label(width: int) -> QLabel:
    label = QLabel("—")
    label.setFixedWidth(width)
    label.setAlignment(Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter)
    label.setFont(QFont("Consolas", 10))
    return label


#: ★HP / MP の桁数（⚠ DQ3 は 3 桁まで。★列の幅も「999/999」で決めてある）
PAIR_DIGITS = 3


def _pair(now: int, most: int) -> str:
    """★`いま/最大` を**桁をそろえて**出す（RX3-0369 / 2026-09-22）。

    ⚠⚠ 依頼者「桁を合わせたい（★数字は 3 桁スペースサプレス）」。

    ```text
    ⚠ 今まで   30/31    124/124   ← ★縦に並べるとスラッシュの位置がずれる
    ★これから   30/ 31   124/124
    ```

    ⚠ 0 で埋めません（★`030` は別の数に見える）。★空白で右へ寄せます。
    ⚠ 列は右そろえ ＋ Consolas（等幅）なので、これで縦がそろいます。
    """
    return "%*d/%*d" % (PAIR_DIGITS, int(now), PAIR_DIGITS, int(most))


def _ratio_style(now: int, most: int) -> str:
    """★危ないときだけ色を付ける。

    ⚠⚠ 普通のときに色を**決め打ちしない**。明るいテーマだと
    白っぽい文字が背景に溶けて**読めなくなる**（2026-08-29 に実際に踏んだ）。
    ★何も指定しなければ、その環境の既定の色になる。
    """
    if not most:
        return "color: palette(mid);"
    ratio = now / most
    if ratio <= DANGER:
        return "color: #d64545; font-weight: bold;"
    if ratio <= CAUTION:
        return "color: #c2681a;"
    return ""


class Dq3PartyPanel(QWidget):
    """4 人ぶんの枠を**固定**で持つ表。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(COLUMN_GAP)
        root.setVerticalSpacing(2)

        # --- ★見出し（⚠ ここに所持金も出す / 依頼者 2026-08-29）----------
        head = QHBoxLayout()
        title = QLabel("パーティ")
        title.setStyleSheet("font-weight: bold; color: palette(mid);")
        head.addWidget(title)
        head.addStretch(1)
        self.gold = QLabel("G  —")
        self.gold.setStyleSheet("color: palette(mid);")
        self.gold.setToolTip(
            "所持ゴールド\n"
            "⚠ DQ3 の番地がまだ**確認できていません**（★推測では出しません）")
        head.addWidget(self.gold)
        root.addLayout(head, 0, 0, 1, len(COLUMNS))

        for col, (text, width, _key) in enumerate(COLUMNS):
            # ⚠⚠ **列そのものにも幅を持たせる。** ラベルへ `setFixedWidth` を
            #   付けただけだと、★列が狭いままで**隣と重なって読めなかった**
            #   （2026-08-29 に実際に重なった）。
            root.setColumnMinimumWidth(col, width)
            label = QLabel(text)
            label.setStyleSheet("color: palette(mid);")
            label.setFixedWidth(width)
            label.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            root.addWidget(label, 1, col)

        #: ★4 行ぶん作っておく（⚠ 居ない枠は「—」にするだけ）
        self.rows = []
        for i in range(SLOTS):
            cells = []
            for col, (_text, width, _key) in enumerate(COLUMNS):
                cell = _value_label(width)
                root.addWidget(cell, 2 + i, col)
                cells.append(cell)
            self.rows.append(cells)

        # ★右に余白を作って、列を**左へ寄せる**（⚠ 既定だと横に散らばる）
        root.setColumnStretch(len(COLUMNS), 1)
        root.setRowStretch(2 + SLOTS, 1)
        # ⚠ 中身で幅が広がらないようにする（★右パネルがはみ出した原因）
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)

    # --- ★更新 ----------------------------------------------------------

    def update_party(self, members, gold=None) -> None:
        """★4 行を書き換える。⚠ 行は**増減しない**。"""
        for i, cells in enumerate(self.rows):
            member = members[i] if i < len(members) else None
            # ★内訳は 1 人につき 1 度だけ作る（⚠ マスごとに作ると 10 倍になる）
            tips = self._tips(member)
            for cell, (_text, _w, key) in zip(cells, COLUMNS):
                text, style = self._cell(member, key)
                cell.setText(text)
                cell.setStyleSheet(style)
                cell.setToolTip(tips.get(key, ""))

        # ⚠ 届いていなければ「—」（★0 と区別する）
        self.gold.setText("G %s" % ("—" if gold is None else "{:,}".format(gold)))

    @staticmethod
    def _tips(member) -> dict:
        """★その人のヒント（⚠ 装備こみの値は**内訳**を出す / RX3-0284）。

        依頼者 2026-09-18「装備を入れ替えた時、ステータスが変わるようにしたい」。
        ⚠ 1 文字の見出しでは「何を足した値か」が読み取れないので、
        ★`derived_stats.explain` の内訳をそのまま出します
        （⚠ 文は `dq3/knowledge` 側で作る。★画面は ROM を読まない）。
        """
        if member is None:
            return {}
        from ..knowledge import derived_stats

        return derived_stats.explain(getattr(member, "derived", None))

    @staticmethod
    def _cell(member, key):
        """★1 マスの中身と色（⚠ 届いていなければ「—」）。"""
        if member is None:
            return ("—", "color: palette(mid);")
        if key == "job":
            tile = getattr(member, "job_tile", None)
            if tile is None:
                return ("—", "color: palette(mid);")
            # ⚠⚠ **数字と同じ大きさに見えるようにする。**
            #
            #   ★数字は Consolas 10pt だが、⚠ Consolas に漢字は無いので
            #   職業だけ**別のフォントへ落ちて**、太字と重なって大きく見えた
            #   （2026-08-29 / 依頼者「少し大きい気がしている」）。
            #   → ★太字をやめ、1 段小さくして高さをそろえる。
            return (JOB_INITIAL.get(int(tile), "？"), "font-size: 8pt;")
        if key == "hp":
            now, most = int(member.hp), int(member.max_hp)
            return (_pair(now, most), _ratio_style(now, most))
        if key == "mp":
            now, most = int(member.mp), int(member.max_mp)
            # ⚠ 魔法を使わない人は MP 0/0。★「—」にして目立たせない
            if not most:
                return ("—", "color: palette(mid);")
            return (_pair(now, most), _ratio_style(now, most))
        value = getattr(member, key, None)
        if value is None:
            return ("—", "color: palette(mid);")
        return ("%d" % int(value), "")

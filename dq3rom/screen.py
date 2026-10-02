"""画面（ネームテーブル）を文字に起こす（RX3-0016 / 2026-08-25）。

## ★なぜ画面から読むのか

DQ3 の ROM の中は、テキストもフォントも**圧縮されている**（`docs/design/dq3-findings.md`）。
⚠ 圧縮を解くのは大仕事で、しかも解いた結果を持つと**原作テキストを抱える**ことになる。

★画面から読めば、どちらの問題も消える。

    ネームテーブル（いま画面に出ているタイル番号） + 文字コード表  →  文字列

⚠ 保存するのは「読んだ」という事実であって、ROM のテキストではない。

## ⚠ DQ3 の濁点は「1 行上」に置かれる

DQ2 は濁点を文字の流れの中に混ぜるが、★DQ3 は**対象の文字の真上のマス**に置く。

```text
y=21        ゛          ← 濁点だけの行
y=22   に け る          → にげる
```

そのため 1 行だけ見ても読めない。★**上の行と一緒に**見る必要がある。
⚠ ここは DQ3 固有なので `retroux/core/text.py` には入れない（あちらは変えない）。

## 出典

- 文字コード表 … `dq3rom/profiles/dq3_fc_jp_rev0a.json` の `text`
- 濁点 `0x16A` … ★戦闘画面の「にげる / ぼうぎょ / どうぐ」で確認（2026-08-25）
"""

from __future__ import annotations

import dataclasses

#: 画面の升目
COLUMNS = 32
ROWS = 30
#: 背景のパターンテーブルが 1 側にある（★文字は 0x100 から）
PATTERN_BASE = 0x100
#: 濁点・半濁点（★対象文字の 1 行上に置かれる）
#:
#: ⚠⚠ 2026-09-07 訂正（RX3-0108）: 半濁点は **0x16B** です。
#:   ★もとは `0x169` でしたが、⚠ **どこにも根拠がありません**でした。
#:   ★根拠は profile の `_unresolved`（2026-09-03 / bank 14 `$89EC` が ゜ に `#$6B` を使う）。
#:   ⚠ 番号が違うと 2 つ同時に壊れます:
#:     ① `は` が `ぱ` にならない（★合成が起きない）
#:     ② 半濁点のマスが**本文に `<6B>` として漏れる**（★文字表に無いので unknown）
#:   ⚠ 実際に依頼者の会話 1 件で両方出ました（★下は**同じ形の架空の文** / RX3-0433）:
#:     `…むすこさんか？<6B>゛  ゛たいへん りっはなものたそ！`（★`りっぱ` が `りっは`）
#:   ⚠ `0x169` は**未確定のまま**です（★空いた番号を別の意味に流用しない）。
DAKUTEN = 0x16A
HANDAKUTEN = 0x16B
#: ★濁点・半濁点のマスそのもの（⚠ **下の行へ合成する印**で、本文の文字ではない）
MARK_TILES = (DAKUTEN, HANDAKUTEN)


def is_mark_tile(code: int) -> bool:
    """★そのタイルが「印」か（⚠ 印は人向けの本文に出さない / RX3-0108）。

    ⚠⚠ 印を**文字として出さない**のは、番号が正しいかどうかとは**別の守り**です。
    ★`0x16A` は文字表に `゛` があるので「読めた」ことになり、
    ⚠ `0x16B` は文字表に無いので `<6B>` になります。★どちらも本文には要りません。
    """
    return code in MARK_TILES
#: メニューのカーソル（▶）
CURSOR = 0x172

_VOICED = {
    "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
    "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
    "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
    "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
    "カ": "ガ", "キ": "ギ", "ク": "グ", "ケ": "ゲ", "コ": "ゴ",
    "サ": "ザ", "シ": "ジ", "ス": "ズ", "セ": "ゼ", "ソ": "ゾ",
    "タ": "ダ", "チ": "ヂ", "ツ": "ヅ", "テ": "デ", "ト": "ド",
    "ハ": "バ", "ヒ": "ビ", "フ": "ブ", "ヘ": "ベ", "ホ": "ボ",
    # ⚠ RX3-0216（2026-09-12）: 「ソ」が抜けていて、アニマルゾンビ を「アニマルソンビ」と覚えていた。
    #   ★ケ セ チ ツ ヘ は文字表に無い（ひらがなと共用）が、表に入ったときに同じ抜けを作らないよう並べておく
}
_SEMI_VOICED = {"は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ",
                "ハ": "パ", "ヒ": "ピ", "フ": "プ", "ヘ": "ペ", "ホ": "ポ"}


@dataclasses.dataclass(frozen=True)
class Line:
    """画面 1 行ぶん。"""

    row: int
    text: str
    unknown: tuple[int, ...]        # ⚠ 読めなかったタイル番号（黙って捨てない）
    has_cursor: bool

    @property
    def stripped(self) -> str:
        return self.text.replace("␣", " ").strip()


def read_screen(nametable, charset, base: int = 0) -> list[Line]:
    """ネームテーブル 1 面（1024 バイト）を行ごとの文字列にする。

    ⚠ `charset` は `retroux.core.text.Charset`（★DQ2 のものをそのまま使う）。
    """
    out: list[Line] = []
    for y in range(ROWS):
        row = nametable[base + y * COLUMNS: base + (y + 1) * COLUMNS]
        above = (nametable[base + (y - 1) * COLUMNS: base + y * COLUMNS]
                 if y > 0 else bytes(COLUMNS))
        chars: list[str] = []
        unknown: list[int] = []
        for x, b in enumerate(row):
            code = PATTERN_BASE + b
            if is_mark_tile(code):
                chars.append(" ")       # ★印は下の行へ合成済み（⚠ 文字として出さない）
                continue
            ch = charset.table.get(code)
            if ch is None:
                unknown.append(code)
                chars.append("·")
                continue
            mark = PATTERN_BASE + above[x] if x < len(above) else 0
            if mark == DAKUTEN:
                ch = _VOICED.get(ch, ch)
            elif mark == HANDAKUTEN:
                ch = _SEMI_VOICED.get(ch, ch)
            chars.append(ch)
        text = "".join(chars)
        out.append(Line(row=y, text=text, unknown=tuple(unknown),
                        has_cursor=(CURSOR - PATTERN_BASE) in row))
    return out


def find(lines: list[Line], needle: str) -> list[Line]:
    """その文字列が出ている行を返す。★「たたかう が出ているか」を見るのに使う。"""
    return [ln for ln in lines if needle in ln.text]


def cursor_row(nametable, base: int = 0) -> int | None:
    """カーソル（▶）がある行。⚠ 無ければ None（★推測で 0 を返さない）。"""
    for y in range(ROWS):
        row = nametable[base + y * COLUMNS: base + (y + 1) * COLUMNS]
        if (CURSOR - PATTERN_BASE) in row:
            return y
    return None

def unvoice(char: str) -> tuple[str, int | None]:
    """濁点つきの文字 → (基底の文字, 上に置くタイル)。

    ★DQ3 は濁点を**別のマス**に置くので、語をタイル列にするときは分解が要る。
    ⚠ 濁点が付かない文字はそのまま返す。
    """
    for base, voiced in _VOICED.items():
        if char == voiced:
            return base, DAKUTEN
    for base, semi in _SEMI_VOICED.items():
        if char == semi:
            return base, HANDAKUTEN
    return char, None

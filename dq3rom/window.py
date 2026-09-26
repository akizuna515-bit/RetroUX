"""画面の「枠つき窓」を見つけて、中身だけ取り出す（RX3-0016 / 2026-08-25）。

## ★★ なぜ窓ごとに分けるのか

DQ3 は意味のある文字を**ほとんど枠の中**に出す。★枠を見つけて中だけ取れば、
地形や飾りを拾わずに済む。

⚠ そしてもう 1 つ、実際に踏んだ理由がある。
**呪文の一覧が開くと窓が 2 つになり、カーソルも 2 つ出る**。
★画面を 1 枚の板として見ていたので、「どちらの窓のカーソルか」が分からず、
Auto 戦闘の呪文がいつまでも決まらなかった（`docs/design/dq3-findings.md`）。

## 枠のタイル（★実測。`work/dq3-probe` のセーブステートで確認）

```text
79 左上   7C 右上   7A 左下   7E 右下
77 上辺   7D 下辺   76 左縦   7B 右縦   78 ★縦の仕切り（窓の中）
```

⚠ 上辺の行に**文字が入る窓もある**（パーティの名前欄）。★「上辺は全部 77」と
決め打ちしないこと。

## ⚠ raw を一次情報にする

`tiles`（生のタイル番号）を必ず持つ。★文字コード表を直したら、
**過去のデータを読み直せる**ようにするため。文字列だけ保存しない。
"""

from __future__ import annotations

import dataclasses

COLUMNS, ROWS = 32, 30

#: 枠のタイル（★実測）
TOP_LEFT, TOP_RIGHT = 0x79, 0x7C
BOTTOM_LEFT, BOTTOM_RIGHT = 0x7A, 0x7E
EDGE_TOP, EDGE_BOTTOM = 0x77, 0x7D
EDGE_LEFT, EDGE_RIGHT = 0x76, 0x7B
#: ★窓の中の縦の仕切り（枠ではないが、文字でもない）
DIVIDER = 0x78

#: 窓として認めない大きさ。⚠ 1x1 の飾りを窓と呼ばない
MIN_WIDTH, MIN_HEIGHT = 3, 3


@dataclasses.dataclass(frozen=True)
class Window:
    """見つけた窓 1 つ。

    ⚠ `tiles` は**枠を除いた中身**の生タイル番号（行ごと）。★これが一次情報。
    """

    x: int
    y: int
    width: int
    height: int
    tiles: tuple[tuple[int, ...], ...]

    @property
    def key(self) -> str:
        """位置と大きさで決まる名前。★同じ窓かどうかの目印。"""
        return f"{self.x:02d}_{self.y:02d}_{self.width:02d}_{self.height:02d}"

    @property
    def digest(self) -> str:
        """中身の指紋。⚠ 変化を見るのに使う（★同じなら記録しない）。"""
        flat = ",".join(",".join(str(t) for t in row) for row in self.tiles)
        return f"{self.key}:{hash(flat) & 0xFFFFFFFF:08x}"

    def to_json(self) -> dict:
        return {
            "window": {"x": self.x, "y": self.y,
                       "width": self.width, "height": self.height},
            "window_id": self.key,
            # ★生のタイル番号。⚠ これを捨てない
            "raw_tiles": [list(row) for row in self.tiles],
        }


def _row(nametable, base: int, y: int) -> memoryview | bytes:
    return nametable[base + y * COLUMNS: base + (y + 1) * COLUMNS]


def find_windows(nametable, base: int = 0) -> list[Window]:
    """枠つきの窓を全部見つける。

    ⚠ 見つからなくても例外にしない（★窓が無い画面もある）。
    """
    out: list[Window] = []
    for y in range(ROWS - MIN_HEIGHT + 1):
        row = _row(nametable, base, y)
        for x in range(COLUMNS - MIN_WIDTH + 1):
            if row[x] != TOP_LEFT:
                continue
            # ★右上角を探す（⚠ 上辺に文字が入る窓もあるので、中身は問わない）
            right = None
            for k in range(x + MIN_WIDTH - 1, COLUMNS):
                if row[k] == TOP_RIGHT:
                    right = k
                    break
                if row[k] == TOP_LEFT:      # ⚠ 次の窓が始まった
                    break
            if right is None:
                continue
            # ★下辺を探す（左下角と右下角が揃う行）
            bottom = None
            for yy in range(y + MIN_HEIGHT - 1, ROWS):
                r = _row(nametable, base, yy)
                if r[x] == BOTTOM_LEFT and r[right] == BOTTOM_RIGHT:
                    bottom = yy
                    break
                # ⚠ 縦線が途切れたら、その窓ではない
                if r[x] != EDGE_LEFT and r[x] != BOTTOM_LEFT:
                    break
            if bottom is None:
                continue
            inner = tuple(
                tuple(_row(nametable, base, yy)[x + 1:right])
                for yy in range(y + 1, bottom)
            )
            out.append(Window(x=x, y=y, width=right - x + 1,
                              height=bottom - y + 1, tiles=inner))
    return out


def text_of(window: Window, nametable, charset, base: int = 0) -> tuple[str, list[int]]:
    """窓の中身を文字にする。

    ⚠ DQ3 の濁点は**1 行上のマス**にあるので、窓の外（上辺の行）も見る必要がある。
    ★読めなかったタイルは `<XX>` の形で残す（指示書 §6。⚠ 捨てない）。
    """
    from .screen import (DAKUTEN, HANDAKUTEN, PATTERN_BASE, _SEMI_VOICED,
                         _VOICED, is_mark_tile)

    lines: list[str] = []
    unknown: list[int] = []
    for i, row in enumerate(window.tiles):
        y = window.y + 1 + i
        above = _row(nametable, base, y - 1) if y > 0 else bytes(COLUMNS)
        chars: list[str] = []
        for j, b in enumerate(row):
            code = PATTERN_BASE + b
            if b == DIVIDER:
                chars.append(" ")           # ★仕切りは空白にする
                continue
            if is_mark_tile(code):
                # ★印のマス（濁点・半濁点）は**下の行へ合成済み**（RX3-0108）
                # ⚠⚠ ここを空白にしないと、⚠ 文字表に無い印が `<6B>` として
                #   本文に残り、★「印だけの行」を落とす下の判定も**すり抜けます**。
                chars.append(" ")
                continue
            ch = charset.table.get(code)
            if ch is None:
                unknown.append(code)
                chars.append(f"<{b:02X}>")  # ★raw が分かる形で残す
                continue
            x = window.x + 1 + j
            mark = PATTERN_BASE + above[x] if x < len(above) else 0
            if mark == DAKUTEN:
                ch = _VOICED.get(ch, ch)
            elif mark == HANDAKUTEN:
                ch = _SEMI_VOICED.get(ch, ch)
            chars.append(ch)
        lines.append("".join(chars).replace("␣", " ").rstrip())
    # ⚠ 濁点だけの行は落とす（★下の行に合成済みなので、残すと二重に見える）
    lines = [ln for ln in lines
             if ln.strip(u"゛゜ ") or not ln.strip()]
    # ⚠ 完全な空行だけ落とす（★意味のある空白は消さない）
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines), unknown

"""画面（32x30）を、スクロールを反映して組み立てる（RX3-0016 / 2026-08-26）。

★★ なぜ必要か ★★

ネームテーブルを **1 枚そのまま**画面だと思って読んでいた。⚠ これが間違いだった。

    実測（`DQ3_J.fc9` / NPC と会話中）:

        NT0 y=22  x=12: 79 77 77 … 7C   ← ★会話窓の上辺
        NT0 y= 0  x=12: 76 00 …    7B   ← ⚠ 続きが y=0 に回り込んでいる
        NT0 y= 1  x=12: 7A 7D …    7E   ← ★下辺

⚠ 窓は 30 行で**折り返す**ので、1 枚を素直に走査すると
**下辺が見つからず、窓ごと取りこぼす**。★実際に会話窓が 1 つも取れていなかった。

## ★スクロールはセーブステートに入っている

FCEUX の savestate は PPU の内部レジスタ（loopy）を分けて持っている。

    P_HT  横のタイル位置      → scroll_x = P_HT * 8 + PFHx
    P_VT  縦のタイル位置      → scroll_y = P_VT * 8 + P_FV
    P_Hx  横のネームテーブル   ┐★どの面を左上にするか
    P_Vx  縦のネームテーブル   ┘

⚠ `PFVx/PVxx/PHxx/PVTx/PHTx`（loopy_v のほう）は**フレーム末で 0 に戻る**ので使えない。
★`P_*`（loopy_t）が「次に使うスクロール」を持っている。

### ★実測で裏を取った

| | セーブステートから計算 | 実機 probe（`dq3_scroll_probe.lua`） |
| --- | --- | --- |
| `DQ3_J.fc7` | `HT=8 VT=10 H=1` → (64, 80) nt=1 | ★(64, 80) `$2000`=0x91 → nt=1 |

★一致した。⚠ これで**エミュを起動せずに**画面を組み立てられる。
"""

from __future__ import annotations

import dataclasses
import struct

COLUMNS = 32
ROWS = 30
PAGE = 0x400

#: MMC1 の制御レジスタ下位 2 ビット。
ONE_SCREEN_LOWER = 0
ONE_SCREEN_UPPER = 1
VERTICAL = 2
HORIZONTAL = 3


@dataclasses.dataclass(frozen=True)
class Scroll:
    """左上に映っている位置（ピクセル）と、どの面から始まるか。"""

    x: int
    y: int
    nametable: int          # ★0-3（bit0 = 横、bit1 = 縦）

    @property
    def tile_x(self) -> int:
        return self.x // 8

    @property
    def tile_y(self) -> int:
        return self.y // 8

    @property
    def fine_x(self) -> int:
        return self.x % 8

    @property
    def fine_y(self) -> int:
        return self.y % 8


def _u32(chunks, key: str) -> int:
    raw = chunks.get(key)
    if not raw or len(raw) != 4:
        return 0
    return struct.unpack("<I", bytes(raw))[0]


def scroll_of(chunks) -> Scroll:
    """savestate のチャンクからスクロールを取り出す。"""
    ht, vt = _u32(chunks, "P_HT"), _u32(chunks, "P_VT")
    fh, fv = _u32(chunks, "PFHx"), _u32(chunks, "P_FV")
    h, v = _u32(chunks, "P_Hx"), _u32(chunks, "P_Vx")
    return Scroll(x=ht * 8 + fh, y=vt * 8 + fv, nametable=(h & 1) | ((v & 1) << 1))


def mirroring_of(chunks) -> int:
    """MMC1 の制御レジスタからミラーリングを取り出す。

    ⚠ 実測では DQ3 は `0x0E` → **縦ミラー**（面が横に並ぶ）。
    """
    raw = chunks.get("DREG")
    if not raw:
        return VERTICAL
    return raw[0] & 3


def page_of(nametable: int, mirroring: int) -> int:
    """論理的な面番号（0-3）→ 実際に置かれている 1KB ページ（0 か 1）。"""
    if mirroring == VERTICAL:
        return nametable & 1
    if mirroring == HORIZONTAL:
        return (nametable >> 1) & 1
    if mirroring == ONE_SCREEN_UPPER:
        return 1
    return 0


def compose(ntar, scroll: Scroll, mirroring: int = VERTICAL) -> bytearray:
    """いま画面に映っている 32x30 のタイルを組み立てる。

    ⚠ 8 ドット未満のずれ（`fine_x` / `fine_y`）は切り捨てる。
    ★升目より細かいずれなので、タイルの読み取りには影響しない。
    """
    out = bytearray(COLUMNS * ROWS)
    for sy in range(ROWS):
        ty = scroll.tile_y + sy
        nt = scroll.nametable
        if ty >= ROWS:                      # ★縦に回り込むと面が切り替わる
            ty -= ROWS
            nt ^= 2
        for sx in range(COLUMNS):
            tx = scroll.tile_x + sx
            n = nt
            if tx >= COLUMNS:               # ★横も同じ
                tx -= COLUMNS
                n ^= 1
            src = page_of(n, mirroring) * PAGE + ty * COLUMNS + tx
            out[sy * COLUMNS + sx] = ntar[src]
    return out


def screen_of(chunks) -> bytearray:
    """savestate のチャンクから、そのまま画面を組み立てる。"""
    return compose(chunks["NTAR"], scroll_of(chunks), mirroring_of(chunks))

#: 各面の後ろ 64 バイトが属性（16x16 ごとに 2 ビット）。
ATTRIBUTE_AT = 0x3C0


def attribute_at(ntar, page: int, tx: int, ty: int) -> int:
    """その升のパレット番号（0-3）。

    ⚠ 属性は**面ごと**に置かれているので、タイルと同じ面から取る必要がある。
    ★組み立て後の画面で計算し直すと、面の境目で色がずれる。
    """
    byte = ntar[page * PAGE + ATTRIBUTE_AT + (ty // 4) * 8 + (tx // 4)]
    shift = ((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2
    return (byte >> shift) & 3


def compose_attributes(ntar, scroll: Scroll, mirroring: int = VERTICAL) -> bytearray:
    """`compose` と同じ並びで、升ごとのパレット番号を返す。"""
    out = bytearray(COLUMNS * ROWS)
    for sy in range(ROWS):
        ty = scroll.tile_y + sy
        nt = scroll.nametable
        if ty >= ROWS:
            ty -= ROWS
            nt ^= 2
        for sx in range(COLUMNS):
            tx = scroll.tile_x + sx
            n = nt
            if tx >= COLUMNS:
                tx -= COLUMNS
                n ^= 1
            out[sy * COLUMNS + sx] = attribute_at(ntar, page_of(n, mirroring), tx, ty)
    return out


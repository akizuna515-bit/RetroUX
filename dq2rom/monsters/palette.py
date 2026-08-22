"""NES の色番号 → RGB と、モンスターごとのパレット表。

## 色番号 → RGB

★★ **RGB の表は同梱しない。ファイルから読む。** ★★

  NES の色番号は 0..63 だが、実際の RGB は「どのパレットファイルを使うか」で
  変わる（エミュレータごとに違う）。**このプロジェクトの正解は
  利用者の FCEUX が出す色**なので、FCEUX が持っている `.pal` を読む。

    既定: `tools/fceux/palettes/FCEUX.pal`

  ⚠ FCEUX の画面キャプチャは、この値をさらに **255/252 倍**して出している
    （実測: `$37`=(252,216,168) が撮影では (255,219,170)）。
    見た目は変わらないが、**撮影と RGB がバイト一致しない**ことは覚えておく。
    照合は RGB ではなく**パレット番号**で行う（`validator.py`）。

## モンスターのパレット表（`bank4.asm:1170-1217`）

    先頭1バイト = (高位ニブル << 4) | 低位ニブル
    続けて  低位ニブル個 × 3バイト   （書き込み先 offset $00 側）
            高位ニブル個 × 3バイト   （書き込み先 offset $0D 側）

  ★実測（撮影10枚）では、**格子に置くタイル（bit6=1）は高位グループの色**、
    画素で置くタイル（bit6=0）は低位グループの色で描かれている。

  ⚠ 1グループに複数のパレットがある敵が **82体中6体**いる
    （最大は ID $52 の 低4/高3）。**どのタイルがどれを使うかは未解明**なので、
    先頭のパレットを使い、`confidence` を下げて出す。
"""

from __future__ import annotations

import dataclasses
import pathlib

BANK4_PRG_BASE = 0x10000
WINDOW_BASE = 0x8000

PAL_FILE_SIZE = 192          # 64色 × RGB
DEFAULT_PAL = pathlib.Path("tools/fceux/palettes/FCEUX.pal")

# FCEUX の画面キャプチャで観測される引き伸ばし（実測）
SCREENSHOT_SCALE = 255 / 252


class PaletteError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class NesPalette:
    """色番号 0..63 → RGB。"""

    colors: tuple[tuple[int, int, int], ...]
    source: str

    def rgb(self, index: int) -> tuple[int, int, int]:
        if not 0 <= index < len(self.colors):
            raise PaletteError(f"色番号が範囲外です: ${index:02X}")
        return self.colors[index]

    def as_screenshot(self) -> "NesPalette":
        """FCEUX の画面キャプチャに合わせて引き伸ばした表。"""
        scaled = tuple(
            tuple(min(255, round(v * SCREENSHOT_SCALE)) for v in c)
            for c in self.colors)
        return NesPalette(colors=scaled, source=self.source + "（撮影に合わせて引き伸ばし）")


def load_nes_palette(path: str | pathlib.Path | None = None) -> NesPalette:
    """`.pal`（64色 × RGB = 192バイト）を読む。"""
    p = pathlib.Path(path) if path else DEFAULT_PAL
    if not p.exists():
        raise PaletteError(
            f"パレットファイルがありません: {p}\n"
            "  FCEUX に付属する .pal を --palette で指定してください"
            "（例 tools/fceux/palettes/FCEUX.pal）")
    data = p.read_bytes()
    if len(data) < PAL_FILE_SIZE:
        raise PaletteError(
            f"パレットファイルが短すぎます（{len(data)} バイト / "
            f"{PAL_FILE_SIZE} バイト必要）: {p}")
    colors = tuple((data[i * 3], data[i * 3 + 1], data[i * 3 + 2])
                   for i in range(64))
    return NesPalette(colors=colors, source=str(p))


@dataclasses.dataclass(frozen=True)
class MonsterPalettes:
    """1体ぶんのパレット。色番号（0..63）のまま持つ。"""

    header: int
    low: tuple[tuple[int, int, int], ...]     # 書き込み先 offset $00 側
    high: tuple[tuple[int, int, int], ...]    # 書き込み先 offset $0D 側

    @property
    def ambiguous(self) -> bool:
        """★どのタイルがどのパレットを使うか決められない状態か。"""
        return len(self.low) > 1 or len(self.high) > 1

    def for_layer(self, on_grid: bool, index: int = 0) -> tuple[int, int, int] | None:
        """そのレイヤーの `index` 番目のパレット（無ければ None）。

        ★`index` は置き方の先頭バイト bit4-5（`Placement.palette` / RX-0051）。
        ⚠ 宣言より大きい番号は**無い**ものとして None（推測で先頭へ丸めない）。
        """
        group = self.high if on_grid else self.low
        if 0 <= index < len(group):
            return group[index]
        return None

    def to_json(self) -> dict:
        return {
            "header": f"0x{self.header:02X}",
            "low": [[f"0x{c:02X}" for c in p] for p in self.low],
            "high": [[f"0x{c:02X}" for c in p] for p in self.high],
            "ambiguous": self.ambiguous,
        }


def read_monster_palettes(prg: bytes, cpu_addr: int) -> MonsterPalettes:
    if not WINDOW_BASE <= cpu_addr <= 0xBFFF:
        raise PaletteError(
            f"パレットのポインタが切り替えバンクの窓の外です: ${cpu_addr:04X}")
    off = BANK4_PRG_BASE + (cpu_addr - WINDOW_BASE)
    if off >= len(prg):
        raise PaletteError(f"パレットが PRG の外です: 0x{off:05X}")
    header = prg[off]
    low_n, high_n = header & 0x0F, header >> 4
    need = 1 + 3 * (low_n + high_n)
    if off + need > len(prg):
        raise PaletteError("パレットが PRG からはみ出します")
    body = prg[off + 1:off + need]

    def group(start: int, n: int):
        return tuple(tuple(body[(start + i) * 3:(start + i) * 3 + 3])
                     for i in range(n))

    return MonsterPalettes(header=header,
                           low=group(0, low_n),
                           high=group(low_n, high_n))

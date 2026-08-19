"""実機で撮った絵と突き合わせる（指示書 §7 Phase M4 / §18）。

★★ **色では比べない。パレット番号で比べる。** ★★

  撮った絵は「パレットを当てたあとの色」で、こちらが持っているのは 0〜3 の番号。
  さらに FCEUX の画面キャプチャは色を 255/252 倍して出している。
  RGB で比べると、正しくても落ちる。

★比べ方（`research/probes/archived/probe_gfx3.py` で確立）:

  1. 展開したタイルを**集合**として持つ（置かれる向きのものだけ）
  2. 撮った絵を 8x8 に切り、どれかと**完全一致**するかを見る
  3. 色の対応（4色の選び方と並び）と、切れ目（0..7）を総当たりして
     一番よく合う組み合わせを採る

⚠ 2つ、落とすと**正しいのに落ちる**ものがある:

  a. **真っ黒なマス**。タイルが置かれていない格子はその戦闘の背景のまま
     なので撮影では真っ黒に写る。これを「不一致」と数えない。
  b. **別レイヤーが重なったマス**。撮影には最大7色出るので、
     4色に収まらないマスは判定から外す。★外した数は必ず報告する
     （都合の悪いマスを黙って捨てない）。
"""

from __future__ import annotations

import dataclasses
import itertools
import pathlib
import re
import struct
import zlib

from .decoder import Block
from .renderer import tile_indices

BLANK = tuple([0] * 64)
NAME_RE = re.compile(r"^([0-9A-Fa-f]{2})$")


class ValidateError(ValueError):
    pass


#: ★★ これ未満のマスしか比べられなかった撮影は「材料不足」とする ★★
#:
#: ⚠⚠ 2026-08-01 に実データで踏みました。遊んでいる最中に撮れた
#:   敵ID 0x30 の絵は、**判定できたマスが4つ**しかなく（他の敵は 9〜28）、
#:   そのうち2つが合わずにテスト全体が赤くなりました。
#:
#: ★4マスでは「展開が間違っている」とも「撮影が悪い」とも言えません。
#:   ⚠ **黙って除外しません。** 「N枚は材料不足で判定できず」と
#:     件数を出します（0 と 不明 を混ぜない）。
MIN_JUDGED = 8


@dataclasses.dataclass(frozen=True)
class Comparison:
    monster_id: int
    matched: int
    judged: int
    skipped: int
    offset: tuple[int, int] | None
    note: str = ""
    #: ★ROM の絵の大きさ（⚠ 分からなければ None）
    expected_size: tuple[int, int] | None = None
    #: ★撮影の大きさ
    shot_size: tuple[int, int] | None = None
    #: ★形が合った画素数と全画素数（`compare_shape`）
    shape_matched: int = 0
    shape_total: int = 0

    @property
    def missing(self) -> tuple[int, int]:
        """ROM の絵に対して**写っていない**幅と高さ（px）。★負なら余分。"""
        if self.expected_size is None or self.shot_size is None:
            return (0, 0)
        return (self.expected_size[0] - self.shot_size[0],
                self.expected_size[1] - self.shot_size[1])

    @property
    def shape_ok(self) -> bool:
        """★★ **形が1画素の狂いもなく一致したか**（2026-08-14）★★

        ⚠⚠ こちらが**決定的**です。`ok`（タイルの集合との突き合わせ）は
          `on_grid` のレイヤーしか見ないので、⚠ **重なったマスを
          「合わない」と言います**（シドーで実際にそうなりました）。
        """
        return self.shape_total > 0 and self.shape_matched == self.shape_total

    @property
    def shape_rate(self) -> float:
        return self.shape_matched / self.shape_total if self.shape_total else 0.0

    @property
    def ok(self) -> bool:
        return self.judged > 0 and self.matched == self.judged

    @property
    def enough(self) -> bool:
        """**不一致を不一致と言い切れる**だけのマスがあったか。

        ★★ **成功は成功。失敗したときだけ材料の量を問う。** ★★

        ⚠⚠ 最初は「judged が少なければ材料不足」と書き、13枚が
          そちらへ落ちました。ところが**うち12枚は 6/6・7/7 で
          完全に一致**していました。前は合格だったものを、
          こちらの都合で判定不能に落としていたのです。

        ★全部合っているなら、マスが少なくても「合っている」で正しい。
          疑わしいのは「少ないマスで、しかも合わない」ときだけ。

        """
        return self.ok or self.judged >= MIN_JUDGED

    @property
    def verdict(self) -> str:
        """★★ **3つに分ける**（合う / 合わない / 材料不足）★★

        ⚠ 2つに分けると、材料不足を「合わない」に混ぜることになり、
          遊ぶたびにテストが赤くなります（実際にそうなりました）。
        """
        if self.ok:
            return "match"
        return "mismatch" if self.judged >= MIN_JUDGED else "insufficient"

    @property
    def rate(self) -> float:
        return self.matched / self.judged if self.judged else 0.0


# --- PNG を読む（外部ライブラリなし）----------------------------------


def read_png_rgb(path: str | pathlib.Path) -> tuple[int, int, list[list[tuple]]]:
    """撮影した PNG を読む。8bit の RGB/RGBA・非インターレースだけ。

    ★`gui.savescreenshotas` が出す PNG を読めれば足りる。
      それ以外は**推測で読まずに例外**にする。
    """
    data = pathlib.Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValidateError(f"PNG ではありません: {path}")
    pos = 8
    width = height = depth = ctype = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I", data[pos:pos + 4])[0], data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _c, _f, interlace = struct.unpack(
                ">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                raise ValidateError(
                    f"対応していない PNG です（深さ{depth} 種別{ctype} "
                    f"インターレース{interlace}）: {path}")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None:
        raise ValidateError(f"IHDR がありません: {path}")

    channels = 3 if ctype == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = []
    prev = bytearray(stride)
    at = 0
    for _y in range(height):
        filt = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        at += stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if filt == 0:
                pass
            elif filt == 1:
                line[i] = (line[i] + a) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + b) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
            else:
                raise ValidateError(f"知らないフィルタ {filt}: {path}")
        out.append([tuple(line[x * channels:x * channels + 3])
                    for x in range(width)])
        prev = line
    return width, height, out


# --- 比べる -----------------------------------------------------------


def art_size(blocks: list[Block]) -> tuple[int, int] | None:
    """ROM の絵の大きさ（px）。★置くタイルが1枚も無ければ None。

    ⚠ `renderer.render()` と**同じ計算**にすること（★食い違うと
      「切れている」の判定がずれる）。
    """
    spots = [p for b in blocks for p in b.placements]
    if not spots:
        return None
    xs = [p.x for p in spots]
    ys = [p.y for p in spots]
    return (max(xs) + 8 - min(xs), max(ys) + 8 - min(ys))


#: ★形を当てるときに ROM の絵の周りへ足す余白（px）。
#:  ⚠ 切り出し（`retroux/core/art/trim.py`）は `MARGIN = 2` の余白を付ける。
#:    ★足さないと「撮影のほうが大きい」になって当てられない。
SHAPE_PAD = 6


def silhouette(blocks: list[Block]) -> tuple[int, int, list[int]]:
    """★★ **両方のレイヤーを重ねた「形」** ★★（2026-08-14）

    戻り値は `(幅, 高さ, 行ごとのビット列)`。1 が不透明。

    ## ⚠⚠ なぜ要るか

      `placed_tiles()` は **`on_grid` のタイルだけ**を集めます。
      ところが実機の画面は**両方のレイヤーが重なった姿**です。
      ★重なったマスは「ROM に無いタイル」に見えるので、
        `compare()` は**正しいのに不一致**と言います。

      実測（2026-08-14 / シドー 0x52）:

          `compare()`       34/37 マス   ⚠ 3マスが不一致
          こちらの突き合わせ 6072/6072 画素  ★**完全一致**

      ★合わなかった3マスは、どれも「ROM の形＋別レイヤーの画素」でした。
        ⚠ **展開は正しく、比べ方が足りていなかった**のです。

    ## ★ 色は使わない

      色はレイヤーごとのパレットの当て方で変わります（⚠ シドーでは
      448 画素で桃色と鮭色が入れ替わっていました）。★形は変わりません。
    """
    spots = [(b, p) for b in blocks for p in b.placements]
    if not spots:
        return (0, 0, [])
    xs = [p.x for _b, p in spots]
    ys = [p.y for _b, p in spots]
    x0, y0 = min(xs), min(ys)
    width = max(xs) + 8 - x0 + SHAPE_PAD * 2
    height = max(ys) + 8 - y0 + SHAPE_PAD * 2
    rows = [0] * height
    for block, place in spots:
        px = tile_indices(block.variants[place.variant])
        top = place.y - y0 + SHAPE_PAD
        left = place.x - x0 + SHAPE_PAD
        for dy in range(8):
            bits = 0
            for dx in range(8):
                if px[dy][dx]:
                    bits |= 1 << (left + dx)
            rows[top + dy] |= bits
    return (width, height, rows)


def shot_shape(shot: list[list[tuple]],
               background: tuple = (0, 0, 0)) -> list[int]:
    """撮影を「不透明かどうか」のビット列にする。

    ⚠ 背景（純黒）は透明扱い。★敵の絵に純黒が含まれると当てられないので、
      そのときは一致率が下がる（★呼ぶ側が件数で気づけるようにする）。
    """
    out = []
    for row in shot:
        bits = 0
        for x, c in enumerate(row):
            if c != background:
                bits |= 1 << x
        out.append(bits)
    return out


def compare_shape(shot: list[list[tuple]], mask: tuple[int, int, list[int]]
                  ) -> tuple[int, int, tuple[int, int] | None]:
    """形で突き合わせる。戻り値 `(合った画素, 全画素, ずらし)`。

    ★ずらしは総当たり。⚠ ビット演算で数えるので、素直に書くより 100 倍速い
      （★全 79 枚で 7 分 → 数秒）。
    """
    mw, mh, mrows = mask
    sh = len(shot)
    sw = len(shot[0]) if sh else 0
    if not sw or not mrows or sw > mw or sh > mh:
        return (0, sw * sh, None)
    srows = shot_shape(shot)
    full = (1 << sw) - 1
    best = (-1, None)
    for oy in range(mh - sh + 1):
        for ox in range(mw - sw + 1):
            same = 0
            for y in range(sh):
                diff = (((mrows[oy + y] >> ox) & full) ^ srows[y])
                same += sw - diff.bit_count()
            if same > best[0]:
                best = (same, (ox, oy))
    return (best[0], sw * sh, best[1])


def placed_tiles(blocks: list[Block], on_grid: bool = True) -> set[tuple[int, ...]]:
    """そのレイヤーに置かれる向きのタイルだけを集める。"""
    out = {BLANK}
    for block in blocks:
        for place in block.placements:
            if place.on_grid == on_grid:
                px = tile_indices(block.variants[place.variant])
                out.add(tuple(v for row in px for v in row))
    return out


def compare(tiles: set[tuple[int, ...]], width: int, height: int,
            shot: list[list[tuple]]) -> Comparison:
    colors: list[tuple] = []
    for row in shot:
        for c in row:
            if c not in colors:
                colors.append(c)
    if len(colors) < 2:
        return Comparison(-1, 0, 0, 0, None, "色が1種しかない")
    if len(colors) > 8:
        return Comparison(-1, 0, 0, 0, None, f"色が {len(colors)} 種と多すぎる")

    best = Comparison(-1, 0, 0, 0, None)
    for dy in range(8):
        for dx in range(8):
            cols, rows = (width - dx) // 8, (height - dy) // 8
            if cols < 1 or rows < 1:
                continue
            cells = [tuple(shot[dy + by * 8 + y][dx + bx * 8 + x]
                           for y in range(8) for x in range(8))
                     for by in range(rows) for bx in range(cols)]
            for subset in itertools.combinations(colors, min(4, len(colors))):
                for perm in itertools.permutations(range(4), len(subset)):
                    table = dict(zip(subset, perm))
                    matched = judged = skipped = 0
                    for cell in cells:
                        mapped = tuple(table.get(c, -1) for c in cell)
                        if -1 in mapped:
                            skipped += 1
                            continue
                        judged += 1
                        if mapped in tiles:
                            matched += 1
                    if (matched, judged) > (best.matched, best.judged):
                        best = Comparison(-1, matched, judged, skipped, (dx, dy))
    return best


def validate_dir(rom_prg: bytes, entries, capture_dir: pathlib.Path,
                 decode) -> list[Comparison]:
    """`<敵ID2桁>.png` という名前の撮影を全部見る。"""
    out: list[Comparison] = []
    for path in sorted(pathlib.Path(capture_dir).glob("*.png")):
        m = NAME_RE.match(path.stem)
        if not m:
            continue
        mid = int(m.group(1), 16)
        if mid >= len(entries) or not entries[mid].in_range:
            continue
        entry = entries[mid]
        blocks = decode(rom_prg, entry.graphics_addr, entry.count)
        tiles = placed_tiles(blocks, on_grid=True)
        width, height, shot = read_png_rgb(path)
        got = compare(tiles, width, height, shot)
        # ★★ **形でも突き合わせる**（2026-08-14）★★
        #   ⚠ タイルの集合だけだと、重なったマスを「合わない」と言う。
        shape_matched, shape_total, _off = compare_shape(
            shot, silhouette(blocks))
        out.append(dataclasses.replace(
            got, monster_id=mid,
            expected_size=art_size(blocks), shot_size=(width, height),
            shape_matched=shape_matched, shape_total=shape_total))
    return out

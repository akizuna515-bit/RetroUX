"""地図の升を、ゲーム内のタイルの絵にする（RX3-0032 / 2026-08-31）。

## ★★ 何をするか

```text
地図バッファの 1 バイト
  → ★tileset（$7200）+ 索引*4 の 4 バイト（左上・右上・左下・右下）
  → ★CHR の 8x8 パターン 4 枚
  → 16x16 の絵
```

⚠⚠ **この経路は実測で確かめてあります。** ★依頼者のセーブ 5 本、
634 升すべてが実機のネームテーブルと一致しました
（`tests/test_dq3_map_tiles.py` / `docs/research/260831_dq3-map-tiles.md`）。

## ⚠ bit5 の升は「索引 32」

```text
raw の bit5（0x20）が立つ → ★tileset の索引 **32**（地形に関係なく）
それ以外                  → ★索引 = raw & 0x1F
```

⚠ 索引 32 が何かは**未確認**（★暗闇／未踏あたり）。

## ⚠⚠ 材料はどこから来るか

```text
★tileset  カートリッジ RAM $7200（⚠ セーブの `WRAM` の +0x1200）
★CHR      CHR-RAM 8KB      （⚠ セーブの `CHRR`）
★パレット  $3F00 の 32 バイト（⚠ セーブの `PRAM`）
```

⚠⚠ **どれも ROM には無く、実行時の RAM です。**
★だから「セーブステートから作る」のが今のところ唯一の道です。
⚠ 実機に追随させるには、Lua がこれらを送る仕掛けが要ります（★別の段）。
"""

from __future__ import annotations

import dataclasses
import pathlib

#: ★カートリッジ RAM は $6000 から
TILESET_OFF = 0x1200          #: ★$7200（⚠ 4 バイト × 64 タイル）
#: ★★ 升ごとのパレット組（RX3-0032 / 2026-08-31 実測）
#:
#:   ⚠⚠ `$7300` に **1 バイト 1 索引**で入っています。
#:     ★依頼者のセーブ 5 本 / 634 升すべてで、実機の属性表と一致しました。
#:   ⚠ WRAM 8192 バイトを総当たりして、**ここ 1 か所だけ**が合いました。
PALETTE_OFF = 0x1300          #: ★$7300
MAP_BUF_OFF = 0x1400          #: ★$7400
#: ★1 タイルぶんの並び（左上・右上・左下・右下）
QUAD = 4
#: ★tileset の本数（⚠ 64。★索引 62/63 は空で、64 番目からは `$7300` の別表）
TILES = 64
#: ⚠ bit5 が立つ升は、この索引で描かれる（★実測）
DARK_BIT, DARK_INDEX = 0x20, 32
TERRAIN_MASK = 0x1F
#: ★升 1 つは 16x16 ピクセル
CELL = 16
#: ★BG のパターンは CHR の後ろ半分
PATTERN_TABLE = 0x1000

#: ⚠ NES の色（★`dq3rom/render.py` と同じものを使う）
def _nes_palette():
    from dq3rom import render

    return render.NES_PALETTE


class TileArtError(ValueError):
    """⚠ 絵を作れなかった。★黙って空を返さない。"""


#: ★升の**層**（値の上位 3 bit / RX3-0191）
LAYER_MASK = 0xE0


def index_of(raw: int, hero_raw: int | None = None) -> int:
    """★升の 1 バイト → tileset の索引。

    ⚠⚠ ここが唯一の実装。★呼ぶ側で `& 0x1F` と書かないこと。

    ## ⚠⚠ 黒く塗るのは「層が勇者の升と違う」とき（RX3-0191 / 2026-09-12）

      ★以前は「bit5（0x20）が立つ升 = 黒」でした。⚠ 町では勇者が層 0 に立つので**たまたま**合い、
        ⚠ 洞窟（勇者が層 0x20）では**白黒が逆**になっていました
        （依頼者「エルフの森の近辺洞窟で、画面とMAPの表示が異なる（MAPは黒表示）」）。
      ★ゲームは「升の層（& 0xE0）が勇者の升の層と違えば黒」で描く
        （★セーブ 8 本の画面と 1,417 / 1,417 升で一致 / 町・洞窟とも）。
      ⚠ `hero_raw`（勇者の升の値）が無ければ、今までどおり bit5 で決める（★町ではどちらも同じ）。
    """
    if hero_raw is not None:
        return DARK_INDEX if ((raw ^ hero_raw) & LAYER_MASK) else (raw & TERRAIN_MASK)
    return DARK_INDEX if (raw & DARK_BIT) else (raw & TERRAIN_MASK)


@dataclasses.dataclass(frozen=True)
class TileArt:
    """★1 つの地図ぶんの「升 → 16x16 の絵」。"""

    #: ★索引 → 16x16 の RGB（⚠ `bytes`。長さ 16*16*3）
    cells: dict[int, bytes]

    def block(self, raw: int, hero_raw: int | None = None):
        """★升の 1 バイトから、その絵。⚠ 無ければ None。★`hero_raw` は勇者の升の値（層の決まり / RX3-0191）。"""
        return self.cells.get(index_of(raw, hero_raw))

    def known(self) -> int:
        return len(self.cells)


def _tile_rows(chr_data: bytes, index: int):
    """★8x8 の 2bpp を 0..3 で返す（⚠ `dq3rom/render.py` と同じ形）。"""
    o = PATTERN_TABLE + index * 16
    if o + 16 > len(chr_data):
        raise TileArtError("⚠ CHR が足りません（★タイル %d）" % index)
    out = []
    for y in range(8):
        lo, hi = chr_data[o + y], chr_data[o + y + 8]
        out.append([((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1)
                    for x in range(8)])
    return out


def build(wram: bytes, chr_data: bytes, pram: bytes, *,
          group=None, indices=None) -> TileArt:
    """★材料から `TileArt` を作る。

    ⚠ `group` を渡すと、その 4 色の組で全部を描きます（★見比べ用）。
      ★渡さなければ **`$7300` の実測の表**を使います（⚠ こちらが本物）。
    """
    if len(chr_data) < 0x2000:
        raise TileArtError("⚠ CHR が %d バイトしかありません（8192 のはず）"
                           % len(chr_data))
    if len(pram) < 32:
        raise TileArtError("⚠ パレットが %d バイトしかありません（32 のはず）"
                           % len(pram))
    if len(wram) < TILESET_OFF + 512:
        raise TileArtError("⚠ WRAM が足りません（★$7200 が読めない）")

    nes = _nes_palette()

    def four(g):
        """★4 色（⚠ 色 0 は共通の背景色。NES の決まり）。"""
        base = (g % 4) * 4
        return [nes[(pram[0] if i == 0 else pram[base + i]) & 0x3F]
                for i in range(4)]

    want = range(TILES) if indices is None else indices
    cells = {}
    for idx in want:
        # ★★ 升ごとのパレット組（⚠ `$7300` の実測の表）
        g = group if group is not None else wram[PALETTE_OFF + idx]
        colours = four(g)
        o = TILESET_OFF + idx * QUAD
        quad = wram[o:o + QUAD]
        if len(quad) < QUAD or not any(quad):
            continue                      # ⚠ 空の索引は作らない
        px = bytearray(CELL * CELL * 3)
        for part, pattern in enumerate(quad):
            ox, oy = (part % 2) * 8, (part // 2) * 8
            rows = _tile_rows(chr_data, pattern)
            for y in range(8):
                for x in range(8):
                    r, g, b = colours[rows[y][x]]
                    at = ((oy + y) * CELL + ox + x) * 3
                    px[at], px[at + 1], px[at + 2] = r, g, b
        cells[idx] = bytes(px)
    if not cells:
        raise TileArtError("⚠⚠ 1 つも作れませんでした（★材料を疑うこと）")
    return TileArt(cells=cells)


#: ★実行時の材料の置き場（⚠ `dq3/phase0/map_art.lua` が書く）
RUNTIME_DIR = "work/runtime/dq3-probe"
RUNTIME_JSON, RUNTIME_BIN = "map_art.json", "map_art.bin"


@dataclasses.dataclass(frozen=True)
class RuntimeArt:
    """★実行時に受け取った 1 つの地図ぶん（RX3-0043 / 2026-09-01）。

    ⚠ `TileArt`（絵）に加えて、★**そのときの地図そのもの**も持ちます。
      画面は「歩いた記録」で描きますが、⚠ 地形の生の値はこちらが持ちます。
    """

    art: TileArt
    kind: int
    map_id: int
    width: int
    height: int
    cells: bytes                  #: ★`y * width + x` で 1 升 1 バイト
    chr_checksum: int

    def at(self, x: int, y: int):
        """★その升の生の値。⚠ 外なら None。"""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self.cells[y * self.width + x]

    @property
    def key(self) -> str:
        """★どの地図か（⚠ 変わったら作り直す目印）。"""
        return "%d/%d/%dx%d" % (self.kind, self.map_id, self.width, self.height)


#: ★NES のパレットで「黒」になる値（⚠ 下位 4 ビットで見る）
#:
#:   ```text
#:   $0F $1F $2F $3F   ★黒
#:   $0D $1D $2D $3D   ⚠ 「黒より黒い」
#:   ```
BLACK_ENTRIES = (0x0F, 0x0D)


def is_dark(pram: bytes) -> bool:
    """★★ そのパレットでは何も見えないか（RX3-0046 / 2026-09-02）。

    ⚠⚠ **32 個ぜんぶが黒のときだけ** `True` です。
      ★1 つでも色があれば、暗い部屋であって暗転ではありません。

    ## ⚠ なぜ Python 側にも要るのか

      ★止めるのは Lua 側（`map_art.lua`）です。⚠ ですが、
      **前に書かれた壊れたファイル**がそのまま残ります。

      ⚠⚠ 依頼者の実機で `pram` が `0f` x 32 になり、
        ★64 索引すべての絵が真っ黒になりました（2026-09-02）。
        → ⚠ 真っ黒な地図を出すより、★色ブロックに戻すほうがましです。
    """
    if not pram:
        return True
    return all((b & 0x0F) in BLACK_ENTRIES for b in pram)


def is_colorless(pram: bytes) -> bool:
    """★★ そのパレットに色が無いか（RX3-0061 / 2026-09-03）。

    ⚠⚠ `is_dark` は「**32 個ぜんぶが黒**」しか弾きません。
      ★戦闘に入る一瞬の**白い画面**は素通りします。

    ```text
    2026-09-03 の実機（依頼者「世界地図に色がない」）
      ローカル  0F 30 11 21 0F 27 37 15 …   ★正しい
      世界      00 30 00 10 00 10 20 20 …   ⚠ 下位 4bit が全部 0
                                             ＝ NES パレットの灰色の列
    ```

    ## ⚠ なぜ Python 側にも要るのか

      ★止めるのは Lua 側です。⚠ ですが、**前に書かれた白黒のファイル**が
      そのまま残ります（★実際に一日じゅう白黒のままでした）。
      → ⚠ 白黒の地図を出すより、★色ブロックに戻すほうがましです。
    """
    if not pram:
        return True
    return all((b & 0x0F) == 0 for b in pram)


def from_runtime(base=None, *, group=None) -> RuntimeArt | None:
    """★★ 実機が書き出した材料から作る（⚠ 無ければ `None`）。

    ⚠⚠ **例外を投げません。** ★材料が無い・壊れている・古いときは
      `None` を返し、画面は色ブロックのままにします（指示書 §1）。

    ```text
    work/runtime/dq3-probe/map_art.json   ★小さい情報（⚠ 毎回書かれる）
    work/runtime/dq3-probe/map_art.bin    ⚠ CHR 8KB（★変わったときだけ）
    ```
    """
    import json
    import pathlib

    root = pathlib.Path(base) if base is not None else (
        pathlib.Path(__file__).resolve().parents[2] / RUNTIME_DIR)
    try:
        body = json.loads((root / RUNTIME_JSON).read_text(encoding="utf-8"))
        chr_data = (root / RUNTIME_BIN).read_bytes()
    except (OSError, ValueError):
        return None                    # ⚠ まだ書かれていない／読めない

    # ★世界地図（RX3-0061）。⚠ アレフガルド（2）も同じ道（RX3-0316）
    if int(body.get("kind", 1)) in WORLD_NAMES:
        return _world_runtime(body, chr_data)
    try:
        # ★16 進の文字列から戻す
        tileset = bytes.fromhex(body["tileset"])
        groups = bytes.fromhex(body["palette_group"])
        pram = bytes.fromhex(body["pram"])
        cells = bytes.fromhex(body["map"])
        width, height = int(body["width"]), int(body["height"])
    except (KeyError, TypeError, ValueError):
        return None                    # ⚠ 形が違う（★黙って作らない）

    if len(cells) != width * height:
        return None                    # ⚠⚠ 数が合わない（★信じない）

    if is_dark(pram):
        # ⚠⚠ **暗転中に取られた材料**（RX3-0046）。
        #   ★これで絵を作ると 64 索引すべてが真っ黒になります。
        #   ⚠ 色ブロックに戻したほうが、まだ地形が分かります。
        return None

    # ★`build()` は WRAM の並びを期待するので、その形に組み直す
    wram = bytearray(TILESET_OFF + 512)
    wram[TILESET_OFF:TILESET_OFF + len(tileset)] = tileset
    wram[PALETTE_OFF:PALETTE_OFF + len(groups)] = groups
    try:
        art = build(bytes(wram), chr_data, pram, group=group)
    except TileArtError:
        return None                    # ⚠ 材料が足りない（★落とさない）

    return RuntimeArt(art=art, kind=int(body.get("kind", 1)),
                      map_id=int(body.get("map_id", 0)),
                      width=width, height=height, cells=cells,
                      chr_checksum=int(body.get("chr_checksum", 0)))


#: ★世界地図（RX3-0061 / 2026-09-02）
KIND_WORLD = 0
#: ★アレフガルド（下の世界 / RX3-0316 / 2026-09-20）
#:
#:   ⚠⚠ 依頼者「アレフガルドで CHR も表示されない」。
#:   ★測った結果、**対応表も升の定義も上の世界と同じ**でした
#:     （`$9A` tileset = 0 / `$7200`・`$7300` は全バイト一致 /
#:      画面と `world_alefgard` が 181/181 一致）。
#:   ⚠ 違うのは **CHR の絵柄とパレット**だけなので、★実機から取り直せば足ります。
KIND_ALEFGARD = 2
#: ★種別 → ROM の世界地図の名前（⚠ `terrain.WORLD_TABLE` と同じ）
WORLD_NAMES = {KIND_WORLD: "world_main", KIND_ALEFGARD: "world_alefgard"}
WORLD_METATILES = (pathlib.Path(__file__).resolve().parents[2] / "data" / "dq3" / "world-metatiles.json")
_WORLD_CELLS: dict = {}


def world_metatiles(path=None) -> dict:
    """★世界タイル id → (CHR 4 枚, パレット組)。★セーブの実測から起こした表（OBSERVED / `data/dq3/world-metatiles.json`）。"""
    import json

    p = pathlib.Path(path) if path else WORLD_METATILES
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for key, row in (body.get("metatiles") or {}).items():
        try:
            tiles = tuple(int(v) for v in row["tiles"])
            if len(tiles) == 4:
                out[int(key)] = (tiles, int(row.get("pal", 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


#: ★★ 世界地図の升の差し替え（RX3-0203 / 2026-09-12 依頼者「save6 北の氷河みたいなところがMAPだと砂漠表示されている」）。
#:   ★ゲーム自身が、升を並べるときに**行で**絵を替えている（bank 15 $E526 / PRG 0x3E526）:
#:     升 1（砂漠）は y < 100 か y >= 230 なら升 30（氷）。⚠ アレフガルド（$2F & 2）では替えない。
#:   ⚠ ROM の升の値だけを見ると、北と南の氷が砂漠の絵で描かれる。
WORLD_ICE_FROM, WORLD_ICE_TO = 1, 30
#: ★この行の間（100..229）は砂漠のまま
WORLD_ICE_ROWS = (100, 230)


def _game_swap(name: str, y: int, v: int) -> int:
    """★ゲームが描くときの升（⚠ 世界地図の本土だけ）。"""
    if name == "world_main" and v == WORLD_ICE_FROM and not (WORLD_ICE_ROWS[0] <= y < WORLD_ICE_ROWS[1]):
        return WORLD_ICE_TO
    return v


def world_cells(name: str = "world_main"):
    """★ROM の世界地図の升（⚠ 1 升 1 バイト = 世界タイル id）。★1 度だけ展開して持つ。"""
    if name in _WORLD_CELLS:
        return _WORLD_CELLS[name]
    try:
        from dq3.knowledge import terrain as T
        from dq3rom import world_map as wm

        ident = T.TerrainSource()._identify()
        world = wm.decode(ident, name)
        # ★ゲームが描くときの升へ（RX3-0203 / ⚠ 北と南の氷）
        cells = bytes(_game_swap(name, y, v & 0x1F) for y, row in enumerate(world.tiles) for v in row)
        got = (cells, world.width, world.height)
    except Exception:                                  # noqa: BLE001 ★ROM が無い / 読めない
        got = None
    _WORLD_CELLS[name] = got
    return got


def _world_runtime(body: dict, chr_data: bytes):
    """★世界地図: CHR + パレット（実機）+ 対応表（data）+ 升（ROM）で `RuntimeArt` を作る。

    ⚠ どちらの世界かで **升だけ**が変わります（★対応表は同じ / RX3-0316）。
    """
    kind = int(body.get("kind", KIND_WORLD))
    name = WORLD_NAMES.get(kind)
    if name is None:
        return None
    try:
        pram = bytes.fromhex(body["pram"])
    except (KeyError, TypeError, ValueError):
        return None
    if is_dark(pram) or is_colorless(pram):
        return None                    # ⚠ 白黒の材料（RX3-0061）
    table = world_metatiles()
    got = world_cells(name)
    if not table or got is None:
        return None
    cells, width, height = got
    wram = bytearray(TILESET_OFF + 512)
    for idx, (tiles, pal) in table.items():
        if 0 <= idx < TILES:
            wram[TILESET_OFF + idx * QUAD:TILESET_OFF + idx * QUAD + QUAD] = bytes(tiles)
            wram[PALETTE_OFF + idx] = pal & 3
    try:
        art = build(bytes(wram), chr_data, pram, indices=sorted(table))
    except TileArtError:
        return None
    return RuntimeArt(art=art, kind=kind, map_id=0, width=width, height=height, cells=cells,
                      chr_checksum=int(body.get("chr_checksum", 0)))


def from_savestate(path, *, group=None) -> TileArt:
    """★セーブステートから作る（⚠ いまはこれが唯一の道）。"""
    from retroux.core.bgmap import savestate as ss

    chunks = ss.load(path).chunks
    for name in ("WRAM", "CHRR", "PRAM"):
        if name not in chunks:
            raise TileArtError("⚠ セーブに %s がありません" % name)
    # ⚠⚠ **既定は None**（★$7300 の実測の表を使う）。
    #   ⚠ ここを 0 のままにしていて、"両端は正しいのに橋渡しが落とす" を踏んだ
    #   （2026-08-31。★色が全部 組 0 になっていた）。
    return build(chunks["WRAM"], chunks["CHRR"], chunks["PRAM"], group=group)

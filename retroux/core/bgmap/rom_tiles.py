"""背景タイルを **ROM から**取り出す（2026-08-02）。

依頼者:
    > もともと、グラフィックパターンはROM解析して準備して
    > 後で実測と答え合わせする想定。

★★ **絵の辞書は ROM から。配置は見た画面から。** ★★

  ⚠⚠ 指示書 §2.2「未表示領域をROM解析だけで先読みして、
    未探索地形を自動開示しない」。
  ★**絵**を先に用意するのはこれに触れません。
    どのマスに何があるかは、これまでどおり**見た画面からしか**記録しません。

## 索引表（2026-08-02 に日本版で実測）

`0x00147` から **6バイト × 16 件**。1件は

    転送元（CPU $8000起点） / 転送先の終わり / PPU の宛先

⚠ 北米版の逆アセンブル（`bank0.asm` の `$8161`）と**同じ構造**でしたが、
  位置は違います。★借りたのは構造だけで、番地は日本版で測りました。
  **大きさが北米版と完全一致**したのが、同じ表である裏づけです
  （1360 / 1696 / 1040 / 1024）。

## ⚠ 重ね塗りである

CHR-RAM へは**順に上書き**されます。洞窟なら
「基本の洞窟」→「洞窟2」…と重なります。

★★ **どのマップがどれを重ねるかは分かりました**（`DUNGEON_BITS` 参照）。
  ROM のコードを読んで見つけた表で、実測と一致します。

## ⚠ まだ分かっていないこと（★推測で埋めない）

- `map_id` < `$2B` のうち、街以外（城など）の土台
  → ★`order_for_map()` は `None` を返します
- 洞窟のタイル `$BE` 1枚（`chr_for_map` が 98.7% に留まる原因）
- PPU `$0D00` 以降（街の飾り）。★ROM にそのままの形では入っていません
"""

from __future__ import annotations

import dataclasses
import pathlib

#: 索引表の位置（2026-08-02 / 日本版で実測）
TABLE_OFFSET = 0x00147
#: 1件のバイト数
ENTRY_SIZE = 6
#: 表の件数（★この先は値がもっともらしくなくなる）
ENTRY_COUNT = 16
#: PRG のバンク0 が写る CPU アドレス
BANK0_BASE = 0x8000
#: iNES ヘッダの長さ
INES_HEADER = 16
#: CHR-RAM の大きさ
CHR_SIZE = 0x2000

#: 索引の名前（★北米版の逆アセンブルの呼び名に合わせた）。
#: ⚠ 日本版で中身を確かめたのは 0-3 と 8 だけ。ほかは**参考**。
ENTRY_NAMES = {
    0: "world_map", 1: "town", 2: "cave", 3: "tower",
    4: "npc_sprites", 5: "text_ui", 6: "credits",
    7: "cave_alt", 8: "cave_overlay", 9: "lava",
    10: "small_a", 11: "small_b", 12: "small_c", 13: "small_d",
    14: "extra_a", 15: "extra_b",
}

#: ★背景が使う PPU の範囲（$0900-$0FFF）。⚠ ここだけ見て答え合わせする
BACKGROUND_FROM, BACKGROUND_TO = 0x0900, 0x1000


@dataclasses.dataclass(frozen=True)
class TileSetEntry:
    """索引表の1件。"""

    index: int
    name: str
    #: PRG の中の位置（0 起点）
    rom_offset: int
    #: PPU のどこへ載るか
    ppu_offset: int
    size: int

    @property
    def cpu_address(self) -> int:
        return BANK0_BASE + self.rom_offset

    @property
    def is_background(self) -> bool:
        """★背景の絵か（スプライトや文字ではないか）。"""
        return BACKGROUND_FROM <= self.ppu_offset < BACKGROUND_TO


def load_prg(rom_path) -> bytes:
    """iNES のヘッダを外して PRG を返す。"""
    data = pathlib.Path(rom_path).read_bytes()
    if data[:4] != b"NES\x1a":
        raise ValueError(f"iNES ではありません: {rom_path}")
    return data[INES_HEADER:]


def read_table(prg: bytes, offset: int = TABLE_OFFSET,
               count: int = ENTRY_COUNT) -> list[TileSetEntry]:
    """索引表を読む。

    ⚠ もっともらしくない件が来たら**そこで止める**。
      ★表の終わりを数で決め打ちせず、中身で判断する。
    """
    out: list[TileSetEntry] = []
    for i in range(count):
        base = offset + i * ENTRY_SIZE
        if base + ENTRY_SIZE > len(prg):
            break
        src = prg[base] | (prg[base + 1] << 8)
        end = prg[base + 2] | (prg[base + 3] << 8)
        ppu = prg[base + 4] | (prg[base + 5] << 8)
        size = end - src + 1
        # ★もっともらしさの検査（バンク0の中 / PPU の中 / 正の大きさ）
        if not (BANK0_BASE <= src < 0xC000 and src <= end < 0xC000
                and ppu < CHR_SIZE and 0 < size <= CHR_SIZE):
            break
        out.append(TileSetEntry(
            index=i, name=ENTRY_NAMES.get(i, f"entry_{i}"),
            rom_offset=src - BANK0_BASE, ppu_offset=ppu, size=size))
    return out


def build_chr(prg: bytes, entries, order) -> bytes:
    """指定した順に**重ね塗り**して CHR-RAM を作る。

    ⚠ 順番が意味を持ちます（後のものが前を上書きする）。
    """
    by_index = {e.index: e for e in entries}
    chr_ram = bytearray(CHR_SIZE)
    for i in order:
        e = by_index.get(i)
        if e is None:
            continue
        chunk = prg[e.rom_offset:e.rom_offset + e.size]
        chr_ram[e.ppu_offset:e.ppu_offset + len(chunk)] = chunk
    return bytes(chr_ram)


def match_rate(built: bytes, real: bytes,
               lo: int = BACKGROUND_FROM, hi: int = BACKGROUND_TO) -> float:
    """組み立てたものと、実機から採ったものの一致率。

    ★これが「答え合わせ」です。⚠ 1.0 でなければ、まだ分かっていない
      部分があるということ。**隠さず数字で出します。**
    """
    if not real or lo >= hi:
        return 0.0
    same = sum(1 for a, b in zip(built[lo:hi], real[lo:hi]) if a == b)
    return same / (hi - lo)


def best_order(prg: bytes, entries, real: bytes, bases=(0, 1, 2, 3),
               extras=(7, 8, 9, 10, 11, 12, 13), depth: int = 2):
    """実機のCHRに一番近くなる重ね方を探す。

    ⚠⚠ **これは「当てる」ための道具であって、正解表ではありません。**
      `map_id` → どれを重ねるか の対応が分かるまでの当座のものです。
      ★見つかった一致率も一緒に返すので、**どれだけ確かかが分かります**。
    """
    import itertools

    best_score, best_list = -1.0, []
    for base in bases:
        for n in range(0, depth + 1):
            for combo in itertools.combinations(extras, n):
                order = [base] + list(combo)
                rate = match_rate(build_chr(prg, entries, order), real)
                if rate > best_score:
                    best_score, best_list = rate, order
    return best_list, best_score


# --- ★★ マップ → タイルセット（2026-08-02 実測）★★ --------------------

#: マップヘッダ表（既知 / `docs/rom-analysis-notes.md` 4章）
MAP_HEADER = 0x08000
MAP_HEADER_SIZE = 8

#: 背景パレットの表（2026-08-02 実測）。1件 13 バイト
PALETTE_TABLE = 0x0FBBC
PALETTE_RECORD = 13

#: ★地形が実際に使うタイルの範囲（PPU $0900-$0CFF）。
#: ⚠ この外（$0D00 以降）は街の飾りで、ROM にそのままの形では無い。
TERRAIN_FROM, TERRAIN_TO = 0x0900, 0x0D00

#: ★★ ダンジョンの重ね方を決めるビット表（2026-08-02 実測）★★
#:
#: **ROM のコードを読んで見つけました。当てずっぽうではありません。**
#: `$807B`（PRG `0x0007B`）:
#:
#:     A5 31        LDA $31        ; ★map_id
#:     38 E9 2B     SEC / SBC #$2B ; ★$2B を引く
#:     AA           TAX
#:     BD A7 81     LDA $81A7,X    ; ★ここがビット表
#:     85 12        STA $12
#:     A9 07 85 13  LDA #$07 / STA $13
#:     06 12        ASL $12        ; 上の桁から1ビットずつ
#:     90 43        BCC （立っていなければ飛ばす）
#:     A5 13 85 0C  LDA $13 / STA $0C   ; ★立っていれば索引 $13 を重ねる
#:     ...
#:     E6 13        INC $13
#:     A5 13 C9 0E  CMP #$0E       ; ★14 になるまで（索引 7〜13 の7回）
#:
#: つまり **bit7→索引7, bit6→索引8, … bit1→索引13**。bit0 は使いません。
#:
#: ★答え合わせ（地形範囲 $0900-$0CFF）:
#:   map $3F 洞窟: 表の値 $44 -> [2, 8, 12] -> **98.7%**（違うのは $BE の1枚）
#:   map $40 塔  : 表の値 $40 -> [2, 8]     -> **100%**（2件とも）
DUNGEON_BITS = 0x001A7
#: ★この map_id からビット表が始まる（コードの `SBC #$2B`）
DUNGEON_FIRST_MAP = 0x2B
#: ★ダンジョンの土台は「洞窟」。塔も土台は洞窟でした（実測）
DUNGEON_BASE = 2
#: ★最初に重ねる索引（コードの `LDA #$07`）
DUNGEON_FIRST_ENTRY = 7
#: ★何ビット見るか（コードの `CMP #$0E` … 索引 7〜13 の7回）
DUNGEON_BIT_COUNT = 7

#: 境界タイルID（ヘッダ1バイト目）→ どの索引を重ねるか。
#:
#: ⚠ こちらは **ビット表の外**（`map_id` < `$2B`）のためのものです。
#:   ★街（境界 `$01` / map `$0B`）だけ実測しました（地形範囲 **100%**）。
#:   城などはまだ確かめていないので `None` を返し、**推測で描きません**。
BORDER_TO_ORDER = {
    0x01: [1],                 # 街
}

#: ★★★ **マップ種別がそのまま CHR 索引です**（2026-08-03 / Phase 1）。
#:
#: ```
#: D0AB: LDA $1F      ; ★マップ種別
#: D0AD: STA $0C
#: D0AF: JSR $8000    ; ★★その索引の CHR を転送
#: D0B8: LDA #$04 / STA $0C / JSR $8000   ; ★NPC の絵も
#: ```
#:
#: ⚠ 境界タイルID（ヘッダ byte0）は**関係ありません**。
#:   2026-08-02 まで `BORDER_TO_ORDER` で境界 `$01` の 8 件だけに
#:   絞っていましたが、実コードを読んだところ**種別で決まっていました**。
#:
#: ★索引の中身（`$8147` の表 / `read_table` が読むもの）:
#:   0=world_map  1=town  2=cave  3=tower  4=npc_sprites
KIND_IS_CHR_INDEX = True
#: ★世界地図の `map_id`（種別0）
WORLD_MAP_ID = 0x01


def dungeon_bits(prg: bytes, offset: int = DUNGEON_BITS) -> bytes:
    """ビット表を、**もっともらしい間だけ**読む。

    ⚠ 件数を決め打ちしません（`read_table` と同じ流儀）。
      ★bit0 は使われないので、そこが立った時点で表の外と判断します。
      実測では `map_id $6C`（値 `$0B`）から乱れました。
    """
    out = bytearray()
    for i in range(offset, len(prg)):
        if prg[i] & 0x01:
            break
        out.append(prg[i])
    return bytes(out)


def order_for_map(prg: bytes, map_id: int):
    """そのマップで重ねる索引の並び。⚠ 分からなければ None。

    ★**推測で返しません。** ROM のコードから導いた分だけ答えます。
    """
    if map_id >= DUNGEON_FIRST_MAP:
        # ★★ 2026-08-19 / RX-0072: **塔（種別3）は [種別, 4]** ★★
        #
        #   ⚠⚠ ここは長らく「ビット表 `dungeon_bits`」から order を作っていたが、
        #     塔で **[2,13] を返して実機と食い違って**いた（青灰ノイズ）。
        #   ★逆アセンブル（`D0AB: LDA $1F`=種別 → その CHR を転送 /
        #     `D0B8: LDA #$04`=NPC を常時転送）どおり、塔は **[3, 4]**。
        #     灯台(map $50)のセーブステートの実CHRで**壁タイルまで画素一致**を確認。
        #   ⚠ 洞窟（種別2）は base=2 が種別と一致しており、ビット表の overlay が
        #     前半に別タイルを供給している可能性があるため、**未検証のまま変えない**
        #     （洞窟のセーブで裏取りしてから直す / RX-0072）。
        from .dungeon_map import map_kind

        table = dungeon_bits(prg)
        i = map_id - DUNGEON_FIRST_MAP
        if i >= len(table):
            return None            # ⚠ 表の外。分からない（塔でも同じ）
        if map_kind(map_id) == 3:
            return [3, 4]
        bits = table[i]
        return [DUNGEON_BASE] + [
            DUNGEON_FIRST_ENTRY + n for n in range(DUNGEON_BIT_COUNT)
            if bits & (0x80 >> n)]
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    if off + MAP_HEADER_SIZE > len(prg):
        return None
    # ★★ `$D0AB: LDA $1F / STA $0C / JSR $8000`
    #    マップ種別がそのまま CHR 索引です。⚠ 境界タイルIDは関係ありません。
    return [0] if map_id == WORLD_MAP_ID else [1]


def palette_for_map(prg: bytes, map_id: int) -> bytes | None:
    """そのマップの背景パレット 16 バイト。⚠ 読めなければ None。

    ★実測3件と完全一致（2026-08-02）。
    ⚠⚠ `$3F04` / `$3F08` / `$3F0C` は **00 のまま**にします。
      共通色で埋めると実機と食い違います（一度間違えました）。
    """
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    if off + MAP_HEADER_SIZE > len(prg):
        return None
    index = prg[off + 7]
    rec = prg[PALETTE_TABLE + index:PALETTE_TABLE + index + PALETTE_RECORD]
    if len(rec) < PALETTE_RECORD:
        return None
    out = bytearray(16)
    out[0] = rec[0]
    for g in range(4):
        out[g * 4 + 1:g * 4 + 4] = rec[1 + g * 3:4 + g * 3]
    return bytes(out)


def chr_for_map(prg: bytes, entries, map_id: int) -> bytes | None:
    """そのマップの CHR-RAM を ROM から組む。⚠ 分からなければ None。

    ★これで**セーブステートを読まずに**地形の絵がそろいます。
    ⚠ 出来上がるのは絵だけ。**どのマスに何があるか**は、これまでどおり
      見た画面からしか記録しません（指示書 §2.2）。
    """
    order = order_for_map(prg, map_id)
    if order is None:
        return None
    return build_chr(prg, entries, order)

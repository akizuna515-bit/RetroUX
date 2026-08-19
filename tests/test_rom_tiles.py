"""背景タイルを ROM から取る（2026-08-02）。

依頼者:
    > もともと、グラフィックパターンはROM解析して準備して
    > 後で実測と答え合わせする想定。

★★ **答え合わせをテストにする。** ★★
  ⚠ 一致率を**そのまま出す**ので、まだ分かっていない部分が隠れません。
  ⚠ 100% でないところは「★ここは未解明」と分かる形にしてあります。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.rom_tiles import (
    BACKGROUND_FROM, BACKGROUND_TO, ENTRY_COUNT, TABLE_OFFSET, best_order,
    build_chr, load_prg, match_rate, read_table,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
ASSETS = PROJECT_ROOT / "work" / "map-assets"

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_capture = pytest.mark.skipif(
    not (ASSETS / "capture-3.txt").exists(), reason="採取データが無い")

#: ★地形として採る 8px 行の数（指示書のマス行 0-9 = 8px 行 0-19）。
#: ⚠ これより下はステータス窓（2026-08-02 実測）
TERRAIN_ROWS = 20


# --- 索引表 -------------------------------------------------------------

@needs_rom
def test_索引表を読める():
    entries = read_table(load_prg(ROM))
    assert len(entries) == ENTRY_COUNT, [e.name for e in entries]


@needs_rom
def test_大きさが北米版と一致する():
    """★★ **これが「同じ表だ」という裏づけ**（2026-08-02）。

    北米版の逆アセンブル `bank0.asm`:
        gfx_WorldMap $8C43-$9192 = 1360
        gfx_Town     $9193-$9832 = 1696
        gfx_Cave     $9833-$9C42 = 1040
        gfx_Tower    $9C43-$A042 = 1024

    ⚠ **番地は違う**（日本版は $898B から）。★大きさだけが一致した。
    """
    entries = read_table(load_prg(ROM))
    assert [e.size for e in entries[:4]] == [1360, 1696, 1040, 1024]


@needs_rom
def test_名前と宛先が想定どおり():
    entries = read_table(load_prg(ROM))
    by_name = {e.name: e for e in entries}
    assert by_name["world_map"].ppu_offset == 0x0900
    assert by_name["town"].ppu_offset == 0x0900
    assert by_name["cave"].ppu_offset == 0x0900
    assert by_name["tower"].ppu_offset == 0x0900
    # ★スプライトと文字は別の場所へ載る
    assert by_name["npc_sprites"].ppu_offset == 0x1000
    assert by_name["text_ui"].ppu_offset == 0x0000


@needs_rom
def test_背景かどうかを見分けられる():
    entries = read_table(load_prg(ROM))
    by_name = {e.name: e for e in entries}
    assert by_name["town"].is_background is True
    # ⚠ スプライトと文字は地形ではない
    assert by_name["npc_sprites"].is_background is False
    assert by_name["text_ui"].is_background is False


@needs_rom
def test_もっともらしくない件で止まる():
    """⚠ 表の終わりを**数で決め打ちしない**。中身で判断する。"""
    prg = load_prg(ROM)
    # ★わざと多く読ませても、途中で止まる
    assert len(read_table(prg, count=64)) == ENTRY_COUNT


def test_iNESでなければ断る(tmp_path):
    bad = tmp_path / "bad.nes"
    bad.write_bytes(b"XXXX" + bytes(100))
    with pytest.raises(ValueError, match="iNES"):
        load_prg(bad)


# --- 重ね塗り -----------------------------------------------------------

@needs_rom
def test_順に上書きされる():
    """⚠ 後のものが前を上書きする。順番が意味を持つ。"""
    prg = load_prg(ROM)
    entries = read_table(prg)
    only_cave = build_chr(prg, entries, [2])
    with_overlay = build_chr(prg, entries, [2, 8])
    assert only_cave != with_overlay
    # ★上書きされるのは overlay の範囲だけ
    e8 = next(e for e in entries if e.index == 8)
    assert only_cave[:e8.ppu_offset] == with_overlay[:e8.ppu_offset]


@needs_rom
def test_知らない番号は飛ばす():
    prg = load_prg(ROM)
    entries = read_table(prg)
    assert build_chr(prg, entries, [999]) == bytes(0x2000)


# --- ★★ 答え合わせ（実測との照合）★★ ---------------------------------

@needs_rom
@needs_capture
def test_街はROMだけでほぼ再現できる():
    """★★ **街は1件のまま 97% 以上**（2026-08-02 実測）。

    ⚠ 100% ではない。★残りはマップごとに載る部分と見られる。
    """
    from retroux.core.bgmap import Capture

    prg = load_prg(ROM)
    entries = read_table(prg)
    cap = Capture.load(ASSETS / "capture-5.txt")   # 街 $0B
    rate = match_rate(build_chr(prg, entries, [1]), cap.chr_data)
    assert rate >= 0.95, f"街の再現が {rate:.1%} しかない"


@needs_rom
@needs_capture
def test_答え合わせの数字を出す(capsys):
    """★★ **ここが本題**。ROM から組んだものが実測とどれだけ合うか。

    ⚠⚠ **合わないところを隠さない。** 100% でない＝まだ分かっていない
      部分がある、ということを数字で残す。
    """
    from retroux.core.bgmap import Capture

    prg = load_prg(ROM)
    entries = read_table(prg)
    results = []
    for path in sorted(ASSETS.glob("capture-*.txt")):
        cap = Capture.load(path)
        order, rate = best_order(prg, entries, cap.chr_data)
        names = "+".join(
            next(e.name for e in entries if e.index == i) for i in order)
        results.append((path.name, cap.map_id, names, rate))

    # ⚠ `pytest -s` のとき標準出力が cp932 になり、記号が出せずに落ちた
    #   （2026-08-02 / UnicodeEncodeError）。★ファイルへ残す。
    lines = ["== ROM から組んだ背景CHR と、実機の照合 =="]
    for name, map_id, names, rate in results:
        mark = "  合致" if rate >= 0.95 else "未解明"
        lines.append(f"  {mark} {name} map ${map_id:02X}: "
                     f"{names} -> {rate:.1%}")
    lines.append("  100% でないものは、マップごとに載る部分が未解明です。")
    report = PROJECT_ROOT / "work" / "rom_tiles_check.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")

    assert results, "採取データが無い"
    # ★どれか1つでも 95% 以上になること（★仕組みが働いている証拠）
    assert max(r[3] for r in results) >= 0.95


@needs_rom
@needs_capture
def test_未解明を隠さない():
    """⚠⚠ **「だいたい合う」で終わらせない。**

    洞窟は PPU $0D00 / $0F00 を埋める項目が索引表に無い。
    ★それが分かるように、一致率が低いことをここで固定しておく。
      対応表が見つかったらこのテストも一緒に直すこと。
    """
    from retroux.core.bgmap import Capture

    prg = load_prg(ROM)
    entries = read_table(prg)
    cap = Capture.load(ASSETS / "capture-3.txt")   # 洞窟 $3F
    _order, rate = best_order(prg, entries, cap.chr_data)
    # ⚠ いまは 6〜7割。★これが 95% を超えたら「解明した」ということ
    assert rate < 0.95, (
        f"★洞窟が {rate:.1%} まで合うようになった。"
        "対応表が見つかったのなら、このテストを直して前へ進めること")


@needs_rom
def test_背景の範囲だけを見ている():
    """★答え合わせは $0900-$0FFF だけ（スプライトや文字を混ぜない）。"""
    assert BACKGROUND_FROM == 0x0900
    assert BACKGROUND_TO == 0x1000
    a = bytes(0x2000)
    b = bytes([0xFF]) * 0x0900 + bytes(0x2000 - 0x0900)
    # ⚠ $0900 より前が違っても、背景の一致率は下がらない
    assert match_rate(a, b) == 1.0


def test_索引表の位置を書き留めてある():
    """★どこで測ったかを残す（後から確かめられるように）。"""
    assert TABLE_OFFSET == 0x00147


# --- ★★ パレットは ROM から完全に取れる ★★ ---------------------------

#: 背景パレットの表（2026-08-02 / 日本版で実測）
PALETTE_TABLE = 0x0FBBC
#: 1件 13 バイト（共通色1 + 3色×4組）。
#: ⚠ NES が描画に使わない $3F04/$3F08/$3F0C を省いた形
PALETTE_RECORD = 13
#: マップヘッダ表（既知 / docs/rom-analysis-notes.md 4章）
MAP_HEADER = 0x08000
MAP_HEADER_SIZE = 8


def palette_of(prg: bytes, map_id: int) -> bytes:
    """マップの背景パレットを ROM から作る（16バイト）。"""
    index = prg[MAP_HEADER + map_id * MAP_HEADER_SIZE + 7]
    rec = prg[PALETTE_TABLE + index:PALETTE_TABLE + index + PALETTE_RECORD]
    out = bytearray(16)
    out[0] = rec[0]                  # ★共通の背景色は $3F00 だけ
    for g in range(4):
        # ⚠ $3F04 / $3F08 / $3F0C は **00 のまま**（共通色を入れない）。
        #   ★描画には使われないので、ROM も 00 を置いている。
        #   ここを共通色で埋めると実機と食い違う（2026-08-02 に間違えた）。
        out[g * 4 + 1:g * 4 + 4] = rec[1 + g * 3:4 + g * 3]
    return bytes(out)


@needs_rom
@needs_capture
@pytest.mark.parametrize("slot,map_id", [(5, 0x0B), (3, 0x3F), (7, 0x40)])
def test_パレットをROMだけで再現できる(slot, map_id):
    """★★ **3/3 一致**（2026-08-02）。

    ⚠ 索引はマップヘッダの8バイト目。13 の倍数（0,13,…,91 の8種）。
    """
    from retroux.core.bgmap import Capture

    prg = load_prg(ROM)
    want = Capture.load(ASSETS / f"capture-{slot}.txt").palette
    assert palette_of(prg, map_id) == want


# --- ★★ どこまで ROM で足りるか ★★ -----------------------------------

#: ROM からそのまま取れるタイルIDの範囲（PPU $0900-$0CFF）
ROM_TILE_FROM, ROM_TILE_TO = 0x90, 0xD0
#: 空白（暗がり）。★地形ではないので数えない
BLANK_TILE = 0x5F


@needs_capture
@pytest.mark.parametrize("slot,place", [(3, "洞窟"), (7, "塔"), (8, "塔")])
def test_ダンジョンの地形はROMで足りる(slot, place):
    """★★ **ここが結論**（2026-08-02 実測）。

    ダンジョンと塔が実際に使う地形タイルは、**空白を除けば
    すべて $90-$CF**（＝ROM からそのまま取れる範囲）に収まる。

    ⚠ これが崩れたら「ROM だけでは足りない」ということ。
      ★そのときはこのテストを直して、何が増えたかを記録すること。
    """
    from retroux.core.bgmap import COLS, Capture, nametable_index

    cap = Capture.load(ASSETS / f"capture-{slot}.txt")
    outside = set()
    for row in range(20):            # ★上20行＝マス行0-9（窓を除く）
        for col in range(COLS):
            side, nc, nr = nametable_index(
                col, row, cap.scroll_x, cap.scroll_y)
            table = (cap.nametable_left if side == "left"
                     else cap.nametable_right)
            tile = table[nr * COLS + nc]
            if tile == BLANK_TILE:
                continue             # ★空白は地形ではない
            if not (ROM_TILE_FROM <= tile < ROM_TILE_TO):
                outside.add(tile)
    assert not outside, (
        f"★{place}に ROM で取れないタイルがある: "
        + " ".join(f"${t:02X}" for t in sorted(outside)))


@needs_capture
def test_街は飾りが足りないことを記録しておく():
    """⚠⚠ **街だけは ROM で足りない**（2026-08-02 実測）。

    看板・扉などの飾りが PPU $0D00/$0E00 にあり、
    ★**ROM にそのままの形では入っていない**（圧縮か実行時生成）。

    ⚠ 「だいたい足りる」で流さないよう、**足りないことを固定する**。
      解明できたらこのテストを直すこと。
    """
    from retroux.core.bgmap import COLS, Capture, nametable_index

    cap = Capture.load(ASSETS / "capture-5.txt")     # 街 $0B
    outside = set()
    for row in range(20):
        for col in range(COLS):
            side, nc, nr = nametable_index(
                col, row, cap.scroll_x, cap.scroll_y)
            table = (cap.nametable_left if side == "left"
                     else cap.nametable_right)
            tile = table[nr * COLS + nc]
            if tile != BLANK_TILE and not (
                    ROM_TILE_FROM <= tile < ROM_TILE_TO):
                outside.add(tile)
    assert outside, "★街も ROM で足りるようになったなら、このテストを直すこと"


# --- ★★ マップ → タイルセット（2026-08-02 実測）★★ ------------------

@needs_rom
@needs_capture
@pytest.mark.parametrize("slot,map_id,least", [
    (5, 0x0B, 1.00),      # ★街は完全一致
    (3, 0x3F, 0.98),      # ⚠ タイル $BE の1枚だけ違う
    (7, 0x40, 1.00),      # ★塔は完全一致
    (8, 0x40, 1.00),
])
def test_ROMだけで地形の絵がそろう(slot, map_id, least):
    """★★ **ここが到達点**（2026-08-02 実測）。

    セーブステートを読まずに、ROM とマップヘッダだけで地形の絵がそろう。

    ⚠⚠ 測るのは **タイル $90-$CF**（PPU $0900-$0CFF）だけ。
      その外（$0D00 以降）は街の飾りで、ROM にそのままの形では無い。
      ★以前ここまで含めて測り、64% と誤解した。**範囲を間違えない。**
    """
    from retroux.core.bgmap import Capture
    from retroux.core.bgmap.rom_tiles import TERRAIN_FROM, TERRAIN_TO, chr_for_map

    prg = load_prg(ROM)
    entries = read_table(prg)
    built = chr_for_map(prg, entries, map_id)
    assert built is not None, f"map ${map_id:02X} の種類が未確認"
    real = Capture.load(ASSETS / f"capture-{slot}.txt").chr_data
    rate = match_rate(built, real, TERRAIN_FROM, TERRAIN_TO)
    assert rate >= least, f"map ${map_id:02X}: {rate:.1%} しか合わない"


@needs_rom
@pytest.mark.parametrize("map_id,want", [
    (0x3F, [2, 8, 12]),   # ★洞窟。表の値 $44
    (0x40, [2, 8]),       # ★塔。表の値 $40
    (0x0B, [1]),          # ★街（ビット表の外）
])
def test_重ね方をROMのコードから導ける(map_id, want):
    """★★ **当てずっぽうで探していない**（2026-08-02）。

    以前は `best_order()` で総当たりしていた。⚠ それは「当てる」道具で、
    正解表ではない。★ROM の `$807B` を読み、
    `LDA $81A7,X`（X = map_id - $2B）というビット表を見つけた。
    ここで確かめるのは、**その表どおりの答えが出るか**。
    """
    from retroux.core.bgmap.rom_tiles import order_for_map

    assert order_for_map(load_prg(ROM), map_id) == want


@needs_rom
def test_ビット表の並びがコードと合っている():
    """★bit7→索引7, bit6→索引8, … bit1→索引13（`INC $13` / `CMP #$0E`）。

    ⚠ bit0 は使われない（7回しか回らない）。
    """
    from retroux.core.bgmap.rom_tiles import (
        DUNGEON_BASE, DUNGEON_BIT_COUNT, DUNGEON_BITS, DUNGEON_FIRST_ENTRY,
        DUNGEON_FIRST_MAP, dungeon_bits, order_for_map)

    assert (DUNGEON_BITS, DUNGEON_FIRST_MAP) == (0x001A7, 0x2B)
    assert (DUNGEON_BASE, DUNGEON_FIRST_ENTRY, DUNGEON_BIT_COUNT) == (2, 7, 7)
    prg = load_prg(ROM)
    # ★洞窟 $3F の表の値は $44 = bit6 + bit2 -> 索引 8 と 12
    assert dungeon_bits(prg)[0x3F - DUNGEON_FIRST_MAP] == 0x44
    assert order_for_map(prg, 0x3F) == [2, 8, 12]


@needs_rom
def test_ビット表の終わりを数で決め打ちしない():
    """⚠ 件数を決め打ちしない（`read_table` と同じ流儀）。

    ★bit0 は使われないので、立った時点で表の外。
      実測では map $6D（値 $01）から乱れた。
    """
    from retroux.core.bgmap.rom_tiles import DUNGEON_FIRST_MAP, dungeon_bits

    table = dungeon_bits(load_prg(ROM))
    assert all(b & 0x01 == 0 for b in table)
    # ★実測した洞窟・塔はどちらも表の中にある
    assert len(table) > 0x40 - DUNGEON_FIRST_MAP
    # ⚠ 乱れ始めるところで止まっている
    assert DUNGEON_FIRST_MAP + len(table) == 0x6D


@needs_rom
def test_種別がそのままCHR索引になる():
    """★★★ 2026-08-03 / Phase 1。**実コードから確定**。

    ```
    D0AB: LDA $1F      ; ★マップ種別
    D0AD: STA $0C
    D0AF: JSR $8000    ; ★★その索引の CHR を転送
    ```

    ⚠⚠ 境界タイルID（ヘッダ byte0）は**関係ありません**。
      2026-08-02 まで `BORDER_TO_ORDER` で境界 `$01` の 8 件だけに
      絞っていました（★当てずっぽうでした）。直したところ
      **74 → 109 件**が描けるようになりました。
    """
    from retroux.core.bgmap.rom_tiles import chr_for_map, order_for_map

    prg = load_prg(ROM)
    entries = read_table(prg)
    assert order_for_map(prg, 0x01) == [0], "★世界地図は索引0"
    for map_id in (0x00, 0x02, 0x06, 0x07, 0x0B, 0x17, 0x1B, 0x25, 0x2A):
        assert order_for_map(prg, map_id) == [1], f"⚠ map ${map_id:02X}"
    # ★城 $07 も描けるようになった
    assert chr_for_map(prg, entries, 0x07) is not None
    # ⚠ 表の外の map_id でも落ちない
    assert order_for_map(prg, 0x6D) is None


@needs_rom
def test_塔は種別3のCHRと背景後半を使う():
    """★★ RX-0072: 塔（種別3）は order [3, 4] ＋ 背景 後半($1000)。★★

    ⚠⚠ 以前はダンジョンの**ビット表**から [2,13] を返し、塔の base を
      **2（洞窟）にしていた**ため、灯台が青灰ノイズになっていた。
    ★逆アセンブル（D0AB: 種別→CHR / D0B8: entry4=NPC 常時）どおり [種別, 4]。
      灯台 $50 のセーブステートの実CHRで**壁タイルまで画素一致**を確認済み。
    ⚠ 洞窟（種別2）は base=2 が種別と一致しており、未検証なので**変えない**。
    """
    from retroux.core.bgmap.dungeon_map import map_kind
    from retroux.core.bgmap.rom_assets import RomTileSource
    from retroux.core.bgmap.rom_tiles import order_for_map

    prg = load_prg(ROM)
    for mid in (0x50, 0x51, 0x52):        # ★灯台（塔）
        assert map_kind(mid) == 3, f"map ${mid:02X} は種別3のはず"
        assert order_for_map(prg, mid) == [3, 4], f"map ${mid:02X}"
    # ★背景パターンテーブルは後半($1000)
    assert RomTileSource(ROM).for_map(0x50).half == 1
    # ⚠ 街(種別1)・洞窟(種別2)は前半のまま
    assert RomTileSource(ROM).for_map(0x0B).half == 0   # 街
    assert order_for_map(prg, 0x2B)[0] == 2             # 洞窟は base=2
    # ⚠ 表の外は塔でも None（範囲チェックを残す）
    assert order_for_map(prg, 0x6D) is None


@needs_rom
def test_境界IDの表は街だけ():
    """★ビット表の外で確かめたのは街（境界 $01）だけ。

    ⚠ 増やすなら、実測の根拠も一緒に残すこと。
    """
    from retroux.core.bgmap.rom_tiles import BORDER_TO_ORDER

    assert set(BORDER_TO_ORDER) == {0x01}


@needs_rom
def test_地形の範囲を間違えない():
    """⚠⚠ 2026-08-02、$0900-$0FFF で測って「64%」と誤解した。

    ★地形が使うのは $0900-$0CFF。その外は街の飾り。
    """
    from retroux.core.bgmap.rom_tiles import TERRAIN_FROM, TERRAIN_TO

    assert (TERRAIN_FROM, TERRAIN_TO) == (0x0900, 0x0D00)
@needs_rom
@needs_capture
@pytest.mark.parametrize("slot,map_id", [
    (5, 0x0B), (3, 0x3F), (7, 0x40), (8, 0x40)])
def test_画面が実際に使う地形タイルは全部そろう(slot, map_id):
    """★★ **これが本当の合格条件**（2026-08-02）。

    一致率ではなく、**その画面が実際に使っているタイル**を1枚ずつ見る。
    ⚠ 一致率は「使っていないタイルまで数える」ので、良くも悪くも出る。

    ★見るのは地形として採る上10行（8px 行 0-19 / 指示書のマス行 0-9）の、
      タイルID `$90` 以降だけ。
      ⚠ `$90` 未満は**文字**（PPU `$0000` の text_ui）で、地図には描かない。
    """
    from retroux.core.bgmap import Capture
    from retroux.core.bgmap.rom_tiles import chr_for_map

    prg = load_prg(ROM)
    built = chr_for_map(prg, read_table(prg), map_id)
    assert built is not None
    cap = Capture.load(ASSETS / f"capture-{slot}.txt")
    used = set()
    for nt in (cap.nametable_left, cap.nametable_right):
        for row in range(TERRAIN_ROWS):
            used.update(nt[row * 32:(row + 1) * 32])
    bad = [t for t in sorted(used) if t >= 0x90
           and built[t * 16:(t + 1) * 16] != cap.chr_data[t * 16:(t + 1) * 16]]
    assert not bad, ("★合わない地形タイル: "
                     + " ".join(f"${t:02X}" for t in bad))


@needs_rom
@needs_capture
def test_街の飾りもROMに入っている():
    """⚠⚠ **2026-08-02、私は「ROM に無い」と誤って結論した。**

    128バイト単位で探したため見つからなかっただけで、
    `$D8`-`$E8` や `$F9` は ROM に**そのまま**入っていた。
    ★索引1（town）は PPU `$0900`-`$0F9F` を覆うので、飾りまで届く。

    ここでは「街で使う `$D0` 以降が全部そろう」ことを固定する。
    """
    from retroux.core.bgmap import Capture
    from retroux.core.bgmap.rom_tiles import chr_for_map

    prg = load_prg(ROM)
    entries = read_table(prg)
    town = next(e for e in entries if e.name == "town")
    assert town.ppu_offset + town.size == 0x0FA0

    built = chr_for_map(prg, entries, 0x0B)
    cap = Capture.load(ASSETS / "capture-5.txt")
    deco = sorted({t for t in cap.nametable_left + cap.nametable_right
                   if t >= 0xD0})
    assert deco, "★街の飾りが1つも使われていない採取データ"
    bad = [t for t in deco
           if built[t * 16:(t + 1) * 16] != cap.chr_data[t * 16:(t + 1) * 16]]
    assert not bad, " ".join(f"${t:02X}" for t in bad)

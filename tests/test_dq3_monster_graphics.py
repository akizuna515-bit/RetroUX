"""モンスターの絵の在り処（RX3-0035 / 2026-08-31）。

★★ `monster_id` は `_pak_data_lib` の**索引そのもの**だった。 ★★

⚠⚠ `RX3-0033` では「23 バイトに `graphic_id` が無い」で止まっていました。
  ★指示書 §6 の仮説A（`graphics_table[monster_id]`）が当たりです。

```text
実機（JP PRG 0x009891）
  LDA $056D,Y      ★enemy roster の monster_id
  CMP #$A7         ⚠ 167 未満だけ
  ASL / ROL $B5 / ASL / ROL $B5 / CLC / ADC $056D,Y   ★id * 5
  CLC / ADC $955A …                                   ★基点を足す
```

★1 件 5 バイト: `b0, data(2), param(2)`。
⚠ `data` は圧縮された絵、`param` は展開のパラメータ（★中身は未解析）。
"""

from __future__ import annotations

import pathlib

import pytest

from dq3rom import profile as dq3

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"

WINDOW = (0x8000, 0xBFFF)


def _rom_ready() -> bool:
    try:
        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(
    not _rom_ready(), reason=f"DQ3 Rev 0A の ROM が読めない（{ROM_PATH}）")


@pytest.fixture(scope="module")
def ident():
    return dq3.load_and_identify(ROM_PATH)


def _entries(ident):
    t = ident.table("monster_graphics")
    n, size = int(t["entries"]), int(t["entry_size"])
    start = ident.table_prg("monster_graphics")
    raw = ident.rom.prg[start:start + n * size]
    return [(raw[i * size], raw[i * size + 1] | raw[i * size + 2] << 8,
             raw[i * size + 3] | raw[i * size + 4] << 8) for i in range(n)]


@needs_rom
def test_敵の数と同じ件数がある(ident):
    """★139 体（⚠ `tables.enemies` と同じ数）。"""
    assert int(ident.table("monster_graphics")["entries"]) == \
        int(ident.table("enemies")["count"]) == 139


@needs_rom
def test_表はちょうど終わり次のデータに接している(ident):
    """★★ ⚠⚠ ここが一番強い裏づけ。 ★★

    139 件 × 5 バイトが**ちょうど**終わった所が、
    ★1 件目の `param` が指す先と**一致**します。
    ⚠ 件数や大きさを 1 でも間違えると、この 2 つはずれます。
    """
    t = ident.table("monster_graphics")
    start = ident.table_prg("monster_graphics")
    end = ident.table_prg("monster_graphics", "end_file_exclusive")
    assert end - start == int(t["entries"]) * int(t["entry_size"])
    first_param = _entries(ident)[0][2]
    assert ident.prg_offset(int(t["bank"]), first_param) == end, (
        "⚠⚠ 表の終わりと 1 件目の param がずれています")


@needs_rom
def test_全件のポインタが窓に収まる(ident):
    """⚠ 基点を取り違えると、ここが崩れます。"""
    bad = [(i, hex(d), hex(p)) for i, (_b, d, p) in enumerate(_entries(ident))
           if not (WINDOW[0] <= d <= WINDOW[1] and WINDOW[0] <= p <= WINDOW[1])]
    assert bad == [], bad


@needs_rom
def test_基点はROMから引く(ident):
    """⚠ 実機は即値ではなく `$955A` の 2 バイトを読む（★JP 固有）。"""
    t = ident.table("monster_graphics")
    at = ident.table_prg("monster_graphics", "pointer_from")
    prg = ident.rom.prg
    got = prg[at] | (prg[at + 1] << 8)
    assert got == int(str(t["cpu"]), 16), (hex(got), t["cpu"])


@needs_rom
def test_先頭の数件を固定する(ident):
    got = _entries(ident)[:3]
    assert got == [(0x04, 0x8000, 0x917A),
                   (0x13, 0x812B, 0x917E),
                   (0x15, 0x8C8D, 0x9185)], got


@needs_rom
def test_絵は共有しparamは体ごとに違う(ident):
    """★★ ⚠⚠ ここが「1 体 1 枚」ではなかった所。 ★★

    ```text
    data  ★52 種しかない   ⚠ **絵の素は使い回している**
    param ★139 通り        ★体ごとに違う（= ここが「その敵の絵」）
    ```

    ⚠ つまり `data` だけ見ると 6 体が同じ絵に見えます。★組み立ては `param`。
    ⚠⚠ 指示書 G1（違う id は違う絵）は **param で見る**のが正しい。
    """
    ent = _entries(ident)
    data = {d for _b, d, _p in ent}
    param = {p for _b, _d, p in ent}
    assert len(param) == len(ent) == 139, (
        "⚠⚠ param が %d 種（★体ごとに違うはず）" % len(param))
    assert 30 <= len(data) <= 80, (
        "⚠ 絵の素が %d 種（★使い回しているはず）" % len(data))


# --- ★★ 展開（⚠ 実機の CHR-RAM で答え合わせする）------------------------

# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()


def _battles():
    """★戦闘中のセーブ（⚠ 番号で名指ししない / `RX3-0028`）。"""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))
    from dq3_states import BATTLE, pick
    from retroux.core.bgmap import savestate as ss

    return [(p, ss.load(p)) for p in pick(BATTLE)]


@needs_rom
def test_全139体が展開できる(ident):
    """⚠ 途中でバンクの端を越えたら、★形の読み方が違う。"""
    from dq3rom import monster_gfx as mg

    total = 0
    for mid in range(139):
        got = mg.build(ident, mid)
        assert got.tile_count > 0, mid
        total += got.tile_count
    assert total == 3815, "⚠ タイル総数が %d（★3815 のはず）" % total


@needs_rom
def test_展開したタイルが実機のCHRRAMと一致する(ident):
    """★★ ⚠⚠ ここが今回いちばん強い裏づけ。 ★★

    ★戦闘中のセーブには、**ゲーム自身が展開した CHR-RAM** が入っています。
    ⚠ ROM から起こしたタイルが**1 バイトも違わず**そこに在ること。

    ⚠⚠ 「それらしい絵が出た」では確定しません（★指示書 §28）。
    """
    from dq3rom import monster_gfx as mg

    checked = matched = 0
    for path, state in _battles():
        ram, chr_ram = state.chunks["RAM"], state.chunks["CHRR"]
        have = {chr_ram[i:i + 16] for i in range(0, len(chr_ram), 16)}
        for mid in [v for v in ram[0x056D:0x0571] if v != 0xFF]:
            got = mg.build(ident, mid)
            for tile in got.tiles:
                checked += 1
                if tile in have:
                    matched += 1
            assert all(t in have for t in got.tiles), (
                "⚠⚠ %s の id%d が CHR-RAM と合いません" % (path.name, mid))
    if checked < 50:
        # ⚠⚠ 検査そのものは生きています（★上の per-tile 照合は通った）。
        #   ★足りないのは**材料**（大きい敵の戦闘セーブ）です（RX-0135）。
        pytest.skip("⚠ タイルが 50 枚に届く戦闘のセーブがありません（RX-0135）"
                    "（★いま %d 枚 / 観点は docs/audit/tests-waiting-savestates.md）"
                    % checked)
    assert matched == checked


@needs_rom
def test_パレットが実機のPRAMに在る(ident):
    """★`param` の 3 色組が、⚠ 実機のパレットにそのまま入っていること。"""
    from dq3rom import monster_gfx as mg

    checked = {"spr": 0, "bg": 0}
    for path, state in _battles():
        ram, pram = state.chunks["RAM"], state.chunks["PRAM"]
        # ⚠⚠ **どちらの側か**まで見る（★ニブルを入れ替えても通ってしまった）
        bg = {tuple(pram[i + 1:i + 4]) for i in range(0, 16, 4)}
        spr = {tuple(pram[i + 1:i + 4]) for i in range(16, 32, 4)}
        for mid in [v for v in ram[0x056D:0x0571] if v != 0xFF]:
            got = mg.build(ident, mid)
            for pal in got.sprite_palettes:
                checked["spr"] += 1
                assert pal in spr, (
                    "⚠⚠ %s id%d: %s はスプライト側に無い（★下位ニブル = スプライト）"
                    % (path.name, mid, pal))
            for pal in got.bg_palettes:
                checked["bg"] += 1
                assert pal in bg, (
                    "⚠⚠ %s id%d: %s は背景側に無い（★上位ニブル = 背景）"
                    % (path.name, mid, pal))
    assert checked["spr"] >= 1 and checked["bg"] >= 1, (
        "⚠ 片側しか確かめていない（★空回り）: %s" % checked)


@needs_rom
def test_バンクはビット表で決まる(ident):
    """⚠ 総当たりで「合うほう」を選んでいないこと（★実機と同じ規則）。"""
    from dq3rom import monster_gfx as mg

    assert mg.bank_of(ident, 0) == 3
    assert mg.bank_of(ident, 2) == 2
    used = {mg.bank_of(ident, m) for m in range(139)}
    assert used == {2, 3}, used


# --- ⚠⚠ 並べ方（★実測 2 体だけが確か）------------------------------------

#: ★実機のネームテーブルから**測った**形（⚠ 推測ではない）
MEASURED = {0: (2, 2), 2: (5, 4)}


@needs_rom
def test_実測した2体の形と合う(ident):
    """★セーブステートのネームテーブルから測った形と一致すること。

    ```text
    id0 スライム        4 枚 → 2 列 × 2 行（★行 5-6 / 列 0-1）
    id2 いっかくうさぎ 21 枚 → 5 列 × 4 行（★行 3-6 / 列 0-4）
    ```
    """
    from dq3rom import monster_gfx as mg

    for mid, want in MEASURED.items():
        got = mg.build(ident, mid)
        assert (got.width, got.height) == want, (mid, got.width, got.height)
    assert mg.build(ident, 0).top_row == 5
    assert mg.build(ident, 2).top_row == 3


@needs_rom
def test_タイルの位置は見出しから来る(ident):
    """★★ ⚠⚠ **並べ方は推測ではありません。** ★★

    ★タイル 1 枚ごとに見出しがあり、その 2 バイト目が `(行 << 4) | 列`。
    ⚠ 最初は「先頭に見出しが 1 つ」と読み違えて、
      「地面は 7 行目」という**仮説**で高さを出していました
      （★139 体中 21 体で破綻していた）。
    """
    from dq3rom import monster_gfx as mg

    got = mg.build(ident, 0)
    assert [c for c in got.cells] == [(0, 5), (0, 6), (1, 5), (1, 6)]
    assert got.cell(0, 0) is got.tiles[0]     # ★(列 0, 行 0) = 上端
    assert got.cell(1, 0) is got.tiles[2]
    assert got.cell(9, 9) is None             # ⚠ 無い所は None


@needs_rom
def test_全139体が画面に収まる形になる(ident):
    """★★ ⚠⚠ **できていないことを、できたことにしない。** ★★

    ⚠ 前は「地面は 7 行目」の仮説で **21 体が破綻**していました。
    ★見出しから位置を読むようにして **0 体**になりました。

    ⚠ 上限（10 列 × 8 行）も実測です。★最初 8×8 と決めつけて、
      大きい敵 5 体を「ありえない」と言っていました。
    """
    from dq3rom import monster_gfx as mg

    bad = [m for m in range(139) if not mg.build(ident, m).plausible]
    assert bad == [], "⚠ 収まらない形: %s" % bad[:8]
    sizes = [mg.build(ident, m) for m in range(139)]
    assert max(g.width for g in sizes) == 10
    assert max(g.height for g in sizes) == 8


# --- ★★ 左右対称の敵（RX3-0223 / 2026-09-12）------------------------------
#
# ⚠⚠ 依頼者「モンスターのCHRが半分に切れている。」（★ハンターフライ 038）
#   前は 1 枚のタイルの見出しを**最後の 1 つ**しか読まず、
#   ★左右反転して置くもう片側を落としていました。

#: ★置き場が 2 つ以上あるタイルを持つ敵の数（⚠ 見出しを数えた結果。目で選んでいない）
MULTI_PLACED = 49
#: ★直す前 → 直した後の形（列 × 行）
WIDENED = {38: ((3, 5), (4, 5)),     # ハンターフライ
           14: ((3, 5), (6, 5)),     # こうもりおとこ
           7: ((3, 5), (6, 5)),      # まほうつかい
           16: ((3, 5), (4, 5))}     # キラービー
#: ★直す前に作った絵の画素の sha256（⚠ 直した後も 1 バイトも変わらないこと）
UNCHANGED = {
    0: "cbb2a66585f6c8b2c2831b40c0d310cba69fe67727fbe7cb86d82f06e6c34ba3",
    2: "12d0972c3455ef7221e6bf42324577145d213eb75d57fde13ca6b8c8f530a790",
    30: "cf6e0ceb9d5a7e6677694b2602303b27d95fc58249fd4624c89547437c2c68e3",
    92: "4e66ae7923af39405796d18f2ec4d4a5d6805a33b34b107a666d4359bd82a7ac",
    113: "7735df82239f6ee6c68039baa64a83d8bae530292b6c353b978ae2d32cb29338",
    130: "59eff6954372235c06286aac6201c2a83aadc4636ce192870f33aa2cd74089c2",
}


def _mirror_pairs(got):
    """★同じタイルを同じ行に「そのまま」と「左右反転」で置いた組。"""
    plain = [p for p in got.placements if not (p.hflip or p.vflip)]
    flipped = [p for p in got.placements if p.hflip and not p.vflip]
    return [(a, b) for a in plain for b in flipped
            if a.tile == b.tile and a.row == b.row]


def test_反転は実機の4通りの写しと同じ():
    """★`sub_39C5F` の +$10（ビット逆順）/ +$20（8 行を逆順）と同じこと。"""
    from dq3rom import monster_gfx as mg

    tile = bytes([0x01, 0x03, 0x07, 0x0F, 0x80, 0xC0, 0xE0, 0xF0,
                  0x11, 0x22, 0x44, 0x88, 0x00, 0xFF, 0x0F, 0xF0])
    assert mg.flip_tile(tile) is tile, "⚠ 反転しないのに作り直している"
    h = mg.flip_tile(tile, hflip=True)
    assert h[:4] == bytes([0x80, 0xC0, 0xE0, 0xF0])
    assert h[8:12] == bytes([0x88, 0x44, 0x22, 0x11])
    v = mg.flip_tile(tile, vflip=True)
    assert v == tile[7::-1] + tile[15:7:-1], "⚠ 2 枚の面を別々に逆順にする"
    assert mg.flip_tile(tile, True, True) == mg.flip_tile(h, vflip=True)
    assert mg.flip_tile(h, hflip=True) == tile


@needs_rom
def test_1枚のタイルを何か所にも置く(ident):
    """★★ ⚠⚠ ここが原因: 見出しは 1 枚に**いくつも**付く。 ★★"""
    from collections import Counter

    from dq3rom import monster_gfx as mg

    multi = []
    for mid in range(139):
        per_tile = Counter(p.tile for p in mg.build(ident, mid).placements)
        if per_tile and max(per_tile.values()) > 1:
            multi.append(mid)
    assert len(multi) == MULTI_PLACED, multi
    assert set(WIDENED) <= set(multi)


@needs_rom
def test_左右対称の敵は全幅になる(ident):
    from dq3rom import monster_gfx as mg

    for mid, (_before, want) in WIDENED.items():
        got = mg.build(ident, mid)
        assert (got.width, got.height) == want, (mid, got.width, got.height)
        _px, w, h = mg.to_pixels(got)
        assert (w, h) == (want[0] * 8, want[1] * 8), (mid, w, h)


@needs_rom
def test_左右反転の相方はいつも同じ軸で折り返す(ident):
    """★★ 旗の読み方が正しい裏づけ（⚠ 1 体の見た目ではなく 45 体の一致）。 ★★

    ★同じタイルを「そのまま」と「左右反転」で同じ行に置くとき、
      2 つの列の和は**その敵の中でいつも同じ**（＝ 1 本の軸で折り返す）。
    ⚠ bit1 を反転と読み違えていれば、この和はばらけます。

    ⚠ 87 だけは絵の一部（小物）を折り返していて、軸が全幅の中心ではない。
    """
    from dq3rom import monster_gfx as mg

    axes, not_center = 0, []
    for mid in range(139):
        got = mg.build(ident, mid)
        sums = {a.col + b.col for a, b in _mirror_pairs(got)}
        if not sums:
            continue
        axes += 1
        assert len(sums) == 1, (mid, sums)
        if sums != {got.width - 1}:
            not_center.append(mid)
    assert axes == 45, axes
    assert not_center == [87], not_center


@needs_rom
def test_反転の旗どおりに右半分は左半分の鏡(ident):
    """★絵の上で確かめる（⚠ 置き場を読めても、描くときに反転を忘れれば半分のまま）。"""
    from dq3rom import monster_gfx as mg

    def block(px, w, col, row):
        return [bytes(px[((row * 8 + y) * w + col * 8) * 3:
                         ((row * 8 + y) * w + col * 8 + 8) * 3])
                for y in range(8)]

    def mirrored(rows):
        return [b"".join(r[i:i + 3] for i in range(21, -1, -3)) for r in rows]

    checked = 0
    for mid in WIDENED:
        got = mg.build(ident, mid)
        px, w, _h = mg.to_pixels(got)
        for a, b in _mirror_pairs(got):
            top = got.top_row
            assert block(px, w, b.col, b.row - top) == \
                mirrored(block(px, w, a.col, a.row - top)), (mid, a, b)
            checked += 1
    assert checked >= 30, "⚠ 対が %d 組しか無い（★空回り）" % checked


@needs_rom
def test_置き場が1つずつの敵の絵は変わらない(ident):
    """★★ ⚠⚠ 正しかった 90 体を壊していないこと。 ★★

    ① 直す前に作った絵の sha256 と同じ（★固定した数体）
    ② 置き場が 1 タイル 1 つの敵は、前の読み方（`cells`）で描いても同じ（★全員）
    """
    import dataclasses
    import hashlib

    from dq3rom import monster_gfx as mg

    for mid, want in UNCHANGED.items():
        px, _w, _h = mg.to_pixels(mg.build(ident, mid))
        assert hashlib.sha256(bytes(px)).hexdigest() == want, (
            "⚠⚠ id%d の絵が変わった" % mid)
    same = 0
    for mid in range(139):
        got = mg.build(ident, mid)
        if len(got.placements) != sum(c is not None for c in got.cells):
            continue
        old = dataclasses.replace(got, placements=())
        assert mg.to_pixels(old) == mg.to_pixels(got), mid
        same += 1
    assert same == 139 - MULTI_PLACED, same

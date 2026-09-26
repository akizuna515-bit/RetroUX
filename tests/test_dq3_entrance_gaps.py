"""入口表の「合わない 12 map」の性格（RX3-0081 / 2026-09-07）。

## ★分かったこと

⚠ 2026-08-31 の時点では「合わない 12 map は**未解明**」でした。
★数えてみると、⚠ **2 種類にきれいに割れます**。

```text
10 map  ⚠ 表の行が 1 つ多い（★升が見つからない）… 0/60/70/80/85/97/105/113/151/216
 2 map  ⚠ 升が 1 つ多い（★block が空）        … 117 / 198
```

## ⚠⚠ 走査漏れでは**ありません**（★これが今回の決め手）

★以前は「ニブルを 1 つ足せば見つかるのでは」と 15 通り試して全部外しました。
⚠ そもそも**足しても見つかりません**。

```text
★map 105 は、最後に見つけた升の**あとにタイルが 1 つも残っていません**。
  → ⚠ どんなニブルを足しても、余った行に対応する升は出てきません。
```

## ⚠ 「着くだけの枠」でもありません

★243 block を全部見て、⚠ 余った索引を `kind` で**名指ししている行は 0 件**でした。

## ★余った 10 行の性格

```text
★いつも block の**最後**の行
★同じ block の他の行の**写しではない**
★9 / 10 が「外へ出る」（⚠ 4 件は世界地図へ / 5 件は map 番号の小さい方へ）
⚠ 例外 1 件: map 80 → map 150（★番号の大きい方）
```

## ⚠ いちばんもっともらしい説明（★確定ではありません）

```text
sub_17542F は索引 0 から地図をなめ、⚠ **立ち位置と一致した所で止める**
→ ★入口の升に乗っていなければ、索引は最後まで進んで N（＝升の数）になる
→ ⚠ それがちょうど「余った行」
```

⚠⚠ **確かめていません。** ★そのように呼ぶ道（タイルを踏まずに地図を出る道）を
まだ見つけていないためです。→ ⚠ ここを埋めるのが `RX3-0081` の残りです。

★「それらしい」で埋めないので、`Arrival` は `unknown` のままにしてあります。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import area_maps as am
from dq3rom import collision
from dq3rom import entrances as en
from dq3rom import profile as dq3

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")

#: ⚠ 表の行が 1 つ多い（★升が見つからない）
ROW_WITHOUT_CELL = (0, 60, 70, 80, 85, 97, 105, 113, 151, 216)
#: ⚠ 升が 1 つ多い（★block が空）
CELL_WITHOUT_ROW = (117, 198)
#: ⚠ 「外へ出る」に当てはまらない 1 件（★例外を隠さない）
OUTWARD_EXCEPTION = 80


@pytest.fixture(scope="module")
def world():
    ident = dq3.load_and_identify(ROM_PATH)
    blocks = en.read_blocks(ident)
    ov = collision.read_overrides(ident)
    cells, maps = {}, {}
    for m in am.decode_all(ident):
        if not m.ok:
            continue
        table = collision.table_for(ident, m.entry.tileset, m.entry.map_id, ov)
        cells[m.entry.map_id] = en.scan_order(m.decoded, table)
        maps[m.entry.map_id] = (m, table)
    return ident, blocks, cells, maps


@needs_rom
def test_合わない12mapは2種類に割れる(world):
    """⚠ 「12 件が合わない」で止めない（★中身は 2 通り）。"""
    _ident, blocks, cells, _maps = world
    more_rows = tuple(sorted(m for m, cs in cells.items() if len(blocks[m]) > len(cs)))
    more_cells = tuple(sorted(m for m, cs in cells.items() if len(blocks[m]) < len(cs)))
    assert more_rows == ROW_WITHOUT_CELL
    assert more_cells == CELL_WITHOUT_ROW


@needs_rom
def test_ずれはどれもちょうど1(world):
    """★ずれ幅が 1 に揃っていること（⚠ 揃っていないなら別の原因がある）。"""
    _ident, blocks, cells, _maps = world
    for mid in ROW_WITHOUT_CELL:
        assert len(blocks[mid]) - len(cells[mid]) == 1, mid
    for mid in CELL_WITHOUT_ROW:
        assert len(cells[mid]) - len(blocks[mid]) == 1, mid


@needs_rom
def test_走査漏れでは説明できない(world):
    """⚠⚠ **これが今回の決め手**（★ニブルを足しても見つからない）。

    ★map 105 は、最後に見つけた升の**あとにタイルが 1 つも残っていません**。
    """
    _ident, _blocks, cells, maps = world
    m, _table = maps[105]
    last_x, last_y = cells[105][-1]
    after = [(x, y)
             for y, row in enumerate(m.decoded.tiles)
             for x, _t in enumerate(row)
             if (y, x) > (last_y, last_x)]
    assert not after, "⚠ 105 の最後の升のあとに %d 升ある（★前提が崩れた）" % len(after)


@needs_rom
def test_余った索引を名指しする行は無い(world):
    """★「着くだけの枠」ではないこと（⚠ 243 block を全部見る）。"""
    _ident, blocks, cells, _maps = world
    for mid in ROW_WITHOUT_CELL:
        want = len(cells[mid])
        hit = [(src, i) for src, blk in enumerate(blocks)
               for i, r in enumerate(blk)
               if r.dest_map == mid and r.kind < 0x80 and r.kind == want]
        assert not hit, "⚠ map %d の余った索引 %d を %s が名指ししている" % (mid, want, hit)


@needs_rom
def test_余った行はいつも最後(world):
    """⚠ 途中の行が余るなら、★block の切れ目を疑うべき（＝別の原因）。"""
    _ident, blocks, cells, _maps = world
    for mid in ROW_WITHOUT_CELL:
        assert len(cells[mid]) == len(blocks[mid]) - 1, mid


@needs_rom
def test_余った行は同じblockの写しではない(world):
    """★「コピペの残り」なら同じ行があるはず（⚠ 無かった）。"""
    _ident, blocks, cells, _maps = world
    for mid in ROW_WITHOUT_CELL:
        blk = blocks[mid]
        extra = blk[len(cells[mid])]
        same = [i for i, r in enumerate(blk[:len(cells[mid])])
                if (r.dest_map, r.kind) == (extra.dest_map, extra.kind)]
        assert not same, "⚠ map %d: 余った行が %s と同じ" % (mid, same)


@needs_rom
def test_余った行はほぼ外向き(world):
    """★9 / 10 が「外へ出る」（⚠ 例外 1 件を**隠さない**）。"""
    _ident, blocks, cells, _maps = world
    outward, inward = [], []
    for mid in ROW_WITHOUT_CELL:
        r = blocks[mid][len(cells[mid])]
        if r.band in ("band_c0", "band_f0") or r.dest_map < mid:
            outward.append(mid)
        else:
            inward.append(mid)
    assert inward == [OUTWARD_EXCEPTION], (
        "⚠ 外向きでない行が変わりました: %s（★説明を見直すこと）" % inward)
    assert len(outward) == 9


@needs_rom
def test_升が余る2mapはblockが空(world):
    """★117 / 198 は「行が 1 つ足りない」のではなく **block that is empty**。"""
    _ident, blocks, cells, _maps = world
    for mid in CELL_WITHOUT_ROW:
        assert blocks[mid] == [], "⚠ map %d の block: %s" % (mid, blocks[mid])
        assert len(cells[mid]) == 1


@needs_rom
def test_余りは全部で10行だけ(world):
    """⚠ 余りが増えていたら、★どこかで block がずれている。"""
    _ident, blocks, cells, _maps = world
    total = sum(max(0, len(blocks[m]) - len(cs)) for m, cs in cells.items())
    assert total == len(ROW_WITHOUT_CELL)

# ----------------------------------------------------------------------
# ★2026-09-16（RX3-0081）: 外れた説明を 2 つ固定する
#
#   ⚠ 「外れた」も成果です。★同じ道をもう一度試さないように検査で残します
#     （★2026-08-31 の「ニブルを足す」15 通りと同じ扱い）。
# ----------------------------------------------------------------------
@needs_rom
def test_地図の端から出る案では説明できない(world):
    """⚠ 「入口の升を踏まず、地図の端から歩いて出る」では説明が付かない。

    ★入口の升から外周まで歩ける map を数えると **60 件**あり、
    ⚠ 余った行のある 10 map と一致しません。⚠⚠ さらに map 113 は
    **外周まで歩けない**のに余った行があります（★決め手）。
    """
    import collections as _c

    _ident, _blocks, cells, maps = world
    reach = set()
    for mid, (m, table) in maps.items():
        starts = cells[mid]
        if not starts:
            continue
        tiles = m.decoded.tiles
        h, w = len(tiles), len(tiles[0])

        def walkable(x, y):
            return 0 <= x < w and 0 <= y < h and not (table[tiles[y][x] & 0x1F] & 0x80)

        seen, q = set(starts), _c.deque(starts)
        while q:
            x, y = q.popleft()
            if x in (0, w - 1) or y in (0, h - 1):
                reach.add(mid)
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt not in seen and walkable(*nxt):
                    seen.add(nxt)
                    q.append(nxt)
    assert 113 not in reach, "⚠ map 113 が外周へ歩けるようになった（★説明を見直すこと）"
    assert len(reach - set(ROW_WITHOUT_CELL)) > 20, (
        "⚠ 外周へ歩ける map が余った行のある map に近づいた（★説明を見直すこと）")


@needs_rom
def test_数え直しでは升は増えない(world):
    """⚠ 「実機と同じに数え直せば見つかる」でも説明が付かない。

    ★試したのは 2 つ。どちらも**升の数は 1 つも変わりません**。

    ```text
    ① tile & 0x1F で引き直す   ⚠ 生の地図に id > 31 の升は 1 つも無い
    ② 壁つなぎ（実機の $7400）のあとで数える
    ```
    """
    from dq3rom import wall_join

    _ident, _blocks, cells, maps = world
    want_nibbles = set(en.ENTRANCE_NIBBLES)
    for mid in ROW_WITHOUT_CELL:
        m, table = maps[mid]
        want = {i for i, v in enumerate(table) if (v & 0x0F) in want_nibbles}
        raw = m.decoded.tiles
        assert all(v <= 0x1F for row in raw for v in row), (
            "⚠ map %d に id > 31 の升がある（★前提が変わった）" % mid)
        masked = [(x, y) for y, row in enumerate(raw)
                  for x, t in enumerate(row) if (t & 0x1F) in want]
        assert len(masked) == len(cells[mid]), mid
        joined = wall_join.apply(m.decoded, table, m.entry.tileset)
        after = [(x, y) for y, row in enumerate(joined)
                 for x, t in enumerate(row) if (t & 0x1F) in want]
        assert len(after) == len(cells[mid]), (
            "⚠ map %d は壁つなぎで升の数が変わった（★説明を見直すこと）" % mid)


# ----------------------------------------------------------------------
# ★★ 2026-09-17: 余った行は「地図の端から歩き出たときの行き先」（RX3-0081）
# ----------------------------------------------------------------------
@needs_rom
def test_余った行は端から歩き出たときの行き先(world):
    """★固定バンク `$D046`（幅・高さを越えたか）→ `$D06F`（升の総数 N を数えて行 N を引く）を読んだ。

    ★独立した裏: 10 map すべてが「行 = 升 + 1」で、端に歩ける升があり、map 113 は升 0 で行 1（★N = 0 で行 0）。
    ★もう 1 本: map 0 の余った行の着地点 (172,218) は、別の表（`world_entrances` 行 0 = アリアハン）と一致する。
    """
    ident, blocks, cells, _maps = world
    assert en.verify_edge_exit_code(ident) == [], en.verify_edge_exit_code(ident)
    got = {m: en.edge_exit(blocks[m], len(cells[m])) for m in cells}
    assert sorted(m for m, e in got.items() if e is not None) == sorted(ROW_WITHOUT_CELL)
    for m in ROW_WITHOUT_CELL:
        assert got[m] is blocks[m][-1], "★端から出る行は block の最後（map %d）" % m
    from dq3rom import world_entrances

    tables = en.read_arrival_tables(ident)
    a0 = en.arrival_of(got[0], tables)
    assert (a0.x, a0.y) == (world_entrances.read(ident)[0].x, world_entrances.read(ident)[0].y) == (172, 218)


@needs_rom
def test_端から出る道の命令列を壊すと気づく(world):
    """⚠ 命令列が 1 か所でなければ `edge_exit` を信じない（★壊す実験を検査に）。"""
    ident = world[0]
    win = bytes(ident.window(en.EDGE_EXIT_BANK))
    at = win.find(en.EDGE_EXIT_BOUNDS_CODE)
    assert at > 0
    broken = win[:at + 3] + bytes([win[at + 3] ^ 0xFF]) + win[at + 4:]

    class _Fake:
        def window(self, _bank):
            return broken

    assert en.verify_edge_exit_code(_Fake()) != [], "⚠⚠ 命令列が違うのに信じた"

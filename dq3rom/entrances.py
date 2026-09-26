"""入口表（entrance → map_id）。★Phase B の `Connection` の素。

⚠ 場所は profile が持つ（`tables.entrance_table`）。★ここには「仕組み」だけ書く。

## 仕組み（★完全逆アセンブルから）

実機は**地図を先頭から 1 バイトずつ**なめて、`collision[tile & 0x1F]` の
下位ニブルが `1 / A / F` の升だけを数える（`_bE_s19` / `sub_15BA44`）。
★立っている升が「何番目か」が、そのまま表の索引になる。

```text
sub_17542F   索引 = 0 から地図をなめ、立ち位置と一致した所で止める
$17545C      Y = 索引 * 2、bank 6 へ切替、(byte_98),Y を読む
sub_175467   byte0 → $8B（行き先 map）/ byte1 → 種別
```

表は `$FF` 区切りで map ごとに分かれ、実機は `map_no` 個ぶん読み飛ばす
（`$175AE1` の輪）。⚠ だから **block の並び順 = map 番号**。

## ★種別（byte1）＝ どこに着くか

```text
<0x80      ★行き先 map の**何番目の入口に着くか**
           ⚠⚠ 404 件中 396 件で「行った先の その番目が元へ戻る」
0x80-0xBF  ★arrival_local[種別-0x80]        （x, y, 向き）
0xC0-0xEF  ★arrival_world[種別-0xC0]        （世界地図へ出る）
0xF0-0xFD  ★arrival_world_short[種別-0xF0]  （世界地図へ出る・2 バイト）
0xFE-0xFF  ⚠ 表を引かない（★階段の音を鳴らして戻る道。未解析）
```
"""
from __future__ import annotations

import dataclasses

from . import collision
from .profile import Identified

TERMINATOR = 0xFF

#: ★入口として数える collision の下位ニブル（`sub_15BA44` の 3 分岐）
ENTRANCE_NIBBLES = (0x01, 0x0A, 0x0F)

#: ⚠ 種別の下限 → 呼び先の名前（★`sub_175467` の CMP の並びそのもの）
KIND_BANDS: tuple[tuple[int, str], ...] = (
    (0x00, "load_map"),
    (0x80, "band_80"),
    (0xC0, "band_c0"),
    (0xF0, "band_f0"),
    (0xFE, "band_fe"),
)


class EntranceError(ValueError):
    pass


def band_of(kind: int) -> str:
    """種別バイト → 実機がどの分岐へ行くか。"""
    name = KIND_BANDS[0][1]
    for low, label in KIND_BANDS:
        if kind >= low:
            name = label
    return name


@dataclasses.dataclass(frozen=True)
class Entrance:
    """1 升ぶんの行き先。"""

    index: int
    dest_map: int
    kind: int

    @property
    def band(self) -> str:
        return band_of(self.kind)


@dataclasses.dataclass(frozen=True)
class Arrival:
    """★その入口を通ると、どこに出るか。

    ⚠ `where` は `"entrance" / "local" / "world" / "unknown"` のどれか。
    ★分からないものを分かったことにしない（`unknown` を潰さない）。
    """

    where: str
    to_map: int | None = None
    to_index: int | None = None
    x: int | None = None
    y: int | None = None
    facing: int | None = None
    world: int | None = None


def read_arrival_tables(ident: Identified) -> dict[str, list[tuple[int, ...]]]:
    """着地点の 3 表を読む。"""
    out = {}
    for name, size in (("arrival_local", 3), ("arrival_world", 3),
                       ("arrival_world_short", 2)):
        t = ident.table(name)
        n = int(t["entries"])
        start = ident.table_prg(name)
        raw = ident.rom.prg[start:start + n * size]
        if len(raw) != n * size:
            raise EntranceError(f"{name} が短すぎます")
        out[name] = [tuple(raw[i * size:(i + 1) * size]) for i in range(n)]
    return out


def arrival_of(e: Entrance, tables: dict[str, list[tuple[int, ...]]]) -> Arrival:
    """種別 → 着地点。⚠ 表からはみ出したら断る（★黙って `unknown` にしない）。"""
    band = e.band
    if band == "load_map":
        return Arrival(where="entrance", to_map=e.dest_map, to_index=e.kind)
    if band == "band_fe":
        return Arrival(where="unknown", to_map=e.dest_map)
    name, base, = {
        "band_80": ("arrival_local", 0x80),
        "band_c0": ("arrival_world", 0xC0),
        "band_f0": ("arrival_world_short", 0xF0),
    }[band]
    rows = tables[name]
    i = e.kind - base
    if i >= len(rows):
        raise EntranceError(
            f"{name} の外を指しています: 索引 {i}（表は {len(rows)} 件）")
    row = rows[i]
    if name == "arrival_local":
        return Arrival(where="local", to_map=e.dest_map,
                       x=row[0], y=row[1], facing=row[2] & 3)
    if name == "arrival_world":
        return Arrival(where="world", to_map=e.dest_map,
                       world=row[0], x=row[1], y=row[2])
    return Arrival(where="world", to_map=e.dest_map, x=row[0], y=row[1])


@dataclasses.dataclass(frozen=True)
class Site:
    """★地図の升と、そこに対応する表の行。"""

    x: int
    y: int
    entrance: Entrance | None


def parse(data: bytes, blocks: int) -> list[list[Entrance]]:
    """`$FF` 区切りのバイト列を、map ごとの並びへ。

    ⚠ 途中で尽きたら断る（★足りないまま返すと map がずれる）。
    """
    out: list[list[Entrance]] = []
    cur: list[Entrance] = []
    i = 0
    while len(out) < blocks:
        if i >= len(data):
            raise EntranceError(
                f"表が尽きました: block {len(out)} / {blocks}（{i} バイト）")
        b = data[i]
        if b == TERMINATOR:
            out.append(cur)
            cur = []
            i += 1
            continue
        if i + 1 >= len(data):
            raise EntranceError(f"対の途中で尽きました: 位置 {i}")
        cur.append(Entrance(index=len(cur), dest_map=b, kind=data[i + 1]))
        i += 2
    return out


def read_blocks(ident: Identified, blocks: int | None = None
                ) -> list[list[Entrance]]:
    """ROM から map ごとの入口表を読む。

    ⚠ `blocks` を省くと profile の値を使う。★呼び手が area_directory の
    件数を渡すと、**2 つの表が同じ数を言っているか**の検査になる。
    """
    t = ident.table("entrance_table")
    if blocks is None:
        blocks = int(t["blocks"])
    elif int(t["blocks"]) != blocks:
        raise EntranceError(
            f"block 数が profile と違います: {blocks} != {t['blocks']}")
    start = ident.table_prg("entrance_table")
    end = ident.table_prg("entrance_table", "end_file_exclusive")
    return parse(ident.rom.prg[start:end], blocks)


def scan_order(decoded, table: list[int]) -> list[tuple[int, int]]:
    """★実機と同じ順に、入口になる升を拾う（左→右・上→下）。"""
    want: set[int] = set()
    for nibble in ENTRANCE_NIBBLES:
        want |= collision.tiles_with(table, nibble)
    return [(x, y)
            for y, row in enumerate(decoded.tiles)
            for x, t in enumerate(row) if t in want]


#: ★★ 地図の外へ歩き出したときの道（RX3-0081 / 2026-09-17 / 固定バンク $D046〜$D09B を読んだ）。
#:
#:   ```text
#:   $D046  LDX $88（幅）/ DEX / CPX $30（x）/ BCC $D06F      ★x が幅を越えた（⚠ -1 = $FF も越える）
#:   $D04C  LDX $89（高さ）/ DEX / CPX $31（y）/ BCC $D06F    ★y が高さを越えた
#:   $D06F  LDA $8B / BRK $AB 07 / ｛BRK $AC 07 → 見つかれば $04++｝を地図の**最後まで** → $04 = 入口の升の総数 N
#:   $D08C  Y = N * 2 → bank 6 → LDA ($98),Y → $FF なら $D09E（世界地図へ戻る・特別な map）/ それ以外 → $D3FE（表の行 N を使う）
#:   ```
#:
#:   → ★「表の行が 1 つ多い 10 map」の余った最後の行は、**地図の端から歩き出たときの行き先**。
#:     升を踏む道（$D3C6〜）は立ち位置と一致した索引で止まるが、⚠ 端から出る道は**升の総数 N** で引く。
EDGE_EXIT_BANK = 15
#: ★端を越えたかの判定（$D046 から 14 バイト）
EDGE_EXIT_BOUNDS_CODE = bytes.fromhex("A688CAE4309023A689CAE431901C")
#: ★升の総数を数えて表を引く入口（$D06F から 12 バイト）
EDGE_EXIT_COUNT_CODE = bytes.fromhex("A58B00AB0700AC079002E604")


def verify_edge_exit_code(ident: Identified) -> list[str]:
    """★上の 2 つの命令列が固定バンクに**1 か所ずつ**あるか（⚠ 無ければ `edge_exit` を信じない）。"""
    win = bytes(ident.window(EDGE_EXIT_BANK))
    bad = []
    for name, code in (("bounds", EDGE_EXIT_BOUNDS_CODE), ("count", EDGE_EXIT_COUNT_CODE)):
        n = win.count(code)
        if n != 1:
            bad.append("⚠ %s の命令列が %d か所（★1 か所のはず）" % (name, n))
    return bad


def edge_exit(block: list[Entrance], cell_count: int) -> Entrance | None:
    """★地図の端から歩き出たときの行き先（★表の行 N = 升の総数）。⚠ 行が無ければ None（★世界地図へ戻る道）。

    ⚠ 行が 2 つ以上余る map は無い（`tests/test_dq3_entrance_gaps.py`）。★あれば表の読み方を疑う。
    """
    if len(block) <= cell_count:
        return None
    return block[cell_count]


def sites(decoded, table: list[int],
          block: list[Entrance]) -> list[Site]:
    """升と表の行を、索引で突き合わせる。

    ⚠ 数が食い違っても**黙って捨てない**。★余った升は行き先 `None` で残す。
    """
    return [Site(x=x, y=y, entrance=block[i] if i < len(block) else None)
            for i, (x, y) in enumerate(scan_order(decoded, table))]

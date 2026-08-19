"""地形読み出しルーチンの特定（2026-08-02 / Stop A）。

★★ **結論: 地形は圧縮されていません。生の2次元配列です。**

    アドレス = ポインタA($23/$24) + y × (幅($21) + 1) + x

⚠⚠ ここに至るまでに**4回外しました**。一番の原因は
  「形式を仮定してから当てはめた」こと（ランレングスだと思い込んだ）。
  ★**そもそも行という単位が無かった**のが真相でした。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.bgmap.disasm import Layout, decode, walk
from retroux.core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE, load_prg

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"
STATES = PROJECT_ROOT / "tools" / "fceux" / "fcs"
_states = sorted(STATES.glob("DQ2_J.fc[0-9]")) if STATES.exists() else []

needs_rom = pytest.mark.skipif(not ROM.exists(), reason="ROM が無い")
needs_state = pytest.mark.skipif(not _states, reason="セーブステートが無い")

#: ★本命ルーチン（bank7）
BUILDER = 0x1DFAE


# --- 逆アセンブラ -------------------------------------------------------

def test_命令の長さを間違えない():
    """⚠ 長さを間違えると、次の命令の位置がずれて全部狂う。"""
    from retroux.core.bgmap.disasm import MODE_SIZE, OPCODES

    for op, (mnemonic, mode) in OPCODES.items():
        assert mode in MODE_SIZE, f"${op:02X} {mnemonic}"
    # ★代表的なものを直接確かめる
    assert OPCODES[0xA9] == ("LDA", "imm")     # 2 バイト
    assert OPCODES[0xB1] == ("LDA", "izy")     # 2 バイト
    assert OPCODES[0xBD] == ("LDA", "abx")     # 3 バイト
    assert OPCODES[0x4A] == ("LSR", "acc")     # 1 バイト


@needs_rom
def test_入口から辿るのであってROMを舐めない():
    """⚠⚠ **データをコードとして読まない**（2026-08-02 に踏んだ）。

    ★`walk()` は入口から分岐をたどり、届いた所だけを命令とみなします。
    """
    prg = load_prg(ROM)
    layout = Layout(prg)
    insns = walk(prg, layout, 0xE03C, 7)
    assert insns, "★1命令も辿れていない"
    # ★$E03C から $E0A7（RTS）までの範囲に収まる
    assert all(0xE03C <= i.address <= 0xE0B0 for i in insns)
    assert any(i.mnemonic == "RTS" for i in insns)


@needs_rom
def test_逆アセンブルが本物と合う():
    """★`$DFAE` の中身を1命令ずつ確かめる。"""
    prg = load_prg(ROM)
    layout = Layout(prg)
    want = ["LDA $21", "STA $0C", "INC $0C", "JSR $C234", "LDA $12",
            "CLC", "ADC $10", "STA $10", "STA $0E"]
    got, offset = [], BUILDER
    for _ in range(len(want)):
        insn = decode(prg, offset, layout.address_of(offset))
        got.append(insn.text())
        offset += insn.size
    assert got == want


# --- ★★ 地形は生の2次元配列 ★★ --------------------------------------

def terrain_id(prg, map_id, x, y):
    """★`$DFAE` の式そのまま。**Python のデコーダではありません。**

    ⚠ 指示書は Stop A で Python デコーダを作らないとしています。
      ここは**確かめるためだけ**の写しです。
    """
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    width = prg[off + 1]
    pointer = prg[off + 3] | (prg[off + 4] << 8)
    kind = (0 if map_id == 0x01
            else 1 if map_id < 0x2B
            else 2 if map_id < 0x44 else 3)
    if kind >= 2:
        x, y = x >> 1, y >> 1
    addr = pointer + y * (width + 1) + x
    value = prg[0x08000 + (addr - 0x8000)]
    return (value & 0x1F) if kind < 2 else ((value & 0xE0) >> 3)


@needs_rom
def test_読み出しの式がコードと同じ():
    """★`$DFB2` の `INC $0C`（幅+1）を落とさない。

    ⚠ 幅そのままにすると、行が1バイトずつずれて全部崩れます。
    """
    prg = load_prg(ROM)
    layout = Layout(prg)
    insn = decode(prg, BUILDER + 4, layout.address_of(BUILDER + 4))
    assert insn.text() == "INC $0C"


@needs_rom
def test_種別で取り出すビットが変わる():
    """★`$DFDB`-`$DFEE`:

        種別 0・1 -> AND #$1F（下位5ビット）
        種別 2・3 -> AND #$E0 / LSR ×3（上位3ビット。★4刻みのまま）
    """
    prg = load_prg(ROM)
    layout = Layout(prg)
    texts = []
    offset = BUILDER + 0x2D          # $DFDB
    for _ in range(11):
        insn = decode(prg, offset, layout.address_of(offset))
        texts.append(insn.text())
        offset += insn.size
    assert "AND #$1F" in texts
    assert "AND #$E0" in texts
    assert texts.count("LSR") == 3, "★LSR は3回（>>5 ではない）"


@needs_rom
@needs_state
def test_街で画面と地形IDが対応する():
    """★★ **これが Stop A の裏取り**（2026-08-02）。

    ⚠ 地形IDと見た目は 1 対 1 ではありませんが、
      **同じ絵がいつも同じ地形ID**になるかを見ます。

    実測（fc5 / map $0B）:

        $91 -> 00   $94 -> 01   $C5 -> 06   $A1 -> 04
    """
    from collections import defaultdict

    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        if st.byte(0x31) != 0x0B:
            continue
        px, py = st.byte(0x16), st.byte(0x17)
        sx, sy = st.byte(0x05), st.byte(0x06)
        nt = st.nametable
        seen = defaultdict(set)
        for cy in range(10):
            for cx in range(16):
                col = cx * 2 + sx // 8
                row = cy * 2 + sy // 8
                c64 = col % 64
                base = 0 if c64 < 32 else 0x400
                tile = nt[base + (row % 30) * 32 + (c64 % 32)]
                if tile < 0x90:
                    continue
                seen[tile].add(terrain_id(prg, 0x0B, px + cx - 8, py + cy - 7))
        assert seen, "★1マスも見えていない"
        # ★よく出る絵は、いつも同じ地形IDになること
        for tile in (0x91, 0x94, 0xC5, 0xA1):
            if tile in seen:
                assert len(seen[tile]) == 1, (
                    f"★${tile:02X} が {sorted(seen[tile])} に割れた")
        return
    pytest.skip("街のセーブステートが無い")


# --- ⚠ まだ分かっていないこと ------------------------------------------

# ★★ 外した歯止め: `test_地形IDからメタタイルへの変換表はまだ無い`
#
#   「表が見つかっていない」ことを固定していましたが、**見つかりました**
#   （`$DD64` → `$DC6F` → 種別ごとの5バイト表 / 2026-08-02）。
#   ★約束（「見つけたらこのテストを消して前へ進めること」）どおり外します。
#   ⚠ この検査は `metatile_for_terrain` という**名前**が生えたかだけを見て
#     いたので、実際には表が使われていても**緑のまま**でした（2026-08-11 に発覚）。
#   ★いま表が合っているかは `tests/test_dungeon_map.py` と
#     `tests/test_world_art.py` が実測と突き合わせています。

# --- ★★ Stop B: 実コードで地形を取る ★★ ------------------------------

#: ★実行の入口（bank7）。⚠ その手前は特殊ケース（map $12 など）の処理
BUILDER_ENTRY = 0xDFA8


def _map_cpu(prg, ram, bank=2):
    """バンク切替を横取りする 6502。"""
    from retroux.core.bgmap.cpu6502 import Cpu

    class _MapCpu(Cpu):
        def on_jsr(self, target):
            if target in (0xFE95, 0xFE9A, 0xFE9F, 0xC2D0):
                self.bank = {0xFE95: 2, 0xFE9A: 3,
                             0xFE9F: 5}.get(target, self.bank)
                return True
            return False

    return _MapCpu(prg, ram, bank=bank)


def run_builder(prg, map_id, x, y):
    """★★ **ROM だけで地形IDを取る**（2026-08-02 / Stop B）。

    ⚠ セーブステートは要りません。必要なのは:

        $20-$27  マップヘッダ8バイト（ROM の表から）
        $31      map_id
        $1F      マップ種別（map_id から決まる）
        $12/$13  調べる座標
        $0E      ★y をもう一度（掛け算の相手）

    ★`$0E` は `$DFA8` では設定されません（呼び出し元が入れる）。
      ⚠ ここを落とすと、前の値が残って**別の場所を読みます**。
        2026-08-02、実際にそれで手計算と食い違いました。
    """
    ram = bytearray(0x800)
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    ram[0x20:0x28] = prg[off:off + 8]
    ram[0x31] = map_id
    ram[0x1F] = (0 if map_id == 0x01 else 1 if map_id < 0x2B
                 else 2 if map_id < 0x44 else 3)
    ram[0x12], ram[0x13], ram[0x0E] = x & 0xFF, y & 0xFF, y & 0xFF
    cpu = _map_cpu(prg, bytes(ram))
    cpu.stack.append(0)          # ⚠ PLA/TAY があるので1つ積む
    cpu.run(BUILDER_ENTRY, limit=20000)
    return cpu.ram[0x0C]


@needs_rom
def test_ROMだけで地形が取れる():
    """★★ **これが Stop B の到達点**。

    ⚠ セーブステートも FCEUX も要りません。
    """
    prg = load_prg(ROM)
    values = {run_builder(prg, 0x0B, x, y)
              for y in range(26) for x in range(26)}
    assert len(values) >= 4, f"★地形が {sorted(values)} しか出ない"


@needs_rom
@needs_state
def test_セーブステート有無で結果が変わらない():
    """★★ **本物の RAM でも、組み立てた RAM でも同じ**（676/676）。

    ⚠ これが成り立つから「ROM だけで全マップ」が言えます。
    """
    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        if st.byte(0x31) != 0x0B:
            continue
        for y in range(0, 26, 2):
            for x in range(0, 26, 2):
                cpu = _map_cpu(prg, st.ram)
                cpu.ram[0x12], cpu.ram[0x13], cpu.ram[0x0E] = x, y, y
                cpu.stack.append(0)
                cpu.run(BUILDER_ENTRY, limit=20000)
                assert cpu.ram[0x0C] == run_builder(prg, 0x0B, x, y), (x, y)
        return
    pytest.skip("街のセーブステートが無い")


@needs_rom
def test_同じ入力なら同じ結果():
    """★再現性（指示書 Stop B の報告項目）。"""
    prg = load_prg(ROM)
    got = [run_builder(prg, 0x3F, 10, 10) for _ in range(3)]
    assert len(set(got)) == 1


@needs_rom
@pytest.mark.parametrize("map_id", [0x01, 0x07, 0x0B, 0x15, 0x3D, 0x3F,
                                    0x40, 0x59, 0x63])
def test_どの種類のマップでも動く(map_id):
    """★世界地図・城・街・洞窟・塔・祠。⚠ 落ちないこと。"""
    prg = load_prg(ROM)
    values = {run_builder(prg, map_id, x, y)
              for y in range(0, 12, 3) for x in range(0, 12, 3)}
    assert values, "★1つも取れていない"
    # ★ダンジョン（種別2以上）は 4 刻みになる
    if 0x2B <= map_id:
        assert all(v % 4 == 0 for v in values), sorted(values)


@needs_rom
def test_実コードと手計算が一致する():
    """★写しが正しいことを、本物と突き合わせて確かめる。

    ⚠ `$0E` を入れ忘れると食い違います（2026-08-02 に踏んだ）。
    """
    prg = load_prg(ROM)
    for y in range(0, 26, 3):
        for x in range(0, 26, 3):
            assert run_builder(prg, 0x0B, x, y) == terrain_id(prg, 0x0B, x, y)


# --- ★★ Stop C: 1マップを ROM から作る ★★ ---------------------------

def _screen_cells(st, prg):
    """セーブステートの画面から `(x, y, 地形ID, タイル4枚)` を出す。"""
    map_id = st.byte(0x31)
    px, py = st.byte(0x16), st.byte(0x17)
    sx, sy = st.byte(0x05), st.byte(0x06)
    nt = st.nametable
    for cy in range(10):
        for cx in range(16):
            col, row = cx * 2 + sx // 8, cy * 2 + sy // 8
            c64 = col % 64
            base = 0 if c64 < 32 else 0x400
            quad = tuple(nt[base + ((row + dy) % 30) * 32 + ((c64 + dx) % 32)]
                         for dy in (0, 1) for dx in (0, 1))
            if min(quad) < 0x90:
                continue
            x, y = px + cx - 8, py + cy - 7
            if x < 0 or y < 0:
                continue
            yield x, y, terrain_id(prg, map_id, x, y), quad


@needs_rom
@needs_state
def test_街は地形IDから絵がほぼ決まる():
    """★★ **Stop C の到達点（街）**（2026-08-02）。

    ⚠ 変換表は**実測から**作っています。ROM のどこにあるかは未解明です。
      ★見たマスからしか作れないので、未知の地形IDは埋まりません。

    実測（map $0B / 160 マス）:

        地形  1 -> 94949494    地形  6 -> C5C7C4C6
        地形  2 -> 95959595    地形 13 -> BDBFBCBE
        地形  4 -> A1A0A0A1    地形 24 -> B5B7B4B6

    ★一致 150/160（93.8%）。
    ⚠ 外れた 10 マスは**すべて `F9F9DCDC`** で、(21-23, 12-15) の
      矩形に固まっています（★何かが地形の上に置かれている。未解明）。
    """
    from collections import defaultdict

    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        if st.byte(0x31) != 0x0B:
            continue
        table = defaultdict(lambda: defaultdict(int))
        cells = list(_screen_cells(st, prg))
        for _x, _y, t, quad in cells:
            table[t][quad] += 1
        best = {t: max(d.items(), key=lambda kv: kv[1])[0]
                for t, d in table.items()}
        ok = sum(1 for _x, _y, t, q in cells if best.get(t) == q)
        assert len(cells) >= 150, f"★{len(cells)} マスしか見えていない"
        assert ok / len(cells) >= 0.93, f"★一致が {ok}/{len(cells)}"
        # ⚠ 外れたものが1種類に固まっていること（★ばらけたら別の問題）
        missed = {q for _x, _y, t, q in cells if best.get(t) != q}
        assert len(missed) <= 1, f"★外れ方がばらけている: {missed}"
        return
    pytest.skip("街のセーブステートが無い")


@needs_rom
@needs_state
def test_ダンジョンは壁向き補正が要る():
    """⚠⚠ **Stop C はダンジョンでは未達**（2026-08-02）。

    ダンジョンの地形IDは **0 / 4 / 8 / 28 の4種類しかなく**、
    それぞれに**複数の絵**が対応します:

        map $3F 地形 28 -> 9 通りの絵
        map $3F 地形  0 -> 5 通りの絵

    ★指示書 3.5 が言う「周囲の壁配置を見て壁向きを補正する」処理が
      あるはずで、それを見つけるまでダンジョンの絵は決まりません。

    ⚠ 街（種別1）はほぼ 1 対 1 なので、そちらだけ先に使えます。

    ★補正処理が見つかったらこのテストを直して前へ進めること。
    """
    from collections import defaultdict

    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    worst = 0
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        map_id = st.byte(0x31)
        if map_id is None or not (0x2B <= map_id < 0x44):
            continue
        table = defaultdict(set)
        for _x, _y, t, quad in _screen_cells(st, prg):
            table[t].add(quad)
        if table:
            worst = max(worst, max(len(v) for v in table.values()))
    if worst == 0:
        pytest.skip("ダンジョンのセーブステートが無い")
    assert worst >= 4, (
        f"★1つの地形IDに対する絵が最大 {worst} 通りまで減った。"
        "壁向き補正が解けたのなら、この歯止めを外して前へ進めること")


# --- ★★★ 地形ID → 4枚CHR の変換表（2026-08-02）★★★ ------------------

#: 種別ごとの変換表の先頭（CPU 番地）。★`$DC6F` から 2 バイト × 4 種
TERRAIN_TABLES = {0: 0x83B3, 1: 0x8453, 2: 0x851B, 3: 0x85E3}
#: ★表は **bank2**（実測で 7/7 一致）
TABLE_BANK = 2
#: 1件のバイト数（タイル4枚 ＋ 属性）
TABLE_ENTRY = 5


def metatile_of_terrain(prg, kind, terrain):
    """★`$DD64` の式そのまま。

    ```
    DD64: LDA $1F / ASL / TAY        ; 種別で索引
    DD68: LDA $0C / ASL / ASL / ADC $0C   ; ★地形ID × 5
    DD6E: ADC $DC6F,Y / STA $10      ; 種別ごとの表の先頭を足す
    DD74: LDA $DC6F,Y / ADC #$00 / STA $11
    ```
    """
    base = (TABLE_BANK * 0x4000 + (TERRAIN_TABLES[kind] - 0x8000)
            + terrain * TABLE_ENTRY)
    return tuple(prg[base:base + 4]), prg[base + 4]


@needs_rom
def test_変換表の場所がコードと合っている():
    """★`$DC6F` に、種別ごとの表の先頭が 2 バイトずつ並ぶ。"""
    prg = load_prg(ROM)
    for kind, want in TERRAIN_TABLES.items():
        off = 0x1DC6F + kind * 2
        assert prg[off] | (prg[off + 1] << 8) == want, f"種別{kind}"


@needs_rom
def test_地形IDに5を掛ける():
    """⚠ ×4 でも ×8 でもなく **×5**（`ASL / ASL / ADC $0C`）。"""
    prg = load_prg(ROM)
    layout = Layout(prg)
    texts, offset = [], 0x1DD68
    for _ in range(4):
        insn = decode(prg, offset, layout.address_of(offset))
        texts.append(insn.text())
        offset += insn.size
    assert texts == ["LDA $0C", "ASL", "ASL", "ADC $0C"]


@needs_rom
def test_表の中身が実測と合う():
    """★★ **これが変換表である裏づけ**（街 / 種別1）。"""
    prg = load_prg(ROM)
    want = {1: (0x94, 0x94, 0x94, 0x94), 2: (0x95, 0x95, 0x95, 0x95),
            3: (0x9D, 0x9F, 0x9C, 0x9E), 4: (0xA1, 0xA0, 0xA0, 0xA1),
            6: (0xC5, 0xC7, 0xC4, 0xC6), 13: (0xBD, 0xBF, 0xBC, 0xBE),
            24: (0xB5, 0xB7, 0xB4, 0xB6)}
    for terrain, quad in want.items():
        assert metatile_of_terrain(prg, 1, terrain)[0] == quad, terrain


@needs_rom
@needs_state
def test_街は表だけで9割合う():
    """★表から引いた4枚が、画面と **93%** 合う（map $0B）。

    ⚠ 実測から作った表ではなく、**ROM の表**を引いています。
    """
    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        if st.byte(0x31) != 0x0B:
            continue
        cells = list(_screen_cells(st, prg))
        ok = sum(1 for _x, _y, t, q in cells
                 if metatile_of_terrain(prg, 1, t)[0] == q)
        assert ok / len(cells) >= 0.90, f"★{ok}/{len(cells)}"
        return
    pytest.skip("街のセーブステートが無い")


@needs_rom
@needs_state
def test_ダンジョンは表だけでは合わない():
    """⚠⚠ **未達を隠さない**（2026-08-02）。

    ★表を引くだけでは 0〜77% にばらけます:

        map $3D 76.7%  /  map $3E 0.0%  /  map $3F 36.4%

    ⚠ 指示書 4 が言う「近傍参照を伴う壁向き補正」が要ります。
    ★補正が解けたらこのテストを直して前へ進めること。
    """
    from retroux.core.bgmap.savestate import NotASaveState, load

    prg = load_prg(ROM)
    rates = []
    for path in _states:
        try:
            st = load(path)
        except NotASaveState:
            continue
        map_id = st.byte(0x31)
        if map_id is None or not (0x2B <= map_id < 0x44):
            continue
        cells = list(_screen_cells(st, prg))
        if not cells:
            continue
        ok = sum(1 for _x, _y, t, q in cells
                 if metatile_of_terrain(prg, 2, t)[0] == q)
        rates.append(ok / len(cells))
    if not rates:
        pytest.skip("ダンジョンのセーブステートが無い")
    assert max(rates) < 0.90, (
        f"★ダンジョンが {max(rates):.1%} まで合うようになった。"
        "壁向き補正が解けたのなら、この歯止めを外して前へ進めること")


# --- ⚠⚠ 単調なセルで 100% を出さない（2026-08-02 の教訓）------------

def test_単調なサンプルの一致率は合格に使わない():
    """⚠⚠ **2026-08-02、これで「100%一致」を誤って出しました。**

    見えた範囲がほぼ全部 `B0B0B0B0`（一色）だったため、
    2×2 展開しても同じ絵で、当たり前に一致していました。

    ★合格判定には **4枚がばらばらのセルだけ**を使います。
    """
    cells = [((0xB0,)*4, (0xB0,)*4)] * 100      # ★全部同じ絵
    assert stratified_rate(cells) is None, (
        "★単調なサンプルから率を返してはいけない")

    mixed = [((0xA1, 0xA5, 0xA0, 0xA4), (0xA1, 0xA5, 0xA0, 0xA4))] * 8 \
        + [((0xB0,)*4, (0xB0,)*4)] * 92
    rate = stratified_rate(mixed)
    assert rate == 1.0, "★ばらばらのセルだけで判定する"


def stratified_rate(cells, least=5):
    """★4枚がばらばらのセルだけで一致率を出す。

    ⚠ そういうセルが `least` 件に満たなければ **None**（判定しない）。
      「材料が薄いのに率だけ高い」を防ぎます。
    """
    varied = [(p, a) for p, a in cells if len(set(a)) > 1]
    if len(varied) < least:
        return None
    return sum(1 for p, a in varied if p == a) / len(varied)


# --- ★ 外した歯止め（2026-08-11）----------------------------------------
#
# ★★ `test_層化サンプルで測ると9割に届かない` はここにありました。★★
#
#   「2×2 展開の規則を当てると 87.9% で、9割に届かない」という**自分向けの
#   歯止め**で、「9割を超えたら外して前へ進め」という約束でした。
#
#   ⚠ 2026-08-03 に世界地図の復号が **100%** になり、そこから発火し続けて
#     いました（★回帰ではありません）。2026-08-11、依頼者の決定
#     「世界地図は見た範囲だけ／色は ROM から」で**前へ進んだ**ので、
#     約束どおり外します。
#
#   ★いま何が言えるかは、こちらで測っています:
#     - 街・ダンジョン: `test_街は表だけで9割合う` / `tests/test_dungeon_map.py`
#     - 世界地図      : `tests/test_world_art.py` と
#                       `research/probes/active/world_metatile_check.py`
#                       （★地形IDごとの最頻メタタイルが ROM と食い違い 0）
#
#   ⚠ 消したのは**歯止め**であって、測るのをやめたのではありません。

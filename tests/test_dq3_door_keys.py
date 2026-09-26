"""扉と鍵 ― ★道具 ID と段位（RX3-0014 / RX3-0078 / 2026-09-07）。

⚠ `RX3-0014` は「実機で確定する」で **BLOCKED** でした。★ROM で解けました。

## ★この検査が守るもの

```text
① ROM のコードと同じ分岐（★段位ごとに開く扉）
② ⚠⚠ 表の索引と道具 ID のずれ（★索引 = 道具 ID - 73）を**ROM から**確かめる
③ ★鍵 3 種が名前のとおりであること（⚠ ID をここに書き写して終わりにしない）
```
"""
from __future__ import annotations

import pathlib

import pytest

from dq3rom import door_keys as DK

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


@pytest.fixture(scope="module")
def prg():
    return ROM_PATH.read_bytes()[16:]


# ----------------------------------------------------------------------
# ★① 分岐（⚠ ROM 不要）
# ----------------------------------------------------------------------
@pytest.mark.parametrize("rank,want", [
    (0, {DK.DOOR_ANY}),
    (1, {DK.DOOR_ANY, DK.DOOR_MAGIC}),
    (3, {DK.DOOR_ANY, DK.DOOR_MAGIC, DK.DOOR_FINAL}),
])
def test_段位ごとに開く扉(rank, want):
    assert {n for n in DK.DOOR_NIBBLES if DK.opens(n, rank)} == want


def test_扉でないタイルは開かない():
    for n in (0x00, 0x01, 0x0A, 0x0E, 0x0F):
        assert not DK.opens(n, 3), n
        assert DK.needed_key(n) is None


def test_要る鍵はいちばん弱いもの():
    assert DK.needed_key(DK.DOOR_ANY) == 88       # ★とうぞくのかぎ
    assert DK.needed_key(DK.DOOR_MAGIC) == 89     # ★まほうのかぎ
    assert DK.needed_key(DK.DOOR_FINAL) == 90     # ★さいごのかぎ


def test_鍵でない道具の段位はNone():
    """⚠ `None` と `0` を混ぜない（★段位 0 は「とうぞくのかぎを持っている」）。"""
    got = DK.rank_of(1)
    assert got is None and got is not 0          # noqa: F632 ★意図して is で見る


def test_持ち物からいちばん強い段位():
    assert DK.party_rank([88, 89]) == 1
    assert DK.party_rank([90, 88]) == 3
    assert DK.party_rank([1, 2, 3]) == -1, "⚠ 鍵が無いのに段位が出た"
    assert DK.party_rank([]) == -1


# ----------------------------------------------------------------------
# ★② ROM と突き合わせる
# ----------------------------------------------------------------------
@needs_rom
def test_段位を作る入口がROMのとおり(prg):
    """★`LDA #imm` の値が段位そのもの。"""
    b12 = prg[12 * 0x4000:13 * 0x4000]
    for cpu, rank in DK.RANK_ENTRY.items():
        i = cpu - 0x8000
        assert b12[i] == 0xA9 and b12[i + 1] == rank, "⚠ $%04X" % cpu
    assert b12[0x97F0 - 0x8000:0x97F0 - 0x8000 + 2] == bytes([0x85, 0xB6])


@needs_rom
def test_踏み台がBRKで段位の入口へ飛ぶ(prg):
    """★bank0 の `BRK arg; RTS` が、⚠ 段位と対応していること。"""
    from dq3rom import farcall
    from dq3rom import profile as dq3

    b0 = prg[0:0x4000]
    ident = dq3.load_and_identify(ROM_PATH)
    by_arg = {r.arg: r for r in farcall.routines(ident)}
    for cpu, rank in DK.RANK_STUB.items():
        i = cpu - 0x8000
        assert b0[i] == 0x00, "⚠ $%04X が BRK でない" % cpu
        arg = b0[i + 1]
        assert DK.RANK_BRK_ARG[arg] == rank, "⚠ arg %d の段位が違う" % arg
        got = by_arg[arg]
        assert got.bank == 12, got
        assert DK.RANK_ENTRY[got.address] == rank, got


@needs_rom
def test_表の索引と道具IDのずれをROMから確かめる(prg):
    """⚠⚠ **ここが要**（★索引 = 道具 ID - 73）。

    ★`$B06D` の表で、鍵 3 種の索引がちょうど踏み台を指すこと。
    ⚠ ずれが 1 でも違えば、★別の道具を鍵だと言ってしまいます。
    """
    table = DK.read_use_table(prg, 60)
    for item_id, rank in DK.KEY_ITEMS.items():
        k = DK.use_script_index(item_id)
        assert k is not None and k < len(table), item_id
        _mark, ptr = table[k]
        assert DK.RANK_STUB[ptr] == rank, (
            "⚠ 道具 %d（索引 %d）が $%04X を指している" % (item_id, k, ptr))


@needs_rom
def test_ずれを1つずらすと合わなくなる(prg):
    """⚠ 「たまたま合った」でないこと（★前後にずらすと崩れる）。"""
    table = DK.read_use_table(prg, 60)
    for shift in (-1, 1):
        ok = True
        for item_id, rank in DK.KEY_ITEMS.items():
            k = DK.use_script_index(item_id) + shift
            if not (0 <= k < len(table)) or DK.RANK_STUB.get(table[k][1]) != rank:
                ok = False
        assert not ok, "⚠⚠ %+d ずらしても合ってしまう（★この検査は空回り）" % shift


@needs_rom
def test_鍵3種の名前がかぎで終わる():
    """⚠ ID を書き写して終わりにしない（★名前まで ROM から確かめる）。"""
    from dq3rom import names

    items = names.load_cached(ROM_PATH)["names"]["item"]
    got = {i: items.get(i, items.get(str(i))) for i in DK.KEY_ITEMS}
    assert all(str(v).endswith("かぎ") for v in got.values()), got
    # ★段位の順 = 名前の並び順（⚠ とうぞく → まほう → さいご）
    order = [i for i, _r in sorted(DK.KEY_ITEMS.items(), key=lambda kv: kv[1])]
    assert order == sorted(DK.KEY_ITEMS), got


@needs_rom
def test_表に載るのは装身具と道具だけ(prg):
    """★索引のずれの裏取り（⚠ 武器・防具が 1 つも入らないこと）。

    ⚠ 分類は `dq3rom/items.py` が**別の道**（ID の範囲）で出したものです。
    ★ずれが違えば、武器や鎧が表に入ってきます。
    """
    from dq3rom import items as IT

    table = DK.read_use_table(prg, 40)
    kinds = {IT.category_of(k + DK.USE_TABLE_FIRST_ITEM) for k in range(len(table))}
    assert kinds <= {"そうしょくひん", "どうぐ"}, "⚠ 表に別の分類が入っている: %s" % kinds
    # ⚠ 1 つ手前は**まだ装身具**（★ここが境目ではないので、境目で説明しない）
    assert IT.category_of(DK.USE_TABLE_FIRST_ITEM - 1) == "そうしょくひん"


# ----------------------------------------------------------------------
# ⚠⚠ 2 つの数え方が食い違っていないか（★同じ判定を 2 か所に書かない）
# ----------------------------------------------------------------------
def test_doorsの段と実機の段位が同じ結論になる():
    """★`dq3rom/doors.py` は並び（1/2/3）、⚠ こちらは実機の段位（0/1/3）。

    ⚠⚠ 数え方が違うので、★**結論が同じ**ことを突き合わせます
    （= どの鍵がどの扉を開けるか）。⚠ 片方だけ直すと、ここが赤くなります。
    """
    from dq3rom import doors

    for nibble, door_rank in doors.DOOR_RANK.items():
        by_doors = {i for i, r in doors.KEY_RANK.items() if r >= door_rank}
        by_rom = {i for i, r in DK.KEY_ITEMS.items() if DK.opens(nibble, r)}
        assert by_doors == by_rom, (
            "⚠⚠ 扉 $%02X で食い違い: doors=%s / ROM=%s"
            % (nibble, sorted(by_doors), sorted(by_rom)))


def test_鍵のIDは1か所だけに書く():
    """⚠ `doors.KEY_RANK` は `door_keys.KEY_ITEMS` から作られていること。"""
    from dq3rom import doors

    assert set(doors.KEY_RANK) == set(DK.KEY_ITEMS)
    # ★並びも同じ（⚠ 弱い鍵ほど小さい）
    assert ([i for i, _ in sorted(doors.KEY_RANK.items(), key=lambda kv: kv[1])]
            == [i for i, _ in sorted(DK.KEY_ITEMS.items(), key=lambda kv: kv[1])])


@needs_rom
def test_扉の要件はもう推測ではない():
    """★`RX3-0014` が閉じたので、⚠ `inferred` が残っていないこと。"""
    from dq3rom import doors
    from dq3rom import profile as dq3

    from dq3rom import area_maps as am

    ident = dq3.load_and_identify(ROM_PATH)
    got = doors.build(ident, [m for m in am.decode_all(ident) if m.ok])
    rows = [d.to_json() for d in list(got)[:20]]
    assert rows, "⚠ 扉が 1 つも取れない（★この検査は空回り）"
    for row in rows:
        for req in row["requirements"]:
            assert req["confidence"] == "confirmed", req
            assert set(req["item_ids"]) <= set(DK.KEY_ITEMS), req

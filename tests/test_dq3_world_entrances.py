"""世界地図の入口表（RX3-0067 / 2026-09-16）。

## ⚠ 確度は `OBSERVED`（★読む ROM のコードは見つけていません）

だから検査は「コードと同じか」ではなく、⚠ **独立した 2 本が合うか**を見ます。

```text
① ROM の構造   世界地図へ出る出口を持つ map（0..64）が、表でも入口の升を指す
               ⚠ 合わないのは map 4 の 1 件だけ（★`KNOWN_ODD` に出してある）
② 依頼者の記録  ROM 名・手入力の場所と、表の升が近い
               ⚠ 1〜2 升のずれは「入る 1 歩手前の升」を記録しているため（RX3-0275）
③ 行番号 = map 番号   ★これが表の読み方の要
```

⚠⚠ ②は**依頼者が遊んだ記録**を読みます。★無い環境では skip します
（`work/dq3-knowledge/location-book.json`）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3rom import world_entrances as WE

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
BOOK = ROOT / "work" / "dq3-knowledge" / "location-book.json"
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")
needs_book = pytest.mark.skipif(not BOOK.exists(), reason="⚠ 依頼者の記録がありません")


def _ident():
    from dq3rom import profile as dq3
    return dq3.load_and_identify(ROM_PATH)


# ----------------------------------------------------------------------
# ★③ 行番号 = map 番号
# ----------------------------------------------------------------------
@needs_rom
def test_表は65件で2件だけ空():
    got = WE.read(_ident())
    assert sorted(got) == list(range(WE.COUNT)) == list(range(65))
    assert [m for m, e in got.items() if e.empty] == [5, 13], "⚠ 空の行が変わった"


@needs_rom
def test_行番号がmap番号であること():
    """★ここが読み方の要（⚠ 1 つでもずれたら表の頭が違う）。

    ⚠ 使うのは ROM の名前・手入力で確かな 7 件だけ（★仮名は使わない）。
    """
    got = WE.read(_ident())
    #: ★(map, 世界の升) ― 依頼者の記録の ROM 名・手入力から
    want = {0: (172, 218), 9: (159, 192), 12: (86, 110), 20: (65, 38),
            21: (42, 189), 22: (158, 99), 63: (30, 60)}
    for m, cell in want.items():
        assert (got[m].x, got[m].y) == cell, (
            "⚠⚠ map %d の升が (%d,%d) ではなく (%d,%d)" % (m, *cell, got[m].x, got[m].y))


# ----------------------------------------------------------------------
# ★① ROM の構造
# ----------------------------------------------------------------------
@needs_rom
def test_世界へ出るmapは表でも入口の升を指す():
    """⚠ 合わないのは map 4 だけ。★増えたら読み方を疑う。"""
    bad = WE.disagreements(_ident())
    assert len(bad) == len(WE.KNOWN_ODD), bad
    for m in WE.KNOWN_ODD:
        assert any("map %d " % m in line for line in bad), bad


@needs_rom
def test_ほとんどの行が主世界の入口の升():
    s = WE.summary(_ident())
    assert s["maps"] == 65 and s["empty"] == 2
    assert s["on_main"] >= 45, "⚠ 主世界の入口を指す行が %d 件しかない" % s["on_main"]


@needs_rom
def test_同じ升に2つのmapが載っていない():
    """★引っくり返して「升 → map」にできること（⚠ 重なっていたら決まらない）。"""
    cells = WE.by_cell(_ident())
    dup = {k: v for k, v in cells.items() if len(v) > 1}
    assert not dup, "⚠ 同じ升から 2 つの map へ入ることになっている: %s" % dup


@needs_rom
def test_主世界の入口の升をほぼ覆う():
    """⚠ 「表が本物か」の裏。★入口の升 50 個のうち、ほとんどが表に出る。"""
    ident = _ident()
    main = WE.entrance_cells(ident, "world_main")
    got = set(WE.by_cell(ident))
    assert len(main) == 50, "⚠ 入口の升の数が変わった: %d" % len(main)
    assert len(main & got) >= 45, "⚠ 覆えたのは %d / %d" % (len(main & got), len(main))


@needs_rom
def test_どちらの世界かは入口の升で決まる():
    """★map_graph に渡す材料（RX3-0067）。⚠ 決まらないのは map 4 だけ。"""
    got = WE.world_links(_ident())
    worlds = [r["world"] for r in got["entrances"]]
    assert worlds.count("world_main") == 49, worlds.count("world_main")
    assert worlds.count("world_alefgard") == 13, "⚠ アレフガルドの行は 13 件のはず"
    assert got["unplaced"] == list(WE.KNOWN_ODD), got["unplaced"]
    assert got["sizes"]["world_main"] == (256, 256)
    assert got["sizes"]["world_alefgard"] == (158, 138)


# ----------------------------------------------------------------------
# ★② 依頼者の記録と突き合わせ（⚠ 無ければ skip）
# ----------------------------------------------------------------------
@needs_rom
@needs_book
def test_依頼者の記録と近い():
    """⚠ ぴったりでなくてよい（★記録は「入る 1 歩手前の升」/ RX3-0275）。

    ⚠⚠ だから **1〜2 升のずれは合格**、★遠いものだけ数えます。
    """
    ident = _ident()
    table = WE.read(ident)
    book = json.loads(BOOK.read_text(encoding="utf-8"))
    locs = book["locations"]
    rows = list(locs.values()) if isinstance(locs, dict) else locs
    near = far = 0
    for r in rows:
        if r.get("world_x") is None or not r.get("map_ids"):
            continue
        if r.get("name_source") not in ("rom", "manual"):
            continue                       # ⚠ 仮名は使わない
        m = r["map_ids"][0]
        if m >= WE.COUNT:
            continue
        e = table[m]
        d = abs(e.x - int(r["world_x"])) + abs(e.y - int(r["world_y"]))
        near += d <= 2
        far += d > 2
    assert near >= 10, "⚠ 突き合わせられた場所が %d 件しかない（★検査が薄い）" % near
    assert far <= 3, "⚠⚠ 遠い場所が %d 件（★ルーラの升は 2 件のはず）" % far
    assert near > far * 3, (near, far)

"""鍵があれば扉の向こうへ行ける（RX3-0078 / 2026-09-07）。

★`RX3-0014` で鍵の道具 ID が確定したので、⚠ BFS に入れられるようになりました。

## ⚠ 既定の振る舞いは変えていません

★`keys` を渡さなければ、⚠ **扉は今までどおり通りません**。
（`RX3-0077`: アリアハンの城で 14 人中 5 人が扉の向こうで候補に出なかった。
 ★そこが直るのは、鍵を持っているときだけです。）
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.testing import passability as P                    # noqa: E402
from dq3rom import door_keys as DK                          # noqa: E402


def _map(rows, table):
    """★文字の絵から偽の地図を作る（⚠ `tiles[y][x]` は tile id）。"""
    tiles = [[ord(c) - ord("0") for c in row] for row in rows]
    return P.RomMap(map_id=1, tiles=tiles, table=table, tileset=0)


#: ★tile 0 = 床 / 1 = 壁 / 2 = どの鍵でも / 3 = まほう / 4 = さいご
TABLE = [0x00, 0x80, 0x8B, 0x8C, 0x8D] + [0x00] * 27

#: ```text
#: 0 1 1
#: 0 2 0     ← ★真ん中が扉
#: 0 1 1
#: ```
ROWS = ["011", "020", "011"]


def test_鍵が無ければ扉は通れない():
    m = _map(ROWS, TABLE)
    assert m.bfs((0, 1), (2, 1)) is None, "⚠⚠ 鍵が無いのに扉を通った"


def test_鍵があれば通れる():
    m = _map(ROWS, TABLE)
    got = m.bfs((0, 1), (2, 1), keys=[88])          # ★とうぞくのかぎ
    assert got == ["right", "right"], got


def test_弱い鍵では強い扉を通れない():
    m = _map(["011", "030", "011"], TABLE)          # ★まほうのかぎの扉
    assert m.bfs((0, 1), (2, 1), keys=[88]) is None, "⚠ とうぞくのかぎで まほうの扉が開いた"
    assert m.bfs((0, 1), (2, 1), keys=[89]) == ["right", "right"]
    assert m.bfs((0, 1), (2, 1), keys=[90]) == ["right", "right"], "⚠ 強い鍵は弱い扉も開ける"


def test_さいごのかぎだけが最後の扉を開ける():
    m = _map(["011", "040", "011"], TABLE)
    for keys in ([], [88], [89], [88, 89]):
        assert m.bfs((0, 1), (2, 1), keys=keys) is None, keys
    assert m.bfs((0, 1), (2, 1), keys=[90]) == ["right", "right"]


@pytest.mark.parametrize("keys", [[], [88], [89], [90], [88, 89], [88, 90], [89, 90], [88, 89, 90]])
def test_鍵は上位互換で扉を開ける_総当たり(keys):
    """★RX3-0244（依頼者「カギは上位互換 さいごのカギ＞まほうのカギ＞とうぞくのかぎ」）。

    ★持っている鍵のうち**いちばん上の鍵**で決まる: とうぞく → $0B / まほう → $0B・$0C / さいご → 全部。
    ⚠ 下位の鍵を持っていなくても、上位の鍵があれば下位の扉を通る。
    """
    top = max(keys) if keys else None
    opens = {2: top is not None, 3: top in (89, 90), 4: top == 90}    # ★tile 2 = $0B / 3 = $0C / 4 = $0D
    for tile, want in opens.items():
        m = _map(["011", "0%d0" % tile, "011"], TABLE)
        got = m.bfs((0, 1), (2, 1), keys=keys)
        assert (got == ["right", "right"]) is want, "⚠ 鍵 %s で扉 tile %d: 通れる=%s のはず" % (keys, tile, want)


def test_鍵でない道具を渡しても開かない():
    m = _map(ROWS, TABLE)
    assert m.bfs((0, 1), (2, 1), keys=[1, 2, 101]) is None


def test_扉の升かどうかを引ける():
    m = _map(ROWS, TABLE)
    assert m.door_nibble(1, 1) == DK.DOOR_ANY
    assert m.door_nibble(0, 1) is None            # ★床
    assert m.door_nibble(9, 9) is None            # ⚠ 地図の外
    assert m.door_open(1, 1, keys=[88]) is True
    assert m.door_open(1, 1, keys=[]) is False
    assert m.door_open(0, 1, keys=[90]) is False, "⚠ 床を「開く」と言った"


def test_経路に扉が含まれることを呼び手へ伝える():
    """★開ける操作が要るので、⚠ **どこが扉か**を返す（`navigation.plan`）。"""
    from dq3.testing import navigation as N

    m = _map(["0110", "0200", "0110"], TABLE)
    got = N.plan(m, (0, 1), (3, 1), keys=[88])
    assert got is not None
    assert [tuple(d) for d in got["doors"]] == [(1, 1)], got["doors"]


def test_扉が無ければdoorsは空():
    from dq3.testing import navigation as N

    m = _map(["0110", "0000", "0110"], TABLE)
    got = N.plan(m, (0, 1), (3, 1))
    assert got is not None and got["doors"] == []


def test_Luaへ渡す地図は開けた扉だけOで_閉じた扉はDのまま():
    """★RX3-0263（2026-09-14）: ⚠ 以前は開けた後も `D`（壁）→ Lua の作り直しが開けた扉を通れず遠回りした。

    ★この場で開けた扉だけ `O`（door_open / Lua が通す）/ ⚠ 閉じた扉は `D`（door_closed）= 壁のまま。
    ⚠ 扉でない升は `opened` に来ても変えない（★覚え違いで壁や床を書き換えない）。
    """
    from dq3.knowledge.town_service import TownService

    m = _map(["011", "020", "011"], TABLE)                    # ★(1, 1) が扉
    closed = TownService.grid_text(m).splitlines()
    assert closed[2] == "PDP", "⚠ 閉じた扉が D でない: %r" % closed
    opened = TownService.grid_text(m, opened=[(1, 1)]).splitlines()
    assert opened[2] == "POP", "⚠⚠ 開けた扉が O になっていない（★Lua が通れない）: %r" % opened
    assert opened[1] == closed[1] and opened[3] == closed[3], "⚠ 扉の他の升まで変えた"
    same = TownService.grid_text(m, opened=[(0, 1), (1, 0)]).splitlines()
    assert same == closed, "⚠⚠ 扉でない升（床・壁）を O にした"


def test_扉のニブルはROMで確定した():
    """⚠ 2026-09-07（RX3-0014）まで `HYPOTHESIS` でした。"""
    for n in DK.DOOR_NIBBLES:
        assert P.classify(0x80 | n) == (P.DOOR, "CONFIRMED"), n


# ----------------------------------------------------------------------
# ★聞き込みの候補（⚠ 段取りの側）
# ----------------------------------------------------------------------
def test_画面はdq3romを直に触らない():
    """⚠⚠ 2026-09-07 に**破りました**（★`test_UIはROMの正解を読まない` が捕まえた）。

    ★袋 → 鍵 の読み替えは `dq3/knowledge/item_info.py` の担当です。
    """
    import pathlib as _p

    from dq3.ui import town_bar as TB

    src = _p.Path(TB.__file__).read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines()
            if "dq3rom" in ln and not ln.lstrip().startswith("#")
            and "`dq3rom`" not in ln]
    assert not code, "⚠ 画面が dq3rom を触っている: %s" % code


def test_持っている鍵だけを拾う():
    """⚠ 装備中の印（bit7）を落とすこと / ★鍵でない道具は入れない。"""
    from dq3.ui.town_bar import TownNavController

    class _VM:
        def equip_members(self):
            return [{"inventory": [1, 88 | 0x80, 255]}, {"inventory": [89, 101]}]

    ctl = TownNavController(_VM(), object(), object())
    assert ctl.party_keys() == [88, 89]


def test_袋が読めなければ持っていないことにする():
    """⚠ 推測で「持っている」ことにしない。"""
    from dq3.ui.town_bar import TownNavController

    class _VM:
        def equip_members(self):
            raise RuntimeError("⚠ まだ送られていない")

    assert TownNavController(_VM(), object(), object()).party_keys() == []

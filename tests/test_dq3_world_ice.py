"""★世界地図の北と南の氷（RX3-0203 / 2026-09-12）。

依頼者「save6 北の氷河みたいなところがMAPだと砂漠表示されている」。

★ゲームは升 1（砂漠）を、y < 100 と y >= 230 では升 30（氷）として描く（bank 15 $E526）。
⚠ ROM の升の値だけを見ると、氷が砂漠の絵で描かれていた（★save6 の (94..101, 21)）。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import tile_art as TA


def test_行で替える決まり():
    assert TA._game_swap("world_main", 21, 1) == 30, "⚠⚠ 北の升 1 を氷にしていない"
    assert TA._game_swap("world_main", 230, 1) == 30, "⚠⚠ 南の升 1 を氷にしていない"
    assert TA._game_swap("world_main", 99, 1) == 30
    assert TA._game_swap("world_main", 100, 1) == 1, "⚠ 真ん中の砂漠まで氷にした"
    assert TA._game_swap("world_main", 229, 1) == 1
    assert TA._game_swap("world_main", 21, 2) == 2, "⚠ 升 1 のほかまで替えた"
    assert TA._game_swap("world_alefgard", 21, 1) == 1, "⚠ 本土のほかの地図まで替えた"


def test_save6の氷の升が30になる():
    got = TA.world_cells()
    if got is None:
        pytest.skip("ROM が読めません")
    cells, w, _h = got
    for x in range(94, 101):
        assert cells[21 * w + x] == 30, "⚠⚠ (%d,21) が氷にならない（★砂漠の絵で描かれる）" % x
    middle = {cells[y * w + x] for y in range(100, 230) for x in range(w)}
    assert 1 in middle and 30 not in middle, "⚠ 真ん中の砂漠の升を氷にした / 砂漠が消えた"

"""ダンジョン探索MAP v1 Phase A: 探索済みの升を覚え続ける（RX3-0205 / 2026-09-12）。

依頼者の指示書「DQ3 ダンジョン探索MAP v1」§1・§3・§17:

```text
ROM MAP       ⚠ 通常の画面には出さない
Visible MAP   いま画面に映っていて、勇者と同じ層の升（★その場で計算）
Explored MAP  一度でも Visible だった升（★保存する / 消さない）
```

⚠ 「いま居る小部屋だけ出る」原因: 別の層の升を黒く描く決まり（RX3-0191）で、前の部屋が黒くなっていた。
→ ★探索済みの別の部屋は、黒くせず地形を描いて影をかぶせる。
"""
from __future__ import annotations

import json
import os

import pytest

from dq3.knowledge import explored_map as EM
from dq3.knowledge import tile_art as TA

W, H = 40, 20


def _live(kind=5, map_id=45):
    """★2 つの部屋（左 = 層 0x00 / 右 = 層 0x40）。★x < 20 が左の部屋。"""
    cells = bytes((0x02 if x < 20 else 0x43) for _y in range(H) for x in range(W))
    return TA.RuntimeArt(art=None, kind=kind, map_id=map_id, width=W, height=H, cells=cells, chr_checksum=0)


# --- ★Visible MAP ------------------------------------------------------------

def test_映った升のうち同じ層だけが見えている():
    got = set(EM.visible_cells(_live(), 15, 10))   # ★画面は x 7..22 / y 3..17
    assert (15, 10) in got and (7, 3) in got and (19, 17) in got
    assert not any(x >= 20 for x, _y in got), "⚠⚠ 別の部屋（別の層）まで見えたことにした"
    assert all(7 <= x <= 22 and 3 <= y <= 17 for x, y in got), "⚠⚠ 画面の外（未探索）まで入れた"


def test_勇者の升が読めなければ何も見えていない():
    assert EM.visible_cells(_live(), 99, 99) == []


# --- ★Explored MAP -----------------------------------------------------------

def test_次の部屋へ移っても前の部屋が残る(tmp_path):
    store = EM.ExploredMap(tmp_path / "explored.json")
    live = _live()
    store.mark_cells("L45", EM.visible_cells(live, 15, 10))
    first = set(store.cells("L45"))
    assert first
    store.mark_cells("L45", EM.visible_cells(live, 30, 10))      # ★隣の部屋へ
    now = store.cells("L45")
    assert first <= now, "⚠⚠ 次の部屋へ移ったら前の部屋が消えた"
    assert any(x >= 20 for x, _y in now), "⚠ 入った部屋が探索済みにならない"
    store.mark_cells("L45", EM.visible_cells(live, 15, 10))      # ★戻る
    assert store.cells("L45") == now, "⚠ 再訪で記録が変わった"


def test_保存して読み直しても残り_地図ごとに分かれる(tmp_path):
    path = tmp_path / "explored.json"
    store = EM.ExploredMap(path)
    store.mark_cells("L45", [(1, 2), (3, 4)])
    store.mark_cells("L46", [(1, 2)])                          # ★別の map_id（塔の別の階など）
    assert store.save(force=True)
    again = EM.ExploredMap.load(path)
    assert again.cells("L45") == {(1, 2), (3, 4)}, "⚠⚠ 読み直したら消えた"
    assert again.cells("L46") == {(1, 2)}, "⚠⚠ 別の地図と混ざった"
    assert again.cells("L47") == set()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["kind"] == EM.KIND and body["maps"]["L45"]["updated_at"], "⚠ いつ増えたかが残っていない"
    assert again.updated_at["L45"] == body["maps"]["L45"]["updated_at"]


def test_見た升の記録とは別のファイル():
    from dq3.knowledge import seen_map

    assert EM.DEFAULT_PATH != seen_map.DEFAULT_PATH, "⚠⚠ 依頼者の「見た升」の記録を書き換える"
    assert EM.DEFAULT_PATH.name == "explored.json"


def test_画面が記録する_ローカルだけ_今の地図の材料のときだけ(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel(state_path=tmp_path / "state.json", knowledge_path=tmp_path / "k.json",
                      seen_path=tmp_path / "seen.json")
    assert vm.explored_path == tmp_path / "explored.json", "⚠⚠ 検査が本物の記録を読み書きする"
    # ⚠ 材料の置き場も一時フォルダへ（★既定は work/dq3-probe の本物 = 遊んでいる人の今の地図で上書きされる）
    vm.tile_art_dir = tmp_path / "probe"
    vm._tile_art_runtime = _live()
    assert vm.note_explored(0, 45, 15, 10) == 0, "⚠ 世界地図まで探索済みにした（★層が無い）"
    assert vm.note_explored(5, 46, 15, 10) == 0, "⚠⚠ 別の地図の材料で層を決めた"
    assert vm.note_explored(5, 45, 15, 10) > 0
    assert (tmp_path / "explored.json").exists(), "⚠ 保存していない（★再起動で消える）"
    assert not any(x >= 20 for x, _y in vm.explored.cells("L45"))


# --- ★MAP の描き分け -----------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Art:
    """★索引ごとに違う色の絵（★黒 = 別の層）。"""

    def block(self, raw, hero_raw=None):
        idx = TA.index_of(raw, hero_raw)
        rgb = (0, 0, 0) if idx == TA.DARK_INDEX else (40 + idx * 6, 160, 90)
        return bytes(rgb) * (TA.CELL * TA.CELL)


class _VM:
    pass


def test_探索済みの別の部屋は黒くせず影をかぶせて描く(qapp):
    from dq3.ui import map_window as MW

    live = _live()
    seen = {(x, 10) for x in range(W)}
    explored = {(x, 10) for x in range(20, 25)}               # ★隣の部屋のうち 5 升だけ探索済み
    canvas = MW.MapCanvas(_VM())
    image = canvas._tile_image(live, _Art(), seen, 0, 0, W, H, hero_raw=live.at(15, 10), explored=explored)

    def at(x, y):
        c = image.pixelColor(x * TA.CELL + 8, y * TA.CELL + 8)
        return (c.red(), c.green(), c.blue())

    here, dim, dark, unseen = at(15, 10), at(22, 10), at(30, 10), at(15, 5)
    assert here == (52, 160, 90), here
    assert dark == (0, 0, 0), "前提: 探索していない別の部屋は黒（★ゲームの画面と同じ）"
    assert dim != (0, 0, 0), "⚠⚠ 探索済みの別の部屋が黒いまま（★前の部屋が消えて見える）"
    assert dim[1] < 160, "⚠ 影をかぶせていない（★いまの部屋と見分けられない）"
    assert image.pixelColor(15 * TA.CELL + 8, 5 * TA.CELL + 8).rgb() == MW.UNSEEN.rgb(), (
        "⚠⚠ 見ていない升を描いた（★未探索を出さない）: %s" % (unseen,))

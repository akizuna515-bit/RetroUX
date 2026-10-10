"""ダンジョン探索MAP v1 Phase C: 宝箱の発見・開封・中身を覚える（RX3-0207 / 2026-09-12）。

依頼者の指示書「DQ3 ダンジョン探索MAP v1」§7〜§9・§13・§17:

```text
見つけた   宝箱の升が探索済みになった（⚠ 探索していない宝箱は出さない）
開けた     ゲームの「宝箱を開けた印」（$608E〜 / 193 ビット / MSB から）
中身       開けた後だけ（★道具の辞書 item_info の名前）/ ⚠ 開ける前は出さない
消さない   印が 0 に戻っても（★セーブを読み直した）開けた記録は残す
```
"""
from __future__ import annotations

import os

import pytest

from dq3.knowledge import chest_book as CB

SPOTS = [
    CB.Spot("chest_0045_000", 16, 45, 39, 3, "gold", None, 16),
    CB.Spot("chest_0045_001", 17, 45, 37, 17, "item", 101, None),
    CB.Spot("chest_0046_000", 20, 46, 5, 5, "item", 101, None),
]


def _bits(*opened) -> str:
    """★ゲームと同じ並びの印（★`dq3rom/chest_flags.bit_of` で立てる）。"""
    from dq3rom import chest_flags as F

    raw = bytearray(F.NBYTES)
    for n in opened:
        off, mask = F.bit_of(n)
        raw[off - F.BASE] |= mask
    return raw.hex()


def _book(tmp_path):
    return CB.ChestBook(tmp_path / "chests.json", spots=SPOTS)


def test_探索していない宝箱は記録にも印にも出ない(tmp_path):
    book = _book(tmp_path)
    assert book.update(45, set(), _bits(16, 17)) == 0
    assert book.marks(45) == [] and book.rows() == [], "⚠⚠ 探索していない宝箱を出した（★ROM から先回り）"


def test_見つけた宝箱は未開封で_中身は出さない(tmp_path):
    book = _book(tmp_path)
    assert book.update(45, {(39, 3)}, _bits()) == 1
    assert book.marks(45) == [(39, 3, CB.DISCOVERED)]
    row = book.rows(45)[0]
    assert "item_name" not in row and "reward" not in row, "⚠⚠ 開ける前の中身を記録した: %r" % row


def test_開けたら開封済と中身(tmp_path):
    book = _book(tmp_path)
    book.update(45, {(39, 3), (37, 17)}, _bits())
    assert book.update(45, {(39, 3), (37, 17)}, _bits(16, 17)) == 2
    rows = {r["object_id"]: r for r in book.rows(45)}
    assert rows["chest_0045_000"]["state"] == CB.OPENED and rows["chest_0045_000"]["item_name"] == "16 ゴールド"
    item = rows["chest_0045_001"]
    assert item["state"] == CB.OPENED and item["item_id"] == 101
    assert item["item_name"] == CB.reward_label(SPOTS[1]), "⚠ 中身の名前が道具の辞書と違う"
    assert "opened_before_seen" not in item


def test_中身の名前は道具の辞書と同じ():
    from dq3.knowledge import item_info

    got = item_info.info(101)
    if got is None:
        pytest.skip("ROM が読めません")
    assert CB.reward_label(SPOTS[1]) == got.label


def test_印が0に戻っても開けた記録は残る(tmp_path):
    """⚠ セーブを読み直すと印が 0 に戻る（RX3-0167）。★記録はプレイの知識なので消さない。"""
    book = _book(tmp_path)
    book.update(45, {(39, 3)}, _bits(16))
    book.update(45, {(39, 3)}, _bits())
    assert book.marks(45) == [(39, 3, CB.OPENED)], "⚠⚠ 開けた記録が消えた"


def test_見つけたときにはもう開いていた(tmp_path):
    book = _book(tmp_path)
    book.update(45, {(37, 17)}, _bits(17))
    row = book.rows(45)[0]
    assert row["state"] == CB.OPENED and row.get("opened_before_seen") is True


def test_別の地図の宝箱と混ざらない(tmp_path):
    book = _book(tmp_path)
    book.update(45, {(5, 5), (39, 3)}, _bits(20))       # ★map 46 の宝箱と同じ升・同じ印
    assert [r["object_id"] for r in book.rows()] == ["chest_0045_000"], "⚠⚠ 別の地図の宝箱が混ざった"
    book.update(46, {(5, 5)}, _bits(20))
    assert book.marks(46) == [(5, 5, CB.OPENED)] and book.marks(45) == [(39, 3, CB.DISCOVERED)]


def test_保存して読み直しても残る(tmp_path):
    book = _book(tmp_path)
    book.update(45, {(39, 3), (37, 17)}, _bits(17))
    assert book.save()
    again = CB.ChestBook.load(tmp_path / "chests.json", spots=SPOTS)
    assert again.marks(45) == book.marks(45)
    assert again.rows(45)[1]["item_name"] == book.rows(45)[1]["item_name"]


def test_印の並びはゲームと同じ():
    for n in (0, 7, 8, 16, 192):
        bits = _bits(n)
        assert CB.is_opened(bits, n) is True, "⚠⚠ %d 番の印を読めない（★MSB から）" % n
        assert CB.is_opened(bits, n ^ 1) is False
    assert CB.is_opened("", 3) is None and CB.is_opened("zz", 3) is None


def test_ROMの宝箱_ナジミの塔への洞窟():
    spots = [s for s in CB.rom_spots() if s.map_id == 45]
    if not CB.rom_spots():
        pytest.skip("ROM が読めません")
    assert [(s.index, s.x, s.y) for s in spots] == [(16, 39, 3), (17, 37, 17), (18, 32, 33)]


# --- ★画面につなぐ -----------------------------------------------------------

def test_画面が記録する_探索済みの升と印から(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    vm = Dq3ViewModel(state_path=tmp_path / "state.json", knowledge_path=tmp_path / "k.json",
                      seen_path=tmp_path / "seen.json")
    assert vm.chests_path == tmp_path / "chests.json", "⚠⚠ 検査が本物の記録を読み書きする"
    vm._chests = CB.ChestBook(vm.chests_path, spots=SPOTS)
    vm.explored.mark_cells("L45", [(39, 3)])
    vm._raw = lambda: {"chest_bits": _bits(16)}
    assert vm.note_chests(5, 45) == 2, "⚠ 見つけた・開けたを記録していない"
    assert vm.chest_marks(45) == [(39, 3, CB.OPENED)]
    assert vm.note_chests(0, 45) == 0, "⚠ 世界地図まで宝箱を探した"
    assert (tmp_path / "chests.json").exists(), "⚠ 保存していない（★再起動で消える）"


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_MAPに見つけた宝箱の印を描く(qapp):
    from PySide6.QtGui import QImage, QPainter

    from dq3.ui import map_window as MW

    class VM:
        def chest_marks(self, map_id):
            return [(2, 2, CB.DISCOVERED), (5, 2, CB.OPENED)] if map_id == 45 else []

    canvas = MW.MapCanvas(VM())
    canvas._at_now = (5, 45, 3, 3)
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        drawn = canvas._draw_chests(painter, {"x0": 0, "y0": 0, "unit": 16, "origin": (0, 0),
                                              "kind": 5, "w": 200, "h": 200})
    finally:
        painter.end()
    assert drawn == 2
    closed = image.pixelColor(2 * 16 + 3, 2 * 16 + 8)       # ★枠の左の辺
    opened = image.pixelColor(5 * 16 + 3, 2 * 16 + 8)
    assert (closed.red(), closed.green()) != (0, 0) and closed.red() > closed.blue(), "⚠ 未開封の印（金）が無い"
    assert opened.red() == opened.green() or abs(opened.red() - opened.green()) < 20, "⚠ 開封済みの印（灰）が無い"
    assert (closed.red(), closed.green(), closed.blue()) != (opened.red(), opened.green(), opened.blue()), (
        "⚠⚠ 未開封と開封済みが見分けられない")


# --- ★RX3-0261 宝箱で入手したものを勇者メモへ -------------------------------------------------
#
#   依頼者 2026-09-14「DQ3 追加 Work Item 案」WI-1（★正本の写し `docs/requests/260914_dq3-wi-batch.md`）。

def test_いま開いた宝箱だけを受け取れる(tmp_path):
    book = _book(tmp_path)
    book.update(45, {(39, 3), (37, 17)}, _bits())                  # ★見つけた（まだ開いていない）
    assert book.take_opened() == []
    book.update(45, {(39, 3), (37, 17)}, _bits(16))                # ★1 つ開けた
    got = book.take_opened()
    assert [r["object_id"] for r in got] == ["chest_0045_000"] and got[0]["item_name"] == "16 ゴールド"
    assert book.take_opened() == [], "⚠⚠ 同じ宝箱を 2 度渡した"
    book.update(45, {(39, 3), (37, 17)}, _bits())                  # ★セーブを読み直した（印が 0）
    book.update(45, {(39, 3), (37, 17)}, _bits(16))                # ★また印が立った
    assert book.take_opened() == [], "⚠⚠ セーブを読み直したら同じ宝箱をまた渡した"


def test_見つけたときにもう開いていた宝箱と_読み込んだ記録は渡さない(tmp_path):
    """⚠ 依頼者「起動時に過去31件等を一括で勇者メモへ流し込まない」。"""
    book = _book(tmp_path)
    book.update(45, {(37, 17)}, _bits(17))                        # ★見つけたときにはもう開いていた
    assert book.take_opened() == []
    book.update(45, {(39, 3)}, _bits(16, 17))
    book.save(force=True)
    again = CB.ChestBook.load(tmp_path / "chests.json", spots=SPOTS)
    again.update(45, {(39, 3), (37, 17)}, _bits(16, 17))          # ★再起動した（記録はもう OPENED）
    assert again.take_opened() == [], "⚠⚠ 過去に開けた宝箱を流し込んだ"


def test_勇者メモの文():
    assert CB.memo_text({"reward": "item", "item_name": "てつのやり"}, "ロマリア城") == "ロマリア城　宝箱：てつのやり を入手"
    assert CB.memo_text({"reward": "gold", "item_name": "120 ゴールド"}, "ナジミの塔 #3") == "ナジミの塔 #3　宝箱：120 ゴールド を入手"
    assert CB.memo_text({"reward": "mimic", "item_name": "魔物"}, "洞窟") == "洞窟　宝箱：魔物だった", "⚠⚠ 人食い箱を品にした"
    assert CB.memo_text({"reward": "empty", "item_name": "からっぽ"}) == "宝箱：からっぽだった"
    assert CB.memo_text({"reward": "item", "item_name": "やくそう"}) == "宝箱：やくそう を入手", "⚠ 場所が無いのに名前を推測した"


def test_勇者メモは宝箱ごとに1件_同じ場所の同じ品でも別の件(tmp_path):
    """⚠ 本文 + 場所だけで見ると、同じ場所の同じ品の別の宝箱が消える（★event_id で見分ける / 本文を変えない）。"""
    from dq3.knowledge.memos import CHEST, MemoStore

    store = MemoStore(tmp_path / "memos.jsonl")
    text = "ナジミの塔　宝箱：やくそう を入手"
    a = store.add_if_new(text, source=CHEST, location_id="L45", event_id="chest:chest_0045_001")
    b = store.add_if_new(text, source=CHEST, location_id="L45", event_id="chest:chest_0045_002")
    assert a is not None and b is not None, "⚠⚠ 同じ場所・同じ品の別の宝箱を重複として捨てた"
    assert store.add_if_new(text, source=CHEST, location_id="L45", event_id="chest:chest_0045_001") is None, (
        "⚠⚠ 同じ宝箱を 2 度書いた")
    assert a.source == CHEST and a.event_id == "chest:chest_0045_001"
    again = MemoStore(tmp_path / "memos.jsonl")                      # ★再起動しても
    assert again.add_if_new(text, source=CHEST, location_id="L45", event_id="chest:chest_0045_002") is None
    # ★印の無いメモ（会話など）は今までどおり 本文 + 場所 で見る
    assert store.add_if_new("こんにちは", source="conversation", location_id="L45") is not None
    assert store.add_if_new("こんにちは", source="conversation", location_id="L45") is None


def test_画面が宝箱を勇者メモへ_1つ1件_過去の分は流さない(tmp_path):
    """★いま開いた宝箱ごとに 1 件（★同じ場所・同じ品の別の宝箱も別の件）/ ⚠ 再起動しても過去の分は流さない。"""
    from dq3.ui.view_model import Dq3ViewModel

    def make_vm():
        vm = Dq3ViewModel(state_path=tmp_path / "state.json", knowledge_path=tmp_path / "k.json",
                          seen_path=tmp_path / "seen.json")
        assert vm.memo_path.parent == tmp_path and vm.chests_path.parent == tmp_path, "⚠⚠ 検査が本物の記録に書く"
        return vm

    spots = SPOTS + [CB.Spot("chest_0045_002", 18, 45, 32, 33, "item", 101, None)]   # ★17 と同じ品
    cells = [(39, 3), (37, 17), (32, 33)]
    vm = make_vm()
    vm._chests = CB.ChestBook(vm.chests_path, spots=spots)
    vm.explored.mark_cells("L45", cells)
    bits = {"now": _bits()}
    vm._raw = lambda: {"chest_bits": bits["now"]}
    vm.note_chests(5, 45)                                           # ★見つけた（まだ開いていない）
    assert vm.note_chest_memos() == []
    bits["now"] = _bits(16, 17, 18)                                 # ★3 つ開けた
    vm.note_chests(5, 45)
    made = vm.note_chest_memos()
    texts = [m.text for m in made]
    assert len(made) == 3, texts
    assert any(t.endswith("宝箱：16 ゴールド を入手") for t in texts), texts
    herb = CB.reward_label(spots[1])
    assert sum(1 for t in texts if t.endswith("宝箱：%s を入手" % herb)) == 2, (
        "⚠⚠ 同じ場所・同じ品の別の宝箱が消えた: %r" % texts)
    assert all(m.source == "chest" and (m.event_id or "").startswith("chest:") for m in made)
    assert {m.item_id for m in made} == {None, "101"}, "⚠ 品の番号を残していない（★ゴールドは None）"
    assert vm.note_chest_memos() == [], "⚠⚠ 同じ宝箱を 2 度書いた"
    bits["now"] = _bits()                                           # ★セーブを読み直した
    vm.note_chests(5, 45)
    bits["now"] = _bits(16, 17, 18)
    vm.note_chests(5, 45)
    assert vm.note_chest_memos() == [], "⚠⚠ セーブを読み直したら同じ宝箱をまた書いた"
    # ★再起動（★記録は OPENED のまま）→ ⚠ 過去に開けた分を流し込まない
    again = make_vm()
    again._chests = CB.ChestBook.load(vm.chests_path, spots=spots)
    again.explored.mark_cells("L45", cells)
    again._raw = lambda: {"chest_bits": _bits(16, 17, 18)}
    again.note_chests(5, 45)
    assert again.note_chest_memos() == [], "⚠⚠ 再起動したら過去に開けた宝箱を流し込んだ"
    assert sum(1 for m in again._store if m.source == "chest") == 3


# ----------------------------------------------------------------------
# ★★ 座標の分からない宝箱（RX3-0283 / 2026-09-18）
#
#   ⚠⚠ 依頼者「ジパング宝箱でパープルオーブを手に入れたが、勇者メモにでない」。
#     ★193 個のうち 5 個は ROM から升が決まらず、**丸ごと捨てて**いた（→ 記録にもメモにも出ない）。
#   → ★升が無くても「印が立った瞬間」だけ拾う。⚠ 地図の印・「見つけた数」には出さない。
# ----------------------------------------------------------------------
def _nocoord_spot():
    from dq3.knowledge.chest_book import Spot

    return [Spot("chest_0023_000", 23, 23, None, None, "item", 122, None)]


def test_升の分からない宝箱も開けたらメモへ流す(tmp_path):
    from dq3.knowledge.chest_book import OPENED, WATCHED, ChestBook

    book = ChestBook(tmp_path / "c.json", spots=_nocoord_spot())
    assert book.update(23, set(), _bits()) == 1                 # ★まだ開いていない → 見張るだけ
    assert book.records["chest_0023_000"]["state"] == WATCHED
    assert book.take_opened() == [], "⚠ 開けていないのに流した"
    assert book.marks(23) == [] and book.rows(23) == [], "⚠⚠ 升が無いのに地図・一覧へ出した"
    assert book.update(23, set(), _bits(23)) == 1               # ★開けた
    got = book.take_opened()
    assert [r["object_id"] for r in got] == ["chest_0023_000"], got
    assert got[0]["state"] == OPENED and got[0]["item_id"] == 122
    assert book.rows(23) and book.marks(23) == [], "★一覧には出る / ⚠ 地図の印には出さない"


def test_見はじめに開いていた升の無い宝箱は流さない(tmp_path):
    from dq3.knowledge.chest_book import OPENED, ChestBook

    book = ChestBook(tmp_path / "c.json", spots=_nocoord_spot())
    book.update(23, set(), _bits(23))                            # ⚠ 最初からもう開いている
    assert book.records["chest_0023_000"]["state"] == OPENED
    assert book.records["chest_0023_000"].get("opened_before_seen") is True
    assert book.take_opened() == [], "⚠⚠ 前に開けた宝箱をメモへ流した"


def test_ROMの宝箱を1つも捨てていない():
    from dq3.knowledge import chest_book as CB

    spots = CB.rom_spots()
    if not spots:
        pytest.skip("★ROM がありません")
    assert len(spots) == 193, "⚠ 193 個そろっていない（★座標の無い 5 個を捨てていないか）"
    nocoord = [s for s in spots if s.x is None or s.y is None]
    assert len(nocoord) == 5 and 122 in [s.item_id for s in nocoord], nocoord

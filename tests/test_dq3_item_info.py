"""アイテムの性能を製品から引く / 装備比較 / 店（RX3-0083・0084・0085）。

```text
7A  分類・攻守・装備可否・値段・印を製品から引ける
7B  性別制限 3 件 / 装備の特殊効果 5 件 / 使用可能マスク
8-1 いま装備しているものとの差（＋X / −X / 装備できない）
8-2 店の品揃え（★同じ並びを複数の店が使う）
8-3 使い道の系統（⚠ 分かるものだけ。★推測しない）
```
"""
from __future__ import annotations

import os
import pathlib

import pytest

from dq3.knowledge import item_info as II
from dq3rom import item_meta as IM

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"


def _ready() -> bool:
    II.reset()
    return II.available()


needs_rom = pytest.mark.skipif(not _ready(), reason="DQ3 の ROM が読めない")


#: ★実データのパーティは名前つきの固定入力から読む（RX3-0179）
#:   ⚠⚠ 以前は `DQ3_J.fc0` を番号で読んでいた → 依頼者がロマリアで撮り直したら、
#:   全員がどうのつるぎ以上の武器を持っていて「誰も得をしない」で赤くなった（2026-09-12）。
MEMBERS_FIXTURE = "battle_ai_easy_battle"


@pytest.fixture(scope="module")
def members():
    """★実データのパーティ（⚠ 職業・性別・袋）。★fixture なので、遊んでも変わらない。"""
    from dq3.testing import fixtures as FX
    from retroux.tools.ram import read_savestate

    try:
        fx = FX.get(MEMBERS_FIXTURE)
    except FX.FixtureChanged:
        raise                                            # ⚠⚠ 中身が変わった fixture は skip にしない（★赤くする）
    except FX.FixtureError as err:
        pytest.skip("⚠ fixture が使えない: %s" % err)
    ram = read_savestate(fx.path)
    out = []
    for m in range(4):
        if (ram[0x0724 + 2 * m] | (ram[0x0725 + 2 * m] << 8)) == 0:
            continue
        cg = ram[IM.CLASS_GENDER_ADDR + m]
        out.append({"name": "人%d" % m, "class_id": cg & IM.CLASS_MASK,
                    "female": bool(cg & IM.GENDER_BIT),
                    "inventory": list(ram[IM.INVENTORY_ADDR + 8 * m:IM.INVENTORY_ADDR + 8 * (m + 1)])})
    return out


# --- ★7A: 製品から引ける -----------------------------------------------------------

@needs_rom
def test_品の性能を製品から引ける():
    got = II.info(0x02)                                # ★武器
    assert got is not None and got.category == "weapon"
    assert got.pri_stat == 12 and got.buy_price == 100 and got.sell_price == 75
    assert got.stat_label == "攻撃 12" and got.is_gear
    assert "hero" in got.equip_classes and "wizard" not in got.equip_classes


@needs_rom
def test_防具は守備と出る():
    got = II.info(0x38)
    assert got.category == "shield" and got.stat_label.startswith("守備")


@needs_rom
def test_道具は攻守が無い():
    got = II.info(0x65)
    assert got.pri_stat is None and got.stat_label == "" and not got.is_gear


def test_ROMが無くても落ちない(tmp_path):
    II.reset()
    assert not II.available(tmp_path / "none.nes")
    assert II.info(1, tmp_path / "none.nes") is None
    assert II.shop_lists(tmp_path / "none.nes") == []
    assert II.last_error and "ROM" in II.last_error
    II.reset()


@needs_rom
def test_装備中のbit7を落として引ける():
    assert II.meta(0x80 | 0x02).item_id == 0x02


# --- ★7B: 追加調査ぶん -------------------------------------------------------------

@needs_rom
def test_女性しか装備できないものが3件():
    got = [r for r in IM.build_from_rom() if r.female_only] if hasattr(IM, "build_from_rom") else None
    rows = [II.meta(i) for i in IM.MALE_BLOCKED]
    assert all(r is not None and r.female_only for r in rows)
    assert len(IM.MALE_BLOCKED) == 3
    # ⚠ 男は装備できない / ★女なら職業さえ合えば装備できる
    for r in rows:
        cls = next(i for i in range(8) if r.equip_mask & (1 << i))
        assert r.equippable_by(cls, female=True)
        assert not r.equippable_by(cls, female=False)


@needs_rom
def test_装備の特殊効果は5件だけ():
    rows = [II.meta(i) for i in IM.EQUIP_BUFFS]
    assert len(rows) == 5 and all(r.equip_buff is not None for r in rows)
    # ⚠ それ以外は None（★勝手に付けない）
    assert II.meta(0x00).equip_buff is None


@needs_rom
def test_使えるマスクは表に載る範囲だけ():
    assert II.meta(0x00).use_mask is not None          # ★武器
    assert II.meta(0x47).use_mask is not None          # ★装飾品（$27 引いて後ろへ）
    assert II.meta(0x20).use_mask is None              # ⚠ 防具は誰でも使える
    assert II.meta(0x4F).use_mask is None              # ⚠ $4F 以上は誰でも


# --- ★8-1: 装備の比較 --------------------------------------------------------------

def test_比較の差の見せ方():
    c = II.Compare("weapon", "ぶき", 1, "こんぼう", 7, 2, "どうのつるぎ", 12, True)
    assert c.delta == 5 and c.delta_label == "+5"
    down = II.Compare("weapon", "ぶき", 2, "どうのつるぎ", 12, 1, "こんぼう", 7, True)
    assert down.delta_label == "−5"
    same = II.Compare("weapon", "ぶき", 2, "x", 12, 2, "x", 12, True)
    assert same.delta_label == "±0"
    no = II.Compare("weapon", "ぶき", None, None, 0, 3, "y", 20, False, "その人は装備できない")
    assert no.delta_label == "その人は装備できない"


def test_装備している枠だけ拾う():
    """⚠⚠ 「持っているだけ」を装備扱いにしない。

    ★`0x01`（こんぼう / 装備していない武器）を入れておき、⚠ それが拾われたら赤くする。
      （2026-09-06: bit7 の判定を外しても鳴らなかったので、この 1 件を足した）
    """
    inv = [0x80 | 0x02, 0x80 | 0x30, 0x01, 0xFF, 0x80 | 0x65]
    got = II.equipped_ids(inv)
    assert got == {"weapon": 0x02, "armor": 0x30}       # ⚠ 装備していない / 道具は入らない
    # ⚠ 装備していないものを先に置いても、拾うのは装備しているほう
    assert II.equipped_ids([0x01, 0x80 | 0x02]) == {"weapon": 0x02}
    # ⚠ 何も装備していなければ空
    assert II.equipped_ids([0x01, 0x30, 0xFF]) == {}


@needs_rom
def test_実データで比較できる(members):
    got = II.compare_party(0x02, members)               # ★どうのつるぎ
    assert len(got) == len(members)
    assert any(c.equippable and c.delta > 0 for c in got), "⚠ 誰も得をしない"
    assert any(not c.equippable for c in got), "⚠ 装備できない人が居るはず（★魔法使い）"
    best = II.best_for(0x02, members)
    assert best is not None and best.delta > 0
    # ⚠ 装備品でないものは比べない
    assert II.compare(0x65, members[0]["inventory"], 0) is None


@needs_rom
def test_装備できない人には理由を出す(members):
    wizard = next((m for m in members if m["class_id"] == 1), None)
    if wizard is None:
        pytest.skip("⚠ 魔法使いが居ない")
    got = II.compare(0x02, wizard["inventory"], wizard["class_id"], wizard["female"])
    assert not got.equippable and got.reason


# --- ★8-2: 店 ---------------------------------------------------------------------

@needs_rom
def test_店の品揃えが読める():
    lists = II.shop_lists()
    assert len(lists) >= 30
    assert all(2 <= len(x) <= 8 for x in lists), "⚠ 品数がおかしい"
    # ★どの品も性能の表に載っている
    for row in lists:
        for item_id in row:
            assert II.meta(item_id) is not None, hex(item_id)


@needs_rom
def test_最初の品揃えはアリアハンの武器屋():
    """★ID だけで確かめる（⚠ 名前は書かない）。"""
    assert II.shop_lists()[0] == [0x00, 0x01, 0x02, 0x20, 0x30, 0x22, 0x38]
    rows = II.shop_for(II.shop_lists()[0])
    assert [r.buy_price for r in rows] == [5, 30, 100, 10, 70, 150, 90]


@needs_rom
def test_品揃えを探せる():
    assert II.find_shop([0x00, 0x01, 0x02, 0x20, 0x30, 0x22, 0x38]) == 0
    assert II.find_shop([0xEE]) is None


@needs_rom
def test_夜にしか居ない店も拾う():
    """⚠⚠ RX3-0087: `shops_by_map` が昼（`master_for(map_id, 0)`）しか見ていなかった。

    ★NPC 表は昼夜で別々に展開されます（`npc_rom.expand(recs, night)`）。
    ⚠ 片方だけ見ると、もう片方の店員は**エラーも出さずに消えます**。
    """
    got = II.shops_by_map()
    found = {s.shop_index: map_id for map_id, rows in got.items() for s in rows}
    # ★夜にしか居ない武器屋（⚠ 昼の台帳には talk_id ごと無い）
    assert found.get(0) == 12, "⚠ 店 0（map 12 の夜）が出ていない"
    assert found.get(1) == 21, "⚠ 店 1（map 21 の夜）が出ていない"
    assert got[12][0].role == "weapon_armor_shop"


@needs_rom
def test_同じ店を昼夜で2回入れない():
    """⚠ 昼夜の両方を見ると、同じ店員を 2 回数えます。"""
    for map_id, rows in II.shops_by_map().items():
        idx = [s.shop_index for s in rows]
        assert len(idx) == len(set(idx)), "⚠ map %d で店番号が重複: %s" % (map_id, idx)


@needs_rom
def test_差し替えのあるmapの店も出す():
    """⚠⚠ RX3-0090: `master_for` が `status=UNKNOWN` の map の `npcs` を空にしていた。

    ★「差し替えがある」ことと「既定の表が読めない」ことは**別**です。
    ⚠ 既定の表はそのまま読めているのに、店を 4 軒落としていました。
    """
    found = {s.shop_index: (map_id, s) for map_id, rows in II.shops_by_map().items() for s in rows}
    assert found[19][0] == 1 and found[44][0] == 1, "⚠ map 1 の店が出ていない"
    assert found[5][0] == 117 and found[28][0] == 117, "⚠ map 117 の店が出ていない"


@needs_rom
def test_条件つきの店は確かな店と混ぜない():
    """⚠⚠ 差し替えの条件は HYPOTHESIS。★「確かな店」と同じ顔で出さない。"""
    found = {s.shop_index: s for rows in II.shops_by_map().values() for s in rows}
    assert found[19].conditional and found[5].conditional, "⚠ 条件つきの印が無い"
    assert not found[2].conditional and not found[23].conditional, "⚠ 確かな店に印が付いている"
    # ★名前を見ただけで分かる
    assert "⚠" in found[19].label and "⚠" not in found[2].label


@needs_rom
def test_店の画面に出す行と詳細(members):
    from dq3.ui import shop_window as SW

    info = II.info(0x02)
    # ★★ 列で持つ（⚠ 空白で詰めない = 日本語でガタガタにならない）
    cells = SW.row_cells(info, gold=500)
    assert len(cells) == len(SW.COLUMNS) == 3
    assert cells[0] == info.label and cells[1] == "攻撃 12" and cells[2] == "100 G"
    assert "⚠" in SW.row_cells(info, gold=50)[2], "⚠ 買えないのに印が無い"
    assert "⚠" not in SW.row_cells(info, gold=500)[2]
    rows = dict(SW.detail_lines(info, members, 500))
    assert "買える" in rows["値段"] and rows["売ると"] == "75 G"
    assert "いま装備しているものとの差" in rows


def test_列を空白で詰めていない():
    """⚠⚠ 依頼者 2026-09-06「アイテム表示がガタガタ」。

    ★等幅フォント ＋ `%-14s` では**揃いません**（日本語は全角 / Consolas に字が無い）。
    → ★列（`QTreeWidget`）で揃えます。⚠ ここを空白詰めへ戻すと、また崩れます。
    """
    from dq3.ui import shop_window as SW

    # ★列で持っている（⚠ 1 本の文字列に詰めていない）
    assert len(SW.COLUMNS) == 3
    got = SW.row_cells(_FakeInfo(), gold=None)
    assert isinstance(got, tuple) and len(got) == 3
    assert all(" " * 3 not in cell for cell in got), "⚠⚠ 空白で桁を合わせている: %s" % (got,)
    src = (ROOT / "dq3" / "ui" / "shop_window.py").read_text(encoding="utf-8")
    assert "QTreeWidget" in src and "QListWidget" not in src, "⚠ 列で揃えていない"


class _FakeInfo:
    """★`row_cells` だけを見るための最小の品（⚠ ROM を要らなくする）。"""

    label = "ながいなまえのぶき"
    stat_label = "攻撃 12"
    buy_price = 100


# --- ★8-3: 使い道の系統 ------------------------------------------------------------

@needs_rom
def test_使い道の系統は分かるものだけ():
    assert II.meta(0x65).use_kind == "heal"             # ★やくそう
    assert II.meta(0x68).use_kind == "travel"
    assert II.meta(0x58).use_kind == "key"
    assert II.meta(0x5F).use_kind == "boost"
    # ⚠ 分からないものは other のまま（★推測で埋めない）
    assert II.meta(0x00).use_kind == "other"
    kinds = {r.use_kind for r in [II.meta(i) for i in range(125)]}
    assert "other" in kinds and len(kinds) >= 5


@needs_rom
def test_系統を付けたものは全部使用ハンドラを持つ():
    """⚠⚠ `_items_use_lib` に載っていない品へ系統を付けない。

    ⚠ ハンドラを選ぶのは **`d44`（`effect_arg`）の bit7** です。
      ★`d42` の bit7（`battle_use`）とは**別のビット**でした
      （2026-09-06: 検査が私の思い違いを捕まえた。★$76 は d44 だけ立っている）。
    """
    handlers = [i for i in range(125) if II.meta(i).effect_arg & 0x80]
    assert len(handlers) == 42, "⚠ ハンドラの数が 42 でない: %d" % len(handlers)
    for item_id in IM.USE_KINDS:
        assert item_id in handlers, "⚠ $%02X は使用ハンドラを持たない" % item_id


@needs_rom
def test_見出しが全部ある():
    for kind in set(IM.USE_KINDS.values()) | {"other"}:
        assert kind in IM.USE_KIND_LABEL
    assert II.CATEGORY_LABEL["weapon"] and II.FLAG_LABEL["cursed"]
    assert II.class_labels(["hero", "wizard"]) == ["勇", "魔"]


# --- ★製品への配線 ----------------------------------------------------------------

def test_職業と性別が設定から流れてくる():
    """★`profile` → `generate_lua` → `dev.lua` の道が繋がっている。"""
    import json

    from dq3.phase0 import generate_lua as G

    prof = json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                      .read_text(encoding="utf-8"))
    party = G._party(prof)
    assert party["class_gender"] == IM.CLASS_GENDER_ADDR
    assert party["items"] == IM.INVENTORY_ADDR
    lua = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "PARTY.class_gender" in lua and "m.class_gender" in lua


def test_右パネルから店を開ける():
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert '("shop", "店", "お店の品揃えを見る"' in src and "def open_shop" in src


def test_ボタンが右パネルからはみ出さない(app):
    """⚠⚠ 1 文字ボタンは 10 個で 376px になり、★右パネル 360 に入らない（実測）。

    ⚠⚠ 2026-09-20（RX3-0325）訂正: ★以前はここで**偽のボタンを 9 個作って**測っていました。
      ⚠ 本物の窓を見ていないので、★本物のボタンが太っても鳴りません
        （アイコン＋字にした今、`setFixedWidth(34)` の偽物は実態と無関係です）。
      → ★**本物の窓のボタンの箱**を測ります。
    """
    from dq3.ui import layout as layout_mod
    from dq3.ui import main_window as MW
    from dq3.ui.view_model import Dq3ViewModel

    panel_w = layout_mod.default_sizes(layout_mod.qt_area()).panel.w
    win = MW.Dq3MainWindow(Dq3ViewModel(), show_map=False)
    app.processEvents()
    try:
        box = win._buttons["align"].parent()
        need = box.sizeHint().width()
        assert need <= panel_w, (
            "⚠⚠ ボタンの箱が %dpx で、右パネル %dpx に入らない（★%d 個）"
            % (need, panel_w, len(win._buttons)))
    finally:
        win.close()


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                # pragma: no cover
        pytest.skip("Qt が無い環境")
    got = QApplication.instance()
    yield got if got is not None else QApplication([])


@pytest.fixture(scope="module")
def visited_book(tmp_path_factory):
    """★店のある街を「行った」にした場所の記録。

    ⚠⚠ 2026-09-18（RX-0141）まで、店の窓の検査は**依頼者の遊んだ記録**（`work/dq3-knowledge/location-book.json`）を読んでいました。
    ★行った街が少ないと 0 件になり、⚠ まっさらな環境では必ず赤くなります（★検査が自分で用意する形に直した）。
    """
    from dq3.knowledge import item_info as II
    from dq3.knowledge.location_book import LocationBook

    book = LocationBook(path=tmp_path_factory.mktemp("shops") / "location-book.json")
    for map_id in II.shops_by_map():
        book.enter(map_id)
    return book


@needs_rom
def test_所持金はメソッドでも数でも読める(app, members):
    """⚠⚠ 製品の `vm.gold` は **メソッド**（★2026-09-06 に実機で踏んだ）。"""
    from dq3.ui.shop_window import Dq3ShopWindow

    class _Method:
        def gold(self):
            return 383

        def equip_members(self):
            return members

    class _Value:
        gold = 383

        def equip_members(self):
            return members

    for vm in (_Method(), _Value()):
        w = Dq3ShopWindow(vm)
        assert w.gold() == 383
        assert "383" in w.gold_label.text()
        w.close()
    assert Dq3ShopWindow(None).gold() is None


@needs_rom
def test_店の窓が開く(app, members, visited_book):
    from dq3.ui.shop_window import Dq3ShopWindow

    class _VM:
        gold = 383
        location_book = visited_book        # ★行った街は検査が用意する（RX-0141）

        def equip_members(self):
            return members

    w = Dq3ShopWindow(_VM())
    assert w.shop_select.count() >= 1
    assert w.list.topLevelItemCount() >= 2
    w.list.setCurrentItem(w.list.topLevelItem(0))
    assert w.current() is not None
    # ★右側に中身が描かれている（⚠ 空のまま出さない）
    from PySide6.QtWidgets import QLabel

    texts = [w._body_box.itemAt(i).widget().text()
             for i in range(w._body_box.count())
             if isinstance(w._body_box.itemAt(i).widget(), QLabel)]
    assert any("値段" == t for t in texts), texts
    assert any(" G" in t for t in texts), texts
    from dq3.ui.shop_window import WINDOW_H, WINDOW_W

    w.show()
    app.processEvents()
    assert (w.width(), w.height()) == (WINDOW_W, WINDOW_H), "⚠ 中身で窓の大きさが変わった"
    w.close()


@needs_rom
def test_店はROMが無くても開く(app, tmp_path, monkeypatch):
    """⚠ ROM が無い人の画面で落ちない。"""
    from dq3.ui.shop_window import Dq3ShopWindow

    II.reset()
    monkeypatch.setattr(II, "DEFAULT_ROM", tmp_path / "none.nes")
    w = Dq3ShopWindow(None)
    assert w.shop_select.count() >= 1 and "読めません" in w.shop_select.itemText(0)
    w.close()
    II.reset()


# --- ★お店画面の商品検索（RX3-0254 / 依頼者の小WI / 正本 docs/requests/260913_dq3-shop-search.md）---------------

def _info(item_id, name, category):
    return II.ItemInfo(item_id=item_id, name=name, category=category,
                       category_label=II.CATEGORY_LABEL.get(category, category), pri_stat=None, equip_classes=(),
                       female_only=False, buy_price=10, sell_price=5, flags=(), equip_buff=None)


def test_商品名の部分一致と種別はANDで絞り_元の並びは変えない():
    """★指示書 §1〜§4・§9 の 1〜4（⚠ 名前は作り物 / ROM は要らない）。"""
    from dq3.ui import shop_window as SW

    infos = [_info(1, "はがねのつるぎ", "weapon"), _info(2, "はがねのよろい", "armor"),
             _info(101, "やくそう", "item"), _info(3, "どうのつるぎ", "weapon")]
    before = list(infos)
    kind = dict(SW.kinds())
    assert [i.label for i in SW.filter_infos(infos, "やく", None)] == ["やくそう"], "★前方一致に限らない部分一致"
    assert [i.label for i in SW.filter_infos(infos, "はがね", None)] == ["はがねのつるぎ", "はがねのよろい"]
    assert [i.label for i in SW.filter_infos(infos, "つるぎ", None)] == ["はがねのつるぎ", "どうのつるぎ"]
    assert [i.label for i in SW.filter_infos(infos, "", kind["武器"])] == ["はがねのつるぎ", "どうのつるぎ"]
    assert [i.label for i in SW.filter_infos(infos, "", kind["どうぐ"])] == ["やくそう"]
    assert [i.label for i in SW.filter_infos(infos, "はがね", kind["武器"])] == ["はがねのつるぎ"], "⚠ AND になっていない"
    assert SW.filter_infos(infos, "ぬの", kind["武器"]) == []
    assert SW.filter_infos(infos, "", kind[SW.ALL_KINDS]) == infos, "★条件なしなら全部"
    assert infos == before, "⚠⚠ 検索で元の並びを変えた"


def test_種別は既存の分類の見出しで_名前から推測しない():
    """★指示書 §1「種別名称は、既存のDQ3 Item分類に合わせる」/ §5「種別は商品名から推測しない」。"""
    from dq3.ui import shop_window as SW

    assert [k for k, _c in SW.kinds()] == ["すべて", "武器", "よろい", "たて", "かぶと", "そうしょくひん", "どうぐ"]
    fake = _info(9, "つるぎの かたちの どうぐ", "item")
    assert SW.filter_infos([fake], "", dict(SW.kinds())["武器"]) == [], "⚠⚠ 名前の「つるぎ」で武器にした"
    assert SW.filter_infos([fake], "", dict(SW.kinds())["どうぐ"]) == [fake]


@needs_rom
def test_店の窓で検索すると一覧だけが絞られ_条件を外すと戻る(app, members, visited_book):
    """★指示書 §6〜§9: 0 件の表示 / 条件はそのまま / 解除で戻る / 選んだ品が正しい / 店を替えても品揃えは変わらない。"""
    from dq3.ui.shop_window import NO_MATCH, Dq3ShopWindow

    class _VM:
        gold = 383
        location_book = visited_book        # ★行った街は検査が用意する（RX-0141）

        def equip_members(self):
            return members

    w = Dq3ShopWindow(_VM())
    full = [i.label for i in w._infos]
    n = w.list.topLevelItemCount()
    assert n >= 2 and len(full) == n
    word = full[-1][:2]
    w.search_edit.setText(word)
    shown = [w.list.topLevelItem(i).text(0) for i in range(w.list.topLevelItemCount())]
    assert shown and all(word in s for s in shown), shown
    w.list.setCurrentItem(w.list.topLevelItem(0))
    assert w.current().label == shown[0], "⚠⚠ 絞った一覧で選んだ品と、中身に出す品が違う"
    w.search_edit.setText("ぬぬぬぬぬ")
    assert w.list.topLevelItemCount() == 0 and w.no_match.isVisibleTo(w) and w.no_match.text() == NO_MATCH
    assert w.search_edit.text() == "ぬぬぬぬぬ", "★条件はそのまま残す"
    w.search_edit.setText("")
    w.kind_select.setCurrentIndex(0)
    assert w.list.topLevelItemCount() == n and not w.no_match.isVisibleTo(w), "⚠ 条件を外しても元に戻らない"
    assert [i.label for i in w._infos] == full, "⚠⚠ 検索で品揃えを変えた"
    if w.shop_select.count() >= 2:
        # ★先頭は「お店すべて」（RX3-0274）→ そちらへ替えて、元の店へ戻す
        start = w.shop_select.currentIndex()
        w.search_edit.setText(word)
        w.shop_select.setCurrentIndex(0 if start != 0 else 1)
        w.shop_select.setCurrentIndex(start)
        w.search_edit.setText("")
        assert [i.label for i in w._infos] == full, "⚠⚠ 店を替えたら品揃えが変わった"
    w.close()


# --- ★お店を横断して探す（RX3-0274 / 依頼者 2026-09-14「お店全て、条件一致に街も追加」）-----------------------

class _Shop:
    def __init__(self, label, items):
        self.label, self.items = label, tuple(items)


def test_お店すべては店の順に並べ_同じ品も店ごとに1行():
    """★ROM は要らない（⚠ 名前は作り物）。"""
    from dq3.ui import shop_window as SW

    table = {1: _info(1, "はがねのつるぎ", "weapon"), 2: _info(2, "はがねのよろい", "armor"),
             101: _info(101, "やくそう", "item")}
    shops = [_Shop("まちA の ぶきや・ぼうぐや", [1, 2]), _Shop("まちB の どうぐや", [101]),
             _Shop("まちC の ぶきや・ぼうぐや", [2])]
    rows = SW.all_shop_rows(shops, lambda items: [table[i] for i in items])
    assert [(i.label, w) for i, w in rows] == [
        ("はがねのつるぎ", "まちA の ぶきや・ぼうぐや"), ("はがねのよろい", "まちA の ぶきや・ぼうぐや"),
        ("やくそう", "まちB の どうぐや"), ("はがねのよろい", "まちC の ぶきや・ぼうぐや")], \
        "⚠ 同じ品を売る 2 軒が 1 行にまとまった / 店の順が崩れた"
    armor = dict(SW.kinds())["よろい"]
    assert [w for i, w in rows if SW.matches(i, "", armor)] == ["まちA の ぶきや・ぼうぐや", "まちC の ぶきや・ぼうぐや"]
    assert SW.all_shop_rows([], lambda items: []) == []
    lines = dict(SW.detail_lines(table[2], [], None, where="まちC の ぶきや・ぼうぐや"))
    assert lines["売っている店"] == "まちC の ぶきや・ぼうぐや"
    assert "売っている店" not in dict(SW.detail_lines(table[2], [], None)), "⚠ 1 軒ずつのときに店を重ねて出した"


@needs_rom
def test_店の窓でお店すべてを選ぶと全部の店の品が街つきで絞れる(app, members, visited_book):
    from dq3.ui.shop_window import ALL_SHOPS, Dq3ShopWindow

    class _VM:
        gold = 383
        location_book = visited_book        # ★行った街は検査が用意する（RX-0141）

        def equip_members(self):
            return members

    w = Dq3ShopWindow(_VM())
    if len(w._shops) < 2:
        w.close()
        pytest.skip("⚠ 行った街の店が 1 軒以下（★横断を試せない）")
    assert w.shop_select.itemText(0) == ALL_SHOPS
    assert w.shop_select.currentIndex() == 1 and not w.all_shops_selected(), "★開いたときは今までどおり最初の店"
    assert w.list.isColumnHidden(3), "⚠ 1 軒ずつのときに「街・店」の列が出ている"
    one = [i.label for i in w._infos]
    w.shop_select.setCurrentIndex(0)
    assert w.all_shops_selected() and not w.list.isColumnHidden(3)
    from dq3.knowledge import item_info as II

    want = sum(len(II.shop_for(list(s.items))) for s in w._shops)
    assert w.list.topLevelItemCount() == want, "⚠ 全部の店の品が並んでいない"
    labels = {s.label for s in w._shops}
    w.kind_select.setCurrentIndex(w.kind_select.findText("よろい"))
    n = w.list.topLevelItemCount()
    assert n >= 1
    for r in range(n):
        row = w.list.topLevelItem(r)
        assert row.text(3) in labels, "⚠⚠ 一致した品に街・店が出ていない: %r" % row.text(3)
    assert all(i.category == "armor" for i in w._shown)
    w.list.setCurrentItem(w.list.topLevelItem(n - 1))
    assert w.current_where() == w.list.topLevelItem(n - 1).text(3), "⚠ 選んだ行と中身の店が違う"
    w.kind_select.setCurrentIndex(0)
    w.shop_select.setCurrentIndex(1)
    assert w.list.isColumnHidden(3) and [i.label for i in w._infos] == one, "⚠⚠ 1 軒に戻したら品揃えが変わった"
    w.close()

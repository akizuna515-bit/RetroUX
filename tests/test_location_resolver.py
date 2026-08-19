"""ロケーション辞書と現在地の名前（マッパー仕様 4章 / 25章）。

★★ **確かめたいことの中心** ★★

  1. `map_id` から**ロケーション名 + 階層**が出る
  2. 表に無い `map_id` は「未登録」と出る（**近い名前に丸めない**）
  3. 名前の出どころ（ROM / 人の知識）が分かる
  4. ワールドマップは座標から地域名が出る。**地域が空なら地域名を付けない**
  5. 辞書が壊れていても**落ちない**（地名が出ないだけ）

⚠ 実際に同梱している YAML も読む（生成物が壊れていたら気づけるように）。
"""

from __future__ import annotations

import pathlib

import pytest

from retroux.core.navigation.location_resolver import (
    Confidence, LocationDictionary, LocationResolver,
)
from retroux.core.navigation.models import Place

DATA = pathlib.Path(__file__).resolve().parents[1] / "retroux" / "plugins" / "dq2" / "data"


def write(tmp_path: pathlib.Path, **files: str) -> pathlib.Path:
    for name, text in files.items():
        (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def at(map_id: int, x: int = 0, y: int = 0, ptr: int = 0x8000) -> Place:
    return Place(map_id, ptr, x, y)


# --- 同梱の YAML そのもの ---------------------------------------------

def test_shipped_dictionary_loads_without_problems():
    """★同梱の生成物が壊れていないこと。"""
    dictionary = LocationDictionary.load(DATA)
    assert dictionary.problems == []
    assert not dictionary.is_empty


def test_shipped_dictionary_has_every_map_pointing_at_a_real_location():
    dictionary = LocationDictionary.load(DATA)
    missing = [f"${m:02X}" for m, b in dictionary.bindings.items()
               if b.location_id not in dictionary.locations]
    assert missing == []


@pytest.mark.parametrize(("map_id", "expected"), [
    (0x03, "ローレシア 1F"),
    (0x04, "ローレシア B1"),
    (0x2D, "湖の洞窟 B2"),
    (0x37, "ロンダルキアへの洞窟 B1"),
    (0x39, "ロンダルキアへの洞窟 2F（その1）"),   # ★枝番が出る
])
def test_shipped_dictionary_names_known_maps(map_id, expected):
    resolver = LocationResolver.load(DATA)
    assert resolver.resolve(at(map_id)).display == expected


def test_floor_labels_come_from_the_rom_so_they_are_present():
    """★階層は自動移動が使う情報。**ROM 由来なので落ちていないこと**。"""
    dictionary = LocationDictionary.load(DATA)
    with_floor = [b for b in dictionary.bindings.values() if b.floor_label]
    assert len(with_floor) >= 70
    for binding in with_floor:
        assert binding.floor_index is not None


def test_the_world_map_has_no_region_name_until_regions_are_filled_in():
    """⚠ `world_regions.yaml` は空で同梱している。**勝手に地域名を出さない**。"""
    resolver = LocationResolver.load(DATA)
    resolved = resolver.resolve(at(0x01, x=50, y=80))
    assert resolved.region is None
    assert resolved.display == "世界地図"


# --- 未登録 -----------------------------------------------------------

def test_an_unbound_map_is_reported_as_unregistered():
    """★**近い名前に丸めない。**間違った名前は判断材料を壊す。"""
    resolver = LocationResolver.load(DATA)
    resolved = resolver.resolve(at(0x7F))
    assert not resolved.registered
    assert resolved.location is None
    assert "未登録" in resolved.display
    assert "$7F" in resolved.display
    assert resolved.confidence is Confidence.PROVISIONAL
    assert resolved.needs_check


def test_no_place_gives_none_not_an_unknown_location():
    """⚠「まだ読めていない」と「未登録のマップ」は別。"""
    resolver = LocationResolver.load(DATA)
    assert resolver.resolve(None) is None
    assert resolver.resolve(Place(None, 0x8000, 0, 0)) is None


# --- 名前の出どころ ---------------------------------------------------

def test_rom_derived_names_are_marked_and_do_not_need_checking():
    resolver = LocationResolver.load(DATA)
    resolved = resolver.resolve(at(0x03))          # ローレシア = ROM の辞書由来
    assert resolved.source == "rom"
    assert resolved.location.name_is_from_rom
    assert not resolved.needs_check


def test_hand_entered_names_are_marked_as_needing_a_check():
    resolver = LocationResolver.load(DATA)
    resolved = resolver.resolve(at(0x0B))          # ルプガナ = ROM に無い
    assert resolved.source == "knowledge"
    assert not resolved.location.name_is_from_rom
    assert resolved.needs_check


# --- 地域（人が埋めたあと）-------------------------------------------

REGIONS = """
regions:
  - region_id: midenhall_area
    location_id: midenhall
    name: ローレシア周辺
    bounds: { x_min: 40, x_max: 60, y_min: 70, y_max: 92 }
    confidence: provisional
  - region_id: midenhall_gate
    location_id: midenhall
    name: ローレシア城前
    bounds: { x_min: 49, x_max: 51, y_min: 79, y_max: 81 }
    confidence: provisional
  # ★★ **(0,0) を含む地域をわざと入れておく。** ★★
  #   座標が読めていないときに 0 で埋めると、ここに引っかかる。
  #   そういう間違いをテストが捕まえられるようにするための罠。
  - region_id: origin_trap
    location_id: midenhall
    name: 罠（原点）
    bounds: { x_min: 0, x_max: 2, y_min: 0, y_max: 2 }
    confidence: provisional
"""


def dictionary_with_regions(tmp_path) -> LocationDictionary:
    for name in ("locations", "map_bindings"):
        (tmp_path / f"{name}.yaml").write_bytes(
            (DATA / f"{name}.yaml").read_bytes())
    (tmp_path / "world_regions.yaml").write_text(REGIONS, encoding="utf-8")
    return LocationDictionary.load(tmp_path)


def test_a_filled_in_region_is_shown_next_to_the_world_map(tmp_path):
    resolver = LocationResolver(dictionary_with_regions(tmp_path))
    resolved = resolver.resolve(at(0x01, x=45, y=75))
    assert resolved.region.region_id == "midenhall_area"
    assert resolved.display == "世界地図（ローレシア周辺）"


def test_overlapping_regions_pick_the_narrower_one(tmp_path):
    """★狭いほうが具体的。「城前」を「周辺」に負けさせない。"""
    resolver = LocationResolver(dictionary_with_regions(tmp_path))
    resolved = resolver.resolve(at(0x01, x=50, y=80))
    assert resolved.region.region_id == "midenhall_gate"


def test_a_coordinate_outside_every_region_gets_no_region(tmp_path):
    resolver = LocationResolver(dictionary_with_regions(tmp_path))
    assert resolver.resolve(at(0x01, x=200, y=200)).region is None


def test_region_bounds_are_inclusive_on_both_ends(tmp_path):
    dictionary = dictionary_with_regions(tmp_path)
    assert dictionary.region_at(40, 70) is not None
    assert dictionary.region_at(60, 92) is not None
    assert dictionary.region_at(39, 70) is None
    assert dictionary.region_at(60, 93) is None


def test_a_provisional_region_pulls_the_confidence_down(tmp_path):
    """★**一番弱いものに合わせる。**地域が provisional なら全体も provisional。"""
    resolver = LocationResolver(dictionary_with_regions(tmp_path))
    on_region = resolver.resolve(at(0x01, x=50, y=80))
    off_region = resolver.resolve(at(0x01, x=200, y=200))
    assert on_region.confidence is Confidence.PROVISIONAL
    assert off_region.confidence is Confidence.PROBABLE


# --- 壊れた辞書 -------------------------------------------------------

def test_a_missing_directory_gives_an_empty_dictionary_not_a_crash(tmp_path):
    """⚠ 地名が出ないだけで、ゲームと移動記録は動くこと。"""
    dictionary = LocationDictionary.load(tmp_path / "nope")
    assert dictionary.is_empty
    assert len(dictionary.problems) == 3          # 3ファイルぶん
    resolved = LocationResolver(dictionary).resolve(at(0x03))
    assert "未登録" in resolved.display


def test_broken_yaml_is_reported_and_does_not_raise(tmp_path):
    write(tmp_path, locations="locations: {: :", map_bindings="bindings: []",
          world_regions="regions: []")
    dictionary = LocationDictionary.load(tmp_path)
    assert any("読めない" in p for p in dictionary.problems)
    assert dictionary.is_empty


def test_a_binding_pointing_at_a_missing_location_is_dropped_and_reported(tmp_path):
    write(tmp_path,
          locations="locations:\n  midenhall:\n    name: ローレシア\n",
          map_bindings="bindings:\n"
                       "  - { map_id: 3, location_id: midenhall }\n"
                       "  - { map_id: 9, location_id: nowhere }\n",
          world_regions="regions: []")
    dictionary = LocationDictionary.load(tmp_path)
    assert set(dictionary.bindings) == {3}
    assert any("nowhere" in p for p in dictionary.problems)


def test_a_duplicate_map_id_keeps_the_first_and_reports_it(tmp_path):
    write(tmp_path,
          locations="locations:\n  a: { name: A }\n  b: { name: B }\n",
          map_bindings="bindings:\n"
                       "  - { map_id: 3, location_id: a }\n"
                       "  - { map_id: 3, location_id: b }\n",
          world_regions="regions: []")
    dictionary = LocationDictionary.load(tmp_path)
    assert dictionary.bindings[3].location_id == "a"
    assert any("2回" in p for p in dictionary.problems)


def test_a_region_with_missing_bounds_is_dropped_and_reported(tmp_path):
    write(tmp_path, locations="locations: {}", map_bindings="bindings: []",
          world_regions="regions:\n  - { region_id: x, name: X }\n")
    dictionary = LocationDictionary.load(tmp_path)
    assert dictionary.regions == []
    assert any("bounds" in p for p in dictionary.problems)


def test_reversed_region_bounds_are_dropped_not_silently_swapped(tmp_path):
    """⚠ 書いた人の意図が分からないので**黙って直さない**。"""
    write(tmp_path, locations="locations: {}", map_bindings="bindings: []",
          world_regions="regions:\n  - region_id: x\n    name: X\n"
                        "    bounds: { x_min: 60, x_max: 40, y_min: 1, y_max: 2 }\n")
    dictionary = LocationDictionary.load(tmp_path)
    assert dictionary.regions == []
    assert any("逆さ" in p for p in dictionary.problems)


def test_an_unreadable_confidence_falls_back_and_is_not_raised(tmp_path):
    """★読めない確度で**勝手に上げない**。"""
    write(tmp_path,
          locations="locations:\n  a: { name: A, name_source: rom }\n",
          map_bindings="bindings:\n"
                       "  - { map_id: 3, location_id: a, confidence: とても確か }\n",
          world_regions="regions: []")
    dictionary = LocationDictionary.load(tmp_path)
    assert dictionary.bindings[3].confidence is Confidence.PROBABLE


def test_a_location_without_a_japanese_name_shows_the_english_one(tmp_path):
    write(tmp_path,
          locations="locations:\n  q: { name_en: 'Mystery Place' }\n",
          map_bindings="bindings:\n  - { map_id: 3, location_id: q }\n",
          world_regions="regions: []")
    resolver = LocationResolver(LocationDictionary.load(tmp_path))
    resolved = resolver.resolve(at(3))
    assert resolved.display == "Mystery Place"
    assert resolved.source == "unknown"
    assert resolved.needs_check
    # ★名前が弱いので確度も下がる
    assert resolved.confidence is Confidence.PROVISIONAL


# --- 検索語 -----------------------------------------------------------

def test_search_terms_include_the_floor_first():
    resolver = LocationResolver.load(DATA)
    terms = resolver.search_terms(at(0x37))       # ロンダルキアへの洞窟 B1
    assert terms[0] == "ドラゴンクエストII ロンダルキアへの洞窟 B1 攻略"
    assert "ロンダルキアへの洞窟 地図" in terms
    assert any("Dragon Warrior II Cave to Rhone B1 map" == t for t in terms)


def test_search_terms_for_a_floorless_place_do_not_say_none():
    resolver = LocationResolver.load(DATA)
    terms = resolver.search_terms(at(0x0B))       # ルプガナ（階層なし）
    assert terms
    assert all("None" not in t for t in terms)


def test_search_terms_have_no_duplicates():
    resolver = LocationResolver.load(DATA)
    for map_id in (0x01, 0x03, 0x0B, 0x37):
        terms = resolver.search_terms(at(map_id))
        assert len(terms) == len(set(terms))


def test_duplicate_terms_are_dropped_but_the_order_is_kept():
    """★重複を消すときに**順番を崩さない**（前のほうが当たりやすい語）。

    ⚠ いまの語の組み合わせでは重複が起きないので、`search_terms` 越しでは
      この処理が効いているか確かめられない。だから直接試す。
    """
    from retroux.core.navigation.location_resolver import unique_terms

    assert unique_terms(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
    assert unique_terms([]) == []


def test_an_unregistered_map_has_no_search_terms():
    """★名前が分からないのに検索語を作らない（間違った語で調べてしまう）。"""
    resolver = LocationResolver.load(DATA)
    assert resolver.search_terms(at(0x7F)) == []


# --- 画面に出る1行（ViewModel との接続）------------------------------

def build_view_model(tmp_path, resolver):
    from retroux.core.db.database import Database
    from retroux.core.recorder import Recorder
    from retroux.ui.view_model import ViewModel

    db = Database(tmp_path / "t.sqlite3")
    db.register_rom("HASH", "テストROM", "JP", mapper=2)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    return ViewModel(
        Recorder(db, "HASH", events, tmp_path / "command.json"), db, "HASH",
        map_meta={3: {"type": "town", "width": 32, "height": 32}},
        location_resolver=resolver)


def state(**kwargs):
    from retroux.core.bridge.state_reader import GameState

    base = dict(fresh=True, map_id=0x03, map_x=5, map_y=12,
                map_data_pointer=0x8000)
    base.update(kwargs)
    return GameState(**base)


def test_the_current_location_line_shows_the_name_and_the_id(tmp_path):
    """★名前だけにしない。**ID も残す**（ROM を調べるときに要る）。"""
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    line = vm.where_am_i(state())
    assert "ローレシア 1F" in line
    assert "$03" in line
    assert "(5, 12)".replace("(", "（").replace(")", "）") in line


def test_the_line_falls_back_to_the_id_when_there_is_no_dictionary(tmp_path):
    """⚠ 辞書が無くても**落ちず**、従来どおり ID が出ること。"""
    vm = build_view_model(tmp_path, None)
    line = vm.where_am_i(state())
    assert "マップ 03" in line
    assert vm.current_location(state()) is None
    assert vm.location_search_terms(state()) == []


def test_the_line_does_not_mark_every_name_as_needing_a_check(tmp_path):
    """★日本語名の大半は ROM 由来でない。全部に印を付けると印が無意味になる。"""
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    for map_id in (0x03, 0x0B, 0x2D):
        assert "要確認" not in vm.where_am_i(state(map_id=map_id))


def test_battle_and_stale_states_do_not_try_to_name_a_place(tmp_path):
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    assert vm.current_location(state(in_battle=True)) is not None  # 場所は読める
    assert vm.current_location(state(fresh=False)) is None
    assert vm.current_location(state(map_x=None)) is None
    assert "戦闘中" in vm.where_am_i(state(in_battle=True))


def test_the_view_model_hands_out_search_terms(tmp_path):
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    terms = vm.location_search_terms(state())
    assert "ドラゴンクエストII ローレシア 1F 攻略" in terms


@pytest.mark.parametrize(("map_id", "expected"), [
    (0x03, "ローレシア 1F [$03]"),
    (0x7F, "マップ 7F"),                    # ★辞書に無い。名前を作らない
])
def test_the_map_list_label_uses_the_name_when_there_is_one(tmp_path, map_id,
                                                            expected):
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    assert vm.map_label(map_id) == expected


def test_the_map_only_lookup_never_adds_a_region_name(tmp_path):
    """⚠ 座標が無いのに「ローレシア周辺」などと出してはいけない。"""
    resolver = LocationResolver(dictionary_with_regions(tmp_path))
    resolved = resolver.resolve_map(0x01)
    assert resolved.region is None
    assert resolved.display == "世界地図"
    assert resolver.resolve_map(None) is None


# --- 地図ウィンドウ（名前の出どころを画面に書く）----------------------

@pytest.fixture
def map_window(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6", reason="PySide6 が無い環境")
    from PySide6.QtWidgets import QApplication
    from retroux.ui.map_window import MapWindow

    app = QApplication.instance() or QApplication([])
    vm = build_view_model(tmp_path, LocationResolver.load(DATA))
    # 3マップぶん記録を入れる（ROM由来の名前 / 人の知識 / 辞書に無い）
    for map_id in (0x03, 0x0B, 0x7F):
        vm.db.mark_visited("HASH", map_id, 0x8000, 1, 1)
    win = MapWindow(vm)
    win.show()
    app.processEvents()
    yield win, vm
    win.close()


def test_the_map_window_says_when_a_name_came_from_the_rom(map_window):
    win, vm = map_window
    win._list.setCurrentRow(
        [k[0] for k in win._keys].index(0x03))
    assert "ROM の会話辞書" in win._name_note.text()
    assert "ROM 由来" in win._name_note.text()          # 階層のこと


def test_the_map_window_warns_when_a_name_was_entered_by_hand(map_window):
    """★★ **出どころを隠さない。** 隠すと間違った名前をそのまま信じる。"""
    win, vm = map_window
    win._list.setCurrentRow([k[0] for k in win._keys].index(0x0B))
    text = win._name_note.text()
    assert "ROM から取っていません" in text
    assert "locations.yaml" in text


def test_the_map_window_says_a_map_is_not_in_the_dictionary(map_window):
    win, vm = map_window
    win._list.setCurrentRow([k[0] for k in win._keys].index(0x7F))
    assert "辞書にありません" in win._name_note.text()
    # ★名前が無いのに検索語を出さない
    assert win._search.text() == ""


def test_the_map_window_offers_a_search_term_for_a_named_map(map_window):
    win, vm = map_window
    win._list.setCurrentRow([k[0] for k in win._keys].index(0x03))
    assert win._search.text() == "ドラゴンクエストII ローレシア 1F 攻略"


def test_the_map_list_shows_names_not_only_ids(map_window):
    win, vm = map_window
    labels = [win._list.item(i).text() for i in range(win._list.count())]
    assert any("ローレシア 1F" in t for t in labels)
    assert any("マップ 7F" in t for t in labels)

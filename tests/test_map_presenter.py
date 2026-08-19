"""地図に出す中身の組み立て（2026-08-01 の分割 / 指示書 §8.3）。

★★ **画面を建てずに確かめる。** ★★

  分割前は、文言を1つ確かめるのに
  `QApplication` + SQLite + ViewModel + `MapWindow` が要りました。
  いまは `MapPresenter` に**偽の view_model** を渡すだけで足ります。

⚠ 既存の `test_floor_estimator.py` / `test_location_resolver.py` は
  **窓ごと建てる形のまま残します**。あちらは「画面に出るか」を見ており、
  ここは「文言が正しいか」を見ます。★役割が違うので置き換えません。
"""

from __future__ import annotations

import dataclasses

from retroux.ui.map.presenter import MapPresenter, load_map_meta


# --- 偽の view_model ---------------------------------------------------
#
# ★足りない口は「無い」を返す。⚠ 適当な値を返すと、
#   「分からないときの出し方」を試せなくなる。

@dataclasses.dataclass
class FakeFloor:
    index: int | None = 1
    label: str | None = "B1"
    source: str = "binding"
    conflict: tuple = ()
    reason: str | None = None

    @property
    def known(self):
        return self.index is not None

    @property
    def has_conflict(self):
        return bool(self.conflict)

    @property
    def display(self):
        return self.label or "?"


@dataclasses.dataclass
class FakeLocation:
    name_en: str = "Cave"


@dataclasses.dataclass
class FakeResolved:
    registered: bool = True
    source: str = "rom"
    floor_label: str | None = "B1"
    location: FakeLocation = dataclasses.field(default_factory=FakeLocation)
    terms: tuple = ("ロンダルキア 攻略",)

    def search_terms(self):
        return list(self.terms)


class FakeVM:
    def __init__(self, **over):
        self.map_meta = over.get("map_meta", {})
        self._visited = over.get("visited", [(1, 0x8000, 12)])
        self._tiles = over.get("tiles", [(0, 0, 1, "fff"), (1, 0, 2, None)])
        self._size = over.get("size", (10, 8))
        self._type = over.get("type", "dungeon")
        self._matches = over.get("matches", True)
        self._label = over.get("label", "ロンダルキアの洞窟")
        self._notes = over.get("notes", [])
        self._landmarks = over.get("landmarks", [])
        self._connections = over.get("connections", [])
        self._floor = over.get("floor", FakeFloor())
        self._resolved = over.get("resolved", FakeResolved())

    def visited_maps(self):
        return list(self._visited)

    def map_size(self, _map_id):
        return self._size

    def map_type(self, _map_id):
        return self._type

    def map_matches_pointer(self, _map_id, _ptr):
        return self._matches

    def map_label(self, _map_id, _ptr):
        return self._label

    def visited_tiles(self, _map_id, _ptr):
        return list(self._tiles)

    def notes(self, _map_id, _ptr):
        return list(self._notes)

    def landmarks(self, _map_id, _ptr):
        return list(self._landmarks)

    def connections(self, _map_id, _ptr):
        return list(self._connections)

    def floor_of_map(self, _map_id, _ptr):
        return self._floor

    def location_of_map(self, _map_id):
        return self._resolved


def present(**over) -> MapPresenter:
    return MapPresenter(FakeVM(**over))


# --- 一覧 --------------------------------------------------------------

def test_the_list_shows_the_name_and_the_size():
    keys, rows = present().map_rows()
    assert keys == [(1, 0x8000)]
    assert "ロンダルキアの洞窟" in rows[0]
    assert "10x8" in rows[0]
    assert "見た 12 マス" in rows[0]


def test_the_list_marks_a_map_whose_pointer_disagrees():
    """⚠ 食い違いは**黙って直さない**。印を付けて人に見せる。"""
    _keys, rows = present(matches=False).map_rows()
    assert "⚠食い違い" in rows[0]


def test_the_list_says_question_mark_when_the_size_is_unknown():
    """★★ 分からない大きさを**推測で埋めない** ★★"""
    _keys, rows = present(size=(None, None)).map_rows()
    assert "?" in rows[0]
    assert "0x0" not in rows[0]        # ⚠ 0 と 不明 を混ぜない


# --- 見出し ------------------------------------------------------------

def test_the_title_reports_the_zoom_and_the_size():
    p = present()
    detail = p.detail(1, 0x8000)
    text = p.title_text(detail, zoom=4, outside=0)
    assert "10×8 マス" in text
    assert "拡大 ×4" in text
    assert "見た 2 マス" in text


def test_the_title_says_when_records_fell_outside_the_frame():
    """★★ **黙って捨てない**（Qt は範囲外の書き込みを無視する）★★

    ⚠ 数えて出さないと、記録がずれていることに誰も気づけない。
    """
    p = present()
    text = p.title_text(p.detail(1, 0x8000), zoom=1, outside=346)
    assert "枠の外 346 マス" in text


def test_the_title_falls_back_to_the_pointer_when_the_rom_has_no_entry():
    p = present()
    assert "0x8000" in p.title_text(p.detail(1, 0x8000), 1, 0)


def test_the_title_prefers_the_rom_data_pointer():
    p = present(map_meta={1: {"data_pointer": "0x9ABC"}})
    assert "0x9ABC" in p.title_text(p.detail(1, 0x8000), 1, 0)


# --- 階層（★分割で形が変わった所）--------------------------------------

def test_the_floor_text_does_not_carry_a_colour():
    """★★ **色は画面が決める** ★★（分割前はここで setStyleSheet していた）

    ⚠ 文字列に色が混ざっていると、文言だけを試せない。
    """
    got = present().floor_text(1, 0x8000)
    assert "#" not in got.text
    assert got.warn is False


def test_a_conflicting_floor_asks_the_person_to_decide():
    """★★ どちらが正しいかは**こちらで決めない** ★★"""
    got = present(floor=FakeFloor(conflict=(("manual", 2),))).floor_text(1, 0)
    assert got.warn is True
    assert "指定してください" in got.text


def test_an_unknown_floor_says_it_is_unknown():
    got = present(floor=FakeFloor(index=None, label=None)).floor_text(1, 0)
    assert "不明" in got.text
    assert got.warn is False


def test_an_inferred_floor_shows_why():
    """⚠ 推定値は**推定と書き、根拠も出す**（信じすぎないため）。"""
    got = present(floor=FakeFloor(source="inferred",
                                  reason="上へ2回")).floor_text(1, 0)
    assert "推定" in got.text
    assert "上へ2回" in got.text


def test_no_floor_estimate_gives_an_empty_line():
    assert present(floor=None).floor_text(1, 0).text == ""


# --- 名前の出どころ ----------------------------------------------------

def test_a_rom_name_is_called_certain():
    assert "確か" in present().name_source_text(1)


def test_a_hand_entered_name_is_flagged():
    """★★ 出どころを隠すと、間違った名前をそのまま信じてしまう ★★"""
    text = present(resolved=FakeResolved(source="knowledge")).name_source_text(1)
    assert "⚠" in text
    assert "ROM から取っていません" in text


def test_a_map_outside_the_dictionary_is_not_given_a_guessed_name():
    text = present(resolved=FakeResolved(registered=False)).name_source_text(1)
    assert "推測して出さない" in text


def test_without_a_dictionary_it_says_so():
    assert "辞書がありません" in present(resolved=None).name_source_text(1)


# --- つながり ----------------------------------------------------------

def test_links_say_there_is_no_record_rather_than_guessing():
    """★★ 「たぶんつながっている」は出さない ★★"""
    text = present().links_text(1, 0)
    assert "まだ記録がありません" in text
    assert "実際に通った所だけ" in text


def test_links_list_what_was_actually_walked():
    p = present(connections=[("風の塔", (3, 4), "stairs_down")])
    assert "（3, 4）" in p.links_text(1, 0)
    assert "風の塔" in p.links_text(1, 0)


def test_an_unreadable_transition_kind_is_shown_as_is():
    """⚠ 「種類未判定」に丸めると、綴り違いに気づけない。"""
    assert "⚠不明(typo_here)" == MapPresenter.kind_name("typo_here")


def test_links_are_capped_and_the_rest_is_counted():
    p = present(connections=[(f"先{i}", (i, 0), "stairs_down")
                             for i in range(9)])
    text = p.links_text(1, 0)
    assert "ほか 3 件" in text


# --- メモ・目印 --------------------------------------------------------

def test_marks_invite_the_person_when_there_is_nothing():
    assert "Ctrl+M" in present().marks_text(1, 0)


def test_an_unreadable_landmark_kind_is_still_counted():
    """★★ 読めない種類も**数に入れて出す**（黙って隠さない）★★"""
    text = present(landmarks=[{"kind": "not_a_kind"}]).marks_text(1, 0)
    assert "⚠不明" in text


def test_a_long_note_is_shortened_but_the_count_is_kept():
    p = present(notes=[{"body": "あ" * 50}, {"body": "い"}])
    text = p.marks_text(1, 0)
    assert "…" in text
    assert "メモ 2 件" in text
    assert "ほか 1 件" in text


# --- maps.json ---------------------------------------------------------

def test_a_missing_maps_file_is_not_an_error():
    """★無くても動く（推測の大きさを出さないだけ）。"""
    assert load_map_meta(None) == {}
    assert load_map_meta("does/not/exist.json") == {}


def test_a_broken_maps_file_is_not_an_error(tmp_path):
    bad = tmp_path / "maps.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert load_map_meta(bad) == {}


def test_maps_are_keyed_by_id(tmp_path):
    good = tmp_path / "maps.json"
    good.write_text('{"maps": [{"map_id": 3, "data_pointer": "0x1"}]}',
                    encoding="utf-8")
    assert load_map_meta(good)[3]["data_pointer"] == "0x1"


def test_a_map_without_an_id_is_skipped_not_crashed(tmp_path):
    """⚠ 1件おかしいだけで全部読めなくならないこと。"""
    mixed = tmp_path / "maps.json"
    mixed.write_text('{"maps": [{"no_id": 1}, {"map_id": 5}]}',
                     encoding="utf-8")
    assert list(load_map_meta(mixed)) == [5]


# --- 説明 --------------------------------------------------------------

def test_the_shortcut_help_lists_only_the_common_keys():
    """★★ 2026-08-19: よく使う2つ（メモ・名前と階層）だけ案内する（依頼者）。

    ⚠ Ctrl+P（写真）・Ctrl+矢印（遷移の種類）は上級操作なので**案内しない**
      （機能は残っている）。常時のツールチップを煩雑にしない。
    """
    text = MapPresenter.shortcut_help()
    assert "Ctrl+M" in text and "Ctrl+Shift+M" in text
    assert "Ctrl+P" not in text
    assert "Ctrl+↑" not in text and "こちらで決めました" not in text


# --- ★★ Qt を持ち込んでいないこと ★★ --------------------------------

def test_the_presenter_module_imports_without_qt(monkeypatch):
    """★★ 画面のない環境でも読めること ★★

    ⚠ `PySide6` を import していると、将来 CLI から使えない。
      ここは**実際に読み込んで**確かめる（import 文の検査は別にある）。
    """
    import importlib
    import sys

    saved = {k: v for k, v in sys.modules.items() if k.startswith("PySide6")}
    for key in saved:
        monkeypatch.delitem(sys.modules, key, raising=False)
    monkeypatch.setitem(sys.modules, "PySide6", None)
    module = importlib.reload(
        importlib.import_module("retroux.ui.map.presenter"))
    assert module.MapPresenter is not None


# ⚠⚠ **「widget を触っていないか」の文字列検査はここに置きません。**
#   一度書きましたが、この module の説明文に**旧コードを引用**しているため
#   `setStyleSheet` を誤検知しました（コメントを外しても docstring は残る）。
#   ★同じ検査は `test_layer_rules.py` に **AST 版**があります。
#     弱い重複を残すと、直したつもりで守られていない状態になります。

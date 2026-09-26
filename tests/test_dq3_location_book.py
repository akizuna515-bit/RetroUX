"""場所の名前を取る唯一の入口（RX3-0080 §23 / §24）。

```text
同一 Location   map A → X / map B → X。★A の初回だけメモ。⚠ B では増やさない
仮名           拠点 ＋ 方角 ＋ 種別。⚠ 種別が分からなければ「場所」
昇格           provisional → dialogue / manual。★location_id は変わらない
No-Spoiler     ⚠ 知らない正式名を先回りで出さない
suffix         同じ場所の複数 map を「名前」「名前 #2」で見分ける
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.knowledge import location_book as LB
from dq3.knowledge import location_master as LM


def _master(rows):
    """★使い捨ての Master（⚠ ファイルを作らない）。"""
    return LM.LocationMaster({r.map_id: r for r in rows})


def _row(map_id, loc, name="", suffix="", source="", kind=""):
    return LM.Row(map_id=map_id, location_id=loc, display_name=name, suffix=suffix,
                  name_source=source, location_type=kind)


def _book(tmp_path, master=None, rom_place_name=None, heard_place_name=None):
    """⚠ 既定では **ROM も記録も見ません**（★仮名の決まりだけを見る / RX3-0092 / 0101）。"""
    return LB.LocationBook(master or LM.LocationMaster({}), tmp_path / "book.json",
                           rom_place_name or (lambda map_id: None),
                           heard_place_name or (lambda map_id: None))


# --- ★map と場所を分ける -----------------------------------------------------------

def test_既定は1map1場所で既存のidと同じ名前空間(tmp_path):
    """⚠⚠ ここを変えると、貯まっている `location:L9` の Fact が当たらなくなる。"""
    book = _book(tmp_path)
    assert book.location_id_of(9) == "L9" == LB.default_location_id(9)


def test_複数mapを同じ場所として扱える(tmp_path):
    master = _master([_row(12, "castle", "アリアハン城", source="manual", kind="castle"),
                      _row(13, "castle", "アリアハン城", "2F", "manual", "castle"),
                      _row(14, "castle", "アリアハン城", "B1", "manual", "castle")])
    book = _book(tmp_path, master)
    assert book.location_id_of(13) == "castle"
    assert book.get_location_name(12) == "アリアハン城"
    assert book.get_location_name(13, detailed=True) == "アリアハン城 2F"
    assert book.get_location_name(14, detailed=True) == "アリアハン城 B1"


def test_suffixはMasterに無ければ連番(tmp_path):
    master = _master([_row(20, "town", "レーベ", source="manual"),
                      _row(21, "town", "レーベ", source="manual"),
                      _row(22, "town", "レーベ", source="manual")])
    book = _book(tmp_path, master)
    assert book.get_location_name(20, detailed=True) == "レーベ"
    assert book.get_location_name(21, detailed=True) == "レーベ #2"
    assert book.get_location_name(22, detailed=True) == "レーベ #3"


# --- ★★ 発見は location_id で数える（指示書 §14 / §24）------------------------------

def test_同じ場所の別の階では発見にならない(tmp_path):
    master = _master([_row(12, "castle"), _row(13, "castle"), _row(14, "castle")])
    book = _book(tmp_path, master)
    assert book.enter(12)["first"] is True
    assert book.enter(13)["first"] is False, "⚠⚠ 階を移るたびに『見つけた』になっている"
    assert book.enter(14)["first"] is False
    assert book.enter(12)["first"] is False
    assert book.locations["castle"].map_ids == [12, 13, 14]


def test_別の場所なら発見になる(tmp_path):
    book = _book(tmp_path)
    assert book.enter(9)["first"] is True
    assert book.enter(70)["first"] is True
    assert book.enter(9)["first"] is False


def test_メモは1度だけ(tmp_path):
    book = _book(tmp_path)
    book.enter(9)
    assert not book.locations["L9"].memo_done
    book.mark_memo_done("L9")
    assert book.locations["L9"].memo_done
    book.mark_memo_done("L9")                       # ⚠ 二度目は何もしない


# --- ★仮名（指示書 §9〜§11）---------------------------------------------------------

@pytest.mark.parametrize("base, here, wanted", [
    ((100, 100), (100, 90), "北"),
    ((100, 100), (110, 90), "北東"),
    ((100, 100), (110, 100), "東"),
    ((100, 100), (110, 110), "南東"),
    ((100, 100), (100, 110), "南"),
    ((100, 100), (90, 110), "南西"),
    ((100, 100), (90, 100), "西"),
    ((100, 100), (90, 90), "北西"),
    ((100, 100), (100, 100), None),
])
def test_方角は8方向(base, here, wanted):
    assert LB.direction_between(base, here) == wanted


def test_仮名は拠点と方角と種別から作る(tmp_path):
    book = _book(tmp_path)
    book.enter(9, world_xy=(160, 195))
    book.promote("L9", "アリアハン", source="dialogue")
    book.locations["L9"].location_type = "town"
    got = book.make_provisional_name((150, 185), "cave")
    assert got == "アリアハン北西の洞窟"


def test_種別が分からなければ場所と呼ぶ(tmp_path):
    """⚠⚠ 推測で「洞窟」と言わない（★実測: tileset では見分けられない）。"""
    book = _book(tmp_path)
    book.enter(9, world_xy=(160, 195))
    book.promote("L9", "レーベ", source="dialogue")
    assert book.make_provisional_name((170, 195), "") == "レーベ東の場所"


# --- ★RX3-0180: 仮名の拠点は「いちばん近い町」（2026-09-12）-----------------------------
#
#   ⚠⚠ 依頼者「save5 祠の場所だが、アリアハンではなく、ロマリアの北東に思える」:
#     直近に居た拠点（アリアハン）で名前を付けていたので、ルーラで渡った先の祠が
#     「アリアハン北西の場所」になった。★座標は依頼者のセーブ・記録の値。

_TOWNS = {0: "アリアハン", 1: "ロマリア"}


def _town_book(tmp_path):
    return _book(tmp_path, rom_place_name=lambda map_id: _TOWNS.get(map_id))


def _visit(book, map_id, x, y):
    """★世界地図から入って、また世界地図へ出る（⚠ 出ないと次の map が「中の小部屋」になる）。"""
    got = book.enter(map_id, world_xy=(x, y))
    book.note_world(x, y)
    return got


def test_仮名はいちばん近い町を基準にする(tmp_path):
    book = _town_book(tmp_path)
    _visit(book, 1, 53, 89)                             # ★ロマリア（先に行った）
    _visit(book, 0, 172, 218)                           # ★アリアハン（直近の拠点）
    got = _visit(book, 43, 38, 73)                      # ★ロマリアのそばの祠
    assert got["name"] == "ロマリア北西の場所", "⚠⚠ 直近の拠点（遠い大陸）で名前を付けた"


def test_人が名付けた場所より町を基準にする(tmp_path):
    """⚠ 「アリアハンの玉座」は町と同じ升の座標を持つ拠点。★混ぜると「玉座北東」になる。"""
    book = _town_book(tmp_path)
    _visit(book, 0, 172, 218)
    _visit(book, 71, 172, 217)
    book.promote("L71", "アリアハンの玉座", source="manual")
    assert _visit(book, 152, 190, 210)["name"] == "アリアハン北東の場所"


def test_遠い町を名乗った仮名は入り直すと付け直す(tmp_path):
    book = _town_book(tmp_path)
    _visit(book, 0, 172, 218)
    assert _visit(book, 43, 38, 73)["name"] == "アリアハン北西の場所"   # ★ロマリアを知る前
    _visit(book, 1, 53, 89)
    assert _visit(book, 43, 38, 73)["name"] == "ロマリア北西の場所", "⚠⚠ 近い町を知っても古い仮名のまま"


def test_近い町が同じなら仮名を変えない(tmp_path):
    """⚠ 入るたびに名前が変わるのが依頼者の困りごと（RX3-0122）。★近い町が同じなら触らない。"""
    book = _town_book(tmp_path)
    _visit(book, 0, 172, 218)
    first = _visit(book, 152, 190, 210)["name"]
    _visit(book, 1, 53, 89)                             # ★遠くの町を知っても
    assert _visit(book, 152, 190, 210)["name"] == first == "アリアハン北東の場所"


def test_拠点が無ければ未確認(tmp_path):
    """⚠ 2026-09-08（RX3-0122）: 「知らない洞窟」→ ★「未確認の洞窟1」。

    ★「知らない」は突き放して聞こえます。⚠ 実際は**まだ確かめていない**だけです。
    """
    book = _book(tmp_path)
    assert book.make_provisional_name((10, 10), "cave") == "未確認の洞窟1"


def test_同じ升なら近辺と呼ぶ(tmp_path):
    """⚠⚠ 2026-09-08（RX3-0122）: 「レーベの場所」→ ★「レーベ近辺1」。

    ★方角が出ないのに「レーベの場所」と書くと、⚠ **レーベそのもの**に見えます。
    ★「近辺」なら、⚠ 近くだとしか言っていないことが分かります。
    """
    book = _book(tmp_path)
    book.enter(9, world_xy=(160, 195))
    book.promote("L9", "レーベ", source="dialogue")
    assert book.make_provisional_name((160, 195), "") == "レーベ近辺1"


def test_座標が無ければ拠点の名前を名乗らない(tmp_path):
    """⚠⚠ 2026-09-06 依頼者: アリアハン（map 0）が「レーべの場所 2」になっていた。

    ★`direction_between` は「同じ升」でも「座標が無い」でも `None` を返します。
    ⚠ 見分けずに拠点の名前を使うと、**まったく無関係な場所の名前**を名乗ります。
    → ★座標が片方でも無いなら、拠点が無いときと同じ「知らない…」にします。
    """
    book = _book(tmp_path)
    book.enter(9, world_xy=(160, 195))
    book.promote("L9", "レーベ", source="dialogue")
    assert book.make_provisional_name(None, "") == "未確認の場所1"
    assert book.make_provisional_name(None, "cave") == "未確認の洞窟1"


def test_拠点の座標が無ければ名乗らない(tmp_path):
    """⚠ 古い記録から起こした場所には世界座標がありません（★migrate 由来）。"""
    book = _book(tmp_path)
    book.enter(9)                                        # ⚠ world_xy を渡さない
    book.promote("L9", "レーベ", source="dialogue")
    assert book.locations["L9"].world_x is None
    assert book.make_provisional_name((10, 10), "") == "未確認の場所1"


def test_誤った仮名は入り直したときに付け直す(tmp_path):
    """⚠⚠ 依頼者の記録に「レーべの場所 2」が**保存されて**いた（2026-09-06）。

    ★決まりを直しても、⚠ 既に付いた名前は記録に残ります。
    → ★座標が無いのに拠点を名乗っている仮名は、入り直したときに付け直します。
    """
    book = _book(tmp_path)
    book.enter(9, world_xy=(160, 195))
    book.promote("L9", "レーベ", source="dialogue")
    # ★RX3-0091 より前に付いた形をそのまま置く
    book.note_world(160, 195)              # ⚠ 世界地図へ出る（★中に居ない / RX3-0122）
    book.enter(0)
    book.locations["L0"].display_name = "レーベの場所 2"
    book.locations["L0"].name_source = LB.PROVISIONAL
    book.locations["L0"].name_rule = ""        # ⚠ RX3-0122 より前の記録（★付け方が無い）
    book.locations["L0"].world_x = None

    # ⚠ `note_world` を挟まない（★挟むと中に居た L0 へ座標を入れ直してしまう）
    got = book.enter(0)
    assert got["name"] == "未確認の場所1", "⚠ 誤った仮名が残っている"
    assert got["provisional"] is True
    # ⚠ 人が付けた名前・会話で覚えた名前は触らない
    book.rename("L0", "アリアハン")
    assert book.enter(0)["name"] == "アリアハン"


def test_初めて入ると仮名が付いて残る(tmp_path):
    book = _book(tmp_path)
    book.note_world(160, 195)
    book.enter(9)
    book.promote("L9", "レーベ", source="dialogue")
    book.note_world(150, 185)                       # ★世界地図を北西へ歩いた
    got = book.enter(41)
    assert got["first"] and got["provisional"]
    assert got["name"] == "レーベ北西の場所"
    # ★2 度目は同じ仮名（⚠ 作り直さない / 指示書 §12）
    #   ⚠⚠ 「拠点が変わっても名前が変わらない」まで見ます。★ここを見ないと、
    #     `if not loc.display_name:` を `if True:` に壊しても**鳴りません**
    #     （2026-09-05 に実際に空振りした）。
    book.enter(70, world_xy=(200, 100))
    book.promote("L70", "カザーブ", source="dialogue")
    book.note_world(999, 999)
    again = book.enter(41)
    assert not again["first"]
    assert again["name"] == "レーベ北西の場所", "⚠⚠ 仮名を作り直した（★拠点が変わると名前が変わる）"


def test_出た直後の升をその場所の座標にする(tmp_path):
    """⚠⚠ これが無いと方角が出ない（★2026-09-05 に実測で踏んだ）。

    ★町から出ると、勇者は**その町の升**に立ちます。
    """
    book = _book(tmp_path)
    book.enter(9)                                    # ⚠ 世界の升をまだ知らない
    assert book.locations["L9"].world_x is None
    book.note_world(159, 192)                        # ★出た直後 = レーベの升
    assert (book.locations["L9"].world_x, book.locations["L9"].world_y) == (159, 192)
    book.note_world(150, 183)                        # ⚠ そのあと歩いた升では上書きしない
    assert book.locations["L9"].world_x == 159
    book.promote("L9", "レーベ", source="dialogue")
    assert book.enter(41)["name"] == "レーベ北西の場所"


def test_拠点は名前が確定して訪れたものだけ(tmp_path):
    book = _book(tmp_path)
    book.note_world(160, 195)
    book.enter(9)                                    # ⚠ 仮名だけ → 拠点にならない
    assert book.get_last_known_base() is None
    book.promote("L9", "レーベ", source="dialogue")
    base = book.get_last_known_base()
    assert base is not None and base.display_name == "レーベ"


# --- ★昇格（指示書 §12）-------------------------------------------------------------

def test_仮名から正式名へ昇格してもidは変わらない(tmp_path):
    book = _book(tmp_path)
    book.note_world(160, 195)
    book.enter(9)
    book.promote("L9", "レーベ", source="dialogue")
    book.note_world(150, 185)
    book.enter(41)
    before = book.locations["L41"]
    assert before.name_source == LB.PROVISIONAL and before.display_name == "レーベ北西の場所"

    assert book.promote("L41", "ナジミの塔", source="dialogue")
    after = book.locations["L41"]
    assert after.location_id == "L41", "⚠⚠ 昇格で id が変わった（★過去の記録と切れる）"
    assert after.display_name == "ナジミの塔" and after.name_source == "dialogue"
    assert after.known and after.first_seen_at == before.first_seen_at


def test_人とROMの名前は会話で上書きされない(tmp_path):
    book = _book(tmp_path)
    book.enter(9)
    book.rename("L9", "わたしの村")
    assert book.locations["L9"].name_source == "manual"
    assert not book.promote("L9", "レーベ", source="dialogue")
    assert book.locations["L9"].display_name == "わたしの村"


def test_勝手な昇格はしない(tmp_path):
    book = _book(tmp_path)
    book.enter(9)
    assert not book.promote("L9", "", source="dialogue")
    assert not book.promote("L9", "レーベ", source="provisional")
    assert not book.promote("L404", "どこか", source="dialogue")


# --- ⚠ No-Spoiler（指示書 §19）-------------------------------------------------------

def test_知らない場所の名前は出さない(tmp_path):
    """⚠⚠ ROM に正式名があっても、★入る前に名前を出さない。"""
    book = _book(tmp_path)
    assert book.get_location_name(41) is None
    assert not book.is_location_known("L41")
    assert book.get_location(41).display_name is None


def test_Masterに人が書いた名前だけは出る(tmp_path):
    """★人が書いたものは「知っている」扱い（⚠ ROM から引いたのではない）。"""
    master = _master([_row(41, "L41", "ナジミの塔", source="manual", kind="tower")])
    book = _book(tmp_path, master)
    assert book.get_location_name(41) == "ナジミの塔"


def test_仮名は正式名ではない(tmp_path):
    book = _book(tmp_path)
    book.note_world(160, 195)
    book.enter(9)
    book.promote("L9", "レーベ", source="dialogue")
    book.note_world(150, 185)
    book.enter(41)
    assert not book.is_location_known("L41"), "⚠ 仮名を『知っている』にしてはいけない"


# --- ★しまう・戻す -----------------------------------------------------------------

def test_保存して読み直せる(tmp_path):
    book = _book(tmp_path)
    book.note_world(160, 195)
    book.enter(9)
    book.promote("L9", "レーベ", source="dialogue")
    book.mark_memo_done("L9")
    assert book.save()
    again = LB.LocationBook.load(master_path=tmp_path / "none.csv", path=tmp_path / "book.json")
    assert again.locations["L9"].display_name == "レーベ"
    assert again.locations["L9"].memo_done and again.last_world == (160, 195)
    assert again.get_last_known_base().display_name == "レーベ"
    assert not book.save(), "⚠ 変わっていないのに書いた"


def test_進み具合はGitの外():
    import subprocess
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    from dq3 import paths as P3

    # ⚠ 検査中は書き先が一時フォルダなので、repo 側の同じ道を見る（`paths.as_repo` / RX-0141）
    real = P3.as_repo(LB.BOOK_PATH)
    got = subprocess.run(["git", "check-ignore", "-q", str(real)],
                         cwd=str(root), capture_output=True)
    assert got.returncode == 0, "⚠⚠ %s が Git 管理対象" % real
    assert "work" in real.parts
    assert "input" in LM.OFFICIAL_PATH.parts


def test_壊れた記録でも落ちない(tmp_path):
    (tmp_path / "book.json").write_text('{"locations": {"L1": {"nope": 1}, "L2": 3}}',
                                        encoding="utf-8")
    book = LB.LocationBook.load(master_path=tmp_path / "none.csv", path=tmp_path / "book.json")
    assert book.locations == {} or "L2" not in book.locations


def test_メモの文(tmp_path):
    assert LB.memo_text("レーベ北西の場所", True) == "レーベ北西の場所を見つけた"
    assert LB.memo_text("レーベ", False) == "レーベへ はじめて来た"


def test_管理画面の初期化に入っている():
    from dq3.knowledge import playdata as PD

    files = {name for _k, _l, names in PD.ITEMS for name in names}
    assert LB.BOOK_PATH.name in files


# --- ★ROM の地名（ルーラの行き先 / RX3-0092）--------------------------------------

_ROM = pathlib.Path(__file__).resolve().parents[1] / "work" / "rom" / "DQ3_J.nes"
needs_rom = pytest.mark.skipif(not _ROM.exists(), reason="⚠ ROM が無い環境")


@needs_rom
def test_行った街はROMの名前が付く(tmp_path):
    """★依頼者 2026-09-06「アリアハンと出るべきでは」。⚠ 名前はここに書かない。"""
    from dq3.knowledge import rom_names as RN

    RN.reset()
    want = RN.place_for_map(0)
    assert want, "⚠ ROM から地名が引けない"
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    got = book.enter(0)
    assert got["name"] == want
    assert got["provisional"] is False
    assert book.locations["L0"].name_source == "rom"
    assert book.locations["L0"].known


@needs_rom
def test_ルーラに無い場所は今までどおり仮名(tmp_path):
    """⚠ ROM の表は 20 件だけ（★城・洞窟・小さな村は入っていない）。"""
    from dq3.knowledge import rom_names as RN

    RN.reset()
    assert RN.place_for_map(70) is None, "⚠ 20 件の外のはず"
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    got = book.enter(70)
    assert got["provisional"] is True
    assert got["name"] == "未確認の場所1"


@needs_rom
def test_人が付けた名前はROMで上書きしない(tmp_path):
    from dq3.knowledge import rom_names as RN

    RN.reset()
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(0)
    book.rename("L0", "わたしの街")
    assert book.enter(0)["name"] == "わたしの街"
    assert book.locations["L0"].name_source == "manual"


@needs_rom
def test_誤った仮名はROMの名前で直る(tmp_path):
    """⚠⚠ 依頼者の記録に残っていた「レーべの場所 2」が、★入り直しで本名になる。"""
    from dq3.knowledge import rom_names as RN

    RN.reset()
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(0)
    book.locations["L0"].display_name = "レーベの場所 2"
    book.locations["L0"].name_source = LB.PROVISIONAL
    book.locations["L0"].world_x = None
    assert book.enter(0)["name"] == RN.place_for_map(0)


@needs_rom
def test_保存済みのROM名は入り直すたびに引き直す(tmp_path):
    """⚠⚠ 2026-09-07 依頼者「アリアハンになっていない」。

    ★`RX3-0093` で復号器を直しても、⚠ **すでに保存された名前は古いまま**でした
      （`name_source: rom` は付け直しの対象外だったため）。
    → ★ROM は正本で、引くのは安い。**入るたびに引き直します**。
    """
    from dq3.knowledge import rom_names as RN

    RN.reset()
    want = RN.place_for_map(0)
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(0)
    # ★古い綴りが保存されていた状態を作る
    book.locations["L0"].display_name = "アりアハン"
    book.locations["L0"].name_source = "rom"
    assert book.enter(0)["name"] == want, "⚠ 古い ROM 名が残っている"


@needs_rom
def test_ROMに名前があれば会話で覚えた名前より強い(tmp_path):
    """★`promote` の決まり（rom / manual は dialogue より強い）を `enter` にも通す。"""
    from dq3.knowledge import rom_names as RN

    RN.reset()
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(9)
    book.locations["L9"].display_name = "レーべ"           # ⚠ 画面から読んだ古い綴り
    book.locations["L9"].name_source = "dialogue"
    assert book.enter(9)["name"] == RN.place_for_map(9)
    assert book.locations["L9"].name_source == "rom"


@needs_rom
def test_人が付けた名前はROMより強いまま(tmp_path):
    """⚠⚠ ここは変えない。★人が付けた名前を機械が上書きしない。"""
    from dq3.knowledge import rom_names as RN

    RN.reset()
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(0)
    book.rename("L0", "わたしの街")
    assert book.enter(0)["name"] == "わたしの街"
    assert book.locations["L0"].name_source == "manual"


@needs_rom
def test_名前がぶつかるときは種別で分ける(tmp_path):
    """⚠⚠ RX3-0100: 城の挨拶を拾えると、★名前が map 0 と**同じ**になります。

    → ⚠ `_unique` が「アリアハン 2」を作ります（★`RX3-0091` で踏んだ形）。
    ★挨拶は種別も教えてくれるので、⚠ ぶつかるときだけ種別で分けます。
    """
    from dq3.knowledge import rom_names as RN

    RN.reset()
    book = _book(tmp_path, rom_place_name=RN.place_for_map)
    book.enter(0)                                        # ★L0 = アリアハン（ROM）
    base = book.locations["L0"].display_name
    book.enter(70)
    assert book.promote("L70", base, source="dialogue", location_type="castle")
    got = book.locations["L70"]
    assert got.location_type == "castle"
    assert got.display_name == base + "の城", got.display_name
    assert "2" not in got.display_name, "⚠⚠ 連番で逃げている"
    # ⚠ もとの場所は変わらない
    assert book.locations["L0"].display_name == base


def test_ぶつからなければそのままの名前(tmp_path):
    book = _book(tmp_path)
    book.enter(9)
    assert book.promote("L9", "レーベ", source="dialogue", location_type="village")
    assert book.locations["L9"].display_name == "レーベ"
    assert book.locations["L9"].location_type == "village"


def test_記録済みの挨拶が入るだけで台帳へ渡る(tmp_path):
    """⚠⚠ 2026-09-07 依頼者「まだ出ない。聞き込み直しが必要？」→ ★要りません。

    ★`learn_from_text` は「既に覚えていれば触らない」ので、⚠ 一度
    `player-knowledge.json` に入ると**二度と promote されません**。
    → ★入るたびに記録からも取り直します。
    """
    book = _book(tmp_path, rom_place_name=lambda m: None,
                 heard_place_name=lambda m: ("アリアハン", "castle") if m == 70 else None)
    got = book.enter(70)
    assert got["name"] == "アリアハン"
    assert book.locations["L70"].name_source == "dialogue"
    assert book.locations["L70"].location_type == "castle"
    assert got["provisional"] is False


def test_記録から取れなければ今までどおり仮名(tmp_path):
    book = _book(tmp_path, rom_place_name=lambda m: None, heard_place_name=lambda m: None)
    assert book.enter(70)["name"] == "未確認の場所1"


def test_人が付けた名前は記録で上書きしない(tmp_path):
    book = _book(tmp_path, rom_place_name=lambda m: None,
                 heard_place_name=lambda m: ("アリアハン", "castle"))
    book.enter(70)
    book.rename("L70", "わたしの城")
    assert book.enter(70)["name"] == "わたしの城"
    assert book.locations["L70"].name_source == "manual"


# ======================================================================
# ★仮名を親と近隣から作る（RX3-0122 / 2026-09-08）
# ======================================================================
#
# ⚠⚠ 依頼者「いまの仮名は位置関係を想像しづらい」（2026-09-08）
#
# ```text
# 1 親が分かる    レーベの小部屋1      ★同じ場所の中から入った
# 2 方角が出る    アリアハン北西の洞窟  ★世界座標があり向きが決まる
# 3 近隣が分かる  レーベ近辺1          ⚠ 方角は出ないが近くに既知の拠点
# 4 何も無い      未確認の場所1        ⚠⚠ 推測しない
# ```

def _in_town(tmp_path, name="レーベ", at=(160, 195)):
    """★名前の分かっている町に居る状態を作る。"""
    book = _book(tmp_path)
    book.note_world(*at)
    book.enter(9, world_xy=at)
    book.promote("L9", name, source="dialogue")
    book.locations["L9"].location_type = "town"
    return book


def test_町の中から入った小部屋は町の名前を借りる(tmp_path):
    book = _in_town(tmp_path)
    got = book.enter(200)                          # ⚠ 世界地図を経ずに別の map へ
    assert got["name"] == "レーベの小部屋1"
    assert book.locations["L200"].name_rule == LB.PARENT_RULE


def test_小部屋は入るたびに番号が増える(tmp_path):
    book = _in_town(tmp_path)
    assert book.enter(200)["name"] == "レーベの小部屋1"
    book.enter(9)                                  # ★いったん町へ戻る
    assert book.enter(201)["name"] == "レーベの小部屋2"


def test_種別が分かるなら小部屋と言わない(tmp_path):
    book = _in_town(tmp_path)
    book.locations["L202"] = LB.Location(location_id="L202", location_type="tower")
    assert book.enter(202)["name"] == "レーベの塔1"


def test_世界地図へ出たら親にしない(tmp_path):
    """⚠⚠ 「中に居る」は世界地図へ出た時点で終わり（★別の場所の小部屋にしない）。"""
    book = _in_town(tmp_path)
    book.note_world(150, 185)                      # ★町を出て歩いた
    got = book.enter(70)
    assert "小部屋" not in got["name"], got["name"]
    assert got["name"] == "レーベ北西の場所"
    assert book.locations["L70"].name_rule == LB.DIRECTION_RULE


def test_仮名の中に仮名を作らない(tmp_path):
    """⚠⚠ 「未確認の場所1の小部屋1」を作らない（★親は名前が確かなものだけ）。"""
    book = _book(tmp_path)
    assert book.enter(70)["name"] == "未確認の場所1"
    got = book.enter(71)                           # ⚠ 仮名の場所の中から入った
    assert got["name"] == "未確認の場所2", got["name"]


# ★★ RX3-0275（2026-09-14 依頼者「ここのmapに◯があるが、何もない」）
#   ⚠ 仮名の小部屋から奥へ入ると、親にできず世界地図の方角で名付けていた（★イシスの城の奥が「イシス西の場所」）。
#   ⚠ 場所の升は 0.5 秒おきに読んだ最後の世界地図の升（★町の 1〜2 歩手前 / ルーラで着いた升）だった。

def test_小部屋の奥の部屋も町の小部屋として数える(tmp_path):
    book = _in_town(tmp_path)
    assert book.enter(200)["name"] == "レーベの小部屋1"
    got = book.enter(201)                          # ★仮名の小部屋の中から、さらに奥へ
    assert got["name"] == "レーベの小部屋2", "⚠⚠ 世界地図の方角で名付けた: %s" % got["name"]
    loc = book.locations["L201"]
    assert loc.name_rule == LB.PARENT_RULE and loc.parent_location_id == "L9"
    assert (loc.world_x, loc.world_y) == (160, 195), "⚠ 町の升でない（★最後に読んだ世界地図の升を使った）"
    assert book.locations["L200"].parent_location_id == "L9", "★小部屋にも親の id を残す（◯ を出さない）"


def test_親のidが無い古い小部屋からでも名前で親を引く(tmp_path):
    book = _in_town(tmp_path)
    book.enter(200)
    book.locations["L200"].parent_location_id = ""   # ⚠ RX3-0275 より前の記録（★親の id が無い）
    assert book.enter(201)["name"] == "レーベの小部屋2"
    assert book.anchor_of(book.locations["L200"]).location_id == "L9"


def test_前の決まりで方角の名前が付いた奥の部屋を付け直す(tmp_path):
    """★イシス西の場所（map 87 / 83）: 仮名の小部屋から入ったのに、世界地図の方角で名付けていた。"""
    book = _in_town(tmp_path)
    book.enter(200)                                  # ★レーベの小部屋1
    book.locations["L201"] = LB.Location(
        location_id="L201", display_name="レーベ西の場所", name_source=LB.PROVISIONAL,
        name_rule=LB.DIRECTION_RULE, visited=True, world_x=150, world_y=195, map_ids=[201])
    got = book.enter(201)                            # ★小部屋1 の中から入り直した
    assert got["name"] == "レーベの小部屋2", got["name"]
    loc = book.locations["L201"]
    assert loc.name_rule == LB.PARENT_RULE and (loc.world_x, loc.world_y) == (160, 195)


def test_町そのものから入った方角の名前は付け直さない(tmp_path):
    """⚠ 町の外の原っぱの map などは、町（小部屋でない）から入っても方角の名前のまま。"""
    book = _in_town(tmp_path)
    book.locations["L150"] = LB.Location(
        location_id="L150", display_name="レーベ東の場所", name_source=LB.PROVISIONAL,
        name_rule=LB.DIRECTION_RULE, visited=True, world_x=163, world_y=195, map_ids=[150])
    assert book.enter(150)["name"] == "レーベ東の場所"


def test_出口の升で入る手前の升を直す(tmp_path):
    """★アッサラーム: 0.5 秒おきの読みでは町の 1 歩手前 (85,110)。出ると立つ升は (86,110)。"""
    book = _book(tmp_path)
    book.note_world(85, 110)
    book.enter(12)
    assert (book.locations["L12"].world_x, book.locations["L12"].world_y) == (85, 110)
    book.note_world(88, 110, exit_xy=(86, 110))      # ★出た直後の升（Lua が毎フレーム見た）
    assert (book.locations["L12"].world_x, book.locations["L12"].world_y) == (86, 110)
    book.note_world(90, 110, exit_xy=(86, 110))      # ⚠ そのあとの読みでは触らない
    assert book.locations["L12"].world_x == 86


def test_ルーラで遠くへ出た升では直さない(tmp_path):
    book = _book(tmp_path)
    book.note_world(86, 110)
    book.enter(12)
    book.note_world(35, 138, exit_xy=(35, 138))      # ⚠ 町の中からルーラ・キメラのつばさ
    assert (book.locations["L12"].world_x, book.locations["L12"].world_y) == (86, 110)


def test_入口の升が届けば手前の升より先に使う(tmp_path):
    book = _book(tmp_path)
    book.note_world(85, 110)                         # ⚠ 0.5 秒おきの読み（1 歩手前）
    book.enter(12, world_xy=(86, 110))               # ★Lua の入口の升
    assert (book.locations["L12"].world_x, book.locations["L12"].world_y) == (86, 110)


# ★塔・洞窟の別の階（RX3-0196 / 2026-09-12）
#   依頼者「save5 ここはナジミの塔２Fなんだが、うまく特定できないか？ ※ナジミの塔から階段で上がってきた」→ 案 A
#   ★親が塔・洞窟なら「ナジミの塔 #2」。⚠ #n は通し番号（★何階かは言わない / 上り下りは分からない）

def _in_tower(tmp_path, name="ナジミの塔"):
    book = _book(tmp_path)
    book.note_world(120, 200)
    book.enter(159, world_xy=(120, 200))
    book.rename("L159", name)
    return book


def test_塔の中から階段で入った先は同じ塔の別の階(tmp_path):
    book = _in_tower(tmp_path)
    got = book.enter(214)                          # ★世界地図を経ずに（= 階段で）
    assert got["name"] == "ナジミの塔 #2", got["name"]
    loc = book.locations["L214"]
    assert loc.name_rule == LB.FLOOR_RULE and loc.parent_location_id == "L159"


def test_階の中からさらに入ると次の番号(tmp_path):
    book = _in_tower(tmp_path)
    assert book.enter(214)["name"] == "ナジミの塔 #2"
    assert book.enter(215)["name"] == "ナジミの塔 #3", "⚠ 仮名の階の中から入った先に番号が続かない"
    book.enter(214)                                # ★戻っても名前は変わらない
    assert book.locations["L214"].display_name == "ナジミの塔 #2"


def test_人が付けた階の名前からでも塔の名前で数える(tmp_path):
    book = _in_tower(tmp_path)
    book.enter(214)
    book.rename("L214", "ナジミの塔２F")            # ★人が付けた名前は変えない
    got = book.enter(216)
    assert got["name"] == "ナジミの塔 #2", "⚠ 「２F」を外して塔の名前で数えていない: %s" % got["name"]
    assert book.locations["L214"].display_name == "ナジミの塔２F"


def test_種別が塔と分かっていれば名前によらず階(tmp_path):
    book = _book(tmp_path)
    book.enter(60)
    book.rename("L60", "シャンパーニ")
    book.locations["L60"].location_type = "tower"
    assert book.enter(61)["name"] == "シャンパーニ #2"


def test_町の中は今までどおり小部屋で階にしない(tmp_path):
    book = _in_town(tmp_path)                      # ★町（種別 town）
    assert book.enter(200)["name"] == "レーベの小部屋1"
    assert LB.LocationBook.dungeon_root(book.locations["L9"]) is None


def test_方角が出なければ近辺(tmp_path):
    book = _in_town(tmp_path)
    book.note_world(160, 195)                      # ★町と同じ升
    got = book.enter(70)
    assert got["name"] == "レーベ近辺1"
    assert book.locations["L70"].name_rule == LB.NEARBY_RULE


def test_何も分からなければ未確認(tmp_path):
    book = _book(tmp_path)
    assert book.enter(70)["name"] == "未確認の場所1"
    assert book.locations["L70"].name_rule == LB.UNSURE_RULE
    assert book.enter(71)["name"] == "未確認の場所2"


def test_攻略知識から正式名を推測しない(tmp_path):
    """⚠⚠ 「ナジミの塔」などを**知っているから**といって付けない。"""
    book = _book(tmp_path)
    got = book.enter(70)
    assert got["provisional"] is True
    assert book.locations["L70"].confidence == "HYPOTHESIS"
    assert book.locations["L70"].name_source == LB.PROVISIONAL


# --- ⚠⚠ 名前が変わらないこと（★依頼者の困りごと）--------------------------

def test_入り直しても同じ仮名(tmp_path):
    book = _in_town(tmp_path)
    first = book.enter(200)["name"]
    for _ in range(3):
        book.enter(9)
        assert book.enter(200)["name"] == first
    assert first == "レーベの小部屋1"


def test_再起動しても同じ仮名(tmp_path):
    """★保存 → 読み直しで変わらない（⚠ 番号の付け直しをしない）。"""
    book = _in_town(tmp_path)
    book.enter(200)
    book.enter(9)
    book.enter(201)
    book.save(force=True)

    again = LB.LocationBook.load(path=tmp_path / "book.json",
                                 rom_place_name=lambda m: None,
                                 heard_place_name=lambda m: None)
    assert again.locations["L200"].display_name == "レーベの小部屋1"
    assert again.locations["L201"].display_name == "レーベの小部屋2"
    assert again.enter(200)["name"] == "レーベの小部屋1"


def test_近辺や小部屋を付け直さない(tmp_path):
    """⚠⚠ `_needs_rename` は**座標が要る付け方**だけを直す（RX3-0122）。

    ★小部屋・近辺は世界座標を使っていないので、⚠ 座標が無くても正しい名前です。
    ⚠ ここを一緒に消すと、★入るたびに名前が変わります。
    """
    book = _in_town(tmp_path)
    book.enter(200)
    book.locations["L200"].world_x = None
    assert book._needs_rename(book.locations["L200"]) is False
    assert book.enter(200)["name"] == "レーベの小部屋1"


def test_正式名が分かれば昇格する(tmp_path):
    book = _in_town(tmp_path)
    book.enter(200)
    assert book.locations["L200"].display_name == "レーベの小部屋1"
    assert book.promote("L200", "ナジミの塔", source="dialogue") is True
    assert book.locations["L200"].display_name == "ナジミの塔"
    assert book.locations["L200"].name_source == "dialogue"
    # ⚠ 過去のメモが指す location_id は変えない（★繋がりが切れる）
    assert "L200" in book.locations


def test_同じ場所に仮名を大量生成しない(tmp_path):
    """⚠ 同じ location_id は 1 つの名前しか持たない（★map が増えても）。"""
    book = _in_town(tmp_path)
    book.enter(200)
    names = {book.enter(200)["name"] for _ in range(5)}
    assert names == {"レーベの小部屋1"}


def test_古い記録も読める(tmp_path):
    """⚠ `name_rule` の無い記録（★RX3-0122 より前）を読んでも落ちない。"""
    (tmp_path / "book.json").write_text(json.dumps({
        "game": "dq3", "last_world": None, "visit_order": ["L9"],
        "locations": {"L9": {"location_id": "L9", "display_name": "レーベ",
                             "name_source": "dialogue", "visited": True}},
    }, ensure_ascii=False), encoding="utf-8")
    book = LB.LocationBook.load(path=tmp_path / "book.json",
                                rom_place_name=lambda m: None,
                                heard_place_name=lambda m: None)
    assert book.locations["L9"].name_rule == ""
    assert book.locations["L9"].display_name == "レーベ"
# ======================================================================
# ★★ 町のたぐいか（RX3-0355 / 2026-09-21）
#
#   ⚠⚠ 依頼者「特にダンジョンはこの機能は一旦凍結させたい」（★自動移動の [入]）。
#     ★「分からない」は false（⚠ 推測で町だと決めない / 安全側）。
# ======================================================================
def test_町なら町のたぐい(tmp_path):
    book = _in_town(tmp_path)
    assert book.is_town_like(9) is True


def test_城と村も町のたぐい(tmp_path):
    book = _in_town(tmp_path)
    for kind in ("castle", "village"):
        book.locations["L9"].location_type = kind
        assert book.is_town_like(9) is True, kind


def test_塔や洞窟は町のたぐいでない(tmp_path):
    book = _in_town(tmp_path)
    for kind in ("cave", "tower", "shrine", "dungeon"):
        book.locations["L9"].location_type = kind
        assert book.is_town_like(9) is False, kind


def test_ROMの地名は町のたぐい(tmp_path):
    """★ルーラの行き先は町だけ（⚠ 種別が空でも分かる）。"""
    book = _in_town(tmp_path)
    book.locations["L9"].location_type = ""
    book.locations["L9"].name_source = "rom"
    assert book.is_town_like(9) is True


def test_名前が塔なら町のたぐいでない(tmp_path):
    book = _in_town(tmp_path)
    book.locations["L9"].location_type = ""
    book.locations["L9"].name_source = "dialogue"
    book.locations["L9"].display_name = "ナジミの塔"
    assert book.is_town_like(9) is False


def test_分からなければ町のたぐいでない(tmp_path):
    """⚠⚠ ここが肝心（★推測しない / 安全側）。"""
    book = _in_town(tmp_path)
    book.locations["L9"].location_type = ""
    book.locations["L9"].name_source = "provisional"
    book.locations["L9"].display_name = "アリアハン北西の場所"
    assert book.is_town_like(9) is False
    # ⚠ 知らない map も false
    assert book.is_town_like(9999) is False

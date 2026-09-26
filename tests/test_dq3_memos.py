"""ゆうしゃメモ V0（RX3-0016 / 2026-08-30）。

依頼者の指示書:

    勇者メモをUI専用の文字列配列として実装しない。

        ゲーム中に得た知識 → Memo → Player Knowledge / ViewModel → 表示

    world-model.json のROM上の正解を直接Memoへ流し込まない。
    勇者メモはあくまでプレイヤーが実際に得た情報の記録とする。
"""

from __future__ import annotations

import dataclasses
import io
import json
import pathlib

import pytest

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def store(tmp_path):
    from dq3.knowledge.memos import MemoStore

    return MemoStore(tmp_path / "memos.jsonl")


@pytest.fixture()
def vm(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps(
        {"loc_kind": 1, "map_id": 9, "map_x": 3, "map_y": 4}),
        encoding="utf-8")
    return Dq3ViewModel(state_path=state,
                        knowledge_path=tmp_path / "k.json",
                        memo_path=tmp_path / "memos.jsonl")


# --- ★1 メモ 1 行の追記 ------------------------------------------------------

def test_1メモ1行で残る(store):
    store.add("王に会った", location_id="L1", map_id=1, source="discovery")
    store.add("北に洞窟があるらしい", location_id="L1", map_id=1)

    lines = [one for one in
             store.path.read_text(encoding="utf-8").splitlines() if one.strip()]
    assert len(lines) == 2, "⚠ 1 メモ 1 行になっていない"
    for one in lines:
        got = json.loads(one)
        assert set(got) >= {"order", "text", "location_id", "map_id",
                            "source", "raw_digest"}


def test_読み直せる(store):
    from dq3.knowledge.memos import MemoStore

    store.add("あ", location_id="L1")
    store.add("い", location_id="L2")

    again = MemoStore(store.path)
    assert [m.text for m in again] == ["あ", "い"]
    assert again.failed == 0


def test_壊れた行があっても残りは読める(store):
    from dq3.knowledge.memos import MemoStore

    store.add("生きている記録", location_id="L1")
    with io.open(store.path, "a", encoding="utf-8", newline="") as fh:
        fh.write("{ これは JSON ではない\n")
        fh.write(json.dumps({"order": 9, "text": "その後の記録"},
                            ensure_ascii=False) + "\n")

    again = MemoStore(store.path)
    assert [m.text for m in again] == ["生きている記録", "その後の記録"]
    # ⚠⚠ 黙って捨てない。★何件落としたかが分かること
    assert again.failed == 1 and again.last_error


def test_記録が無くても始められる(tmp_path):
    from dq3.knowledge.memos import MemoStore

    got = MemoStore(tmp_path / "まだ無い.jsonl")
    assert len(got) == 0 and got.failed == 0


def test_書けなくても落ちない(tmp_path):
    from dq3.knowledge.memos import MemoStore

    blocked = tmp_path / "ふさがれている"
    blocked.write_text("★これはフォルダではない", encoding="utf-8")
    got = MemoStore(blocked / "memos.jsonl")
    made = got.add("残らないメモ")

    assert made is not None, "⚠ 画面には出るべき"
    assert got.failed == 1 and got.last_error, "⚠⚠ 残らなかったことが分からない"


# --- ★order は単調（⚠ 巻き戻しても壊れない）--------------------------------

def test_orderが単調に増える(store):
    made = [store.add("%d 件目" % i) for i in range(5)]
    assert [m.order for m in made] == [1, 2, 3, 4, 5]


def test_読み直しても番号が続く(store):
    from dq3.knowledge.memos import MemoStore

    store.add("あ")
    store.add("い")

    again = MemoStore(store.path)
    assert again.add("う").order == 3, "⚠⚠ 番号が巻き戻った"


def test_時刻を並びの正本にしていない():
    """⚠⚠ 依頼者の指示: 「実時刻やゲーム内時刻を並び順の正本にしない」。

    ★セーブステートを戻すとゲーム内時刻は戻りますが、
    ⚠ 勇者メモの記録順が戻ってはいけません。

    ## ⚠ 2026-09-10（RX3-0148）に**見張り方を変えました**

      ★もとは `memos.py` から `datetime` を**丸ごと禁止**していました。
      ⚠ ですが冒険ログのために「いつ書いたか」（`at`）が要ります。
      → ★禁じるのは**並びに使うこと**であって、時刻を持つこと自体ではない。
      ⚠⚠ そこで「並びを決める 2 か所」を名指しで見ます。
    """
    src = (ROOT / "dq3" / "knowledge" / "memos.py").read_text(encoding="utf-8")

    # ① ★次の番号は、時刻から作らない
    body = src.split("def next_order")[1].split("\n    def ")[0]
    for banned in ("time.time", "datetime", "os.times", "self.at", "_now"):
        assert banned not in body, "⚠⚠ 番号を時刻から作っている: %s" % banned
    assert "max((m.order" in body, "⚠ `order` の最大から作っていない"

    # ② ★読み直しの並べ替えは `order`
    body = src.split("def reload")[1].split("\n    def ")[0]
    assert "key=lambda m: m.order" in body, "⚠⚠ 並べ替えが `order` でない"
    assert ".at" not in body, "⚠⚠ 時刻で並べている"

    # ③ ★一覧の並べ替え（`MemoBook`）も `order`
    models = (ROOT / "dq3" / "ui" / "models.py").read_text(encoding="utf-8")
    body = models.split("def newest")[1].split("\n    def ")[0]
    assert "key=lambda m: m.order" in body, "⚠⚠ 一覧が `order` で並んでいない"


def test_書いた時刻が残る(store):
    """★冒険ログのために「いつ書いたか」を持つ（RX3-0148）。⚠ 並びには使わない。"""
    import datetime as _dt

    from dq3.knowledge.memos import MemoStore

    got = store.add("あ")
    assert got.at, "⚠ 時刻が入っていない"
    # ★ISO8601 として読めること（⚠ 文字列を目で見て決めない）
    _dt.datetime.fromisoformat(got.at)
    # ★書き戻して読み直しても残る
    again = MemoStore(store.path)
    assert again.recent(1)[0].at == got.at


def test_昔の行に時刻が無くても読める(tmp_path):
    """⚠⚠ 既存の記録は `at` を持ちません（★2026-09-10 より前の 80 件）。"""
    from dq3.knowledge.memos import MemoStore

    path = tmp_path / "memos.jsonl"
    path.write_text(json.dumps({"order": 1, "text": "むかしの行"},
                               ensure_ascii=False) + "\n", encoding="utf-8")
    store = MemoStore(path)
    assert store.failed == 0, "⚠ 昔の行を読み落とした"
    assert store.recent(1)[0].at is None, "⚠ 無いのに埋めている"


# --- ★逆引き ----------------------------------------------------------------

def test_逆引きが3つとも引ける(store):
    store.add("あ", location_id="L1", map_id=1)
    store.add("い", location_id="L2", map_id=2)
    store.add("う", location_id="L1", map_id=1)

    assert [m.text for m in store.recent(2)] == ["う", "い"]
    assert [m.text for m in store.of_location("L1")] == ["あ", "う"]
    assert [m.text for m in store.of_map(2)] == ["い"]


def test_将来の欄は保つが埋めない(store):
    """⚠ 依頼者の指示: 「npc_id / item_id / event_id は将来拡張用として
    保持するが、★今回無理に値を埋めない」。"""
    made = store.add("あ", location_id="L1")
    assert made.npc_id is None and made.item_id is None
    assert made.event_id is None
    # ★引ける形だけは先にある
    assert store.book().of_npc("x") == []
    assert store.book().of_item("y") == []


# --- ⚠ 同じものを二度書かない ------------------------------------------------

def test_同じ会話を二度書かない(store):
    """⚠⚠ 画面を見て記録するので、★同じ窓が出ているあいだ何度も読む。"""
    first = store.add_if_new("北に洞窟", location_id="L1", raw_digest="abc")
    again = store.add_if_new("北に洞窟", location_id="L1", raw_digest="abc")

    assert first is not None and again is None
    assert len(store) == 1


def test_生タイルが1ドット違っても二度書かない(store):
    """★★ 2026-08-31 実機で踏んだ形（`memos.jsonl` の 16 / 17）。 ★★

    ⚠ ▼ の点滅などで生タイルは変わるので、`raw_digest` だけを鍵にすると
    **同じ文がもう 1 件入ります**。★文と地点が同じなら足さない。
    """
    line = "＊「まちのそとを あるくとき  あやしげな ばしょには  なにか あるかも しれぬ。"
    first = store.add_if_new(line, location_id="L9", raw_digest="2a95c393c606be93")
    again = store.add_if_new(line, location_id="L9", raw_digest="8c0403bcba6c6940")

    assert first is not None
    assert again is None, "⚠⚠ 生タイルが違うだけで同じ文が 2 件入っています"
    assert len(store) == 1


def test_地点が違えば別のメモ(store):
    store.add_if_new("同じ言葉", location_id="L1")
    store.add_if_new("同じ言葉", location_id="L2")
    assert len(store) == 2


# --- ⚠⚠ 昔の記録の移行 -------------------------------------------------------

def test_昔の記録を一度だけ移す(vm, tmp_path):
    """⚠⚠ 「両方を見る」にすると `order` が衝突しました（★実際に踏んだ）。"""
    (tmp_path / "k.json").write_text(json.dumps({"memos": [
        {"order": 5, "text": "昔のメモ B", "location_id": "L9"},
        {"order": 2, "text": "昔のメモ A", "location_id": "L9"}]}),
        encoding="utf-8")
    vm.reload_knowledge()

    got = [(m.order, m.text) for m in vm.memos]
    assert got == [(1, "昔のメモ A"), (2, "昔のメモ B")], (
        "⚠ 元の順が保たれていない: %s" % got)

    vm.reload_knowledge()
    assert len(vm.memos) == 2, "⚠⚠ 二度移している"


def test_移行しても番号は衝突しない(vm, tmp_path):
    (tmp_path / "k.json").write_text(
        json.dumps({"memos": [{"order": 1, "text": "昔"}]}), encoding="utf-8")
    vm.reload_knowledge()
    vm.add_memo("いま", source="manual")

    orders = [m.order for m in vm.memos]
    assert len(orders) == len(set(orders)), "⚠⚠ 番号が重なった: %s" % orders


# --- ★ViewModel を通す（⚠ 画面から直接 store を触らせない）------------------

def test_いまの居場所が補われる(vm):
    made = vm.add_memo("井戸の底に何かある", source="discovery")
    assert made.location_id == "L9" and made.map_id == 9


def test_はじめての場所は1回だけ記録される(vm):
    first = vm.note_here()
    assert first is not None and first.source == "discovery"
    assert vm.note_here() is None, "⚠ 同じ場所で二度記録している"
    assert vm.known_locations() == ["L9"]


def test_世界地図では地点にしない(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"loc_kind": 0, "map_x": 30, "map_y": 40}),
                     encoding="utf-8")
    got = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                       memo_path=tmp_path / "memos.jsonl")
    assert got.note_here() is None, "⚠ 世界地図を地点として記録している"


def test_訪れた場所が残る(vm, tmp_path):
    """⚠⚠ **`visited_locations` を書く人が誰もいませんでした。**

    ★読む所しかなく、地点情報は永遠に「？」のままでした。
    ⚠ エラーは出ず、「一度も出ない」という顔で出ます。
    """
    from dq3.ui.view_model import Dq3ViewModel

    vm.note_here()
    body = json.loads((tmp_path / "k.json").read_text(encoding="utf-8"))
    assert body["visited_locations"] == ["L9"]

    again = Dq3ViewModel(state_path=vm.state_path,
                         knowledge_path=tmp_path / "k.json",
                         memo_path=tmp_path / "memos.jsonl")
    assert again.known_locations() == ["L9"]


def test_同じ場所の別の階ではメモを増やさない(tmp_path):
    """⚠⚠ RX3-0080 §14: ★発見は **location_id** で数える。

    ⚠ `map_id` で数えると、アリアハン城の 1F → 2F → B1 と歩くだけで
      「新しい場所を見つけた」が 3 件出ます。
    """
    import json as _json

    from dq3.knowledge import location_book as LB
    from dq3.knowledge import location_master as LM
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"

    def go(map_id):
        state.write_text(_json.dumps({"loc_kind": 1, "map_id": map_id,
                                      "map_x": 3, "map_y": 4}), encoding="utf-8")

    master = LM.LocationMaster({m: LM.Row(map_id=m, location_id="castle") for m in (12, 13, 14)})
    go(12)
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "memos.jsonl")
    vm._location_book = LB.LocationBook(master, tmp_path / "book.json")

    assert vm.note_here() is not None, "★はじめての場所ではメモが出る"
    for map_id in (13, 14, 12):
        go(map_id)
        assert vm.note_here() is None, "⚠⚠ 階を移っただけでメモが増えた（map %d）" % map_id
    assert len([m for m in vm.memos if m.source == "discovery"]) == 1
    # ★別の場所なら、ちゃんと増える
    go(99)
    assert vm.note_here() is not None


def test_はじめての場所のメモに名前が入る(tmp_path):
    """★仮名でも名前で書く（⚠ ROM から引いた正式名ではない / No-Spoiler）。"""
    import json as _json

    from dq3.knowledge import location_book as LB
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(_json.dumps({"loc_kind": 1, "map_id": 9, "map_x": 1, "map_y": 1}),
                     encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "memos.jsonl")
    # ⚠ ここで見たいのは**メモの文**なので、★ROM の地名は使わない（RX3-0092）
    book = vm._location_book = LB.LocationBook(None, tmp_path / "book.json",
                                               lambda map_id: None)
    book.note_world(160, 195)
    book.enter(9)
    book.promote("L9", "レーベ", source="dialogue")

    state.write_text(_json.dumps({"loc_kind": 0, "map_x": 150, "map_y": 185}), encoding="utf-8")
    assert vm.note_here() is None                     # ★世界地図では地点にしない
    state.write_text(_json.dumps({"loc_kind": 1, "map_id": 41, "map_x": 2, "map_y": 2}),
                     encoding="utf-8")
    made = vm.note_here()
    assert made is not None and made.text == "レーベ北西の場所を見つけた"
    assert made.location_id == "L41"


def test_場所の升はLuaが毎フレーム見た入口と出口の升(tmp_path):
    """★RX3-0275（依頼者「ここのmapに◯があるが、何もない」）。

    ⚠ 0.5 秒おきに読む位置は、町へ入る 1 歩手前 (85,110)。★Lua が毎フレーム見た入口・出口の升 (86,110) を使う。
    """
    import json as _json

    from dq3.knowledge import location_book as LB
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"

    def put(**kw):
        state.write_text(_json.dumps(kw), encoding="utf-8")

    put(loc_kind=0, map_x=85, map_y=110)
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "memos.jsonl")
    book = vm._location_book = LB.LocationBook(None, tmp_path / "book.json", lambda map_id: None)
    assert vm.note_here() is None                     # ⚠ 読めたのは町の 1 歩手前
    put(loc_kind=1, map_id=12, map_x=16, map_y=31, entry_x=86, entry_y=110)
    vm.note_here()
    loc = book.locations["L12"]
    assert (loc.world_x, loc.world_y) == (86, 110), "⚠⚠ 入口の升を使っていない"
    loc.world_x, loc.world_y = 85, 110                # ⚠ RX3-0275 より前の記録（1 歩手前）
    put(loc_kind=0, map_x=88, map_y=110, exit_x=86, exit_y=110)
    vm.note_here()
    assert (loc.world_x, loc.world_y) == (86, 110), "⚠⚠ 出口の升で直していない"


def test_地点情報にメモが出る(vm):
    vm.note_here()
    vm.add_memo("北に洞窟があるらしい", source="conversation")
    got = vm.location_view("L9")

    assert got.knowledge != "UNKNOWN"
    assert got.memo_count == 2
    assert "北に洞窟があるらしい" in got.highlights


def test_知らない地点の中身は出さない(vm):
    got = vm.location_view("L99")
    assert got.display_name == "？"
    assert got.memo_count == 0 and got.highlights == []


# --- ⚠⚠ ROM の正解を流し込んでいないか ---------------------------------------

def test_地名をメモに書いていない():
    """⚠⚠ 依頼者の指示: 「world-model.json の ROM 上の正解を直接 Memo へ
    流し込まない」。

    ★DQ3 の ROM に地名の平文は無く（`RX3-0013`）、⚠ 訪れただけでは
    名前は分かりません。★ここで ROM から引くと No-Spoiler が崩れます。
    """
    src = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    i = src.index("def note_here")
    j = src.index("def save_knowledge")
    body = src[i:j]
    for banned in ("world_model", "world-model", "location_names["):
        assert banned not in body, "⚠⚠ ROM の正解を引いている: %s" % banned


def test_メモは文字列の配列ではない():
    """⚠⚠ 依頼者の指示: 「UI 専用の文字列配列として実装しない」。"""
    from dq3.ui.models import Memo

    fields = {f.name for f in dataclasses.fields(Memo)}
    assert {"order", "text", "location_id", "map_id", "source",
            "raw_digest"} <= fields
    assert {"npc_id", "item_id", "event_id"} <= fields


def test_画面が直接storeを触っていない():
    """★補う場所を 1 つにする（⚠ 窓ごとに違う地点が入らないように）。"""
    guilty = []
    for path in sorted((ROOT / "dq3" / "ui").glob("*.py")):
        if path.name == "view_model.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "MemoStore" in text:
            guilty.append(path.name)
    assert not guilty, "⚠⚠ 画面が直接 MemoStore を触っている: %s" % guilty


# --- ⚠ 呼ばれているか（★「誰も書かない」を二度と作らない）-------------------

def test_画面の定期処理がnote_hereを呼んでいる():
    """⚠⚠ **実装があっても、呼ばれていなければ意味がありません。**

    ★`visited_locations` はまさにその形で、⚠ **1 度も書かれて
    いませんでした**。
    """
    src = (ROOT / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    i = src.index("def refresh")
    j = src.index("    def ", i + 10)
    assert "note_here" in src[i:j], "⚠⚠ 定期処理から呼ばれていない"


# --- ★会話を画面から拾う（⚠ 実機では未確認）--------------------------------

# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()

from dq3_states import (BATTLE, BATTLE_COMMAND, CONVERSATION,
                        FIELD, kinds_of, one, pick)


def _screen_hex(slot=None) -> str:
    """★実機の画面を 16 進で。

    ⚠⚠ **番号で名指ししない**（RX3-0028 / 2026-08-31）。
      ★依頼者はセーブ 5〜9 を作業用に使うので、⚠ 撮り直した瞬間に落ちる
      （実際に 10 件落ちた）。→ ★中身で選ぶ。
    """
    path = pathlib.Path(slot) if slot else one(CONVERSATION)
    if not path.is_absolute():
        path = FCS / path
    if not path.exists():
        pytest.skip("⚠ セーブステートが無い環境")
    from dq3rom import ppu
    from retroux.core.bgmap.savestate import load

    st = load(path)
    return "".join("%02X" % (t & 0xFF) for t in ppu.screen_of(st.chunks))


def _tiles(slot=None):
    raw = _screen_hex(slot)
    return [int(raw[i:i + 2], 16) for i in range(0, len(raw), 2)]


def test_実機の画面から窓が見つかる():
    """⚠⚠ 「0 件」を合格にしない。★本当に読めていることを見る。"""
    from dq3.knowledge import conversation as cv

    got = cv.windows_on_screen(_tiles())
    assert len(got) >= 2, "⚠⚠ 窓が見つかっていない（★読めていないだけかも）"
    for text, digest in got:
        assert text and len(digest) == 16


def test_文字表が読めないことは黙らない(monkeypatch):
    """⚠⚠ ここで黙って空を返して、1 度やられました。

    ★profile の場所を間違えていたとき、「窓 0 件」に見えるだけで、
    ⚠ **一度も読めていません**でした。
    """
    from dq3.knowledge import conversation as cv

    # ⚠⚠ **壊す前に画面を取っておく。**
    #   ★セーブの選び方（`dq3_states`）自身が文字表を使うので、
    #   ⚠ 先に壊すと「会話のセーブが 0 本」で落ちる（★実際に踏んだ）。
    tiles = _tiles()
    monkeypatch.setattr(cv, "PROFILE", ROOT / "まだ無い.json")
    assert cv.windows_on_screen(tiles) == []
    assert cv.charset_error, "⚠⚠ 読めなかった理由が残っていない"


def test_パーティの状態は会話にしない():
    """★依頼者のセーブ 8 本すべてで、いちばん上はこの窓でした。

        H27H21H22H14M9M0M15M1ゆ：4せ：5そ：5ま：5
    """
    from dq3.knowledge import conversation as cv

    quiet = [p for p in pick(FIELD) if CONVERSATION not in kinds_of(p)]
    assert quiet, "⚠⚠ 会話していない町/野外のセーブが 1 本も無い"
    for path in quiet:
        got = cv.conversation_on_screen(_tiles(path))
        assert got is None, "⚠ 状態の窓を会話にしている（%s）: %r" % (
            path.name, got)


# --- ★★ 実機の会話（RX3-0016 / 2026-08-31）--------------------------------
#
#   ⚠⚠ ここは長らく「会話中のセーブが 1 本も無いので確かめられない」と
#     書いてありました。★それは**誤り**でした（`fc9` は 2026-08-26 から
#     会話中で、`test_dq3_ppu.py` が既にそれで検査していました）。
#
#   ★2026-08-31 に依頼者が 2 本撮ってくれました:
#     ・継続行（▼）**なし**
#     ・継続行（▼）**あり**
#   ⚠ どちらでも同じように拾えることを、ここで見ます。


def test_実機の会話を拾える():
    """★会話の窓から、文が取れること。"""
    from dq3.knowledge import conversation as cv

    for path in pick(CONVERSATION):
        got = cv.conversation_on_screen(_tiles(path))
        assert got is not None, "⚠⚠ 会話を拾えていない: %s" % path.name
        text, digest = got
        assert len(digest) == 16
        assert "＊「" in text, "⚠ 会話の始まりが無い（%s）: %r" % (path.name, text)
        assert len(text) >= 10, "⚠ 短すぎる（%s）: %r" % (path.name, text)


def test_濁点の行が本文に混ざらない():
    """⚠⚠ **2026-08-31 に実機で踏んだ**（RX3-0016）。

    ★濁点は 1 行上の別のマスにあります。下の字へ合成したあと、
    ⚠ その行自体を本文として出してはいけません。

        ⚠ 「゛＊「レーベのむらに ようこそ。」
        ⚠ 「まちのそとを あるくとき゛゛あやしげな…」

    ⚠⚠ `dq3rom/window.py::text_of` は最初からこれを落としていました。
      ★`conversation.py` が**同じ判定を書き直して**間違えていたのです
      （`docs/50-playbook.md` の「同じ判定を 2 か所に書かない」）。
    """
    from dq3.knowledge import conversation as cv

    for path in pick(CONVERSATION):
        text, _ = cv.conversation_on_screen(_tiles(path))
        assert "゛" not in text, "⚠ 濁点が本文に混ざった（%s）: %r" % (
            path.name, text)
        assert "゜" not in text, path.name


def test_継続行の矢印は本文に入れない():
    """⚠ `▼` は「まだ続きがある」という**操作の合図**で、文ではありません。

    ★依頼者が「継続行あり」「なし」の 2 本を撮ってくれました（2026-08-31）。
    ⚠ 入れると「…かもしれぬ。▼」がそのままメモに残ります。
    """
    from dq3.knowledge import conversation as cv
    from dq3rom.screen import PATTERN_BASE

    MORE = 0x173 - PATTERN_BASE
    withs = [p for p in pick(CONVERSATION) if MORE in _tiles(p)]
    assert withs, "⚠⚠ 継続行（▼）のある会話のセーブが 1 本も無い（★空回り）"
    for path in withs:
        text, _ = cv.conversation_on_screen(_tiles(path))
        assert "▼" not in text, "⚠ 矢印が本文に入った（%s）: %r" % (
            path.name, text)


def _state_like_dev(path):
    """★`dev.lua` が書くのと**同じ形**の `state.json` を、セーブから作る。

    ⚠⚠ 形を自分で決めないこと。★`dev.lua` の `where()` をそのまま写します
    （`loc_kind` / `map_id` / `map_x` / `map_y` / `map_w` / `map_h` / `screen`）。
    ⚠ ここがずれると「両端は正しいのに橋渡しが落とす」形になります。
    """
    import json as _json

    from dq3rom import ppu
    from retroux.core.bgmap.savestate import load

    prof = _json.loads(
        (ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
        .read_text(encoding="utf-8"))
    loc = prof["runtime"]["location"]
    addr = {k: int(str(v), 16) for k, v in loc.items()
            if isinstance(v, str) and v.startswith("0x")}

    st = load(path)
    ram = st.ram
    kind = ram[addr["kind"]]
    from dq3 import battle_state as BS             # ★DQ3 自身の式（RX3-0166 / ⚠ $62 ではない）

    out = {"loc_kind": kind,
           "in_battle": BS.of_memory(ram, st.chunks.get("WRAM", b""))["in_battle"],
           "screen": "".join("%02X" % (t & 0xFF)
                             for t in ppu.screen_of(st.chunks))}
    if kind == 1:
        out["map_id"] = ram[addr["map_no"]]
        out["map_x"] = ram[addr["local_x"]]
        out["map_y"] = ram[addr["local_y"]]
        out["map_w"] = ram[addr["map_width"]]
        out["map_h"] = ram[addr["map_height"]]
    else:
        out["map_x"] = ram[addr["world_x"]]
        out["map_y"] = ram[addr["world_y"]]
    return out


def test_会話が残って地点から引ける(tmp_path):
    """★★ ⚠⚠ **端から端まで**（RX3-0016 / 2026-08-31）。

        実機のセーブ → `state.json`（`dev.lua` と同じ形）
            → `note_conversation()` → `memos.jsonl`
            → **読み直して** → 地点・地図から引ける

    ⚠ 依頼者が外出中で実機を触れないので、★セーブステートで詰めます。
      実機が足すのは FCEUX の入力と PPU だけで、⚠ **この道筋は同じ**です。
    """
    from dq3.ui.view_model import Dq3ViewModel

    path = one(CONVERSATION)
    raw = _state_like_dev(path)
    assert raw["loc_kind"] == 1 and raw.get("map_id") is not None, (
        "⚠ 町のセーブではない: %s" % path.name)

    state = tmp_path / "state.json"
    state.write_text(json.dumps(raw), encoding="utf-8")
    memo_path = tmp_path / "memos.jsonl"
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=memo_path, seen_path=tmp_path / "seen.json")

    # ⚠ 窓が出ているうちは書きません（★2026-08-31）。★閉じて確定させる
    assert vm.note_conversation() is None
    made = vm.flush_conversation()
    assert made is not None, "⚠⚠ 会話を拾えていない: %s" % path.name
    assert made.source == "conversation"
    assert made.raw_digest, "⚠⚠ 生タイルへ戻れない（★文字表を直せない）"
    # ★居場所が付いていること（⚠ 付かないと「どこの話か」が消える）
    assert made.map_id == raw["map_id"], (made.map_id, raw["map_id"])
    assert made.location_id == "L%d" % raw["map_id"], made.location_id

    # ⚠⚠ **読み直せること。** ★書けただけでは「残った」と言えない
    assert memo_path.exists(), "⚠ 置き場に書かれていない"
    again = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k2.json",
                         memo_path=memo_path, seen_path=tmp_path / "seen2.json")
    assert again.memo_failures == 0, "⚠ 読めなかった行がある"

    by_map = again.memos.of_map(raw["map_id"])
    assert [m.text for m in by_map] == [made.text], "⚠ 地図から引けない"
    by_loc = again.memos.of_location("L%d" % raw["map_id"])
    assert [m.text for m in by_loc] == [made.text], "⚠ 地点から引けない"
    assert again.recent_memos(5)[0].text == made.text, "⚠ 直近に出ない"


def test_別の地図のメモは混ざらない(tmp_path):
    """⚠ 「どこの話か」が効いていること（★引くときに混ざらない）。"""
    from dq3.ui.view_model import Dq3ViewModel

    raw = _state_like_dev(one(CONVERSATION))
    state = tmp_path / "state.json"
    state.write_text(json.dumps(raw), encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl",
                      seen_path=tmp_path / "seen.json")
    vm.note_conversation()
    here = vm.flush_conversation()
    assert here is not None, "⚠ 会話を拾えていない"
    other = raw["map_id"] + 1
    vm.add_memo("よその地図で聞いた話", source="conversation",
                location_id="L%d" % other, map_id=other)

    got = vm.memos.of_map(raw["map_id"])
    assert [m.text for m in got] == [here.text], (
        "⚠⚠ よその地図のメモが混ざった: %r" % ([m.text for m in got],))


def test_選ぶ窓は会話にしない():
    """⚠ 「▶ホイミ」のような一覧を拾うと、★メモが呪文名で埋まる。"""
    from dq3.knowledge import conversation as cv

    for path in pick(BATTLE):
        if BATTLE_COMMAND in kinds_of(path):
            continue          # ★コマンド窓は別の検査で見る
        got = cv.conversation_on_screen(_tiles(path))
        assert got is None, "⚠ 選ぶ窓を会話にしている（%s）: %r" % (
            path.name, got)


def test_戦っている間は会話を拾わない(tmp_path):
    """⚠⚠ 戦闘中の窓まで拾うと、★メモが「スライムー1ひき」で埋まる。"""
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps(
        {"loc_kind": 1, "map_id": 9, "in_battle": True,
         "screen": _screen_hex()}), encoding="utf-8")
    got = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                       memo_path=tmp_path / "m.jsonl",
                          seen_path=tmp_path / "seen.json")
    assert got.note_conversation() is None


def test_同じ窓は二度書かない(tmp_path):
    """★窓は出ているあいだ何フレームも同じ（⚠ 生タイルの指紋で見分ける）。"""
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps(
        {"loc_kind": 1, "map_id": 9, "in_battle": False,
         "screen": _screen_hex()}), encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl",
                          seen_path=tmp_path / "seen.json")

    # ⚠⚠ 2026-08-31: **窓が閉じてから書きます**（★流れ込む途中で足さない）
    assert vm.note_conversation() is None, "⚠ 窓が出ているうちに書いている"
    assert vm.note_conversation() is None, "⚠ 同じ窓で 2 度目も書かない"
    # ★窓が消えた（画面が届かない）ら、そこで書く
    state.write_text(json.dumps({"loc_kind": 1, "map_id": 9,
                                 "in_battle": False}), encoding="utf-8")
    vm._raw.cache_clear() if hasattr(vm._raw, "cache_clear") else None
    made = vm.note_conversation()
    assert made is not None and made.source == "conversation", (
        "⚠⚠ 窓が閉じても書かれていない")
    assert vm.note_conversation() is None, "⚠ 二度書いた"


def test_画面が届いていなくても落ちない(tmp_path):
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"loc_kind": 1, "map_id": 9}),
                     encoding="utf-8")
    got = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                       memo_path=tmp_path / "m.jsonl",
                          seen_path=tmp_path / "seen.json")
    assert got.note_conversation() is None


def test_窓の切り出しを2か所に書いていない():
    """⚠⚠ 「同じ判定を 2 か所に書いて片方だけ直っていた」を繰り返さない。

    ★どこからどこまでが窓かは `dq3rom/window.py` だけが決めます。
    """
    src = (ROOT / "dq3" / "knowledge"
           / "conversation.py").read_text(encoding="utf-8")
    code = "\n".join(one for one in src.splitlines()
                     if not one.lstrip().startswith("#"))
    for banned in ("TOP_LEFT", "EDGE_TOP", "0x79", "0x7C"):
        assert banned not in code, "⚠⚠ 枠のタイルを持っている: %s" % banned


def test_Luaは窓の切り出しをしない():
    """★Lua がやるのは「窓があるか」の安い見分けだけ。"""
    dev = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "has_window" in dev
    # ⚠ 枠のタイル番号を Lua に直書きしていないこと
    for banned in ("0x79", "0x7C", "121", "124"):
        assert ("WIN.top_left" in dev) or (banned not in dev)
    assert "CFG.window" in dev, "★設定から受け取っていない"


# --- ★地図の一覧とメモの接続（RX3-0024 × RX3-0016）--------------------------

def test_地図を選ぶとその地図のメモが出る(tmp_path):
    """⚠⚠ 繋がっていませんでした。

    ★地図を選んでも、下に出るのは**全体の直近メモ**でした。
    ⚠ `RX3-0024` の「その地図のメモが下に出る」は、
      `RX3-0016` 待ちのまま**実は誰も繋いでいません**でした。
    """
    pytest.importorskip("PySide6")
    from dq3.ui.map_browser import Dq3MapBrowser
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"loc_kind": 1, "map_id": 9}),
                     encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl",
                          seen_path=tmp_path / "seen.json")
    vm.add_memo("9 番の地図で聞いた話", source="conversation",
                location_id="L9", map_id=9)
    vm.add_memo("3 番の地図で聞いた話", source="conversation",
                location_id="L3", map_id=3)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    got = Dq3MapBrowser(vm)
    try:
        # ★選んでいないうちは全体の直近（⚠ 「まだありません」より親切）
        assert len(got._memos_here(5)) == 2

        got.model._at = (1, 9, 0, 0)          # ★9 番の地図を見ている
        here = got._memos_here(5)
        assert [m.text for m in here] == ["9 番の地図で聞いた話"], (
            "⚠⚠ その地図のメモになっていない: %s" % [m.text for m in here])

        got.model._at = (1, 3, 0, 0)
        assert [m.text for m in got._memos_here(5)] == ["3 番の地図で聞いた話"]
    finally:
        got.deleteLater()


def test_絞り込みの件数が出る(tmp_path):
    """⚠ 全体の件数を出すと、★「6 件」と出て 1 件しか並ばない。"""
    pytest.importorskip("PySide6")
    from dq3.ui.map_browser import Dq3MapBrowser
    from dq3.ui.view_model import Dq3ViewModel

    state = tmp_path / "state.json"
    state.write_text(json.dumps({"loc_kind": 1, "map_id": 9}),
                     encoding="utf-8")
    vm = Dq3ViewModel(state_path=state, knowledge_path=tmp_path / "k.json",
                      memo_path=tmp_path / "m.jsonl",
                          seen_path=tmp_path / "seen.json")
    for i in range(3):
        vm.add_memo("9 番 %d" % i, map_id=9, location_id="L9")
    vm.add_memo("3 番", map_id=3, location_id="L3")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    got = Dq3MapBrowser(vm)
    try:
        got.model._at = (1, 9, 0, 0)
        got.memos.refresh()
        assert got.memos._count.text() == "3 件", got.memos._count.text()
    finally:
        got.deleteLater()


def test_絞り込みは1か所が持っている():
    """⚠⚠ 「同じ判定を 2 か所に書いて片方だけ直っていた」を繰り返さない。

    ★絞り込みは `MemoBook` が持ちます。画面は「どれを呼ぶか」だけ。
    """
    src = (ROOT / "dq3" / "ui" / "map_browser.py").read_text(encoding="utf-8")
    i = src.index("def _memos_here")
    j = src.index("    def refresh", i)
    body = src[i:j]
    assert "self.vm.memos." in body, "★MemoBook に任せていない"
    for banned in ("m.map_id ==", "matches_location", "sorted("):
        assert banned not in body, "⚠⚠ 画面が絞り込み・並べ替えを持っている: %s" % banned


# --- ★★ 実機で出た断片（2026-08-31 / `memos.jsonl` の 20〜31）--------------
#
#   ⚠⚠ 依頼者の実機で、**同じ会話が 4 件**入りました。
#     ★ここは「その 4 件を並べたら 2 件になる」ことを見ます。

#: ★宿屋（⚠ 伸びていくだけ）
YADO = [
    "＊「こんにちは。  たびびとの やどに ようこそ。",
    "＊「こんにちは。  たびびとの やどに ようこそ。＊",
    "＊「こんにちは。  たびびとの やどに ようこそ。＊「ひとばん 8ゴールドですが  おとまりに なります",
]
#: ⚠⚠ 町の人（★途中で**窓が送られて頭が欠ける**）
MACHI = [
    "＊「まちのそとを あるくとき  あやしげな ばしょ",
    "＊「まちのそとを あるくとき  あやしげな ばしょには  なにか あるかも しれぬ。＊「とお",
    "あやしげな ばしょには  なにか あるかも しれぬ。＊「とおくから みるだけでなく  そのばしょま",
    "なにか あるかも しれぬ。＊「とおくから みるだけでなく  そのばしょまで いくことだな。",
]
#: ★岩を押す人（⚠ 伸びるだけ / 1 件になる）
IWA = [
    "＊「よいしょ よいしょ。  だめだ‥。おも",
    "＊「よいしょ よいしょ。  だめだ‥。おもくて おしても  びくとも しないや。",
]


def _joined(rows):
    from dq3.knowledge.conversation import join_continuation

    cur = rows[0]
    for row in rows[1:]:
        got = join_continuation(cur, row)
        assert got is not None, "⚠⚠ 続きだと分からなかった: %r" % row
        cur = got
    return cur


def test_送られて頭が欠けた続きも繋がる():
    """★★ ここが今回いちばん効く検査。 ★★

    ⚠ 「前のが新しい文の先頭か」だけだと、`MACHI` の 3 本目で切れます
    （★窓が送られて頭が欠けるため）。
    """
    from dq3.knowledge.conversation import tidy_message

    assert tidy_message(_joined(MACHI)) == (
        "＊「まちのそとを あるくとき  あやしげな ばしょには  なにか あるかも しれぬ。"
        "＊「とおくから みるだけでなく  そのばしょまで いくことだな。")


def test_継続行は1件にまとめる():
    """⚠⚠ 依頼者 2026-08-31「継続行の場合、別メッセージで扱われる」。

    ★`＊「` は**話し手が変わる印ではありません**。同じ人の続きにも付きます。
    """
    from dq3.knowledge.conversation import SPEECH_MARK, tidy_message

    got = tidy_message(_joined(YADO))
    assert got.count(SPEECH_MARK) == 2, "⚠ 材料が 2 台詞ぶんでない"
    assert got.startswith("＊「こんにちは。")
    assert got.endswith("なります")


def test_伸びるだけなら1件():
    from dq3.knowledge.conversation import tidy_message

    assert tidy_message(_joined(IWA)) == IWA[-1]


def test_別の会話は繋がない():
    """⚠ 何でも繋ぐと、★違う人の台詞が 1 件になります。"""
    from dq3.knowledge.conversation import join_continuation

    assert join_continuation(IWA[-1], MACHI[0]) is None


def test_短い重なりでは繋がない():
    """⚠ 「。」だけで繋ぐと、無関係な文がくっつきます。"""
    from dq3.knowledge.conversation import join_continuation

    assert join_continuation("＊「あいうえお。", "。かきくけこ") is None


def test_会話でない窓は記録しない():
    """⚠⚠ 実機でメモに入ってしまったもの（★2026-08-31）。

    ```text
    18 'あかり  ハンソロ  エルシト  ロミオ'   ⚠ パーティの名前の行
    23 'G  244'                              ⚠ ゴールドの窓
    ```
    """
    from dq3.knowledge import conversation as cv

    for bad in ("あかり  ハンソロ  エルシト  ロミオ", "G  244",
                "レーベの むら"):
        assert cv.SPEECH_MARK not in bad
    assert cv.SPEECH_MARK in YADO[0]


def test_頭の欠けた断片だけなら残さない():
    """⚠ 送られた後の姿だけを見たときに、★半端な文を残さない。"""
    from dq3.knowledge.conversation import tidy_message

    assert tidy_message("あやしげな ばしょには  なにか あるかも しれぬ。") == ""


def test_濁点が落ちた行は同じ行として扱う():
    """★★ ⚠⚠ 依頼者 2026-08-31「濁点を考慮できていない」。 ★★

    ★DQ3 は濁点を**1 行上の別のマス**に描きます。窓が折り返していると、
    同じ行が「濁点つき」と「濁点なし」で 2 度読めます。

    ```text
    ＊「まちのそとを あるくとき  あやしげな ばしょには  あやしけな はしょには …
                                 ^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^
    ```
    """
    from dq3.knowledge.conversation import _drop_repeats, base_form, richer

    rows = ["＊「まちのそとを あるくとき", "  あやしげな ばしょには",
            "  あやしけな はしょには", "  なにか あるかも しれぬ。"]
    assert "".join(_drop_repeats(rows)) == (
        "＊「まちのそとを あるくとき  あやしげな ばしょには  なにか あるかも しれぬ。")
    assert base_form("ばしょ") == base_form("はしょ")
    assert richer("はしょ", "ばしょ") == "ばしょ"


def test_濁点が落ちていても続きだと分かる():
    """⚠ 素で比べると「別の文」になり、★同じ行が 2 度入ります。"""
    from dq3.knowledge.conversation import join_continuation

    prev = "＊「まちのそとを あるくとき  あやしげな ばしょには"
    new = "あやしけな はしょには  なにか あるかも しれぬ。"
    got = join_continuation(prev, new)
    assert got is not None, "⚠⚠ 濁点が落ちただけで別の文にした"
    assert got == prev + "  なにか あるかも しれぬ。", got



# --- ★★ 文の長さで窓の幅を変えない（2026-08-31 / 依頼者）------------------

def test_長いメモでもメモ欄の幅が変わらない():
    """★★ ⚠⚠ 依頼者「メッセージが長いと MAP 画面の大きさが変わってしまう」

        > 基本は画面の大きさを内容で自動的に変えるのは NG
        > （ユーザーが調整した場合のみ）

    ⚠ `QLabel` は既定で「中身が収まる幅」を求めるので、★長いメモが
      入るたびに窓が横に伸びていました。

    ⚠⚠ ここでは**px の実測値を当てにしません**（★画面外のフォントは
      実機と違う / この計画で踏んだ形）。★「短い文のときと同じ」だけを見ます。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                # pragma: no cover
        pytest.skip("Qt が無い環境")
    app = QApplication.instance() or QApplication([])
    assert app is not None

    from dq3.ui.memo_panel import MemoPanel

    class _VM:
        def __init__(self):
            self.rows = []

        @property
        def memos(self):
            return self.rows

        def recent_memos(self, n):
            return self.rows[:n]

    from dq3.ui.models import Memo

    # ⚠ 偽のメモを作らない（★本物の `Memo` を使う / RX3-0118 で `line` が増えた）
    def _M(text):
        return Memo(order=1, text=text)

    vm = _VM()
    vm.rows = [_M("短い")]
    panel = MemoPanel(vm, limit=3)
    narrow = panel.sizeHint().width()

    vm.rows = [_M("＊「まちのそとを あるくとき  あやしげな ばしょには  "
                  "なにか あるかも しれぬ。＊「とおくから みるだけでなく  "
                  "そのばしょまで いくことだな。" * 3)]
    panel.refresh()
    wide = panel.sizeHint().width()

    assert wide == narrow, (
        "⚠⚠ 文が長いと欄が %d → %d px に広がっています（★窓が動きます）"
        % (narrow, wide))
    # ★全文はヒントで読めること（⚠ 切り捨てたままにしない）
    #   ⚠⚠ 話者は `＊` ではなく `？`（★RX3-0118。⚠ `＊` は会話開始記号）
    assert panel._rows[0].toolTip().startswith("？　まちのそとを")          # ★RX3-0253: 「」は出さない


def test_会話でない窓は実機のセーブでも拾わない():
    """★★ ⚠⚠ 実機でメモに入ってしまったもの（2026-08-31）。 ★★

    ```text
    18 'あかり  ハンソロ  エルシト  ロミオ'   ⚠ 仲間を選ぶ窓
    23 'G  244'                              ⚠ ゴールドの窓
    ```

    ## ⚠⚠ 「▶ で弾く」が効かなかった理由

      ★仲間を選ぶ窓は `▶あかり ハンソロ …` です。⚠ ですが **▶ は点滅する**
      ので、消えているフレームでは印が無く、そのまま通りました。
      （★この計画は「点滅するものは 1 枚で決めない」を既に踏んでいます）

      → ⚠ **無いもので弾く**のをやめ、★**会話の印があるものだけ拾う**に
        変えました（`SPEECH_MARK`）。
    """
    from dq3.knowledge import conversation as cv
    from dq3rom import ppu
    from retroux.core.bgmap.savestate import load

    states = sorted(FCS.glob("DQ3_J.fc[0-9]"))
    if not states:
        pytest.skip("⚠ セーブステートが無い環境")
    no_mark = talked = 0
    for path in states:
        tiles = [t & 0xFF for t in ppu.screen_of(load(path).chunks)]
        wins = cv.windows_on_screen(tiles)
        no_mark += sum(1 for text, _ in wins if cv.SPEECH_MARK not in text)
        got = cv.conversation_on_screen(tiles)
        if got is None:
            continue
        talked += 1
        assert cv.SPEECH_MARK in got[0], (
            "⚠⚠ 会話でない窓を拾った: %s / %r" % (path.name, got[0]))
    assert no_mark >= 5, (
        "⚠ 印の無い窓が %d 件しかない（★この検査は空回り）" % no_mark)
    assert talked >= 1, "⚠ 会話の窓が 1 つも無い（★この検査は空回り）"


def _fake_window(lines, *, dakuten_on=None, dakuten_at=()):
    """★合成画面に窓を 1 つ置く（⚠ 実データの経路を通すため）。

    `dakuten_on` の行の**1 つ上のマス**（＝ `lines[dakuten_on - 1]` の行）へ
    `゛` を置きます。⚠ DQ3 は濁点を上の行に描くので、★これが実機と同じ形。
    `dakuten_at` は濁らせる列。
    """
    from dq3.knowledge import conversation as cv
    from dq3rom import window as win
    from dq3rom.screen import PATTERN_BASE

    charset = cv._charset()
    rev = {}
    for code, ch in charset.table.items():
        rev.setdefault(ch, code - PATTERN_BASE)
    blank = rev.get(" ", 0)
    dak = rev["゛"]

    cols, rows_n = 32, 30
    scr = [0] * (cols * rows_n)
    inner = max(len(ln) for ln in lines)
    x0, y0 = 2, 18
    bw, bh = inner + 2, len(lines) + 2

    def put(x, y, v):
        scr[y * cols + x] = v

    put(x0, y0, win.TOP_LEFT)
    put(x0 + bw - 1, y0, win.TOP_RIGHT)
    put(x0, y0 + bh - 1, win.BOTTOM_LEFT)
    put(x0 + bw - 1, y0 + bh - 1, win.BOTTOM_RIGHT)
    for i in range(1, bw - 1):
        put(x0 + i, y0, win.EDGE_TOP)
        put(x0 + i, y0 + bh - 1, win.EDGE_BOTTOM)
    for j in range(1, bh - 1):
        put(x0, y0 + j, win.EDGE_LEFT)
        put(x0 + bw - 1, y0 + j, win.EDGE_RIGHT)
    for j, line in enumerate(lines):
        for i in range(inner):
            ch = line[i] if i < len(line) else " "
            put(x0 + 1 + i, y0 + 1 + j, rev.get(ch, blank))
    if dakuten_on is not None:
        assert not lines[dakuten_on - 1].strip(), "⚠ 濁点の行は空にしておくこと"
        for i in dakuten_at:
            put(x0 + 1 + i, y0 + dakuten_on, dak)
    return scr


def test_折り返しで2度読めた行を実データの経路で落とす():
    """★★ ⚠⚠ 依頼者 2026-08-31「濁点を考慮できていない」の本体。 ★★

    ★同じ行が「濁点つき」と「濁点なし」で 2 度読めたときに、
    ⚠ `windows_on_screen` が**1 本にまとめる**こと（★濁点の多いほうを残す）。
    """
    from dq3.knowledge import conversation as cv

    lines = ["＊「まちのそとを", "", "あやしけな はしょには",
             "あやしけな はしょには"]
    # ★け(3) と は(6) を濁らせる → 「あやしげな ばしょには」
    scr = _fake_window(lines, dakuten_on=2, dakuten_at=(3, 6))
    got = cv.windows_on_screen(scr)
    assert got, "⚠ 合成した窓が見つからない"
    text = got[0][0]
    assert "ばしょ" in text, "⚠ 濁点が付いた行が読めていない: %r" % text
    assert text.count("しょには") == 1, (
        "⚠⚠ 同じ行が 2 度入っています（★濁点の有無で別物になった）: %r" % text)

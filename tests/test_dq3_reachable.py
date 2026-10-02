"""★勇者が知っていて、まだ行っていない場所（RX3-0113 / 2026-09-10）。

```text
⚠⚠ ROM は 20 件の地名を素で持っている（★終盤まで全部）
★出してよいのは  ① 会話に名前が出た  ② 知っている話が指している
⚠ 出さない       行った場所 ／ ROM にあるだけの場所
```

⚠ 決定の正本は `docs/20-decision-log.md`（2026-09-10 / 依頼者）。
"""
from __future__ import annotations

import pathlib

import pytest

from dq3.knowledge import reachable as RE

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ⚠⚠ **絶対に漏れてはいけない地名**（★終盤 / 初見の楽しみを壊す）
SPOILERS = ("サマンオサ", "ラダトーム", "リムルダール", "メルキド", "ドムドーラ",
            "ジパング", "エジンベア", "スー", "マイラ")


# --- ★足場（⚠ 本物の記録に頼らない）------------------------------------

class _Row:
    def __init__(self, loc, name=None, visited=False):
        self.location_id, self.display_name, self.visited = loc, name, visited


class _Book:
    def __init__(self, rows):
        self._rows = rows

    def all_locations(self):
        return self._rows


class _Topic:
    def __init__(self, tid, names):
        self.topic_id, self.related_location_names = tid, list(names)


class _Master:
    def __init__(self, topics):
        self.topics = {t.topic_id: t for t in topics}


class _TopicBook:
    def __init__(self, status):
        self._status = status

    def state(self, tid):
        class _S:
            status = self._status.get(tid, "unknown")
        return _S()


def _conv(*texts):
    return {"9/0": [{"text": t} for t in texts]}


# --- ★濾し器の中身 -------------------------------------------------------

def test_行った場所は出さない():
    book = _Book([_Row("L9", "レーベ", visited=True)])
    master = _Master([_Topic("T1", ["レーベ"])])
    got = RE.collect(book, _TopicBook({"T1": "active"}), master, conversations={})
    assert [r.name for r in got] == [], "⚠ 行った場所を出している"


def test_話に書いただけでは出さない():
    """⚠⚠ 2026-09-27（RX3-0432 / 依頼者の判断「案 A」）に**逆**にしました。

    ★もとは「知っている話が指す未訪問の場所は出す」でした（`BY_TOPIC`）。
    ⚠ それは「メモに地名が書いてある」から「そこへ行け」を導いていて、
      ★勇者の推論を**先回り**しています。

    > 依頼者（2026-09-27）「関連を勇者が把握しきるのはイベント終了後。単にコメントと思っていた」

    → ★出す根拠は **会話に名前が出たこと**（`BY_TALK`）だけ。
    """
    book = _Book([_Row("L9", "レーベ", visited=True)])
    master = _Master([_Topic("T1", ["レーベ", "ナジミの塔"])])
    got = RE.collect(book, _TopicBook({"T1": "active"}), master, conversations={})
    assert [r.name for r in got] == [], "⚠⚠ メモに書いただけで出ている"
    # ★`topic_places` はもう使わない（⚠ 常に空）
    assert RE.topic_places(_TopicBook({"T1": "active"}), master) == set()


def test_会話に名前が出れば出す():
    """★語彙は「利用者が知っている名前」＋「メモに書いた名前」の両方。

    ⚠⚠ 語彙を `place_aliases()` だけにしたら候補が 11 → 2 件に落ちました
      （★`place_aliases()` は**もう知っている**名前＝大半が訪問済み）。
      → ★メモの名前も**語彙としては**使う（⚠ 出す根拠は会話に出たことだけ）。
    """
    book = _Book([_Row("L9", "レーベ", visited=True)])
    master = _Master([_Topic("T1", ["レーベ", "ナジミの塔"])])
    talk = {"0/1": [{"text": "＊「ナジミの塔に いけるとか。"}]}
    got = RE.collect(book, _TopicBook({"T1": "active"}), master, conversations=talk)
    assert [r.name for r in got] == ["ナジミの塔"]
    assert got[0].why == (RE.BY_TALK,)
    assert "話に出た" in got[0].why_text


def test_会話に出ていない場所は話の状態にかかわらず出さない():
    """⚠⚠ 2026-09-27（案 A）: ★濾し器は **会話に出たか**だけになりました。

    ⚠ もとは「`unknown` の Topic の場所は出さない」を見ていました
      （★`active` なら出す＝メモ由来）。→ ⚠ どちらも**出しません**。
    """
    master = _Master([_Topic("T1", ["ナジミの塔"]), _Topic("T9", ["ゾーマ城"])])
    got = RE.collect(_Book([]), _TopicBook({"T1": "active", "T9": "unknown"}),
                     master, conversations={})
    assert [r.name for r in got] == [], "⚠⚠ 会話に出ていないのに出ている"


def test_解決した話の場所は出さない():
    """⚠⚠ RX3-0186（2026-09-12 依頼者「ゆうしゃ会議で解決積み（ナジミの塔とか）が残存してしまっている。」）。

    ★進行中の話にも出てくる場所は、そちらから出る（⚠ 解決した話が消すのは、その話だけの場所）。
    """
    master = _Master([_Topic("T1", ["ナジミの塔", "いざないの洞窟"]),
                      _Topic("T3", ["シャンパーニの塔", "いざないの洞窟"])])
    # ⚠⚠ 2026-09-27（案 A）: ★話の状態は**もう見ません**（会話に出たかだけ）。
    #   ★会話に 2 つ出したうえで、⚠ 解決の有無で差が出ないことを見ます。
    talk = {"0/1": [{"text": "＊「ナジミの塔と いざないの洞窟の はなし。"}]}
    got = RE.collect(_Book([]), _TopicBook({"T1": "resolved", "T3": "active"}),
                     master, conversations=talk)
    names = sorted(r.name for r in got)
    assert names == sorted(["いざないの洞窟", "ナジミの塔"]), names
    assert {r.why for r in got} == {(RE.BY_TALK,)}


def test_漢字の地名でも行った場所は出さない():
    """⚠⚠ RX3-0192（2026-09-12 RX3-0186 の空打ち「エルフの隠れ里は行った場所なのに残る」）。

    ★Guide Master は漢字「エルフの隠れ里」、場所の記録はゲームの文から「エルフのかくれむら」（map 132）。
    """
    book = _Book([_Row("L132", "エルフのかくれむら", visited=True)])
    master = _Master([_Topic("T4", ["エルフの隠れ里", "ノアニール西の洞窟"])])
    # ⚠ 2026-09-27（案 A）: ★会話に出さないと候補にならないので、両方を会話に出す
    talk = {"0/1": [{"text": "＊「エルフの隠れ里と ノアニール西の洞窟の はなし。"}]}
    got = RE.collect(book, _TopicBook({"T4": "active"}), master, conversations=talk)
    names = [r.name for r in got]
    assert "エルフの隠れ里" not in names, "⚠⚠ 行った隠れ里が「行ってみる？」に残っている"
    # ⚠ 「ノアニール西の洞窟」の中の「ノアニール」もルーラの町として当たる（★別の話）。
    #   ★ここで見たいのは「行った隠れ里が消え、別の場所は残る」ことだけ。
    assert "ノアニール西の洞窟" in names, "⚠ 別の場所まで消した"
    # ★行っていなければ出す（⚠ 別名で何でも消していない）
    book = _Book([_Row("L132", "エルフのかくれむら", visited=False)])
    got = RE.collect(book, _TopicBook({"T4": "active"}), master, conversations=talk)
    assert [r.location_id for r in got if r.name == "エルフの隠れ里"] == ["L132"]


def test_記録の名前がひらがな混じりでも行った場所は出さない():
    """★場所の記録の名前は会話の復号（ひらがな混じり）から付く（⚠ Guide Master はカタカナ）。"""
    book = _Book([_Row("L9", "レーべ", visited=True)])      # ⚠ べ はひらがな
    master = _Master([_Topic("T1", ["レーベ"])])
    got = RE.collect(book, _TopicBook({"T1": "active"}), master, conversations={})
    assert [r.name for r in got] == [], "⚠ fold を通さずに名前を引いている"


def test_会話に出た町は出す():
    """★ROM の 20 件でも、⚠ **会話に名前が出ていれば**出してよい。"""
    towns = RE.rura_towns()
    if not towns:
        pytest.skip("ROM が読めません")
    index, map_id, name = towns[2]                 # ★まだ行っていない町（ロマリア）
    got = RE.collect(_Book([]), _TopicBook({}), _Master([]),
                     conversations=_conv("にしの %s に いってみるといい。" % name))
    assert [r.name for r in got] == [name]
    assert got[0].why == (RE.BY_TALK,)
    assert got[0].rura_index == index
    assert got[0].location_id is None or got[0].location_id == "L%d" % map_id


def test_カタカナとひらがなの違いで取り落とさない():
    """⚠⚠ **素の一致では当たりません**（★ROM はカタカナ / 会話はひらがな）。

    ```text
    ROM   レーベ  …30d9（ベ）
    会話  レーべ  …3079（べ）
    ```
    """
    assert RE.spoken("レーベ", "レーべの むらに ようこそ") is True, "⚠ fold を通していない"
    assert RE.spoken("アリアハン", "アりアハンの おしろに ようこそ") is True
    # ⚠ 関係のない地名は当たらない
    assert RE.spoken("サマンオサ", "レーべの むらに ようこそ") is False


def test_短い名前では当てない():
    """⚠ 2 文字以下は本文の途中に紛れる（★`concepts.MIN_ALIAS` と同じ考え）。"""
    assert RE.spoken("スー", "スーッと かぜが ふいた") is False


def test_語の途中の名前では当てない():
    """⚠⚠ RX3-0178（2026-09-12）: ロマリアの兵士の「まいられた」（参られた）が町の「マイラ」に当たった。

    ★見本は**架空の文**です（⚠ 原作の会話は公開物に入れません / RX3-0433）。
    ⚠ ただし取り違えの元になる語（`まいられた`）は本物と同じにしてあります
    （★ここを外すと検査が空回りします）。
    """
    assert RE.spoken("マイラ", "＊「とおくから まいられた おかたですね。") is False, \
        "⚠⚠ 「まいられた」を町のマイラと取り違えた（ネタバレ）"
    # ★助詞・「〜じょう」・記号・文の終わりが続くなら当たり
    assert RE.spoken("マイラ", "マイラの むらには おんせんが あるそうな") is True
    assert RE.spoken("レーベ", "レーべに いくと いい") is True
    assert RE.spoken("ロマリア", "ロマリアじょうへ いくがよい") is True
    assert RE.spoken("マイラ", "ひがしの マイラ！") is True
    assert RE.spoken("マイラ", "ひがしの マイラ") is True
    # ★1 か所目が語の途中でも、2 か所目で出ていれば当たり
    assert RE.spoken("マイラ", "まいられた かたよ、マイラへ いきなさい") is True


def test_未観測の材料でも落ちない():
    """⚠ 材料が 1 つも無いとき、★空を返す（例外にしない）。"""
    assert RE.collect(_Book([]), None, None, conversations={}) == []


def test_同じ場所を2度出さない():
    master = _Master([_Topic("T1", ["ナジミの塔"]), _Topic("T2", ["ナジミの塔"])])
    # ⚠ 2026-09-27（案 A）: 会話に出さないと候補にならないので、★会話に 1 度出す
    talk = {"0/1": [{"text": "＊「ナジミの塔の はなし。"}]}
    got = RE.collect(_Book([]), _TopicBook({"T1": "active", "T2": "discovered"}),
                     master, conversations=talk)
    assert [r.name for r in got] == ["ナジミの塔"]


# --- ⚠⚠ ネタバレの歯止め（★これが要）------------------------------------

def test_ROMの20件を素で出さない():
    """⚠⚠ **いちばん大事な検査。** ★条件を満たさない地名は 1 つも出ない。"""
    towns = RE.rura_towns()
    if not towns:
        pytest.skip("ROM が読めません")
    assert len(towns) == 20, "⚠ ルーラ表が 20 件でない: %d" % len(towns)
    names = {n for _i, _m, n in towns}
    for want in SPOILERS:
        assert want in names, "⚠ ROM の表に %s が無い（★検査の前提が崩れた）" % want

    # ★何も知らない勇者（⚠ Topic も会話も無い）
    got = RE.collect(_Book([]), _TopicBook({}), _Master([]), conversations={})
    assert got == [], "⚠⚠ 何も知らないのに %r が出た" % [r.name for r in got]


def test_いまの記録でネタバレが出ない():
    """★本物の記録で確かめる（⚠ 遊ぶと変わるので、**出てはいけないもの**だけ見る）。

    ★RX3-0256（2026-09-13）: 遊び進めると、表の名前も会話で聞く（★ポルトガで「エジンべア」を 2 回）。
      → ⚠ 表の名前が出たら、**会話の文に本当にその名前があるか**を `reachable` を通さずに確かめ、
        ★聞いていない名前だけを漏れとする（⚠ 同じ照合で照合を確かめない）。
    """
    import json

    from dq3 import paths
    from dq3.knowledge import guide as G
    from dq3.knowledge import guide_master as GM
    from dq3.knowledge.concepts import fold
    from dq3.knowledge.location_book import LocationBook

    # ⚠ ここは**本物の記録**を見る検査（★`paths.work` は検査中は一時フォルダ / RX-0141）
    path = paths.repo("work", "dq3-knowledge", "location-book.json")
    if not path.exists():
        pytest.skip("場所の記録がありません")
    # ★2026-09-28（RX3-0455）: 旧 Guide Master → **勇者メモの原本**
    from dq3.knowledge import hero_memo as HM

    built = HM.build(HM.DEFAULT_PATH)
    got = RE.collect(LocationBook.load(path=path), G.TopicBook.load(), built.as_master())
    names = {r.name for r in got}
    try:
        conv = json.loads(paths.repo("work", "dq3-knowledge",
                                    "npc-conversations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        conv = {}
    texts = [str((row or {}).get("text") or "") for rows in conv.values() if isinstance(rows, list)
             for row in rows if isinstance(row, dict)]
    heard = fold(" ".join(texts))
    leaked = [n for n in SPOILERS if n in names and fold(n) not in heard]
    assert not leaked, "⚠⚠ ネタバレが漏れています（★会話で聞いていない）: %r" % leaked


# --- ★ゲームの記録との突き合わせ -----------------------------------------

def test_材料が無ければ突き合わせない():
    got = RE.compare_visited(None, _Book([]))
    assert got["ok"] is False and got["game_only"] == []


def test_ゲームだけが知っている町に気づく():
    """⚠⚠ 訪問の取りこぼしに気づくための道（★直さない。気づくだけ）。"""
    towns = RE.rura_towns()
    if not towns:
        pytest.skip("ROM が読めません")
    # ★索引 0 と 1 の bit を立てる（⚠ 1 人目だけ）
    raw = bytes([0b11, 0, 0]) + bytes(9)
    book = _Book([_Row("L%d" % towns[0][1], visited=True)])   # ★片方だけ行った記録
    got = RE.compare_visited(raw.hex(), book)
    assert got["ok"] is True
    assert got["both"] == ["L%d" % towns[0][1]]
    assert got["game_only"] == ["L%d" % towns[1][1]], "⚠ 取りこぼしに気づけていない"


def test_こちらだけが知っている場所は異常ではない():
    """★洞窟や塔は 20 件の外なので、⚠ ゲームの bit は立たない。"""
    towns = RE.rura_towns()
    if not towns:
        pytest.skip("ROM が読めません")
    book = _Book([_Row("L%d" % towns[2][1], visited=True)])
    got = RE.compare_visited(bytes(12).hex(), book)
    assert got["game_only"] == [], "⚠ 取りこぼし扱いにしている"
    assert got["ours_only"] == ["L%d" % towns[2][1]]


def test_実物のセーブで食い違わない():
    """★依頼者の本物のセーブで、⚠ ゲームとこちらの記録が一致していること。"""
    from retroux.core.bgmap import savestate as ss

    from dq3 import paths
    from dq3.knowledge.location_book import LocationBook

    save = ROOT / "tools" / "fceux" / "fcs" / "DQ3_J.fc0"
    # ⚠ ここは**本物の記録**を見る検査（★`paths.work` は検査中は一時フォルダ / RX-0141）
    path = paths.repo("work", "dq3-knowledge", "location-book.json")
    if not (save.exists() and path.exists()):
        pytest.skip("セーブか記録がありません")
    ram = ss.load(save).chunks["RAM"]
    got = RE.compare_visited(bytes(ram[0x0750:0x0750 + 12]).hex(), LocationBook.load(path=path))
    if not got["ok"]:
        pytest.skip("ROM が読めません")
    assert got["game_only"] == [], "⚠⚠ 訪問を取りこぼしています: %r" % got["game_only"]


# --- ★つなぎ -------------------------------------------------------------

def test_材料がLuaから届く道がある():
    """⚠ `$0750` は state.json に載っていないと Python から読めない。"""
    lua = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    assert "CFG.rura" in lua and "rura = (function()" in lua
    gen = (ROOT / "dq3" / "phase0" / "generate_lua.py").read_text(encoding="utf-8")
    assert '"rura": _rura(profile)' in gen
    vm = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    assert "def rura_bits" in vm


def test_確かめた番地だけ渡す():
    """⚠ `confidence` が confirmed でない番地は Lua へ渡さない。"""
    import json

    from dq3.phase0 import generate_lua as GL

    profile = json.loads((ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")
                         .read_text(encoding="utf-8"))
    assert GL._rura(profile)["address"] == 0x0750
    weak = json.loads(json.dumps(profile))
    weak["runtime"]["rura"]["confidence"] = "inferred"
    assert GL._rura(weak) == {}, "⚠⚠ 裏の取れていない番地を渡している"


def test_勇者会議が0件のとき節を出さない():
    src = (ROOT / "dq3" / "ui" / "council_window.py").read_text(encoding="utf-8")
    body = src.split("def _render_reachable")[1].split("\n    def ")[0]
    assert "setVisible(show)" in body, "⚠ 0 件でも箱が残る"
    assert "reachable_cap" in body and "reachable_line" in body

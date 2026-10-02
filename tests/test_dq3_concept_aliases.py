"""Concept Alias: ゲーム内の言い回し → 正規の Concept（RX3-0440 / 2026-09-27）。

## ★固定すること

```text
別名 → 正規の名前 / 正規の名前そのもの → 正規の名前
同じ表現を 2 つの Concept に書いたら ERROR（★どちらへ解くか決められない）
会話に別名が出たら、Fact は**正規の Concept**（⚠ 別名の表現は Fact にならない）
勇者メモの `聞いた: <正規の名前>` が、会話の別名で出る
変わっていなければ読み直さない / 変えたら次の Matcher で反映 / ⚠ 会話ごとにファイルを読まない
```

⚠ 名前は ROM の辞書から借ります（★原作の語を検査に書かない）。
"""
from __future__ import annotations

import os

import pytest

yaml = pytest.importorskip("yaml")

from tests.test_dq3_hero_memo_council import _council  # noqa: E402

ALIAS = "ためしのいいまわし"          # ★作り物の言い回し（⚠ 原作の文ではない）


@pytest.fixture
def item(names):
    """★ROM の品の名前を 1 つ借りる（⚠ 同じ綴りが 2 id に当たらないもの）。"""
    for (kind, _folded), hits in names.items():
        if kind == "item" and len(hits) == 1:
            return hits[0]
    pytest.skip("⚠ 品の名前が無い")


@pytest.fixture
def names():
    from dq3.knowledge import guide_mapping
    from dq3.knowledge import rom_names

    rom_names.reset()
    index = guide_mapping.name_index()
    if not index:
        pytest.skip("⚠ ROM の名前辞書が読めません: %s" % rom_names.last_error)
    return index


def _aliases(tmp_path, monkeypatch, body: str):
    from dq3.knowledge import concept_aliases as CA

    path = tmp_path / "concept-aliases.yaml"
    path.write_bytes(("schema_version: 1\n" + body).encode("utf-8"))
    monkeypatch.setattr(CA, "DEFAULT_PATH", path)
    return path


def _bump(path):
    """⚠ 同じ時刻のまま書くと「変わっていない」に見える（★時刻を必ず進める）。"""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


# --- ★逆引き -------------------------------------------------------------------

def test_別名は正規の名前に解ける_正規の名前そのものも(tmp_path, monkeypatch, item):
    from dq3.knowledge import concept_aliases as CA
    from dq3.knowledge.concepts import fold

    _item_id, name = item
    _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    got = CA.heard_alias_index()
    assert got[fold(ALIAS)] == ("item", name)
    assert got[fold(name)] == ("item", name)


# --- ★検査 ---------------------------------------------------------------------

def _levels(doc, known=None):
    from dq3.knowledge import concept_aliases as CA

    return [(level, text) for level, _where, text in CA.problems(doc, known)]


def test_同じ表現を2つのConceptに書くとERROR():
    doc = {"schema_version": 1,
           "items": {"ためしのしなA": {"heard_aliases": ["おなじひょうげん"]},
                     "ためしのしなB": {"heard_aliases": ["おなじひょうげん"]}}}
    assert any(lv == "ERROR" and "にも登録" in t for lv, t in _levels(doc))


def test_種類をまたいでも同じ表現はERROR():
    doc = {"schema_version": 1,
           "items": {"ためしのしな": {"heard_aliases": ["おなじひょうげん"]}},
           "places": {"ためしのばしょ": {"heard_aliases": ["おなじひょうげん"]}}}
    assert any(lv == "ERROR" and "にも登録" in t for lv, t in _levels(doc))


@pytest.mark.parametrize("doc, word", [
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": ["", "ひょうげんA"]}}}, "空"),
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": [3]}}}, "文字ではありません"),
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": "ひょうげんA"}}}, "並び"),
    ({"schema_version": 1, "items": ["ためしのしな"]}, "の形で"),
    ({"schema_version": 1, "things": {}}, "知らない項目"),
    ({"items": {}}, "schema_version"),
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": ["ひょうげんA", "ひょうげんA"]}}}, "重複"),
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": ["ひょ"]}}}, "短すぎ"),
    ({"schema_version": 1, "items": {"ためしのしな": {"heard_aliases": ["ひょうげんA"], "note": 1}}}, "知らない項目"),
])
def test_形の間違いはERROR(doc, word):
    assert any(lv == "ERROR" and word in t for lv, t in _levels(doc)), _levels(doc)


def test_引けない正規の名前はERROR():
    doc = {"schema_version": 1, "items": {"ないしな": {"heard_aliases": ["ひょうげんA"]}}}
    assert any(lv == "ERROR" and "引けません" in t for lv, t in _levels(doc, lambda k, n: False))


def test_正規の名前と同じ表現と_表現の無いConceptはINFO():
    doc = {"schema_version": 1,
           "items": {"ためしのしな": {"heard_aliases": ["ためしのしな"]}, "もうひとつ": {}}}
    got = _levels(doc)
    assert not [t for lv, t in got if lv == "ERROR"]
    assert [lv for lv, _t in got].count("INFO") == 2


# --- ★heard Fact ----------------------------------------------------------------

def test_会話に別名が出たらFactは正規のConcept(tmp_path, monkeypatch, item):
    from dq3.knowledge import concepts as C

    item_id, name = item
    _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    matcher = C.Matcher(places=False)
    obs = C.Observation(observation_id="obs-a", text="＊「うみの %sが あるらしい。" % ALIAS)
    facts = C.analyse(obs, matcher)["facts"]
    assert [(f["subject"], f["predicate"]) for f in facts] == [("item:%d" % item_id, "heard")]


def test_勇者メモの正規の名前が会話の別名で出る(tmp_path, monkeypatch, item):
    from dq3.knowledge import concepts as C

    item_id, name = item
    _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    memo = tmp_path / "hero-memo.yaml"
    memo.write_bytes(("schema_version: 1\nleads:\n  - id: pot\n    memo: ためし\n"
                      "    appears_when:\n      - 聞いた: %s\n"
                      "    retires_when:\n      - 持った: %s\n" % (name, name)).encode("utf-8"))
    obs = C.Observation(observation_id="obs-a", text="＊「%sが あるらしい。" % ALIAS)
    facts = C.analyse(obs, C.Matcher(places=False))["facts"]
    view = _council(tmp_path, memo, facts).evaluate(save=False)
    assert [c["topic_id"] for c in view.recent] == ["pot"]


def test_勇者メモに別名を書いたら正規の名前を教える(tmp_path, monkeypatch, item):
    from dq3.knowledge import hero_memo as HM

    _item_id, name = item
    _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    memo = tmp_path / "hero-memo.yaml"
    memo.write_bytes(("schema_version: 1\nleads:\n  - id: pot\n    memo: ためし\n"
                      "    appears_when:\n      - 聞いた: %s\n"
                      "    retires_when:\n      - 持った: %s\n" % (ALIAS, name)).encode("utf-8"))
    [(_lead, _verb, written, why)] = HM.build(memo).unresolved
    assert written == ALIAS and name in why


# --- ★読み込み（⚠ 会話ごとに読まない）-----------------------------------------------

def test_変わっていなければ読み直さない_変えたら次のMatcherで反映(tmp_path, monkeypatch, item):
    from dq3.knowledge import concept_aliases as CA
    from dq3.knowledge import concepts as C

    item_id, name = item
    path = _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    CA.load()
    before = CA.PARSES
    C.Matcher(places=False)
    C.Matcher(places=False)
    assert CA.PARSES == before, "⚠ 変わっていないのに読み直した"

    path.write_bytes(("schema_version: 1\nitems:\n  %s:\n    heard_aliases:\n      - あたらしいいいまわし\n"
                      % name).encode("utf-8"))
    _bump(path)
    matcher = C.Matcher(places=False)
    assert CA.PARSES == before + 1
    obs = C.Observation(observation_id="obs-b", text="＊「あたらしいいいまわしが ある。")
    assert [f["subject"] for f in C.analyse(obs, matcher)["facts"]] == ["item:%d" % item_id]


def test_会話を解くときはファイルを読まない(tmp_path, monkeypatch, item):
    from dq3.knowledge import concept_aliases as CA
    from dq3.knowledge import concepts as C

    _item_id, name = item
    _aliases(tmp_path, monkeypatch, "items:\n  %s:\n    heard_aliases:\n      - %s\n" % (name, ALIAS))
    matcher = C.Matcher(places=False)

    def boom(*_a, **_k):
        raise AssertionError("⚠ 会話を解くたびに別名の表を読んだ")

    monkeypatch.setattr(CA, "load", boom)
    obs = C.Observation(observation_id="obs-c", text="＊「%sが ある。" % ALIAS)
    assert C.analyse(obs, matcher)["facts"]


# --- ★本物の原本（⚠ 名前を検査に書かないため、カードの id から引く）--------------------

REAL_CARDS = ("072_lastkey3", "100_red", "100_yellow", "150_underworld")


def test_正規化したカードの聞いたが正規のConceptとして解ける(tmp_path, names):
    """★072（別名で正規化）/ 100_red / 100_yellow / 150（地名）の `聞いた:` が引けること。

    ⚠ ROM の名前辞書が要る（`names` が無ければ skip / ★公開版で ROM を置いていない環境）。
    """
    from dq3.knowledge import hero_memo as HM

    doc = yaml.safe_load(HM.DEFAULT_PATH.read_bytes())
    leads = [l for l in doc["leads"] if l.get("id") in REAL_CARDS]
    if len(leads) != len(REAL_CARDS):
        pytest.skip("⚠ 原本に見本のカードがそろっていない")
    for lead in leads:
        lead["memo"] = lead.get("memo") or "（検査用）"         # ⚠ 150 の memo は人が書く
    path = tmp_path / "hero-memo.yaml"
    path.write_bytes(yaml.safe_dump({"schema_version": 1, "leads": leads},
                                    allow_unicode=True).encode("utf-8"))
    built = HM.build(path)
    if not built.rules:
        pytest.skip("⚠ ROM の名前辞書が無い")
    heard = [u for u in built.unresolved if u[1] == "聞いた"]
    assert heard == [], heard

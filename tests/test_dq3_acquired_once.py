"""「一度でも手に入れた」（`入手した:` / RX3-0443）と、重複キー・複数 id（RX3-0441 / 0444）。

## ★固定すること

```text
入手した:   一度成立したら**戻らない**（⚠ 使っても渡しても消えない）
            ★持ち物で見えた品 ＋ **入手した瞬間の記録**（宝箱・しらべる・入手）
持った:     ⚠ いま持っているか（★今までどおり）
重複キー    ⚠⚠ 同じ項目を 2 度書いたら ERROR（★YAML は黙って後勝ちにする）
複数 id     ★同じ名前が 2 つの id に当たるなら**どちらでも**成立（⚠ ゾーマ / カンダタ）
短い地名    ★2 文字の地名も**名前で書ける**（⚠ 会話の照合は今までどおり 3 文字から）
```

⚠ 名前は ROM の辞書から借ります（★原作の語を検査に書かない）。
"""
from __future__ import annotations

import json

import pytest

yaml = pytest.importorskip("yaml")

from dq3.knowledge import progress as PG  # noqa: E402
from tests.test_dq3_hero_memo_council import _council  # noqa: E402
from tests.test_dq3_hero_memo_scenario import _items, _write  # noqa: E402


@pytest.fixture
def names():
    from dq3.knowledge import guide_mapping
    from dq3.knowledge import rom_names

    rom_names.reset()
    index = guide_mapping.name_index()
    if not index:
        pytest.skip("⚠ ROM の名前辞書が読めません: %s" % rom_names.last_error)
    return index


# --- ★Progress: 一度でも手に入れた -------------------------------------------------

def test_持ち物から消えても入手したは残る(tmp_path):
    p = PG.Progress(path=tmp_path / "progress.json")
    p.note_acquired([42])
    assert p.acquired_ever() == {42}
    # ⚠ 持ち物を覗き直して 1 つも無くても、★入手した記録は消えない
    p.note_party([{"items": [0xFF] * 8, "hp_max": 10}])
    assert p.acquired_ever() == {42}


def test_入手したは持ち物で見えた分も含む(tmp_path):
    p = PG.Progress(path=tmp_path / "progress.json")
    p.items_seen = True
    p.note_party([{"items": [7], "hp_max": 10}])
    p.note_acquired([42])
    assert p.acquired_ever() == {7, 42}
    assert p.items_ever == {7}, "⚠ 持った: の材料は増やさない"


def test_保存して読み直しても残る(tmp_path):
    p = PG.Progress(path=tmp_path / "progress.json")
    p.note_acquired([42, 7])
    assert p.save(force=True)
    again = PG.Progress.load(tmp_path / "progress.json")
    assert again.acquired == {7, 42}


def test_2人が別々に書いても消し合わない(tmp_path):
    path = tmp_path / "progress.json"
    one = PG.Progress(path=path)
    one.note_acquired([1])
    one.save(force=True)
    other = PG.Progress(path=path)
    other.note_acquired([2])
    other.save(force=True)
    assert PG.Progress.load(path).acquired == {1, 2}


def test_入手の記録は文字列のitem_idでも読める(tmp_path):
    """⚠⚠ 記録の `item_id` は**文字列**（★int と決め打つと 0 件になる / 2026-09-28 に踏んだ）。"""
    memos = tmp_path / "memos.jsonl"
    rows = [
        {"order": 1, "source": "chest", "item_id": "82", "text": "宝箱"},
        {"order": 2, "source": "search", "item_id": 90, "text": "しらべる"},
        {"order": 3, "source": "chest", "item_id": None, "text": "ゴールド"},
        {"order": 4, "source": "conversation", "item_id": "5", "text": "会話"},
        {"order": 5, "source": "unknown", "item_id": "17", "text": "受け取った"},
    ]
    memos.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8"))
    got = PG.acquired_items(memos)
    assert got == {82, 90, 17}, "⚠ 会話の行は入手ではない / ⚠ 金額の行は品ではない"


def test_記録が無ければ空(tmp_path):
    assert PG.acquired_items(tmp_path / "ない.jsonl") == set()


def test_load_allは入手の記録も取り込む(tmp_path):
    memos = tmp_path / "memos.jsonl"
    memos.write_bytes(json.dumps({"order": 1, "source": "chest", "item_id": "42"}).encode("utf-8"))
    got = PG.load_all(tmp_path / "progress.json", memos)
    assert got.acquired == {42}


def test_gatherも入手の記録を取り込む(tmp_path):
    """★画面（勇者会議）が通る道（`Council._progress` → `gather`）でも取り込むこと。"""
    memos = tmp_path / "memos.jsonl"
    memos.write_bytes(json.dumps({"order": 1, "source": "chest", "item_id": "42"}).encode("utf-8"))
    got = PG.gather(progress=PG.Progress(path=tmp_path / "progress.json"),
                    state={"party": []}, memos_path=memos)
    assert got.acquired == {42}
    assert ("item:42", "acquired") in {(f["subject"], f["predicate"]) for f in got.facts()}


#: ⚠⚠ 実測（2026-09-28 / 依頼者の記録）: 拾ってすぐ手放したため `items_ever` に入らなかった品。
#:   ★`入手した:` はこれを拾えること（⚠ 名前は書かない / id だけ / RX3-0443）。
MISSED_BY_INVENTORY = (17, 64, 66, 76, 99, 120, 121)


def test_持ち物で見えなかった品も入手の記録から拾える(tmp_path):
    """★実測で抜けていた 7 種が、入手の記録から成立すること（⚠ 出どころは種類 3 つ）。"""
    memos = tmp_path / "memos.jsonl"
    rows = [{"order": 100 + i, "source": src, "item_id": str(iid), "text": "入手"}
            for i, (iid, src) in enumerate(zip(MISSED_BY_INVENTORY,
                                               ("chest", "chest", "chest", "chest",
                                                "chest", "chest", "unknown")))]
    memos.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8"))
    got = PG.load_all(tmp_path / "progress.json", memos)
    assert got.acquired == set(MISSED_BY_INVENTORY)
    assert got.items_ever == set(), "⚠ 持った: の材料は増やさない"
    facts = {(f["subject"], f["predicate"]) for f in got.facts()}
    for iid in MISSED_BY_INVENTORY:
        assert ("item:%d" % iid, "acquired") in facts
        assert ("item:%d" % iid, "obtain") not in facts


def test_facts_は持ったと入手したを別に出す(tmp_path):
    p = PG.Progress(path=tmp_path / "progress.json")
    p.items_seen = True
    p.note_party([{"items": [7], "hp_max": 10}])
    p.note_acquired([42])
    got = {(f["subject"], f["predicate"]) for f in p.facts()}
    assert ("item:7", "obtain") in got
    assert ("item:7", "acquired") in got
    assert ("item:42", "acquired") in got
    assert ("item:42", "obtain") not in got, "⚠⚠ 入手の記録だけで「いま持っている」にしない"


# --- ★勇者メモから使う ------------------------------------------------------------

def _acquired(item_id):
    from dq3.knowledge import concepts as C

    subject = "item:%d" % item_id
    return {"fact_id": C.fact_id_of(subject, "acquired", None, "got"), "subject": subject,
            "predicate": "acquired", "object": None, "source_observation_id": "got",
            "confidence": 1.0}


def _heard(item_id, obs="obs-1"):
    from dq3.knowledge import concepts as C

    subject = "item:%d" % item_id
    return {"fact_id": C.fact_id_of(subject, "heard", None, obs), "subject": subject,
            "predicate": "heard", "object": None, "source_observation_id": obs, "confidence": 1.0}


def test_入手したで片づき_持ち物から消えても戻らない(tmp_path, names):
    (a_id, a), (b_id, b) = _items(names, 2)
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: pot\n    memo: ためし\n"
                             "    appears_when:\n      - 聞いた: %s\n"
                             "    retires_when:\n      - 入手した: %s\n" % (a, b)))
    view = _council(tmp_path, path, [_heard(a_id)]).evaluate(save=True)
    assert [c["topic_id"] for c in view.recent] == ["pot"]
    view = _council(tmp_path, path, [_heard(a_id), _acquired(b_id)]).evaluate(save=True)
    assert [c["topic_id"] for c in view.resolved] == ["pot"]
    # ⚠ 持ち物から消えた（★`入手した` の Fact も来なくなった）→ ★それでも片づいたまま
    view = _council(tmp_path, path, [_heard(a_id)]).evaluate(save=True)
    assert [c["topic_id"] for c in view.resolved] == ["pot"], "⚠⚠ カードが復活した"
    assert [c["topic_id"] for c in view.recent] == []


def test_入手したは持ったでは成立しない(tmp_path, names):
    """★別の predicate（⚠ `持った:` の Fact では `入手した:` は満たされない）。"""
    from dq3.knowledge import concepts as C

    (a_id, a), (b_id, b) = _items(names, 2)
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: pot\n    memo: ためし\n"
                             "    appears_when:\n      - 聞いた: %s\n"
                             "    retires_when:\n      - 入手した: %s\n" % (a, b)))
    obtain = {"fact_id": C.fact_id_of("item:%d" % b_id, "obtain", None, "inv"),
              "subject": "item:%d" % b_id, "predicate": "obtain", "object": None,
              "source_observation_id": "inv", "confidence": 1.0}
    view = _council(tmp_path, path, [_heard(a_id), obtain]).evaluate(save=False)
    assert [c["topic_id"] for c in view.recent] == ["pot"]
    assert view.resolved == []


def test_入手したは道具だけ(tmp_path, names):
    from dq3.knowledge import hero_memo as HM

    _mid, monster = next((hits[0][0], hits[0][1]) for (k, f), hits in names.items()
                         if k == "monster" and len(hits) == 1)
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: bad\n    memo: ためし\n"
                             "    appears_when:\n      - フラグ: ship_obtained\n"
                             "    retires_when:\n      - 入手した: %s\n" % monster))
    [(_lead, verb, written, why)] = HM.build(path).unresolved
    assert verb == "入手した" and written == monster and "名前" in why


# --- ⚠⚠ 重複キー（RX3-0441）------------------------------------------------------

def test_同じ項目を2度書いたら止まる(tmp_path):
    from dq3.knowledge import hero_memo as HM

    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: twice\n"
                             "    scenario: walk\n    memo: ためし\n"
                             "    scenario: walk\n"
                             "    appears_when:\n      - フラグ: ship_obtained\n"
                             "    retires_when:\n      - フラグ: ship_obtained\n"))
    with pytest.raises(HM.HeroMemoError, match="重複"):
        HM.load(path)


def test_重複キーは行番号が分かる():
    from dq3.yaml_strict import DuplicateKey, load_strict

    body = "a: 1\nb:\n  - x\nc: 2\na: 3\n"
    with pytest.raises(DuplicateKey) as got:
        load_strict(body.encode("utf-8"))
    assert got.value.key == "a" and got.value.line == 5 and got.value.first_line == 1


def test_重複が無ければsafe_loadと同じ():
    from dq3.yaml_strict import load_strict

    body = "a: 1\nb:\n  - x\n  - y\nc:\n  d: 2\n"
    assert load_strict(body.encode("utf-8")) == yaml.safe_load(body)


def test_門番も重複キーを止める(tmp_path):
    import importlib.util
    import pathlib

    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "dq3_hero_memo_check.py"
    if not script.is_file():
        pytest.skip("★公開版には scripts/dq3_hero_memo_check.py がありません")
    spec = importlib.util.spec_from_file_location("dq3_hero_memo_check_dup", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    memo = tmp_path / "hero-memo.yaml"
    memo.write_bytes(b"\xef\xbb\xbf" + ("schema_version: 1\r\nleads:\r\n  - id: twice\r\n"
                                       "    memo: a\r\n    memo: b\r\n").encode("utf-8"))
    mod.MEMO = memo
    assert mod.main([]) == 1


# --- ★同じ名前が 2 つの id（RX3-0444）---------------------------------------------

def test_同じ名前が2つのidに当たればどちらでも成立(tmp_path, names):
    from dq3.knowledge import concepts as C
    from dq3.knowledge import hero_memo as HM

    pair = next(((f, hits) for (k, f), hits in names.items()
                 if k == "monster" and len(hits) > 1), None)
    if pair is None:
        pytest.skip("⚠ 同じ名前で 2 つの id を持つ敵が ROM に無い")
    _folded, hits = pair
    name = hits[0][1]
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: boss\n    memo: ためし\n"
                             "    appears_when:\n      - フラグ: ship_obtained\n"
                             "    retires_when:\n      - 倒した: %s\n" % name))
    built = HM.build(path)
    subjects = {r.subject() for r in built.rules if r.predicate == "defeat"}
    assert subjects == {"monster:%d" % int(i) for i, _n in hits}, "⚠⚠ 1 つの id にしか解いていない"
    # ★2 つめの id を倒しても片づく
    flag = {"fact_id": C.fact_id_of("event:ship_obtained", "set", None, "story"),
            "subject": "event:ship_obtained", "predicate": "set", "object": None,
            "source_observation_id": "story", "confidence": 1.0}
    last = int(hits[-1][0])
    beat = {"fact_id": C.fact_id_of("monster:%d" % last, "defeat", None, "battle"),
            "subject": "monster:%d" % last, "predicate": "defeat", "object": None,
            "source_observation_id": "battle", "confidence": 1.0}
    view = _council(tmp_path, path, [flag, beat]).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == ["boss"]


# --- ★短い地名（RX3-0442）---------------------------------------------------------

def _a_short_place():
    """★3 文字未満の地名を 1 つ借りる（⚠ 原作の語を検査に書かないため）。"""
    from dq3.knowledge import concepts as C

    matching = {f for f, _l, _n in C.place_aliases()}
    for folded, location_id, name in C.place_aliases(min_len=1):
        if folded not in matching:
            return location_id, name
    pytest.skip("⚠ この ROM には 3 文字未満の地名が無い")


def test_2文字の地名も名前で書ける():
    from dq3.knowledge import concepts as C

    matching = {f for f, _l, _n in C.place_aliases()}
    short = {f for f, _l, _n in C.place_aliases(min_len=1)}
    only = short - matching
    if not only:
        pytest.skip("⚠ この ROM には 3 文字未満の地名が無い")
    assert all(len(f) < C.MIN_ALIAS for f in only)


def test_短い地名を勇者メモの条件に書ける(tmp_path):
    """⚠⚠ ここが本題（★`place_aliases` を素で呼ぶと 2 文字の地名は書けない）。"""
    from dq3.knowledge import concepts as C
    from dq3.knowledge import hero_memo as HM

    location_id, name = _a_short_place()
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: town\n    memo: ためし\n"
                             "    appears_when:\n      - フラグ: ship_obtained\n"
                             "    retires_when:\n      - 行った: %s\n" % name))
    built = HM.build(path)
    assert built.unresolved == [], built.unresolved
    assert {r.subject() for r in built.rules if r.predicate == "visit"} == {"location:%s" % location_id}
    # ★着いたら片づく
    flag = {"fact_id": C.fact_id_of("event:ship_obtained", "set", None, "story"),
            "subject": "event:ship_obtained", "predicate": "set", "object": None,
            "source_observation_id": "story", "confidence": 1.0}
    visit = {"fact_id": C.fact_id_of("location:%s" % location_id, "visit", None, "v"),
             "subject": "location:%s" % location_id, "predicate": "visit", "object": None,
             "source_observation_id": "v", "confidence": 1.0}
    view = _council(tmp_path, path, [flag, visit]).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == ["town"]


def test_短い地名は会話の照合には入れない():
    """★3 文字未満を会話で当てると誤爆する（⚠ そこは今までどおり）。"""
    from dq3.knowledge import concepts as C

    _location_id, name = _a_short_place()
    matcher = C.Matcher()
    assert C.fold(name) not in {f for f, _l, _n in matcher.places}

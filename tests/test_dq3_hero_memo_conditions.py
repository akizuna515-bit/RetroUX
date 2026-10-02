"""勇者メモの複数条件・論理 Fact・時系列の再生（RX3-0436 / 2026-09-27）。

## ★固定すること

```text
条件        1 本 / all_of（全部）/ any_of（どれか）/ all_of の途中は見えない
論理 Fact   同じ知識を何度聞いても 1 つ。⚠ 聞き直しで NEW にも「更新」にもならない
時系列      first_visible は成立した条件より前にならない / NEVER_TRIGGERED を出す
No-Spoiler  all_of の途中のカードは題名も id も件数も出ない
```

⚠ 見本の名前は ROM の辞書から借ります（★原作の語を検査に書かない）。
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from tests.test_dq3_hero_memo_council import _council  # noqa: E402
from tests.test_dq3_hero_memo_scenario import _everything_shown, _items, _write  # noqa: E402

SECRET = "まだそろっていないカード"


@pytest.fixture
def names():
    from dq3.knowledge import guide_mapping
    from dq3.knowledge import rom_names

    rom_names.reset()
    index = guide_mapping.name_index()
    if not index:
        pytest.skip("⚠ ROM の名前辞書が読めません: %s" % rom_names.last_error)
    return index


def _heard(item_id, obs="obs-1"):
    """★観測ごとの Fact（⚠ fact_id は観測ごとに違う = 本物と同じ作り）。"""
    from dq3.knowledge import concepts as C

    subject = "item:%d" % item_id
    return {"fact_id": C.fact_id_of(subject, "heard", None, obs), "subject": subject,
            "predicate": "heard", "object": None, "source_observation_id": obs, "confidence": 1.0}


def _obtain(item_id):
    from dq3.knowledge import concepts as C

    subject = "item:%d" % item_id
    return {"fact_id": C.fact_id_of(subject, "obtain", None, "inv"), "subject": subject,
            "predicate": "obtain", "object": None, "source_observation_id": "inv", "confidence": 1.0}


def _book(tmp_path, names):
    """★3 枚の見本。

    ```text
    single   A を聞いたら出る / B を持ったら片づく
    both     C と D を**両方**聞いたら出る（all_of）/ E を持ったら片づく
    either   C か F を聞いたら出る（any_of）/ E を持ったら片づく
    ```
    """
    (a_id, a), (b_id, b), (c_id, c), (d_id, d), (e_id, e), (f_id, f) = _items(names, 6)
    body = ("schema_version: 1\n"
            "scenarios:\n"
            "  walk:\n"
            "    title: ためしの話\n"
            "leads:\n"
            "  - id: single\n"
            "    scenario: walk\n"
            "    memo: ひとつで出るカード\n"
            "    appears_when:\n"
            "      - 聞いた: %s\n"
            "    retires_when:\n"
            "      - 持った: %s\n"
            "  - id: both\n"
            "    scenario: walk\n"
            "    memo: %s\n"
            "    appears_when:\n"
            "      - all_of:\n"
            "          - 聞いた: %s\n"
            "          - 聞いた: %s\n"
            "    retires_when:\n"
            "      - 持った: %s\n"
            "  - id: either\n"
            "    memo: どちらかで出るカード\n"
            "    appears_when:\n"
            "      - any_of:\n"
            "          - 聞いた: %s\n"
            "          - 聞いた: %s\n"
            "    retires_when:\n"
            "      - 持った: %s\n" % (a, b, SECRET, c, d, e, c, f, e))
    ids = dict(a=a_id, b=b_id, c=c_id, d=d_id, e=e_id, f=f_id)
    return _write(tmp_path, body), ids


def _visible(view) -> set[str]:
    return {c["topic_id"] for c in view.recent + view.resolved}


# --- ★条件 -------------------------------------------------------------------

def test_1本の条件で出る(tmp_path, names):
    path, ids = _book(tmp_path, names)
    view = _council(tmp_path, path, [_heard(ids["a"])]).evaluate(save=False)
    assert _visible(view) == {"single"}


def test_all_ofは片方だけでは出ず_両方そろうと出る(tmp_path, names):
    path, ids = _book(tmp_path, names)
    only_d = _council(tmp_path, path, [_heard(ids["d"])]).evaluate(save=False)
    assert "both" not in _visible(only_d)
    assert "both" not in only_d.moved, "⚠ 見えないカードの id が moved に漏れた"
    assert SECRET not in _everything_shown(only_d)

    both = [_heard(ids["d"], "obs-1"), _heard(ids["c"], "obs-2")]
    view = _council(tmp_path, path, both).evaluate(save=False)
    assert {"both", "either"} <= _visible(view)


def test_all_ofがそろった瞬間はNEWで_途中の当たりを数えない(tmp_path, names):
    path, ids = _book(tmp_path, names)
    first = [_heard(ids["d"], "obs-1")]
    _council(tmp_path, path, first).evaluate(save=True)
    view = _council(tmp_path, path, first + [_heard(ids["c"], "obs-2")]).evaluate(save=True)
    card = next(c for c in view.recent if c["topic_id"] == "both")
    assert card["badge"] == "NEW" and card["update_count"] == 1


def test_any_ofはどれか1本で出る(tmp_path, names):
    path, ids = _book(tmp_path, names)
    view = _council(tmp_path, path, [_heard(ids["f"])]).evaluate(save=False)
    assert _visible(view) == {"either"}


def test_何も満たさなければ何も出ない(tmp_path, names):
    path, _ids = _book(tmp_path, names)
    view = _council(tmp_path, path, []).evaluate(save=False)
    assert _visible(view) == set() and view.scenarios == []


def test_片づく条件だけ成立しても分かったことに出ない(tmp_path, names):
    """⚠⚠ 出る条件が 1 度も成立していないカードは、片づいても見せない（★存在が漏れる）。"""
    path, ids = _book(tmp_path, names)
    only_d_and_retire = [_heard(ids["d"]), _obtain(ids["e"])]
    view = _council(tmp_path, path, only_d_and_retire).evaluate(save=True)
    assert "both" not in _visible(view) and "either" not in _visible(view)
    assert SECRET not in _everything_shown(view)
    # ★後から出る条件がそろえば、片づいた姿で出る
    view = _council(tmp_path, path, only_d_and_retire + [_heard(ids["c"], "obs-9")]).evaluate(save=True)
    assert {"both", "either"} <= {c["topic_id"] for c in view.resolved}


def test_保存済みの状態も今の規則で決め直す(tmp_path, names):
    """★以前の規則で resolved と保存されたカードも、出る条件が未成立なら見せない。"""
    import json

    path, ids = _book(tmp_path, names)
    _council(tmp_path, path, [_heard(ids["d"]), _obtain(ids["e"])]).evaluate(save=True)
    state = tmp_path / "topic-state.json"
    data = json.loads(state.read_text(encoding="utf-8"))
    data["topics"]["both"]["status"] = "resolved"            # ⚠ 古い規則の保存を再現
    state.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    view = _council(tmp_path, path, [_heard(ids["d"]), _obtain(ids["e"])]).evaluate(save=False)
    assert "both" not in _visible(view)


def test_all_ofの1本が解けなければ組ごと使わない(tmp_path, names):
    """⚠⚠ 残りだけで組を作ると、AND が黙って短くなり「早すぎる」カードになる。"""
    from dq3.knowledge import hero_memo as HM

    (a_id, a), (b_id, b) = _items(names, 2)
    path = _write(tmp_path, (
        "schema_version: 1\nleads:\n"
        "  - id: half\n    memo: ためし\n    appears_when:\n"
        "      - all_of:\n          - 聞いた: %s\n          - 聞いた: ぜったいにないなまえ\n"
        "    retires_when:\n      - 持った: %s\n" % (a, b)))
    built = HM.build(path)
    assert [r for r in built.rules if not r.completes] == []
    assert len(built.unresolved) == 1
    view = _council(tmp_path, path, [_heard(a_id)]).evaluate(save=False)
    assert _visible(view) == set()


@pytest.mark.parametrize("appears, match", [
    ("      - all_of:\n          - 聞いた: X\n", "2 つ以上"),
    ("      - all_of:\n          - any_of:\n              - 聞いた: X\n          - 聞いた: Y\n", "入れ子"),
    ("      - all_of: 聞いた\n", "並び"),
])
def test_組の書き間違いは止める(tmp_path, appears, match):
    from dq3.knowledge import hero_memo as HM

    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: bad\n    memo: ためし\n"
                             "    appears_when:\n" + appears
                             + "    retires_when:\n      - フラグ: x\n"))
    with pytest.raises(HM.HeroMemoError, match=match):
        HM.load(path)


def test_retires_whenにall_ofは書けない(tmp_path):
    from dq3.knowledge import hero_memo as HM

    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: bad\n    memo: ためし\n"
                             "    appears_when:\n      - 聞いた: X\n"
                             "    retires_when:\n      - all_of:\n          - 聞いた: X\n"
                             "          - 聞いた: Y\n"))
    with pytest.raises(HM.HeroMemoError, match="retires_all"):
        HM.load(path)


# --- ★論理 Fact --------------------------------------------------------------

def test_同じ知識を何度聞いても論理Factは1つ(tmp_path, names):
    from dq3.knowledge import concepts as C

    path, ids = _book(tmp_path, names)
    heard = [_heard(ids["a"], "obs-%d" % n) for n in range(4)]
    facts, renames = C.logical_facts(heard)
    assert len(facts) == 1 and facts[0]["count"] == 4
    assert facts[0]["source_observation_ids"] == ["obs-0", "obs-1", "obs-2", "obs-3"]
    assert set(renames.values()) == {facts[0]["fact_id"]}

    view = _council(tmp_path, path, heard).evaluate(save=False)
    card = next(c for c in view.recent if c["topic_id"] == "single")
    assert len(card["matched_fact_ids"]) == 1, "⚠ 同じ知識が複数の Fact として当たった"
    from dq3.ui.council_window import detail_lines

    rows = dict(detail_lines(card, view))
    assert rows["関連 Fact"].count("heard") == 1 and "×4 回" in rows["関連 Fact"]


def test_聞き直してもNEWのままで更新にならない(tmp_path, names):
    path, ids = _book(tmp_path, names)
    once = [_heard(ids["a"], "obs-1")]
    view = _council(tmp_path, path, once).evaluate(save=True)
    assert view.recent[0]["badge"] == "NEW"
    again = once + [_heard(ids["a"], "obs-2"), _heard(ids["a"], "obs-3")]
    view = _council(tmp_path, path, again).evaluate(save=True)
    card = view.recent[0]
    assert card["badge"] == "NEW" and card["update_count"] == 1
    assert view.moved == {}, "⚠ 同じ知識の聞き直しで「動いた」になった"


def test_新しい別の知識では条件を満たしたカードだけ増える(tmp_path, names):
    path, ids = _book(tmp_path, names)
    first = [_heard(ids["a"], "obs-1")]
    _council(tmp_path, path, first).evaluate(save=True)
    view = _council(tmp_path, path, first + [_heard(ids["f"], "obs-2")]).evaluate(save=True)
    assert _visible(view) == {"single", "either"}
    assert set(view.moved) == {"either"}
    single = next(c for c in view.recent if c["topic_id"] == "single")
    assert single["update_count"] == 1


def test_保存済みの観測ごとの番号は論理Factへ畳まれる(tmp_path, names):
    """★RX3-0436 以前の状態ファイル（観測ごとの番号）を読んでも、更新回数が進まない。"""
    from dq3.knowledge import guide as G

    book = G.TopicBook(master={}, rules=[], path=tmp_path / "s.json")
    book.states["x"] = G.TopicState(topic_id="x", matched_fact_ids=["o1", "o2", "o3"])
    book.rename_facts({"o1": "L", "o2": "L", "o3": "L"})
    assert book.states["x"].matched_fact_ids == ["L"]


def test_一般の語は品名の中に出ても聞いたになる(tmp_path, monkeypatch):
    from dq3.knowledge import concepts as C

    words = tmp_path / "concept-words.csv"
    words.write_bytes("word,evidence,notes\nふしぎなもの,ためし,ためし\n".encode("utf-8"))
    monkeypatch.setattr(C, "CONCEPT_WORDS", words)
    matcher = C.Matcher(places=False)
    obs = C.Observation(observation_id="obs-w", text="＊「あかいふしぎなものを さがしている。")
    subjects = {f["subject"] for f in C.analyse(obs, matcher)["facts"]}
    assert "word:ふしぎなもの" in subjects


# --- ★時系列の再生 ------------------------------------------------------------

def _replay(tmp_path, names, facts_and_orders):
    from dq3.knowledge import concepts as C
    from dq3.knowledge import hero_memo as HM
    from dq3.knowledge import hero_memo_timeline as T

    path, ids = _book(tmp_path, names)
    built = HM.build(path)
    raw = [fact for fact, _order in facts_and_orders(ids)]
    facts, renames = C.logical_facts(raw)
    order_of = {renames[fact["fact_id"]]: order for fact, order in facts_and_orders(ids)}
    clocks = {f["fact_id"]: T.Clock(order_of[f["fact_id"]]) for f in facts}
    return T.replay(built.topics, built.rules, facts, clocks)


def test_first_visibleは組がそろった時点(tmp_path, names):
    from dq3.knowledge import hero_memo_timeline as T

    got = _replay(tmp_path, names, lambda ids: [
        (_heard(ids["d"], "o1"), 10), (_heard(ids["a"], "o2"), 20),
        (_heard(ids["c"], "o3"), 30), (_obtain(ids["e"]), 40)])
    assert got["single"].first_visible == T.Clock(20)
    assert got["both"].first_visible == T.Clock(30), "⚠ AND が 1 本目で見えた"
    assert {t.clock.order for t in got["both"].triggers} == {10, 30}
    assert got["both"].resolved == T.Clock(40)
    assert got["either"].first_visible == T.Clock(30)
    assert all(T.REVIEW_BEFORE_SOURCE not in c.review for c in got.values())


def test_1度も見えないカードはNEVER_TRIGGERED(tmp_path, names):
    from dq3.knowledge import hero_memo_timeline as T

    got = _replay(tmp_path, names, lambda ids: [(_heard(ids["a"], "o1"), 5)])
    assert T.NEVER_TRIGGERED in got["both"].review
    assert T.NEVER_TRIGGERED in got["either"].review
    assert T.NEVER_TRIGGERED not in got["single"].review


def test_片方だけの組はNEVER_TRIGGERED(tmp_path, names):
    from dq3.knowledge import hero_memo_timeline as T

    got = _replay(tmp_path, names, lambda ids: [(_heard(ids["d"], "o1"), 5)])
    assert T.NEVER_TRIGGERED in got["both"].review


# --- ★門番も組と一般の語を知っている（⚠ 2026-09-27 に門番だけ古いまま ERROR を出した）---------

def _checker():
    import importlib.util
    import pathlib

    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "dq3_hero_memo_check.py"
    if not script.is_file():
        pytest.skip("★公開版には scripts/dq3_hero_memo_check.py がありません")
    spec = importlib.util.spec_from_file_location("dq3_hero_memo_check_t", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check(mod, names, appears, retires=None):
    lead = {"id": "x", "memo": "ためし", "appears_when": appears,
            "retires_when": retires or [{"持った": _items(names, 1)[0][1]}]}
    rep = mod.Report()
    mod.check_lead(lead, 0, rep, names, {}, set(), set(), set())
    return [text for level, _where, text in rep.rows if level == "ERROR"]


def test_門番はall_ofの中の条件を1本ずつ見る(names):
    mod = _checker()
    (_a_id, a), (_b_id, b) = _items(names, 2)
    assert _check(mod, names, [{"all_of": [{"聞いた": a}, {"聞いた": b}]}]) == []
    errors = _check(mod, names, [{"all_of": [{"聞いた": a}, {"聞いた": "ぜったいにないなまえ"}]}])
    assert len(errors) == 1 and "ぜったいにないなまえ" in errors[0]


def test_門番は組の形の書き間違いとretiresの組を止める(names):
    mod = _checker()
    (_a_id, a), (_b_id, b) = _items(names, 2)
    assert any("2 つ以上" in e for e in _check(mod, names, [{"all_of": [{"聞いた": a}]}]))
    assert any("retires_all" in e for e in _check(
        mod, names, [{"聞いた": a}], retires=[{"all_of": [{"聞いた": a}, {"聞いた": b}]}]))


def test_門番は一般の語を引ける(tmp_path, monkeypatch, names):
    from dq3.knowledge import concepts as C

    words = tmp_path / "concept-words.csv"
    words.write_bytes("word,evidence,notes\nふしぎなもの,ためし,ためし\n".encode("utf-8"))
    monkeypatch.setattr(C, "CONCEPT_WORDS", words)
    mod = _checker()
    assert _check(mod, names, [{"聞いた": "ふしぎなもの"}]) == []


# --- ★片づいたときの文（`done:` / RX3-0437）-------------------------------------------

DONE_TEXT = "かたづいたときにわかったこと"


def _done_book(tmp_path, names):
    """★`with_done` は done を持ち、`plain` は持たない（⚠ どちらも scenario walk）。"""
    (a_id, a), (b_id, b), (c_id, c), (d_id, d) = _items(names, 4)
    body = ("schema_version: 1\n"
            "scenarios:\n  walk:\n    title: ためしの話\n"
            "leads:\n"
            "  - id: with_done\n    scenario: walk\n    memo: しらべるカード\n"
            "    done: %s\n"
            "    appears_when:\n      - 聞いた: %s\n"
            "    retires_when:\n      - 持った: %s\n"
            "  - id: plain\n    scenario: walk\n    memo: ふつうのカード\n"
            "    appears_when:\n      - 聞いた: %s\n"
            "    retires_when:\n      - 持った: %s\n" % (DONE_TEXT, a, b, c, d))
    return _write(tmp_path, body), dict(a=a_id, b=b_id, c=c_id, d=d_id)


def _rows(view) -> list[str]:
    from dq3.ui.council_window import list_rows

    return [text for _kind, text, _card in list_rows(view)]


def test_doneは片づくまで出ず_片づくと分かったことに出る(tmp_path, names):
    path, ids = _done_book(tmp_path, names)
    active = _council(tmp_path, path, [_heard(ids["a"])]).evaluate(save=False)
    assert DONE_TEXT not in _everything_shown(active), "⚠ 片づく前に分かったことが漏れた"

    done = _council(tmp_path, path, [_heard(ids["a"]), _obtain(ids["b"])]).evaluate(save=False)
    [group] = done.scenarios
    assert [c["done_text"] for c in group.done_cards] == [DONE_TEXT]
    assert any(DONE_TEXT in row and row.lstrip().startswith("✓") for row in _rows(done))
    from dq3.ui.council_window import detail_lines

    assert dict(detail_lines(group.done_cards[0], done))["分かったこと"] == DONE_TEXT


def test_doneが無ければ片づいてもmemoの題名が出る(tmp_path, names):
    path, ids = _done_book(tmp_path, names)
    view = _council(tmp_path, path, [_heard(ids["c"]), _obtain(ids["d"])]).evaluate(save=False)
    assert any("ふつうのカード" in row and row.lstrip().startswith("✓") for row in _rows(view))
    assert DONE_TEXT not in _everything_shown(view)


def test_出ていないカードのdoneは片づいても出ない(tmp_path, names):
    """⚠ 出る条件が未成立のまま片づく条件だけ成立 → ★doneも題名も出さない。"""
    path, ids = _done_book(tmp_path, names)
    view = _council(tmp_path, path, [_obtain(ids["b"])]).evaluate(save=False)
    assert DONE_TEXT not in _everything_shown(view)
    assert view.scenarios == []

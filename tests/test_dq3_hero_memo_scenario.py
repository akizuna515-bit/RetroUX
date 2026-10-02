"""勇者メモの scenario（RX3-0434 / 2026-09-27）。

## ★固定すること

```text
No-Spoiler   ⚠ 未出のカードの memo・件数・存在が ScenarioView / list_rows に漏れない
quiet 復帰   open → 全部片づく → quiet → 新しいカード → open
並び         ★出た順（⚠ id 順・YAML の順ではない）
定義         未定義の参照 ERROR / 所属 0 WARNING / 所属 1 INFO / 知らない最上位 ERROR
```

⚠ 見本の名前は ROM の辞書から借ります（★原作の語を検査に書かない）。
"""
from __future__ import annotations

import re

import pytest

yaml = pytest.importorskip("yaml")

from tests.test_dq3_hero_memo_council import _a_name, _council, _fact  # noqa: E402

#: ⚠ 未出のカードの memo（★この文字列が画面側のどこにも出てはいけない）
SECRET = "まだしらないはずのカード"


@pytest.fixture
def names():
    from dq3.knowledge import guide_mapping
    from dq3.knowledge import rom_names

    rom_names.reset()
    index = guide_mapping.name_index()
    if not index:
        pytest.skip("⚠ ROM の名前辞書が読めません: %s" % rom_names.last_error)
    return index


def _items(index, n):
    """★道具の名前を n 個借りる（⚠ 同じ綴りが 2 id に当たらないもの）。"""
    got = []
    for (kind, _folded), hits in index.items():
        if kind == "item" and len(hits) == 1:
            got.append(hits[0])
        if len(got) == n:
            return got
    pytest.skip("⚠ 道具の名前が足りない")


def _write(tmp_path, body: str):
    path = tmp_path / "hero-memo.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + body.replace("\n", "\r\n").encode("utf-8"))
    return path


def _lead(lead_id, memo, heard, obtained, scenario="walk"):
    """★「その品の名前を聞いたら出る / 持ったら片づく」1 件。"""
    return ("  - id: %s\n"
            "    scenario: %s\n"
            "    memo: %s\n"
            "    appears_when:\n"
            "      - 聞いた: %s\n"
            "    retires_when:\n"
            "      - 持った: %s\n" % (lead_id, scenario, memo, heard, obtained))


def _book(tmp_path, names, *, secret=True):
    """★3 枚の scenario 見本。

    ```text
    zz_first    ★id は後ろだが、いちばん先に出る
    aa_second   ★id は前だが、後から出る
    mm_secret   ⚠ 最後まで出さない（No-Spoiler の見張り）
    ```
    """
    (a_id, a), (b_id, b), (c_id, c), (d_id, d), (e_id, e), (f_id, f) = _items(names, 6)
    body = ("schema_version: 1\n"
            "scenarios:\n"
            "  walk:\n"
            "    title: ためしの話\n"
            "leads:\n"
            + _lead("aa_second", "あとから出たカード", c, d)
            + _lead("zz_first", "さきに出たカード", a, b)
            + (_lead("mm_secret", SECRET, e, f) if secret else ""))
    ids = {"a": a_id, "b": b_id, "c": c_id, "d": d_id, "e": e_id, "f": f_id}
    return _write(tmp_path, body), ids


def _heard(item_id):
    return _fact("item:%d" % item_id, "heard", obs="obs-%d" % item_id)


def _obtain(item_id):
    return _fact("item:%d" % item_id, "obtain", obs="obs-o%d" % item_id)


#: ⚠⚠ 日時の札（`09/30 08:04`）。★照合の前に伏せる（RX3-0477）
#
#   ⚠ 「分母を出していないこと」を `"/3" not in shown` で見ていたので、
#     ★毎月 30・31 日だけ日付の `/3` に当たって赤くなっていました
#     （⚠ `"1/"` のほうは 1・11・21・31 日に当たります）。
#   ★伏せるのは**毎回変わるもの**だけです（⚠ No-Spoiler の照合は緩めません）。
#
#   ⚠⚠ **時刻まで必須**にしています（`dq3/knowledge/council.py::_short` の
#     `%m/%d %H:%M` そのまま）。★`\d/\d` だけにすると、⚠ 本物の分母
#     （`1/3 枚`）まで伏せてしまい、**検査が何も守らなくなります**。
_DATETIME_LABEL = re.compile(r"\d{2}/\d{2} \d{2}:\d{2}")


def _everything_shown(view) -> str:
    """★画面側に渡る文字を全部つなぐ（⚠ ScenarioView ＋ list_rows）。

    ⚠ 日時の札は `<日時>` に伏せます（★`RX3-0477`）。
    """
    from dq3.ui.council_window import list_rows

    parts = [repr(view.scenarios)]
    parts += [text for _kind, text, _card in list_rows(view)]
    parts += [repr(card) for _kind, _text, card in list_rows(view) if card]
    return _DATETIME_LABEL.sub("<日時>", "\n".join(parts))


# --- ⚠⚠ 日時の札が「分母」に見えないこと（RX3-0477）-------------------------

@pytest.mark.parametrize("label", [
    "09/30 08:04",   # ⚠ 実際に赤くなった日（★"/3" に当たる）
    "10/31 23:59",   # ⚠ "/3" と "1/" の両方
    "11/01 00:00",   # ⚠ "1/" に当たる
    "01/21 09:05",   # ⚠ "1/" に当たる
])
def test_日時の札は分母に見えない(label) -> None:
    """★毎月数日だけ赤くなる検査にしないこと。"""
    got = _DATETIME_LABEL.sub("<日時>", "'update_label': '%s'" % label)
    assert "/3" not in got and "1/" not in got, got


@pytest.mark.parametrize("text", ["のこり 1/3 枚", "2/3", "あと 1/10"])
def test_本物の分母は伏せない(text) -> None:
    """⚠⚠ ここが緩むと No-Spoiler の検査が**何も守らなくなります**。"""
    got = _DATETIME_LABEL.sub("<日時>", text)
    assert got == text, "⚠ 分母まで伏せている: %r" % got


# --- ★No-Spoiler -------------------------------------------------------------

def test_未出のカードはScenarioViewにもlist_rowsにも漏れない(tmp_path, names):
    path, ids = _book(tmp_path, names)
    facts = [_heard(ids["a"])]                     # ★zz_first だけ出る
    view = _council(tmp_path, path, facts).evaluate(save=False)
    assert view.ok, view.error

    [group] = view.scenarios
    assert group.title == "ためしの話"
    assert [c["topic_id"] for c in group.open_cards] == ["zz_first"]
    assert group.done_cards == ()
    shown = _everything_shown(view)
    # ⚠ memo も id も出ない
    assert SECRET not in shown
    assert "mm_secret" not in shown and "aa_second" not in shown
    # ⚠ 件数・分母・「???」を出さない
    assert "???" not in shown and "/3" not in shown and "（3）" not in shown
    assert "1/" not in shown


def test_1枚も出ていないscenarioは題名も出ない(tmp_path, names):
    path, _ids = _book(tmp_path, names)
    view = _council(tmp_path, path, []).evaluate(save=False)
    assert view.scenarios == []
    assert "ためしの話" not in _everything_shown(view)


# --- ★quiet 復帰 -------------------------------------------------------------

def test_全部片づいてもresolvedにせずquietで新しいカードが出ればopenに戻る(tmp_path, names):
    from dq3.knowledge import scenario_view as SV
    from dq3.ui.council_window import list_rows

    path, ids = _book(tmp_path, names)
    facts = [_heard(ids["a"])]
    view = _council(tmp_path, path, facts).evaluate(save=True)
    assert [g.state for g in view.scenarios] == [SV.OPEN]

    # ★見えている 1 枚を片づける → quiet（⚠ 「完了」ではない）
    facts += [_obtain(ids["b"])]
    view = _council(tmp_path, path, facts).evaluate(save=True)
    [group] = view.scenarios
    assert group.state == SV.QUIET
    assert group.open_cards == ()
    assert [c["topic_id"] for c in group.done_cards] == ["zz_first"]
    heads = [text for kind, text, _c in list_rows(view) if text.startswith("■")]
    assert heads == ["■ ためしの話 — %s" % SV.QUIET_TEXT]
    assert "完了" not in heads[0] and "続き" not in heads[0]

    # ★新しいカードが出る → open に戻る
    facts += [_heard(ids["c"])]
    view = _council(tmp_path, path, facts).evaluate(save=True)
    [group] = view.scenarios
    assert group.state == SV.OPEN
    assert [c["topic_id"] for c in group.open_cards] == ["aa_second"]
    assert [c["topic_id"] for c in group.done_cards] == ["zz_first"]
    assert SECRET not in _everything_shown(view)


def test_状態は3つだけでresolvedは無い():
    from dq3.knowledge import scenario_view as SV

    assert SV.state_of([]) == SV.HIDDEN
    assert SV.state_of(["unknown", "unknown"]) == SV.HIDDEN
    assert SV.state_of(["unknown", "active"]) == SV.OPEN
    assert SV.state_of(["resolved", "active"]) == SV.OPEN
    assert SV.state_of(["resolved", "unknown"]) == SV.QUIET
    assert not hasattr(SV, "RESOLVED_STATE")


# --- ★並び -------------------------------------------------------------------

@pytest.mark.parametrize("order", ["first_z", "first_a"])
def test_気になっていることは出た順でid順ではない(tmp_path, names, order):
    """⚠ 1 例だけだと id 順と偶然一致するので、★逆の順でも確かめる。"""
    path, ids = _book(tmp_path, names)
    if order == "first_z":
        facts, want = [_heard(ids["a"]), _heard(ids["c"])], ["zz_first", "aa_second"]
    else:
        facts, want = [_heard(ids["c"]), _heard(ids["a"])], ["aa_second", "zz_first"]
    view = _council(tmp_path, path, facts).evaluate(save=False)
    [group] = view.scenarios
    assert [c["topic_id"] for c in group.open_cards] == want


def test_分かったことは片づいた順の新しいほうから(tmp_path, names):
    path, ids = _book(tmp_path, names, secret=False)
    facts = [_heard(ids["a"]), _heard(ids["c"]), _obtain(ids["d"]), _obtain(ids["b"])]
    view = _council(tmp_path, path, facts).evaluate(save=False)
    [group] = view.scenarios
    # ★d（aa_second）が先に片づき、b（zz_first）が後 → 新しいほうが上
    assert [c["topic_id"] for c in group.done_cards] == ["zz_first", "aa_second"]


def test_scenarioどうしは最近動いた順で定義の順ではない(tmp_path, names):
    (a_id, a), (b_id, b), (c_id, c), (d_id, d) = _items(names, 4)
    body = ("schema_version: 1\n"
            "scenarios:\n"
            "  one:\n"
            "    title: さきに定義した話\n"
            "  two:\n"
            "    title: あとに定義した話\n"
            "leads:\n"
            + _lead("x1", "ひとつめ", a, b, scenario="one")
            + _lead("x2", "ふたつめ", c, d, scenario="two"))
    path = _write(tmp_path, body)
    view = _council(tmp_path, path, [_heard(a_id), _heard(c_id)]).evaluate(save=False)
    assert [g.title for g in view.scenarios] == ["あとに定義した話", "さきに定義した話"]
    view = _council(tmp_path, path, [_heard(c_id), _heard(a_id)]).evaluate(save=False)
    assert [g.title for g in view.scenarios] == ["さきに定義した話", "あとに定義した話"]


# --- ★定義の検査（⚠ 読み込みと門番が同じ判定を使う）-------------------------

def _doc(scenarios, leads, extra=None):
    doc = {"schema_version": 1, "scenarios": scenarios, "leads": leads}
    doc.update(extra or {})
    return doc


def _card(lead_id, scenario=None):
    got = {"id": lead_id, "memo": "ためし", "appears_when": [{"フラグ": "x"}],
           "retires_when": [{"フラグ": "y"}]}
    if scenario is not None:
        got["scenario"] = scenario
    return got


def _levels(doc):
    from dq3.knowledge.hero_memo import scenario_problems

    return [(level, where) for level, where, _text in scenario_problems(doc)]


def test_未定義のscenarioを指すとERROR():
    got = _levels(_doc({"one": {"title": "t"}}, [_card("a", "one"), _card("b", "nothing")]))
    assert ("ERROR", "leads[1] b") in got


def test_所属0件のscenarioはWARNING_1件はINFO():
    got = _levels(_doc({"zero": {"title": "t0"}, "single": {"title": "t1"}},
                       [_card("a", "single")]))
    assert ("WARNING", "scenarios.zero") in got
    assert ("INFO", "scenarios.single") in got
    assert not [lv for lv, _ in got if lv == "ERROR"]


def test_知らない最上位の項目はERROR():
    got = _levels(_doc({}, [], extra={"scenarioes": {}}))
    assert ("ERROR", "scenarioes") in got


@pytest.mark.parametrize("key", ["order", "sequence", "priority", "parent",
                                 "prerequisite", "next", "appears_when"])
def test_scenarioにtitle以外は書けない(key):
    got = _levels(_doc({"one": {"title": "t", key: 1}}, [_card("a", "one")]))
    assert ("ERROR", "scenarios.one") in got


def test_門番も同じ判定を出す(capsys):
    """⚠ 読み込みと門番で判定が割れない（★`check_document` は同じ関数を呼ぶ）。"""
    import importlib.util
    import pathlib

    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "dq3_hero_memo_check.py"
    if not script.is_file():
        # ⚠ 公開版は門番のスクリプトを同梱しない（★開発用 / manifest の include に無い）
        pytest.skip("★公開版には scripts/dq3_hero_memo_check.py がありません")
    spec = importlib.util.spec_from_file_location("dq3_hero_memo_check", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rep = mod.Report()
    mod.check_document(_doc({"zero": {"title": "t"}}, [_card("b", "nothing")],
                            extra={"oops": 1}), rep)
    assert rep.count("ERROR") == 2          # ★未定義の参照 ＋ 知らない最上位
    assert rep.count("WARNING") == 1        # ★所属 0 件


def test_strictでない読み込みは未定義のscenarioのカードを落とさず単独にする(tmp_path):
    from dq3.knowledge import hero_memo as HM

    path = tmp_path / "hero-memo.yaml"
    path.write_bytes(yaml.safe_dump(_doc({"one": {"title": "t"}},
                                         [_card("a", "one"), _card("b", "nothing")]),
                                    allow_unicode=True).encode("utf-8"))
    with pytest.raises(HM.HeroMemoError, match="定義されていません"):
        HM.load(path, strict=True)
    problems: list = []
    titles, got = HM.load_document(path, strict=False, problems=problems)
    assert [(l.lead_id, l.scenario) for l in got] == [("a", "one"), ("b", "")]
    assert problems and "定義されていません" in problems[0]
    assert titles == {"one": "t"}


def test_all_of_falseは書かなくても同じで_trueは止める(tmp_path):
    from dq3.knowledge import hero_memo as HM

    ok = _card("a")
    ok["all_of"] = False
    path = tmp_path / "hero-memo.yaml"
    path.write_bytes(yaml.safe_dump(_doc({}, [ok, _card("b")]),
                                    allow_unicode=True).encode("utf-8"))
    assert [l.lead_id for l in HM.load(path)] == ["a", "b"]
    bad = _card("c")
    bad["all_of"] = True
    path.write_bytes(yaml.safe_dump(_doc({}, [bad]), allow_unicode=True).encode("utf-8"))
    with pytest.raises(HM.HeroMemoError, match="出る側には効きません"):
        HM.load(path)


# --- ★詳細の「何の話」（RX3-0445）------------------------------------------------

def test_詳細に分類を出さず何の話を出す(tmp_path, names):
    """⚠⚠ 「分類 探索 / priority 50」は**全カード同じ固定値**だった（★出さない）。"""
    from dq3.ui.council_window import detail_lines

    path, ids = _book(tmp_path, names, secret=False)
    view = _council(tmp_path, path, [_heard(ids["a"])]).evaluate(save=False)
    card = next(c for c in view.recent if c["topic_id"] == "zz_first")
    rows = dict(detail_lines(card, view))
    assert "分類" not in rows, "⚠⚠ 固定値の「分類」がまだ出ている"
    assert rows["何の話"] == "ためしの話"
    assert "priority" not in repr(rows)


def test_scenarioの無いカードでは何の話の行を出さない(tmp_path, names):
    from dq3.ui.council_window import detail_lines

    (a_id, a), (b_id, b) = _items(names, 2)
    path = _write(tmp_path, ("schema_version: 1\nleads:\n  - id: alone\n    memo: ひとりのカード\n"
                             "    appears_when:\n      - 聞いた: %s\n"
                             "    retires_when:\n      - 持った: %s\n" % (a, b)))
    view = _council(tmp_path, path, [_heard(a_id)]).evaluate(save=False)
    card = next(c for c in view.recent if c["topic_id"] == "alone")
    rows = dict(detail_lines(card, view))
    assert "何の話" not in rows and "分類" not in rows

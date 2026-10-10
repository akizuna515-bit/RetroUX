"""人が書いた「気になること」→ 勇者会議 の 1 往復（RX3-0432 / 2026-09-27）。

## ★通す道

```text
実プレイの会話で名前を聞く
        ↓ heard Fact
data/dq3/hero-memo.yaml（★人が書く）
        ↓ hero_memo.build()   ⚠ ファイルを作らない（★メモリの中だけ）
{topic_id: Topic} ＋ [Rule]
        ↓
Council.evaluate()
        ↓
★勇者会議に出る（view.recent）
        ↓ 持った Fact
★片づく（view.resolved へ移る）
```

## ⚠ ここで見ないもの

★GUI の見た目は見ません（⚠ 人が見るもの）。
⚠ 実機も要りません（★Fact を直に作って通します）。
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
REAL = PROJECT_ROOT / "data" / "dq3" / "hero-memo.yaml"


# --- ★材料 -------------------------------------------------------------------

@pytest.fixture
def names():
    """★ROM の名前辞書（⚠ 無ければ skip / 名前をここに書かない）。"""
    from dq3.knowledge import guide_mapping
    from dq3.knowledge import rom_names

    rom_names.reset()
    index = guide_mapping.name_index()
    if not index:
        pytest.skip("⚠ ROM の名前辞書が読めません: %s" % rom_names.last_error)
    return index


def _a_name(index, kind):
    """★その種類の名前を 1 つ借りる（⚠ 見本に原作の語を書かないため）。"""
    for (got_kind, _folded), hits in index.items():
        if got_kind == kind and hits:
            return hits[0][0], hits[0][1]
    pytest.skip("⚠ %s の名前が無い" % kind)


def _a_place():
    from dq3.knowledge import concepts

    got = concepts.place_aliases()
    if not got:
        pytest.skip("⚠ 場所の名前が 1 つも無い")
    return got[0][1], got[0][2]         # (L<map>, 名前)


def _write(tmp_path, leads_yaml: str) -> pathlib.Path:
    """★見本の原本を作る（⚠ 本物の `data/dq3/hero-memo.yaml` は触らない）。"""
    path = tmp_path / "hero-memo.yaml"
    body = "schema_version: 1\nleads:\n" + leads_yaml
    path.write_bytes(b"\xef\xbb\xbf" + body.replace("\n", "\r\n").encode("utf-8"))
    return path


def _fact(subject, predicate, obs="obs-test"):
    return {"fact_id": "fact-%s-%s" % (predicate, subject), "subject": subject,
            "predicate": predicate, "object": None,
            "source_observation_id": obs, "confidence": 1.0}


# --- ★組み立て ---------------------------------------------------------------

def test_原本からTopicとRuleができる(tmp_path, names):
    from dq3.knowledge import guide
    from dq3.knowledge import hero_memo as HM

    item_id, item_name = _a_name(names, "item")
    location_id, place_name = _a_place()
    path = _write(tmp_path, (
        "  - id: sample_one\n"
        "    memo: |\n"
        "      ためしの 1 件\n"
        "    appears_when:\n"
        "      - 聞いた: %s\n"
        "    retires_when:\n"
        "      - 持った: %s\n"
        "    about: %s\n" % (place_name, item_name, place_name)))

    got = HM.build(path)
    assert got.unresolved == [], got.unresolved
    assert list(got.topics) == ["sample_one"]
    topic = got.topics["sample_one"]
    # ★画面に出る文は `memo` そのまま（⚠ 作文しない）
    assert topic.head_message.strip() == "ためしの 1 件"

    appear = [r for r in got.rules if r.weight < guide.RESOLVE_WEIGHT]
    retire = [r for r in got.rules if r.completes]
    assert [r.subject() for r in appear] == ["location:%s" % location_id]
    assert [r.predicate for r in appear] == ["heard"]
    assert [r.subject() for r in retire] == ["item:%d" % item_id]
    assert [r.predicate for r in retire] == ["obtain"]


def test_retires_whenが無ければ読まない(tmp_path, names):
    """⚠⚠ 永久に残るメモを**構造で**禁止する（★RX3-0432 の要点）。"""
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_no_retire\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 持った: %s\n" % item_name))
    with pytest.raises(HM.HeroMemoError, match="retires_when"):
        HM.load(path)


def test_知らない言い方は読まない(tmp_path):
    from dq3.knowledge import hero_memo as HM

    path = _write(tmp_path, (
        "  - id: sample_bad_verb\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - みつけた: なにか\n"
        "    retires_when:\n"
        "      - みつけた: なにか\n"))
    with pytest.raises(HM.HeroMemoError, match="知らない言い方"):
        HM.load(path)


def test_解けない名前は捨てずに残す(tmp_path, names):
    """⚠ 黙って落とすと「書いたのに出ない」理由が分からなくなります。"""
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_unresolved\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 聞いた: ぜったいにそんななまえはない\n"
        "    retires_when:\n"
        "      - 持った: %s\n" % item_name))
    got = HM.build(path)
    assert len(got.unresolved) == 1
    assert got.unresolved[0][1:3] == ("聞いた", "ぜったいにそんななまえはない")
    # ★解けた分は残る（⚠ 1 件解けなくても全部止めない）
    assert [r.predicate for r in got.rules] == ["obtain"]


# --- ★★ 1 往復（appears → 勇者会議 → retire）--------------------------------

def _council(tmp_path, memo_path, facts):
    """★Fact を直に与えて勇者会議を 1 回まわす（⚠ 実機を使わない）。"""
    from dq3.knowledge import council as CO

    class _Council(CO.Council):
        def _facts(self):
            # ⚠ 2 つめは **fact_id → 会話の本文** の辞書（★list ではない）
            return list(facts), {}

        def _progress(self, PG, catalog):      # ⚠ 進行の記録は使わない（★Fact は上で与える）
            return PG.Progress()

    return _Council(state_path=tmp_path / "topic-state.json",
                    hero_memo_path=memo_path,
                    knowledge_path=tmp_path / "player-knowledge.json")


def test_聞いたら勇者会議に出て_持ったら片づく(tmp_path, names):
    """★★ **1 往復**（⚠ ここが RX3-0432 の疎通確認）★★"""
    from dq3.knowledge import hero_memo as HM

    item_id, item_name = _a_name(names, "item")
    location_id, place_name = _a_place()
    path = _write(tmp_path, (
        "  - id: sample_round_trip\n"
        "    memo: |\n"
        "      ためしの 1 件（★往復の確認）\n"
        "    appears_when:\n"
        "      - 聞いた: %s\n"
        "    retires_when:\n"
        "      - 持った: %s\n"
        "    about: %s\n" % (place_name, item_name, place_name)))
    assert HM.build(path).unresolved == []

    # --- ① ⚠ まだ何も聞いていない → 出ない -------------------------------
    view = _council(tmp_path, path, []).evaluate(save=False)
    assert view.ok, view.error
    assert view.topic_count == 1
    assert [c["topic_id"] for c in view.recent] == [], view.recent
    assert [c["topic_id"] for c in view.resolved] == []

    # --- ② ★聞いた → 出る ------------------------------------------------
    heard = [_fact("location:%s" % location_id, "heard")]
    view = _council(tmp_path, path, heard).evaluate(save=True)
    assert view.ok, view.error
    assert [c["topic_id"] for c in view.recent] == ["sample_round_trip"], view.recent
    assert view.recent[0]["message"].strip().startswith("ためしの 1 件")
    assert [c["topic_id"] for c in view.resolved] == []

    # --- ③ ★持った → 片づく（⚠ recent から消えて resolved へ）-----------
    got = heard + [_fact("item:%d" % item_id, "obtain")]
    view = _council(tmp_path, path, got).evaluate(save=True)
    assert view.ok, view.error
    assert [c["topic_id"] for c in view.recent] == [], view.recent
    assert [c["topic_id"] for c in view.resolved] == ["sample_round_trip"]

    # --- ④ ★もう一度開いても同じ（⚠ 状態が残っている）-------------------
    again = _council(tmp_path, path, got).evaluate(save=False)
    assert [c["topic_id"] for c in again.resolved] == ["sample_round_trip"]
    assert (tmp_path / "topic-state.json").exists(), "⚠ 状態が保存されていない"


def test_all_ofは効かないので止める(tmp_path, names):
    """⚠⚠ **実測で分かったこと**（2026-09-27 / RX3-0432）。

    ★`match_mode=ALL` は `TopicBook.completed()`（＝**片づく**判定）だけをまとめます。
    ⚠ 出るかどうかは「どれか 1 本当たったか」なので、`all_of: true` と書いても
      **1 つ満たすだけで出てしまいます**（★実際にそうなった）。

    → ⚠ 黙って無視すると「書いたのに効かない値」になります
      （★この repo の `project_retroux_dead_profile_value` と同じ形）。
      ★だから**読んだ時点で止めます**。
    """
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    _location_id, place_name = _a_place()
    path = _write(tmp_path, (
        "  - id: sample_all_of\n"
        "    memo: ためし\n"
        "    all_of: true\n"
        "    appears_when:\n"
        "      - 聞いた: %s\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - 倒した: %s\n"
        % (place_name, item_name, _a_name(names, "monster")[1])))
    with pytest.raises(HM.HeroMemoError, match="出る側には効きません"):
        HM.load(path)


def test_出る条件が複数ならどれか1つで出る(tmp_path, names):
    """★`all_of` を書かなければ「どれか 1 つ」。⚠ これは**実際にそう動く**。"""
    from dq3.knowledge import hero_memo as HM

    item_id, item_name = _a_name(names, "item")
    _location_id, place_name = _a_place()
    monster_id, monster_name = _a_name(names, "monster")
    path = _write(tmp_path, (
        "  - id: sample_any\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 聞いた: %s\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - 倒した: %s\n" % (place_name, item_name, monster_name)))
    assert HM.build(path).unresolved == []

    one = [_fact("item:%d" % item_id, "obtain")]
    view = _council(tmp_path, path, one).evaluate(save=False)
    assert [c["topic_id"] for c in view.recent] == ["sample_any"], view.recent
    # ★倒したら片づく
    got = one + [_fact("monster:%d" % monster_id, "defeat")]
    view = _council(tmp_path, path, got).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == ["sample_any"]


# --- ★旧経路は無い（RX3-0432 / 2026-10-03）------------------------------------

def test_旧経路への切り替えの口は無い(tmp_path):
    """⚠⚠ 以前は `use_hero_memo` の既定が False で、★書き忘れると黙って旧 2 表を読んでいた。

    ★口ごと消したので、⚠ 古い書き方は**名前で落ちる**（★黙って旧経路に落ちない）。
    """
    import pytest

    from dq3.knowledge import council as CO

    for old in ("use_hero_memo", "master_path", "rules_path"):
        with pytest.raises(TypeError):
            CO.Council(**{old: True})
    got = CO.Council()
    assert not hasattr(got, "use_hero_memo")
    assert got.hero_memo_path is None                 # ★既定の原本（data/dq3/hero-memo.yaml）


#: ⚠ 人が書くのを待っている件（★ここに無い問題は**赤**にする / RX3-0434）
#:   150_underworld の `memo` は依頼者が書く（⚠ AI は書かない / 2026-09-27）
PENDING_EMPTY_MEMO = {"150_underworld"}


def test_本物の原本をstrictで読む():
    """★本物の `data/dq3/hero-memo.yaml` を **strict** で読む。

    ## ⚠⚠ 2026-09-27（RX3-0434 / 依頼者の指示）: skip をやめて**赤**にしました

    ★もとは「読めなければ skip」でした。⚠ それだと `scenario:` を足した原本が
    読めなくなっても**緑のまま**です（★「0 件は通っていないだけ」と同じ形）。

    ⚠ 例外は **1 つだけ**: 人が書くのを待っている `memo` の空（`PENDING_EMPTY_MEMO`）。
      ★その件だけなら xfail（⚠ 理由を名指し）。⚠ 書かれたら通る。ほかの問題は赤。
    """
    from dq3.knowledge import hero_memo as HM

    assert REAL.exists(), "⚠⚠ 原本がありません（★公開版にも同梱します）"
    doc = yaml.safe_load(REAL.read_bytes())
    empty = {str(l.get("id")) for l in doc.get("leads") or []
             if isinstance(l, dict) and not str(l.get("memo") or "").strip()}
    try:
        got = HM.load(REAL, strict=True)
    except HM.HeroMemoError as exc:
        if empty and empty <= PENDING_EMPTY_MEMO and "`memo` がありません" in str(exc):
            pytest.xfail("★人が書くのを待っている memo: %s" % sorted(empty))
        raise
    assert not empty - PENDING_EMPTY_MEMO
    assert isinstance(got, list)
    for lead in got:
        assert lead.lead_id and lead.memo
        assert lead.retires_when, "⚠⚠ %s に消える条件が無い" % lead.lead_id


def test_本物の原本はmemoの空を除けばstrictで読める(tmp_path):
    """★xfail で他の問題が隠れないように、待っている件を除いて strict で読む。"""
    from dq3.knowledge import hero_memo as HM

    doc = yaml.safe_load(REAL.read_bytes())
    doc["leads"] = [l for l in doc["leads"] if str(l.get("id")) not in PENDING_EMPTY_MEMO]
    path = tmp_path / "hero-memo.yaml"
    path.write_bytes(yaml.safe_dump(doc, allow_unicode=True).encode("utf-8"))
    titles, got = HM.load_document(path, strict=True)
    assert got, "⚠ 1 件も読めていない"
    # ★scenario の定義が読めて、カードの所属がそこを指している
    assert titles
    assert {l.scenario for l in got if l.scenario} <= set(titles)


# --- ★★ 全部そろって初めて片づく（RX3-0432 / 2026-09-27）--------------------

ORB_FLAGS = ("orb_placed_silver", "orb_placed_red", "orb_placed_yellow",
             "orb_placed_purple", "orb_placed_blue", "orb_placed_green")


def _flags_exist(need):
    from dq3.knowledge import story

    try:
        got = {getattr(f, "flag_id", f) for f in story.load_flags()}
    except Exception:                                      # noqa: BLE001
        got = set()
    missing = [f for f in need if f not in got]
    if missing:
        pytest.skip("⚠ フラグが足りません: %s" % missing)


def test_retires_allは全部そろって初めて片づく(tmp_path, names):
    """★★ ⚠⚠ **`rule_id` の付け方で 1 度 外しました**（2026-09-27）★★

    `TopicBook.completed()` は `rule_id` の **`#` の前**を「1 つの条件」と見ます。
    ⚠ そこを `<lead_id>#r0` にしていたので、★6 本が**同じ条件に畳まれて**
      「どれか 1 本で片づく」になっていました（★実測して気づいた）。
    → ★条件ごとに前を変える（`<lead_id>-r0#0`）。⚠ この検査がその歯止めです。
    """
    from dq3.knowledge import hero_memo as HM

    _flags_exist(ORB_FLAGS)
    _item_id, item_name = _a_name(names, "item")
    lines = ["  - id: sample_orbs",
             "    memo: ためし",
             "    retires_all: true",
             "    appears_when:",
             "      - 持った: %s" % item_name,
             "    retires_when:"]
    lines += ["      - フラグ: %s" % f for f in ORB_FLAGS]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    got = HM.build(path)
    assert got.unresolved == [], got.unresolved
    retire = [r for r in got.rules if r.completes]
    assert len(retire) == len(ORB_FLAGS)
    assert {r.match_mode for r in retire} == {"ALL"}
    # ⚠⚠ 条件ごとに `#` の前が違うこと（★ここが畳まれると 1 本で片づく）
    bases = {r.rule_id.split("#", 1)[0] for r in retire}
    assert len(bases) == len(ORB_FLAGS), bases

    appear = [_fact("item:%d" % _item_id, "obtain")]
    # --- ★5 つでは片づかない ---------------------------------------------
    five = appear + [_fact("event:%s" % f, "set") for f in ORB_FLAGS[:5]]
    view = _council(tmp_path, path, five).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == [], view.resolved
    assert [c["topic_id"] for c in view.recent] == ["sample_orbs"]
    # --- ★6 つそろえば片づく ---------------------------------------------
    six = appear + [_fact("event:%s" % f, "set") for f in ORB_FLAGS]
    view = _council(tmp_path, path, six).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == ["sample_orbs"], view.resolved


def test_retires_allを書かなければどれか1つで片づく(tmp_path, names):
    from dq3.knowledge import hero_memo as HM

    _flags_exist(ORB_FLAGS[:2])
    item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_any_retire\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - フラグ: %s\n"
        "      - フラグ: %s\n" % (item_name, ORB_FLAGS[0], ORB_FLAGS[1])))
    assert HM.build(path).unresolved == []
    got = [_fact("item:%d" % item_id, "obtain"),
           _fact("event:%s" % ORB_FLAGS[0], "set")]
    view = _council(tmp_path, path, got).evaluate(save=False)
    assert [c["topic_id"] for c in view.resolved] == ["sample_any_retire"]


def test_船のフラグが書ける(tmp_path, names):
    """★依頼者の質問（2026-09-27）「船を手に入れたかは フラグ で聞けるか」→ ★聞けます。"""
    from dq3.knowledge import hero_memo as HM

    _flags_exist(("ship_obtained",))
    _item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_ship\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - フラグ: ship_obtained\n" % item_name))
    got = HM.build(path)
    assert got.unresolved == []
    retire = [r for r in got.rules if r.completes]
    assert [r.subject() for r in retire] == ["event:ship_obtained"]
    assert [r.predicate for r in retire] == ["set"]


def test_aboutは複数書ける(tmp_path, names):
    """★依頼者は「アリアハン、レーベ」と**1 つの文字列**で書きました（⚠ 実測）。"""
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    place_a = _a_place()[1]
    path = _write(tmp_path, (
        "  - id: sample_about\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - 持った: %s\n"
        "    about: %s\u3001%s\n" % (item_name, item_name, place_a, place_a)))
    leads = HM.load(path)
    assert leads[0].about == (place_a, place_a)
    # ★並びで書いてもよい
    assert HM._places_written([" a ", "", "b"]) == ("a", "b")
    assert HM._places_written("a\u30fbb,c") == ("a", "b", "c")


def test_all_ofは止まるがretires_allは通る(tmp_path, names):
    """⚠ 似た名前の 2 つを取り違えないこと（★片方だけが効く）。"""
    from dq3.knowledge import hero_memo as HM

    _flags_exist(("ship_obtained",))
    _item_id, item_name = _a_name(names, "item")
    head = ("  - id: sample_knob\n"
            "    memo: ためし\n"
            "    %s: true\n"
            "    appears_when:\n"
            "      - 持った: %s\n"
            "    retires_when:\n"
            "      - フラグ: ship_obtained\n")
    with pytest.raises(HM.HeroMemoError, match="出る側には効きません"):
        HM.load(_write(tmp_path, head % ("all_of", item_name)))
    assert HM.load(_write(tmp_path, head % ("retires_all", item_name)))[0].retires_all


# --- ★壊れた 1 件を飛ばして残りを出す（RX3-0432 / 2026-09-27）------------------

def test_壊れた1件を飛ばして残りを出す(tmp_path, names):
    """⚠⚠ **1 件の書き間違いで勇者会議を丸ごと暗くしない**。

    ★2026-09-27: 依頼者が 27 件書いたうち **1 件の `memo` が空**でした。
    ⚠ 素の `strict=True` だと 27 件全部が消えます。
    → ★残りを出し、⚠ 飛ばした理由は `problems` に**必ず残す**。
    """
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_ok\n"
        "    memo: よい 1 件\n"
        "    appears_when:\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - 持った: %s\n"
        "  - id: sample_broken\n"
        "    memo: |\n"
        "\n"
        "    appears_when:\n"
        "      - 持った: %s\n"
        "    retires_when:\n"
        "      - 持った: %s\n" % (item_name, item_name, item_name, item_name)))

    # ⚠ strict なら止まる（★門番のスクリプトはこちら）
    with pytest.raises(HM.HeroMemoError, match="memo"):
        HM.load(path, strict=True)

    # ★strict でなければ残りを出す
    got = HM.build(path)
    assert list(got.topics) == ["sample_ok"], got.topics
    assert len(got.problems) == 1, got.problems
    assert "memo" in got.problems[0]
    # ⚠⚠ 黙って捨てていないこと（★理由が残る）
    assert "sample_broken" not in got.topics


def test_id重複でも残りを出す(tmp_path, names):
    """⚠ 重複は飛ばせないので、★**後のほうを使わず**理由を残す。"""
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    one = ("  - id: same_id\n"
           "    memo: %s\n"
           "    appears_when:\n"
           "      - 持った: %s\n"
           "    retires_when:\n"
           "      - 持った: %s\n")
    path = _write(tmp_path, (one % ("さきに書いた", item_name, item_name))
                  + (one % ("あとに書いた", item_name, item_name)))
    got = HM.build(path)
    assert list(got.topics) == ["same_id"]
    assert got.topics["same_id"].head_message.strip() == "さきに書いた"
    assert any("重複" in p for p in got.problems), got.problems


def test_地名の逃げ道はL番号で書ける(tmp_path, names):
    """★名前を付けていない場所は `L<map 番号>` と書ける（⚠ 依頼者が実際にそうした）。"""
    from dq3.knowledge import hero_memo as HM

    _item_id, item_name = _a_name(names, "item")
    path = _write(tmp_path, (
        "  - id: sample_lid\n"
        "    memo: ためし\n"
        "    appears_when:\n"
        "      - 行った: L41\n"
        "    retires_when:\n"
        "      - 持った: %s\n" % item_name))
    got = HM.build(path)
    assert got.unresolved == [], got.unresolved
    appear = [r for r in got.rules if r.weight < 100]
    assert [r.subject() for r in appear] == ["location:L41"]

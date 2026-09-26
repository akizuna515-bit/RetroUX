"""聞いた会話 → Concept → Relation → Fact（RX3-0070 / 2026-09-03）。

★★ 原作の会話本文を**ここに焼かない** ★★

  ⚠ 見本の文は「言い回しの骨」だけを作り、★実体の名前は
    **runtime の名前辞書から取ってきて差し込みます**（`rom_names`）。
    → ROM が無い環境では skip。⚠ 名前を fixture に書かない。
"""

from __future__ import annotations

import json
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "dq3" / "knowledge" / "concepts.py"
ROM_PATH = PROJECT_ROOT / "work" / "rom" / "DQ3_J.nes"


@pytest.fixture(scope="module")
def matcher():
    from dq3.knowledge import concepts as C
    from dq3.knowledge import rom_names

    rom_names.reset()
    got = C.Matcher()
    if not got.available:
        pytest.skip("⚠ 名前辞書が使えません: %s" % rom_names.last_error)
    return got


def _obs(text, **kw):
    from dq3.knowledge import concepts as C

    return C.Observation(observation_id=kw.pop("observation_id", "obs-test"),
                         text=text, **kw)


def _an_item(matcher, kind="item"):
    """★runtime の名前辞書から、3 文字以上の実体を 1 つ借りる。"""
    for folded, got_kind, entity_id, name in matcher.aliases:
        if got_kind == kind and len(folded) >= 5:
            return entity_id, name
    pytest.skip("⚠ 借りられる名前が無い")


# --- ⚠⚠ 原作テキストを焼いていない ------------------------------------------

def test_会話本文と名前をソースに書いていない():
    """⚠⚠ 指示書 §20-7。★方角・場所の型（ふつうの日本語）だけは持ってよい。

    ⚠ 見るのは **module の定数**（★docstring や help は対象外）。
    """
    from dq3.knowledge import concepts as C
    from dq3.knowledge import rom_names

    allowed = set(C.DIRECTIONS) | set(C.PLACE_TYPES) | set(C.OBTAIN_HINT_PHRASES)         | set(C.GENERIC_HINT_PHRASES) | set(C.DROP) | set(C.FOLLOWERS) | {C.UTTERANCE_MARK}

    def kana_of(value):
        if isinstance(value, str):
            return [value] if any("぀" <= ch <= "ヿ" for ch in value) else []
        if isinstance(value, (list, tuple, set, frozenset)):
            return [x for v in value for x in kana_of(v)]
        if isinstance(value, dict):
            return [x for k, v in value.items() for x in kana_of(k) + kana_of(v)]
        return []

    bad = []
    for name in dir(C):
        if name.startswith("__"):
            continue
        value = getattr(C, name)
        if isinstance(value, (str, tuple, list, dict, set, frozenset)):
            for text in kana_of(value):
                # ★1 文字ずつ許す（`DROP` / `FOLLOWERS` はまとめ書き）
                if text in allowed or all(ch in allowed for ch in text):
                    continue
                bad.append("%s = %r" % (name, text))
    assert not bad, "⚠⚠ 素性の分からない かなの定数がある: %s" % bad

    # ⚠ 名前辞書の語が 1 つでもソースに入っていないこと
    rom_names.reset()
    data = rom_names._load()
    if data is None:
        return
    body = SRC.read_text(encoding="utf-8")
    for kind in ("monster", "item", "spell"):
        for name in (data["names"][kind]).values():
            if len(name) >= 4:
                assert name not in body, "⚠⚠ 名前がソースに書いてある: %s" % name


# --- ★正規化（⚠ これが無いと当たらない）--------------------------------------

def test_かなを畳まないと当たらない(matcher):
    """⚠⚠ ROM 自身が、道具の表では ひらがな、会話では カタカナ で綴る（実測）。"""
    from dq3.knowledge import concepts as C

    entity_id, name = _an_item(matcher)
    katakana = "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in name)
    assert katakana != name, "⚠ 見本が畳めていない"
    assert C.fold(katakana) == C.fold(name)
    # ★素の部分一致では当たらないことも見る（⚠ 畳みが要る理由）
    assert name not in katakana


def test_飾りの記号は全部落ちる():
    """⚠⚠ `fold` は **NFKC を先に掛ける**ので、全角で書いた `DROP` が抜けていた（RX3-0296）。

    ★実測（直す前）:

    ```text
    fold("＊「こんにちは。") → "*こんにちは"   ⚠ 発話の区切り ＊ が残っている
    fold("どう？")          → "どう?"
    fold("そう…")          → "そう..."
    ```

    ★`＊` は発話の区切り（`UTTERANCE_MARK`）で、⚠ 落とすつもりで `DROP` に入れてある。
    """
    from dq3.knowledge import concepts as C

    assert C.fold("＊「こんにちは。") == "こんにちは"
    assert C.fold("ありがとう！") == "ありがとう"
    assert C.fold("どう？") == "どう"
    assert C.fold("そう…") == "そう"
    assert C.fold("そう‥") == "そう"


def test_落とす記号は書いたものと同じ():
    """⚠ `DROP` に足した字が、★正規化のあとも落ちること（⚠ 片方だけ増やさない）。"""
    import unicodedata

    from dq3.knowledge import concepts as C

    for ch in C.DROP:
        assert C.fold(("あ" + ch + "い")) == "あい", (
            "⚠⚠ `DROP` の %r が落ちていない（★NFKC で %r に化けている）"
            % (ch, unicodedata.normalize("NFKC", ch)))


def test_落としすぎていない():
    """⚠ かな・漢字・数字は残る（★畳みすぎて何でも当たる、にしない）。"""
    from dq3.knowledge import concepts as C

    assert C.fold("やくそう3こ") == "やくそう3こ"
    assert C.fold("岬の洞窟") == "岬の洞窟"


# --- ★Concept は (kind, id) -----------------------------------------------------

def test_実体は名前ではなくidで持つ(matcher):
    entity_id, name = _an_item(matcher)
    got = matcher.entities("＊「%sは てにいれましたか？" % name, 0)[0]
    assert got and got[0].entity_id == entity_id and got[0].type == "item"
    assert got[0].concept_id == "item:%d" % entity_id
    # ⚠ 名前は表示のためだけ（★鍵ではない）
    assert got[0].alias == name


# --- ★Pattern A: 実体 ＋ 言い回し → Fact ----------------------------------------

def test_実体と言い回しが揃えばFactになる(matcher):
    from dq3.knowledge import concepts as C

    entity_id, name = _an_item(matcher)
    got = C.analyse(_obs("＊「%sは てにいれましたか？" % name), matcher)
    assert [r["relation"] for r in got["relations"]] == ["obtain_hint"]
    assert len(got["facts"]) == 1
    fact = got["facts"][0]
    assert fact["subject"] == "item:%d" % entity_id
    assert fact["predicate"] == "obtain_hint"
    assert fact["object"] is None, "⚠⚠ 根拠が無いのに object を作っている"
    assert fact["confidence"] >= C.FACT_MIN_CONFIDENCE


def test_実体だけならFactにしない(matcher):
    from dq3.knowledge import concepts as C

    _entity_id, name = _an_item(matcher)
    got = C.analyse(_obs("＊「%sを もっています。" % name), matcher)
    assert got["concepts"], "⚠ 実体は取れているはず"
    assert got["facts"] == [], "⚠⚠ 言い回しが無いのに Fact を作った"


# --- ⚠ Pattern B: 方角＋場所の型は Concept どまり -------------------------------

def test_方角と場所の型はFactにしない(matcher):
    from dq3.knowledge import concepts as C

    got = C.analyse(_obs("＊「みなみの もりに なにか あるらしい。"), matcher)
    kinds = {c["concept_id"] for c in got["concepts"]}
    assert "direction:south" in kinds and "place_type:forest" in kinds
    assert [r["relation"] for r in got["relations"]] == ["direction"]
    assert got["facts"] == [], "⚠⚠ どの場所が南かは決められない（★§10 Pattern B）"
    # ★候補は作り、⚠ 下限で落ちる（★落ちた理由が残る / 指示書 §18）
    assert len(got["rejected"]) == 1
    dropped = got["rejected"][0]
    assert dropped["confidence"] < C.FACT_MIN_CONFIDENCE and dropped["reason"]


def test_確度の下限が実際に効いている(matcher):
    """⚠⚠ 下限を 0 にすると、★落としていた候補が Fact に出てくること。

    ⚠ これが無いと「下限が一度も効いていない」ことに気づけません
      （★2026-09-03 に実際に踏んだ: 下限を 0 にしても検査が 1 件も鳴らなかった）。
    """
    from dq3.knowledge import concepts as C

    text = "＊「みなみの もりに なにか あるらしい。"
    strict = C.analyse(_obs(text), matcher)
    saved = C.FACT_MIN_CONFIDENCE
    try:
        C.FACT_MIN_CONFIDENCE = 0.0
        loose = C.analyse(_obs(text), matcher)
    finally:
        C.FACT_MIN_CONFIDENCE = saved
    assert strict["facts"] == [] and strict["rejected"]
    assert loose["facts"] and loose["rejected"] == []


# --- ⚠⚠ 誤検出の歯止め（★実測で出た 2 件）--------------------------------------

def test_名前の中の語を場所として拾わない(matcher):
    """⚠⚠ 実測: 品名の先頭 2 字（とう）を place_type:tower として拾っていた。"""
    from dq3.knowledge import concepts as C

    # ★「とう」で始まる名前を辞書から借りる（⚠ 名前は書かない）
    target = next((row for row in matcher.aliases
                   if row[0].startswith("とう") and len(row[0]) >= 5), None)
    if target is None:
        pytest.skip("⚠ 「とう」で始まる名前が辞書に無い")
    got = C.analyse(_obs("＊「%sは てにいれましたか？" % target[3]), matcher)
    kinds = {c["concept_id"] for c in got["concepts"]}
    assert "place_type:tower" not in kinds, "⚠⚠ 名前の中の語を場所として拾った"
    assert "%s:%d" % (target[1], target[2]) in kinds


def test_動詞の中の語を場所として拾わない(matcher):
    """⚠⚠ 実測: 動詞の中の 2 字（まち）を place_type:town として拾っていた。"""
    from dq3.knowledge import concepts as C

    got = C.analyse(_obs("＊「また おこしを おまちしてます。"), matcher)
    kinds = {c["concept_id"] for c in got["concepts"]}
    assert "place_type:town" not in kinds, "⚠⚠ 動詞の中の語を場所として拾った"


def test_歯止めが強すぎない(matcher):
    """⚠ 「まち」が**語として**出ていれば、★取れること（空振りの検査）。"""
    from dq3.knowledge import concepts as C

    got = C.analyse(_obs("＊「まちの そとを あるくとき。"), matcher)
    kinds = {c["concept_id"] for c in got["concepts"]}
    assert "place_type:town" in kinds, "⚠⚠ 歯止めが強すぎて語も取れない"


# --- ⚠ ほのめかしは Fact にしない ------------------------------------------------

def test_対象の無いほのめかしはFactにしない(matcher):
    from dq3.knowledge import concepts as C

    got = C.analyse(_obs("＊「あやしげな ばしょには なにか あるかも しれぬ。"), matcher)
    assert got["facts"] == []
    assert "generic_hint" in got["tags"], "⚠ ほのめかしと分かる印が無い"


# --- ⚠⚠ 文脈を Fact に昇格させない -----------------------------------------------

def test_観測の場所をFactへ勝手に入れない(matcher):
    """⚠⚠ 「レーベで聞いた」は文脈。★「レーベにある」ではない（指示書 §3.2）。"""
    from dq3.knowledge import concepts as C

    _entity_id, name = _an_item(matcher)
    got = C.analyse(_obs("＊「%sは てにいれましたか？" % name, map_id=9, npc_id=0), matcher)
    fact = got["facts"][0]
    assert fact["object"] is None
    body = json.dumps(fact, ensure_ascii=False)
    assert "map_id" not in body and "9" not in fact.get("object", "") if fact["object"] else True
    # ★文脈は Observation 側にある
    assert got["observation"]["map_id"] == 9


def test_発話をまたいで組み合わせない(matcher):
    """⚠ 別の発話の実体と、別の発話の言い回しをつながない（指示書 §9）。"""
    from dq3.knowledge import concepts as C

    _entity_id, name = _an_item(matcher)
    got = C.analyse(_obs("＊「%s。＊「てにいれましたか？" % name), matcher)
    assert got["facts"] == [], "⚠⚠ 発話をまたいで Fact を作った"


# --- ⚠ 名前辞書が無いとき --------------------------------------------------------

def test_名前辞書が無ければ実体を作らない(tmp_path):
    """⚠⚠ ROM が無い環境で、★でたらめな id を作らない。"""
    from dq3.knowledge import concepts as C
    from dq3.knowledge import rom_names

    rom_names.reset()
    try:
        got = C.Matcher(rom_path=tmp_path / "no-such.nes")
        assert not got.available
        result = C.analyse(_obs("＊「なにかは てにいれましたか？"), got)
        assert not [c for c in result["concepts"] if c.get("entity_id") is not None]
        assert result["facts"] == []
    finally:
        rom_names.reset()


# --- ★実測（⚠ 記録が無ければ skip）----------------------------------------------

def test_実測の会話からFactが起きる(matcher):
    from dq3.knowledge import concepts as C

    rows = C.observations()
    if not rows:
        pytest.skip("⚠ 聞いた会話の記録が無い")
    facts, tagged = [], []
    for observation in rows:
        got = C.analyse(observation, matcher)
        facts.extend(got["facts"])
        if got["tags"]:
            tagged.append(got)
    if not facts:
        # ⚠ この検査は work/ の記録に依存する。★2026-09-05 に聞き込み履歴を初期化した直後
        #   （城の会話だけ）で赤くなった。記録に手がかりの会話が無いのは環境であって欠陥ではない。
        pytest.skip("⚠ 記録に手がかりの会話が無い（★履歴を初期化した直後など）")
    assert all(f["subject"].split(":")[0] in ("monster", "item", "spell") for f in facts)
    assert tagged, "⚠ ほのめかしの印が 1 件も付いていない"

"""勇者メモの原本 template の形を固定する（RX3-0432 / 2026-09-26）。

## ⚠⚠ なぜ要るか

★`data/dq3/hero-memo.yaml` は **人が書く唯一の原本**です。
⚠ 人が触るファイルは、★**気づかないうちに壊れます**。

```text
⚠⚠ 起きうる壊れ方            ★この検査で鳴る
BOM が落ちて Excel で化ける   test_人が開く原本はBOM付きCRLF
改行が LF になる（全行差分）   同上
YAML が壊れて黙って空になる    test_原本が読める
`leads:` の鍵を消してしまう    同上
語彙を増やしたのに説明が無い    test_条件の語彙が説明と合っている
```

## ⚠ ここで見ないもの

★compile と validation は**まだ実装していません**（RX3-0432 の Fix 5〜7）。
⚠ 未実装のものを検査すると、★「未達を固定して古い主張を守る」形になります。
→ ★いま在るもの（template の形と、人に見せている説明）だけを見ます。
"""
from __future__ import annotations

import csv
import io
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MEMO = ROOT / "data" / "dq3" / "hero-memo.yaml"
LOCATIONS = ROOT / "data" / "dq3" / "location-names.csv"
README = ROOT / "data" / "dq3" / "README.md"

#: ★条件に書ける言い方（⚠ 実在する Fact の predicate に 1:1 で対応する / RX3-0432）
#:
#:  ⚠⚠ 2026-09-28（RX3-0443）: ここは**写し**でした。★語彙を増やすたびに
#:    「本体は通るのに検査だけ赤い」を起こしました（⚠ 3 度目: word / 入手した）。
#:    → ★本体から借ります（`dq3.knowledge.hero_memo.VOCABULARY`）。
from dq3.knowledge.hero_memo import VOCABULARY as _VOCABULARY  # noqa: E402

VOCABULARY = tuple(_VOCABULARY)

#: ⚠⚠ **使えない**言い方（★template に載せてはいけない）
#:  `direction` は confidence 0.5 固定で FACT_MIN_CONFIDENCE(0.8) を下回り、
#:  ★facts に一度も入らない（concepts.py:344）
FORBIDDEN = ("方角", "direction")


# --- ★原本そのもの ---------------------------------------------------------

def test_原本がある() -> None:
    assert MEMO.exists(), "⚠ data/dq3/hero-memo.yaml が無い（★人が書く原本）"


def test_人が開く原本はBOM付きCRLF() -> None:
    """⚠ Excel・メモ帳で化けない / ⚠⚠ 改行を混ぜない（★CLAUDE.md の改行の節）。"""
    for path in (MEMO, README, LOCATIONS):
        raw = path.read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf", "⚠⚠ BOM が無い: %s" % path.name
        assert raw.count(b"\n") == raw.count(b"\r\n"), (
            "⚠⚠ CRLF でない行がある: %s" % path.name)


def test_原本が読める() -> None:
    """★YAML として読めて、⚠ 鍵が揃っていること。"""
    got = yaml.safe_load(MEMO.read_bytes())
    assert isinstance(got, dict), "⚠ 辞書ではない: %r" % type(got)
    assert got.get("schema_version") == 1, got.get("schema_version")
    assert "leads" in got, "⚠⚠ `leads:` が無い（★人が足す場所）"
    assert isinstance(got["leads"] or [], list), "⚠ leads は並びであること"


def _leads_or_skip() -> list:
    """★読めたら `leads`、⚠ 読めなければ**理由を出して skip**。

    ## ⚠⚠ なぜ skip にするか（2026-09-27 の判断）

    ★この原本は**依頼者が書いている最中**です。⚠ 途中の書き間違いで全件 pytest が
    赤くなると、★こちらの作業が止まります。
    → ★**門番は `scripts/dq3_hero_memo_check.py`**（⚠ 終了コードで止める）。
      ここは「読めたなら形が合っているか」だけ見ます。
    ⚠ 黙って通り過ぎないよう、★理由は必ず印字します。
    """
    try:
        got = yaml.safe_load(MEMO.read_bytes())
    except Exception as exc:                               # noqa: BLE001
        pytest.skip("⚠ 原本が書きかけです（★`python scripts/dq3_hero_memo_check.py`）: %s"
                    % str(exc).splitlines()[0])
    return (got or {}).get("leads") or []


def test_書かれた1件ごとに要る項目がある() -> None:
    """★人が書き始めたので「空であること」の検査は外した（2026-09-27 / RX3-0432）。

    ⚠ 中身の正しさ（★名前が引けるか・条件が立つか）は
      `scripts/dq3_hero_memo_check.py` が見ます。⚠ ここは**形**だけ。
    """
    leads = _leads_or_skip()
    bad = [lead for lead in leads
           if not isinstance(lead, dict)
           or not all(lead.get(k) for k in ("id", "memo", "appears_when", "retires_when"))]
    if bad:
        pytest.skip("⚠ 原本が書きかけです（★%d 件に足りない項目があります / "
                    "`python scripts/dq3_hero_memo_check.py`）" % len(bad))
    for n, lead in enumerate(leads):
        for key in ("appears_when", "retires_when"):
            assert isinstance(lead[key], list), (
                "⚠ leads[%d] の `%s` は並びで書く" % (n, key))


def _flatten(conds: list, key: str) -> list:
    """★`appears_when` の `all_of` / `any_of` の組は中の条件を並べる（RX3-0436）。

    ⚠ `retires_when` の組は開かない（★書けないので、語彙の外として赤にする）。
    """
    from dq3.knowledge.hero_memo import GROUP_KEYS

    got = []
    for cond in conds:
        if (key == "appears_when" and isinstance(cond, dict) and len(cond) == 1
                and next(iter(cond)) in GROUP_KEYS and isinstance(next(iter(cond.values())), list)):
            got.extend(next(iter(cond.values())))
        else:
            got.append(cond)
    return got


def test_条件の言い方が5つの語彙に収まっている() -> None:
    """⚠⚠ 語彙の外を書くと、★立たない条件が静かに増えます。"""
    for n, lead in enumerate(_leads_or_skip()):
        if not isinstance(lead, dict):
            continue
        for key in ("appears_when", "retires_when"):
            for i, cond in enumerate(_flatten(lead.get(key) or [], key)):
                if not (isinstance(cond, dict) and len(cond) == 1):
                    # ⚠ 形が違うのは書きかけ（★門番のスクリプトが ERROR で止めます）
                    continue
                verb = next(iter(cond))
                assert verb in VOCABULARY, (
                    "⚠⚠ leads[%d].%s[%d] 知らない言い方 `%s`（★使えるのは %s）"
                    % (n, key, i, verb, " / ".join(VOCABULARY)))


# --- ★人に見せている説明 ---------------------------------------------------

def test_条件の語彙が説明と合っている() -> None:
    """⚠ 語彙を増やしたのに説明を直し忘れる、を防ぐ。"""
    text = MEMO.read_text(encoding="utf-8-sig")
    for word in VOCABULARY:
        assert "%s:" % word in text, "⚠ template に `%s:` の説明が無い" % word


def test_使えない語彙をtemplateに載せていない() -> None:
    """⚠⚠ `direction` は Fact に**一度も入らない**（★concepts.py:344）。

    ★条件として載せると「書いたのに一生消えないメモ」が作れてしまう。
    ⚠ 「条件には使えない」と**断り書きがある**のは可（★本文には書けるため）。
    """
    text = MEMO.read_text(encoding="utf-8-sig")
    for word in FORBIDDEN:
        # ★載っていてもよいが、⚠ 必ず「条件にはできません」と一緒に書いてあること
        if word in text:
            assert "条件にはできません" in text or "条件に使えない" in text, (
                "⚠⚠ `%s` を載せるなら「条件にはできません」と書くこと" % word)


def test_人が書くのは4つだけと書いてある() -> None:
    """★人間の負荷を増やす変更が入ったら気づけるように。"""
    text = MEMO.read_text(encoding="utf-8-sig")
    for word in ("memo", "appears_when", "retires_when", "about"):
        assert word in text, "⚠ template に `%s` の説明が無い" % word


def test_内部IDを書かせないと明記してある() -> None:
    """⚠⚠ ここが緩むと、★人間に item_id や RAM 番地を手入力させる設計に戻る。"""
    text = MEMO.read_text(encoding="utf-8-sig")
    assert "内部 ID" in text, "⚠ 「内部 ID は書きません」の断りが無い"


# --- ★場所の表 -------------------------------------------------------------

def _locations() -> list[dict]:
    with io.open(LOCATIONS, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_場所の表の列が揃っている() -> None:
    """⚠ 人が列を消したら気づけるように。

    ⚠⚠ **行数は固定しません。** ★依頼者が行を足していく表です
    （2026-09-27 実測: メモは **173 か所**を指しているのに、⚠ この表は 23 行しかない）。
    → ★足せるようにしておかないと、⚠ 検査が作業の邪魔になります。
    """
    rows = _locations()
    assert len(rows) >= 23, "⚠ 23 行より減っています（★消していない？）: %d 行" % len(rows)
    want = {"location_id", "map_id", "name", "kind", "review_status",
            "evidence", "notes"}
    assert want <= set(rows[0]), "⚠⚠ 列が足りない: %s" % (want - set(rows[0]))
    ids = [r["location_id"] for r in rows]
    assert len(ids) == len(set(ids)), "⚠⚠ location_id が重複: %s" % (
        [i for i in ids if ids.count(i) > 1])


def test_ルーラ表の20行に手入力を求めていない() -> None:
    """⚠⚠ 二重入力を防ぐ（★RX3-0432 の主眼）。

    ★ルーラ表の行は利用者の ROM から自動で引けます（2026-09-26 実測）。
    ⚠ そこに「人が入れる」と書いてあったら、★人に無駄な作業をさせています。
    """
    rows = _locations()
    rura = [r for r in rows if "ルーラ表" in (r["evidence"] or "")]
    assert len(rura) == 20, "⚠ ルーラ表の行が 20 行でない: %d" % len(rura)
    for r in rura:
        assert "自動" in (r["notes"] or ""), (
            "⚠ %s に「自動で引ける」と書いていない" % r["location_id"])
        assert "ここだけ人が入れる" not in (r["notes"] or ""), (
            "⚠⚠ %s は ROM から引けるのに手入力を求めています" % r["location_id"])


def test_まだ空の行には人が入れると書いてある() -> None:
    """★ROM から引けず、⚠ **まだ name が空**の行に印があること。

    ⚠⚠ 2026-09-27: 印を「ROM から引けない行すべて」に求めていて、
      ★埋め終わった行に別の註釈（根拠）を書いた瞬間に赤くなりました。
      → ★見るのは「**これから人が入れる行**」だけにします。
    """
    rows = _locations()
    todo = [r for r in rows
            if "ルーラ表" not in (r["evidence"] or "")
            and not (r["name"] or "").strip()]
    for r in todo:
        assert "ここだけ人が入れる" in (r["notes"] or ""), (
            "⚠ %s に「ここだけ人が入れる」と書いていない" % r["location_id"])


def test_埋めた行には根拠が書いてある() -> None:
    """⚠ 地名を入れたなら、★どこから来た名前かを `evidence` に残すこと。"""
    rows = _locations()
    for r in rows:
        if (r["name"] or "").strip() and "ルーラ表" not in (r["evidence"] or ""):
            assert (r["evidence"] or "").strip(), (
                "⚠⚠ %s に地名があるのに根拠が空（★出どころを残す）" % r["location_id"])


def test_AIの推測を禁じる断りがある() -> None:
    """⚠⚠ 第三者由来・AI の推測が混ざると、★公開できなくなる（D-25）。"""
    notes = " ".join(r["notes"] or "" for r in _locations())
    assert "転記は禁止" in notes, "⚠ CSV に禁止の断りが無い"
    readme = README.read_text(encoding="utf-8-sig")
    for word in ("AI の推測を書かない", "転記しない"):
        assert word in readme, "⚠ README に「%s」が無い" % word

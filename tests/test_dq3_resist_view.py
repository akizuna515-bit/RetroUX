"""耐性の見せ方 ― ログの札（1 文字）と図鑑（5 つのまとまり × ◎○△×）（RX3-0269 / 2026-09-14）。

★依頼者 2026-09-14「S9,S10は提案通りでOK。耐性表示はログのモンスター表示は簡易的に 一文字で工夫」＋ 1 文字の表:

```text
攻撃呪文      メラ・ギラ・イオ 炎   ヒャド 氷   バギ 風   デイン 雷
眠り・混乱    ラリホー 眠   メダパニ 乱   マヌーサ 幻   マホトーン 黙
能力を下げる  ルカニ・ルカナン 軟   ボミオス・バシルーラ 遅
即死・消える  ザキ・ザラキ 死   メガンテ メ   ニフラム・せいすい 聖
MP           マホトラ Ｍ
```

★根拠: `docs/design/dq3-resistance-analysis.md` §9（図鑑）/ §2（14 カテゴリ）。
⚠ 内部の 2bit・index は画面に出さない。⚠ 攻撃呪文の × は「ダメージ 0（効かない）」（★半減ではない / RX3-0267）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM = ROOT / "work" / "rom" / "DQ3_J.nes"

#: ★依頼者の表そのもの（⚠ 並びも見る）
USER_TABLE = (
    ("攻撃呪文", (("damage_reduction", "メラ・ギラ・イオ", "炎"), ("ice_spells", "ヒャド", "氷"),
                  ("wind_spells", "バギ", "風"), ("lightning_spells", "デイン", "雷"))),
    ("眠り・混乱", (("sleep", "ラリホー", "眠"), ("chaos", "メダパニ", "乱"),
                   ("surround", "マヌーサ", "幻"), ("stopspell", "マホトーン", "黙"))),
    ("能力を下げる", (("sap", "ルカニ・ルカナン", "軟"), ("limbo_slow", "ボミオス・バシルーラ", "遅"))),
    ("即死・消える", (("beat", "ザキ・ザラキ", "死"), ("sacrifice", "メガンテ", "メ"),
                     ("expel_fairywater", "ニフラム・せいすい", "聖"))),
    ("MP", (("robmagic", "マホトラ", "Ｍ"),)),
)


def test_14カテゴリを依頼者の表のまとまりと1文字で持つ():
    from dq3.knowledge import monster_book as mb
    from dq3rom import enemy_detail as det

    assert mb.RESIST_GROUPS == USER_TABLE
    keys = [k for _g, rows in mb.RESIST_GROUPS for k, _l, _c in rows]
    assert sorted(keys) == sorted(name for _i, _o, _s, name, _c in det.RESISTANCES), "⚠ 14 カテゴリが揃っていない"
    assert len(set(keys)) == 14
    chars = [c for _g, rows in mb.RESIST_GROUPS for _k, _l, c in rows]
    assert all(len(c) == 1 for c in chars) and len(set(chars)) == 14, "⚠ 1 文字でない / 重なっている"


def test_段階の記号とことば():
    from dq3.knowledge import monster_book as mb

    assert mb.RESIST_SYMBOL == ("◎", "○", "△", "×")
    assert mb.RESIST_WORD == ("よく効く", "効く", "効きにくい", "効かない")


def _detail_with(pred):
    from dq3rom import enemies as EN
    from dq3rom import enemy_detail as ED
    from dq3rom import profile as P

    if not ROM.exists():
        pytest.skip("ROM が無い")
    for d in ED.read_all(EN.read_all(P.load_and_identify(ROM))):
        if pred(d.resistances):
            return d
    pytest.skip("条件に合う敵が無い")


def test_ログの札は1文字と記号_効きにくいものだけ():
    """★札（ログのモンスターの帯）は △（段 2）と ×（段 3）だけ。◎○ は出さない（★場所節約 / RX3-0060 と同じ）。"""
    from dq3.knowledge import monster_book as mb

    d = _detail_with(lambda r: r["damage_reduction"]["level"] == 3 and r["sleep"]["level"] == 2
                     and r["ice_spells"]["level"] <= 1)
    got = mb.card_extras(d)
    parts = got["resist"].split()
    assert "炎×" in parts and "眠△" in parts, got["resist"]
    assert not any(p.startswith("氷") for p in parts), "⚠ 効く（段 0・1）ものを札に出した: %s" % got["resist"]
    assert not any(ch.isdigit() for ch in got["resist"]), "⚠⚠ 内部の値を出した"
    for _g, rows in mb.RESIST_GROUPS:
        for _k, label, char in rows:
            assert "%s=%s" % (char, label) in got["legend"], "⚠ 凡例に %s=%s が無い" % (char, label)
    assert "ダメージ 0" in got["legend"], "⚠ 攻撃呪文の × の意味（ダメージ 0）を書いていない"


def test_図鑑は5つのまとまりで記号とことば():
    from dq3.knowledge import monster_book as mb

    d = _detail_with(lambda r: r["damage_reduction"]["level"] == 3 and r["sleep"]["level"] == 2)
    groups = mb.resistance_groups(d)
    assert [g for g, _rows in groups] == [g for g, _rows in USER_TABLE]
    fire = dict((label, (sym, word)) for label, _char, _lv, sym, word in groups[0][1])
    assert fire["メラ・ギラ・イオ"] == ("×", "効かない")
    sleep = dict((label, (sym, word)) for label, _char, _lv, sym, word in groups[1][1])
    assert sleep["ラリホー"] == ("△", "効きにくい")


def _book(met, defeated):
    """★使い捨ての図鑑（⚠ 本物の記録は触らない / `test_dq3_monster_book._book` と同じ作法）。"""
    from dq3.knowledge.enemies_seen import EnemyBook

    got = EnemyBook(path=pathlib.Path(os.devnull))
    got.met = set(met)
    got.defeated = set(defeated)
    got.names = {0: "スライム"}
    return got


def test_図鑑の文は倒した敵だけ_まとまりの名前が出る():
    from dq3.knowledge import monster_book as mb
    from dq3.ui import monster_book_window as win

    if not ROM.exists():
        pytest.skip("ROM が無い")
    rows = dict(win.summary_lines(mb.entry_of(_book((0,), (0,)), 0)))
    assert "耐性" in rows and "攻撃呪文" in rows["耐性"] and "MP" in rows["耐性"], rows.get("耐性")
    assert any(s in rows["耐性"] for s in mb.RESIST_SYMBOL)
    assert "耐性" not in dict(win.summary_lines(mb.entry_of(_book((0,), ()), 0)))

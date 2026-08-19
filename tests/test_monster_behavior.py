"""図鑑に出す「行動と確率」「ドロップ」「耐性」の整形（Qt に依存しない）。

★守りたい契約:
  1. **選び直し（0x1E）を除いて正規化する**
     - これを忘れると「アンデッドマンは12.5%で何もしない」と出る。
       公開データは通常攻撃100%。実際に一度この誤りを作った
  2. 前提が崩れたら**何も返さない**（推測で埋めない）
  3. 「落とさない」と「まだ分からない」を書き分ける
  4. 耐性の数値を**効き方の言葉**にする（0=必ず効く / 7=効かない）

出典と根拠: `docs/design/monster-book-spec.md` 3章
"""

from __future__ import annotations

import pytest

from retroux.core.db.behavior import (
    REROLL_ACTION, action_breakdown, format_actions, format_drop, resist_label,
)

# ROM の実データ（memory_map の action_rates）。賢さ0 は均等、賢さ1 は前寄り。
RATES = {
    0: [12.5] * 8,
    1: [14.84, 15.23, 12.89, 13.28, 11.72, 11.72, 10.16, 10.16],
}
NAMES = {0x00: "通常攻撃", 0x05: "逃げる", 0x0C: "ホイミ", 0x1E: "選び直し"}


# --- 1. 選び直しを除いて正規化する ------------------------------------


def test_reroll_is_excluded_and_rest_normalized():
    """★これが元の誤りそのもの。

    アンデッドマン相当（通常攻撃×7 + 選び直し×1 / 賢さ0）。
    ROM 上は 87.5% + 12.5% だが、**表示は通常攻撃 100%**。
    """
    behavior = {"wisdom": 0, "actions": [0x00] * 7 + [REROLL_ACTION]}
    got = action_breakdown(behavior, NAMES, RATES)
    assert got == [("通常攻撃", pytest.approx(100.0, abs=0.05))]
    # ★「選び直し」が表に出てはいけない
    assert all(name != "選び直し" for name, _ in got)


def test_normalization_matches_published_data():
    """バブルスライム相当。公開データ 71.4% / 28.6% と一致すること。

    ROM: 通常攻撃 62.5 / 毒攻撃 25.0 / 選び直し 12.5（賢さ0）
      -> 62.5/87.5 = 71.4% ・ 25.0/87.5 = 28.6%
    """
    names = {**NAMES, 0x02: "毒攻撃"}
    behavior = {"wisdom": 0,
                "actions": [0x00] * 5 + [0x02, 0x02, REROLL_ACTION]}
    got = dict(action_breakdown(behavior, names, RATES))
    assert got["通常攻撃"] == pytest.approx(71.4, abs=0.1)
    assert got["毒攻撃"] == pytest.approx(28.6, abs=0.1)


def test_slime_matches_published_data():
    """スライム（賢さ1 / 枠 05 00 05 00 00 00 00 00）。公開 72.3 / 27.7。"""
    behavior = {"wisdom": 1, "actions": [0x05, 0x00, 0x05, 0x00, 0, 0, 0, 0]}
    got = dict(action_breakdown(behavior, NAMES, RATES))
    assert got["逃げる"] == pytest.approx(27.7, abs=0.1)
    assert got["通常攻撃"] == pytest.approx(72.3, abs=0.1)


def test_healer_matches_published_data():
    """ホイミスライム（賢さ1 / ホイミ×7 + 通常×1）。公開 88.3 / 11.7。"""
    behavior = {"wisdom": 1,
                "actions": [0x0C] * 4 + [0x00] + [0x0C] * 3}
    got = dict(action_breakdown(behavior, NAMES, RATES))
    assert got["ホイミ"] == pytest.approx(88.3, abs=0.1)
    assert got["通常攻撃"] == pytest.approx(11.7, abs=0.1)


def test_same_action_in_multiple_slots_is_summed():
    """同じ行動が複数の枠にあれば足すこと（別々の行にしない）。"""
    behavior = {"wisdom": 0, "actions": [0x00] * 8}
    got = action_breakdown(behavior, NAMES, RATES)
    assert len(got) == 1
    assert got[0][1] == pytest.approx(100.0, abs=0.05)


def test_sorted_by_probability_desc():
    behavior = {"wisdom": 0, "actions": [0x00, 0x05, 0x05, 0x05, 0, 0, 0, 0]}
    got = action_breakdown(behavior, NAMES, RATES)
    assert [n for n, _ in got] == ["通常攻撃", "逃げる"]


# --- 2. 前提が崩れたら何も返さない ------------------------------------


@pytest.mark.parametrize("behavior,reason", [
    (None, "行動が無い"),
    ({}, "空"),
    ({"wisdom": 0, "actions": []}, "枠が空"),
    ({"wisdom": 9, "actions": [0] * 8}, "賢さが表に無い"),
    ({"wisdom": 0, "actions": [0] * 7}, "★枠が7つしかない（8つのはず）"),
    ({"wisdom": 0, "actions": [0] * 9}, "枠が9つある"),
    ({"wisdom": 0, "actions": [REROLL_ACTION] * 8}, "全部が選び直し"),
])
def test_returns_nothing_when_assumptions_break(behavior, reason):
    """★推測で埋めない。**空を返す**（呼び出し側が「データが無い」と書く）。

    特に「枠が7つ」は実際に踏んだ誤り（8枠なのに7と数えた）。
    黙って7枠ぶんで計算すると、確率が合わないまま表示されてしまう。
    """
    assert action_breakdown(behavior, NAMES, RATES) == [], reason


def test_returns_nothing_without_tables():
    behavior = {"wisdom": 0, "actions": [0] * 8}
    assert action_breakdown(behavior, None, RATES) == []
    assert action_breakdown(behavior, NAMES, None) == []


def test_unknown_action_id_is_labelled_not_dropped():
    """表に無い行動IDは**捨てずに**「不明」と出す。

    ★捨てると確率の合計が変わり、他の行動の値が狂う。
    """
    behavior = {"wisdom": 0, "actions": [0x00] * 4 + [0x7F] * 4}
    got = dict(action_breakdown(behavior, NAMES, RATES))
    assert "不明(0x7F)" in got
    assert sum(got.values()) == pytest.approx(100.0, abs=0.05)


# --- 3. ドロップの書き分け --------------------------------------------


def test_format_drop():
    items = {0x3C: "やくそう"}
    assert format_drop({"item": 0x3C, "denominator": 128}, items) \
        == "やくそう（1/128）"


def test_format_drop_without_data_is_empty():
    """★空文字を返す。「落とさない」と書くのは呼び出し側の役目。

    ここで「落とさない」と返すと、**ROM データが無い敵**にも
    「落とさない」と出てしまう（分からないことを断定してしまう）。
    """
    assert format_drop(None, {0x3C: "やくそう"}) == ""
    assert format_drop({}, {}) == ""


def test_format_drop_with_unknown_item_says_so():
    assert "不明な道具" in format_drop({"item": 0x99, "denominator": 8}, {})


# --- 4. 耐性の言葉 ----------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (0, "必ず効く"),
    (7, "効かない"),
    (None, "-"),
])
def test_resist_label_edges(value, expected):
    assert resist_label(value) == expected


@pytest.mark.parametrize("value,pct", [(1, 86), (4, 43), (6, 14)])
def test_resist_label_middle(value, pct):
    """成功率 = (7 - 値) / 7。数値だけでは意味が分からないので % で出す。"""
    assert resist_label(value) == f"{pct}%"


def test_format_actions_is_readable():
    assert format_actions([("ホイミ", 88.3), ("通常攻撃", 11.7)]) \
        == "ホイミ 88.3% / 通常攻撃 11.7%"
    assert format_actions([]) == ""

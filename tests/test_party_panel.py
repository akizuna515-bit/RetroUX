"""パーティ状態を「棒グラフ」から「表」へ変えた（2026-07-27 / 依頼者の要望）。

> パーティー状態の棒グラフをやめて、行を減らしたい

★守りたい契約:
  1. **1人1行**であること（棒のときは1人4行だった）
  2. ⚠ **棒が持っていた情報を落とさない** —
     棒は「残りの割合」を一目で伝えていた。表では **HP の文字を色で塗る**。
     ★色だけに頼らない。数字は常に出す（色が見えにくい人にも伝わる）
  3. 3つの状態を区別する（更新待ち / 最大レベル / 残り経験値）
  4. 呪文を持たない人の MP を「0/0」と出さない
  5. 表の高さが行数ぶんに収まる（余白で縦を食わない）
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 が無い環境")

from PySide6.QtWidgets import QApplication  # noqa: E402

from retroux.core.bridge.state_reader import Member  # noqa: E402
from retroux.ui.panels import HP_DANGER, HP_WARN, PartyPanel  # noqa: E402

DANGER, WARN = "#e05a5a", "#e0b34a"
# ★十分あるときは**色を付けない**（2026-07-29 / 依頼者の指定）。
#   以前は満タンでも青くしていたので「色が付いている＝注意」に見えなかった。
#   何色になるかは環境のテーマ次第なので、**危険色でないこと**だけを見る。

# ★★ **列番号は名前から引く。** ★★
#   ⚠ `range(6)` で決め打ちしていたので、列を1つ足しただけで
#     関係ないテストが5件まとめて落ちた（2026-07-31 に踏んだ）。
#     ★列の増減は今後もある（攻撃・守備を足した / すばやさも分かれば足す）。
def _col(label: str) -> int:
    from retroux.ui.panels import PartyPanel

    return PartyPanel.COLUMNS.index(label)


COL_NAME = _col("名前")
COL_LV = _col("LV")
COL_HP = _col("HP")
COL_MP = _col("MP")
# ★★ 2026-08-09: 見出しを1文字に縮めました（依頼者の指示）★★
#   > パーティーステータス表示見切れるので努力したい
#   ⚠ 「力」と「攻」は**別物**（攻 = 力 + 武器）。★見分けが付くように、
#     列見出しにはゲームと同じ言葉のツールチップを付けてあります
#     （`PartyPanel.COLUMN_TIPS`。下のテストで固定しています）。
COL_STRENGTH = _col("力")
COL_AGILITY = _col("速")
COL_ATTACK = _col("攻")
COL_DEFENSE = _col("守")
COL_NEXT = _col("次")
COL_STATUS = _col("状態")


def test_short_headers_say_what_they_mean():
    """★★ 1文字の見出しには**必ず**説明を付ける（2026-08-09）★★

    ⚠⚠ 「ちから」と「こうげき力」は別物です（こうげき力 = ちから + 武器）。
      ★1文字にすると見分けが付かないので、ツールチップにゲームと同じ
        言葉を入れています。⚠ ここが抜けると装備の効果が読み取れません。
    """
    from retroux.ui.panels import PartyPanel

    for label in ("力", "速", "攻", "守", "次"):
        assert label in PartyPanel.COLUMNS
        assert PartyPanel.COLUMN_TIPS.get(label), f"{label} の説明が無い"
    assert "ちから" in PartyPanel.COLUMN_TIPS["力"]
    assert "こうげき力" in PartyPanel.COLUMN_TIPS["攻"]


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    try:
        created = QApplication([])
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Qt を起動できない環境: {exc}")
    yield created


@pytest.fixture
def panel(app):
    widget = PartyPanel()
    widget.resize(640, 300)
    widget.show()
    app.processEvents()
    yield widget, app
    widget.close()


def _member(**kw) -> Member:
    base = dict(name="a", level=10, hp=30, max_hp=40, mp=5, max_mp=10,
                status=0x84)
    base.update(kw)
    return Member(**base)


def _cell(panel, row, col):
    return panel._table.item(row, col)


# --- 1. 1人1行 --------------------------------------------------------


def test_one_row_per_member(panel):
    widget, app = panel
    widget.update_party([_member(name="a"), _member(name="b"),
                         _member(name="c")])
    app.processEvents()
    assert widget._table.rowCount() == 3


def test_no_progress_bars(panel):
    """★棒グラフを使っていないこと（行を減らすための変更なので）。"""
    from PySide6.QtWidgets import QProgressBar

    widget, app = panel
    widget.update_party([_member()])
    app.processEvents()
    assert widget.findChildren(QProgressBar) == [], "棒グラフが残っている"


def test_table_height_fits_rows(panel):
    """★高さが行数ぶんに収まること（余白で縦を食わない）。"""
    widget, app = panel
    widget.update_party([_member(name="a")])
    app.processEvents()
    one = widget._table.height()

    widget.update_party([_member(name="a"), _member(name="b"),
                         _member(name="c")])
    app.processEvents()
    three = widget._table.height()

    assert one < three, "行を増やしても高さが変わらない"
    # 3人でも 4人ぶん（見出し込み）に収まっていること
    row = widget._table.verticalHeader().defaultSectionSize()
    assert three <= row * 5, f"高さ {three}px が行数に見合わない"


# --- 2. ⚠ 棒が持っていた情報を落とさない ------------------------------


@pytest.mark.parametrize("hp,max_hp,expected,why", [
    (40, 40, None, "満タン"),
    (21, 40, None, "警告より上"),
    (20, 40, WARN, f"AI が回復に動く境目（{HP_WARN}）"),
    (11, 40, WARN, "警告の範囲"),
    (10, 40, DANGER, f"危険状態の境目（{HP_DANGER}）"),
    (0, 40, DANGER, "戦闘不能"),
])
def test_hp_text_is_coloured_by_ratio(panel, hp, max_hp, expected, why):
    """★棒の代わりに文字を塗る。**割合の情報を落とさない**。"""
    widget, app = panel
    widget.update_party([_member(hp=hp, max_hp=max_hp)])
    app.processEvents()
    got = _cell(widget, 0, COL_HP).foreground().color().name()
    if expected is None:
        assert got not in (WARN, DANGER), f"{why}: {hp}/{max_hp} が {got}"
    else:
        assert got == expected, f"{why}: {hp}/{max_hp} が {got}"


# --- 2b. MP も同じ規則で塗る（2026-07-29 / 依頼者の指定）----------------


@pytest.mark.parametrize("mp,max_mp,expected,why", [
    (68, 68, None, "満タン"),
    (35, 68, None, "半分より上"),
    (30, 68, WARN, "半分以下"),
    (10, 68, DANGER, "1/4以下"),
    (0, 68, DANGER, "空"),
])
def test_mp_text_is_coloured_by_ratio(panel, mp, max_mp, expected, why):
    widget, app = panel
    widget.update_party([_member(mp=mp, max_mp=max_mp)])
    app.processEvents()
    got = _cell(widget, 0, COL_MP).foreground().color().name()
    if expected is None:
        assert got not in (WARN, DANGER), f"{why}: {mp}/{max_mp} が {got}"
    else:
        assert got == expected, f"{why}: {mp}/{max_mp} が {got}"


def test_member_without_mp_is_not_marked_dangerous(panel):
    """⚠★ MP を持たない人（ローレシア）を「危険」と出さない。

    0/0 の割合は 0 なので、素直に塗ると**常に赤**になる。
    """
    widget, app = panel
    widget.update_party([_member(mp=0, max_mp=0)])
    app.processEvents()
    got = _cell(widget, 0, COL_MP).foreground().color().name()
    assert got not in (WARN, DANGER), f"MPなしが {got} で塗られた"


def test_numbers_are_always_shown(panel):
    """★色だけに頼らない。数字が必ず出ていること。"""
    widget, app = panel
    widget.update_party([_member(hp=7, max_hp=40)])
    app.processEvents()
    text = _cell(widget, 0, COL_HP).text()
    assert "7" in text and "40" in text, text


# --- 3. 経験値の3つの状態 ---------------------------------------------


def test_exp_not_yet_received(panel):
    """届いていない（エミュレータ側が古い）ことを書く。"""
    widget, app = panel
    widget.update_party([_member(exp=None)])
    app.processEvents()
    assert "更新待ち" in _cell(widget, 0, COL_NEXT).text()


def test_exp_at_max_level(panel):
    widget, app = panel
    widget.update_party([_member(exp=99999, next_level=None)])
    app.processEvents()
    assert "最大レベル" in _cell(widget, 0, COL_NEXT).text()


def test_exp_remaining(panel):
    widget, app = panel
    widget.update_party([_member(exp=100, next_level=11, exp_to_next=1234)])
    app.processEvents()
    assert "1,234" in _cell(widget, 0, COL_NEXT).text()


# --- 4. 呪文を持たない人 ----------------------------------------------


def test_no_spells_is_not_zero_over_zero(panel):
    """★ローレシアは呪文を覚えない。「0/0」と出さない。"""
    widget, app = panel
    widget.update_party([_member(mp=0, max_mp=0)])
    app.processEvents()
    # ★2026-08-09: 表示は「-」へ短縮（依頼者の指示。列幅のため）。
    #   ⚠ 「0/0」にしないという元の狙いはそのまま。★意味はツールチップで補う。
    from retroux.ui.panels import PartyPanel

    cell = _cell(widget, 0, COL_MP)
    assert cell.text() == PartyPanel.MP_NONE
    assert "呪文を覚えません" in cell.toolTip()


# --- 状態と入力中の印 -------------------------------------------------


def test_status_marks(panel):
    widget, app = panel
    widget.update_party([
        _member(name="a"),
        _member(name="b", poisoned=True),
        _member(name="c", alive=False, hp=0),
    ])
    app.processEvents()
    assert _cell(widget, 0, COL_STATUS).text() == "－"
    assert "毒" in _cell(widget, 1, COL_STATUS).text()
    assert "戦闘不能" in _cell(widget, 2, COL_STATUS).text()


def test_actor_is_marked(panel):
    """いま入力を求められている人が分かること（AI判断と対応づく）。"""
    widget, app = panel
    widget.update_party([_member(name="a"), _member(name="b")], actor="b")
    app.processEvents()
    assert "◀" in _cell(widget, 1, COL_NAME).text()
    assert "◀" not in _cell(widget, 0, COL_NAME).text()


def test_empty_party_shows_a_message(panel):
    """★空欄にしない（読めていないことを書く）。"""
    widget, app = panel
    widget.update_party([])
    app.processEvents()
    assert widget._empty.isVisible()
    assert not widget._table.isVisible()

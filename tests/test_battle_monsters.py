"""戦っているモンスターの帯（2026-08-09 / 依頼者の指示）。

    > 下の窓の上段に戦うモンスターを表示させる
    > （横に広がる形で。たくさん出たらスクロールバーで）

★★ ここで固定したいこと ★★
  ・**切り捨てない**。8体出たら8枚。⚠ 「3体まで」にしない
  ・**絵が無い敵を落とさない**。名前だけの札にする
  ・同じ敵が並んだら **×N** にまとめる（★並び順は変えない）
"""

from __future__ import annotations

import dataclasses

import pytest

from retroux.ui import battle_monsters as bm

NAMES = {0x01: "スライム", 0x02: "おおありくい", 0x30: "あくまのきし"}


def _no_art(_monster_id):
    return None


@dataclasses.dataclass
class _Group:
    monster_id: int
    name: str
    count: int


# --- 札の組み立て（★Qt を使わない部分だけ）---------------------------

def test_同じ敵が並んだらまとめる():
    cards = bm.cards_from_ids([0x01, 0x01, 0x01], NAMES, _no_art)
    assert len(cards) == 1
    assert cards[0].count == 3
    assert cards[0].name == "スライム"


def test_離れて並んだ同じ敵はまとめない():
    """⚠ 並び順は画面の並びなので、**勝手に寄せません**。"""
    cards = bm.cards_from_ids([0x01, 0x02, 0x01], NAMES, _no_art)
    assert [c.monster_id for c in cards] == [0x01, 0x02, 0x01]
    assert [c.count for c in cards] == [1, 1, 1]


def test_名前を知らない敵も落とさない():
    """⚠ 辞書に無いからといって**消しません**。★IDで出します。"""
    cards = bm.cards_from_ids([0xEE], NAMES, _no_art)
    assert len(cards) == 1
    assert "EE" in cards[0].name


def test_グループからも作れる():
    groups = [_Group(0x01, "スライム", 2), _Group(0x30, "あくまのきし", 1)]
    cards = bm.cards_from_groups(groups, NAMES, _no_art)
    assert [(c.name, c.count) for c in cards] == [
        ("スライム", 2), ("あくまのきし", 1)]


def test_敵が居なければ空():
    assert bm.cards_from_ids([], NAMES, _no_art) == []
    assert bm.cards_from_groups(None, NAMES, _no_art) == []


# --- 帯そのもの（★Qt が要る）------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """★画面を建てずに widget を作るための最小の QApplication。"""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def strip(qapp):
    return bm.BattleMonsterStrip()


def test_たくさん出ても切り捨てない(strip):
    """⚠⚠ **ここが本題**。8体でも8枚。★入らないぶんは横スクロール。"""
    ids = [0x01] * 4 + [0x02] * 4          # ★まとめると2枚
    strip.set_cards(bm.cards_from_ids(ids, NAMES, _no_art))
    assert len(strip.cards()) == 2
    assert sum(c.count for c in strip.cards()) == 8

    # ★別々の敵が8種なら8枚（⚠ 減らさない）
    many = list(range(0x10, 0x18))
    strip.set_cards(bm.cards_from_ids(many, NAMES, _no_art))
    assert len(strip.cards()) == 8


def test_横スクロールは出るが縦は出ない(strip):
    """★帯の高さは固定。⚠ 縦に出しても掴めないので消してある。"""
    from PySide6.QtCore import Qt

    assert strip.verticalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    assert strip.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def test_空なら黙らずに書く(strip):
    """⚠ 何も出さないと「壊れている」と見分けが付きません。"""
    strip.set_cards([])
    assert strip.cards() == []


def test_同じ中身なら作り直さない(strip):
    """★点滅を防ぐため。⚠ 戦闘中は毎秒描き直されます。"""
    cards = bm.cards_from_ids([0x01, 0x02], NAMES, _no_art)
    strip.set_cards(cards)
    first = strip.widget().layout().itemAt(0).widget()
    strip.set_cards(bm.cards_from_ids([0x01, 0x02], NAMES, _no_art))
    assert strip.widget().layout().itemAt(0).widget() is first

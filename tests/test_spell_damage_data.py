"""攻撃呪文の威力（2026-08-03 / 「ガンガン行こうぜ」Phase 1 の土台）。

★★ **出典は依頼者が示した攻略情報です。** ★★

⚠⚠ ROM の逆アセンブルとは食い違いました。**黙って合わせていません。**

| 呪文 | ROM の Power | ★式の予測 | ⚠ 攻略情報 |
| --- | --- | --- | --- |
| ギラ | `#$18`=24 | 中心 12 | **12〜28（中心20）** |
| ベギラマ | `#$32`=50 | 中心 25 | 13〜35（中心24） |
| イオナズン | `#$82`=130 | 中心 65 | 32〜91（中心61） |

★ベギラマとイオナズンは近いのに、**ギラだけ倍近く違います**。
⚠ 参照した逆アセンブルは**北米版**なので、日本版と違う恐れがあります。

★ここでは「攻略情報が正本」であることと、
**食い違いが残っていること自体**を試験で残します。
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
MEMORY_MAP = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml"

#: ★攻撃呪文（ID → 攻略情報の数字）
ATTACK_SPELLS = {
    0x01: {"name": "ギラ", "mp": 2, "min": 12, "max": 28, "avg": 20,
           "scope": "single"},
    0x03: {"name": "ベギラマ", "mp": 4, "min": 13, "max": 35, "avg": 25,
           "scope": "all"},
    0x05: {"name": "バギ", "mp": 4, "min": 13, "max": 35, "avg": 25,
           "scope": "group"},
    0x0E: {"name": "イオナズン", "mp": 8, "min": 32, "max": 91, "avg": 60,
           "scope": "all"},
}

#: ★対象の広さ。⚠ `target`（カーソルで選ぶか）とは別
SCOPES = ("single", "group", "all")


def _spells() -> dict:
    data = yaml.safe_load(MEMORY_MAP.read_bytes().decode("utf-8"))
    return data["spells"]


@pytest.mark.parametrize("spell_id,want", sorted(ATTACK_SPELLS.items()))
def test_攻撃呪文の威力が攻略情報どおり(spell_id, want):
    """★★ これが正本。⚠ 勝手に変えたら知らせます。"""
    spell = _spells()[spell_id]
    assert spell["mp_battle"] == want["mp"], f"⚠ {want['name']} の MP"
    assert spell["damage_min"] == want["min"]
    assert spell["damage_max"] == want["max"]
    assert spell["damage_avg"] == want["avg"]
    assert spell["scope"] == want["scope"]


@pytest.mark.parametrize("spell_id", sorted(ATTACK_SPELLS))
def test_出典が書いてある(spell_id):
    """⚠ どこから来た数字か分からなくならないように。"""
    assert "攻略情報" in str(_spells()[spell_id]["source"])


@pytest.mark.parametrize("spell_id", sorted(ATTACK_SPELLS))
def test_平均が範囲の中にある(spell_id):
    spell = _spells()[spell_id]
    assert spell["damage_min"] <= spell["damage_avg"] <= spell["damage_max"]


@pytest.mark.parametrize("spell_id", sorted(ATTACK_SPELLS))
def test_広さが決まった3つのどれか(spell_id):
    assert _spells()[spell_id]["scope"] in SCOPES


# --- ⚠⚠ ROM との食い違いを残す -------------------------------------------

def test_ROMのPowerと攻略情報が食い違っていることを記録する():
    """⚠⚠ **これは「直すべき不具合」ではなく「未解決の食い違い」です。**

    ★ROM の `Power` を 1/2 したものが中心値になる、という読みは
      ベギラマ・イオナズンでは近いのに、**ギラでは倍近く外れます**。

    ⚠ 参照した逆アセンブルは北米版（`src/us/`）です。
      日本版で威力が違うのか、私の式の読みが足りないのかは
      **まだ分かっていません**。

    ★食い違いが消えたら（＝どちらかが直ったら）ここが落ちて気づけます。
    """
    spells = _spells()
    # ★ROM の値を控えてあるもの
    rom_powers = {0x01: 0x18, 0x03: 0x32, 0x0E: 0x82}
    close, far = [], []
    for spell_id, power in rom_powers.items():
        assert spells[spell_id]["rom_power"] == power, "★控えを変えないこと"
        predicted = power / 2
        actual = spells[spell_id]["damage_avg"]
        (close if abs(predicted - actual) <= actual * 0.2 else far).append(
            (spell_id, predicted, actual))
    assert len(close) == 2, f"★近いのは 2 件のはず: {close}"
    assert [s for s, _, _ in far] == [0x01], (
        f"⚠ 外れているのはギラだけのはず: {far}")


def test_バギにはROMのPowerを控えていない():
    """⚠ 逆アセンブルの handler 一覧に**バギが見当たりません**。

    ★見つかっていないものを、それらしい値で埋めていないことを固定します。
    """
    assert "rom_power" not in _spells()[0x05]


# --- ★ 既存の呪文を壊していない -------------------------------------------

def test_攻撃呪文以外に威力を足していない():
    """⚠ 回復呪文などに damage を付けると、攻撃候補に紛れます。"""
    for spell_id, spell in _spells().items():
        if spell_id in ATTACK_SPELLS:
            continue
        assert "damage_avg" not in spell, f"⚠ 呪文 ${spell_id:02X}"
        assert "scope" not in spell


def test_唱えてはいけない呪文の印が残っている():
    """★メガンテ・パルプンテの歯止めを壊していないこと。"""
    spells = _spells()
    assert spells[0x0C]["never_cast"] is True       # メガンテ
    assert spells[0x0F]["never_cast"] is True       # パルプンテ


def test_回復呪文の印が残っている():
    for spell_id in (0x09, 0x0B, 0x0D):
        assert _spells()[spell_id]["heal"] is True

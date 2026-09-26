"""アイテムの ID・分類・袋、そして名前の覚え方（RX3-0041 / 2026-09-01）。

## ⚠⚠ ここで守ること

★`docs/00-project-policy.md` §3「原作テキストを同梱しない」。
⚠ 品の**名前**をリポジトリに持ちません。★持つのは ID・分類・場所という**構造**だけ。

```text
★持つ    分類は ID の範囲（⚠ 逆アセンブルの註釈そのもの）
★持つ    袋は $077C（⚠ 4 人 x 8 枠 / bit7 装備 / 0xFF 空き）
⚠ 持たない 「0x02 は どうのつるぎ」のような**文言**
```

## ★袋の番地は実データで裏を取っています

セーブステートの初期装備が `81 / A0 / B8`（★こんぼう・ぬののふく・かわのたて）で、
⚠ 3 つとも**分類の範囲に収まります**。★偶然ではありません。
"""

from __future__ import annotations

import os
import pathlib

import pytest

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from savestate_dir import states_dir  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
# ★固定した写しがあればそちら（⚠ 遊んでも動かない / RX-0135）
FCS = states_dir()


# --- ★分類（⚠ ROM もセーブも要らない）--------------------------------------


def test_分類はIDの範囲で決まる():
    """★逆アセンブルの註釈:

    > something will be classified as armor if its ID is >= $20 and <= $37
    """
    from dq3rom import items as it

    assert it.category_of(0x00) == "ぶき"
    assert it.category_of(0x1F) == "ぶき"
    assert it.category_of(0x20) == "よろい"
    assert it.category_of(0x37) == "よろい"
    assert it.category_of(0x38) == "たて"
    assert it.category_of(0x3F) == "かぶと"
    assert it.category_of(0x50) == "どうぐ"


def test_範囲に切れ目も重なりも無い():
    """⚠ 隙間があると「不明」が増え、★重なると先に書いたほうが勝つ。"""
    from dq3rom import items as it

    ranges = sorted((low, high) for low, high, _ in it.CATEGORIES)
    for (a_low, a_high), (b_low, b_high) in zip(ranges, ranges[1:]):
        assert a_high < b_low, "⚠⚠ 重なっている: %s / %s" % (a_high, b_low)
        assert b_low == a_high + 1, "⚠ 隙間がある: 0x%02X" % (a_high + 1)
    assert ranges[0][0] == 0x00
    assert ranges[-1][1] == 0x7C, "⚠ 0x7D..0x7F は分類しない（★weird stuff）"


def test_品なしを品として出さない():
    """★★★ ⚠⚠ `0x7F` は「品なし」（`ITEM_SWORD_HORNED` の流用）★★★"""
    from dq3rom import items as it

    assert it.category_of(0x7F) == "なし"
    assert it.label_of(0x7F) == "（なし）"
    assert it.label_of(None) == "（なし）"
    assert it.slot_of(0x7F) is None
    assert it.slot_of(0xFF) is None, "⚠ 空き枠を品として読んでいる"


def test_空き枠と品なしは同じ結果になる():
    """⚠⚠ **この 2 つは検査で区別できません**（★2026-09-01 に確かめた）。

    ```text
    0xFF（空き枠）  & 0x7F  =  0x7F（品なし）
    ```

    ★`slot_of` の `EMPTY_SLOT` の行を消しても、⚠ **素通りします**
    （次の「品なし」判定が拾うため）。★わざと壊して確かめました。

    ⚠ つまり `EMPTY_SLOT` の行は**意図を書くためのもの**で、
      振る舞いを守ってはいません。★消してよいという意味ではなく、
      「この検査は守っていない」と分かるように、ここに書いておきます。
    """
    from dq3rom import items as it

    assert it.EMPTY_SLOT & it.TYPE_MASK == it.NO_ITEM_ID
    assert it.slot_of(it.EMPTY_SLOT) == it.slot_of(it.NO_ITEM_ID) is None


def test_名前を知らないときも裸の番号にしない():
    """⚠ 「品 56」だけでは、★何なのかまったく分かりません。

    ★分類は ROM の構造から分かるので、⚠ そこまでは出します。
    """
    from dq3rom import items as it

    got = it.label_of(0x38)
    assert "たて" in got and "0x38" in got, got
    assert it.label_of(0x38, "かわのたて") == "かわのたて"


def test_名前をソースに持っていない():
    """★★★ ⚠⚠ **原作テキストを同梱しない**（方針 §3）★★★"""
    src = (ROOT / "dq3rom" / "items.py").read_text(encoding="utf-8")
    for banned in ("どうのつるぎ", "ひのきのぼう", "やくそう", "きえさりそう"):
        assert banned not in src, "⚠⚠ 品の名前を焼いている: %s" % banned


# --- ★袋の読み方 ------------------------------------------------------------


def test_袋の1枠を解ける():
    from dq3rom import items as it

    got = it.slot_of(0x81)
    assert got["item_id"] == 0x01 and got["equipped"] and got["category"] == "ぶき"
    got = it.slot_of(0x38)
    assert got["item_id"] == 0x38 and not got["equipped"]
    assert got["category"] == "たて"


def test_4人分の袋を切り出せる():
    from dq3rom import items as it

    ram = bytearray(0x800)
    ram[it.INVENTORY_ADDR:it.INVENTORY_ADDR + 32] = bytes([0xFF] * 32)
    ram[it.INVENTORY_ADDR] = 0x81                 # ★1 人目の 1 枠目
    ram[it.INVENTORY_ADDR + 8] = 0x20             # ★2 人目の 1 枠目
    got = it.inventory_of(ram)
    assert len(got) == 4
    assert [s["item_id"] for s in got[0]] == [0x01]
    assert [s["item_id"] for s in got[1]] == [0x20]
    assert got[2] == [] and got[3] == []
    assert it.known_ids(ram) == [0x01, 0x20]


# --- ★★ 本物のセーブで確かめる（⚠ 足場だけで緑にしない）---------------------


def _states():
    if not FCS.exists():
        return []
    return sorted(p for p in FCS.glob("DQ3_J.fc[0-9]"))


@pytest.mark.skipif(not _states(), reason="DQ3 のセーブが無い")
def test_初期装備が分類と合う():
    """★★★ ⚠⚠ **番地が正しいことの、識別性のある根拠** ★★★

    ⚠ 「それらしい値が並んでいる」では足りません。
    ★DQ3 の初期装備は **こんぼう / ぬののふく / かわのたて**で、
      これは `ぶき / よろい / たて` の**3 つの別々の範囲**に落ちます。

    ⚠ 番地がずれていれば、3 つとも別の分類になるはずです。
    """
    from retroux.core.bgmap import savestate as ss
    from dq3rom import items as it

    seen = []
    for path in _states():
        ram = ss.load(path).chunks["RAM"]
        for slots in it.inventory_of(ram):
            seen.extend((s["item_id"], s["category"], s["equipped"])
                        for s in slots)
    assert seen, "⚠⚠ どのセーブにも品が 1 つも無い（★番地が違う）"

    cats = {c for _, c, _ in seen}
    assert {"ぶき", "よろい", "たて"} <= cats, (
        "⚠⚠ 初期装備の 3 分類が揃わない: %s" % cats)
    # ★装備中の旗が立っているものがある（⚠ 全部 False なら bit7 の読み方が違う）
    assert any(eq for _, _, eq in seen), "⚠⚠ 装備中が 1 つも無い"
    # ⚠ ID は必ず 0x7F 未満（★マスクが効いている）
    assert all(0 <= i < 0x7F for i, _, _ in seen)


@pytest.mark.skipif(not _states(), reason="DQ3 のセーブが無い")
def test_空き枠を品と読まない():
    """⚠ `0xFF` は空き。★これを品として読むと「品 127」が並びます。"""
    from retroux.core.bgmap import savestate as ss
    from dq3rom import items as it

    for path in _states():
        ram = ss.load(path).chunks["RAM"]
        for slots in it.inventory_of(ram):
            assert all(s["raw"] != it.EMPTY_SLOT for s in slots)
            assert len(slots) <= it.SLOTS_PER_PC


# --- ★名前を覚える ----------------------------------------------------------


def _names(tmp_path=None):
    from dq3.knowledge.item_names import ItemNames

    return ItemNames(path=pathlib.Path(os.devnull))


def test_並びが合うときだけ覚える():
    """★★★ ⚠⚠ **ずれたまま覚えると、別の品の名前が付く** ★★★

    ★敵の名前と同じ守り方です（`EnemyNames.learn`）。
    """
    got = _names()
    assert got.learn([1, 2, 3], ["あ", "い"]) == 0, "⚠⚠ 数が合わないのに覚えた"
    assert got.learn([1, 2], ["あ", "い", "う"]) == 0
    assert got.learn([], []) == 0
    assert got.learn([1, 2], ["あ", ""]) == 0, "⚠ 読めなかった名前で覚えた"
    assert got.names == {}

    assert got.learn([1, 2], ["こんぼう", "どうのつるぎ"]) == 2
    assert got.names == {1: "こんぼう", 2: "どうのつるぎ"}
    # ★同じものをもう一度覚えても増えない
    assert got.learn([1, 2], ["こんぼう", "どうのつるぎ"]) == 0


def test_装備の旗を落として覚える():
    """⚠ 袋の値は `0x81` のように bit7 が立っています（★同じ品）。"""
    got = _names()
    got.learn([0x81], ["こんぼう"])
    assert got.names == {0x01: "こんぼう"}
    assert got.knows(0x01) and got.knows(0x81)
    assert got.label(0x81) == "こんぼう"


def test_知らない品は知らないと分かる形で出す():
    """★2026-09-03（RX3-0069）: 画面で読めていなくても、⚠ ROM から起こした品名があれば出す。

    ⚠⚠ ROM が無い環境では今までどおり「分類 ＋ 番号」（★裸の番号にしない）。
    """
    from dq3.knowledge import rom_names

    got = _names()
    if rom_names.available():
        assert got.label(0x38) == rom_names.item(0x38), got.label(0x38)
    else:
        assert "たて" in got.label(0x38) and "0x38" in got.label(0x38)
    assert got.label(None) == "（なし）"
    assert not got.knows(0x38), "⚠ ROM の名前を『画面で見た』ことにしてはいけない"


def test_保存先がGitの外():
    """⚠⚠ 覚えた名前を**リポジトリに残さない**（★方針 §3）。"""
    from dq3 import paths as P3
    from dq3.knowledge.item_names import DEFAULT_PATH

    # ⚠ 検査中は書き先が一時フォルダなので、repo 側の同じ道を見る（`paths.as_repo` / RX-0141）
    real = P3.as_repo(DEFAULT_PATH)
    assert "work" in real.parts, real
    import subprocess

    got = subprocess.run(["git", "check-ignore", "-q", str(real)],
                         cwd=ROOT)
    assert got.returncode == 0, "⚠⚠ 覚えた名前が Git 管理下にある"


# --- ★図鑑との繋がり --------------------------------------------------------


def test_図鑑が名前を使う():
    from dq3.knowledge import monster_book as mb

    got = _names()
    got.learn([0x65], ["やくそう"])

    class _Detail:
        drop = {"item_id": 0x65, "rate": "1/256"}

    assert mb.drop_label(_Detail(), got) == "やくそう"
    # ★画面で読めていなければ ROM の品名（RX3-0069）、⚠ ROM も無ければ分類＋番号
    from dq3.knowledge import rom_names
    fallback = mb.drop_label(_Detail(), _names())
    if rom_names.available():
        assert fallback == rom_names.item(0x65), fallback
    else:
        assert "どうぐ" in fallback
    assert mb.drop_label(None, got) == ""


def test_品なしの敵は品として出さない():
    from dq3.knowledge import monster_book as mb

    class _Detail:
        drop = {"item_id": None, "rate": "always"}

    assert mb.drop_label(_Detail(), _names()) == "（なし）"

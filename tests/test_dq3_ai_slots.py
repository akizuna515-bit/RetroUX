"""AI 用セーブスロットの決めごと（RX3-0031 / 2026-08-31）。

## ⚠⚠ 何を守っているのか

    slot 0〜4  人間用。**AI は書き込み禁止**
    slot 5〜9  AI が自由に使ってよい

★2026-08-31 に、依頼者のセーブが**上書きされて 3 つの場面が失われました**
（`RX3-0028`）。⚠ あれは依頼者自身の操作でしたが、★AI がやったら目も当てられません。
"""

from __future__ import annotations

import io
import pathlib
import re

import pytest

from dq3.testing import slots

ROOT = pathlib.Path(__file__).resolve().parents[1]
LUA = ROOT / "dq3" / "phase0" / "ai_state.lua"


def test_人のスロットへは書けない():
    for slot in range(slots.HUMAN_MIN, slots.HUMAN_MAX + 1):
        assert not slots.can_write(slot), "⚠⚠ スロット %d へ書けてしまう" % slot
        with pytest.raises(slots.SlotDenied):
            slots.check_write(slot)


def test_AIのスロットへは書ける():
    for slot in range(slots.AI_MIN, slots.AI_MAX + 1):
        assert slots.can_write(slot)
        assert slots.check_write(slot) == slot


def test_読むのは全部よい():
    """⚠ 禁じられているのは**書き込み**だけ（★人のセーブを見るのは無害）。"""
    for slot in range(10):
        assert slots.can_read(slot)


def test_範囲外と型違いを弾く():
    for bad in (-1, 10, 99, "5", 5.0, None, True):
        assert not slots.can_write(bad), "⚠ %r を通している" % (bad,)


def test_Luaと同じ数字である():
    """⚠⚠ **写しが 2 か所にある。** ★片方だけ変わるのを止める。

    Lua は FCEUX の中で動くので Python から呼べません。
    ⚠ だから写しは避けられない。→ ★ここで縛ります。
    """
    src = io.open(LUA, encoding="utf-8", newline="").read()
    got = re.search(r"M\.AI_MIN,\s*M\.AI_MAX\s*=\s*(\d+),\s*(\d+)", src)
    assert got, "⚠ Lua 側に AI_MIN / AI_MAX が無い"
    assert (int(got.group(1)), int(got.group(2))) == (slots.AI_MIN, slots.AI_MAX), (
        "⚠⚠ Python と Lua で数字が違う（★%s vs %s）"
        % ((slots.AI_MIN, slots.AI_MAX), got.groups()))


def test_Lua側も人のスロットを拒む():
    """★字面ではなく、⚠ **拒む道があること**を見る。"""
    src = io.open(LUA, encoding="utf-8", newline="").read()
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("--"))
    assert "function M.can_write" in body
    assert "if not M.can_write(slot) then" in body, (
        "⚠⚠ 保存の入口で確かめていない（★誰でも書けてしまう）")
    assert "persist" in body, (
        "⚠⚠ `persist` を呼んでいない（★ファイルに書かれません / 2026-07-31 実測）")


def test_人の道は触っていない():
    """⚠ `bridge.lua` の `_save_state` は**人が GUI から使う道**。

    ★0〜4 に保存できないと困るので、⚠ こちらの制限を持ち込まないこと。
    """
    bridge = (ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua").read_text(
        encoding="utf-8")
    assert "AI_MIN" not in bridge, "⚠⚠ 人の道に AI の制限が漏れています"

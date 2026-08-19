"""攻撃の見積もり（2026-08-03 / 「ガンガン行こうぜ」Phase 1）。

★★ **本物の Lua を走らせる。** ★★
（`test_battle_item_conditions.py` と同じ流儀）

## ⚠⚠ この日に踏んだ2つの取り違え（記録）

### 1. `wipes_targets` だけで「単独で足りる」と判断した

`wipes_targets` は「**届いた敵**を全部倒せるか」なので、
1 体にしか届かないギラでも `true` になります。

    ドラキー 2 体に対して
      サマルのギラ … 1 体だけ確定 → wipes_targets = true
      ムーンのバギ … 2 体とも確定 → wipes_targets = true

★先に見たほうが勝ち、**「サマル単独で足りる」と誤判定**しました。
→ 「**その場の敵を何体倒せるか**」で見るように直しました。

### 2. どちらでも足りるときに、ここで選ぼうとした

★両方が倒しきれるなら**戦闘はどちらでも終わる**ので、
本当に見るべきは MP や道具の残りです。
⚠ `combined_verdict` は MP を知らないので、決めるのは筋違いでした。
→ `"either"` を返して**呼ぶ側に選ばせます**。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "damage_estimate_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
          / "damage_estimate.lua")


@pytest.fixture(scope="module")
def result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def test_ハーネスが全部通る(result):
    assert "不合格 0" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"合計 (\d+) 項目", result)
    assert m and int(m.group(1)) >= 40, result


# --- ★ ROM から確定した式 -------------------------------------------------

def test_即死の成功率はROMの式どおり(result):
    """★`(7 - 耐性) / 7`。⚠ 推測ではありません。"""
    assert "OK   耐性 0（必ず効く） -> 1.000" in result, result
    assert "OK   耐性 7（効かない） -> 0.000" in result, result


def test_耐性が読めないときは0と混ぜない(result):
    """⚠⚠ 「効かない」と「分からない」は別のことです。"""
    assert "OK   ⚠ 耐性が読めない -> nil" in result, result


# --- ★ 確定撃破と期待撃破を分ける -----------------------------------------

def test_確定撃破は最低ダメージで見る(result):
    """⚠ 平均で見ると「倒せるはずが倒せない」が起きます。"""
    assert "OK   HP 10 にギラ（最低12）-> 確定 -> true" in result, result
    assert "OK   HP 15 にギラ（最低12/平均20）-> 確定ではない -> false" in result


def test_無駄打ちを数えない(result):
    """★HP 5 の敵にイオナズンを撃つのが「最善」に見えないように。"""
    assert "OK   HP 5 の敵に 20 -> 5 だけ数える -> 5" in result, result


# --- ★★ 連携（指示書 §7 の中核）------------------------------------------

def test_ムーン単独で倒せるならサマルは別行動(result):
    """★★★ **これが指示書の一番の要求**（§7.1 ケースB）。"""
    assert "OK   ★★ ムーン単独 -> サマルは別行動へ -> b_alone" in result, result


def test_2人なら倒せる場合を見分ける(result):
    """★§7.1 ケースA。"""
    assert "-> together" in result, result


def test_2人でも倒せない場合を見分ける(result):
    """★§7.1 ケースC。"""
    assert "-> neither" in result, result


def test_どちらでも足りるときは呼ぶ側に選ばせる(result):
    """⚠⚠ `combined_verdict` は MP を知らないので決めません。"""
    assert "OK   ★敵 1 体なら、どちらでも倒しきれる -> either" in result, result


def test_敵の数を渡し忽れると取り違えることを記録する(result):
    """⚠ 呼ぶ側は必ず `alive` を渡すこと。★ここで見張ります。"""
    assert "OK   ⚠ 敵の数を渡さないと either になってしまう" in result, result


# --- ★ Core と同じ流儀を守る ----------------------------------------------

def test_RAMもメニューも知らない():
    """★`item_conditions.lua` と同じ。⚠ 知ると実機が要ります。"""
    source = MODULE.read_bytes().decode("utf-8")
    for banned in ("memory.read", "joypad", "emu.", "gui."):
        assert banned not in source, f"⚠ {banned} が入っています"


def test_威力が分からなければnilを返す(result):
    """⚠⚠ **推測で埋めません。**"""
    assert "OK   ⚠ 威力が無い呪文 -> nil" in result, result


# --- ⚠⚠ 実機で見つかった見落とし（2026-08-03）-----------------------------

def test_呪文が効かない敵にダメージを見込まない(result):
    """★★★ **依頼者の実機指摘で見つかった。**

        「呪文が効かない相手に呪文を使っている？」

    ⚠⚠ キラーマシーンは `spell_damage: 7`（**まったく効かない**）。
      それなのにギラ・ベギラマ・イオナズンを撃っていました。

    ★`resist.spell_damage` を見ていなかったのが原因です。
      どの呪文がこの耐性を見るかは ROM の分岐で確定しています
      （`bank4.asm:6115-6215`）。
    """
    assert "OK   ⚠⚠ 効かない敵には実効ダメージ 0 -> 0" in result, result
    assert "OK   ⚠⚠ 倒せる数も 0 -> 0" in result, result


def test_効きにくい敵はダメージが減る(result):
    """★シルバーデビルは `spell_damage: 1` -> 6/7 しか通りません。"""
    assert "OK   ★効きにくい敵にはダメージが減る -> true" in result, result


def test_必ず効くのでなければ確定撃破にしない(result):
    """⚠ 1 回でも外れる可能性があるなら「確定」とは言えません。"""
    assert "OK   ⚠ 必ず効くわけではないので確定撃破にしない -> 0" in result


def test_耐性が読めない敵は呪文を封じない(result):
    """★図鑑に載っていない初遭遇の敵で、呪文を使えなくしないこと。

    ⚠ 「分からない」を「効かない」と混ぜると、初見の敵に何もできません。
    """
    assert "OK   ★耐性が分からない敵は、そのまま通るとみなす -> 20" in result

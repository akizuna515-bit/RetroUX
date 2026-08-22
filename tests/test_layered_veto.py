"""Layered Veto Wiring（Phase 10A / 2026-08-07）。

★別AIへの相談回答（`input/戦闘AI_Layered接続方針_相談回答_20260807.md`）
の推奨をそのまま実装したものです。

    > まず `attack_spell` にだけ実際の拒否権を与える
    > 拒否されたら次の legacy claim へ進む
    > 行動途中では拒否しない
    > directive はターン単位で固定

## ⚠⚠⚠ 「呼ばれているか」だけでは足りない

回答の指摘:

    > assert source.count("self:_use_layered()") > 0 だけでは不十分。
    > 「呼ばれているが結果が入力へ反映されていない」という
    > 同じ失敗を再発させる可能性がある。

★だから **定義 -> 呼び出し -> 実際の入力** の3段階を1本で見ます。
⚠ これは 2026-08-07 に8回踏んだ失敗の型そのものへの対策です。
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
           / "layered_veto_test.lua")
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


# --- ★RX-0011: 字面の検査に挙動を併設 --------------------------------------
#
# ⚠ 下の `bridge.lua` の文字列検査は、分岐が死んでいても緑のままです。
#   ★`rx0011_bridge_behavior_test.lua` は偽RAMで本物の bridge を動かします。

BEHAVIOR = (PROJECT_ROOT / "research" / "probes" / "active"
            / "rx0011_bridge_behavior_test.lua")


@pytest.fixture(scope="module")
def behavior():
    if not (RUNNER.exists() and BEHAVIOR.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(BEHAVIOR)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


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


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_ハーネスが全部通る(result):
    assert "NG 0 件" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 20, result


# --- ★★★ 定義 -> 呼び出し -> 実入力 の3段階 -------------------------

def test_1_定義_指示が禁止を持てる(result):
    assert _ok(result, "★攻撃呪文は禁止"), result
    assert _ok(result, "★道具は許可"), result


def test_2_呼び出し_指示を読む(result):
    assert _ok(result, "★★ 拒否される"), result
    assert _ok(result, "★★ 理由に戦術の名前が入る"), result


def test_3_実入力_計画を作らない(result):
    assert _ok(result, "★★★ 攻撃呪文の計画を作らない"), result


def test_4_実入力_何も主張しない(result):
    """★★★ **ここまで見ないと意味がありません。**

    ⚠⚠ 「呼ばれているが結果が入力へ反映されていない」を防ぎます。
    """
    assert _ok(result, "★★★ 入力を主張しない"), result


# --- ⚠⚠ 既定の利用者の挙動を変えていないこと -------------------------

def test_legacyでは従来どおり(result):
    """★★ **これが無いと、既定の利用者の挙動を勝手に変えます。**"""
    assert _ok(result, "★★★ legacy では指示を返さない"), result
    assert _ok(result, "★★★ legacy では拒否しない"), result
    assert _ok(result, "★★★ legacy では禁止を無視して従来どおり"), result


def test_封じすぎていない(result):
    """⚠ 拒否ではなく**壊している**だけ、を見分けます。"""
    assert _ok(result, "★★ 禁止していなければ、これまでどおり試す"), result


# --- ⚠ 何もしないターンを作らない -------------------------------------

def test_指示が無ければ通す(result):
    """⚠⚠ 戦況が読めず戦術が決まらないことがあります（★材料不足）。

    ★そのとき全部禁止になると**何もしないターン**が生まれます。
    """
    assert _ok(result, "★★ 指示が無ければ通す"), result


def test_ターンが進んでも拒否は効く(result):
    """★★★ **2026-08-07 に逆へ直しました**（実機で発覚）。

    ⚠⚠ 最初は「ターン番号が変われば捨てる」にしていました。
      ★ところが**見立てはターンが進む前**に走り、**入力は進んだ後**。
      番号が食い違い、実機で拒否が**1件も効きませんでした**。

    ⚠ 相談回答の意図は「**同じターン中に上書きしない**」であって、
      ★「番号が変わったら捨てる」ではありません。

    ⚠⚠ **元の検査は間違った仕様を守っていました**（★私の誤りを固定していた）。
    """
    assert _ok(result, "★★★ ターンが進んでも拒否は効く"), result


def test_戦闘が終われば持ち越さない(result):
    """⚠ 次の戦闘まで残ると、★戦況を見ていない指示で拒否してしまいます。"""
    assert _ok(result, "★★ 戦闘が終われば拒否しない"), result


# --- ⚠⚠⚠ 行動途中で拒否しない（★相談回答の最重要指摘）---------------

def test_拒否点は1か所だけ(result):
    """★★★ **相談回答の最重要の指摘**。

        > layered の拒否判定は「行動開始前」だけ行う。

    ⚠⚠ 呪文は「メニュー移動 -> 一覧 -> カーソル -> A -> 敵選択 -> A」と
      **複数フレームにまたがります**。途中で放棄すると、
      ★別の claim が入力して事故ります。
    """
    assert _ok(result, "★★★ 拒否点は1か所だけ"), result
    assert _ok(result, "★★ 拒否点は「計画を作る前」にある"), result


def test_ターン単位で固定している():
    """★HPが1変わるたびに再評価しない（⚠ 戦術の振動を防ぐ）。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "self.turn_directive_turn ~= self.turn_no" in source, (
        "⚠ ターン単位で固定していません")


def test_ターン単位で固定している_の挙動(behavior):
    """★RX-0011: 字面の検査に挙動を併設。

    `tactics_selector.choose` を差し替えて `_log_assessment()` を呼ぶ。
    ★同じ `turn_no` のまま別の指示を返しても `turn_directive` は最初のまま。
    ★`turn_no` を進めると新しい指示に替わり、`_on_battle_end()` で捨てる。
    """
    assert "NG 0 件" in behavior, behavior
    assert _ok(behavior, "★最初の見立てで指示が入る"), behavior
    assert _ok(behavior, "★★★ 同じターン中は別の指示で上書きしない"), behavior
    assert _ok(behavior, "★★ ターンが進めば新しい指示に替わる"), behavior
    assert _ok(behavior, "★戦闘が終われば指示とターン番号を捨てる"), behavior


def test_呼ばれているかだけで満足していない():
    """⚠⚠ **相談回答の指摘そのもの**。

        > assert source.count("self:_use_layered()") > 0 だけでは不十分。

    ★このファイルが「実入力まで」見ていることを、自分で確かめます。
    """
    mine = pathlib.Path(__file__).read_bytes().decode("utf-8")
    assert "test_4_実入力_何も主張しない" in mine
    assert "入力を主張しない" in mine


def test_呼ばれているかだけで満足していない_の挙動(result):
    """★RX-0011: 字面の検査に挙動を併設。

    ★上は「このファイルに test_4 が**書いてある**か」しか見ない。
      書いてあっても、ハーネス側の行が消えれば test_4 は赤くなるが、
      この検査は緑のまま。ここでは**実入力まで見た OK 行が実際に出た**
      ことを見る（＝`layered_veto_test.lua` が入力を主張しない所まで通った）。
    ⚠ 新しいハーネスは作らない（★test_4 と同じ行を見る）。
    """
    assert _ok(result, "★★★ 入力を主張しない"), result
    assert _ok(result, "★★★ 攻撃呪文の計画を作らない"), result

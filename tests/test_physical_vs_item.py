"""道具と通常攻撃を比べる（2026-08-08 / 依頼者の指摘）。

    > サマルではやぶさの剣（2回攻撃）と、魔道士の杖（期待15ぐらい）だと、
    > はやぶさのほうが守備力大きい敵以外には期待値高いように思える

## ⚠⚠ そのとおりでした

杖は `when: spell_may_damage`（＝効く敵が居れば使う）だけで決めていて、
★**通常攻撃と比べていませんでした**。

## ★ 実測に基づく比較（こうげき力100・はやぶさのけん2回攻撃）

    敵の守備力   はやぶさ2回   杖（ギラ相当 期待20）
          20        67.5        20   -> ★はやぶさ
          60        52.5        20   -> ★はやぶさ
         100        37.5        20   -> ★はやぶさ
         150        18.8        20   -> ⚠ 杖

## ⚠ 物理の式は「攻略情報」どまり（★ROM からではありません）

    ダメージ ＝ (こうげき力 − 守備力/2) / 4 〜 (こうげき力 − 守備力/2) / 2

⚠⚠ **だから僅差で判断を変えません**（★`margin` で余裕を持たせます）。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "physical_vs_item_test.lua")
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
DISASM = PROJECT_ROOT / "work" / "dq2-disasm" / "src" / "us" / "prg"


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
    assert m and int(m.group(1)) >= 24, result


# --- ★★★ 依頼者の場面 ---------------------------------------------------

def test_柔らかい敵には通常攻撃を選ぶ(result):
    """★★★ **依頼者の指摘そのもの**。"""
    assert _ok(result, "★★★ 守備力20 の敵には**通常攻撃**（杖を使わない）"), result
    assert _ok(result, "★守備力100 でもまだ通常攻撃"), result


def test_硬い敵には杖を使う(result):
    """⚠ 「常に通常攻撃」にしてしまわないこと。"""
    assert _ok(result, "★★ 守備力150 なら杖のほうが上"), result


def test_はやぶさのけんを2回として数える(result):
    assert _ok(result, "★★ はやぶさのけん（2回）は倍"), result
    assert _ok(result, "★★ 2回攻撃だと分かるように書く"), result


# --- ⚠⚠ 甘く見積もらない ------------------------------------------------

def test_守備力が読めない敵を甘く見積もらない(result):
    """⚠⚠ 守備力 0 として計算すると、★初見の敵に通常攻撃を過大評価します。"""
    assert _ok(result, "★★ 守備力が読めないときは控えめに見積もる"), result


def test_かすり傷を0にしない(result):
    """⚠ 0 にすると「通常攻撃は無価値」と読めてしまいます。"""
    assert _ok(result, "⚠ 0 にしない（★通常攻撃が無価値には見せない）"), result


def test_見積もれないときは封じない(result):
    """★「分からないから使わない」にすると、⚠ 初見の敵に何もできません。"""
    assert _ok(result, "⚠ 道具の威力が分からなければ使ってよい"), result
    assert _ok(result, "⚠ 通常攻撃を見積もれなければ使ってよい"), result
    assert _ok(result, "⚠ こうげき力が読めなければ従来どおり使う"), result


def test_いちばん硬い敵で比べる(result):
    """⚠⚠ 平均にすると、★硬い敵が1体混ざったときに読み違えます。"""
    assert _ok(result, "★★ 硬い敵が1体でも居れば使う（⚠ 平均で薄めない）"), result


# --- ★★★ 組み合わせで素通りしない（⚠ 2026-08-08 に踏んだ）--------------

def test_組み合わせても比較が効く(result):
    """⚠⚠ **子に `expected_damage` を渡し忘れていました。**

    ★すると `beats_physical` は「威力が分からない」で**常に true**。
      つまり `all:` で組み合わせても**素通り**していました。
    """
    assert _ok(result, "★★★ 組み合わせでも通常攻撃と比べる（⚠ 素通りしない）"), result


# --- ⚠ 設定と実装の食い違いを防ぐ ----------------------------------------

def test_杖に比較が付いている():
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    items = ((config.get("auto_input") or {}).get("battle_items") or {}
             ).get("items") or {}
    wands = [i for i in items if str(i.get("name", "")).endswith("つえ")]
    assert wands, "⚠ 杖が設定にありません"
    for wand in wands:
        assert wand.get("expected_damage"), (
            f"⚠ {wand.get('name')} に期待ダメージがありません"
            "（★無いと比較が素通りします）")
        whens = {p.get("when") for p in (wand.get("all") or [])}
        assert "beats_physical" in whens, (
            f"⚠ {wand.get('name')} が通常攻撃と比べていません")


def test_装備中でなければ2回にしない():
    """⚠⚠ **持っているだけでは2回攻撃になりません。**

    ★`0x49` は `0x09 | 0x40` で、bit6 が「装備中」の印です。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    at = source.index("function Bridge:_attack_hits")
    body = source[at:at + 1200]
    assert "want + 0x40" in body, (
        "⚠⚠ 装備中の印（bit6）を見ていません（★持っているだけで2回になります）")


def test_複数回攻撃の武器が設定にある():
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    weapons = (config.get("auto_input") or {}).get("multi_hit_weapons") or []
    assert weapons, "⚠ 複数回攻撃の武器が設定にありません"
    falcon = [w for w in weapons if w.get("id") == 0x09]
    assert falcon and falcon[0].get("hits") == 2, falcon


def test_装備フラグの根拠がROMにある():
    """★★ **推測ではありません。**

    ⚠ 逆アセンブルが無い環境では飛ばします（★ROM は Git 管理外）。
    """
    bank4 = DISASM / "bank4.asm"
    if not bank4.exists():
        pytest.skip("逆アセンブルが無い環境")
    text = bank4.read_bytes().decode("utf-8", "replace")
    assert "Falcon Sword (equipped)" in text
    assert "lda #$49" in text


# --- ⚠⚠ 敵の見立てを2か所で作らない -------------------------------------

def test_敵の見立ては1か所で作る():
    """⚠⚠ **`_attack_turn_plan` と `_item_context` が同じものを別々に
    組み立てていました**（2026-08-08 に気づいた）。

    ★守備力を足そうとして「同じ行が2つある」ことで分かりました。
    ⚠ 片方だけ直すと、攻撃と道具で**違う敵が見えます**。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))
    assert "function Bridge:_enemy_view" in code
    assert code.count("enemies[#enemies + 1] = { id = e.id") == 1, (
        "⚠ 敵の見立てを組み立てる場所が増えています（★1か所に寄せてください）")
    assert code.count("self:_enemy_view()") >= 2, (
        "⚠ 共通の見立てを使っていない呼び出しがあります")

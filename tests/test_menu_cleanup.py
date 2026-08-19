"""戦闘後にメニューが開いたら閉じる（2026-08-07 / 依頼者報告の不具合）。

    > いまずっとメニューでたまま。

## ⚠⚠ 「B を押して閉じる」仕組みは**元からありました**

`_claim_menu_cleanup()` が 8フレーム押して8フレーム離すのを 600フレーム
まで繰り返します。★実装は正しい。
⚠ ところが実機22戦中3戦で、**1度も動きませんでした**。押していたのは
全部ハーネス側（`request`）で、`bridge` は 0 回。

## ★★★ 原因: `frames_since_battle` の名前と中身が違った

0 に戻していたのは「戦闘が終わったとき」ではなく
★「**自動入力が主張したとき**」（`_apply_input` の `claim ~= nil`）。

⚠ AUTO が効いていない戦闘（手動・危険状態で見送り・キャラ別AI操作OFF）
では1度も戻らず、実測でこうなっていました:

    ハーネスの計測    戦闘終了の 4〜6 フレーム後にメニューが開いた
    bridge の計測     戦闘終了から 1401 / 2301 / 2279 フレーム

→ しきい値 45 を超えるので「**人が開けた**」と判断して手を出さない。

★戦闘が終わったかどうかは、自動入力が働いたかとは**無関係**です。
  `_on_battle_end()`（立ち下がり）で数え直します。
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
           / "menu_cleanup_test.lua")
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


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
    """⚠ 条件が揃わずに1件も走らないまま「成功」にしない。"""
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 8, result


def test_戦闘終了で数え直す(result):
    """★★★ **これが直したところそのもの**。"""
    assert _ok(result, "★★★ 戦闘終了で 0 に戻る"), result
    assert _ok(result, "★閉じる期限が入り直す"), result


def test_実際にBを押しにいく(result):
    """★★ **「数え直した」だけでは足りません。**

    ⚠ 実際に後始末が主張を返すところまで見ないと、
      ★別の条件で降りていても気づけません。
    """
    assert _ok(result, "★★★ B を押して閉じにいく"), result


def test_押しっぱなしにしない(result):
    """⚠⚠ 押しっぱなしだと閉じきりません。

    ★過去の実測: 12フレーム周期・5フレーム押下では $002F に B が
      届いているのに閉じず、期限を使い切って方向キーが吸われ続けました。
    """
    assert _ok(result, "★押して離すを繰り返す"), result


def test_人が開けたメニューは閉じない(result):
    """⚠⚠ **元の設計を壊さない。**

    ★プレイヤーが自分で開けたメニューを勝手に閉じるのは、
      「操作を奪われた」という別の不具合になります。
    """
    assert _ok(result, "★★ 人が開けたメニューは勝手に閉じない"), result


def test_マクロ操作中は手を出さない(result):
    assert _ok(result, "★抑止フラグが立っていれば降りる"), result


def test_直す前の壊れ方を再現できる(result):
    """★★★ **これが無いと「直った」と言えません**（空振り防止）。

    ⚠⚠ 直した後のコードで全部 OK になるのは当たり前です。
      ★「数え直さなければ降りる」ことを**同じ検査の中で**確かめて、
        はじめて「数え直したから直った」と言えます。
    """
    assert _ok(result, "★★ 数え直さないと降りる"), result


def test_戦闘終了の立ち下がりで数え直している():
    """⚠ 数え直す場所が `_apply_input` に戻っていないこと。

    ★`_on_battle_end()`（戦闘状態の立ち下がり）が唯一の起点です。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    start = source.index("function Bridge:_on_battle_end")
    body = source[start:start + 2500]
    assert "self.frames_since_battle = 0" in body, (
        "⚠⚠ 戦闘終了で数え直していません")

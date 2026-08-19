"""「ぼうぎょ」の入力が実機で1度も通っていなかった（2026-08-12）。

依頼者の実機ログ（`work/retroux.log` / 8-11 18:26 と 8-12 07:31）:

    samaltria は指定の道具が無いので防御します（亀の子戦術）
    moonbrooke は指定の道具が無いので防御します（亀の子戦術）
    防御の入力が 17 回で進まないため、この番は従来どおりにします（moonbrooke）

これが 3ターン全部で出て、行動ログは全員「たたかう」でした。
★つまり **亀の子戦術は実質「全員たたかう」** になっていました。

## ★★★ 原因: `_claim_defend` だけ「どの画面か」を見ていなかった

兄弟の `_claim_battle_heal` / `_claim_battle_item` は
「戦闘コマンドか どうぐ の画面以外では何も主張しない」と明示しています。
⚠ `_claim_defend` の門番は `cursor_x ~= 255` **だけ**でした。

⚠⚠ ところが `memory_map.yaml` の `menu_cursor_x` にはこう書いてあります:

    戦闘中は 0xFF（無効値）になる。

★つまり `cx == 255` は「戦闘コマンドが開いている」を意味しません。
  メッセージ・演出の間も素通りして方向キーを押し続け、
  歯止め（16回）を**コマンドが開く前に使い切って**いました。

## ⚠ なぜテストで気づけなかったか

`tests/test_fixed_action_wiring.py` の「道具が無ければ防御にフォールバック
できる」は、**ソースに文字列があるか**しか見ていませんでした（`in src`）。
★呼んでいないので、壊れたまま緑でした。ここでは**実際に呼びます**。

⚠ 実機もセーブステートも要りません（偽の RAM で戦闘コマンドを模します）。
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
           / "defend_input_test.lua")
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
    assert m and int(m.group(1)) >= 13, result


def test_コマンドメニューでは防御できる(result):
    """★機構そのものは正しい（下・下・A の 3 回で決まる）。

    ⚠ ここが通ることが大事です。「押し方が悪い」のではなく
      「押す場面を間違えていた」と切り分けられます。
    """
    assert _ok(result, "★ぼうぎょを決定できる"), result
    assert _ok(result, "★押下は 3 回で足りる"), result


def test_演出中は1回も押さない(result):
    """★★★ **これが直したところそのもの**。"""
    assert _ok(result, "★★★ コマンド画面でなければ1回も押さない"), result
    assert _ok(result, "★★ 歯止め（押下数）を減らさない"), result


def test_主張しないときはnilを返す(result):
    """⚠⚠ `{}` は「全ボタンを離す」の指示です。

    固定戦略の呼び出し元はそれをそのまま返すので、`{}` にすると
    ★**メッセージ送りの A まで毎フレーム打ち消して戦闘が止まります**。
    """
    assert _ok(result, "★演出中は nil"), result


def test_実機で起きた並びで2人目も防御できる(result):
    """★★ **1人ぶんだけ試しても足りません**（依頼者の実機は3人）。

    ⚠ 実機で諦めていたのは常に2人目以降でした。
      「前の人 → 演出 → 自分の番」を通しで確かめます。
    """
    assert _ok(result, "★1人目（samaltria）が防御できる"), result
    assert _ok(result, "★★ 演出の間は押さない"), result
    assert _ok(result, "★★★ 2人目（moonbrooke）も防御できる"), result
    assert _ok(result, "★2人目が決定した行"), result


def test_直す前の壊れ方を再現できる(result):
    """★★★ **これが無いと「直った」と言えません**（空振り防止）。

    ⚠⚠ 直した後のコードで全部 OK になるのは当たり前です。
      ★門番を外した写しを読み込んで、**同じ検査の中で**
        実機と同じ「17 回で進まない」が出ることまで見ます。
    """
    assert _ok(result, "⚠⚠ 門番が無いと、演出中に押し切って諦める"), result
    assert _ok(result, "⚠⚠ 実機ログと同じ文面が出る"), result


def test_門番が兄弟と揃っている():
    """⚠ `_claim_defend` が「どの画面か」を見ていること。

    ★`_claim_battle_heal` / `_claim_battle_item` と同じ考え方です。
    ⚠ `cursor_x` だけを見る形に戻っていたら赤くします
      （`cursor_x` は戦闘中ずっと 0xFF なので目印になりません）。
    """
    # ⚠ bridge.lua は CRLF。改行を揃えないと関数の終わりを探せません。
    source = BRIDGE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    start = source.index("function Bridge:_claim_defend(m)")
    body = source[start:source.index("\nend\n", start)]
    assert "menu_id" in body, (
        "⚠⚠ 画面を見ずに押しています（演出中に歯止めを使い切ります）")
    assert "battle_menu" in body, "⚠ 戦闘コマンドメニュー以外でも押します"


def test_番が変わったら数え直す():
    """⚠⚠ 呼び出し元の reset に頼らないこと。

    ★`_claim_manual_character` は `menu ~= battle_menu` で早期 return
      するので、**通らない場面があります**。前提が崩れると:
        ・前の人の押下数を引き継いで、すぐ諦める
        ・⚠ 前の人の押下サイクルが残り、次の人の番に
          **行0（たたかう）で A を押す**（probe の 4 で実際に踏みました）
    """
    # ⚠ bridge.lua は CRLF。改行を揃えないと関数の終わりを探せません。
    source = BRIDGE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    start = source.index("function Bridge:_claim_defend(m)")
    body = source[start:source.index("\nend\n", start)]
    assert "self.fb_member ~= m.index" in body, (
        "⚠⚠ 番の変わり目を自分で見ていません")
    assert "self.fb_button = nil" in body, (
        "⚠ 前の人の押下サイクルが残ります（行0で A を押します）")

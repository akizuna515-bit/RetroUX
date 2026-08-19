"""ログ棚卸しの検出器そのものを検査する（製品版ログ整理 Phase 1）。

## ★★ なぜ検出器にテストを書くのか

⚠ この検出器の出力は、**「ログを減らした」の分母**になります。
  ★数え漏れ（少なく数える）と誤検知（多く数える）は、どちらも
  **削減の成果を嘘にします**。しかも表を見ても気づけません。

  実際、作っている最中に2つ踏みました:

    ・判定ルールの中の `log.warning(` という**文字列**を出力箇所として数えた（+16 件）
    ・docstring に書いた使い方の見本 `say(...)` を数えた（+3 件）

  どちらも「多く数える」向きです。⚠ 実在しないものを削ったことにできてしまいます。

## ⚠ ここで固定していないこと

★出力箇所の**総数**は固定しません（コードが増えれば変わるのが正しい）。
  固定するのは**検出器の性質**です:

    ・実在する呼び出しを拾う
    ・説明文の中の見本を拾わない
    ・自分自身を拾わない
    ・未判定を残さない（指示書 §30 の完了条件）
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

audit = pytest.importorskip("audit_log_sites")


@pytest.fixture(scope="module")
def rows():
    return audit.collect()


# --- ★ 拾えていること ---------------------------------------------------

def test_実在するPythonのログを拾う(rows):
    """`observer.py` の「想定外の座標変化」は実在する DEBUG 出力。

    ⚠ 以前はここで「新しい道」を使っていたが、Phase 4 で**消した**ので
      検査が空振りになった。★見本には「残す」と決めたものを使う。
    """
    got = [r for r in rows
           if r["file"].endswith("navigation/observer.py")
           and "想定外の座標変化" in r["snippet"]]
    assert got, "observer.py の DEBUG 出力を拾えていない"
    assert got[0]["level"] == "DEBUG"


def test_実在するLuaのログを拾う(rows):
    got = [r for r in rows
           if r["file"].endswith("bridge.lua") and r["kind"] == "lua-log"]
    assert len(got) > 50, f"bridge.lua の self:log が少なすぎる: {len(got)}"


def test_Luaのイベントを拾う(rows):
    names = {r["detail"] for r in rows if r["kind"] == "lua-emit"}
    # ★指示書 §7 の中核。これを取り逃がすと棚卸しの意味が無い
    assert "battle_decision_snapshot" in names
    assert "battle_action" in names


def test_本文が次行にある呼び出しも中身が読める(rows):
    """⚠ `self:log(string.format(` は本文が次の行から始まる。

    ★これを1行しか見ないと、24 件が「何を出しているか分からない」まま残った。

    ⚠ 行番号では当てない（★コードが動くたびにずれる。実際にずれた）。
      **本文で探す**。
    """
    got = [r for r in rows
           if r["file"].endswith("bridge.lua")
           and "戦闘で回復します" in r["snippet"]
           and r["text"].startswith("self:log(")]
    assert got, "続きの行まで読めていない（本文が次行にある呼び出し）"
    # ★呼び出し行そのものには本文が無いこと（＝snippet が効いている証拠）
    assert "戦闘で回復します" not in got[0]["text"]


# --- ⚠ 拾ってはいけないもの ---------------------------------------------

def test_説明文の中の見本を数えない(rows):
    """`core/console.py` の docstring にある `say(...)` の見本。"""
    got = [r for r in rows
           if r["file"].endswith("core/console.py") and r["line"] in (13, 28, 29)]
    assert got == [], f"docstring の見本を数えている: {got}"


def test_検出器自身を数えない(rows):
    """⚠ 判定ルールは `log.warning(` などの**文字列**を持つ。"""
    bad = [r for r in rows if "audit_log_sites.py" in r["file"]
           or "build_log_inventory.py" in r["file"]]
    assert bad == [], f"検出器自身を数えている: {bad}"


def test_同梱の見本Luaを数えない(rows):
    """`tools/fceux/luaScripts/` は FCEUX 同梱。この計画の対象外。"""
    bad = [r for r in rows if "tools/fceux" in r["file"]]
    assert bad == [], f"FCEUX 同梱の見本を数えている: {len(bad)} 件"


def test_CLIの標準出力を製品ログと混ぜない(rows):
    """★CLI の `print` は「そのコマンドの出力」。削減対象ではない。"""
    kinds = {r["kind"] for r in rows}
    assert "cli-stdout" in kinds, "CLI の標準出力を区別していない"
    cli = [r for r in rows if r["kind"] == "cli-stdout"]
    # ⚠ 製品ランタイムの中心である bridge.lua が CLI 扱いになっていないこと
    assert not any("bridge.lua" in r["file"] for r in cli)


# --- ★ 指示書 §30: 未判定を残さない -------------------------------------

def test_未判定が0件である():
    """★これが完了条件（指示書 §30）。

    ⚠ 出力箇所が増えて判定ルールに当たらなくなると、ここが赤くなる。
      **表に載らないまま見落とす**のを防ぐための歯止め。
    """
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_log_inventory.py"), "--check"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", env={"PYTHONUTF8": "1", "PATH": ""},
        timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr

"""判定どおりに**直してあるか**を見る（製品版ログ整理）。

## ⚠⚠ これが無かったせいで抜けた

`build_log_inventory.py --check` は **「判定が付いているか」**しか見ない。
★「判定どおりに直したか」は**別のこと**で、誰も見ていなかった。

実際、2026-08-13 に依頼者から「修正は完了か」と聞かれて数え直したところ、
**11 件のずれ**が見つかった:

    4 件  py-log   判定=KEEP-DEBUG   実際=INFO   ← ★Python 側は適用漏れ
    3 件  lua-log  判定=MOVE-TO-EVENT 実際=INFO  ← ⚠ 検出器が動的な段階を読めていない
    4 件  ルールの側が誤り（★コードのほうが正しかった）

⚠ 適用スクリプト（`apply_lua_log_levels.py`）は **Lua しか直さない**。
★Python 側は手で直す前提だったが、そのことがどこにも書かれていなかった。

## ★ ここで見ること

判定から**あるべき段階**が決まるものについて、
実際に出している段階と一致していること。

⚠ `MERGE` / `KEEP-EVENT` / `KEEP-CLI` / `INFRA` は段階が決まらないので対象外。
⚠ `DYNAMIC`（その場で決まる段階）も対象外。★ただし「段階を渡している」ことは確かめる。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

pytest.importorskip("build_log_inventory")

from build_log_inventory import build  # noqa: E402

#: 判定 → あるべき段階。⚠ ここに無い判定は「段階が決まらない」
WANT = {
    "KEEP-DEBUG": "DEBUG",
    "KEEP-INFO": "INFO",
    "KEEP-WARNING": "WARNING",
    "KEEP-ERROR": "ERROR",
    # ★human log からは落とす（events へ移すのは別作業 / §6）
    "MOVE-TO-EVENT": "DEBUG",
    "MOVE-TO-RESEARCH-TOOL": "DEBUG",
    "SUPPRESS-DUPLICATE": "DEBUG",
    # ★★ 2026-08-14 / RX-0040: **ここに MERGE が無かった** ★★
    #
    #   ⚠⚠ そのせいで、`[敵]` `[戦術]` `[役割]` が **INFO のまま3行**
    #     出ているのを**この検査が見逃した**（実機で 16分・4戦闘 = 12行）。
    #
    #   ★MERGE は「1行へまとめる」判断なので、
    #     **まとめた先が INFO / 元の行は DEBUG** になるのが正しい形。
    #   ⚠ まとめる行そのものは手で書くので、
    #     `tests/test_battle_start_summary.py` が別に見張る。
    "MERGE": "DEBUG",
}

#: 段階を持てる種別だけを見る
LEVELLED = ("lua-log", "py-log")


@pytest.fixture(scope="module")
def judged():
    rows, unjudged = build()
    assert unjudged == [], f"未判定が {len(unjudged)} 件"
    return rows


def test_判定どおりの段階になっている(judged):
    """★★ **これが要**。⚠ 「判定を付けた」で終わらせない。"""
    bad = []
    for r in judged:
        want = WANT.get(r["verdict"])
        if want is None or r["kind"] not in LEVELLED:
            continue
        got = r["level"]
        if got == "DYNAMIC":
            # ★その場で段階が決まる形（`ended and "DEBUG" or "WARNING"`）。
            #   ⚠ 中身までは見ない。★「段階を渡している」ことは確かめられている
            continue
        if got != want:
            bad.append(f"{r['file']}:{r['line']}  判定={r['verdict']} "
                       f"あるべき={want} 実際={got}\n      {r['text'][:76]}")
    assert not bad, (
        f"⚠ 判定と実際の段階がずれています（{len(bad)} 件）。\n"
        "★どちらかが誤りです。コードを直すか、判定を直してください:\n  "
        + "\n  ".join(bad))


def test_適用漏れが起きやすい所を名指ししておく():
    """⚠ 道具は Lua しか直さない。★そのことを道具自身に書いておく。

    ★書いていないと、次の人（＝次の私）が同じ抜けをやる。
    """
    src = (SCRIPTS / "apply_lua_log_levels.py").read_text(encoding="utf-8")
    assert "Python" in src, (
        "⚠ `apply_lua_log_levels.py` に「Python 側は直さない」旨が書かれていない")


def test_未判定が0件である():
    """★指示書 §30 の完了条件。⚠ 増えた出力箇所を見落とさないため。"""
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_log_inventory.py"), "--check"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", env={"PYTHONUTF8": "1", "PATH": ""}, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_段階を持たないLuaのlogが残っていない(judged):
    """⚠⚠ Phase 2 の中心。★既定 INFO に頼りきった行を増やさない。

    ⚠ 「INFO のまま」自体は誤りではない（起動・終了・戦闘終了などは INFO）。
      ★ここで見るのは **判定が INFO 以外なのに INFO のまま**の行が無いこと
      （＝上の検査と同じ）で、この検査は**件数の見張り**。
    """
    lua = [r for r in judged if r["kind"] == "lua-log"]
    info = [r for r in lua if r["level"] == "INFO"]
    # ★Phase 2 前は 115 件すべてが段階なし（＝実質 INFO）だった。
    #   ⚠ ここが増えていくなら、判定を見直す合図。
    assert len(info) <= 30, (
        f"段階を渡していない Lua の log が {len(info)} 件あります"
        "（★Phase 3 完了時点は 21 件）")

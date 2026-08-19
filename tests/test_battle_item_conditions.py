"""戦闘中に道具を使う条件（2026-08-01 / 課題 #62）。

★★ **本物の Lua を走らせる。** ★★

## 依頼者の実機確認（2026-08-01）

    「ちからのたてを使わない？（サマルトリア装備）
      ※本人へのベホイミなので本人向けの機能」

    「ひかりの剣をサマルトリアに渡した。マヌーサが聞きそうな的には使いたい」

    「いなずまの剣を手に入れた。ローレシアが雑魚多い場合は使いたい」

## ⚠ 何が足りなかったか

いまの `battle_items` は「上から優先」で**いつでも使う**形でした。
杖（敵にダメージ）だけならそれでよかったのですが、

  ・回復の盾を、無傷のときに使う
  ・全体攻撃の剣を、敵1匹に使う

は明らかに無駄です。

## ⚠⚠ 効果は未検証です

3つの効果は**依頼者の証言**によるもので、ROM では確かめていません
（道具の効果表がまだ解読できていない）。★証言のほうが確かな一次情報です。
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
           / "item_conditions_test.lua")
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


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


def test_the_harness_passes(result):
    assert "不合格 0" in result, result


def test_it_reports_enough_checks(result):
    m = re.search(r"合計 (\d+) 項目", result)
    assert m and int(m.group(1)) >= 32, result


# --- 依頼者の3つの要望が、そのまま検査になっていること ------------------

def test_the_shield_heals_only_its_own_holder(result):
    """★★ 「本人へのベホイミなので本人向けの機能」 ★★

    ⚠ 一番HPが低い**他人**は治せない。だから本人のHPで判断する。
    """
    assert "OK   HP 100/100 -> 使わない" in result, result
    assert "OK   HP 50/100（5割）-> 使う" in result, result
    assert "OK   ⚠ 本人が元気なら、他人が瀕死でも使わない" in result, result


def test_the_light_sword_waits_for_a_target_that_can_be_dazzled(result):
    """★★ 「マヌーサが聞きそうな的には使いたい」 ★★"""
    assert "OK   耐性 0（必ず効く）-> 使う" in result, result
    assert "OK   耐性 7（効かない）-> 使わない" in result, result
    assert "OK   ★1体でも効きそうなら使う" in result, result


def test_the_bolt_sword_waits_for_a_clump(result):
    """★★ 「雑魚が１グループ複数で残っていたら」 ★★

    依頼者の要望は2段階でした（2026-08-01）:

      1回目「ローレシアが雑魚多い場合は使いたい」  -> 敵の総数で判断
      2回目「もっと厳しくしたい。雑魚が１グループ複数で残っていたら
             ぐらいでいいかもしれない」          -> **同じ敵の数**で判断

    ⚠ 違う敵が1体ずつ3種類なら、全体攻撃の値打ちは薄い。
    """
    assert "OK   同じ敵1体 -> 使わない" in result, result
    assert "OK   同じ敵2体 -> 使う" in result, result


def test_a_mixed_crowd_is_not_worth_the_bolt_sword(result):
    """★★ ここが「厳しくした」所 ★★

    ⚠ 旧い条件（敵の総数）なら、違う敵3体でも使ってしまっていた。
    """
    assert "OK   違う敵が1体ずつ3種類 -> 使わない" in result, result
    assert "OK   ★旧い条件なら3体で使ってしまう（比較）" in result, result


def test_one_clump_among_singles_still_counts(result):
    """★混ざっていても、**どれか1組がまとまっていれば**使う。"""
    assert "OK   1体 + 同じ敵2体 -> 使う" in result, result


def test_defeated_enemies_are_not_counted(result):
    """★倒した個体は数えない（残っている数で判断する）。"""
    assert "OK   同じ敵3体のうち2体は倒れている -> 使わない" in result, result
    assert "OK   同じ敵4体のうち2体は生きている -> 使う" in result, result


def test_enemies_with_an_unreadable_id_are_not_lumped_together(result):
    """⚠ IDが読めない個体を同じ組と見なさない。

    ★まとめてしまうと、違う敵を1組と誤解して使ってしまう。
    """
    assert "OK   id が nil の敵2体 -> 使わない" in result, result


# --- ⚠ 読めないときの倒れ方（安全側がどちらかは条件で違う）--------------

def test_an_unreadable_hp_stops_the_heal(result):
    """⚠ HPが読めなければ**使わない**。

    ★回復は急ぐものではないので、分からないまま使って1ターン損するより待つ。
    """
    assert "OK   HP が nil" in result, result


def test_unreadable_enemies_still_count_as_a_crowd(result):
    """⚠ HPが読めない敵は**居るものとして数える**。

    ★読めないことを理由に「敵が少ない」と判断すると、本当は多いのに
      全体攻撃を使わなくなる（安全でない側へ倒れる）。
    """
    assert "OK   hp が nil の同じ敵2体 -> 使う" in result, result


def test_an_unknown_resistance_is_worth_trying(result):
    """⚠ 耐性が読めない敵は「効くかもしれない」として使う。

    ★外しても1ターン損するだけ。新しい敵にいつまでも使わないほうが損。
    """
    assert "OK   resist が無い" in result, result


def test_a_misspelled_condition_stops_the_item(result):
    """⚠ 知らない条件は**使わない**。

    ★綴り違いで毎ターン使い続けるほうが困る。
    """
    assert "OK   綴り違い" in result, result


def test_it_says_why_it_skipped(result):
    """★★ 黙って見送らない（playbook #46）★★"""
    assert "OK   HPの理由" in result, result
    assert "OK   敵の数の理由" in result, result


# --- 設定 --------------------------------------------------------------

def _battle_items() -> list[dict]:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return ((cfg.get("auto_input") or {}).get("battle_items") or {}).get(
        "items") or []


@pytest.mark.parametrize("item_id,name", [
    (0x1D, "ちからのたて"),
    (0x0E, "ひかりのつるぎ"),
    (0x10, "いなずまのけん"),
])
def test_the_three_items_are_configured(item_id, name):
    """★依頼者が挙げた3つが、実際に設定へ入っていること。

    ⚠ 仕組みだけ作って設定へ入れ忘れると、**何も変わらない**。
    """
    got = [i for i in _battle_items() if i.get("id") == item_id]
    assert got, f"{name}（0x{item_id:02X}）が設定に無い"
    assert got[0].get("when"), f"{name} に条件が無い（いつでも使ってしまう）"


def test_the_staves_only_skip_spell_immune_enemies():
    """★★★ **杖は呪文と同じ効果**（2026-08-07 / 依頼者の実機指摘）。

        > キラーマシーン単体と戦闘。魔道士の杖を使っている？

    ⚠⚠ まどうしのつえ＝ギラ、いかづちのつえ＝バギ。
      ★攻撃呪文の側は「効かない敵には撃たない」を守っていたのに、
        **道具だけ素通り**していました（★「片側だけ」の状態）。

    ⚠ 以前ここは「杖に条件が付いていないこと」を見ていました。
      ★前提が変わったので、**どの条件が付いているか**を見ます。
      ⚠⚠ 条件を増やしすぎると「使えない道具」になるので、
        `spell_may_damage` **だけ**であることも確かめます。
    """
    def _whens(item) -> set:
        """その道具に付いている条件の名前（★`all:` の中も見ます）。

        ⚠⚠ **形で見ないこと**（2026-08-08 に赤くなりました）。
          `when: spell_may_damage` を**直接**書いてある前提でしたが、
          ★通常攻撃との比較を足すために `all:` へ移しました。
          ⚠ 中身（呪文が効かない敵には使わない）は変わっていません。
        """
        got = set()
        if item.get("when"):
            got.add(item["when"])
        for part in (item.get("all") or []):
            if part.get("when"):
                got.add(part["when"])
        return got

    staves = [i for i in _battle_items() if i.get("id") in (0x03, 0x04)]
    assert len(staves) == 2, "杖が消えている"
    for stave in staves:
        whens = _whens(stave)
        assert "spell_may_damage" in whens, (
            f"⚠ 杖が「呪文が効かない敵」を避けなくなりました: {stave!r}")
        # ★通常攻撃との比較は 2026-08-08 に足したもの（⚠ 依頼者の指摘）
        assert whens <= {"spell_may_damage", "beats_physical"}, (
            f"⚠⚠ 杖に知らない条件が増えています: {stave!r}")
        # ⚠ 追加の縛り（回数制限など）は付けない。
        #   ★「呪文が効かない敵だけ避ける」以上のことをさせません。
        assert not stave.get("once_per_battle"), (
            f"⚠⚠ 杖に回数制限が付いています: {stave!r}")
        assert stave.get("ratio") is None and stave.get("count") is None, (
            f"⚠ 杖に余計な条件が付いています: {stave!r}")

def test_the_unverified_effects_are_flagged():
    """★★ **効果は ROM で確かめていない**と書いておく ★★

    ⚠ 書いていないと、次に見た人が「確かめた」と思って別の判断をする。
    """
    text = CONFIG.read_text(encoding="utf-8")
    assert "未検証" in text

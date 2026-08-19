"""攻撃呪文が狙いを合わせる（2026-08-07 / 依頼者の実機指摘）。

    > キラーマシン（呪文きかない）のに攻撃呪文使っている

## ★★★ 原因は「判断」ではなく「操作」だった

`bridge.lua` の対象選択は ⚠ **カーソルを動かさずそのまま A を押していた**:

    -- menu == 0x0A（敵の対象選択）
    -- ⚠ 第一版では**先頭のグループ**を狙います。
    return self:_ba_press("A")

★つまり**ゲームが置いた既定の位置**に当たります。
⚠ ところが判断側は `index = 1`（先頭）に効くかで計算していました。
→ 「1体目に効く」と思って選び、**別の敵に当たる**。

## ★ 直し方（2段階でやりました）

1. ⚠ 暫定: 「効かない敵が1体でも居たら呪文を使わない」
   ★安全だが**かなり損**（ダンジョン後半ほど当てはまる）
2. ★★ 本命: **狙いを合わせる**。行を寄せる仕組みは物理攻撃用に
   既にあったので（`_claim_target_selection`）、そこへ渡し、
   ⚠ 呪文の番だけ「効かない敵」を飛ばすようにした。
   → ★1 の暫定策は**緩めました**。

⚠⚠ **前提が変わったのに規則だけ残すと損をします。**
  ★`aim_is_uncontrolled` にその手順を残してあります。
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
           / "spell_aim_test.lua")
PLAN = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "attack_plan.lua"
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
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 13, result


def test_効く敵が居るなら使う(result):
    """★★★ **狙いを合わせられるようになりました**（2026-08-07）。

    ⚠ 一度は「効かない敵が居たら使わない」という暫定策を入れましたが、
      `bridge.lua` が対象選択で効かない敵を飛ばすようになったので
      ★**緩めました**。⚠ 前提が変わったのに規則だけ残すと損をします。
    """
    assert _ok(result, "★★★ 効く敵が居るなら使う"), result


def test_全部効かないなら撃たない(result):
    """⚠⚠ **寄せる先がありません。** ★ここは撃ってはいけません。"""
    assert _ok(result, "★★★ 全部効かないなら撃たない"), result
    assert _ok(result, "⚠ 1体でも効くなら「全部効かない」ではない"), result
    assert _ok(result, "★★ 耐性が読めない敵を「効かない」扱いしない"), result


# --- ⚠⚠ **封じすぎない**（★これが無いと別の壊れ方）--------------------

def test_全部効く相手には使う(result):
    """⚠⚠ **ここが通らないなら、呪文を封じすぎです。**"""
    assert _ok(result, "★★ 全部効く相手には使う"), result


def test_全体呪文は使う(result):
    """★ベギラマは全員に当たるので、狙いがずれようがありません。"""
    assert _ok(result, "★★ 全体呪文は効かない敵が居ても使う"), result


def test_耐性が読めない敵で封じない(result):
    """★★ **読めないことを理由に封じると、未知の敵に何もできません。**"""
    assert _ok(result, "★★ 耐性が読めない敵には、これまでどおり使う"), result


def test_倒れた敵は数えない(result):
    """⚠ 倒した「効かない敵」で、以降ずっと呪文を封じないこと。"""
    assert _ok(result, "★★ 倒れている敵は数えない"), result


def test_グループ呪文も使う(result):
    assert _ok(result, "★グループ呪文も効く敵が居れば使う"), result


def test_攻撃呪文が狙いを合わせる仕組みに任せている():
    """★★★ **これが今回の本題**（2026-08-07）。

    ⚠⚠ 以前はここで**カーソルを動かさず A を押していました**。
      そのため「ゲームが置いた既定の位置」に当たり、判断側が
      `index = 1`（先頭）で計算した結果とずれていました。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    idx = source.index("menu == 0x0A（敵の対象選択）")
    body = source[idx:idx + 1200]
    assert "self.ba_avoid_immune = true" in body, (
        "⚠ 呪文を撃つ番だと伝えていません")
    assert "return nil" in body, (
        "⚠⚠ ここで A を押しています（★狙いを合わせる仕組みに渡らない）")
    assert '_ba_press("A")' not in body, (
        "⚠⚠ まだカーソルを動かさず決定しています")


def test_効かない敵を飛ばす():
    """★対象選択で、呪文が効かない敵を候補から外していること。"""
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "local function spell_useless" in source
    idx = source.index("local function still_needs")
    assert "spell_useless(i)" in source[idx:idx + 400], (
        "⚠ 狙い先の判定で使っていません")


def test_印を必ず消している():
    """⚠⚠ **印が残ると、次の人の物理攻撃まで巻き添え**になります。

    ★殴れる敵を素通りします。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    assert source.count("self.ba_avoid_immune = false") >= 2, (
        "⚠ 消す場所が足りません（★戦闘の初期化と、人と人の境目）")


# --- ★ 前提が変わったら気づけるように ---------------------------------

def test_暫定策を緩めた経緯を残している():
    """★★ **なぜ緩めたかが分からないと、また厳しくしてしまいます。**

    ⚠ 対象選択の作りを戻すなら、`aim_is_uncontrolled` を true に
      戻す必要があります。★その手順をコードに残しています。
    """
    source = PLAN.read_bytes().decode("utf-8")
    assert "aim_is_uncontrolled" in source
    assert "対象選択の作りを戻したら、ここを true に戻すこと" in source


# --- ★★★ 当たり先を必ず記録する（2026-08-07 / 1-1 の本題）-------------
#
# ⚠ ここは**別のハーネス**（`spell_target_wiring_test.lua`）を見ます。
#   ★最初 `result`（= spell_aim_test）を見ていて落ちました。

WIRING = (PROJECT_ROOT / "research" / "probes" / "active"
          / "spell_target_wiring_test.lua")


@pytest.fixture(scope="module")
def wiring():
    if not (RUNNER.exists() and WIRING.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(WIRING)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def test_つなぎ方のハーネスが全部通る(wiring):
    assert "NG 0 件" in wiring, wiring


def test_当たり先を必ず残す(wiring):
    """★★★ **狙いを合わせた「つもり」では足りません。**

    ⚠⚠ 実機ログで「まどうしのつえに狙い先が無い」のを見て、
      ★「合わせていない」と**誤って結論**しました。
      実際は**ログが出る条件**が違っただけ
      （★ダメージを見積もれたときだけ出ていた）。
      道具はダメージを推計していないので、⚠ **出ないほうが普通**でした。

    ★これは「無いこと」を根拠にした誤りです。
    """
    assert _ok(wiring, "★★★ 寄せが確定したら必ず残す"), wiring
    assert _ok(wiring, "★★ 予約の判定より"), wiring


def test_寄せない理由も残す(wiring):
    """⚠⚠ **出ない理由が分からないと追えません。**

    ★`[狙い]` が出ないとき、「寄せに行かなかった」のか
      「寄せたが記録が漏れた」のかを区別できませんでした。
    """
    assert _ok(wiring, "★★ 寄せない理由も残す"), wiring


def test_戦闘ごとに印を戻す(wiring):
    """⚠ 戻さないと**2戦目以降ずっと黙ります**。"""
    assert _ok(wiring, "⚠ 戦闘ごとに印を戻す"), wiring

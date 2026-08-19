"""現行 戦闘AI の判断を固定する（2026-08-04 / 戦闘AI再設計 Phase 0）。

指示書: `input/RetroUX 戦闘AI再設計・段階的リファクタリング指示書.docx`

★★ **これはリファクタの安全網です。** ★★

  Phase 1・2 で処理を三層（戦況分析 / 作戦指示 / 個人貢献 / 最終調整）へ
  移したあと、**ここが同じ答えを返せば**「挙動を変えていない」と言えます。

⚠⚠ 答えが変わったら、必ずどちらかを明示すること（指示書 §19）:

    ・意図した改善     -> 期待値を直し、**理由をコメントに書く**
    ・リグレッション   -> コードを直す

  ★理由不明の差異を放置しない。

## ⚠ このハーネスが実際に見つけた欠陥（2026-08-04 / 記録）

作った初回に**2件**捕まえました。どちらも実機では気づけていませんでした。

1. **二重回復の予約が成立していなかった**
   `heal.spells` に `expected_heal` が無く、予約量が nil になるため
   `_reserve_heal` が**黙って何もしていなかった**。
   ★サマルが回復してもムーンが同じ人を回復する状態。

2. **「予約で使わない」という理由が消えていた**
   呪文を2つ書くと、後の呪文（高いほう）が必ず
   「MPが足りない」で上書きする。★Healmore を足した瞬間に発現。
   ⚠ 利用者は「MPが無い」と思って宿屋へ行き、戻っても同じことが起きる。

★**実機を1度も起動せずに**見つかりました。これが偽データの価値です。
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
           / "battle_ai_baseline_test.lua")
FAKE_RAM = PROJECT_ROOT / "research" / "probes" / "reusable" / "fake_ram.lua"


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


def _ok(result: str, label: str, value: str | None = None) -> bool:
    """`OK   <説明>  -> <値>` の行を探す。

    ⚠⚠ ハーネスは `%-46s` で桁を揃えますが、**Lua の `%s` はバイト数で
      数える**ため、日本語だと空白の数が変わります。
      ★完全一致で書くと、文言を1文字直しただけで落ちます。
    """
    for line in result.splitlines():
        if not line.startswith("OK"):
            continue
        if label not in line:
            continue
        if value is None or line.rstrip().endswith(value):
            return True
    return False


def test_ハーネスが全部通る(result):
    assert "NG 0 件" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 12, result


# --- ★★★ Phase 2 の完了条件: 新旧で答えが一致する ------------------------

def test_決めた答えから変わっていない(result):
    """★★★ **golden behavior テスト**（2026-08-08 / Phase 10）。

    ## ⚠⚠ 「新旧の一致」から「答えそのものの固定」へ変えました

      ★相談回答 §12 の**条件6**:

        > baseline を「legacy 比較テスト」から golden behavior テストへ
        > 移行済みであること。legacy を削除すると比較自体ができなくなる。

      ⚠ 以前ここは、同じ場面を「新しいモジュール」と
        「`bridge.lua` に残した控え」の両方に通して比べていました。
      ⚠⚠ ところがその控えは **production では絶対に動きません**でした
        （`load_module` は失敗すると `error()` を投げ、★nil を返さない）。
        つまり比べていたのは「動くコード」と「**動かないコード**」です。

      → ★36通りの**最終行動そのもの**をハーネスに固定しました。
        ⚠ 控えを消したあとも、答えが変われば赤くなります。
    """
    assert _ok(result, "★★★ 決めた答えから変わっていない（golden behavior）"), result
    assert _ok(result, "★十分な数を確かめている"), result


def test_確かめた場面が十分にある(result):
    """⚠ 少ない場面で「変わっていない」と言わない。"""
    m = re.search(r"確かめた場面: (\d+) 通り", result)
    assert m and int(m.group(1)) >= 30, result


def test_決めた答えに余りが無い(result):
    """⚠⚠ **場面を消したのに表だけ残る**、を防ぎます。

    ★表が余っていると「36通り固定してある」という説明が嘘になります。
    """
    assert _ok(result, "⚠ 決めた答えの数と、確かめた数が合っている"), result


# --- ★ 指示書 §19 の代表シナリオ -----------------------------------------

def test_全員元気なら誰も回復しない(result):
    assert _ok(result, "サマルは殴る"), result
    assert _ok(result, "ムーンは殴る"), result


def test_ローレシア42パーセントで回復が入る(result):
    """★§19「ローレシアHP42%」。

    ★★★ **2026-08-08 に期待値を ホイミ -> Healmore へ直しました** ★★★

      依頼者の指摘:
        > 戦闘時の回復が弱い。９割（満タン設定）を狙うようにしたい。

      ⚠ ローレシアは 59/142。★目標 90% は 128 なので**不足 69**。
        ホイミ（32）では足りないので Healmore（50）を選びます。

    ⚠⚠ **同じ期待値が Lua 側（`battle_ai_baseline_test.lua`）にもあります。**
      ★2026-08-07 に「誤った仕様を Lua と Python の両方が守っていた」件を
        踏んだばかりです（`docs/design/handoff-20260807.md` §5 の10番）。
        ⚠ 片方だけ直すと**赤くなって初めて気づく**ので、必ず両方直すこと。
    """
    assert _ok(result, "★サマルが回復する",
               "samaltria -> lorasia に Healmore"), result


def test_ムーンブルクも回復に回れる(result):
    """★★ 2026-08-04 の修正（`heal.spells` へ Healmore を追加）。

    ⚠ 直す前は「設定した回復呪文を覚えていない」で必ず殴っていました。
    """
    assert _ok(result, "ムーンも回復に回る", "moonbrooke -> lorasia に Healmore"), result


def test_二重回復を避ける(result):
    """★★★ **このハーネスが欠陥を見つけた項目**（上の説明を参照）。"""
    assert _ok(result, "★サマルが回復したのでムーンは殴る"), result


def test_MP予約で唱えない(result):
    assert _ok(result, "MPが足りないので殴る"), result


def test_予約の理由がMP不足と区別できる(result):
    """★★★ **このハーネスが欠陥を見つけた項目**。

    ⚠⚠ 「MPが足りない」と混ぜると、利用者は宿屋へ行き、
      戻ってきても同じことが起きます（直しようがない報告）。
    """
    assert _ok(result, "★理由が「予約」と分かる（MP不足と混ぜない）"), result


def test_ローレシアは静かに殴る(result):
    """⚠ 「呪文を覚えない」を毎ターン報告しない（直しようがないため）。"""
    assert _ok(result, "★ローレシアは静かに殴る"), result


def test_いのちをだいじにで判断順が変わる(result):
    """★同じ場面で、作戦によって答えが変わることを固定する。"""
    assert _ok(result, "最も減っているサマルを回復", "moonbrooke -> samaltria に Healmore"), result
    assert _ok(result, "いのちをだいじに: 守る相手が先", "moonbrooke -> lorasia に Healmore"), result


def test_自己回復はちからのたてを優先する(result):
    """★§9.1。⚠ 道具が無ければ呪文へ落ちること。"""
    # ★2026-08-08: 同上（⚠ 40/113 は目標 102 に対し**不足 62**）
    assert _ok(result, "道具が無ければ呪文で自己回復",
               "samaltria -> samaltria に Healmore"), result
    assert _ok(result, "★★ ちからのたてへ譲る（MPを使わない）"), result


# --- ⚠ 偽データの作り方そのもの ------------------------------------------

def test_偽RAMは実機もセーブも要らない():
    """★★ **ここが Phase 0 の肝**（指示書 §18.7）。

    ⚠ RAM ダンプは「そのときのセーブデータそのもの」で配布できず、
      しかも「ローレシアHP42%」のような場面を**作れません**
      （撮れた場面しか無い）。
    """
    source = FAKE_RAM.read_bytes().decode("utf-8")
    # ★注意書き（--）は数えない。**なぜ使わないかを書くのは良いこと**で、
    #   ⚠ 文中に `ramdump` と書いただけで落ちるのは検査の誤りです。
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))
    for banned in ("ramdump", "io.open", "io.lines", ".fc0"):
        assert banned not in code, f"⚠ {banned} を読んでいます"
    # ★逆に、なぜ使わないかは書いてあること
    assert "ramdump" in source, "★理由が書かれていない"


def test_呪文の枠番号を手で書いていない():
    """⚠⚠ 枠番号は ROM 由来で memory_map が唯一の出典です。

    ★テストへ数字を写すと、並びが変わったときに
      **黙って別の呪文を覚えたことになります**。
    """
    source = FAKE_RAM.read_bytes().decode("utf-8")
    assert "slot_table" in source, "★memory_map から引いていない"
    harness = HARNESS.read_bytes().decode("utf-8")
    assert "FakeRam.slots_for(mm," in harness


def test_状態ビットを既定で立てている():
    """⚠⚠ **実際に踏んだ穴**（2026-08-04）。

    `status` を 0 のままにすると `in_party`(0x04) が立たず、
    ★`active_party()` が空になって**AI が何も判断しません**。
    「居ない」とだけ出て、原因が分かりませんでした。
    """
    source = FAKE_RAM.read_bytes().decode("utf-8")
    assert "in_party" in source and "status_bits" in source
    assert "active_party" in source, "★理由が書かれていない"

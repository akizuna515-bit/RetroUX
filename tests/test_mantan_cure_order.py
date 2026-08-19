"""まんたんが「誰のMPから使うか」（2026-08-01 / 課題 #57）。

★★ **本物の Lua を走らせる。** ★★
  ⚠ ソースを文字列で検索する形にしない（指示書 §10.2-B）。
    並べ替えの規則は、実際に呼んで並びを見ないと確かめられない。

## 依頼者の報告（2026-08-01）

    「まんたんでムーンブルグを使わなさ過ぎる。満タンの設定が必要か。
      MPの使い方をどの配分でやるかを」

## 実測（`work/retroux.log` 13:33:57〜58）

| 使ったもの | サマルトリアMP | ムーンブルクMP |
| --- | ---: | ---: |
| ホイミ×4（samaltria） | 35 -> 23 | **83（手つかず）** |

書いてある順だと、先頭のホイミ（サマルトリア）が使える限り
Healmore（ムーンブルク）まで届かない。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "cure_order_test.lua")


@pytest.fixture(scope="module")
def result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def test_the_harness_runs_and_passes(result):
    assert "不合格 0" in result, result


def test_it_uses_the_caster_with_more_mp(result):
    """★★ これが依頼者の報告そのもの ★★

    サマルトリア 35 / ムーンブルク 83 のとき、**ムーンブルク**を使う。
    """
    assert "OK   MP 35 対 83 -> ムーンブルクの Healmore" in result, result


def test_the_old_order_is_still_available(result):
    """★設定で従来どおりにも戻せる（`cure_order: list_order`）。"""
    assert "OK   list_order" in result, result


def test_items_stay_last(result):
    """⚠ やくそうは買い足しにゴールドが要る。MPで済むならそちらを先に。"""
    assert "OK   道具が先頭でも呪文を先に使う" in result, result


def test_it_falls_back_to_an_item_when_no_one_has_mp(result):
    """★★ 黙って何もしない、をやらない ★★"""
    assert "OK   MPが尽きたら やくそう" in result, result


def test_an_unreadable_mp_is_not_treated_as_the_best(result):
    """⚠ **0 と 不明 を混ぜない。** 読めない人を先に選ばない。"""
    assert "OK   MP不明より、分かっている人" in result, result


def test_it_reports_enough_checks(result):
    """★項目が減っていないこと（ハーネスが痩せたら気づく）。"""
    import re

    m = re.search(r"最終合計 (\d+) 項目", result)
    assert m and int(m.group(1)) >= 12, result


# --- 最低残存MP（2026-08-01 / 依頼者「まんたんの時、最低MP保持が効かない」）

def test_the_reserve_floor_applies_to_mantan_too(result):
    """★★ 戦術プロフィールの「最低残存MP」を まんたん でも効かせる ★★

    ⚠⚠ それまでは `mp_reserve`（ルーラ・リレミトのぶん）しか見ておらず、
      **戦闘では効く設定が、まんたんでは無視されていた**。
    ★注釈には「まんたんと同じ数字を使う」と書いてあったが、実際は違った。
    """
    assert "OK   最低残存MP 15 のほうが大きい" in result, result


def test_the_two_reserves_are_not_added_together(result):
    """★★ **足さず、大きいほうを採る**（仕様書 5.5）★★

    ⚠ 足すと「ルーラのぶん + 最低残存MP」になり、
      利用者が指定した数より多く残してしまう（設定と違う挙動）。
    """
    assert "OK   ⚠ 足していない" in result, result
    assert "OK   最低残存MP 5 は小さい" in result, result


def test_the_rule_lives_in_one_place():
    """★同じ規則を2か所に写さない。

    ⚠ 写していたから片方（まんたん）だけ古いままになった。
      `DQ2:reserved_mp` を、戦闘とまんたんの**両方**が呼ぶこと。
    """
    dq2 = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
           / "dq2.lua").read_text(encoding="utf-8")
    assert "function DQ2:reserved_mp" in dq2

    for rel in ("retroux/emulator/fceux/bridge.lua",
                "retroux/plugins/dq2/mantan.lua"):
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        code = "\n".join(ln.split("--")[0] for ln in text.splitlines())
        assert "reserved_mp(" in code, f"{rel} が共通の計算を使っていない"


# --- 設定 --------------------------------------------------------------

def test_the_setting_is_documented_in_the_config():
    """★設定できることを `config.yaml` に書く（探させない）。"""
    text = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
            / "config.yaml").read_text(encoding="utf-8")
    assert "cure_order:" in text
    assert "list_order" in text, "従来へ戻す方法が書かれていない"


def test_moonbrooke_can_actually_be_used():
    """⚠ Healmore(0x0B) が回復手段に入っていること。

    ★これが無いと、並べ替えても**ムーンブルクは選べない**
      （彼女はホイミを覚えないので / 実機ログで確認済み）。
    """
    text = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
            / "config.yaml").read_text(encoding="utf-8")
    assert "id: 0x0B" in text

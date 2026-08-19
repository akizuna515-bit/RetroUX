"""「いのちをだいじに」（2026-08-04 / 指示書 §8〜§11・§18.4）。

★★ **本物の Lua を走らせる。** ★★
（`test_attack_plan.py` / `test_mp_reserve.py` と同じ流儀）

## ★この作戦の要点

    ローレシアを主攻撃役として維持し、
    サマルトリアとムーンブルクが回復を担当する。

判断順（§10）:

    1. 自分のHP   <= 緊急自己回復(25%)  -> 自分
    2. 守る相手   <= 保護しきい値(50%)  -> その人
    3. 自分のHP   <= 自分の回復開始(50%) -> 自分
    4. どれでもなければ従来どおり「最も減っている人」

⚠⚠ **1 が 2 より先なのが肝**です（§10 末尾）:
  回復役自身が瀕死のままローレシアだけを回復して**共倒れ**になるのを防ぎます。
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
           / "life_first_test.lua")
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


def test_ハーネスが全部通る(result):
    assert "NG 0 件" in result, result


def test_検査の数が足りている(result):
    m = re.search(r"OK (\d+) 件", result)
    assert m and int(m.group(1)) >= 20, result


# --- ★★ 指示書 §18.4 の受け入れ項目 --------------------------------------

def test_ローレシアが50パーセント以下なら回復する(result):
    """★§18.4「ローレシアが50%以下ならサマルまたはムーンが回復を選ぶ」。"""
    assert "OK   ★★ 守る相手（ローレシア）を回復する -> lorasia" in result


def test_自分が25パーセント以下ならローレシアより自分が先(result):
    """★★★ **§10 の一番の要求。**

    ⚠ ローレシアのほうが減っていても（10% vs 20%）、自分を先に回復します。
      ★共倒れを防ぐための順番です。
    """
    assert ("OK   ★★★ ローレシアのほうが減っていても、自分を先に回復"
            " -> samaltria") in result


def test_ローレシアが安全なら自己回復する(result):
    """★§18.4「自分が50%以下でローレシアが安全なら自己回復する」。"""
    assert "OK   ★自己回復 -> samaltria" in result
    assert "守る相手は無事" in result


def test_二重回復防止が働く(result):
    """★★ §11 の例そのまま（ローレシア 40/100 に見込み45 -> 予約後85）。"""
    assert "OK   ★予約後HP -> 85" in result
    assert "OK   ★★ ムーンは回復しない（攻撃へ回る） -> nil" in result


def test_1回で足りなければ2人目も回復する(result):
    """★§11 の例外「1回の回復見込みでは安全圏へ届かない」。"""
    assert ("OK   ★★ まだ届かないので、ムーンも回復する -> lorasia") in result


def test_回復不要なら従来の探し方へ落ちる(result):
    """⚠ nil を返して、既存の「最も減っている人」へ渡すこと。"""
    assert "OK   ⚠ 回復不要なら nil -> nil" in result


# --- ⚠⚠ 既定では何も変わらない（§19 受入条件13）--------------------------

def test_守る相手が未設定なら何もしない(result):
    """★★★ **これが「既存を壊さない」ことの線です。**

    ⚠ `protect_target` は既定 `none`。触らなければ従来どおり
      「最も減っている人」を回復します。
    """
    assert "OK   ★protect_target=none なら nil -> nil" in result
    assert "OK   ★プロフィールが無くても nil -> nil" in result


def test_守る相手が戦闘にいなければフォールバックする(result):
    """⚠ §15「保護対象が戦闘メンバーにいない場合は安全に通常戦術へ」。

    ★ムーンブルクが仲間になる前の場面です。
    """
    assert "OK   ★居ない相手を守ろうとして落ちない -> nil" in result


def test_死んでいる人を回復しようとしない(result):
    assert "OK   ⚠ 死んでいる守る相手は回復しない -> nil" in result


def test_仲間を回復するOFFを尊重する(result):
    """⚠ 新しい設定が既存の設定を踏み越えないこと。"""
    assert "OK   ⚠ ally_enabled=false を尊重する -> nil" in result


# --- ⚠ 予約の後始末（§7 予約情報）----------------------------------------

def test_予約はターンをまたがない(result):
    """⚠⚠ 持ち越すと、前のターンに回復したつもりのHPで次を判断します。

    ★指示書 §7「前ターン・前作戦の予約情報を持ち越さない」。
    """
    assert "OK   ★★ 次のターンでは消える -> 40" in result


def test_予約は最大HPを超えて数えない(result):
    """⚠ 超えて数えると「もう十分」と誤判定します。"""
    assert "OK   ⚠ 140 ではなく 100 -> 100" in result


# --- ★ ちからのたて（§9）--------------------------------------------------

def _bridge() -> str:
    return BRIDGE.read_bytes().decode("utf-8")


def test_自己回復ではちからのたてを優先する():
    """★★ §9.1「ちからのたて ＞ 回復呪文 ＞ やくそう」。

    ⚠⚠ 行動の優先順は `heal -> attack -> item -> target` なので、
      **回復呪文のほうが道具より先**に主張します。
      ★そこで「自分を回復する番で、使える道具があるなら**譲る**」
        という作りにしました（譲れば次に item が主張します）。
    """
    source = _bridge()
    assert "自己回復は %s を優先" in source, "⚠ 譲る処理が無い"
    # ★譲るのは**自分のとき**だけ（`worst.index == m.index`）
    assert "worst.index == m.index" in source


def test_他者回復ではちからのたてを選ばない():
    """★★ §9.2・§16「ちからのたてを他者回復候補に含めない」。

    ⚠ ちからのたては**使用者自身しか回復できません**。他者回復で選ぶと
      「回復したのに相手のHPが減ったまま」になります。
    """
    source = _bridge()
    start = source.index("自己回復は「ちからのたて」が最優先")
    end = source.index("唱えられる回復呪文を優先順に探す", start)
    region = source[start:end]
    # ★自分かどうかを確かめてから譲っていること
    assert "worst.index == m.index" in region
    assert "他者回復では候補に入れません" in region


def test_攻撃道具に譲ってしまわない():
    """★★★ **2026-08-04 の実機ログで見つけた穴**（記録）。

    最初は `_find_battle_item` をそのまま呼んでいました。しかしあれは
    **設定順で最初に使える道具**を返します。設定の並びは

        いかづちのつえ / まどうしのつえ / ちからのたて / ひかりのつるぎ

    なので、⚠⚠ **自己回復の番なのに いかづちのつえ（攻撃）に譲る**
    ことになります。回復するはずの番で敵を殴って終わります。

    → `heals_self: true` の印が付いた道具だけを探す
      `_find_self_heal_item` を別に用意しました。
    """
    source = _bridge()
    assert "function Bridge:_find_self_heal_item" in source
    # ★譲る判断は**専用の関数**を使うこと
    start = source.index("自己回復は「ちからのたて」が最優先")
    end = source.index("唱えられる回復呪文を優先順に探す", start)
    region = source[start:end]
    assert "_find_self_heal_item" in region
    assert "_find_battle_item(m.index, m)" not in region, \
        "⚠⚠ 攻撃道具にも譲ってしまいます"


def test_回復道具かどうかを条件から推測しない():
    """⚠⚠ `when: self_hp_below` は「いつ使うか」であって
    「何をする道具か」ではありません。

    ★別の道具に同じ条件を書いた瞬間、それが回復道具として扱われます。
      印（`heals_self`）で明示します。
    """
    import yaml

    source = _bridge()
    start = source.index("function Bridge:_find_self_heal_item")
    end = source.index("function Bridge:_find_battle_item", start)
    region = source[start:end]
    assert "want.heals_self == true" in region
    assert "self_hp_below" not in region, "⚠ 条件から推測しています"

    # ★同梱の設定で、ちからのたてに印が付いていること
    config = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    items = ((config.get("auto_input") or {}).get("battle_items")
             or {}).get("items") or []
    flagged = [i for i in items if i.get("heals_self")]
    assert flagged, "⚠ heals_self の印が付いた道具が1つもありません"
    for item in flagged:
        assert item["id"] == 0x1D, f"⚠ 自己回復道具は ちからのたて だけのはず: {item}"


def test_回復する道具も予約する():
    """★★★ **2026-08-05 の実機ログで見つけた二重回復**（記録）。

        07:27:18 戦闘で ちからのたて を使います（samaltria）  ← 本人が自己回復
        07:27:19 戦闘で回復します: moonbrooke が samaltria に Healmore
        07:27:19 回復を確認: samaltria のHP 22 -> 80

    ⚠⚠ 同じターンに samaltria へ**2回回復**していました。
      道具の使用が `_reserve_heal` を呼んでおらず、ムーンブルクは
      「samaltria はもう回復する予定」を**知りませんでした**。

    ★指示書 §11 の二重回復防止は「回復手段」全部が対象です。
      呪文だけ予約しても、道具で抜けます。
    """
    import yaml

    source = _bridge()
    # ★道具を決めた直後に予約すること
    assert "回復する道具も**予約する**" in source, "⚠ 理由が書かれていない"
    assert "self:_reserve_heal(m, heal_amount)" in source, "⚠ 予約していない"
    # ⚠ 「二重回復を避ける」が OFF の人では予約しないこと
    start = source.index("回復する道具も**予約する**")
    end = source.index("return { A = true }", start)
    region = source[start:end]
    assert "avoid_duplicate_healing" in region

    # ★回復量が設定にあること（無いと予約量が nil で黙って何もしない）
    config = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
         / "config.yaml").read_bytes().decode("utf-8"))
    items = ((config.get("auto_input") or {}).get("battle_items")
             or {}).get("items") or []
    for item in items:
        if item.get("heals_self"):
            assert item.get("expected_heal"), (
                f"⚠⚠ {item.get('name')} に expected_heal が無く、"
                "予約が黙って成立しません")


def test_既定では譲らない():
    """⚠ 道具を持っていない／使えないなら、これまでどおり呪文を唱えること。

    ★`_find_self_heal_item` が nil を返せば譲りません（§15）。
    """
    source = _bridge()
    assert ("local slot, _id, item_name = "
            "self:_find_self_heal_item(m.index, m)") in source
    assert "if slot ~= nil then" in source



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は
#       assert "function Bridge:_find_self_heal_item" in source
#   のように、**関数を作ったか**しか見ていません。
#   ★その関数が本当に回復道具だけを返すかは分かりません。
#     `heals_self` の見方をひとつ変えれば、字面はそのままで
#     **いかづちのつえ（攻撃）を返す**ようになります。
#
# ⚠ これは 2026-08-04 の実機ログで見つかった穴そのものです。
# =====================================================================

_ITEM_HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
                 / "self_heal_item_test.lua")


@pytest.fixture(scope="module")
def item_lua():
    if not (RUNNER.exists() and _ITEM_HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(_ITEM_HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _has(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで道具選びが全部通る(item_lua):
    assert "すべて合格" in item_lua, item_lua


def test_道具選びの検査の数が足りている(item_lua):
    count = sum(1 for line in item_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 17, f"OK が {count} 件しかありません\n{item_lua}"


def test_攻撃道具が先にあっても回復道具を返す(item_lua):
    """⚠⚠ **2026-08-04 の穴そのもの。**

    設定の並びは いかづちのつえ / まどうしのつえ / ちからのたて …
    ★素直に「最初に使える道具」を返すと、自己回復の番に敵を殴ります。
    """
    assert _has(item_lua, "★攻撃道具が先にあっても、回復道具を返す"), item_lua
    assert _has(item_lua, "⚠ 印の無い道具しか無ければ返さない"), item_lua


def test_印はtrueのときだけ(item_lua):
    """⚠ `~= false` で見ると、印の無い道具まで回復扱いになります。"""
    assert _has(item_lua, '★文字列の "true" は印と数えない'), item_lua
    assert _has(item_lua, "★数値の 1 も印ではない"), item_lua


def test_装備中でも見つける(item_lua):
    """★装備中は bit6（0x40）が立ちます。⚠ 素の比較だと見つかりません。"""
    assert _has(item_lua, "★装備中でも見つける"), item_lua


def test_空きスロットを道具と間違えない(item_lua):
    """⚠⚠ ここは**別の理由で通ってしまう**ので、門を通る値で見ています。

    ★最初 0x1D で書いたら、`got ~= 0` を外しても緑のままでした
      （`0 % 0x40` と `0x1D % 0x40` は元々一致しないため）。
      → id を 0x40 で割った余りが 0 の道具で確かめています。
    """
    assert _has(item_lua, "★空きスロット（0）を道具と間違えない（★門を通る値で）"),         item_lua

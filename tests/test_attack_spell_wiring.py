"""攻撃呪文が bridge へ正しく繋がっているか（2026-08-03 / Phase 1）。

★★ **既定は無効。設定しなければ、これまでとまったく同じ挙動。** ★★

⚠⚠ ここで守りたいこと:

  1. `attack_spells.enabled` が既定で false
  2. **人ごと**に ON/OFF できる（★2026-08-03 に画面から選べるようにした）
  3. 回復（`_bh_*`）と攻撃（`_ba_*`）の状態が**混ざらない**
  4. 攻撃の判断が3つの部品へ委ねられている（★bridge に式を書かない）

## ⚠⚠ 2026-08-03 に方針を変えた点（記録）

以前は「`priority` の既定に `attack` を入れない」ことで止めていました。
★画面から選べるようになると、これは**二段構え**になります:

    作戦設定画面で ON → でも config.yaml の priority も直さないと動かない

「ONにしたのに効かない」は必ず起きます。→ **入り口を1つに絞り**、
priority には常に `attack` を入れ、止めるのは
`actions.attack_spell` の既定値（False）だけにしました。
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
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
GENERATED = PROJECT_ROOT / "work" / "generated" / "config.lua"


def _bridge() -> str:
    return BRIDGE.read_bytes().decode("utf-8")


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))


# --- ★★ 設定しなければ動かない ------------------------------------------
#
# ⚠⚠ **同梱の config.yaml の値は見ません**（2026-08-03 の反省）。
#   依頼者が動作確認で `enabled: true` にしたとたん落ちました。
#   ★利用者が設定を変えるのは当たり前で、テストが縛るのが間違いです。
#   ここでは「**設定が無いときに何もしない**」ことを**コード側**で見ます。

def test_設定が無ければ攻撃呪文を使わない():
    """★★★ `attack_spells` が無い／空でも、勝手に唱えないこと。

    ⚠ `cfg.enabled == true` と**明示的に比べている**ことを見ます。
      `~= false` のような書き方だと、**設定が無いときに動いてしまいます**。
    """
    source = _bridge()
    assert "function Bridge:_attack_spell_enabled" in source
    start = source.index("function Bridge:_attack_spell_enabled")
    body = source[start:start + 300]
    assert "cfg.enabled == true" in body, "⚠ 既定で有効になる書き方"
    assert "~= false" not in body, "⚠ 設定が無いときに動いてしまいます"


def test_既定の優先順にattackが入っている():
    """★★ **2026-08-03 に方針を変えました**（依頼者の指定）。

    以前は「既定に `attack` を入れない」でした。しかしガンガン行こうぜが
    作戦設定画面から選べるようになったため、

        画面で ON にする → でも priority にも書かないと動かない

    という二段構えになります。⚠ これは必ず「ONにしたのに効かない」を生みます。

    ★入り口は**画面のチェック1つ**に絞りました。
      priority は「順番の宣言」でしかなく、使うかどうかは決めません。
      ⚠ だから **既定 OFF は `attack_spell` の既定値が守ります**
        （下の `test_攻撃呪文の既定はOFF`）。
    """
    source = _bridge()
    assert ('local DEFAULT_BATTLE_PRIORITY = '
            '{ "heal", "attack", "item", "target" }') in source


def test_回復が攻撃より先():
    """★依頼者の指定。HP が減っていれば、ガンガンでも先に回復します。"""
    source = _bridge()
    m = re.search(r'local DEFAULT_BATTLE_PRIORITY = \{([^}]*)\}', source)
    assert m, "★既定の順が読めない"
    order = re.findall(r'"(\w+)"', m.group(1))
    assert order.index("heal") < order.index("attack"), "⚠ 回復が後回し"
    assert order[-1] == "target", "⚠ target は必ず最後"


# --- ★★ 画面から人ごとに切り分ける（2026-08-03 / 依頼者の要望）------------
#
#   > 今の物理＋道具＋回復とガンガン行こうぜは切り分けられるようにしたい

def test_攻撃呪文の既定はOFF():
    """★★★ **触らなければ、これまでどおり**「たたかう＋杖＋回復呪文」。

    ⚠ 2026-08-11: ラベルから「（ガンガン行こうぜ）」を外したが、機能（項目）は
      残す（依頼者）。★既定 OFF は `attack_spell` の既定値（False）が守る。
    """
    from retroux.core.tactics import models
    field = models.FIELD_BY_PATH[("actions", "attack_spell")]
    assert field.default is False, "⚠ 既定で攻撃呪文を使ってしまいます"
    assert field.implemented, "★画面で選べる（グレーアウトしない）こと"
    # ★ラベルから「ガンガン行こうぜ」を外した（機能名だけ残す）
    assert field.label == "攻撃呪文を使う"
    assert "ガンガン" not in field.label


def test_人ごとにガンガンを切り替えられる():
    """★サマルだけ ON（ムーンは MP 温存）ができること。"""
    source = _bridge()
    assert 'self:_tactic_flag(m.name, "actions", "attack_spell", base)'\
        in source, "⚠ 作戦プロフィールを見ていません"
    # ★誰が OFF なのかログに出ること
    assert "は「ガンガン行こうぜ」が OFF" in source


def test_プロフィールが無ければ従来どおり():
    """⚠ 画面を使っていない環境で挙動が変わらないこと。

    ★`_tactic_flag` の第4引数（fallback）が config.yaml の値であること。
    """
    source = _bridge()
    start = source.index("function Bridge:_attack_spell_enabled")
    body = source[start:source.index("\nend", start)]
    assert "local base = (cfg.enabled == true)" in body
    assert "return base" in body, "⚠ 誰の番か分からないときの戻りが無い"


def test_攻撃呪文はshippedで通し_フェーズ3自体は実装扱いにしない():
    """⚠⚠ `IMPLEMENTED_PHASES` に 3 を足して済ませていないこと。

    ★攻撃呪文だけは `shipped=True`（個別に実装済み）で通します。
    ⚠ 2026-08-11: ラベルから「ガンガン行こうぜ」を外したが、項目は残す。
    """
    from retroux.core.tactics import models
    assert 3 not in models.IMPLEMENTED_PHASES
    attack_spell = models.FIELD_BY_PATH[("actions", "attack_spell")]
    assert attack_spell.phase == 3
    assert attack_spell.shipped is True
    assert attack_spell.implemented, "★攻撃呪文は shipped で実装済みのはず"
    # ★フェーズ3の他の項目は消えている（棚卸しの方針どおり）
    assert ("actions", "group_spell_min_enemies") not in models.FIELD_BY_PATH
    assert ("targeting", "focus_fire") not in models.FIELD_BY_PATH


def test_誰もONでなければ戦闘中に何もしない():
    """★毎フレームの無駄も、思わぬ発動も避ける。"""
    source = _bridge()
    assert "function Bridge:_attack_spell_possible" in source
    assert "if not self:_attack_spell_possible() then return nil end" in source


def test_同梱の設定が使える値になっている():
    """★書いてある値が壊れていないこと（★何であってもよい）。"""
    auto = _config().get("auto_input") or {}
    priority = auto.get("priority") or []
    assert set(priority) <= {"heal", "attack", "item", "target"}
    assert priority[-1] == "target", "⚠ target は必ず最後"
    section = auto.get("attack_spells") or {}
    assert isinstance(section.get("enabled"), bool)


def test_使える行動名にattackが増えている():
    """★`priority` に書けば使えること。"""
    source = _bridge()
    assert "attack = function(self) return self:_claim_battle_attack() end,"\
        in source
    # ★案内文も直っていること（⚠ 古いままだと使えないと思われる）
    assert "使えるのは heal / attack / item / target" in source


def test_設定がLuaまで届く():
    """★yaml に書いた値が、そのまま Lua へ渡ること。

    ⚠ true / false のどちらでもよい（★利用者が決めます）。
    """
    if not GENERATED.exists():
        pytest.skip("★生成物がありません")
    text = GENERATED.read_bytes().decode("utf-8")
    assert "attack_spells" in text
    assert re.search(r"attack_spells\s*=\s*\{[^}]*enabled\s*=\s*(true|false)",
                     text), "⚠ enabled が届いていない"


# --- ⚠⚠ 回復と混ざらない -------------------------------------------------

def test_攻撃と回復で状態変数を分けている():
    """⚠⚠ 同じ変数を使い回すと、カーソルの位置を取り違えます。"""
    source = _bridge()
    for name in ("ba_left", "ba_button", "ba_tried", "ba_settle",
                 "ba_plan", "ba_presses"):
        assert f"self.{name}" in source, f"⚠ {name} が無い"
    # ★回復側はそのまま残っていること
    for name in ("bh_left", "bh_plan", "bh_tried"):
        assert f"self.{name}" in source


def test_攻撃の状態も戦闘開始で戻る():
    """⚠ 前の戦闘の計画が残ると、別の敵に撃ちます。"""
    source = _bridge()
    assert "self:_reset_battle_attack()" in source
    assert source.count("self:_reset_battle_attack()") >= 2, \
        "★初期化と戦闘開始の2か所で呼ぶこと"


def test_味方の対象選択が出たら手を引く():
    """⚠ 攻撃のつもりで味方を狙ったら前提が崩れています。"""
    source = _bridge()
    assert "攻撃のつもりが味方の対象選択" in source


# --- ★ 判断は部品へ委ねる -------------------------------------------------

def test_3つの部品を読み込んでいる():
    source = _bridge()
    for module in ("damage_estimate.lua", "attack_candidates.lua",
                   "attack_plan.lua"):
        assert module in source, f"⚠ {module} を読み込んでいない"


def test_bridgeにダメージの式を書いていない():
    """★★ 式は `damage_estimate.lua` にあります。

    ⚠ bridge に書くと、実機なしで試せなくなります。
    """
    source = _bridge()
    # ★攻撃呪文まわりの行だけ見る
    start = source.index("_reset_battle_attack")
    end = source.index("-- 回復呪文が本当に効いたかを追う")
    if end < start:
        end = len(source)
    region = source[start:end]
    for banned in ("damage_min", "damage_max", "damage_avg", "/ 7"):
        assert banned not in region, f"⚠ {banned} が bridge に書かれています"


def _attack_region() -> str:
    """★攻撃呪文まわりの行だけ取り出す。"""
    source = _bridge()
    start = source.index("function Bridge:_reset_battle_attack")
    end = source.index("-- 回復呪文が本当に効いたかを追う", start)
    return source[start:end]


def test_呪文の位置を決め打ちしていない():
    """⚠⚠ 行番号は**覚えると変わる**うえ**人によって違う**ので、
    設定に数字を書かず `learned_spells` から取ります。

    ★決定の直前にも `find_spell_pos` でもう一度確かめます
      （回復側の DEV-12 と同じ位置づけ）。
    """
    region = _attack_region()
    assert "find_spell_pos" in region, "★決定の直前に確かめること"
    assert "呪文の位置が変わったため決定しません" in region
    # ⚠ 位置を数字で決め打ちしていないこと
    assert not re.search(r"\brow\s*=\s*\d", region), "⚠ 行番号の決め打ち"
    assert not re.search(r"\bcol\s*=\s*\d", region), "⚠ 列番号の決め打ち"


def test_MPの予約を攻撃でも守る():
    """★回復と同じ数（ルーラ・リレミトのぶん＋最低残存MP）を使います。"""
    region = _attack_region()
    assert "reserved_mp" in region
    assert "ignore_reserve_on_boss" in region


def test_マホトーンで封じられたら唱えない():
    region = _attack_region()
    assert "spell_blocked" in region


# --- ★ 安全側 -------------------------------------------------------------

def test_押しても進まないときの上限がある():
    """★playbook「すべてのループに上限」。"""
    source = _bridge()
    assert "攻撃呪文の入力が %d 回で進まないため" in source


# --- ⚠⚠ 実機で落ちた穴（2026-08-03）--------------------------------------

DQ2_LUA = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "dq2.lua"


def test_存在しないゲーム層のメソッドを呼んでいない():
    """★★★ **2026-08-03、実機の起動時に落ちた。**

        bridge.lua:3755: attempt to call method 'menu_id' (a nil value)

    ⚠⚠ `self.game:menu_id()` と書いたが、そんなメソッドは無かった。
      メニューIDは `memory.readbyte(a.menu_id.addr)` で読む。
      ★同じく `cursor_x()` / `cursor_y()` も無い。

    ⚠ Lua は**呼ぶまで気づけない**。構文検査も単体テストも通ってしまう。
    ★だからここで、呼んでいる名前が `dq2.lua` にあるか照合する。
    """
    source = _bridge()
    start = source.index("function Bridge:_reset_battle_attack")
    end = source.index("-- 回復呪文が本当に効いたかを追う", start)
    # ★注意書き（--）の行は除く（★書いてあること自体は違反ではない）
    code = "\n".join(line for line in source[start:end].split("\n")
                     if not line.strip().startswith("--"))
    used = set(re.findall(r"self\.game:(\w+)", code))
    have = set(re.findall(r"function DQ2:(\w+)",
                          DQ2_LUA.read_bytes().decode("utf-8")))
    missing = sorted(used - have)
    assert not missing, f"⚠ dq2.lua に無いメソッドを呼んでいます: {missing}"
    assert used, "★ゲーム層を1つも使っていないのはおかしい"


def test_メニューIDは既存と同じ読み方をする():
    """★回復側（`_claim_battle_heal`）と同じ書き方であること。"""
    region = _attack_region()
    assert "memory.readbyte(a.menu_id.addr)" in region
    assert "a.menu_id.values.battle_menu" in region
    assert "memory.readbyte(a.menu_cursor_x.addr)" in region
    assert "memory.readbyte(a.menu_cursor_y.addr)" in region


def test_1ターンに1回だけ連携を計算する():
    """⚠ 毎フレーム計算すると重く、途中で答えが変わります。"""
    source = _bridge()
    assert "self.ba_turn_no == self.turn_no" in source



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は
#       assert "local base = (cfg.enabled == true)" in body
#   のように、**その行が書いてあるか**しか見ていません。
#   ★言いたいこと（`~= false` だと設定が無いのに動く）は正しいのですが、
#     別の場所で上書きしても、書き方を変えても**緑のまま**です。
#   ⚠ ここは 2026-08-03 に実際に事故ったところです。
# =====================================================================

HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "attack_spell_gate_test.lua")
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"


@pytest.fixture(scope="module")
def lua_result():
    if not (RUNNER.exists() and HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(HARNESS)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで門が全部通る(lua_result):
    assert "すべて合格" in lua_result, lua_result


def test_検査の数が足りている(lua_result):
    count = sum(1 for line in lua_result.splitlines()
                if line.startswith("OK "))
    assert count >= 20, f"OK が {count} 件しかありません\n{lua_result}"


def test_設定が無いときは本当に唱えない(lua_result):
    """⚠⚠ **2026-08-03 の事故の芯。** `~= false` と書くとここが落ちます。"""
    assert _ok(lua_result, "★enabled が未設定なら false"), lua_result
    assert _ok(lua_result, '★文字列の "true" では動かない'), lua_result


def test_画面のチェックだけで動く(lua_result):
    """★依頼者の指定: `config` が false でも画面で ON なら唱える。"""
    assert _ok(lua_result, "★config が false でも、画面で ON の人は唱える"),         lua_result
    assert _ok(lua_result, "★1人でも ON なら true"), lua_result


def test_人ごとに切れる(lua_result):
    """★サマルだけ ON・ムーンは MP 温存、ができること。"""
    assert _ok(lua_result, "★config が true でも、画面で OFF の人は唱えない"),         lua_result


def test_番が分からないとき勝手に唱えない(lua_result):
    """⚠ true を返すと、**知らない人が唱えます**。"""
    assert _ok(lua_result, "★番が分からないときは config の値（false）"),         lua_result


def test_全員OFFなら戦闘中に何もしない(lua_result):
    assert _ok(lua_result, "★全員 OFF なら false"), lua_result


def test_壊れた設定でONと数えない(lua_result):
    """⚠ `~= false` で数えると、壊れた値が ON になります。"""
    assert _ok(lua_result, '★文字列の "true" は ON と数えない'), lua_result

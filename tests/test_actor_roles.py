"""各個人の役割と貢献（2026-08-07 / 戦闘AI再設計 Phase 6）。

指示書 §11:

    > 各キャラクターは、具体的コマンドではなく、自分が作戦へ
    > **どのように貢献できるか**を候補として返す。
    > 各個人は上位3候補程度を返す。⚠ 全候補の総当たり探索は実施しない。

## ★★ §18 Phase 6 の完了条件（★この5つがそのまま検査です）

    サマルが常に回復するのではなく、不要時は攻撃や防御を選べる
    ムーンが回復代行できる
    ローレシアが主火力として優先される
    亀の子作戦で非主力が防御できる
    既存のちからのたて・呪文・薬草選択が維持される

## ⚠⚠ 役割を「名前の表」で決めない

「サマルは回復役」と名前で決め打つと、⚠ **回復呪文を覚える前**や
**MPが尽きた後**も回復役のままになります。
★できること（MP・攻撃力・覚えた呪文）から役割を組み立てます。
  ローレシアが主火力なのは「ローレシアだから」ではなく
  ★**MPを持たず攻撃力が高いから**です。

## ⚠⚠ Phase 6 でも `engine: legacy` なら判断は変わりません
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
           / "actor_roles_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "actor_roles.lua")
BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"
MEMORY_MAP = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml"


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
    assert m and int(m.group(1)) >= 25, result


# --- ★★★ §18 Phase 6 の完了条件（5つ）--------------------------------

@pytest.mark.parametrize("label", [
    "★1 ローレシアの一番手は攻撃",
    "★★★ 2 減っていなければ回復しない",
    "★3 ムーンが回復代行できる",
    "★★★ 4 亀の子で非主力が防御する",
    "★5 道具の候補が残っている",
])
def test_完了条件を満たす(result, label):
    """★★★ **これが Phase 6 の完了条件そのもの**。"""
    assert _ok(result, label), result


def test_不要時は攻撃か防御を選べる(result):
    """⚠⚠ **fallback が無いと棒立ちになります。**

    ★「回復役だが回復が要らない」ときの受け皿が要ります。
    """
    assert _ok(result, "★★ 攻撃か防御を選べる"), result


def test_減っていれば回復が一番手(result):
    """⚠ 「回復しない」だけを見ると、**壊れていても通ります**。

    ★逆（減っていれば回復する）も同じ検査で確かめます。
    """
    assert _ok(result, "★★ 減っていれば回復が一番手"), result


def test_主力は亀の子でも守らない(result):
    """⚠⚠ **主力まで守ったら、誰も敵を削りません。**"""
    assert _ok(result, "★★ 主力は亀の子でも守らない"), result


def test_呪文の候補も残る(result):
    """★既存の選択肢を消さない（指示書 Phase 6 の5つ目）。"""
    assert _ok(result, "★呪文の候補が残っている"), result


# --- ★ 戦術の指示が効く（Phase 5 とつなぐ）----------------------------

def test_戦術の指示が個人に効く(result):
    assert _ok(result, "★★ MP温存なら道具が呪文より上"), result
    assert _ok(result, "★★ 守る相手なら回復の点が上がる"), result


# --- ⚠⚠ 分からないものを 0 にしない -----------------------------------

def test_分からない値を0で埋めない(result):
    """★★ **0 は「価値が無い」という意味**になります。

    ⚠ 見積もれないだけの手が「価値ゼロ」に化けると、二度と選ばれません。
    """
    assert _ok(result, "★★ 火力が分からなければ点も出さない"), result
    assert _ok(result, "★減り具合が分からなければ点を出さない"), result


def test_点が出なくても候補は捨てない(result):
    """⚠⚠ **捨てると、未知の敵に何もできなくなります。**"""
    assert _ok(result, "★★ 点が出なくても候補は捨てない"), result


# --- ⚠ 総当たりをしない（§21）-----------------------------------------

def test_上位3件までしか返さない(result):
    assert _ok(result, "★★ 既定で上位3件まで"), result
    assert _ok(result, "⚠ 1件も返さないのは別の壊れ方"), result


# --- ⚠⚠ 役割を名前で決めていない ---------------------------------------

def test_役割はできることから決まる(result):
    """★★★ **同じ人でも、できることが変われば役割が変わる**。

    ⚠ 名前で決め打つと、回復呪文を覚える前から「回復役」になります。
    """
    assert _ok(result, "★★★ 回復を覚える前は回復役ではない"), result


@pytest.mark.parametrize("name", ["lorasia", "samaltria", "moonbrooke"])
def test_キャラ名で分岐していない(name):
    """⚠ 名前で分岐すると、★キャラが増えた瞬間に破綻します。"""
    code = "\n".join(
        line for line in MODULE.read_bytes().decode("utf-8").splitlines()
        if not line.strip().startswith("--"))
    assert name not in code, f"⚠ {name} で分岐しています"


def test_RAMもメニューも知らない(result):
    assert _ok(result, "⚠ memory%.read を使っていない"), result


# --- ★ 防御が本当に押せること -----------------------------------------

def test_防御コマンドが実在することを確かめてある():
    """★★ **「防御」を実装する前に、ゲームにあるかを確かめる。**

    ⚠⚠ 直前に「フィールドのコマンドに『とじる』がある」と思い込んで
      間違えました（★実際は6項目で存在しない）。同じ轍を踏まないため、
      ★戦闘コマンドの行構成が**実測として記録されている**ことを見ます。

        行0 たたかう / 行1 にげる or じゅもん / 行2 ぼうぎょ / 行3 どうぐ
    """
    text = MEMORY_MAP.read_bytes().decode("utf-8")
    assert "ぼうぎょ" in text, (
        "⚠⚠ 戦闘コマンドに『ぼうぎょ』の実測記録がありません")
    # ★行1が人によって変わることも記録されていること
    assert "にげる/じゅもん" in text or "にげる  / 行2" in text, text[:0]


# --- ⚠⚠ Phase 6 でも既定の挙動を変えていない --------------------------

def test_見立ての失敗を黙って捨てない():
    """★★★ **これが「実機で1行も出ない」を隠していました**（2026-08-07）。

    ⚠⚠ 元のコードはこうでした:

        pcall(function() self:_log_assessment() end)

    ★戻り値を捨てているので、⚠ 中で何が落ちても**何も残りません**。
      実際、Phase 6 の `[役割]` は**1行も出ないのに無音**でした。
      `[戦況]` と `[戦術]` は出ていたので、余計に気づけません。

    ⚠ 「落ちても戦闘を止めない」ことは正しい。★**黙るのが誤り**です。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    idx = source.index("self:_log_assessment() end)")
    around = source[idx - 200:idx + 400]
    assert "local ok, err = pcall" in around, (
        "⚠⚠ pcall の戻り値を捨てています。★落ちても無音になります")
    assert "戦況の見立てで落ちました" in around, (
        "⚠ 落ちた理由をログに出していません")


def test_つなぎ方の検査がある():
    """★★ **部品が正しくても、つなぎ方が誤っていれば動きません。**

    ⚠ `actor_roles.lua` 単体は OK 27件で全部通っていたのに、実機では
      `[役割]` が 0件でした（★引数の渡し間違い）。
      ⚠⚠ 部品の検査だけでは**絶対に見つかりません**。
    """
    wiring = (PROJECT_ROOT / "research" / "probes" / "active"
              / "contributions_wiring_test.lua")
    assert wiring.exists(), "⚠ つなぎ方の検査がありません"


@pytest.fixture(scope="module")
def wiring_result():
    harness = (PROJECT_ROOT / "research" / "probes" / "active"
               / "contributions_wiring_test.lua")
    if not (RUNNER.exists() and harness.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(harness)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def test_本物のbridgeで役割の行が出る(wiring_result):
    """★★★ **実機で 0件だったのは、ここが無かったからです。**"""
    assert "NG 0 件" in wiring_result, wiring_result
    assert _ok(wiring_result, "★★★ 実際に [役割] の行が出る"), wiring_result


def test_人によって点が違う(wiring_result):
    """⚠⚠ **全員が同じ点なら、役割を区別できていません。**

    ★最初 `lorasia:attack(1.0) / samaltria:attack(1.0) /
      moonbrooke:attack(1.0)` と出て「動いた」と思いかけました。
      ⚠ 偽RAMが攻撃力を書いていなかっただけで、**何も確かめていません**。
    """
    assert _ok(wiring_result, "★★★ 人によって点が違う"), wiring_result
    assert _ok(wiring_result, "★★ 攻撃力90の人が先頭"), wiring_result


def test_回復が実際に選ばれる(wiring_result):
    """★★★ **「0件は通っていないだけ」を潰す**（2026-08-07）。

    ⚠ 実機の最初の6件で `[役割]` に回復が **1度も出ません**でした。
      ★全員が元気だっただけかもしれないし、⚠ `_can_heal` が
        **いつも false** なだけかもしれない。区別がつきません。

    → 偽RAMで「主力が瀕死」かつ「回復呪文を覚えている」状態を作り、
      ★**回復が選ばれること**を確かめます。
    """
    assert _ok(wiring_result, "★★★ 主力が瀕死なら回復が選ばれる"), \
        wiring_result


def test_MPを持たない人は回復役にならない(wiring_result):
    """⚠ ローレシアは呪文を覚えません。★MP 0 で落ちること。"""
    assert _ok(wiring_result, "⚠ MPを持たない人は回復に選ばれない"), \
        wiring_result


def test_三層を使う場所を増やしていない():
    """★★★ **Phase 10A で意図的に1か所だけ効かせました**（2026-08-07）。

    ⚠ 以前ここは「0か所であること」を見張っていました。
      ★`engine: layered` のときだけ攻撃呪文を拒否する経路を1本つないだので、
        **0 ではなく 1** が正しい状態です。

    ⚠⚠ **増やさないことが大事です**（★相談回答の最重要指摘）:

        > layered の拒否判定は「行動開始前」だけ行う。

      呪文は「メニュー移動 -> 一覧 -> カーソル -> A -> 敵選択 -> A」と
      **複数フレームにまたがります**。★2か所目を足すと、
      ⚠ 行動の途中で拒否して別の claim が入力する事故が起きます。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    # ⚠ 注釈の中の記述は数えない（★説明で名前を出すのは構わない）
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("--"))
    calls = code.count("self:_may_act(")
    assert calls == 1, (
        f"⚠⚠ 拒否点が {calls} か所あります。★1か所だけにしてください"
        "（行動の途中で拒否すると事故ります）")


def test_既定では挙動を変えていない():
    """⚠⚠ **`engine: legacy` のままなら従来どおり**。

    ★拒否は `_current_directive()` が nil を返すことで止まります。
      ⚠ ここが崩れると、設定を変えていない利用者の挙動が勝手に変わります。
    """
    source = BRIDGE.read_bytes().decode("utf-8")
    assert "if not self:_use_layered() then return nil end" in source, (
        "⚠⚠ legacy で指示を返さない仕掛けがありません")



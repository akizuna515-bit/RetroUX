"""補助行動の評価（2026-08-08 / 戦闘AI再設計 Phase 7・8）。

## ★★★ 指示書 §18 の完了条件が、そのまま検査です

    Phase 7:
      ・短期優勢戦で無意味なルカナンを使わない
      ・均衡長期戦で有効なルカナンを使う
      ・防御バフで崩壊ターンが有意に延びる場合に候補化する

    Phase 8:
      ・100%即死が、通常攻撃より有利なら使われる
      ・通常攻撃で確殺できる敵へ無駄な即死を使わない
      ・100%ラリホーで敵を分断できる
      ・眠った敵を不用意に攻撃しない
      ・慎重と大胆で低成功率行動の採用が変わる

## ★★ いちばん大事な考え方: **ターンは整数**

⚠⚠ 「2.2 -> 2.09 に縮んだ」は**何の得にもなりません**（★どちらも3ターン）。
★これが Phase 7 の完了条件の1つ目と2つ目を、そのまま分けます。

## ⚠⚠ **まだ実際の入力には効かせていません**

★Phase 1〜9 と同じで、いまは**評価と説明**までです。
⚠ 効かせるときは Phase 10A と同じ規律（**拒否点は行動開始前の1か所だけ**）
  を守ってください。`layered_veto_test.lua` が `_may_act(` の数を見張ります。
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
           / "support_plan_test.lua")
MODULE = (PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "support_plan.lua")
CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"
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
    assert m and int(m.group(1)) >= 45, result


# --- ★★★ Phase 7 の完了条件 ------------------------------------------

def test_ターンは整数として比べる(result):
    """★★★ **これが土台**。⚠ 小数で比べると完了条件が2つとも壊れます。"""
    assert _ok(result, "★★★ 2.2 -> 2.09 は「どちらも3ターン」＝得なし"), result
    assert _ok(result, "★★★ 8.0 -> 6.73 は「8 -> 7」＝1ターン得"), result


def test_短期優勢戦で無意味なルカナンを使わない(result):
    assert _ok(result, "★★★ 使わない"), result


def test_均衡長期戦で有効なルカナンを使う(result):
    assert _ok(result, "★★★ 使う"), result


def test_防御バフで崩壊ターンが延びるなら候補化(result):
    assert _ok(result, "★★ 崩れるまでが延びるので候補になる"), result


# --- ★★★ Phase 8 の完了条件 ------------------------------------------

def test_慎重と大胆で採用が変わる(result):
    assert _ok(result, "★★ 慎重（75%以上）では使わない"), result
    assert _ok(result, "★★★ 大胆（25%以上）では使う"), result


def test_確実なものだけという段もある(result):
    """⚠ 4段階のうち `disabled` は「成功率100%以外は使わない」。"""
    assert _ok(result, "⚠ 確実なものだけ、なら使わない"), result
    assert _ok(result, "★成功率100%なら「確実なものだけ」でも使う"), result


def test_確殺できる敵へ無駄な即死を使わない(result):
    assert _ok(result, "★★★ 通常攻撃で確実に倒せるなら使わない"), result


def test_眠った敵を不用意に攻撃しない(result):
    assert _ok(result, "★★★ 眠らせた敵は狙わない"), result


def test_確実でない即死は消えたつもりにしない(result):
    """⚠⚠ **外れた敵を狙わなくなると、生きている敵を放置します。**"""
    assert _ok(result, "★★★ 100%でない即死では印を付けない"), result


def test_止めた敵を除いた戦力を出せる(result):
    assert _ok(result, "★止めた敵を除ける"), result


# --- ⚠⚠ 「分からない」を「効く」と決めない ------------------------------

def test_耐性が読めなければ使わない(result):
    """★初遭遇の敵は図鑑に無いので耐性が読めません。

    ⚠⚠ ここを「効く」と決めると、**初見の敵にラリホーを撃ち続けます**。
    """
    assert _ok(result, "★★★ 耐性が読めなければ使わない"), result


def test_グループは一番効きにくい確率で見る(result):
    """⚠⚠ 平均を採ると「1体だけ効く」を「半分効く」と読み替えてしまいます。"""
    assert _ok(result, "★★ 効かない1体が居れば 0%（⚠ 平均にしない）"), result


def test_効果中は掛け直さない(result):
    assert _ok(result, "★掛け直さない"), result


# --- ★ 見送った理由を必ず返す（⚠ 黙って捨てない）------------------------

def test_見送った理由を残す(result):
    for label in ("★理由を残す（⚠ 黙って捨てない）",
                  "★MP不足だと分かる書き方（⚠ 他の理由と混ぜない）"):
        assert _ok(result, label), result


# --- ⚠ 設定と実装の食い違いを防ぐ ----------------------------------------

def test_設定の耐性名がmemory_mapに実在する():
    """⚠⚠ **推測で書かない。**

    ★`resist_field` に無い名前を書くと「効くか分からない」で
      **黙って見送り続けます**（⚠ 設定したのに何も起きない）。
    """
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    spells = ((config.get("auto_input") or {}).get("support") or {}
              ).get("spells") or {}
    assert spells, "⚠ 補助行動の設定がありません"

    # ★耐性の表は ROM から起こす（RX-0090）。名前の正本は dq2rom.enemies.RESIST_KEYS
    from dq2rom import enemies
    known = set(enemies.RESIST_KEYS)

    for spell_id, effect in spells.items():
        field = effect.get("resist_field")
        if field is None:
            continue                      # ★味方に掛ける呪文（スクルト）
        assert field in known, (
            f"⚠⚠ 0x{spell_id:02X} の resist_field '{field}' は "
            f"memory_map にありません（★実在するのは {sorted(known)}）")


def test_設定の呪文IDがmemory_mapに実在する():
    """⚠ 存在しない呪文IDを設定に書いても、★永久に使われません。"""
    config = yaml.safe_load(CONFIG.read_bytes().decode("utf-8"))
    spells = ((config.get("auto_input") or {}).get("support") or {}
              ).get("spells") or {}
    text = MEMORY_MAP.read_bytes().decode("utf-8")
    for spell_id in spells:
        assert re.search(rf"^\s*0x{spell_id:02X}:\s*\{{\s*name:", text,
                         re.MULTILINE), (
            f"⚠ 呪文 0x{spell_id:02X} が memory_map にありません")


def test_倍率が近似だと書いてある():
    """⚠⚠ **ROM から取った値ではありません。**

    ★出典を書いておかないと、次に読む人が「実測値だ」と信じます。
    """
    body = CONFIG.read_bytes().decode("utf-8")
    at = body.index("  support:")
    block = body[at:at + 4000]
    assert block.count("source: 近似") >= 5, (
        "⚠ 倍率の出典が書かれていません（★近似だと分かるようにしてください）")


def test_4段階がbattle_typesと揃っている(result):
    """⚠ 片方だけ増えると、設定に書いた名前が黙って normal に落ちます。"""
    assert _ok(result, "★4段階ちょうど"), result


def test_RAMもメニューも知らない(result):
    """★画面も実機も無しで試せること（⚠ 判断層の約束）。"""
    for banned in ("memory%.read", "joypad", "emu%.", "gui%."):
        assert _ok(result, f"⚠ {banned} を使っていない"), result


# --- ⚠⚠ **まだ効かせていない**（★次の段） -------------------------------

BRIDGE = PROJECT_ROOT / "retroux" / "emulator" / "fceux" / "bridge.lua"


def _bridge_code() -> str:
    """⚠ 注釈は数えない（★説明で名前を出すのは構わない）。"""
    body = BRIDGE.read_bytes().decode("utf-8")
    return "\n".join(line for line in body.splitlines()
                      if not line.strip().startswith("--"))


def test_実機のログに出るところまで繋いである():
    """★★★ **「作ったけれど一度も通っていない」を避けます。**

    ⚠ Phase 6 で「部品は27件通るのに実機で `[役割]` 0件」を踏みました
      （`docs/design/handoff-20260807.md` §5 の1番）。
    ★候補を `[補助]` としてログに出すので、実機で見えます。
    """
    code = _bridge_code()
    assert "self.support_plan = load_module(" in code, (
        "⚠ モジュールを読み込んでいません")
    assert "function Bridge:_log_support" in code
    assert "self:_log_support(assessment)" in code, (
        "⚠⚠ 作っただけで呼んでいません（★Phase 6 と同じ形）")


def test_落ちても黙らない():
    """⚠⚠ **`pcall` が握りつぶして「0件」になった**のが Phase 6 の原因でした。

    ★理由を1回だけ残します（⚠ 毎回出すとログが埋まります）。
    """
    code = _bridge_code()
    at = code.index("self:_log_support(assessment)")
    around = code[max(0, at - 300):at + 500]
    assert "support_log_failed" in around, (
        "⚠ 失敗しても理由が残りません（★握りつぶしになります）")


def test_まだ判断には効かせていない():
    """⚠⚠ **Phase 7・8 は「評価と説明」までです。**

    ★効かせるときは Phase 10A と同じ規律を守ってください:

      > layered の拒否判定は「行動開始前」だけ行う。

    ⚠ 呪文は複数フレームにまたがるので、★2か所目を足すと
      **行動の途中で拒否して別の claim が入力する事故**が起きます。

    ⚠ ここでは「拒否点が増えていないこと」と
      「補助が行動の主張（claim）に入っていないこと」を見ます。
    """
    code = _bridge_code()
    assert code.count("self:_may_act(") == 1, (
        "⚠⚠ 拒否点が増えています。★1か所だけにしてください")
    assert "_claim_battle_support" not in code, (
        "⚠⚠ 補助を行動として主張し始めています。"
        "★`layered_veto_test.lua` の検査と、この検査を同じコミットで"
        "直してください")
    # ★ログの文言でも「まだ効かせていない」と言い続けること
    body = BRIDGE.read_bytes().decode("utf-8")
    at = body.index("function Bridge:_log_support")
    assert "※まだ効かせていません" in body[at:at + 3000]


def test_モジュールが単体で読める():
    """★`load_module` は失敗すると落ちます（⚠ 控えを作らないこと）。"""
    tail = MODULE.read_bytes().decode("utf-8").rstrip().splitlines()[-1]
    assert tail == "return Support", tail

WIRING = (PROJECT_ROOT / "research" / "probes" / "active"
          / "support_wiring_test.lua")


def test_偽RAMで本物のbridgeを通す():
    """★★★ **「呼んでいる」ではなく「実際に出る」を見ます。**

    ⚠⚠ 字面の検査（`self:_log_support(` がある）は、
      ★引数違い・例外の握りつぶしを**素通り**します。
      Phase 6 で踏んだのがまさにそれでした（部品27件通って実機0件）。

    → ★偽RAMで本物の `bridge` を動かし、`[補助]` の行が出ることを見ます。
    """
    if not (RUNNER.exists() and WIRING.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(WIRING)],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8",
                                                              "replace")
    if "lua5.1" in out and done.returncode != 0 and "[補助]" not in out:
        pytest.skip("Lua を動かせない環境")
    assert done.returncode == 0, out
    assert "★★★ [補助] が本物の bridge を通って出た" in out, out

"""旧分岐（控え）の削除（2026-08-08 / 戦闘AI再設計 Phase 10）。

## ★★★ 何を消したのか（⚠ 2種類の「legacy」を混ぜないこと）

    A. モジュールが読めない環境のための**控え**   -> ★消した
    B. `engine: legacy` という**利用者の設定**    -> ⚠ 残す

⚠⚠ A と B は別物です。★A は同じ規則を2か所に書いていただけで、
  **production では絶対に動きませんでした**。

## ★ なぜ動かなかったと言い切れるのか

`bridge.lua` の `load_module` は、読み込めないと `error()` を投げます。
⚠ **nil を返しません。** だから

    if self.actor_decision ~= nil then ... else <控え> end

の `else` には**到達できません**。★この検査がそれを固定します。

## ⚠ B を残した理由（相談回答 §12）

  3. veto 後 -> 無行動 0 / menu stuck 0 / 意図しない逃走 0   ⚠ 未測定
  4. 実機 monkey -> 重大回帰 0                               ⚠ 未実施
  5. 手動介入率 -> legacy 比で悪化していない                 ⚠ 未測定

★実機で測るまでは安全弁として残します。
"""

from __future__ import annotations

import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
FCEUX = PROJECT_ROOT / "retroux" / "emulator" / "fceux"
BRIDGE = FCEUX / "bridge.lua"
BASELINE = (PROJECT_ROOT / "research" / "probes" / "active"
            / "battle_ai_baseline_test.lua")

#: ★控えを持っていたモジュール
MODULES = ("actor_decision", "tactics_commander", "party_coordinator")


def _bridge() -> str:
    return BRIDGE.read_bytes().decode("utf-8")


def _code_lines(source: str) -> str:
    """⚠ 注釈は数えない（★説明で名前を出すのは構わない）。"""
    return "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("--"))


# --- ★★★ 到達できなかったことの根拠 -------------------------------------


def test_モジュールが読めなければ落ちる():
    """★★★ **これが削除の根拠そのもの**。

    ⚠ `load_module` が nil を返すなら、控えには意味がありました。
      ★`error()` を投げるので、**呼ぶ側は nil を受け取れません**。
    """
    source = _bridge()
    at = source.index("local function load_module")
    body = source[at:source.index("\nend", at)]
    assert "error(" in body, (
        "⚠⚠ 読み込めないときに落ちなくなりました。"
        "★控えを消した根拠が崩れています")
    assert "return nil" not in body, (
        "⚠⚠ nil を返すようになりました。★控えが必要になります")


def test_全モジュールが値を返す():
    """⚠ `loadfile` に成功しても、★`return` が無ければ nil になります。

    ⚠⚠ そうなると `load_module` は落ちずに nil を返し、
      ★消した控えが必要だった、ということになります。
    """
    for name in MODULES + ("battle_types",):
        path = FCEUX / f"{name}.lua"
        tail = path.read_bytes().decode("utf-8").rstrip().splitlines()[-1]
        assert tail.startswith("return "), (
            f"⚠⚠ {name}.lua が値を返していません: {tail!r}")


def test_控えの分岐が残っていない():
    """★同じ規則を2か所に書かない（⚠ 片方だけ直すと黙って食い違う）。"""
    code = _code_lines(_bridge())
    for name in MODULES:
        for pattern in (f"self.{name} ~= nil", f"self.{name} == nil"):
            assert pattern not in code, (
                f"⚠ 控えの分岐が残っています: {pattern}")


def test_二重に書かれていた規則が消えている():
    """⚠⚠ **字面ではなく、規則そのものが1つだけであること**を見ます。

    ★消したのは「最も減っている人を探す」ループと
      「1. 自分が緊急 -> 2. 守る相手 -> 3. 自分」の並びです。
      ⚠ どちらも `actor_decision.lua` に**同じものがあります**。

    ⚠ 検査に**行の字面**を書かないこと（★2026-08-07 に踏んだ5番）。
      ここでは「その規則を作る式が bridge.lua に無いこと」を見ます。
    """
    code = _code_lines(_bridge())
    # ★「最も減っている人」を測る式（`max_hp * ratio - hp`）
    assert "other.max_hp * ratio" not in code, (
        "⚠ 「最も減っている人」を探す式が bridge.lua に残っています"
        "（★`actor_decision.lua` にあるものと二重です）")
    # ★緊急自己回復のしきい値を bridge.lua で読み直していないこと
    assert code.count("emergency_self_hp_threshold") <= 1, (
        "⚠ 緊急自己回復の判定が2か所にあります")

    # ⚠⚠ **移した先に本当にあること**（★消しただけで無くなっては困る）
    decision = (FCEUX / "actor_decision.lua").read_bytes().decode("utf-8")
    assert "max_hp" in decision and "protect_target" in decision


# --- ⚠⚠ 消したぶんの安全網（golden behavior / §12 条件6）----------------


def test_決めた答えを持っている():
    """★★★ **legacy を消すと「新旧の比較」自体ができなくなります。**

    ⚠ 相談回答 §12 の条件6。★消す前に期待値を固定しました。
    """
    source = BASELINE.read_bytes().decode("utf-8")
    assert "local GOLDEN = {" in source, (
        "⚠⚠ 決めた答えの表がありません（★消したのに安全網が無い状態）")
    rows = re.findall(r'^\s*\{ ".*?", ".*?", \d, ".*?" \},\s*$',
                      source, re.MULTILINE)
    assert len(rows) >= 36, f"⚠ 決めた答えが {len(rows)} 通りしかありません"


def test_新旧の比較をやめている():
    """⚠ 比べる相手を消したのに比較が残っていると、★空振りします。"""
    source = BASELINE.read_bytes().decode("utf-8")
    code = _code_lines(source)
    assert "use_legacy" not in code, (
        "⚠ 比べる相手はもう居ません（★`use_legacy` を消してください）")


def test_表の数と確かめた数が合っている():
    """⚠ 場面を消したのに表だけ残る、を防ぐ検査があること。"""
    source = BASELINE.read_bytes().decode("utf-8")
    assert "check(#GOLDEN, seen," in source


# --- ⚠ engine: legacy は**消していない** --------------------------------


def test_利用者の設定は残っている():
    """⚠⚠ **A（控え）と B（設定）を混ぜない。**

    ★`engine: legacy` を消す ＝ すべての利用者で layered を既定にする、
      という意味です。⚠ 相談回答 §12 の条件3・4・5 が未測定なので残します。
    """
    source = _bridge()
    assert "function Bridge:_use_layered" in source
    assert "Types.Engine.LEGACY" in source, (
        "⚠⚠ 利用者の安全弁まで消しています（★実機で測ってからにしてください）")


def test_既定は従来どおり():
    """⚠ 設定を触っていない人の挙動を変えない。"""
    import yaml

    config = yaml.safe_load(
        (PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml")
        .read_bytes().decode("utf-8"))
    engine = (config.get("auto_input") or {}).get("engine")
    assert engine in (None, "legacy"), (
        f"⚠⚠ 同梱の既定が {engine} になっています（★実機で測ってからです）")


def test_残っている条件を書いてある():
    """★「まだ満たしていない条件」を**コードに残す**（⚠ 忘れないため）。"""
    source = _bridge()
    at = source.index("--- 三層構造で判断するか。")
    head = source[at:at + 2000]
    for word in ("monkey", "手動介入率", "未測定"):
        assert word in head, f"⚠ 残っている条件に {word} がありません"

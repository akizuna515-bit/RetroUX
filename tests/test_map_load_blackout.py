"""ロード直後の暗転を「見た地形」に記録しない（2026-08-11 / 依頼者の指摘）。

★★ 直した不具合 ★★
  Pボタン等でセーブステートをロードすると画面が暗転し、その暗い画面を
  地図の材料として記録して**世界地図が黒塗り**になっていた。
  → savestate.registerload でロードを拾い、直後の数フレームは
    `_map_sample` が採り直さず前回の材料を返す（黒を記録しない）。
"""

from __future__ import annotations

import pathlib

BRIDGE = (pathlib.Path(__file__).resolve().parents[1]
          / "retroux" / "emulator" / "fceux" / "bridge.lua")


def _bridge() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def test_ロードを拾って地図採取を止める仕掛けがある():
    src = _bridge()
    # ★ロードを拾う
    assert "savestate.registerload" in src
    # ★スキップの期限をフレームで持つ
    assert "map_load_until_frame" in src
    assert "MAP_LOAD_SKIP_FRAMES" in src


def test_暗転中は採らない仕掛けがある():
    """★ロード以外の暗転（画面切替・フェード）も拾う（依頼者「なぜ黒塗りに」）。"""
    src = _bridge()
    assert "function Bridge:_screen_looks_blank()" in src
    # ★_map_sample が暗転チェックを通す
    start = src.index("function Bridge:_map_sample(")
    end = src.index("\nfunction Bridge:", start + 10)
    body = src[start:end]
    assert "self:_screen_looks_blank()" in body


def test_map_sampleがスキップ期間は採り直さない():
    """★`_map_sample` の冒頭で、期限内なら前回の材料を返す（黒を記録しない）。"""
    src = _bridge()
    start = src.index("function Bridge:_map_sample(")
    end = src.index("function Bridge:", start + 10)
    body = src[start:end]
    assert "map_load_until_frame" in body, "★スキップ判定が _map_sample に無い"
    assert "framecount()" in body
    # ★採り直さず return する（前回の材料 or 空）
    assert "return self.map_sample" in body


def test_ロード拾いは落ちても本体を止めない():
    """⚠ savestate API が無い/例外でも起動を止めない（pcall＋nil ガード）。"""
    src = _bridge()
    # ★API が無ければ触らない（nil ガード）
    assert "if savestate ~= nil and savestate.registerload ~= nil then" in src
    # ★登録は pcall で包む（例外でも起動を止めない）
    reg = src.index("savestate.registerload(function()")
    assert "pcall(function()" in src[reg - 120:reg]



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます（2026-08-12 / F-089）
#
# ⚠⚠ 上の検査は
#       assert "function Bridge:_screen_looks_blank()" in src
#   のように、**仕掛けがあるか**しか見ていません。
#   ★しきい値をひとつ変えれば、字面はそのままで
#     **真っ黒でも「明るい」と言う**ようになります（＝黒が地図に焼き付く）。
#   ⚠ 一度記録した黒は**あとから消せません**。
# =====================================================================

import os          # noqa: E402
import subprocess  # noqa: E402
import sys         # noqa: E402

import pytest      # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HARNESS = _ROOT / "research" / "probes" / "active" / "map_blackout_test.lua"
_RUNNER = _ROOT / "research" / "probes" / "reusable" / "lua_run.py"


@pytest.fixture(scope="module")
def blackout_lua():
    if not (_RUNNER.exists() and _HARNESS.exists()):
        pytest.skip("Lua のハーネスが無い")
    done = subprocess.run(
        [sys.executable, str(_RUNNER), str(_HARNESS)],
        cwd=str(_ROOT), capture_output=True, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (done.stdout or b"").decode("utf-8", "replace")
    err = (done.stderr or b"").decode("utf-8", "replace")
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _b_ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeで暗転の門が全部通る(blackout_lua):
    assert "すべて合格" in blackout_lua, blackout_lua


def test_暗転の検査の数が足りている(blackout_lua):
    count = sum(1 for line in blackout_lua.splitlines()
                if line.startswith("OK "))
    assert count >= 17, f"OK が {count} 件しかありません\n{blackout_lua}"


def test_しきい値の境目を守っている(blackout_lua):
    """⚠⚠ ここを動かすと、静かに壊れます。

    ★上げすぎ → 明るい画面も暗転扱いで**地図が採れない**
    ★下げすぎ → 真っ黒でも採って**黒が焼き付く**（あとから消せません）
    """
    assert _b_ok(blackout_lua, "★合計 24 は暗転（境目）"), blackout_lua
    assert _b_ok(blackout_lua, "★合計 25 は明るい（境目）"), blackout_lua


def test_1点でも明るければ止めない(blackout_lua):
    """★5点のうち1点でも明るければ、ふつうの画面として採ります。"""
    assert _b_ok(blackout_lua, "⚠ 1点でも明るければ暗転ではない"), blackout_lua


def test_画面が読めなくても落ちない(blackout_lua):
    """⚠ API が無い・例外でも、**暗転扱いにしない**（★止めない）。"""
    assert _b_ok(blackout_lua, "⚠ 画面を読む API が無ければ false"), blackout_lua
    assert _b_ok(blackout_lua, "⚠ 例外でも false（落ちない）"), blackout_lua


def test_ロード直後は採り直さない(blackout_lua):
    """★2026-08-11 依頼者「なぜ黒塗りに」への対応そのもの。"""
    assert _b_ok(blackout_lua, "★期限内は採り直さず前回を返す"), blackout_lua
    assert _b_ok(blackout_lua, "★期限が切れたら採り直す"), blackout_lua


def test_見送った回数を数えている(blackout_lua):
    """⚠ 黙って捨てない（★何回見送ったか分かること）。"""
    assert _b_ok(blackout_lua, "★見送った回数を数える"), blackout_lua


def test_前回が無ければ黒を記録しない(blackout_lua):
    """⚠⚠ 初回の暗転で黒を書くと、地図に焼き付きます。"""
    assert _b_ok(blackout_lua, "⚠ 前回が無ければ空を返す"), blackout_lua

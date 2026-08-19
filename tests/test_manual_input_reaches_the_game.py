"""AI操作OFF のときプレイヤーの入力がゲームへ届くこと（2026-07-31 / 実機 T-5）。

★依頼者の報告:
    「キーボード入力を受け付けない。エミュレーター画面で、
      キーを受け付けた表示はあるが、ゲームに届いていない。」

★★ 原因 ★★

  AI操作OFF の人の番で `{}`（空のボタン表）を**毎フレーム**返していた。
  `full_button_set({})` は8ボタン全部を `false` にする。
  ⚠⚠ FCEUX の `joypad.set` で `false` は「離れている」ではなく
    **「強制的に離す」**。だから人がキーを押しても同じフレームで消える。
  FCEUX の入力表示には出るのにゲームへ届かない、という形になっていた。

  ★`{}` を選んだこと自体には理由があった。`nil` を返すと下の判断へ落ちて
    「たたかう」の A 連打になる（OFF にしたのに勝手に戦う）。
    **`nil` でも `{}` でもない第3の返り値**が要る、というのが答え。
    それが `HANDS_OFF`（主張しない、かつ下へも落とさない）。

## ⚠ もう1つ見つけた穴（同じ受入項目の裏返し）

  `_claim_manual_character` は**コマンドメニューでしか**判断しない。
  そのため人が自分で「たたかう」を押して**敵選択が開いた瞬間から素通り**になり、
  AI がカーソルを動かして A を押していた。
  ＝「AI操作OFF にしたのに勝手に敵を選ばれる」。

★動きそのものは `research/probes/active/manual_input_test.lua` が本物の Lua で確かめている。
  ここで固定するのは**設計の約束**（壊れやすい形へ戻っていないか）。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "research" / "probes" / "reusable" / "lua_run.py"
HARNESS = (PROJECT_ROOT / "research" / "probes" / "active"
           / "manual_input_test.lua")


def _bridge() -> str:
    return (PROJECT_ROOT / "retroux" / "emulator" / "fceux"
            / "bridge.lua").read_text(encoding="utf-8")


def _body(src: str, name: str) -> str:
    """`function Bridge:name` の中身を切り出す（次の関数定義まで）。"""
    i = src.index(f"function Bridge:{name}")
    j = src.index("\nfunction Bridge:", i + 10)
    return src[i:j]


def test_handing_control_back_is_a_third_return_value():
    """★`nil`（下へ落ちる）でも `{}`（強制的に離す）でもない返り値があること。"""
    src = _bridge()
    assert "local HANDS_OFF = setmetatable" in src
    assert "Bridge.HANDS_OFF = HANDS_OFF" in src, "試験から参照できない"


def test_an_ai_off_turn_never_forces_the_buttons_forever():
    """⚠⚠ ここが不具合そのもの。`{}` を**返し続けて**はいけない。

    ★番の頭だけ期限つきで離し（直前の AI の押下を断ち切る）、
      そのあとは `HANDS_OFF`（`joypad.set` を呼ばない）。
    """
    src = _bridge()
    body = _body(src, "_release_then_hands_off")
    assert "return HANDS_OFF" in body, "人に返す経路が無い"
    # ⚠⚠ **残り回数そのものを読んでいること。**
    #   `self.manual_release_left` が本文のどこかにあるか、では足りない。
    #   次の行の `self.manual_release_left = left - 1` に当たってしまい、
    #   ★判定を定数にしても緑のままだった（`research/probes/active/break_release.py` が検出）。
    #   「その名前が出てくる」ではなく「そこから読んでいる」を見る。
    assert "local left = self.manual_release_left or 0" in body, \
        "残り回数を読んでいない（無期限に離し続ける形に戻っている）"

    # ★AI操作OFF と 代替行動「手動」の**両方**が同じ経路を通ること。
    #   片方だけ直すと、もう片方で同じ症状が残る。
    for name in ("_claim_manual_character", "_claim_fallback_action"):
        assert "_release_then_hands_off" in _body(src, name), \
            f"{name} が古い `{{}}` のままになっている"


def test_the_sentinel_stops_joypad_set_but_still_counts_as_battle():
    """★`HANDS_OFF` はボタンを送らないが、戦闘中の主張としては扱う。

    ⚠ 「主張なし」にしてしまうと、戦闘直後のメニュー後始末の期限が
      戦闘中から数え始めてしまう（別の不具合を呼ぶ）。
    """
    body = _body(_bridge(), "_apply_input")
    assert "local hands_off = (claim == HANDS_OFF)" in body
    # ★期限のリセットを済ませた**あと**で nil へ落とすこと
    assert body.index("self.release_left = self.release_frames_after_battle") \
        < body.index("if hands_off then claim = nil end")


def test_the_diagnostic_separates_handing_back_from_not_knowing():
    """★「読めなくて何もしなかった」と「意図して人に返した」を混ぜない。

    ⚠ 並びは実際に採用される順（`final = claim or requested`）と揃えること。
      hands_off を requested より前に置くと、要求を送ったのに
      「人に返した」と記録される（診断が嘘をつく）。
    """
    body = _body(_bridge(), "_apply_input")
    assert '(hands_off and "hands_off")' in body
    assert body.index('(requested and "request")') \
        < body.index('(hands_off and "hands_off")')


def test_the_target_menu_also_respects_ai_off():
    """⚠ コマンドメニュー以外でも AI操作OFF を見ること（見落としていた穴）。"""
    src = _bridge()
    assert "function Bridge:_current_member_ai_off()" in src
    body = _body(src, "_claim_target_selection")
    assert "_current_member_ai_off" in body, "敵選択が素通りしている"
    # ★押しかけの状態を捨てること（次の人へ持ち越さない）
    i = body.index("_current_member_ai_off")
    assert "_reset_target_seek" in body[i:i + 120]


def test_an_unreadable_member_keeps_the_old_behaviour():
    """⚠ 名前が読めないときに止めない。止めると自動戦闘が丸ごと動かなくなる。"""
    body = _body(_bridge(), "_current_member_ai_off")
    # 読めない経路はすべて false（＝これまでどおり AI が動く）
    assert body.count("return false") >= 3
    assert "if m == nil or m.name == nil then return false end" in body


def test_the_release_window_is_configurable_and_short():
    """★期限は設定で変えられること。⚠ その間はキーが効かないので短く。"""
    config = (PROJECT_ROOT / "retroux" / "plugins" / "dq2"
              / "config.yaml").read_text(encoding="utf-8")
    assert "manual_release_frames: 8" in config
    assert "self.manual_release_frames = ai.manual_release_frames or 8" \
        in _bridge()



# =====================================================================
# ★★ ここから下は「書いてある」ではなく「**動く**」を見ます ★★
#
# ⚠⚠ **2026-08-12 まで、この確認は1度も走っていませんでした。**
#   `manual_input_test.lua` は上の docstring で名前を出しているだけで、
#   `pytest` からは呼ばれていませんでした。
#   ★そのあいだに `bridge.lua` へ `_track_turn_actor` が増え（2026-08-08）、
#     ハーネスは **9日間動かないまま**でした
#     （`attempt to call method '_track_turn_actor' (a nil value)`）。
#
# ★つまり「人の入力が消える」という**最も重い不具合の見張り**が、
#   誰にも気づかれずに外れていました。⚠ 上の文字列検査は全部緑のままです。
# =====================================================================


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
    if "SKIP:" in out:
        pytest.skip(out.strip())
    if done.returncode != 0 and "lua5.1" in err:
        pytest.skip("Lua を動かせない環境")
    return out + err


def _ok(result: str, label: str) -> bool:
    return any(line.startswith("OK") and label in line
               for line in result.splitlines())


def test_本物のbridgeでハーネスが全部通る(lua_result):
    """⚠ ここが赤いときは、**文字列検査が緑でも壊れています**。"""
    assert "NG" not in lua_result.replace("NG  ", "NG"), lua_result
    assert "すべて合格" in lua_result, lua_result


def test_検査の数が足りている(lua_result):
    """⚠⚠ 途中で落ちて「0件でも合格」になっていないこと。

    ★実際、2026-08-12 まではハーネスが**最初の関数で落ちて**いました。
      件数を見ていないと「動かない」と「全部通った」を区別できません。
    """
    count = sum(1 for line in lua_result.splitlines()
                if line.startswith("OK "))
    assert count >= 11, f"OK が {count} 件しかありません\n{lua_result}"


def test_人の番はjoypad_setを呼ばない(lua_result):
    """⚠⚠ **不具合そのもの。** 呼ぶと同じフレームで人の入力が消えます。"""
    assert _ok(lua_result, "HANDS_OFF なら joypad.set を呼ばない"), lua_result


def test_頭の数フレームだけ離してあとは人に返す(lua_result):
    assert _ok(lua_result, "頭3フレームは離し、あとは人に返す"), lua_result


def test_勝手にたたかうへ落ちない(lua_result):
    """★`nil` を返すと下の判断へ落ちて「たたかう」の A 連打になります。"""
    assert _ok(lua_result, "nil を返さない"), lua_result


def test_敵選択でも手を出さない(lua_result):
    """★人が自分で「たたかう」を押した直後の穴（同じ受入項目の裏返し）。"""
    assert _ok(lua_result, "AI操作OFF なら敵選択に手を出さない"), lua_result


def test_AI操作ONは今までどおり押す(lua_result):
    """⚠ 直しすぎていないか（★OFF を直して ON を壊さない）。"""
    assert _ok(lua_result, "AI操作ON なら押下を続ける"), lua_result

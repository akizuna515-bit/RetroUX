"""画面に出す値の組み立て（2026-08-01 の Phase 6 / 指示書 §7.2）。

★★ **画面を建てずに確かめる。** ★★

  分割前は `main_window.py` の `_refresh()` の中で、文言と色を
  同時に組み立てていました。⚠ そのため **AUTO の5分岐は
  1件もテストされていませんでした**（2026-08-01 に実測）。

★ここが見るのは「何を出すか」だけです。
  **色は見ません**（`main_window.py` の `_TONE_COLORS` の仕事）。
  ⚠ ここで色を確かめると、配色を変えるたびにテストが赤くなります。
"""

from __future__ import annotations

import dataclasses

import pytest

from retroux.ui.view_model import (TONE_CAUTION, TONE_DANGER, TONE_INFO,
                                   TONE_MUTED, TONE_OK, UiState)


@dataclasses.dataclass
class FakeGroup:
    name: str
    count: int = 1


@dataclasses.dataclass
class FakeGame:
    """Lua が書く「いまの値」の代わり。

    ⚠ 既定は**何も分かっていない**状態にする。
      そうしないと「分からないときの出し方」を試せない。
    """

    gold: int | None = None
    force_auto: bool = False
    auto_enabled: bool | None = None
    manual_latched: bool = False
    auto_input: bool = False
    danger_reason: str | None = None
    enemy_groups: list = dataclasses.field(default_factory=list)


def state(**over) -> UiState:
    game = over.pop("game", None) or FakeGame(**over.pop("g", {}))
    return UiState(game=game, **over)


# --- 状態欄の調子 -------------------------------------------------------

def test_a_quiet_field_is_muted():
    assert state().state_tone == TONE_MUTED


def test_being_in_battle_is_informational_not_alarming():
    assert state(in_battle=True).state_tone == TONE_INFO


def test_real_danger_is_shown_as_danger():
    assert state(danger=True).state_tone == TONE_DANGER


def test_not_being_able_to_read_the_party_is_not_danger():
    """★★ 「読めていない」を赤くしない ★★

    ⚠ タイトル画面で赤い『危険状態』が出っぱなしになり、壊れて見えた。
      実際は安全側へ正しく倒れていただけ。
    """
    got = state(danger=True, danger_reason=UiState.UNREADABLE)
    assert got.state_tone != TONE_DANGER
    assert got.state_label == "待機中（セーブ未読込）"


# --- 速度 ---------------------------------------------------------------

def test_normal_speed_is_written_in_words():
    """⚠ 「×1」だけだと、倍速なのか等速なのか読み取りにくい。"""
    assert state(speed=1.0).speed_badge.text == "等速"


def test_turbo_shows_the_multiplier():
    got = state(speed=8.0).speed_badge
    assert got.text == "Turbo ×8"
    assert got.tone == TONE_INFO


def test_a_hair_above_one_still_counts_as_normal_speed():
    """★浮動小数の誤差で「Turbo ×1」と出さない。"""
    assert state(speed=1.005).speed_badge.text == "等速"


def test_a_missing_speed_does_not_crash():
    assert state(speed=0).speed_badge.text == "等速"


# --- 所持ゴールド -------------------------------------------------------

def test_gold_that_has_not_arrived_is_a_dash_not_zero():
    """★★ 0 と 不明 を混ぜない ★★ 0 と書くと「無一文」に見える。"""
    assert state().gold_text == "-"


def test_gold_is_grouped_for_reading():
    assert state(g={"gold": 12345}).gold_text == "12,345"


def test_actually_having_no_money_shows_zero():
    """⚠ 本当に 0 のときは 0 と出す（`-` にしない）。"""
    assert state(g={"gold": 0}).gold_text == "0"


# --- ★★ AUTO の5分岐（分離前は1件もテストが無かった）★★ ---------------

def test_auto_running_is_shown_as_on():
    got = state(g={"auto_enabled": True, "auto_input": True}).auto_badge
    assert got.text == "ON"
    assert got.tone == TONE_OK


def test_auto_turned_off_by_the_person_says_so():
    """⚠ **切ってあるとき**と**止められたとき**は別物。"""
    got = state(g={"auto_enabled": False}).auto_badge
    assert got.text == "OFF（自分で操作）"
    assert got.tone == TONE_MUTED


def test_forced_auto_is_not_presented_as_a_third_mode():
    """★「強制AUTO」は AUTO の一形態として書く（指示書 §4）。

    ⚠ 第3のモードに見せると、どちらが強いのか分からなくなる。
    """
    got = state(g={"force_auto": True}).auto_badge
    assert "ON" in got.text
    assert "安全停止を解除" in got.text
    assert got.tone == TONE_CAUTION


def test_a_safety_stop_says_why():
    """★★ **止まった理由まで出す**（2026-07-31 の指示書 §6.3）★★

    ⚠ 「OFF」とだけ出ていると、切ってあるのか止められたのか区別が付かない。
    """
    got = state(g={"auto_enabled": True, "auto_input": False,
                   "danger_reason": "HPが1/4を切りました"}).auto_badge
    assert got.text == "停止（HPが1/4を切りました）"
    assert got.tone == TONE_CAUTION


def test_a_safety_stop_without_a_reason_still_says_it_stopped():
    """⚠ 理由が分からなくても**黙らない**。"""
    got = state(g={"auto_enabled": True, "auto_input": False}).auto_badge
    assert got.text == "停止"


def test_a_latched_manual_battle_is_distinguished_from_a_stop():
    got = state(g={"auto_enabled": True, "manual_latched": True}).auto_badge
    assert got.text == "停止（この戦闘は手動）"


def test_a_latched_battle_shows_the_reason_when_there_is_one():
    got = state(g={"auto_enabled": True, "manual_latched": True,
                   "danger_reason": "ボス"}).auto_badge
    assert got.text == "停止（ボス）"


def test_forced_auto_wins_over_a_latch():
    """★安全停止を外しているのだから、掛かっている錠より強い。"""
    got = state(g={"force_auto": True, "manual_latched": True}).auto_badge
    assert "安全停止を解除" in got.text


def test_being_switched_off_wins_over_a_latch():
    """⚠ 切ってあるなら「この戦闘は手動」ではなく「自分で操作」。"""
    got = state(g={"auto_enabled": False, "manual_latched": True}).auto_badge
    assert got.text == "OFF（自分で操作）"


# --- 記録しているのは誰か -----------------------------------------------

def test_read_only_says_another_process_is_recording():
    """★★ 「壊れている」ではなく「別プロセスが記録中」★★

    ⚠ 区別できないと、直せる問題を直せない問題だと思ってしまう。
      （2026-08-01 に、これで実際に「保存できない」と誤解された）
    """
    assert "別プロセスが記録中" in state(read_only=True).mode_text


def test_recording_here_says_so():
    assert state().mode_text == "このGUIが記録中"


# --- 出ている敵 ---------------------------------------------------------

def test_enemies_fall_back_to_the_recorded_names():
    """★群れが読めなければ、記録側の名前を出す（空にしない）。"""
    assert state(current_monsters="スライム").monsters_text == "スライム"


def test_a_single_enemy_has_no_count():
    got = state(g={"enemy_groups": [FakeGroup("ドラキー")]})
    assert got.monsters_text == "ドラキー"


def test_several_of_the_same_enemy_are_counted():
    got = state(g={"enemy_groups": [FakeGroup("スライム", 3),
                                    FakeGroup("ドラキー")]})
    assert got.monsters_text == "スライム×3, ドラキー"


# --- 警告 ---------------------------------------------------------------

def test_no_warning_is_none_so_the_row_can_be_hidden():
    """★★ 空文字ではなく None ★★

    ⚠ 空文字だと「警告欄が空で出ている」のか「警告が無い」のか、
      呼ぶ側で区別できない。
    """
    assert state().warning_text is None


def test_each_warning_gets_its_own_mark():
    got = state(warnings=["ROMが違います", "設定が古いです"]).warning_text
    assert got.startswith("⚠ ")
    assert got.count("⚠") == 2


# --- ★★ ViewModel の原則（指示書 §7.3）★★ ----------------------------

@pytest.mark.parametrize("attr", ["state_tone", "speed_badge", "gold_text",
                                  "auto_badge", "mode_text", "monsters_text",
                                  "warning_text"])
def test_the_same_state_always_gives_the_same_answer(attr):
    """★★ 「同じ state なら同じ結果になる」（§7.3）★★

    ⚠ 時刻や乱数が混ざっていると、画面が理由もなく変わる。
    """
    got = state(speed=4.0, in_battle=True, warnings=["あ"],
                g={"gold": 7, "auto_enabled": True, "auto_input": True})
    first = getattr(got, attr)
    for _ in range(3):
        assert getattr(got, attr) == first


def test_the_view_model_does_not_carry_colours():
    """★★ 色は画面の都合であって、状態の意味ではない ★★

    ⚠ ViewModel が `#8fd18f` を知っていると、配色を変えるたびに
      ViewModel を直すことになる。
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "retroux" / "ui" / "view_model.py").read_text(encoding="utf-8")
    # ⚠ コメントと説明文は外す（自分の説明を誤検知しないため / Phase 5 の教訓）
    import ast
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.startswith("#") or len(node.value) != 7, \
                f"色らしき文字列がある: {node.value}"

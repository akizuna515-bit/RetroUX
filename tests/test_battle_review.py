"""戦況4行表示と直前戦闘レビュー（2026-08-12 / 依頼者の指示 §22）。

## ★ 何のための機能か

    RetroUX ではAUTO戦闘時の進行が速いため、
    «戦闘中に全情報を読むことより、戦闘終了後に
      「今の戦闘でAIがどう判断したか」を確認できること» を重視する。

★戦闘は約35倍で終わります。**読む前に消えます。**

## ⚠⚠ ここで守りたい壊れ方

  1. 同じターンを polling 回数ぶん増やす（0.2秒ごとに1件ずつ増える）
  2. 戦闘が終わった瞬間に「—（戦闘中に出ます）」へ戻る（読む間が無い）
  3. 次の戦闘が始まっても前の戦闘の履歴が混ざる
  4. 分からない勝敗を「勝利」と書く（★推測で埋めない）
"""

from __future__ import annotations

import pytest

from retroux.core.bridge.state_reader import GameState
from retroux.ui import battle_format as bf
from retroux.ui.battle_review import BattleReviewRecorder


def _game(seq=1, in_battle=True, turn=1, **kw):
    """★1回ぶんの `state.json` を模す。"""
    decisions = kw.pop("decisions", None)
    if decisions is None and turn is not None:
        decisions = [{"index": 0, "name": "lorasia", "action": "attack",
                      "reason": "", "turn": turn}]
    return GameState(in_battle=in_battle, battle_seq=seq,
                     ai_decisions=decisions or [], **kw)


# =====================================================================
# §22 Formatter
# =====================================================================

@pytest.mark.parametrize("internal,shown", [
    ("lorasia", "ロ"), ("samaltria", "サ"), ("moonbrooke", "ム"),
])
def test_キャラ名を1文字にする(internal, shown):
    assert bf.short_actor_name(internal) == shown


@pytest.mark.parametrize("internal,shown", [
    ("attack", "攻"), ("heal", "回"), ("item", "道"),
    ("support", "補"), ("defend", "防"), ("manual", "手"),
    ("attack_spell", "呪"),
])
def test_行動を1文字にする(internal, shown):
    assert bf.short_action_name(internal) == shown


def test_知らない値は潰さずそのまま出す():
    """⚠⚠ **「？」に潰さないこと。**

    ★知らない行動が増えたときに、画面で気づけるようにします。
      潰すと「表に足りていない」ことが永久に分かりません。
    """
    assert bf.short_action_name("brand_new") == "brand_new"
    assert bf.short_actor_name("someone") == "someone"


def test_推定ターンはT表記():
    assert bf.format_estimated_turn_row(0.5, 4.2) == "撃破 0.5T / 崩壊 4.2T"


def test_片方しか無いときは残りをダッシュにする():
    """⚠ 0 で埋めない。★「届いていない」と「0ターン」は別物です。"""
    assert bf.format_estimated_turn_row(0.5, None) == "撃破 0.5T / 崩壊 —"
    assert bf.format_estimated_turn_row(None, None) == "—"


def test_戦況の本文に見出しと同じ語を入れない():
    """★見出しにあるので本文には要りません（指示 §2・§3.1）。"""
    row = bf.format_assessment_row("advantage", "short")
    assert row == "優勢・短期"
    assert "戦況" not in row


def test_短期戦は短期と出す():
    assert bf.format_assessment_row("even", "long") == "均衡・長期"


def test_分からないは消さない():
    """⚠ `unknown` は「材料が無いと分かった」＝値が来ています。"""
    assert "分からない" in bf.format_assessment_row("unknown", None)


def test_役割の行は短縮される():
    roles = "lorasia:attack(3.0) / samaltria:item(1.3) / moonbrooke:support(1.3)"
    assert bf.format_role_row(roles) == "役割 ロ:攻3.0 サ:道1.3 ム:補1.3"


def test_点を消した役割も出せる():
    """★戦闘が終わったあとの要約用（指示 §10）。"""
    roles = "lorasia:attack(3.0) / samaltria:item(1.3)"
    assert bf.format_role_row(roles, with_score=False) == "役割 ロ:攻 サ:道"


def test_4行になる():
    rows = bf.format_summary_rows(
        balance="advantage", length="short", win=0.5, lose=4.2,
        plan="省資源", score=5.5, margin=1.5,
        roles="lorasia:attack(3.0) / samaltria:item(1.3)")
    assert rows == [
        "優勢・短期",
        "撃破 0.5T / 崩壊 4.2T",
        "戦術 省資源 5.5/+1.5",
        "役割 ロ:攻3.0 サ:道1.3",
    ]


def test_劣勢や僅差は警告を出す():
    """⚠ 依頼者の指示どおり、**既存の値から素直に分かるものだけ**（§5）。"""
    warns = bf.assessment_warnings(
        balance="disadvantage", win=6.2, lose=2.1, margin=0.1)
    assert "劣勢" in warns
    assert any("崩壊が先" in w for w in warns)
    assert any("僅差" in w for w in warns)


def test_全員同じ点なら区別できていないと言う():
    """⚠⚠ 実際 `attack(1.0)` が3人並んで「動いた」と誤認しかけました。"""
    assert bf.roles_all_same("a:attack(1.0) / b:attack(1.0)")
    assert not bf.roles_all_same("a:attack(1.0) / b:attack(2.0)")


# =====================================================================
# §22 Turn履歴
# =====================================================================

def test_同じターンを何度受け取っても1件のまま():
    """★★★ **これが無いと 0.2 秒ごとに履歴が増えます**（指示 §14・§15）。"""
    rec = BattleReviewRecorder()
    rec.observe(_game(turn=1, battle_balance="advantage"))
    assert rec.current.total_turns == 1
    for _ in range(10):
        rec.observe(_game(turn=1, battle_balance="advantage"))
    assert rec.current.total_turns == 1, "⚠⚠ 同じターンが増えています"

    rec.observe(_game(turn=2, battle_balance="even"))
    assert rec.current.total_turns == 2


def test_同じターンの中身が増えたら上書きする():
    """⚠ 判断が先に来て、戦況があとから届くことがあります。

    ★足さずに**書き換え**ます（1ターン=1件を崩さない）。
    """
    rec = BattleReviewRecorder()
    rec.observe(_game(turn=1))
    assert rec.current.turns[0].balance is None
    changed = rec.observe(_game(turn=1, battle_balance="advantage"))
    assert changed is True
    assert rec.current.total_turns == 1
    assert rec.current.turns[0].balance == "advantage"


def test_ターンが読めないうちは足さない():
    """⚠⚠ **0 を1ターン目にしない**（★推測で埋めない）。"""
    rec = BattleReviewRecorder()
    rec.observe(_game(turn=None, decisions=[], battle_balance="advantage"))
    assert rec.current is not None
    assert rec.current.total_turns == 0


def test_変わっていなければ何もしないと答える():
    """★画面はこれを見て、**変わったときだけ**描き直します（指示 §20）。"""
    rec = BattleReviewRecorder()
    rec.observe(_game(turn=1, battle_balance="advantage"))
    assert rec.observe(_game(turn=1, battle_balance="advantage")) is False


# =====================================================================
# §22 Battle終了 / 次戦闘
# =====================================================================

def test_戦闘が終わっても直前戦闘として残る():
    """★★★ **これが指示 §9（最重要）そのもの**。

    ⚠ AUTO は一瞬で終わるので、即座に「—」へ戻すと読む間がありません。
    """
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1, battle_balance="advantage"))
    rec.observe(_game(seq=1, turn=2, battle_balance="advantage"))
    rec.observe(_game(seq=1, in_battle=False, turn=None, decisions=[]))

    assert rec.current is None
    assert rec.previous is not None
    assert rec.previous.total_turns == 2
    assert rec.active() is rec.previous


def test_次の戦闘が始まったら履歴を作り直す():
    """⚠ 前の戦闘のターンが混ざらないこと（指示 §11）。"""
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1))
    rec.observe(_game(seq=1, turn=2))
    rec.observe(_game(seq=1, in_battle=False, turn=None, decisions=[]))
    rec.observe(_game(seq=2, turn=1))

    assert rec.current.battle_seq == 2
    assert rec.current.total_turns == 1
    assert rec.previous.battle_seq == 1, "⚠ 直前戦闘が失われています"
    assert rec.previous.total_turns == 2


def test_戦闘の切れ目を見逃しても混ざらない():
    """⚠⚠ 倍速だと戦闘まるごと1回を画面が見逃します（0.2秒に収まる）。

    ★`battle_seq` が変わったことで「別の戦闘」だと分かります。
    """
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1))
    rec.observe(_game(seq=3, turn=1))          # ★in_battle のまま番号が飛んだ
    assert rec.current.battle_seq == 3
    assert rec.current.total_turns == 1
    assert rec.previous.battle_seq == 1


def test_勝敗は分かるときだけ書く():
    """⚠ `state.json` に勝敗は来ません。★推測で「勝利」と書かないこと。"""
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1, battle_balance="advantage"))
    rec.observe(_game(seq=1, in_battle=False, turn=None, decisions=[]))

    rows = bf.format_previous_rows(rec.previous)
    assert rows[0] == "直前 1T", f"⚠ 勝敗を勝手に書いています: {rows[0]!r}"

    rec.set_result("勝利")
    assert bf.format_previous_rows(rec.previous)[0] == "直前 勝利 1T"


def test_一度も戦っていなければ戦闘中に出ますと書く():
    assert bf.format_previous_rows(None) == bf.IDLE_ROWS


def test_DBに入る勝敗の4種すべてに日本語がある():
    """⚠⚠ **2026-08-12 の訂正をここで固定します。**

    最初 `{"win": "勝利", "retreat": "撤退"}` と書いていました。
    ★根拠は `database.py` のスキーマのコメント「win / retreat」でしたが、
      **`retreat` という値は存在しません**。⚠ 実データを見ていませんでした。

    ★実データ（`work/retroux.sqlite3` の 522 件）:

        win 500 / flee 13 / lose 6 / enemy_fled 3

    ★決めているのは `bridge.lua:3189` の4分岐です。
    ⚠ 抜けがあると、その戦闘だけ英語のまま画面に出ます。
    """
    from retroux.ui.battle_review import RESULT_LABELS

    for value in ("win", "lose", "flee", "enemy_fled"):
        assert value in RESULT_LABELS, (
            f"⚠ `{value}` の日本語がありません（★英語のまま画面に出ます）")
    assert "retreat" not in RESULT_LABELS, (
        "⚠ `retreat` は存在しない値です（★スキーマのコメントが誤り）")


def test_勝敗の言い換えはLuaの分岐と揃っている():
    """★`bridge.lua` が出す値と、画面の表を**同じ数**に保つ。

    ⚠ Lua に5つ目の結末が増えたら、ここが赤くなって気づけます。
    """
    import pathlib
    import re

    from retroux.ui.battle_review import RESULT_LABELS

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "retroux" / "emulator" / "fceux" / "bridge.lua").read_bytes()
    text = src.decode("utf-8")
    found = set(re.findall(r'outcome = "(\w+)"', text))
    assert found, "⚠ `bridge.lua` から結末の値を読めませんでした"
    assert found == set(RESULT_LABELS), (
        f"⚠⚠ Lua と画面の表が食い違っています。\n"
        f"  Lua にだけある: {sorted(found - set(RESULT_LABELS))}\n"
        f"  表にだけある:   {sorted(set(RESULT_LABELS) - found)}")


# =====================================================================
# §22 ツールチップ
# =====================================================================

def test_ツールチップに全ターンが出る():
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1, battle_balance="advantage",
                      battle_length="short", battle_turns_to_win=0.8,
                      battle_turns_to_lose=4.5, battle_plan="通常速攻",
                      battle_roles="lorasia:attack(3.0)"))
    rec.observe(_game(seq=1, turn=2, battle_balance="advantage",
                      battle_length="short", battle_plan="省資源",
                      battle_roles="lorasia:item(1.3)"))

    text = bf.format_battle_review_tooltip(rec.active(), in_battle=True)
    assert text.startswith("今回の戦闘")
    assert "T1" in text and "T2" in text
    assert "撃破 0.8T / 崩壊 4.5T" in text
    assert "通常速攻" in text and "省資源" in text
    assert "ロ:攻3.0" in text


def test_戦闘後のツールチップは直前戦闘になる():
    rec = BattleReviewRecorder()
    rec.observe(_game(seq=1, turn=1, battle_balance="even"))
    rec.observe(_game(seq=1, in_battle=False, turn=None, decisions=[]))
    rec.set_result("勝利")

    text = bf.format_battle_review_tooltip(rec.active(), in_battle=False)
    assert "直前の戦闘（勝利 / 1ターン）" in text


def test_ツールチップの先頭に画面の4行が入る():
    """⚠ 2026-08-11 の依頼者「戦況の行が切れて続きが見えない」への備え。

    ★4行化で短くはなりましたが、狭い窓では今後も切れます。
      **切れた行の全文をここで読めること**を守ります。
    """
    rows = ["優勢・短期", "撃破 0.5T / 崩壊 4.2T", "戦術 省資源 5.5/+1.5",
            "役割 ロ:攻3.0"]
    text = bf.format_battle_review_tooltip(None, True, summary_rows=rows)
    for row in rows:
        assert row in text


def test_記録が無くてもツールチップが壊れない():
    text = bf.format_battle_review_tooltip(None, True)
    assert "まだ記録がありません" in text
    assert "見逃す" in text, "⚠ 取りこぼしうることを黙らない"


# =====================================================================
# ★ 画面との配線（⚠ 作っただけで呼んでいなければ意味がない）
# =====================================================================

def test_画面が4行とレビューを実際に使っている():
    """⚠⚠ 「書いてある」だけの検査にしないための最低限の配線確認。

    ★挙動そのものは `tests/test_reasoning_view.py` が実物の窓で見ます。
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "retroux" / "ui"
              / "main_window.py").read_bytes().decode("utf-8")
    assert "self.vm.assessment_rows()" in source
    assert "self.vm.battle_review_tooltip()" in source
    # ★履歴が変わったらツールチップも作り直すこと（指示 §20）
    assert "self.vm.battle_review_revision()" in source

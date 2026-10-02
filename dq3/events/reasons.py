"""止まった理由 → 人の言葉（RX3-0154 / 2026-09-10）。★表はここ 1 か所。

⚠⚠ **表に無い理由は推測しません。** ★`action_log.humanize_reason()` が
「うまくいきませんでした」に落とし、⚠ 内部の語（`screen_frozen`）は `detail` へ回します。

★もとは `ui/auto_watch.py` にありました。⚠ Event の formatter からも引くので、
UI に依存しない場所へ移しています（★`auto_watch` は再輸出するだけ）。
"""
from __future__ import annotations

#: ★自動戦闘が止まった理由（⚠ `auto_v0.lua` の `stop(...)` と揃える）
BATTLE = {
    "ppu_unavailable": "画面が読めません",
    "spell_not_found": "呪文が見つかりません",
    "spell_cursor_not_blinking": "カーソルが動きません",
    "spell_cursor_stuck": "カーソルが動きません",
    "target_not_shown": "相手を選べません",
    "target_unreachable": "相手まで届きません",
    "item_not_found": "道具が見つかりません",
    # ⚠ RX3-0233: 「画面が変わりません」は実際と違った（★点滅して入力を待っていた / 操作が噛み合わなかった）
    "screen_frozen": "操作がかみ合わなくなりました",
    "cursor_not_found": "カーソルが見つかりません",
    "actor_unknown": "誰の番か分かりません",
    "command_missing": "コマンドが見つかりません",
    # ★賢者の「呪文の系統を選ぶ窓」（RX3-0293 / 2026-09-18）
    "spell_family_unknown": "呪文の系統が分かりません",
    "spell_family_stuck": "呪文の系統を選べません",
    "spell_family_cursor_not_blinking": "カーソルが動きません",
}

#: ★まんたんが止まった理由（⚠ `mantan_v0.lua` の `stop(...)` と揃える）
MANTAN = {
    "ppu_unavailable": "画面が読めません",
    "healer_missing": "回復できる人がいません",
    "window_will_not_close": "窓を閉じられません",
    "could_not_reset": "窓を閉じられません",
    "menu_not_opened": "メニューが開きません",
    "spell_command_missing": "じゅもん が見つかりません",
    "cursor_not_blinking": "カーソルが動きません",
    "cursor_stuck": "カーソルが動きません",
    "spell_not_found": "呪文が見つかりません",
    "spell_not_first": "じゅもん を選べません",
    # ★まんたん v1（RX3-0163 / 2026-09-12）: 選んだ呪文の名前が無い / 頭が同じ別の呪文の行だった
    "spell_tiles_missing": "呪文の名前が分かりません",
    "spell_label_mismatch": "呪文を選び違えそうなので止めました",
    "healer_name_missing": "回復する人を選べません",
    # ★賢者の「呪文の系統を選ぶ窓」（RX3-0293 / 2026-09-18）
    "spell_family_unknown": "呪文の系統が分かりません",
    "target_name_missing": "相手を選べません",
    "target_not_offered": "相手を選べません",
    "no_effect": "回復できませんでした",
    "did_not_return": "元の画面へ戻れません",
    # ★RX3-0174: 道具（やくそう / どくけしそう）。★`item:<理由>` の形で来る（⚠ 後ろは記録の材料）
    "item": "道具を使えませんでした",
}

#: ★自動移動が止まった理由（⚠ `ui/town_bar.NAV_TEXT` と**同じ語**を使う）
NAVIGATION = {
    "path_blocked": "道がふさがっています",
    "path_deviation": "経路を見失いました",
    "face_moved": "相手が動きました",
    "skip_unreachable_now": "目的地へ到達できません",
    "unreachable_now": "目的地へ到達できません",
    "needs_key": "鍵が要ります",
    "no_conversation": "会話になりませんでした",
    "command_failed": "頼めませんでした",
    "too_long": "時間がかかりすぎました",
    "window_will_not_close": "会話の窓が閉じませんでした",
    # ⚠⚠ RX3-0194: **すぐ旅立つかを尋ねる窓**の窓を開けたまま止めた（★B = いいえ はゲームが終わる）
    "depart_question_unanswered": "「はい」で答えてください",
}

#: ★domain → 表（⚠ formatter はこれだけを見る）
BY_DOMAIN = {"battle": BATTLE, "mantan": MANTAN, "navigation": NAVIGATION}

#: ★Auto を切って人へ返した終わり（RX3-0225 / RX3-0233）。⚠ `auto_v0.lua` の `finish(why .. "（ここから手で戦う）", "DANGER")`
HANDBACK_MARK = "手で戦う"
#: ★返した理由（⚠ `battle_speed.lua` の WHY_* の語 / 部分一致 / 上から順）
HANDBACK = (
    ("窓の色 オレンジ", "倒れている仲間がいる"),
    ("窓の色 緑", "HPが1/4を切った仲間がいる"),
    ("劣勢", "戦況が劣勢になった"),
)


def is_handback(why) -> bool:
    """★勝ったのではなく、人へ返した終わりか（RX3-0233）。"""
    return HANDBACK_MARK in str(why or "")


def handback_text(why) -> str:
    """★返した理由の人の言葉（⚠ 表に無ければ空 / 推測しない）。"""
    text = str(why or "")
    return next((ui for key, ui in HANDBACK if key in text), "")


__all__ = ["BATTLE", "MANTAN", "NAVIGATION", "BY_DOMAIN", "HANDBACK", "HANDBACK_MARK",
           "is_handback", "handback_text"]

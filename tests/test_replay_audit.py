"""AI判断と実入力の突き合わせ（2026-08-05 / Test Phase C）。

指示書 §5.1:

    > AI内部の判断と、実際のゲーム上で行われた操作が一致することを検証する。

★★ **検出器そのものを試します。** ★★
  ⚠⚠ 「一致 15 件 / 不一致 0 件」は、**検出器が甘いだけ**かもしれません。
    わざと食い違わせた記録を食わせて、★鳴ることを確かめます。

## ⚠⚠ キー名では判定できないと分かったこと（記録）

`on_input_decided` が渡す `source` は **"bridge" だけ**で、
「回復のために押した」のか「道具のために押した」のかが**区別できません**。
押したキーは `A` の連打として見えます。

→ **効果で照合します**（そのほうが本質的でもあります）:
  「ホイミと言ったなら、HP が増えて MP が減っているはず」。
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from research.probes.reusable import replay_audit as audit

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RECORDER = PROJECT_ROOT / "scripts" / "replay_check.lua"


def _turn(actor, action, before, after):
    return {"kind": "turn", "battle": 1, "turn": 1,
            "actor": actor, "action": action, "reason": "",
            "pressed": "bridge:A", "before": before, "after": after}


# --- ★★ 一致を正しく数える -----------------------------------------------

def test_回復が効いていれば一致():
    got = audit.judge(_turn(
        "samaltria", "ホイミ（回復呪文）",
        {"lorasia": "60/142 hp 0 mp", "samaltria": "110/113 hp 80 mp"},
        {"lorasia": "92/142 hp 0 mp", "samaltria": "110/113 hp 77 mp"}))
    assert got[0] == "一致", got


def test_たたかうでMPが減っていなければ一致():
    got = audit.judge(_turn(
        "lorasia", "たたかう",
        {"lorasia": "140/142 hp 0 mp"}, {"lorasia": "120/142 hp 0 mp"}))
    assert got[0] == "一致", got


# --- ★★★ 検出器が本当に鳴るか（★ここが肝）------------------------------

def test_回復と言ったのにMPが減っていなければ不一致():
    """⚠⚠ **これが「呪文を唱えたつもりで唱えていない」形**。

    ★HP は別の理由（道具・敵の行動）でも増えるので、
      **MP が減ったか**まで見ないと確かめたことになりません。
    """
    got = audit.judge(_turn(
        "samaltria", "ホイミ（回復呪文）",
        {"lorasia": "60/142 hp 0 mp", "samaltria": "110/113 hp 80 mp"},
        {"lorasia": "92/142 hp 0 mp", "samaltria": "110/113 hp 80 mp"}))
    assert got[0] == "不一致", got
    assert "MP が減っていない" in got[1]


def test_たたかうと言ったのにMPが減っていたら不一致():
    """⚠⚠ **「たたかう」のはずが呪文を唱えている**形。

    ★指示書 §5.1 の「コマンド階層の誤認」がこれに当たります。
    """
    got = audit.judge(_turn(
        "samaltria", "たたかう",
        {"samaltria": "110/113 hp 80 mp"},
        {"samaltria": "110/113 hp 75 mp"}))
    assert got[0] == "不一致", got
    assert "MP が 5 減った" in got[1]


def test_道具と言ったのにMPが減っていたら不一致():
    """★道具は MP を使いません（杖も盾も）。"""
    got = audit.judge(_turn(
        "samaltria", "どうぐ: いかづちのつえ",
        {"samaltria": "110/113 hp 80 mp"},
        {"samaltria": "110/113 hp 76 mp"}))
    assert got[0] == "不一致", got


# --- ⚠⚠ 判定できないものを「一致」にしない -------------------------------

def test_HPが増えていなければ判定不能():
    """⚠ 戦闘が先に終わった場合と区別できません。

    ★★ **「一致」に混ぜてはいけません。** 混ぜると
      「全部一致しました」が何も意味しなくなります。
    """
    got = audit.judge(_turn(
        "samaltria", "ホイミ（回復呪文）",
        {"lorasia": "60/142 hp 0 mp", "samaltria": "110/113 hp 80 mp"},
        {"lorasia": "60/142 hp 0 mp", "samaltria": "110/113 hp 77 mp"}))
    assert got[0] == "判定不能", got


def test_状態が取れていなければ判定不能():
    got = audit.judge(_turn("samaltria", "たたかう", {}, {}))
    assert got[0] == "判定不能", got


def test_知らない行動は判定不能():
    got = audit.judge(_turn(
        "lorasia", "なにか知らない行動",
        {"lorasia": "140/142 hp 0 mp"}, {"lorasia": "140/142 hp 0 mp"}))
    assert got[0] == "判定不能", got


# --- ⚠ 壊れた記録を黙って捨てない ----------------------------------------

def test_壊れた行を数える(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes('{"kind":"turn"}\n{こわれている\n'.encode("utf-8"))
    got = audit.audit(path)
    assert len(got["broken"]) == 1, "⚠ 壊れた行を捨てています"


def test_記録が無ければ合格にしない(tmp_path, capsys):
    """★★ **「採れなかった」を合格に見せない**（playbook #43）。"""
    path = tmp_path / "s.jsonl"
    path.write_bytes(b'{"kind":"start"}\n')
    assert audit.main(["--session", str(path)]) == 1
    assert "何も確かめていません" in capsys.readouterr().out


def test_不一致があれば失敗を返す(tmp_path):
    path = tmp_path / "s.jsonl"
    row = _turn("samaltria", "たたかう",
                {"samaltria": "110/113 hp 80 mp"},
                {"samaltria": "110/113 hp 75 mp"})
    path.write_bytes((json.dumps(row, ensure_ascii=False) + "\n")
                     .encode("utf-8"))
    assert audit.main(["--session", str(path)]) == 1


# --- ★★ Test Phase D: 戦闘終了までの再生 --------------------------------
#
# 指示書 §15 Test Phase D の完了条件:
#   ・戦闘終了まで自動進行できる
#   ・**最大ターンと同一状態反復を検出できる**
#   ・**戦闘終了後の誤入力を検出できる**
#
# ⚠⚠ `showing_victory` を試すテストは**1つもありませんでした**（棚卸し）。


def _battle(**kw):
    row = {"kind": "battle_end", "battle": 1, "turns": 5,
           "victory_seen": True, "after_victory_keys": 0, "same_state": 0}
    row.update(kw)
    return row


def test_ふつうの戦闘は何も言わない():
    assert audit.judge_battle(_battle()) == []


def test_長すぎる戦闘に気づく():
    """★§4.3「最大ターンを超える停滞を検出する」。"""
    got = audit.judge_battle(_battle(turns=99))
    assert got and got[0][0] == "最大ターン超過", got


def test_同じ状態の反復に気づく():
    """★§4.3「同じ状態・同じ判断が無限に反復しない」。

    ⚠ HP も MP も動かないまま進むのは、★誰も有効な手を打てていない印です。
    """
    got = audit.judge_battle(_battle(same_state=6))
    assert got and got[0][0] == "同一状態の反復", got


def test_戦闘終了後の入力に気づく():
    """★★★ **これが `showing_victory` の 0 件を埋めます**（§10 IT-008）。

    ⚠⚠ 勝利メッセージ中に押すと、フィールドへ戻った直後に
      コマンドメニューが開き、★**歩けなくなって戦闘が起きなくなります**
      （2026-08-05 に実際に踏み、依頼者から「ずっとメニューでたまま」と
      指摘されました）。
    """
    got = audit.judge_battle(_battle(after_victory_keys=3))
    assert got and got[0][0] == "戦闘後にフィールドのメニューが開いた", got
    assert "3 回押した" in got[0][1]


def test_誰が押したかを出す():
    """★★ **「開いた」だけでは直せません**（2026-08-06 に足した）。

    ⚠⚠ 22戦中3戦で開いたと分かっても、開けた相手が分からないと
      直す場所が決まりません:

        こちらの A が漏れた     -> bridge の入力側を直す
        モンキーの歩きが開けた   -> ハーネス側で、実害は無い

    ⚠ 直し方が正反対なので、**推測で決めない**。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1,
        after_victory_by_source={"auto": 40, "monkey": 5}))
    assert got, got
    detail = got[0][1]
    assert "auto 40回" in detail, detail
    assert "monkey 5回" in detail, detail


def test_開けた犯人を出す():
    """★★★ **これが②の核心**（2026-08-07）。

    ⚠⚠ 「押した人」は**閉じようとした人**であって、開けた人ではありません。
      45回押しても閉じない＝開きっぱなし、までは分かっても、
      ★**何が開けたか**が分からないと直せません。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1,
        menu_open_why={"frames_after_battle": 2, "in_battle": 0,
                       "last_pressed": "bridge:A bridge:A"}))
    detail = got[0][1]
    assert "戦闘終了の2フレーム後" in detail, detail
    assert "直前の入力 bridge:A" in detail, detail


def test_後始末が降りた理由を出す():
    """★★★ **これが②の本題**（2026-08-07）。

    ⚠⚠ `bridge` には「B を押して閉じる」仕組みが**既にあります**。
      ところが実機の45回中**1回も動きませんでした**（押したのは全部
      ハーネス側）。★「B を押せば早い」は正しいのに、**その B が
      出ていない**のが本題でした。

    ⚠ 降りる条件は4つ。★どれかを推測で決めず、全部見て言います。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1,
        menu_open_why={"frames_after_battle": 5, "in_battle": 0,
                       "last_pressed": "request:A",
                       "cleanup_left": 600, "suppressed": 0,
                       "bridge_frames_since_battle": 120,
                       "detect_frames": 45}))
    detail = got[0][1]
    assert "人が開けたと判断" in detail, detail
    assert "120 フレーム > しきい値 45" in detail, detail


def test_閉じたなら異常にしない():
    """★★★ **2026-08-07 の訂正。ここは2回まちがえました。**

    ⚠ 「B では閉じない」と読んだ  -> ★B で閉じます（7回目に閉じた）
    ⚠ 「A で閉じる位置がある」    -> ★潜っただけを閉じたと数えていた

    ★実測すると、メニューは 109〜121フレーム（約2秒）で**閉じて**
      いました。⚠ 「45回押した」は「45回失敗した」ではなく
      **「閉じるまでに45回押した」**でした。

    → 異常とするのは「**閉じられなかった**」ときだけ。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1, menu_frames=50,
        menu_still_open=0))
    assert got == [], got


def test_閉じたが遅いことは言う():
    """⚠ 閉じてさえいれば不具合ではありませんが、★人には見えます。

    ⚠⚠ **しきい値を実測より上に置かない。** ★そうすると、いまの遅さが
      「異常なし」になって、直す機会を失います。
    """
    assert audit.MENU_SLOW_FRAMES < 109, (
        "⚠⚠ しきい値が実測(109フレーム)より上です。★今の遅さを見逃します")
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1, menu_frames=109,
        menu_still_open=0))
    assert got and got[0][0] == "戦闘後のメニューを閉じるのに時間がかかった", got
    assert "★閉じてはいます" in got[0][1], got


def test_閉じなかったときは今までどおり異常にする():
    """★★ **本物の不具合はこちら**（依頼者の「ずっとメニューでたまま」）。"""
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1, menu_frames=5000,
        menu_still_open=1))
    assert got and got[0][0] == "戦闘後にフィールドのメニューが開いた", got


def test_古い記録では今までどおり判定する():
    """⚠ `menu_still_open` が無い記録を「閉じた」ことにしない。

    ★分からないものを都合よく解釈すると、⚠ 過去の異常が消えます。
    """
    got = audit.judge_battle(_battle(after_victory_keys=45, menu_opened=1))
    assert got and got[0][0] == "戦闘後にフィールドのメニューが開いた", got


def test_Bが届いているのに閉じないことを言う():
    """★★★ **これが次の一手を決めます**（2026-08-07）。

    ⚠⚠ 後始末が降りる問題を直したあと、`bridge` が 52〜60回押しても
      メニューが閉じませんでした。★`$002F` は**ゲームが実際に読んだ
      入力**なので、ここに B が立っていれば押し方の問題ではありません。
      → **B では閉じない作り**（「とじる」を選ぶ必要）という話になります。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=55, menu_opened=1,
        menu_frames=900, menu_b_reached=450, menu_cursor_spots=1))
    detail = got[0][1]
    assert "届いているのに閉じていません" in detail, detail
    assert "カーソルは 1 か所" in detail, detail


def test_Bが届いていない場合と区別する():
    """⚠ 直し方が正反対です。★届いていないなら押し方を直す。"""
    got = audit.judge_battle(_battle(
        after_victory_keys=55, menu_opened=1,
        menu_frames=900, menu_b_reached=0))
    assert "B がゲームに届いていません" in got[0][1], got


def test_古い記録では閉じない理由を書かない():
    """★推測で埋めない。"""
    got = audit.judge_battle(_battle(after_victory_keys=3, menu_opened=1))
    assert "B が届いた" not in got[0][1], got


def test_期限切れと抑止も見分ける():
    got = audit.judge_battle(_battle(
        after_victory_keys=3, menu_opened=1,
        menu_open_why={"frames_after_battle": 2, "in_battle": 0,
                       "last_pressed": "bridge:A", "cleanup_left": 0,
                       "suppressed": 1, "bridge_frames_since_battle": 2,
                       "detect_frames": 45}))
    detail = got[0][1]
    assert "期限切れ" in detail, detail
    assert "抑止フラグ" in detail, detail


def test_理由が説明できないときは説明できないと言う():
    """⚠⚠ **ここを「異常なし」にすると、追うのをやめてしまいます。**

    ★降りる条件が全部そろっていないのに動いていないなら、
      それは**まだ知らない原因**です。
    """
    got = audit.judge_battle(_battle(
        after_victory_keys=45, menu_opened=1,
        menu_open_why={"frames_after_battle": 5, "in_battle": 0,
                       "last_pressed": "request:A", "cleanup_left": 600,
                       "suppressed": 0, "bridge_frames_since_battle": 5,
                       "detect_frames": 45}))
    assert "説明できません" in got[0][1], got


def test_古い記録では後始末の理由を書かない():
    """★推測で埋めない（0 と不明を混ぜない）。"""
    got = audit.judge_battle(_battle(
        after_victory_keys=3, menu_opened=1,
        menu_open_why={"frames_after_battle": 2, "in_battle": 0,
                       "last_pressed": "bridge:A"}))
    assert "後始末が降りた理由" not in got[0][1], got
    assert "説明できません" not in got[0][1], got


def test_戦闘中に開いた場合を区別する():
    """⚠ 戦闘中に開いたなら、原因はまったく別のところです。"""
    got = audit.judge_battle(_battle(
        after_victory_keys=1, menu_opened=1,
        menu_open_why={"frames_after_battle": -1, "in_battle": 1,
                       "last_pressed": ""}))
    assert "開いたのは 戦闘中" in got[0][1], got
    # ⚠ 入力が無かったなら「無かった」と書く（★空欄にしない）
    assert "直前の入力なし" in got[0][1], got


def test_戦闘の後の行も検査する():
    """★★ **1つずれていたのを直した**（2026-08-07）。

    ⚠⚠ メニューが開くのは戦闘が終わった**後**です。ところが集計は
      `battle_end` の行でリセットしていたため、45回は**次の戦闘の行**に
      載っていました。★「5戦目」と報告していたものは、実は
      **4戦目の後**です。

    ⚠ `after_battle` という別の行に分け、どの戦闘の後かを明示します。
    """
    rows = [{"kind": "battle_start", "battle": 1},
            {"kind": "battle_end", "battle": 1, "turns": 3,
             "victory_seen": True, "same_state": 0},
            {"kind": "after_battle", "battle": 1, "after_victory_keys": 45,
             "menu_opened": 1}]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        path = pathlib.Path(fh.name)
    try:
        got = audit.audit(path)
        issues = got["battle_issues"]
        assert len(issues) == 1, issues
        row, rule, _why = issues[0]
        assert rule == "戦闘後にフィールドのメニューが開いた"
        # ★★ **どの戦闘の後か**が正しいこと
        assert row["battle"] == 1, row
        assert row["kind"] == "after_battle", row
    finally:
        path.unlink(missing_ok=True)


def test_戦闘終了の行では戦闘後の集計を見ない():
    """⚠⚠ **同じ数字を2回数えない。**

    ★`battle_end` に `after_victory_keys` が残っていると、
      `after_battle` と合わせて**2件に見えます**。
    """
    source = RECORDER.read_bytes().decode("utf-8")
    end = source.index('kind = "battle_end"')
    tail = source[end:end + 400]
    assert "after_victory_keys" not in tail, (
        "⚠ battle_end の行に戦闘後の集計が残っています")


def test_押した回数と開いた回数を分ける():
    """⚠⚠ **45回押した ≠ 45回開いた**。

    ★開いたのが1回なら「開きっぱなし」、45回なら「開け閉めの繰り返し」で、
      直す場所がまったく違います。
    """
    got = audit.judge_battle(_battle(after_victory_keys=45, menu_opened=1))
    assert "開いた回数 1" in got[0][1], got


def test_誰が押したか分からないときはそう書く():
    """★★ **推測で埋めない**（0 と不明を混ぜない）。

    ⚠ 古い記録には `after_victory_by_source` がありません。
      そこを「誰も押していない」ことにすると、★**嘘の証拠**になります。
    """
    got = audit.judge_battle(_battle(after_victory_keys=3))
    assert "記録されていません" in got[0][1], got
    # ⚠ 分からないのに人の名前を書いていないこと
    assert "回" in got[0][1] and "押した人 " not in got[0][1], got


def test_勝利メッセージ中のAを異常にしない():
    """⚠⚠ **最初の検出器が厳しすぎた**（2026-08-05 / 訂正の記録）。

    「勝利メッセージ中の入力」を数えたら **22戦すべて**が引っかかりました。
    ★A を押すのはメッセージを送るために**必要**で、bridge が意図的に
      押しています。⚠ 直しようのないものを「異常22件」と報告する
      ところでした。

    → 数えるのは「**フィールドのメニューが開いた状態**で押した」ときだけ。
    """
    text = (PROJECT_ROOT / "scripts" / "replay_check.lua").read_bytes(
        ).decode("utf-8")
    # ★記録側が「メニューが開いているか」で数えていること
    assert "field_command" in text
    hook = text.index("bridge.on_input_decided = function")
    # ⚠ 宣言の書き方が変わっても壊れないように、名前だけで探す。
    #   ★2026-08-07 に `local MENU, CUR_X, CUR_Y, INPUT = ...` へ増えた。
    assert text.index("local MENU") < hook, (
        "⚠ MENU の定義がフックより後ろです（nil に見えて落ちます）")


def test_戦闘の異常があれば失敗を返す(tmp_path):
    path = tmp_path / "s.jsonl"
    rows = [_turn("lorasia", "たたかう",
                  {"lorasia": "140/142 hp 0 mp"},
                  {"lorasia": "120/142 hp 0 mp"}),
            _battle(after_victory_keys=2)]
    path.write_bytes("\n".join(
        json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8"))
    assert audit.main(["--session", str(path)]) == 1


def test_勝利メッセージを見たことを数える(tmp_path):
    """★「戦闘終了まで進めた」ことの証拠になります。"""
    path = tmp_path / "s.jsonl"
    rows = [_battle(victory_seen=True), _battle(victory_seen=False)]
    path.write_bytes("\n".join(
        json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8"))
    got = audit.audit(path)
    assert got["victories"] == 1
    assert len(got["ends"]) == 2


def test_記録側が戦闘終了を追っている():
    """⚠ 記録が無ければ、判定しようがありません。"""
    text = RECORDER.read_bytes().decode("utf-8")
    assert "showing_victory" in text, "★勝利メッセージを見ていない"
    assert "battle_end" in text
    assert "after_victory_keys" in text
    assert "same_state" in text


# --- ★ 記録する側 --------------------------------------------------------

def test_記録は判定しない():
    """★★ **記録（Lua）と判定（Python）を分ける。**

    ⚠ Lua 側に判定を書くと、直すたびに**実機が要ります**。
    """
    text = RECORDER.read_bytes().decode("utf-8")
    # ⚠ `assert(loadfile(...))` は Lua の標準関数で、判定ではありません。
    #   ★「合否を決める言葉」だけを見ます。
    for banned in ("不一致", "一致しました", "★NG", "os.exit(1)"):
        assert banned not in text, f"⚠ 記録側で判定しています: {banned}"


def test_実際に押したキーを記録している():
    """★AI が何を選んだかだけでなく、**何を押したか**。"""
    text = RECORDER.read_bytes().decode("utf-8")
    assert "on_input_decided" in text
    assert "pressed" in text


def test_フックが使う変数はフックより前で宣言する():
    """★★★ **実機で毎フレーム落ちた**（2026-08-05 / 依頼者が発見）。

        attempt to perform arithmetic on global 'after_victory_keys'

    ⚠⚠ Lua の `local` は**それ以降**でしか見えません。フックより後に
      宣言すると、フックからは**グローバルの nil** に見えます。

    ★`luacheck` は通ります（構文は正しい）。
      ⚠ 「呼ばないと分からない Lua の誤り」の典型です。
      依頼者がエラーダイアログを見るまで、★記録が 8 行で止まっている
      ことにしか気づけませんでした。
    """
    text = RECORDER.read_bytes().decode("utf-8")
    hook = text.index("bridge.on_input_decided = function")
    for name in ("after_victory_keys", "after_victory_by_source",
                 "victory_seen", "battle_turns", "same_state"):
        declared = text.find(f"local {name}")
        assert declared >= 0, f"⚠ {name} を local で宣言していません"
        assert declared < hook, (
            f"⚠⚠ {name} の宣言がフックより後ろです。"
            "★フックからは nil に見えて実機で落ちます")


def test_ターン前後の状態を記録している():
    """★指示書 §5.2「RAM状態を再取得し、実際の結果とAI予測を照合」。"""
    text = RECORDER.read_bytes().decode("utf-8")
    assert "before" in text and "after" in text
    assert "snapshot" in text

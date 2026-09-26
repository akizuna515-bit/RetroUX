"""ユーザー向けの行動履歴 ― Action Summary Log の土台（RX3-0109 / 2026-09-07）。

## ★依頼者が挙げた確認事項（§5）

```text
★完了時に必ず 1 summary だけ生成される
★同じ処理で 2 重出力されない
★中断時も summary が出る
★部分成功を表現できる
★Technical Log とは独立している
⚠⚠ UI へ渡す文字列に raw dict / hex / traceback 等が混ざらない
```
"""
from __future__ import annotations

import pytest

from dq3 import action_log as AL


@pytest.fixture
def log():
    clock = [1_000.0]
    got = AL.ActionLog(clock=lambda: clock[0])
    got.tick = clock                       # ★時間を進めたいとき用
    return got


# ----------------------------------------------------------------------
# ★1 回に 1 行だけ
# ----------------------------------------------------------------------
def test_完了で1行だけ出る(log):
    run = log.begin("hearing")
    got = run.completed("9人と会話")
    assert got is not None
    assert len(log.rows) == 1
    assert got.line() == "[聞き込み] 完了：9人と会話"


def test_二度終わらせても2行にならない(log):
    """⚠⚠ 終わり方が何通りもあるので、★ここを緩めると必ず 2 行出ます。"""
    run = log.begin("move")
    assert run.completed("道具屋へ到着 / 37歩") is not None
    assert run.failed("目的地へ到達できません") is None
    assert run.cancelled() is None
    assert len(log.rows) == 1


def test_別の回なら別の行(log):
    log.begin("move").completed("道具屋へ到着 / 12歩")
    log.begin("move").completed("宿屋へ到着 / 20歩")
    assert len(log.rows) == 2


# ----------------------------------------------------------------------
# ★終わり方
# ----------------------------------------------------------------------
def test_中断でも1行出る(log):
    got = log.begin("move").failed("目的地へ到達できません / 18歩")
    assert got.line() == "[自動移動] 中断：目的地へ到達できません / 18歩"


def test_ユーザー操作の停止は区別される(log):
    got = log.begin("battle").cancelled("ユーザー操作 / 3戦3勝")
    assert got.line() == "[自動戦闘] 停止：ユーザー操作 / 3戦3勝"


def test_部分成功を表せる(log):
    """★`PARTIAL` も人には「完了」。⚠ 未完の件数は本文で言う（依頼者の例のまま）。"""
    got = log.begin("hearing").partial("7人と会話 / 未完3人（扉2・到達不能1）")
    assert got.status == AL.PARTIAL
    assert got.line() == "[聞き込み] 完了：7人と会話 / 未完3人（扉2・到達不能1）"


@pytest.mark.parametrize("status", AL.STATUSES)
def test_どの終了状態にも日本語がある(status):
    assert AL.STATUS_LABELS[status] in ("完了", "中断", "停止")


# ----------------------------------------------------------------------
# ⚠⚠ Technical Log と混ぜない
# ----------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    "npc_id=4 reason=path_deviation x=18 y=22",
    "止まりました: reason=path_blocked",
    "{'npc_id': 4, 'reason': 'path_deviation'}",
    "アドレス 0x0644 が読めません",
    'Traceback (most recent call last):  File "x.py", line 3, in <module>',
    "<dq3.ui.town_bar.TownNavController object at 0x0000029E>",
])
def test_生の値はユーザー向けに出さない(log, bad):
    got = log.begin("hearing").failed(bad)
    assert AL.is_user_safe(got.message), got.message
    assert bad not in got.line()
    # ★捨てない（⚠ Technical 側には残す）
    assert got.detail["raw_message"] == bad
    assert log.scrubbed == 1


@pytest.mark.parametrize("ok", [
    "9人と会話 / 未完2人（到達不能1・会話失敗1）",
    "道具屋へ到着 / 42歩 / 12秒",
    "8戦8勝 / 31ターン / HP回復2回 / MP消費18",
    "やくそう×4、どくけしそう×2 / 72G",
    "3人回復 / HP +126 / MP -14",
    "レーベの道具屋へ到着 / 31歩",
])
def test_依頼者の例はそのまま通る(log, ok):
    """⚠ 検出が**厳しすぎない**ことも見る（★鳴りすぎも壊れ方）。"""
    assert AL.is_user_safe(ok), ok
    got = log.begin("move").completed(ok)
    assert got.message == ok and log.scrubbed == 0


def test_詳しい値はdetailに残る(log):
    got = log.begin("hearing").partial("7人と会話 / 未完3人",
                                       skipped=[{"npc_id": 4, "reason": "path_deviation"}])
    assert got.detail["skipped"][0]["npc_id"] == 4
    assert "npc_id" not in got.line()


# ----------------------------------------------------------------------
# ★見せ方
# ----------------------------------------------------------------------
def test_時刻つきの行(log):
    got = log.begin("move").completed("道具屋へ到着 / 37歩")
    assert got.stamped().endswith("[自動移動] 完了：道具屋へ到着 / 37歩")
    assert len(got.stamped().split(" ")[0]) == 5           # ★HH:MM


def test_知らないActionでも落ちない(log):
    got = log.begin("teleport").completed("どこかへ")
    assert got.line() == "[teleport] 完了：どこかへ"


def test_本文が空でも形になる(log):
    assert log.begin("battle").completed("").line() == "[自動戦闘] 完了"


# ----------------------------------------------------------------------
# ★引きに来る側（⚠ UI は subscribe でも since でも取れる）
# ----------------------------------------------------------------------
def test_増えたぶんだけ取れる(log):
    seen = 0
    log.begin("move").completed("a")
    rows, seen = log.since(seen)
    assert [r.message for r in rows] == ["a"] and seen == 1
    log.begin("move").completed("b")
    rows, seen = log.since(seen)
    assert [r.message for r in rows] == ["b"] and seen == 2
    rows, seen = log.since(seen)
    assert rows == []


def test_上限を超えても新しい行が届き続ける(log):
    """⚠⚠ **500 件で止まっていました**（RX3-0429 / P-3）。

    ```text
    ★昔は `since()` が `len(rows)` を番号に使っていた
    ⚠ `rows` は上限で頭打ち → `seen` も止まる → `rows[seen:]` が永久に空
    ```
    ★保持する件数（`limit`）と、⚠ どこまで渡したか（`total`）は**別**です。
    """
    log.limit = 500
    seen, delivered, at = 0, 0, {}
    for i in range(1, 621):
        log.record("walk", "ok", "%d 歩目" % i)
        rows, seen = log.since(seen)
        delivered += len(rows)
        if i in (499, 500, 501, 600, 620):
            at[i] = len(rows)

    assert at == {499: 1, 500: 1, 501: 1, 600: 1, 620: 1}, (
        "⚠⚠ 上限を超えた所で新しい行が止まりました: %s" % at)
    assert delivered == 620, "⚠⚠ %d 件しか UI へ流れていません（★620 件記録した）" % delivered
    assert len(log.rows) == 500, "⚠ 保持は上限どおり 500 件のはず"
    assert log.rows[-1].message == "620 歩目"


def test_追いつけないほど遅れても流れは止まらない(log):
    """⚠ 上限より遅れたら**捨てたぶんは戻らない**が、★その先は届くこと。"""
    log.limit = 10
    for i in range(1, 101):
        log.record("walk", "ok", "%d" % i)
    rows, seen = log.since(0)               # ★0 件目から（⚠ 90 件はもう無い）
    assert [r.message for r in rows] == [str(i) for i in range(91, 101)]
    assert seen == 100
    log.record("walk", "ok", "101")
    rows, seen = log.since(seen)
    assert [r.message for r in rows] == ["101"] and seen == 101


def test_見る側が失敗しても履歴は残る(log):
    def boom(_summary):
        raise RuntimeError("⚠ 画面が壊れた")

    log.subscribe(boom)
    got = log.begin("move").completed("到着")
    assert got is not None and len(log.rows) == 1


def test_溜め込まない():
    log = AL.ActionLog(limit=3)
    for i in range(10):
        log.begin("move").completed("%d歩" % i)
    assert len(log.rows) == 3 and log.rows[0].message == "7歩"


def test_共有は1本(monkeypatch):
    AL.reset_shared()
    try:
        assert AL.shared() is AL.shared()
    finally:
        AL.reset_shared()

"""オートを止めた・人へ返した理由が右画面に残る（RX3-0233 / 2026-09-13）。

⚠⚠ 依頼者「save3 よくわからない理由で自動戦闘が中断」:
  右画面の速さの行は Auto が切れると消える（`speed_line`）ので、⚠ 止めた理由がどこにも出ていなかった。
  → ★「前回」の行（`last_battle_line`）に、止めた・人へ返した理由を次の戦闘まで残す。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.events import reasons as RS          # noqa: E402
from dq3.ui import auto_panel as AP           # noqa: E402


class _Row:
    def __init__(self, detail):
        self.detail = detail


def test_止めた戦闘は理由を出す():
    got = AP.last_battle_line([_Row({"result": "stopped", "reason": "screen_frozen"})])
    assert got == "前回 止めました：操作がかみ合わなくなりました（ここから手で操作）"


def test_知らない理由は推測しない():
    got = AP.last_battle_line([_Row({"result": "stopped", "reason": "まだ無い理由"})])
    assert got.startswith("前回 止めました：") and "まだ無い理由" not in got


def test_人へ返した戦闘は理由を出す():
    got = AP.last_battle_line([_Row({"result": "handed", "reason": "窓の色 緑（HP 1/4 未満）（ここから手で戦う）"})])
    assert got == "前回 手で戦う画面に戻しました：HPが1/4を切った仲間がいる"


def test_いちばん新しい戦闘だけ見る():
    rows = [_Row({"result": "stopped", "reason": "screen_frozen"}),
            _Row({"result": "win", "breakdown": {"attack": 2}, "rounds": 1, "actions": 2, "strategy": "leveling"})]
    assert "止めました" not in AP.last_battle_line(rows)


def test_人へ返した印は_Luaの終わり方と揃う():
    """★`auto_v0.lua` の `finish(why .. "（ここから手で戦う）", "DANGER")` と、battle_speed の WHY_* の語。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    auto = (root / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    speed = (root / "dq3" / "phase0" / "battle_speed.lua").read_text(encoding="utf-8")
    assert "（ここから手で戦う）" in auto and RS.HANDBACK_MARK in "（ここから手で戦う）"
    for key, _ui in RS.HANDBACK:
        assert key in speed, "⚠ battle_speed の理由の語が変わった: %s" % key


def test_膠着の見張りへ敵HPを渡している():
    """★RX3-0327 §11: `auto_v0` → `battle_speed.on_plan` に**敵 HP 合計**を渡す結線。

    ⚠⚠ 2026-09-21 の壊す実験で見つけた穴: 速さの足場は `F.on_plan` を**直に**呼ぶので、
      ★`auto_v0` が `enemy_hp` を渡すのをやめても**緑のまま**でした。
      → ⚠ 渡さないと、膠着の見張りは黙って何もしません（★止まらなくなる）。

    ★見張りそのものの挙動は `research/probes/active/dq3_battle_speed_test.lua` の
      「膠着」6 件が見ています（⚠ ここは結線だけ）。
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    auto = (root / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    code = [ln for ln in auto.splitlines() if not ln.lstrip().startswith("--")]
    assert any("enemy_hp = sit" in ln for ln in code), (
        "⚠⚠ `speed_plan` が敵 HP 合計を渡していない（★膠着の見張りが動かない）")

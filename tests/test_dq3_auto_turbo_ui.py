"""右画面の AUTO / TURBO ボタン（RX3-0169 → RX3-0237）— ★表示は「いま実際にどう動いているか」。

```text
MANUAL        AUTO OFF / TURBO OFF   通常操作・等速
MANUAL_TURBO  AUTO OFF / TURBO ON    手動操作・高速（★RX3-0237 で正式な状態に）
AUTO_NORMAL   AUTO ON  / TURBO OFF   自動戦闘・等速
AUTO_TURBO    AUTO ON  / TURBO ON    自動戦闘・高速
押せる        AUTO・TURBO とも戦闘の本体（ACTIVE）だけ
```

★状態の遷移そのもの（A / T / ボタン / 危険化 / 勝利）は Lua の足場が動かして見ています:
`dq3_battle_speed_test.lua` / `dq3_auto_ai_test.lua` / `dq3_dev_test.lua` §6（★仕様 §9 の順）。
⚠ 2026-09-11 の RX3-0169 は「Turbo は Auto 中だけ」だった（★依頼者の仕様 2026-09-13 で変えた）。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.ui import main_window as MW                                     # noqa: E402


@pytest.mark.parametrize(("raw", "state", "auto_on", "turbo_on", "auto_ok", "turbo_ok"), [
    ({"battle_phase": "NONE"}, "MANUAL", False, False, False, False),            # ★戦闘の外
    ({"battle_phase": "ACTIVE"}, "MANUAL", False, False, True, True),            # ★戦闘開始: TURBO も押せる
    ({"battle_phase": "ACTIVE", "auto_enabled": True}, "AUTO_NORMAL", True, False, True, True),
    ({"battle_phase": "ACTIVE", "auto_enabled": True, "turbo_enabled": True},
     "AUTO_TURBO", True, True, True, True),
    # ★AUTO OFF / TURBO ON（手動操作・高速）も正式な状態（RX3-0237 仕様 §4）
    ({"battle_phase": "ACTIVE", "auto_enabled": False, "turbo_enabled": True},
     "MANUAL_TURBO", False, True, True, True),
    # ★勝利の結果（RESULT）: AUTO も TURBO も OFF。★結果の文を送っていても押せない
    ({"battle_phase": "RESULT", "auto_enabled": False}, "MANUAL", False, False, False, False),
    ({"battle_phase": "ENTERING"}, "MANUAL", False, False, False, False),
    ({}, "MANUAL", False, False, False, False),                                  # ⚠ 届いていない
])
def test_表示と押せるかは実効の状態から(raw, state, auto_on, turbo_on, auto_ok, turbo_ok):
    got = MW.battle_buttons(raw)
    assert (got["state"], got["auto_on"], got["turbo_on"]) == (state, auto_on, turbo_on)
    assert (got["auto_enabled"], got["turbo_enabled"]) == (auto_ok, turbo_ok)


def test_ヒントは役割を短く言う():
    assert "AIに任せます" in MW.AUTO_TIP and "Turboも入ります" in MW.AUTO_TIP
    assert "手動に戻ります" in MW.AUTO_TIP and "Turboも切れます" in MW.AUTO_TIP
    assert "A キー" in MW.AUTO_TIP
    assert "速さだけ" in MW.TURBO_TIP and "Autoはそのまま" in MW.TURBO_TIP and "T キー" in MW.TURBO_TIP
    assert MW.TURBO_TIP_DISABLED.startswith("Turboは戦闘中に使えます。")
    for tip in (MW.AUTO_TIP, MW.TURBO_TIP):
        assert tip.count(chr(10)) <= 2, "⚠ ヒントが長すぎる（★2〜3 行まで）"


def test_ボタンに映す():
    """★★ 2026-09-20（RX3-0325）: ON は**色**ではなく `icon_button.is_on()` で見ます。

    ⚠⚠ 鍵も「A」「タ」から**役割**（`auto` / `turbo`）へ変えました。
      ★以前は表示の字が鍵で、⚠ 字を変えると `_apply_battle_buttons` が
      **例外も出さずに何もしなくなり**ました（★いちばん静かな壊れ方）。
    """
    from PySide6.QtWidgets import QApplication

    from dq3.ui import icon_button as IB

    app = QApplication.instance() or QApplication([])
    win = MW.Dq3MainWindow.__new__(MW.Dq3MainWindow)
    win._buttons = {"auto": IB.make("auto", "オート", MW.AUTO_TIP),
                    "turbo": IB.make("turbo", "ターボ", MW.TURBO_TIP)}
    auto, turbo = win._buttons["auto"], win._buttons["turbo"]

    win._apply_battle_buttons({"battle_phase": "NONE"})
    assert not auto.isEnabled() and not turbo.isEnabled()
    assert turbo.toolTip() == MW.TURBO_TIP_DISABLED

    win._apply_battle_buttons({"battle_phase": "ACTIVE"})
    assert auto.isEnabled() and turbo.isEnabled(), "⚠ 戦闘の本体なのに TURBO が押せない（★AUTO OFF でも押せる）"
    assert not IB.is_on(auto) and not IB.is_on(turbo)
    assert turbo.toolTip() == MW.TURBO_TIP

    win._apply_battle_buttons({"battle_phase": "ACTIVE", "auto_enabled": True})
    assert IB.is_on(auto) and not IB.is_on(turbo)

    win._apply_battle_buttons({"battle_phase": "ACTIVE", "auto_enabled": True,
                               "turbo_enabled": True})
    assert IB.is_on(auto) and IB.is_on(turbo)

    # ★AUTO OFF / TURBO ON（手動操作・高速）
    win._apply_battle_buttons({"battle_phase": "ACTIVE", "auto_enabled": False,
                               "turbo_enabled": True})
    assert not IB.is_on(auto) and IB.is_on(turbo)

    # ★勝利に入ったら両方 OFF 表示・押せない
    win._apply_battle_buttons({"battle_phase": "RESULT", "auto_enabled": False,
                               "turbo_enabled": False})
    assert not IB.is_on(auto) and not IB.is_on(turbo)
    assert not auto.isEnabled() and not turbo.isEnabled()
    assert app is not None


def test_押せないTurboを押しても頼みは送らない():
    """⚠ 押せない（disabled）ボタンは clicked を出さない（★Qt の決まり）を確かめる。"""
    from PySide6.QtWidgets import QApplication, QPushButton

    QApplication.instance() or QApplication([])
    sent = []
    button = QPushButton("タ")
    button.clicked.connect(lambda: sent.append("turbo"))
    button.setEnabled(False)
    button.click()
    assert sent == []
    button.setEnabled(True)
    button.click()
    assert sent == ["turbo"]


def test_新しいボタンや第三のモードを足していない():
    """★仕様 §7・§10: AUTO / TURBO の 2 概念だけ（⚠ 強制AUTO・AUTO TURBO などの別ボタンを作らない）。"""
    import pathlib

    src = (pathlib.Path(MW.__file__)).read_text(encoding="utf-8")
    for banned in ("強制AUTO", "強制高速"):
        assert banned not in src, banned

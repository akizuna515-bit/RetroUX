"""時間の表示のテスト（依頼者の要望 / MVP2 Phase 1）。

★「削減できた待ち時間」はこのプロジェクトの中心指標。
  31285.7 秒 のままでは、どれだけ効いているか実感できない。
"""

from __future__ import annotations

import pytest

from retroux.core.humanize import compact_duration, duration


@pytest.mark.parametrize("seconds,expected", [
    (0, "0.0秒"),               # ★0 を空欄にしない（壊れているのか0か区別できない）
    (45.24, "45.2秒"),
    (59.9, "59.9秒"),
    (60, "1分0秒"),
    (312, "5分12秒"),           # 分が出たら秒の小数は邪魔
    (3600, "1時間0分0秒"),
    (31285.7, "8時間41分25秒"),  # 実際に画面に出ていた値
])
def test_duration(seconds, expected):
    assert duration(seconds) == expected


def test_negative_keeps_sign():
    assert duration(-90) == "-1分30秒"


def test_none_is_dash():
    """値が無いことと 0 を混ぜない。"""
    assert duration(None) == "-"


@pytest.mark.parametrize("seconds,expected", [
    (0.4, "0.4s"),
    (45.24, "45.2s"),
    (312, "5m12s"),
    (3720, "1h02m"),
])
def test_compact(seconds, expected):
    """表の列に入れる短い形。★日本語にすると列幅を食う。"""
    assert compact_duration(seconds) == expected

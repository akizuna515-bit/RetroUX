"""まんたんの設定（2026-08-02 / 指示書 `input/260802_manatan.md`）。

★責務を分けてあります（指示書 §12）:

    settings.py    型付きの設定・既定値・表示名との対応
    validation.py  値の検証。⚠ 壊れていても止めず、既定値へ落として理由を残す
    repository.py  config/mantan.yaml の読み書き・同梱設定とのマージ・
                   書きかけを残さない保存
"""

from .repository import load, save
from .settings import (
    ANTIDOTE_POLICY_LABELS, HP_PERCENT_MAX, HP_PERCENT_MIN,
    ITEM_POLICIES, ITEM_POLICY_LABELS, MP_POLICIES, MP_POLICY_LABELS,
    SCHEMA_VERSION, SPELL_POLICIES, USER_PATH, MantanSettings, summary_lines,
)
from .validation import from_dict

__all__ = [
    "ANTIDOTE_POLICY_LABELS", "HP_PERCENT_MAX", "HP_PERCENT_MIN",
    "ITEM_POLICIES", "ITEM_POLICY_LABELS", "MP_POLICIES", "MP_POLICY_LABELS",
    "MantanSettings", "SCHEMA_VERSION", "SPELL_POLICIES", "USER_PATH",
    "from_dict", "load", "save", "summary_lines",
]

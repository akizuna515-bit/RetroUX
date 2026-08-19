"""まんたん設定の検証（2026-08-02 / 指示書 §4.2）。

★★ **壊れていても止めない。既定値へ落として、理由を残す。** ★★

  ⚠ まんたんの設定が1つ間違っているだけで RetroUX が起動できないのは
    筋が悪い（指示書 §4.2「アプリケーション全体を起動不能にしない」）。

  ★ただし**黙って直しません**。何をどう直したかを `problems` に残し、
    ログと画面に出します（プロジェクトの原則「失敗を黙って捨てない」）。
"""

from __future__ import annotations

from .settings import (
    BALANCE_WEIGHT_MAX,
    HP_PERCENT_MAX, HP_PERCENT_MIN, ITEM_POLICIES, MP_POLICIES,
    SPELL_POLICIES, MantanSettings,
)


def _pick_policy(value, allowed, fallback, label, problems):
    """許された値ならそのまま、違えば既定値へ落として理由を残す。"""
    if value is None:
        return fallback
    if not isinstance(value, str):
        problems.append(
            f"{label}は文字列で書いてください（{value!r} でした）。"
            f"既定の「{fallback}」を使います")
        return fallback
    if value not in allowed:
        problems.append(
            f"{label}に知らない値「{value}」がありました。"
            f"使えるのは {' / '.join(allowed)} です。"
            f"既定の「{fallback}」を使います")
        return fallback
    return value


def _pick_weight(value, fallback, problems):
    """★MP偏りの補正の重み。⚠ 負の値は「偏っている人を優先する」になります。"""
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(
            f"MP配分の重みは数値で書いてください（{value!r} でした）。"
            f"既定の {fallback} を使います")
        return fallback
    if value < 0 or value > BALANCE_WEIGHT_MAX:
        problems.append(
            f"MP配分の重み {value} は範囲外です（0〜{BALANCE_WEIGHT_MAX}）。"
            f"既定の {fallback} を使います")
        return fallback
    return float(value)


def _pick_percent(value, fallback, problems):
    """HP 割合。⚠ 0未満・100超・数値でない、をすべて拾う（指示書 §4.2）。"""
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(
            f"まんたん完了HPは数値で書いてください（{value!r} でした）。"
            f"既定の {fallback}% を使います")
        return fallback
    n = int(value)
    if n < HP_PERCENT_MIN or n > HP_PERCENT_MAX:
        problems.append(
            f"まんたん完了HP {n}% は範囲外です"
            f"（{HP_PERCENT_MIN}〜{HP_PERCENT_MAX}%）。"
            f"既定の {fallback}% を使います")
        return fallback
    return n


def _pick_bool(value, fallback, label, problems):
    if value is None:
        return fallback
    if not isinstance(value, bool):
        problems.append(
            f"{label}は「はい／いいえ」で書いてください（{value!r} でした）。"
            f"既定を使います")
        return fallback
    return value


def _section(data, name, problems):
    """入れ子の節を取り出す。⚠ 節が節でなければ**無かったことにする**。"""
    got = data.get(name)
    if got is None:
        return {}
    if not isinstance(got, dict):
        problems.append(f"{name} の書き方が違います。既定値を使います")
        return {}
    return got


def from_dict(data, base: MantanSettings | None = None):
    """辞書から設定を作る。★読めない項目は `base`（既定）で埋める。

    戻り値は `(設定, 気づいたことの一覧)`。
    ⚠ 例外を投げません。**呼ぶ側が起動できなくなるのを避けるため**。
    """
    base = base or MantanSettings()
    problems: list[str] = []

    if data is None:
        return base, problems
    if not isinstance(data, dict):
        return base, ["設定の中身が読めませんでした。既定値で動きます"]

    version = data.get("schema_version")
    if version is not None and version != 1:
        problems.append(
            f"知らない schema_version {version!r} です。"
            "この版が読める形として扱います")

    items = _section(data, "items", problems)
    herb = _section(items, "herb", problems)
    antidote = _section(items, "antidote", problems)
    mp_alloc = _section(data, "mp_allocation", problems)
    spells = _section(data, "healing_spells", problems)
    poison = _section(data, "poison_cure", problems)
    reserve = _section(data, "mp_reserve", problems)

    return MantanSettings(
        target_hp_percent=_pick_percent(
            data.get("target_hp_percent"), base.target_hp_percent, problems),
        herb_policy=_pick_policy(
            herb.get("policy"), ITEM_POLICIES, base.herb_policy,
            "やくそうの使い方", problems),
        antidote_policy=_pick_policy(
            antidote.get("policy"), ITEM_POLICIES, base.antidote_policy,
            "どくけしそうの使い方", problems),
        mp_policy=_pick_policy(
            mp_alloc.get("policy"), MP_POLICIES, base.mp_policy,
            "MP配分", problems),
        mp_balance_weight=_pick_weight(
            mp_alloc.get("balance_weight"), base.mp_balance_weight, problems),
        healing_spells_enabled=_pick_bool(
            spells.get("enabled"), base.healing_spells_enabled,
            "回復呪文を使うか", problems),
        spell_policy=_pick_policy(
            spells.get("selection_policy"), SPELL_POLICIES, base.spell_policy,
            "回復呪文の選び方", problems),
        poison_cure_enabled=_pick_bool(
            poison.get("enabled"), base.poison_cure_enabled,
            "解毒するか", problems),
        use_tactics_reserve=_pick_bool(
            reserve.get("use_tactics_profile"), base.use_tactics_reserve,
            "戦術プロフィールの最低残存MPを使うか", problems),
    ), problems

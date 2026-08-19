"""ユーザー指定戦略（custom_1）の固定行動を、人が読める形で返す。

2026-08-11 / UI整理 Phase 5（戦略に直結する設定画面 / 表示のみ）。

★★ ここに置く理由（指示書§13）★★
  戦略の**構造**は Core（`core/strategy/models.py`）にあるが、中身の
  既定データ（「ちからのたて」= ROM のアイテムID 0x1D）は **DQ2 プラグイン**
  が持つ。Core にアイテム名・キャラ名を入れない。

★この窓は**読むだけ**。編集・保存はしない（依頼者の判断 / Phase 5）。
  出典は `config.yaml` の `user_strategies` と `memory_map.yaml` の `items`。
"""

from __future__ import annotations

import pathlib

import yaml

_HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str) -> dict:
    """プラグイン配下の YAML を読む。★読めなければ空 dict。"""
    try:
        data = yaml.safe_load((_HERE / name).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _item_names() -> dict:
    """`{item_id(int): 名前}`。★YAML の `0x1D:` は int 29 として読まれる。"""
    items = _load("memory_map.yaml").get("items")
    return items if isinstance(items, dict) else {}


def _profile(strategy_id: str = "custom_1") -> dict:
    us = _load("config.yaml").get("user_strategies")
    if not isinstance(us, dict):
        return {}
    prof = us.get(strategy_id)
    return prof if isinstance(prof, dict) else {}


def strategy_name(strategy_id: str = "custom_1") -> str:
    """固定戦略の名前（例: ちからのたて）。★無ければ汎用名。"""
    return str(_profile(strategy_id).get("name") or "ユーザー指定1")


def fixed_action_lines(strategy_id: str = "custom_1") -> list:
    """`[(キャラ表示名, 行動の説明)]` を返す。★読めなければ空。

    例: [("ローレシア", "たたかう"),
         ("サマルトリア", "どうぐ：ちからのたて"),
         ("ムーンブルク",  "どうぐ：ちからのたて")]
    """
    # ⚠ キャラの並び・表示名は Core の1箇所から取る（DQ2 側で写さない）。
    from ...core.tactics import models

    actors = _profile(strategy_id).get("actors")
    if not isinstance(actors, dict):
        return []
    names = _item_names()
    out = []
    for cid in models.CHARACTER_IDS:
        label = models.CHARACTER_LABELS.get(cid, cid)
        spec = actors.get(cid)
        if not isinstance(spec, dict):
            out.append((label, "—（指定なし＝AI にまかせる）"))
            continue
        action = spec.get("action")
        if action == "attack":
            out.append((label, "たたかう"))
        elif action == "item":
            iid = spec.get("item")
            if isinstance(iid, int):
                item = names.get(iid) or f"0x{iid:02X}"
            else:
                item = str(iid)
            out.append((label, f"どうぐ：{item}"))
        else:
            out.append((label, str(action)))
    return out

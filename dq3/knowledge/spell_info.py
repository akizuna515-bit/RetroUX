"""呪文の知識（RX3-0125 / 2026-09-08）— ★ROM の表を、画面と AI が使える形に。

```text
dq3rom/spells.py        ★消費 MP / 対象 / 種別 / 威力（★ROM の表そのまま）
dq3rom/spell_flags.py   ★誰が何を覚えているか（★$078C の bit + $A2BA のブロック）
ここ                    ★名前を添えて、`state.json` の 1 人ぶんから「使える呪文」を出す
```

⚠⚠ 画面（`dq3/ui/`）は `dq3rom` を直に触りません（`test_UIはROMの正解を読まない`）。
★番地とビットの意味はここで引き受けます。
"""
from __future__ import annotations

import dataclasses
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

_cache: dict | None = None
_tried = False
last_error: str | None = None


def _load(rom_path=None) -> dict | None:
    """★1 度だけ読む（⚠ ROM が無ければ None。★理由は `last_error`）。"""
    global _cache, _tried, last_error
    if _tried and rom_path is None:
        return _cache
    _tried = True
    try:
        from dq3rom import profile as P
        from dq3rom import spell_flags as SF
        from dq3rom import spells as SP
        from . import rom_names as RN

        target = pathlib.Path(rom_path) if rom_path else RN.DEFAULT_ROM
        if not target.exists():
            last_error = "ROM がありません: %s" % target
            _cache = None
            return None
        prg = P.load_and_identify(target).rom.prg
        rows = SP.read_all(prg)
        if not rows:
            last_error = "呪文の表が見つかりません（★署名が一致しない）"
            _cache = None
            return None
        _cache = {"spells": {s.spell_id: s for s in rows},
                  "blocks": SF.blocks(prg)}
        last_error = None
    except Exception as exc:                          # noqa: BLE001 - ★理由を残す
        last_error = "呪文の表を読めません: %s" % exc
        _cache = None
    return _cache


def available(rom_path=None) -> bool:
    return _load(rom_path) is not None


def reset() -> None:
    global _cache, _tried, last_error
    _cache, _tried, last_error = None, False, None


@dataclasses.dataclass(frozen=True)
class SpellInfo:
    """★画面に出せる形（⚠ 名前は実行時に ROM から）。"""

    spell_id: int
    name: str | None
    mp: int
    target: str
    kind: str
    scope: str | None
    effect: str | None
    resist: str | None
    avg: float | None

    @property
    def label(self) -> str:
        return self.name or "呪文 %d" % self.spell_id


def info(spell_id, rom_path=None) -> SpellInfo | None:
    got = _load(rom_path)
    if got is None:
        return None
    s = got["spells"].get(int(spell_id))
    if s is None:
        return None
    from . import rom_names as RN

    return SpellInfo(spell_id=s.spell_id, name=RN.spell(s.spell_id, rom_path), mp=s.mp,
                     target=s.target, kind=s.kind, scope=s.scope, effect=s.effect,
                     resist=s.resist, avg=s.avg)


def all_spells(rom_path=None) -> list[SpellInfo]:
    got = _load(rom_path)
    if got is None:
        return []
    return [info(i, rom_path) for i in sorted(got["spells"])]


def learned_for(member: dict, rom_path=None, *, battle_only: bool = True) -> list[int]:
    """★`state.json` の 1 人ぶん（`spells` 8 バイト + `class_gender`）→ 呪文 ID。

    ⚠ `spells` が届いていなければ**空**（★推測で「覚えている」ことにしない）。
    """
    got = _load(rom_path)
    if got is None or not isinstance(member, dict):
        return []
    raw = member.get("spells")
    if not raw or len(raw) < 8:
        return []
    from dq3rom import spell_flags as SF
    from . import item_info as II

    class_id, _female = II.split_class_gender(member.get("class_gender"))
    try:
        return SF.learned_ids(bytes(int(b) & 0xFF for b in raw[:8]), class_id or 0,
                              got["blocks"], battle_only=battle_only)
    except (TypeError, ValueError):
        return []


def castable(member: dict, rom_path=None) -> list[SpellInfo]:
    """★覚えていて、⚠ **いまの MP で唱えられる**戦闘呪文。"""
    mp = int(member.get("mp") or 0) if isinstance(member, dict) else 0
    out = []
    for sid in learned_for(member, rom_path):
        got = info(sid, rom_path)
        if got is not None and got.mp <= mp and got.kind != "field":
            out.append(got)
    return out


def lua_table(rom_path=None) -> dict:
    """★Lua へ渡す形（`work/generated/dq3_ai.lua` の `spells` / `blocks`）。"""
    got = _load(rom_path)
    if got is None:
        return {"spells": {}, "blocks": []}
    return {"spells": {sid: s.to_lua() for sid, s in got["spells"].items()},
            "blocks": [list(b) for b in got["blocks"]]}


__all__ = ["SpellInfo", "info", "all_spells", "learned_for", "castable", "lua_table",
           "available", "reset"]

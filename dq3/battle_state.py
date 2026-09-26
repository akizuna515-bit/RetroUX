"""DQ3 の戦闘の状態 ― Python 側の 1 か所（RX3-0166 / 2026-09-11）。

★Lua 側の `dq3/phase0/battle_state.lua` と**同じ式**です（⚠ 番地は profile が正本）。

```text
戦闘中（DQ3 自身の式 / 固定バンク $C8F8）   $32 == $FD かつ $60B7 & $20
段階                                        NONE / ENTERING / ACTIVE / RESULT / EXITING
                                            （★曲 $06F0 = 番号×2 を足して分ける）
```

⚠⚠ `$62` でも画面のマス数でも決めません（★RX3-0165 で両方外れた /
`docs/research/dq3-battle-state-research.md`）。

★使う所: セーブステートの場面（`dq3/testing/fixtures.py`）/ 生成（`dq3/phase0/generate_lua.py`）。
"""
from __future__ import annotations

import dataclasses
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"

NONE, ENTERING, ACTIVE, RESULT, EXITING = "NONE", "ENTERING", "ACTIVE", "RESULT", "EXITING"
PHASES = (NONE, ENTERING, ACTIVE, RESULT, EXITING)


def _hex(value) -> int:
    """★`"0x60B7"` でも `24759` でも受ける（⚠ 10 進を 16 進で読む事故を起こさない）。"""
    return value if isinstance(value, int) else int(str(value), 16)


@dataclasses.dataclass(frozen=True)
class Spec:
    """★戦闘の状態を読む番地（⚠ profile の `runtime.in_battle`）。"""

    mode: int = 0x0032
    mode_battle: int = 0xFD
    flags: int = 0x60B7
    flag_bit: int = 0x20
    track: int = 0x06F0
    battle_tracks: tuple = (0x10, 0x12)

    def as_lua(self) -> dict:
        """★生成物（`dq3_phase0.lua` の `battle_state`）へ渡す形。"""
        return {"mode": self.mode, "mode_battle": self.mode_battle, "flags": self.flags,
                "flag_bit": self.flag_bit, "track": self.track,
                "battle_tracks": list(self.battle_tracks)}


def spec_from_profile(profile: dict | None = None) -> Spec:
    """★profile から番地を読む。⚠ 旧い形（`address` だけ = `$62`）は**受けない**。"""
    if profile is None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    row = ((profile.get("runtime") or {}).get("in_battle") or {})
    if "mode" not in row or "flags" not in row:
        raise ValueError("⚠ profile の runtime.in_battle が旧い形です（★$32 / $60B7 が要る）")
    return Spec(mode=_hex(row["mode"]), mode_battle=_hex(row["mode_battle"]),
                flags=_hex(row["flags"]), flag_bit=_hex(row["flag_bit"]),
                track=_hex(row["track"]),
                battle_tracks=tuple(_hex(v) for v in row.get("battle_tracks") or ()))


def classify(mode: int, flags: int, track_raw: int, spec: Spec | None = None) -> str:
    """★3 つのバイトから段階を決める（⚠ Lua の `BattleState.classify` と同じ）。"""
    s = spec or Spec()
    bit5 = bool(flags & s.flag_bit)
    screen = mode == s.mode_battle
    music = (track_raw >> 1) in s.battle_tracks
    if bit5 and screen:
        return ACTIVE if music else RESULT
    if screen:
        return EXITING
    return ENTERING if music else NONE


def is_in_battle(mode: int, flags: int, spec: Spec | None = None) -> bool:
    """★DQ3 自身の式（ACTIVE と RESULT）。"""
    s = spec or Spec()
    return mode == s.mode_battle and bool(flags & s.flag_bit)


def _byte(ram: bytes, wram: bytes, addr: int) -> int:
    """★内蔵 RAM（$0000-$07FF）と WRAM（$6000-$7FFF）を番地で引く。⚠ 読めなければ 0。"""
    if 0 <= addr < len(ram):
        return ram[addr]
    if 0x6000 <= addr < 0x6000 + len(wram):
        return wram[addr - 0x6000]
    return 0


def of_memory(ram: bytes, wram: bytes, spec: Spec | None = None) -> dict:
    """★RAM と WRAM から、戦闘中か と 段階 を出す（★セーブステート用）。"""
    s = spec or Spec()
    mode, flags = _byte(ram, wram, s.mode), _byte(ram, wram, s.flags)
    track = _byte(ram, wram, s.track)
    return {"in_battle": is_in_battle(mode, flags, s),
            "battle_phase": classify(mode, flags, track, s)}


__all__ = ["Spec", "spec_from_profile", "classify", "is_in_battle", "of_memory",
           "NONE", "ENTERING", "ACTIVE", "RESULT", "EXITING", "PHASES"]

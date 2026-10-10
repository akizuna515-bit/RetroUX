"""物語の旗（RX3-0210 / RX3-0211 / 2026-09-12）。★RAM の旗を、人が書いた表（`data/dq3/story-flags.csv`）で意味づける。

★★ ノアニールの眠り（`docs/research/260912_dq3-noaniel-sleep.md`）★★

```text
ROM 13:B20E  map が 11 / 120 かつ `$60B7` bit2 = 0 → 全員「ぐうぐう‥‥。」（★talk_id は同じ / 表の差し替えではない）
ROM 6:B666   bit2 を立てる唯一の所（★めざめのこなの「つかう」とみられる / HYPOTHESIS）
```

★Lua（dev.lua）が `$60B7` を state.json の `story_60b7` で渡す。

★★ 船を手に入れた（RX3-0249 / 2026-09-13 依頼者「黒こしょうと船が、船入手したが、クリアされない」）★★

```text
ROM 13:BC79  `$60B8` bit7 が立っていれば別の台詞 → 13:BC81 くろこしょう(79) を持っているか → 13:BC88 渡す
             → 13:BC8B `ORA #$C0` で bit6・bit7 を立てる（★bit7 を立てるのはここだけ / bit6 はほかで消える）
```
★Lua（dev.lua）が `$60B8` を `story_60b8` で渡す（★意味は表の ship_obtained）。
⚠ 旗の意味は表に書く（★推測しない / 一度立ったら覚えるのは progress）。
"""

from __future__ import annotations

import csv
import dataclasses
import io
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
FLAGS_PATH = ROOT / "data" / "dq3" / "story-flags.csv"

#: ★眠りの村（★ノアニール = 11 / その小部屋 = 120 / ROM 13:B20E）
SLEEP_MAPS = frozenset({11, 120})
#: ★目覚めた印（`$60B7` の bit2）
AWAKE_ADDRESS, AWAKE_BIT = 0x60B7, 2
#: ★眠っている / 起きている（★heard の記録に残す段階）
ASLEEP, AWAKE = "asleep", "awake"
#: ★眠りの台詞（⚠ 飾りを落とすとこれだけになる）
SLEEP_LINE = "ぐうぐう"


#: ★「この敵を倒した」を意味する旗（RX3-0451 / 2026-09-28）
#:
#:   ⚠⚠ ボスの撃破は**戦闘の記録だけでは取りこぼします**（★経験値 0 / 姿が変わる）。
#:   ★ゲーム自身の旗があるものは、それも「倒した」の証拠にします。
#:   ⚠ 勇者メモには `倒した: <敵の名前>` と書くだけでよく、★RAM 番地も id も書きません。
#:   ⚠ 旗が**確かめられているものだけ**を入れます（★推測で増やさない）。
#:     ゾーマには永続する旗がありません（★逆アセンブルで確認 / RX3-0447）。
DEFEAT_FLAGS: dict[str, str] = {"バラモス": "baramos_defeated"}


def defeat_flag_of(monster_name: str, flags=None) -> str | None:
    """★その敵の「倒した」を意味する旗（⚠ 無ければ None / 表に無ければ None）。"""
    want = DEFEAT_FLAGS.get(str(monster_name or "").strip())
    if not want:
        return None
    known = {f.flag_id for f in (flags if flags is not None else load_flags())}
    return want if want in known else None


def state_key(address: int) -> str:
    """★state.json の欄の名前（★`story_60b7` / ⚠ DQ2 の reader の欄とぶつけない）。"""
    return "story_%04x" % int(address)


@dataclasses.dataclass(frozen=True)
class StoryFlag:
    flag_id: str
    address: int
    bit: int
    label: str
    evidence: str = ""


def load_flags(path=None) -> list[StoryFlag]:
    """★旗の表（⚠ 無ければ空）。"""
    target = pathlib.Path(path) if path else FLAGS_PATH
    got: list[StoryFlag] = []
    try:
        with io.open(target, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    got.append(StoryFlag(row["flag_id"].strip(), int(row["address"], 0), int(row["bit"]),
                                         (row.get("label") or "").strip(), (row.get("evidence") or "").strip()))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return got


def flags_set(state, flags=None) -> set[str]:
    """★state.json から、いま立っている旗の flag_id（⚠ 読めない欄は数えない）。"""
    out: set[str] = set()
    for flag in (flags if flags is not None else load_flags()):
        raw = (state or {}).get(state_key(flag.address))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value & (1 << flag.bit):
            out.add(flag.flag_id)
    return out


def label_of(flag_id: str, flags=None) -> str | None:
    for flag in (flags if flags is not None else load_flags()):
        if flag.flag_id == flag_id:
            return flag.label or flag.flag_id
    return None


def phase_of(map_id, value) -> str | None:
    """★眠りの村なら ASLEEP / AWAKE（⚠ ほかの map・読めないときは None = 段階を問わない）。"""
    try:
        if int(map_id) not in SLEEP_MAPS or value is None:
            return None
        return AWAKE if int(value) & (1 << AWAKE_BIT) else ASLEEP
    except (TypeError, ValueError):
        return None


def is_sleep_text(text) -> bool:
    """★眠りの台詞だけか（「＊「ぐうぐう‥‥。」）。"""
    core = re.sub(r"[＊「」‥…・。、！\s]", "", str(text or ""))
    return core == SLEEP_LINE


__all__ = ["FLAGS_PATH", "SLEEP_MAPS", "ASLEEP", "AWAKE", "StoryFlag", "load_flags", "flags_set", "label_of",
           "phase_of", "is_sleep_text", "state_key"]
